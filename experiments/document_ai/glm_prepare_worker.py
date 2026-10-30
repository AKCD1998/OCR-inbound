"""HQ-only, supervised GLM artifacts/runtime preparation. Never reads invoices."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse
import zipfile

from component_common import checked,pin,read,require_HQ,RESOURCES,save,verify_admission

CONTRACT='document-ai-glm-materialize.v1'
MAX_DOWNLOAD_BYTES=2_000_000_000
ALLOWED_HOSTS={'huggingface.co','github.com','files.pythonhosted.org'}


def validated_artifact(value):
    if (not isinstance(value,dict) or set(value)!={'role','filename','url','bytes','sha256'}
      or value['role'] not in ('decoder','projector','backend','pillow','psutil')
      or type(value['bytes']) is not int or not 0<value['bytes']<=MAX_DOWNLOAD_BYTES
      or not isinstance(value['filename'],str) or Path(value['filename']).name!=value['filename']
      or value['filename'] in ('.','..')
      or any(c in value['filename'] for c in ('/', '\\', ':'))
      or not isinstance(value['sha256'],str) or len(value['sha256'])!=64
      or any(c not in '0123456789abcdef' for c in value['sha256'])):
        raise ValueError('Explicit bounded source artifact required')
    url=urlparse(value['url'])
    if url.scheme!='https' or url.hostname not in ALLOWED_HOSTS or url.username or url.password:
        raise ValueError('Pinned public artifact host required')
    return value


def download(artifact,folder,progress):
    a=validated_artifact(artifact);dest=folder/a['filename'];partial=dest.with_name(dest.name+'.partial')
    if dest.exists() or partial.exists():raise FileExistsError('Preserve prior download attempt')
    count=0;digest=hashlib.sha256();began=time.monotonic();last=began
    request=urllib.request.Request(a['url'],headers={'User-Agent':'OCR-Inbound-Isolated-GLM-Experiment/1'})
    with urllib.request.urlopen(request,timeout=45) as response,partial.open('xb') as stream:
        while True:
            data=response.read(1048576)
            if not data:break
            count+=len(data)
            if count>a['bytes']:raise ValueError('Artifact exceeds pinned size')
            stream.write(data);digest.update(data)
            if time.monotonic()-last>5:
                progress('DOWNLOAD_PROGRESS',role=a['role'],downloaded_bytes=count,total_bytes=a['bytes']);last=time.monotonic()
        stream.flush();os.fsync(stream.fileno())
    if count!=a['bytes'] or digest.hexdigest()!=a['sha256']:raise ValueError('Downloaded artifact size/SHA differs')
    partial.rename(dest)
    return {'role':a['role'],'file':pin(dest),'bytes':count,'elapsed_seconds':time.monotonic()-began,
            'upstream_url':a['url'],'verified_sha256':digest.hexdigest()}


def extract_backend(archive,target):
    if target.exists():raise FileExistsError('Preserve backend extraction')
    target.mkdir();records=[]
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist()
        if len(entries)>1000 or sum(v.file_size for v in entries)>300_000_000:
            raise ValueError('Backend archive exceeds finite extraction budget')
        seen=set()
        for info in entries:
            name=info.filename.replace('\\','/');dest=(target/name).resolve()
            parts=name.rstrip('/').split('/');key=str(dest).casefold()
            if (':' in name or not dest.is_relative_to(target.resolve())
              or any(part in ('.','..') or part!=part.rstrip('. ') for part in parts)
              or key in seen
              or ((info.external_attr>>16)&0o170000)==0o120000):
                raise ValueError('Archive traversal/alias/duplicate/symlink refused')
            seen.add(key)
        z.extractall(target)
    for item in sorted(target.rglob('*')):
        if item.is_file():records.append({'relative_path':str(item.relative_to(target)),'pin':pin(item)})
    server=list(target.rglob('llama-server.exe'));quant=list(target.rglob('llama-quantize.exe'))
    if len(server)!=1 or len(quant)!=1:raise ValueError('One actual server and quantizer required')
    return {'files':records,'server':pin(server[0]),'quantizer':pin(quant[0])}


def run_child(argv,folder,label,timeout,accepted_exit_codes=(0,)):
    stdout=folder/(label+'.stdout.log');stderr=folder/(label+'.stderr.log');began=time.monotonic()
    env=dict(os.environ,**{k:'1' for k in ('OMP_NUM_THREADS','OMP_THREAD_LIMIT','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')})
    env.pop('PYTHONPATH',None)
    with stdout.open('xb') as out,stderr.open('xb') as err:
        result=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,
                              timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    receipt={'actual_argv':argv,'exit_code':result.returncode,'stdout':pin(stdout),'stderr':pin(stderr),
             'elapsed_seconds':time.monotonic()-began}
    save(folder/(label+'.child.json'),receipt)
    if result.returncode not in accepted_exit_codes:raise RuntimeError('Preparation child failed: '+label)
    return receipt


def materialize(config,output):
    require_HQ()
    if (config.get('contract')!=CONTRACT or config.get('resource_policy')!=RESOURCES
      or config.get('production_activation') is not False or config.get('optimizer_updates_allowed') is not False
      or config.get('source_image_decodes_allowed') is not False):raise ValueError('Root isolated GLM materialization policy required')
    deadline=datetime.fromisoformat(config['cutoff_utc']).timestamp()
    if type(config['maximum_seconds']) is not int or not 0<config['maximum_seconds']<=1800:
        raise ValueError('Bounded materialization duration required')
    if datetime.now(timezone.utc).timestamp()+config['maximum_seconds']+120>deadline:
        raise ValueError('Materialization would cross clock-out boundary')
    artifacts=[validated_artifact(x) for x in config['artifacts']]
    if sorted(x['role'] for x in artifacts)!=['backend','decoder','pillow','projector','psutil']:
        raise ValueError('Exact backend/decoder/vision/two isolated dependencies required')
    root=Path(config['target_root']).resolve();allowed=Path(r'D:\OCR-Experiments\document-ai-20261028\glm-ocr-20261030').resolve()
    if not root.is_relative_to(allowed) or root==allowed or root.exists():raise ValueError('New isolated GLM target required')
    if (output.resolve()!=Path(config['output_root']).resolve() or not output.resolve().is_relative_to(allowed)
      or output.resolve().is_relative_to(root)):raise ValueError('Exact isolated worker output required')
    root.mkdir(parents=True);output.mkdir(parents=True,exist_ok=False);began=time.monotonic()
    end=min(began+config['maximum_seconds'],began+deadline-datetime.now(timezone.utc).timestamp())
    def progress(phase,**values):
        if time.monotonic()>=end:raise TimeoutError('Finite preparation/clock-out deadline')
        with (output/'PROGRESS.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'phase':phase,'elapsed_seconds':time.monotonic()-began,
                                     'utc':datetime.now(timezone.utc).isoformat(),**values})+'\n');stream.flush()
    progress('STARTED',model_calls=0,image_decodes=0)
    def child(argv,label,seconds,accepted=(0,)):
        progress('CHILD_START',label=label)
        return run_child(argv,output,label,max(.1,min(seconds,end-time.monotonic())),accepted)
    downloaded=[];sources={x['role']:x for x in artifacts}
    for role in ('backend','pillow','psutil'):
        progress('DOWNLOAD_STARTED',role=role)
        downloaded.append(download(sources[role],root,progress))
    by_role={x['role']:x for x in downloaded}
    backend=extract_backend(checked(by_role['backend']['file']),root/'backend')
    version=child([backend['server']['path'],'--version'],'server_version',60)
    version_text=checked(version['stdout']).read_text(encoding='utf-8',errors='replace')+checked(version['stderr']).read_text(encoding='utf-8',errors='replace')
    if '11998' not in version_text or '78feec' not in version_text:raise ValueError('Actual binary build differs from selected b11998')
    help_result=child([backend['quantizer']['path'],'--help'],'quantizer_help',60,(0,1))
    help_text=checked(help_result['stdout']).read_text(encoding='utf-8',errors='replace')+checked(help_result['stderr']).read_text(encoding='utf-8',errors='replace')
    if '--max-buffer-size' not in help_text or '--allow-requantize' not in help_text:
        raise ValueError('Actual quantizer does not expose reviewed bounded-buffer/requantization options')
    # A fresh venv keeps GLM dependency resolution separate from Paddle/Docling.
    runtime=root/'runtime'
    child([sys.executable,'-X','utf8','-B','-m','venv',str(runtime)],'create_isolated_runtime',180)
    python=runtime/'Scripts/python.exe'
    install=child([str(python),'-I','-m','pip','install','--no-index','--no-deps','--disable-pip-version-check',
                   by_role['psutil']['file']['path'],by_role['pillow']['file']['path']],'install_two_pinned_wheels',180)
    code=("import importlib.metadata as m,json,sys;names=['psutil','Pillow','paddlepaddle','paddleocr','torch','docling','transformers'];"
          "d={};exec(\"for n in names:\\n try:d[n]=m.version(n)\\n except m.PackageNotFoundError:d[n]=None\");"
          "print(json.dumps({'prefix':sys.prefix,'packages':d}))")
    probe=child([str(python),'-I','-c',code],'isolated_runtime_probe',60)
    observed=json.loads(checked(probe['stdout']).read_text(encoding='utf-8-sig'))
    expected={'psutil':'7.2.2','Pillow':'12.3.0','paddlepaddle':None,'paddleocr':None,'torch':None,'docling':None,'transformers':None}
    if observed['packages']!=expected or Path(observed['prefix']).resolve()!=runtime.resolve():raise ValueError('Runtime is not isolated with exact selected dependencies')
    for role in ('projector','decoder'):
        progress('DOWNLOAD_STARTED',role=role)
        downloaded.append(download(sources[role],root,progress))
    result={'contract':CONTRACT,'status':'COMPLETE','component':'glm-materialize','executed':True,
            'worker':pin(__file__),'config':config['config_pin'],'artifacts':downloaded,'backend':backend,
            'isolated_python':pin(python),'runtime_probe':probe,'runtime_packages':observed,
            'server_version':version,'quantizer_help':help_result,'dependency_install':install,
            'model_calls':0,'quantization_calls':0,'source_image_decodes':0,'optimizer_updates':0,
            'baseline_cache_modified':False,'production_activation':False,'elapsed_seconds':time.monotonic()-began}
    progress('COMPLETE')
    save(output/'SUMMARY.json',result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--output',required=True);p.add_argument('--admission',required=True);p.add_argument('--admission-sha256',required=True);a=p.parse_args()
    cfg_pin={'path':a.config,'sha256':a.config_sha256};cfg=read(checked(cfg_pin))
    verify_admission(a.admission,a.admission_sha256,__file__,'glm-materialize')
    materialize({**cfg,'config_pin':cfg_pin},Path(a.output))


if __name__=='__main__':main()
