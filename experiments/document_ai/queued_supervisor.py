"""Wait without model imports, then run one frozen supervised job under 07b.

This is a finite durable HQ queue entry, independent of the browser lifetime.
It never restarts an old job, skips an uncertain process, or raises resource caps.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import errno
import importlib.util
import json
from pathlib import Path
import sys
import time

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True)
    p.add_argument('--config-sha256',required=True);a=p.parse_args()
    c=json.loads(a.config.read_text(encoding='utf-8'))
    sys.path.insert(0,str(Path(c['source']['path']).parent))
    from component_common import read,sha,pin,checked,save,require_HQ
    require_HQ()
    if sha(a.config)!=a.config_sha256 or c['queue_driver']!=pin(__file__):raise ValueError('Queue source/config binding')
    checked(c['source'])
    spec=importlib.util.spec_from_file_location('_frozen_document_ai_supervisor',c['source']['path'])
    s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
    output=s.validate(c)
    maximum_wait=c.get('maximum_wait_seconds',3600)
    if not 0<maximum_wait<=86400:raise ValueError('Queue deadline must be finite <=24h')
    import psutil
    ownership=s.load('_queued_original620',c['pins']['ownership']['path'])
    probe=s.load('_queued_metadata',c['pins']['metadata_probe']['path'])
    registry=ownership.OwnedRegistry(psutil);end_wait=time.monotonic()+maximum_wait
    stack=ExitStack();waiting=a.config.with_suffix('.WAITING.json')
    save(waiting,{'status':'WAITING_FOR_SHARED_RESOURCE','config':pin(a.config),
                  'model_calls':0,'optimizer_updates':0,'maximum_wait_seconds':maximum_wait})
    while True:
        if time.monotonic()>=end_wait:raise TimeoutError('HQ queue wait deadline')
        if a.config.with_suffix('.STOP_REQUEST.json').exists():raise RuntimeError('Stopped before model launch')
        if psutil.virtual_memory().available<s.RESOURCES['minimum_start_free_RAM_bytes']:
            time.sleep(5);continue
        try:
            stack.enter_context(ownership.safe_owned_lock(ownership.LOCK,registry));break
        except OSError as exc:
            if exc.errno not in (errno.EACCES,errno.EAGAIN) and getattr(exc,'winerror',None) not in (32,33):raise
            time.sleep(5)
    resources=[];failure=None
    try:
        with stack:
            output.mkdir(parents=True,exist_ok=False)
            save(output/'STARTED.json',{'config':pin(a.config),'workers_started':0})
            fresh=probe.probe(c['pins']['controller']['path'],ownership.LOCK)
            closure=s.ordinary_process_gate(fresh,c)
            save(output/'EXTERNAL_PROCESS_CLOSURE.json',{'fresh_metadata':fresh,'source_verified_ordinary_processes':closure})
            end=time.monotonic()+c['maximum_total_seconds']
            for step in c['steps']:
                if sha(a.config)!=a.config_sha256:raise ValueError('Config changed after admission')
                checked(step['worker'])
                for record in step.get('input_pins',[]):checked(record)
                resources.append(s.run_stage(step,c,output,ownership,registry,psutil,end))
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc)}
    cleanup=registry.last_cleanup or registry.cleanup();safe=cleanup['confirmed_all_known_owned_exited'] is True
    save(output/'RESULT.json',{'contract':'document-ai-HQ-serial-result.v1',
        'status':'COMPLETE' if failure is None and safe else 'FAILED','failure':failure,
        'config':pin(a.config),'resources':resources,'cleanup':cleanup,
        'shared_lock_released_after_owned_closure':safe,'production_activation':False})
    if failure or not safe:raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except BaseException as exc:
        # Retain a finite terminal queue failure even before a model was admitted.
        if '--config' in sys.argv:
            error_path=Path(sys.argv[sys.argv.index('--config')+1]).with_suffix('.QUEUE_FAILED.json')
            if not error_path.exists():
                with error_path.open('x',encoding='utf-8') as stream:json.dump({'status':'FAILED','type':type(exc).__name__,'message':str(exc)},stream)
        raise
