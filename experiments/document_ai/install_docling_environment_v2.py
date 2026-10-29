"""Repair V1 package-resolution wait using pinned local CPU wheels and traces.

Creates a NEW isolated environment. The retained V1 wheel/environment are read
only. The first probe has no index/network/dependencies; no timeout is extended.
Only a subsequent successful full URL/SHA256 resolution permits installation.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse,unquote,parse_qs
from urllib.request import urlopen,Request
from component_common import read,pin,save,verify_admission

HASH_READ_BYTES=8*1024*1024

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(HASH_READ_BYTES):digest.update(block)
    return digest.hexdigest()

def direct_requirements(spec):
    result=[]
    for line in spec['primary_requirements']:
        if ' @ ' not in line:continue
        name,url=line.split(' @ ',1);parsed=urlparse(url);digest=parse_qs(parsed.fragment).get('sha256',[None])[0]
        if parsed.scheme!='https' or parsed.hostname not in spec['allowed_artifact_hosts'] or not digest or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Publisher URL/SHA256 required')
        filename=unquote(parsed.path.rsplit('/',1)[-1])
        if Path(filename).name!=filename or not filename.endswith('.whl'):raise ValueError('Safe binary wheel filename required')
        result.append({'name':name,'upstream_url':url,'sha256':digest,'filename':filename})
    if {x['name'] for x in result}!={'torch','torchvision'}:raise ValueError('Exactly the two pinned CPU-wheel requirements required')
    return result

def lock_resolution(report,spec,local_wheels,archive_sizes=None):
    allowed={x['file_url']:x for x in local_wheels};resolved=[];total=0
    for item in report.get('install',[]):
        info=item['download_info'];url=info['url'];u=urlparse(url);digest=info.get('archive_info',{}).get('hashes',{}).get('sha256')
        if not digest or not re.fullmatch('[0-9a-f]{64}',digest) or not unquote(u.path).endswith('.whl'):raise ValueError('Only hash-pinned binary packages')
        local=allowed.get(url)
        if u.scheme=='file':
            if local is None or local['sha256']!=digest:raise ValueError('File wheel not in verified CPU materialization')
            if sha(local['path'])!=digest:raise ValueError('Local CPU wheel changed during resolution')
            size=local['bytes']
        elif u.scheme=='https' and u.hostname in spec['allowed_artifact_hosts']:
            if archive_sizes is not None:size=archive_sizes[url]
            else:
                with urlopen(Request(url,method='HEAD'),timeout=15) as response:size=int(response.headers.get('Content-Length','0'))
        else:raise ValueError('Unapproved package source')
        if size<=0:raise ValueError('Package byte size not established')
        auxiliary=spec.get('publisher_auxiliary_packages',{}).get(item['metadata']['name'].casefold().replace('_','-'))
        if auxiliary and (item['metadata']['version']!=auxiliary['version'] or digest!=auxiliary['sha256'] or size!=auxiliary['bytes']):raise ValueError('Pinned auxiliary package publisher bytes differ')
        total+=size
        if total>spec['maximum_resolved_download_bytes']:raise ValueError('Resolved package budget exceeded')
        resolved.append({'name':item['metadata']['name'],'version':item['metadata']['version'],'url':url,'sha256':digest,'bytes':size,
                         'upstream_url':local['upstream_url'] if local else url})
    if not resolved:raise ValueError('Empty resolution')
    return sorted(resolved,key=lambda x:x['name'].casefold())

def materialize_cpu_wheels(spec,root,retained):
    wheels=[];downloaded=0
    for requirement in direct_requirements(spec):
        if requirement['name']=='torch' and retained is not None:
            path=retained.resolve()
            if path.drive.upper()!='D:' or 'OCR-Experiments' not in path.parts or path.name!=requirement['filename']:raise ValueError('Exact retained experiment CPU Torch wheel required')
            if sha(path)!=requirement['sha256']:raise ValueError('Retained Torch wheel does not match publisher SHA256')
            reused=True
        else:
            path=root/'bootstrap_wheels'/requirement['filename'];path.parent.mkdir(exist_ok=True)
            partial=path.with_name(path.name+'.partial');count=0
            with urlopen(requirement['upstream_url'],timeout=15) as response,partial.open('xb') as stream:
                while block:=response.read(HASH_READ_BYTES):
                    count+=len(block)
                    if count>spec['maximum_resolved_download_bytes']:raise ValueError('CPU wheel exceeds package budget')
                    stream.write(block)
            expected_size=spec.get('publisher_CPU_wheel_bytes',{}).get(requirement['name'])
            if expected_size is not None and count!=expected_size:raise ValueError('CPU wheel publisher byte length differs')
            if sha(partial)!=requirement['sha256']:raise ValueError('Downloaded CPU torchvision hash differs')
            partial.rename(path);downloaded+=count;reused=False
        wheels.append({**requirement,**pin(path),'file_url':path.as_uri(),'bytes':path.stat().st_size,'reused_retained_bytes':reused})
    return wheels,downloaded

def execute(a):
    verify_admission(a.admission,a.admission_sha256,__file__,'docling-install')
    if sha(a.environment_spec)!=a.environment_spec_sha256:raise ValueError('Spec changed')
    if sha(a.pip_runner)!=a.pip_runner_sha256:raise ValueError('Trace runner changed')
    spec=read(a.environment_spec);direct_requirements(spec)
    if sys.version_info[:2]!=(3,11) or platform.machine().casefold() not in ('amd64','x86_64'):raise ValueError('Pinned cp311 Windows wheels only')
    root=a.environment_root.resolve()
    if root.drive.upper()!='D:' or 'OCR-Experiments' not in root.parts or 'runtime' in root.parts or root.exists():raise ValueError('NEW isolated D experiment environment required')
    if shutil.disk_usage(root.parent).free<spec['minimum_free_disk_bytes_before_setup']:raise ValueError('Disk setup gate')
    root.mkdir();logs=root/'setup_logs';logs.mkdir();(root/'tmp').mkdir()
    env=dict(os.environ,TEMP=str(root/'tmp'),TMP=str(root/'tmp'),PYTHONNOUSERSITE='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_NO_INPUT='1')
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    steps=[];began=time.monotonic();phase=0
    faulthandler.enable();faulthandler.dump_traceback_later(20,repeat=True)
    def mark(label):
        nonlocal phase
        phase+=1;save(root/(str(phase).zfill(2)+'-'+label+'.json'),{'phase':label,'elapsed_seconds':time.monotonic()-began,'utc':datetime.now(timezone.utc).isoformat()})
    def run(name,argv,seconds):
        out=logs/(name+'.stdout.log');err=logs/(name+'.stderr.log');start=time.monotonic();result=None;failure=None
        try:
            with out.open('xb') as stdout,err.open('xb') as stderr:
                result=subprocess.run(argv,env=env,stdout=stdout,stderr=stderr,shell=False,timeout=seconds,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise RuntimeError('Setup step exit '+str(result.returncode)+': '+name)
        except BaseException as exc:failure={'type':type(exc).__name__,'message':str(exc)};raise
        finally:
            record={'name':name,'elapsed_seconds':time.monotonic()-start,'timeout_seconds':seconds,'exit_code':None if result is None else result.returncode,
                    'failure':failure,'stdout':pin(out) if out.exists() else None,'stderr':pin(err) if err.exists() else None}
            save(root/(name+'.resource.json'),record);steps.append(record)
    try:
        mark('VERIFY_RETAINED_CPU_WHEEL_STARTED');wheels,downloaded=materialize_cpu_wheels(spec,root,a.retained_torch_wheel);save(root/'CPU_WHEEL_MATERIALIZATION.json',{'wheels':wheels,'downloaded_bytes':downloaded,'model_imports':0});mark('CPU_WHEELS_PINNED')
        bootstrap=None
        if spec.get('bootstrap_pip'):
            asset=spec['bootstrap_pip'];path=Path(sys.base_prefix)/'Lib'/'ensurepip'/'_bundled'/asset['filename']
            if path.stat().st_size!=asset['bytes'] or sha(path)!=asset['sha256']:raise ValueError('Existing ensurepip bundle differs from publisher pin')
            bootstrap={**pin(path),'version':asset['version'],'bytes':asset['bytes'],'publisher_url':asset['publisher_url']};save(root/'BOOTSTRAP_PIP.json',bootstrap)
        create=[sys.executable,'-m','venv']+(['--without-pip'] if bootstrap else [])+[str(root/'venv')]
        run('create_new_venv',create,120)
        python=root/'venv'/'Scripts'/'python.exe'
        prefix=[str(python),'-u','-I','-B',str(a.pip_runner),'--journal']
        def pip(name,args,seconds):
            boot=['--bootstrap-pip-wheel',bootstrap['path'],'--bootstrap-pip-wheel-sha256',bootstrap['sha256']] if bootstrap else []
            run(name,prefix+[str(logs/(name+'.journal.json'))]+boot+['--','--isolated','--disable-pip-version-check','--no-input','--no-cache-dir','--timeout','15','--retries','1']+args,seconds)
        torch=next(x for x in wheels if x['name']=='torch');probe=root/'local-wheel-metadata-probe.json'
        mark('LOCAL_WHEEL_METADATA_PROBE_STARTED')
        pip('local_wheel_metadata_probe',['install','--dry-run','--ignore-installed','--no-deps','--no-index','--only-binary=:all:','--report',str(probe),torch['file_url']+'#sha256='+torch['sha256']],120)
        tiny=read(probe)
        if len(tiny.get('install',[]))!=1 or tiny['install'][0]['metadata']['name'].casefold()!='torch':raise ValueError('One-wheel metadata probe did not bind Torch')
        mark('LOCAL_WHEEL_METADATA_PROBE_PASSED')
        replacements={x['name']:x['file_url']+'#sha256='+x['sha256'] for x in wheels};requirements=root/'primary-local-cpu.txt'
        requirements.write_text('\n'.join(line.split(' @ ',1)[0]+' @ '+replacements[line.split(' @ ',1)[0]] if ' @ ' in line else line for line in spec['primary_requirements'])+'\n',encoding='utf-8')
        report=root/'resolved-pip-report.json';mark('FULL_METADATA_RESOLUTION_STARTED')
        pip('resolve_binary_packages',['install','--dry-run','--ignore-installed','--only-binary=:all:','--index-url','https://pypi.org/simple','--report',str(report),'-r',str(requirements)],600)
        lock=lock_resolution(read(report),spec,wheels);save(root/'artifact_lock.json',{'spec':pin(a.environment_spec),'packages':lock,'CPU_wheels':pin(root/'CPU_WHEEL_MATERIALIZATION.json')})
        locked=root/'requirements.lock.txt';locked.write_text('\n'.join(x['name']+' @ '+x['url']+' --hash=sha256:'+x['sha256'] for x in lock)+'\n',encoding='utf-8');mark('EXACT_BINARY_INSTALL_STARTED')
        pip('install_resolved_exact_wheels',['install','--no-deps','--no-compile','--require-hashes','--index-url','https://pypi.org/simple','-r',str(locked)],900)
        pip('metadata_dependency_check',['check'],60)
        code="import importlib.metadata,json;print(json.dumps({x.metadata['Name']:x.version for x in importlib.metadata.distributions()},sort_keys=True))"
        run('metadata_without_model_import',[str(python),'-I','-B','-c',code],30)
        installed=json.loads((logs/'metadata_without_model_import.stdout.log').read_text(encoding='utf-8-sig'));normalized={k.casefold().replace('_','-'):v for k,v in installed.items()}
        for package in lock:
            if normalized.get(package['name'].casefold().replace('_','-'))!=package['version']:raise ValueError('Installed version differs from lock')
        result={'contract':'document-ai-isolated-cpu-environment-result.v2','status':'COMPLETE','environment_spec':pin(a.environment_spec),'pip_runner':pin(a.pip_runner),
            'python':pin(python),'artifact_lock':pin(root/'artifact_lock.json'),'requirements_lock':pin(locked),'CPU_wheels':pin(root/'CPU_WHEEL_MATERIALIZATION.json'),
            'local_metadata_probe':pin(probe),'installed_metadata':installed,'steps':steps,'elapsed_seconds':time.monotonic()-began,
            'bootstrap_pip':pin(root/'BOOTSTRAP_PIP.json') if bootstrap else None,'pip_installed_in_environment':not bool(bootstrap),
            'model_imports':0,'model_calls':0,'optimizer_updates':0,'frozen_runtime_modified':False,'retained_V1_environment_modified':False}
        save(a.summary,result);return result
    except BaseException as exc:
        save(a.summary,{'contract':'document-ai-isolated-cpu-environment-result.v2','status':'FAILED','error':type(exc).__name__,'message':str(exc),'steps':steps,
                       'environment_spec':pin(a.environment_spec),'model_calls':0,'model_imports':0,'frozen_runtime_modified':False,'retained_V1_environment_modified':False,'partial_environment_retained':str(root)})
        raise
    finally:faulthandler.cancel_dump_traceback_later()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--environment-spec',type=Path,required=True);ap.add_argument('--environment-spec-sha256',required=True)
    ap.add_argument('--pip-runner',type=Path,required=True);ap.add_argument('--pip-runner-sha256',required=True);ap.add_argument('--retained-torch-wheel',type=Path)
    ap.add_argument('--environment-root',type=Path,required=True);ap.add_argument('--summary',type=Path,required=True);ap.add_argument('--execute',action='store_true');ap.add_argument('--admission',type=Path);ap.add_argument('--admission-sha256');a=ap.parse_args()
    if sha(a.environment_spec)!=a.environment_spec_sha256 or sha(a.pip_runner)!=a.pip_runner_sha256:raise ValueError('Pinned source/spec differs')
    if not a.execute:print(json.dumps({'valid':True,'executed':False,'model_calls':0,'repair':'hash-verified retained local CPU wheel, no-index one-wheel probe, traced isolated pip'}));return
    print(json.dumps(execute(a),ensure_ascii=False))

if __name__=='__main__':main()
