"""Bounded load-only GLM diagnostic; no image decoding or generation request.

Uses the exact previously measured native source's validation and unchanged
weights/CPU flags. Only verbose logs and read-only process samples are added.
The original 07b/620/877 supervisor remains the owned-tree resource authority.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error

CONTRACT='document-ai-glm-load-diagnostic-config.v1'
SUMMARY='document-ai-glm-load-diagnostic-result.v1'
NATIVE_SHA='eaa509e53adba43a5cedb13aa89df1e5f087c5a3c7e228556092d62d4289dd39'
COMMON_SHA='70178f992d1b64735daeed5919fbcbbbaf0a8a8bea9bd35e5a9e80547f9b0d36'
CAPS={'CPU_threads':1,'minimum_start_free_RAM_bytes':1983628573,
      'stop_free_RAM_bytes':1288490188,'maximum_own_process_tree_RSS_bytes':1073741824}
SOURCE_HASHES={'native':NATIVE_SHA,'common':COMMON_SHA,
 'backend':'f1451f9ef5b52cd8bf4583c3c93ff28e1d6c75d19d07d565c69479cc51381646',
 'evidence':'b4b363377b2d3173d9a86d09a83ceb4601f2968ea80a42df83cd32f70d5e8e89',
 'quant_verifier':'37409eccdf3273fab1ccb9de36b4560cc0505299a1573aecbf5e246b2ab4f150'}

def pin(path):return {'path':str(path),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
def checked(record):
    p=Path(record['path'])
    if pin(p)!=record:raise ValueError('Actual pinned bytes differ')
    return p
def read(record):return json.loads(checked(record).read_text(encoding='utf-8-sig'))
def save(path,value):
    with Path(path).open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())

def validate_config(config):
    if (config.get('contract')!=CONTRACT or config.get('resource_policy')!=CAPS
        or any(type(config['resource_policy'].get(k)) is not int for k in CAPS)
        or config.get('optimizer_updates_allowed') is not False or config.get('production_activation') is not False
        or config.get('source_image_decodes_allowed') is not False or config.get('generation_requests_allowed') is not False):
        raise ValueError('Original isolated load-only resource/permission policy required')
    if (config.get('load_timeout_seconds')!=240 or type(config.get('load_timeout_seconds')) is not int
        or config.get('sample_interval_seconds')!=5 or type(config.get('sample_interval_seconds')) is not int
        or type(config.get('maximum_seconds')) is not int or not 260<=config['maximum_seconds']<=360
        or config.get('log_verbosity')!=5 or type(config.get('log_verbosity')) is not int):
        raise ValueError('Exact bounded diagnostic timing/log options required')
    cutoff=datetime.fromisoformat(config['cutoff_utc'])
    if cutoff.tzinfo is None or cutoff.astimezone(timezone.utc)>datetime(2026,10,30,9,30,tzinfo=timezone.utc):
        raise ValueError('Safe30Oct16:30Bangkok cutoff required')
    if set(config['sources'])!=set(SOURCE_HASHES) or any(config['sources'][k]['sha256']!=v for k,v in SOURCE_HASHES.items()):
        raise ValueError('Exact accepted native and dependency source recipe required')
    return cutoff

@contextmanager
def original_modules(sources):
    """Load actual pinned old paths, preserving native helper path checks."""
    names={'common':'component_common','backend':'glm_backend','evidence':'glm_evidence',
           'quant_verifier':'glm_quantize_worker',
           'native':'_glm_load_diagnostic_original_native'}
    prior={name:sys.modules.get(name) for name in names.values()}
    loaded={}
    try:
        for key in ('common','backend','evidence','quant_verifier','native'):
            p=checked(sources[key]);name=names[key]
            spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec)
            sys.modules[name]=m;spec.loader.exec_module(m);loaded[key]=m
        yield loaded
    finally:
        for name,old in prior.items():
            if old is None:sys.modules.pop(name,None)
            else:sys.modules[name]=old

def diagnostic_argv(backend,native,model,config,port):
    return backend.server_command(native['server']['path'],model['decoder']['path'],model['projector']['path'],
       port=port,context_tokens=config['context_tokens'],max_output_tokens=config['max_output_tokens'],
       image_max_tokens=config['image_max_tokens'])+['--log-verbosity','5']

def process_sample(process,created,elapsed):
    if process.create_time()!=created:raise ValueError('Server PID creation identity changed')
    cpu=process.cpu_times();io=process.io_counters();memory=process.memory_info()
    return {'elapsed_seconds':elapsed,'pid':process.pid,'creation_time':created,
       'cpu_user_seconds':cpu.user,'cpu_system_seconds':cpu.system,'read_bytes':io.read_bytes,
       'write_bytes':io.write_bytes,'read_count':io.read_count,'write_count':io.write_count,
       'thread_count':process.num_threads(),'server_RSS_bytes':memory.rss,
       'scope':'EXACT_SERVER_PROCESS_NOT_TOTAL_OWNED_TREE'}

def monitor(process,owned,created,url,load_timeout,interval,sample,health,clock=time.monotonic,sleep=time.sleep):
    began=clock();deadline=began+load_timeout;next_sample=began;count=0
    while True:
        now=clock()
        if process.poll() is not None:return 'BACKEND_EXIT',clock()-began,count
        if now>=next_sample:
            sample(process_sample(owned,created,now-began));count+=1;next_sample=now+interval
        if now>=deadline:return 'LOAD_TIMEOUT',clock()-began,count
        try:
            response=health(url+'/health',timeout=min(2,max(.05,deadline-now)))
            if response.get('status')=='ok':
                if owned.create_time()!=created:raise ValueError('Server PID creation identity changed')
                port=int(url.rsplit(':',1)[1])
                listeners=[x for x in owned.net_connections(kind='tcp') if x.status=='LISTEN'
                    and x.laddr.ip=='127.0.0.1' and x.laddr.port==port]
                if len(listeners)!=1:raise ValueError('Health listener must belong to exact server child')
                return 'MODEL_AND_VISION_READY',clock()-began,count
        except (urllib.error.URLError,TimeoutError,ConnectionError):pass
        sleep(min(.25,max(0,deadline-clock())))

def execute(config,config_pin,output,admission,admission_sha256):
    cutoff=validate_config(config)
    if socket.gethostname().casefold()!='server':raise ValueError('Native diagnostic is000HQ/SERVER only')
    if datetime.now(timezone.utc).timestamp()+600+60>cutoff.timestamp():raise ValueError('Insufficient safe diagnostic clock-out headroom')
    allowed=Path(r'D:\OCR-Experiments\document-ai-20261028\glm-ocr-20261030\load-diagnostic-v1').resolve()
    output=Path(output)
    if not output.resolve().is_relative_to(allowed) or output.exists():raise ValueError('New dedicated diagnostic output only')
    output.mkdir(parents=True);began=time.monotonic();process=None;cleanup=None;failure=None;outcome='NOT_STARTED'
    samples=0;load_seconds=None;source_seconds=None;argv=None;native_cfg=None;memory=None;server_identity=None;close_child=None
    save(output/'STARTED.json',{'contract':SUMMARY,'worker':pin(__file__),'config':config_pin,
       'source_verification_started':True,'server_started':False,'source_image_decodes':0,'generation_requests':0,'optimizer_updates':0})
    stdout,stderr=output/'server.stdout.log',output/'server.stderr.log'
    try:
        with original_modules(config['sources']) as modules:
            common,native,backend=modules['common'],modules['native'],modules['backend']
            close_child=modules['quant_verifier'].close_owned_child
            common.require_HQ();lease=common.verify_admission(admission,admission_sha256,__file__,'glm-load-diagnostic')
            native_cfg=read(config['native_config'])
            for key in ('common','backend','evidence','quant_verifier'):
                if config['sources'][key]!=native_cfg['sources'][key]:raise ValueError('Original native source path/recipe differs')
            if (native_cfg.get('context_tokens')!=1024 or native_cfg.get('max_output_tokens')!=512
                or native_cfg.get('image_max_tokens')!=256 or native_cfg.get('load_timeout_seconds')!=240):
                raise ValueError('Original measured resource/context recipe required')
            model,native_binding,_,_,memory=native.validate_config(native_cfg,config['native_config'])
            source_seconds=time.monotonic()-began
            if datetime.now(timezone.utc).timestamp()+config['maximum_seconds']+60>cutoff.timestamp():
                raise ValueError('Source verification exhausted safe load-diagnostic headroom')
            if time.time()+config['load_timeout_seconds']+30>lease['expires_at_epoch']:
                raise ValueError('Source verification exhausted original supervisor admission headroom')
            with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            argv=diagnostic_argv(backend,native_binding,model,native_cfg,port)
            save(output/'SERVER_ARGV.json',{'actual_argv':argv,'changed_options_only':['--log-verbosity','5'],
                'native_config':config['native_config'],'source_verification_seconds':source_seconds,'prospective_memory':memory})
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            env.update({key:'1' for key in ('OMP_NUM_THREADS','OMP_THREAD_LIMIT','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')})
            import psutil
            with stdout.open('xb') as log_out,stderr.open('xb') as log_err:
                try:
                    process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log_out,stderr=log_err,env=env,shell=False,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    owned=psutil.Process(process.pid);created=owned.create_time();server_identity={'pid':process.pid,'creation_time':created}
                    save(output/'SERVER_STARTED.json',{'actual_argv':argv,**server_identity})
                    def write_sample(value):
                        with (output/'PROCESS_SAMPLES.jsonl').open('a',encoding='utf-8') as f:
                            f.write(json.dumps(value,allow_nan=False)+'\n');f.flush()
                    outcome,load_seconds,samples=monitor(process,owned,created,'http://127.0.0.1:'+str(port),
                        config['load_timeout_seconds'],config['sample_interval_seconds'],write_sample,native.response_json)
                finally:
                    if process is not None:cleanup=close_child(process)
                    log_out.flush();log_err.flush();os.fsync(log_out.fileno());os.fsync(log_err.fileno())
    except BaseException as exc:failure={'type':type(exc).__name__,'message':str(exc)}
    finally:
        if process is not None and cleanup is None:cleanup=close_child(process)
        closed=process is None or cleanup is not None and cleanup['confirmed_closed']
        if not closed and failure is None:failure={'type':'OwnedChildClosureUncertain','message':'Original supervisor must establish physical closure'}
        result={'contract':SUMMARY,'status':'EXECUTION_FINISHED' if failure is None and closed else 'FAILED',
            'component':'glm-load-diagnostic','executed':True,'worker':pin(__file__),'config':config_pin,
            'native_config':config['native_config'],'source_recipe':config['sources'],'actual_argv':argv,
            'load_outcome':outcome,'source_verification_seconds':source_seconds,'load_seconds':load_seconds,
            'elapsed_seconds':time.monotonic()-began,'server_identity':server_identity,'server_started':process is not None,
            'server_closed':closed,'cleanup':cleanup,'failure':failure,'process_samples':samples,
            'process_samples_pin':pin(output/'PROCESS_SAMPLES.jsonl') if (output/'PROCESS_SAMPLES.jsonl').exists() else None,
            'raw_stdout':pin(stdout) if stdout.exists() else None,'raw_stderr':pin(stderr) if stderr.exists() else None,
            'source_image_decodes':0,'generation_requests':0,'OCR_calls':0,'optimizer_updates':0,
            'model_load_attempts':int(process is not None),'accuracy_measured':False,'baseline_cache_modified':False,
            'production_activation':False,'diagnostic_completion_is_not_model_readiness_or_accuracy':True}
        save(output/'SUMMARY.json',result)
    if failure is not None:raise RuntimeError('Diagnostic failed; inspect preserved summary and raw logs')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--output',required=True);p.add_argument('--admission',required=True);p.add_argument('--admission-sha256',required=True)
    a=p.parse_args();config_pin={'path':a.config,'sha256':a.config_sha256}
    execute(read(config_pin),config_pin,a.output,a.admission,a.admission_sha256)
if __name__=='__main__':main()
