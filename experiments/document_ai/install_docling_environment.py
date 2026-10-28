"""Guarded HQ-only isolated CPU dependencies; no model imports or images.

Must run as one serial_supervisor stage, component='docling-install'. Resolves
once into a complete URL/SHA256 lock, installs only that lock into a NEW venv,
and records packages using metadata (not by importing Torch or Docling).
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from component_common import read,sha,pin,save,verify_admission

def checked_report(report,spec,archive_sizes=None):
    installs=report.get('install',[])
    if not installs:raise ValueError('Empty package resolution')
    lock=[];total=0
    for item in installs:
        info=item['download_info'];url=info['url'];parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in spec['allowed_artifact_hosts']:raise ValueError('Unapproved package source')
        digest=info.get('archive_info',{}).get('hashes',{}).get('sha256')
        if not digest or len(digest)!=64 or not parsed.path.casefold().endswith('.whl'):raise ValueError('Only SHA256-pinned binary wheels')
        name=item['metadata']['name'];version=item['metadata']['version']
        if archive_sizes is not None:size=archive_sizes[url]
        else:
            with urlopen(Request(url,method='HEAD'),timeout=30) as response:
                size=int(response.headers.get('Content-Length','0'))
        if size<=0:raise ValueError('Binary wheel byte size unavailable')
        total+=size
        if total>spec['maximum_resolved_download_bytes']:raise ValueError('Resolved wheel bytes exceed approved disk budget')
        lock.append({'name':name,'version':version,'url':url,'sha256':digest,'bytes':size})
    return sorted(lock,key=lambda x:x['name'].casefold())

def execute(a):
    verify_admission(a.admission,a.admission_sha256,__file__,'docling-install')
    if sha(a.environment_spec)!=a.environment_spec_sha256:raise ValueError('Environment spec changed')
    spec=read(a.environment_spec)
    if spec.get('contract')!='document-ai-isolated-cpu-environment.v1':raise ValueError('Unknown environment specification')
    if sys.version_info[:2]!=(3,11) or platform.machine().casefold() not in ('amd64','x86_64'):raise ValueError('Pinned CPU wheels require Python3.11 WindowsAMD64')
    root=a.environment_root.resolve()
    if root.drive.upper()!='D:' or 'OCR-Experiments' not in root.parts or 'runtime' in root.parts or root.exists():raise ValueError('New isolated D experiment venv root required')
    if shutil.disk_usage(root.parent).free<spec['minimum_free_disk_bytes_before_setup']:raise ValueError('Disk setup headroom gate')
    root.mkdir();logs=root/'setup_logs';logs.mkdir();(root/'tmp').mkdir();(root/'pip_cache').mkdir()
    env=dict(os.environ,TEMP=str(root/'tmp'),TMP=str(root/'tmp'),PIP_CACHE_DIR=str(root/'pip_cache'),PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_NO_INPUT='1')
    steps=[]
    def run(name,argv,seconds):
        stdout=logs/(name+'.stdout.log');stderr=logs/(name+'.stderr.log')
        with stdout.open('xb') as out,stderr.open('xb') as err:
            result=subprocess.run(argv,env=env,stdout=out,stderr=err,shell=False,timeout=seconds,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        steps.append({'name':name,'exit_code':result.returncode,'stdout':pin(stdout),'stderr':pin(stderr)})
        if result.returncode:raise RuntimeError('Isolated setup step failed: '+name)
    try:
        run('create_new_venv',[sys.executable,'-m','venv',str(root/'venv')],120)
        python=root/'venv'/'Scripts'/'python.exe'
        requirements=root/'primary_requirements.txt';requirements.write_text('\n'.join(spec['primary_requirements'])+'\n',encoding='utf-8')
        report=root/'resolved-pip-report.json'
        run('resolve_binary_packages',[str(python),'-m','pip','install','--dry-run','--ignore-installed','--only-binary=:all:','--index-url','https://pypi.org/simple','--report',str(report),'-r',str(requirements)],600)
        lock=checked_report(read(report),spec);save(root/'artifact_lock.json',{'spec':pin(a.environment_spec),'packages':lock})
        # Requirements contain exact publisher URLs and archive hashes; pip may
        # reuse its own hash-checked cache from resolution, never global models.
        locked=root/'requirements.lock.txt';locked.write_text('\n'.join(x['name']+' @ '+x['url']+' --hash=sha256:'+x['sha256'] for x in lock)+'\n',encoding='utf-8')
        run('install_resolved_exact_wheels',[str(python),'-m','pip','install','--no-deps','--require-hashes','--index-url','https://pypi.org/simple','-r',str(locked)],900)
        code="import importlib.metadata,json;print(json.dumps({x.metadata['Name']:x.version for x in importlib.metadata.distributions()},sort_keys=True))"
        run('metadata_without_model_import',[str(python),'-I','-B','-c',code],30)
        installed=json.loads((logs/'metadata_without_model_import.stdout.log').read_text(encoding='utf-8-sig'))
        byname={k.casefold().replace('_','-'):v for k,v in installed.items()}
        for package in lock:
            if byname.get(package['name'].casefold().replace('_','-'))!=package['version']:raise ValueError('Installed exact version differs')
        result={'contract':'document-ai-isolated-cpu-environment-result.v1','status':'COMPLETE','environment_spec':pin(a.environment_spec),
            'python':pin(python),'artifact_lock':pin(root/'artifact_lock.json'),'requirements_lock':pin(locked),'installed_metadata':installed,
            'steps':steps,'model_imports':0,'model_calls':0,'optimizer_updates':0,'frozen_runtime_modified':False}
        save(a.summary,result);return result
    except BaseException as exc:
        save(a.summary,{'contract':'document-ai-isolated-cpu-environment-result.v1','status':'FAILED','error':type(exc).__name__,'message':str(exc),
            'environment_spec':pin(a.environment_spec),'steps':steps,'model_calls':0,'model_imports':0,'frozen_runtime_modified':False,'partial_environment_retained':str(root)})
        raise

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--environment-spec',type=Path,required=True);ap.add_argument('--environment-spec-sha256',required=True)
    ap.add_argument('--environment-root',type=Path,required=True);ap.add_argument('--summary',type=Path,required=True);ap.add_argument('--execute',action='store_true')
    ap.add_argument('--admission',type=Path);ap.add_argument('--admission-sha256');a=ap.parse_args()
    if sha(a.environment_spec)!=a.environment_spec_sha256:raise ValueError('Spec SHA differs')
    if not a.execute:print(json.dumps({'valid':True,'executed':False,'spec':pin(a.environment_spec),'model_imports':0,'model_calls':0}));return
    print(json.dumps(execute(a),ensure_ascii=False))

if __name__=='__main__':main()
