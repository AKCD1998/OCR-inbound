"""Root-only serial HQ jobs using the audited 07b lock and 620 child registry.

No SDK/model imports. Every new launch needs a fresh root classification of
pre-existing Python/native-reader processes; a PID or executable exemption alone
is deliberately insufficient. The worker owns numerical training measurements.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from component_common import RESOURCES,CONTROLLER_SHA256,read,sha,pin,checked,save,require_HQ

OWNERSHIP_SHA='620df01cdc5037b922bc6b28586a0d94c8a266c936ebb05a57b42b22a5fefb45'
TRAIN_START_BYTES=2469606195

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

def ordinary_process_gate(probe,c):
    """Fresh observed identities must match explicit, source-backed root review."""
    if probe['process_inventory_uncertain']:raise ValueError('Uncertain external process inventory')
    approved={(x['pid'],x['creation_time']):x for x in c['ordinary_external_processes']}
    actual=[]
    for item in probe['model_like_processes']:
        key=(item['pid'],item['creation_time']);allowed=approved.get(key)
        if allowed is None:raise ValueError('Unreviewed external process identity: '+str(item['pid']))
        for field in ('command_sha256','parent_identity','entrypoint','module'):
            if allowed.get(field)!=item.get(field):raise ValueError('External identity/source observation changed: '+str(item['pid']))
        if allowed.get('classification')!='root_source_verified_ordinary_application':raise ValueError('Ordinary application source classification required')
        if item['loaded_ML_library_basenames'] or item['memory_map_observation_error']:raise ValueError('External ML libraries or uncertain mappings')
        checked(allowed['reviewed_source'])
        actual.append({'pid':item['pid'],'creation_time':item['creation_time'],'reviewed_source':allowed['reviewed_source']})
    return actual

def validate(c):
    if c.get('contract')!='root-HQ-document-ai-serial.v1' or c.get('approved_by')!='root':raise ValueError('Root serial configuration required')
    if c.get('source')!=pin(__file__) or c.get('resource_policy')!=RESOURCES or c.get('production_activation_allowed') is not False:raise ValueError('Source/resource policy differs')
    if c['pins']['controller']['sha256']!=CONTROLLER_SHA256 or c['pins']['ownership']['sha256']!=OWNERSHIP_SHA:raise ValueError('Original 07b/620 ownership sources required')
    for record in c['pins'].values():checked(record)
    output=Path(c['output_root']).resolve()
    if output.drive.upper()!='D:' or 'OCR-Experiments' not in output.parts or output.exists():raise ValueError('New isolated HQ experiment output required')
    if not 0<c['maximum_total_seconds']<=43200:raise ValueError('Fresh total deadline must be <=12 hours')
    names=set()
    for step in c['steps']:
        if not step['id'].replace('_','').isalnum() or step['id'] in names:raise ValueError('Unique simple stage id required')
        names.add(step['id'])
        if not 0<step['maximum_seconds']<=2400:raise ValueError('Each stage must be bounded <=2400s')
        checked(step['worker'])
        if step.get('python'):checked(step['python'])
        for record in step.get('input_pins',[]):checked(record)
        if not isinstance(step['args'],list) or not all(isinstance(v,str) for v in step['args']):raise ValueError('Structured worker arguments required')
        if step.get('optimizer_updates_allowed') not in (True,False):raise ValueError('Explicit optimizer authority required')
        if step.get('component') and step['optimizer_updates_allowed']:raise ValueError('Geometry components cannot optimize')
        if not step.get('summary_equals'):raise ValueError('Actual summary completion predicates required')
        summary=Path(step['summary_path']).resolve()
        if not summary.is_relative_to(output) or summary==output:raise ValueError('Summary outside this experiment')
    return output

def run_stage(step,c,output,ownership,registry,psutil,end):
    minimum_start=TRAIN_START_BYTES if step['optimizer_updates_allowed'] else RESOURCES['minimum_start_free_RAM_bytes']
    if psutil.virtual_memory().available<minimum_start:raise ValueError('Fresh RAM start gate')
    now=time.monotonic();deadline=min(end,now+step['maximum_seconds'])
    lease={'contract':'root-HQ-document-ai-admission.v1' if step.get('component') else 'root-HQ-serial-worker-admission.v1',
           'approved_by':'root','component':step.get('component'),'resource_policy':RESOURCES,
           'worker':step['worker'],'controller_sha256':CONTROLLER_SHA256,'shared_lock_held':True,
           'supervisor_pid':os.getpid(),'supervisor_creation_time':psutil.Process().create_time(),
           'expires_at_epoch':time.time()+max(0,deadline-time.monotonic()),
           'optimizer_updates_allowed':step['optimizer_updates_allowed'],'production_activation_allowed':False}
    lease['actual_stage_minimum_start_free_RAM_bytes']=minimum_start
    leasepath=output/(step['id']+'.admission.json');save(leasepath,lease)
    replacements={'{admission}':str(leasepath),'{admission_sha256}':sha(leasepath)}
    python=step.get('python',c['pins']['python']);checked(python)
    argv=[python['path'],'-X','utf8','-B',step['worker']['path']]+[replacements.get(x,x) for x in step['args']]
    env=dict(os.environ,**{k:'1' for k in ('OMP_THREAD_LIMIT','OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','CPU_NUM','FLAGS_paddle_num_threads')})
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True',NO_ALBUMENTATIONS_UPDATE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    logs=[output/(step['id']+x) for x in ('.stdout.log','.stderr.log')]
    process=None;failure=None;stop=None;peak=0;minimum=psutil.virtual_memory().available;result=None
    try:
        with logs[0].open('xb') as stdout,logs[1].open('xb') as stderr:
            process=subprocess.Popen(argv,cwd=output,env=env,stdout=stdout,stderr=stderr,shell=False,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));registry.add(process)
            while process.poll() is None:
                try:rss=registry.sample()
                except psutil.NoSuchProcess:
                    # The root's real Popen handle must prove exit, not PID lookup.
                    if process.poll() is None:raise
                    rss=registry.sample()
                free=psutil.virtual_memory().available;minimum=min(minimum,free);peak=max(peak,rss)
                if free<RESOURCES['stop_free_RAM_bytes']:stop='free_RAM_floor'
                elif rss>RESOURCES['maximum_own_process_tree_RSS_bytes']:stop='owned_RSS_cap'
                elif time.monotonic()>=deadline:stop='stage_or_total_deadline'
                elif (output/'STOP_REQUEST.json').exists():stop='root_stop'
                if stop:raise RuntimeError(stop)
                time.sleep(.25)
            process.wait(timeout=10);stdout.flush();stderr.flush();os.fsync(stdout.fileno());os.fsync(stderr.fileno())
        if process.returncode!=0:raise RuntimeError('Actual worker exit '+str(process.returncode))
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    try:cleanup=registry.cleanup()
    except BaseException as exc:
        cleanup={'confirmed_all_known_owned_exited':False,'uncertain_or_live_owned':[{'error':type(exc).__name__}]}
        if failure is None:failure={'type':type(exc).__name__,'message':str(exc)}
    safe=cleanup['confirmed_all_known_owned_exited'] is True
    if safe and failure is None:
        try:
            summary=Path(step['summary_path']);result=read(summary)
            for key,value in step['summary_equals'].items():
                if result.get(key)!=value:failure={'type':'SummaryPredicate','message':key+' differs'};break
        except BaseException as exc:failure={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    record={'stage':step['id'],'actual_argv':argv,'actual_exit_code':None if process is None else process.poll(),
            'child_started':process is not None,'peak_owned_process_tree_RSS_bytes':peak,'minimum_free_RAM_bytes':minimum,
            'elapsed_seconds':time.monotonic()-now,'stop_reason':stop,'failure':failure,'cleanup':cleanup,
            'worker_optimizer_updates_permission':step['optimizer_updates_allowed'],
            'actual_stage_minimum_start_free_RAM_bytes':minimum_start,
            'optimizer_updates_measurement':'read actual worker summary/checkpoint; supervisor does not infer zero',
            'worker_summary':pin(step['summary_path']) if safe and Path(step['summary_path']).is_file() else None,
            'logs_finalized_after_owned_cleanup':safe,'logs':[pin(p) for p in logs if p.exists()] if safe else []}
    save(output/(step['id']+'.resource.json'),record)
    if not safe or failure:raise RuntimeError('Stage failed: '+step['id'])
    return record

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',type=Path,required=True);ap.add_argument('--config-sha256',required=True);ap.add_argument('--execute',action='store_true');a=ap.parse_args()
    if sha(a.config)!=a.config_sha256:raise ValueError('Config SHA differs')
    c=read(a.config);output=validate(c)
    if not a.execute:print({'valid':True,'executed':False,'steps':len(c['steps']),'model_calls':0});return
    require_HQ();import psutil
    ownership=load('_docai_original620_ownership',c['pins']['ownership']['path']);probe=load('_docai_fresh_metadata',c['pins']['metadata_probe']['path'])
    output.mkdir(parents=True,exist_ok=False);registry=ownership.OwnedRegistry(psutil);resources=[];failure=None;closure=None;lock_acquired=False
    save(output/'STARTED.json',{'config':pin(a.config),'supervisor':pin(__file__),'started_utc':datetime.now(timezone.utc).isoformat(),'workers_started':0})
    try:
        with ownership.safe_owned_lock(ownership.LOCK,registry):
            lock_acquired=True
            fresh=probe.probe(c['pins']['controller']['path'],ownership.LOCK)
            closure=ordinary_process_gate(fresh,c);save(output/'EXTERNAL_PROCESS_CLOSURE.json',{'fresh_metadata':fresh,'source_verified_ordinary_processes':closure})
            end=time.monotonic()+c['maximum_total_seconds']
            for step in c['steps']:
                if time.monotonic()>=end:raise RuntimeError('Fresh total deadline expired')
                if sha(a.config)!=a.config_sha256:raise ValueError('Config changed')
                checked(step['worker'])
                for record in step.get('input_pins',[]):checked(record)
                resources.append(run_stage(step,c,output,ownership,registry,psutil,end))
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
        # A failed stage writes its resource receipt before raising. Keep that
        # real attempt in RESULT as well as in the standalone immutable file.
        if 'step' in locals():
            failed_resource=output/(step['id']+'.resource.json')
            if failed_resource.is_file() and not any(r['stage']==step['id'] for r in resources):resources.append(read(failed_resource))
    cleanup=registry.last_cleanup or registry.cleanup();safe=cleanup['confirmed_all_known_owned_exited'] is True
    save(output/'RESULT.json',{'contract':'document-ai-HQ-serial-result.v1','status':'COMPLETE' if failure is None and safe else 'FAILED',
        'failure':failure,'config':pin(a.config),'resources':resources,'cleanup':cleanup,'shared_lock_acquired':lock_acquired,
        'shared_lock_released_after_owned_closure':safe and lock_acquired,
        'production_activation':False,'optimizer_updates_measurement':'worker summaries only'})
    if failure or not safe:raise SystemExit(1)

if __name__=='__main__':main()
