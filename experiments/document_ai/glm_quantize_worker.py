"""One admitted HQ projector requantization, never OCR or model inference.

Original 07b/620/877 supervision owns the RSS/free-RAM limit and descendants.
The quantizer's Windows mmap fragment release is a no-op: its 16 MiB slab
setting is explicitly not represented as a whole-process RAM guarantee.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback
import component_common as common

CONTRACT='document-ai-glm-projector-quantize-config.v1'
SUMMARY='document-ai-glm-projector-quantize-result.v1'
PROJECTOR_SHA='9c4b58e33e316ed142eb5dcb41abec3844d3e6e5dc361ffb782c3fa9d175141f'
PROJECTOR_BYTES=484403648
PREPARE_WORKER_SHA='0cc41b63ed7f57eeec4c129cb39fb4c59cace806a10fbce6db2e6e4bd60986cb'
COMMON_SHA='70178f992d1b64735daeed5919fbcbbbaf0a8a8bea9bd35e5a9e80547f9b0d36'
ALLOWED_ROOT=Path(r'D:\OCR-Experiments\document-ai-20261028\glm-ocr-20261030')

def same_pin(a,b):
    return (isinstance(a,dict) and isinstance(b,dict) and a.get('sha256')==b.get('sha256')
        and str(a.get('path')).replace('\\','/').casefold()==str(b.get('path')).replace('\\','/').casefold())

def valid_pin(value):
    return (isinstance(value,dict) and isinstance(value.get('path'),str)
        and isinstance(value.get('sha256'),str) and len(value['sha256'])==64
        and all(c in '0123456789abcdef' for c in value['sha256']))

def materialization_proof(config,check=common.checked):
    summary=common.read(check(config['source_materialization_summary']))
    closed=common.read(check(config['closed_materialization_root']))
    if (summary.get('contract')!='document-ai-glm-materialize.v1' or summary.get('status')!='COMPLETE'
        or summary.get('component')!='glm-materialize' or summary.get('executed') is not True
        or summary.get('worker',{}).get('sha256')!=PREPARE_WORKER_SHA
        or any(summary.get(k)!=0 for k in ('model_calls','quantization_calls','source_image_decodes','optimizer_updates'))
        or summary.get('production_activation') is not False or summary.get('baseline_cache_modified') is not False):
        raise ValueError('Actual selected model-free materialization summary required')
    if (closed.get('contract')!='document-ai-HQ-serial-result.v1' or closed.get('status')!='COMPLETE'
        or closed.get('failure') is not None or closed.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
        or closed.get('shared_lock_acquired') is not True or closed.get('shared_lock_released_after_owned_closure') is not True):
        raise ValueError('Physically closed materialization supervision required')
    matches=[r for r in closed.get('resources',[]) if same_pin(r.get('worker_summary'),config['source_materialization_summary'])]
    if len(matches)!=1:raise ValueError('Materialization resource must bind this exact summary')
    resource=matches[0]
    if (resource.get('actual_exit_code')!=0 or resource.get('child_started') is not True or resource.get('failure') is not None
        or resource.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
        or resource.get('worker_optimizer_updates_permission') is not False
        or resource.get('logs_finalized_after_owned_cleanup') is not True
        or resource.get('peak_owned_process_tree_RSS_bytes',math.inf)>common.RESOURCES['maximum_own_process_tree_RSS_bytes']
        or resource.get('minimum_free_RAM_bytes',0)<common.RESOURCES['stop_free_RAM_bytes']):
        raise ValueError('Actual successful bounded materialization child closure required')
    argv=resource.get('actual_argv',[])
    if (summary['worker']['path'] not in argv or '--config' not in argv or '--config-sha256' not in argv
        or argv[argv.index('--config')+1]!=summary.get('config',{}).get('path')
        or argv[argv.index('--config-sha256')+1]!=summary.get('config',{}).get('sha256')):
        raise ValueError('Materialization summary is not causally bound to actual worker argv')
    artifacts=[x for x in summary.get('artifacts',[]) if x.get('role')=='projector']
    if (len(artifacts)!=1 or not same_pin(artifacts[0].get('file'),config['projector_source'])
        or artifacts[0].get('bytes')!=PROJECTOR_BYTES or config['projector_source']['sha256']!=PROJECTOR_SHA):
        raise ValueError('Exact official Q8 projector source required')
    if not same_pin(summary.get('isolated_python'),config['isolated_python']):
        raise ValueError('Exact isolated runtime from materialization required')
    backend=summary.get('backend') or {}
    files=backend.get('files',[])
    if (not files or not valid_pin(backend.get('quantizer'))
        or sum(same_pin(x.get('pin'),backend['quantizer']) for x in files)!=1):
        raise ValueError('Actual sealed backend file inventory/quantizer required')
    for record in files:check(record['pin'])
    check(backend['quantizer']);check(config['projector_source']);check(config['isolated_python'])
    return summary,resource

def validate_config(config,output,*,check_files=True):
    keys={'contract','resource_policy','maximum_seconds','cutoff_utc','source_materialization_summary',
        'closed_materialization_root','backend_module','common','isolated_python','projector_source',
        'output_filename','output_root','production_activation','optimizer_updates_allowed','source_image_decodes_allowed'}
    if (type(config) is not dict or set(config)!=keys or config.get('contract')!=CONTRACT
        or config.get('resource_policy')!=common.RESOURCES or type(config.get('maximum_seconds')) is not int
        or not 1<=config['maximum_seconds']<=540 or config.get('production_activation') is not False
        or config.get('optimizer_updates_allowed') is not False or config.get('source_image_decodes_allowed') is not False):
        raise ValueError('Exact finite no-inference/no-training quantization configuration required')
    for key in ('source_materialization_summary','closed_materialization_root','backend_module','common','isolated_python','projector_source'):
        if not valid_pin(config[key]):raise ValueError('Pinned input required: '+key)
    filename=config['output_filename']
    if (type(filename) is not str or Path(filename).name!=filename or not filename.endswith('.gguf')
        or filename in ('.','..') or any(c in filename for c in ('/','\\',':'))):
        raise ValueError('New local projector output basename required')
    if config['common']['sha256']!=COMMON_SHA or config['projector_source']['sha256']!=PROJECTOR_SHA:
        raise ValueError('Original helper/projector bytes required')
    deadline=datetime.fromisoformat(config['cutoff_utc'])
    if deadline.tzinfo is None:raise ValueError('Explicit UTC-aware clock-out boundary required')
    out=Path(output).resolve()
    if out!=Path(config['output_root']).resolve() or not out.is_relative_to(ALLOWED_ROOT.resolve()) or out==ALLOWED_ROOT.resolve():
        raise ValueError('Exact new isolated GLM output required')
    if check_files:
        if common.checked(config['common']).resolve()!=Path(common.__file__).resolve():raise ValueError('Actual imported helper differs')
        if common.checked(config['isolated_python']).resolve()!=Path(sys.executable).resolve():raise ValueError('Actual isolated Python differs')
        if common.checked(config['projector_source']).stat().st_size!=PROJECTOR_BYTES:raise ValueError('Official projector length differs')
        common.checked(config['backend_module']);materialization_proof(config)
    return out,deadline.timestamp()

def projector_header(path,expected_file_type=2):
    """Bounded GGUF metadata and complete tensor-range validation; no inference."""
    path=Path(path);size=path.stat().st_size;used=0
    with path.open('rb') as stream:
        def take(n):
            nonlocal used
            if not 0<=n<=4*1024*1024 or used+n>32*1024*1024:raise ValueError('Bounded GGUF header required')
            value=stream.read(n);used+=len(value)
            if len(value)!=n:raise ValueError('Truncated GGUF header')
            return value
        def number(fmt):return struct.unpack('<'+fmt,take(struct.calcsize('<'+fmt)))[0]
        def string():return take(number('Q')).decode('utf8')
        formats={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
        def value(kind,depth=0):
            if kind in formats:return number(formats[kind])
            if kind==8:return string()
            if kind==9 and depth==0:
                element,count=number('I'),number('Q')
                if count>1_000_000:raise ValueError('Bounded GGUF array required')
                for _ in range(count):value(element,1)
                return {'element_type':element,'count':count}
            raise ValueError('Unsupported GGUF metadata type')
        if take(4)!=b'GGUF' or number('I')!=3:raise ValueError('GGUF v3 output required')
        tensors,nkv=number('Q'),number('Q')
        if not 1<=tensors<=10000 or not 1<=nkv<=10000:raise ValueError('Bounded GGUF tensor/metadata inventory required')
        metadata={}
        for _ in range(nkv):
            key=string()
            if key in metadata:raise ValueError('Duplicate GGUF metadata key')
            metadata[key]=value(number('I'))
        if expected_file_type not in (2,7) or metadata.get('general.architecture')!='clip' or metadata.get('general.file_type')!=expected_file_type:
            raise ValueError('Actual selected CLIP projector metadata required')
        alignment=metadata.get('general.alignment',32)
        if type(alignment) is not int or alignment<1 or alignment>4096 or alignment&(alignment-1):raise ValueError('GGUF alignment invalid')
        names=set();records=[];counts={};inventory=[]
        # block width / byte size for the reviewed output and retained float/
        # quantized exceptions. Unknown layouts abstain instead of guessing.
        layouts={0:(1,4),1:(1,2),2:(32,18),3:(32,20),6:(32,22),7:(32,24),8:(32,34),9:(32,36),30:(1,2)}
        for _ in range(tensors):
            name=string();ndim=number('I')
            if name in names or not 1<=ndim<=4:raise ValueError('Unique bounded tensor metadata required')
            names.add(name);shape=[number('Q') for _ in range(ndim)];kind=number('I');offset=number('Q')
            if any(not 1<=n<=2**32 for n in shape) or kind not in layouts or offset%alignment:
                raise ValueError('Unsupported tensor shape/type/alignment')
            block,width=layouts[kind]
            if shape[0]%block:raise ValueError('Invalid quantized tensor row width')
            length=shape[0]//block*width*math.prod(shape[1:])
            records.append((offset,length));counts[str(kind)]=counts.get(str(kind),0)+1
            inventory.append({'name':name,'shape':shape})
        start=(used+alignment-1)//alignment*alignment
        intervals=sorted((a,a+b) for a,b in records)
        if (expected_file_type==2 and not counts.get('2') or expected_file_type==7 and not counts.get('8')
                or any(start+b>size for a,b in intervals) or any(a1<b0 for (_,b0),(a1,_) in zip(intervals,intervals[1:]))):
            raise ValueError('Incomplete/overlapping GGUF tensor payload')
    inventory.sort(key=lambda t:t['name'])
    digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'version':3,'architecture':'clip','file_type':expected_file_type,'target_quantization':'Q4_0' if expected_file_type==2 else 'Q8_0',
        'tensor_count':tensors,'tensor_type_counts':counts,'metadata_bytes':used,'data_offset':start,
        'file_bytes':size,'all_tensor_payload_ranges_present':True,'tensor_values_decoded':False,
        'tensor_name_shape_inventory':inventory,'tensor_name_shape_inventory_sha256':digest}

def close_owned_child(process):
    """Best-effort handle-owned cleanup; a failed terminate never skips kill."""
    errors=[];actions=[]
    def poll():
        try:return process.poll()
        except Exception as error:errors.append({'operation':'poll','type':type(error).__name__});return None
    if poll() is None:
        try:process.terminate();actions.append('terminate')
        except Exception as error:errors.append({'operation':'terminate','type':type(error).__name__})
        try:process.wait(timeout=5)
        except Exception as error:errors.append({'operation':'wait_after_terminate','type':type(error).__name__})
    if poll() is None:
        try:process.kill();actions.append('kill')
        except Exception as error:errors.append({'operation':'kill','type':type(error).__name__})
        try:process.wait(timeout=5)
        except Exception as error:errors.append({'operation':'wait_after_kill','type':type(error).__name__})
    code=poll()
    return {'confirmed_closed':code is not None,'exit_code':code,'actions':actions,'errors':errors,
        'outer_original_supervisor_remains_final_closure_authority':True}

def run_quantization(config,output,config_pin):
    common.require_HQ();out,cutoff=validate_config(config,output)
    if out.exists():raise FileExistsError('Preserve previous quantization attempt')
    if datetime.now(timezone.utc).timestamp()+config['maximum_seconds']+60>cutoff:
        raise ValueError('Quantization would cross safe clock-out boundary')
    source,_=materialization_proof(config)
    spec=importlib.util.spec_from_file_location('_sealed_glm_quantize_backend',common.checked(config['backend_module']))
    backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
    backend.validate_resources(config['resource_policy'])
    out.mkdir(parents=True,exist_ok=False);began=time.monotonic();failure=None;process=None;started=completed=0;header=None;source_header=None;result=None;cleanup=None
    partial=out/(config['output_filename']+'.partial');final=out/config['output_filename']
    stdout,stderr=out/'quantizer.stdout.log',out/'quantizer.stderr.log'
    command=backend.quantize_command(source['backend']['quantizer']['path'],config['projector_source']['path'],str(partial),quantization='Q4_0')
    common.save(out/'STARTED.json',{'contract':SUMMARY,'worker':common.pin(__file__),'config':config_pin,
        'actual_argv':command,'quantization_started':0,'model_calls':0,'source_image_decodes':0,'optimizer_updates':0})
    try:
        source_header=projector_header(config['projector_source']['path'],expected_file_type=7)
        env=dict(os.environ,OMP_NUM_THREADS='1',OMP_THREAD_LIMIT='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        env.pop('PYTHONPATH',None)
        with stdout.open('xb') as log_out,stderr.open('xb') as log_err:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log_out,stderr=log_err,env=env,
                cwd=Path(source['backend']['quantizer']['path']).parent,shell=False,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));started=1
            process.wait(timeout=max(.1,config['maximum_seconds']-(time.monotonic()-began)-30))
            log_out.flush();log_err.flush();os.fsync(log_out.fileno());os.fsync(log_err.fileno())
        if process.returncode!=0:raise RuntimeError('Actual quantizer exit '+str(process.returncode))
        header=projector_header(partial)
        if (header['tensor_name_shape_inventory_sha256']!=source_header['tensor_name_shape_inventory_sha256']
                or header['tensor_name_shape_inventory']!=source_header['tensor_name_shape_inventory']):
            raise ValueError('Quantizer source/output whole tensor name/shape inventory differs')
        common.checked(config['projector_source'])
        if final.exists():raise FileExistsError('Never replace an earlier quantized artifact')
        partial.rename(final);result=common.pin(final);completed=1
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()}
    finally:
        if process is not None:cleanup=close_owned_child(process)
    if cleanup is not None and not cleanup['confirmed_closed'] and failure is None:
        failure={'type':'OwnedChildClosureUncertain','message':'Outer supervisor must establish physical closure'}
    summary={'contract':SUMMARY,'status':'COMPLETE' if failure is None and completed==1 else 'FAILED',
        'component':'glm-quantize','executed':True,'failure':failure,'worker':common.pin(__file__),'config':config_pin,
        'source_materialization_summary':config['source_materialization_summary'],'closed_materialization_root':config['closed_materialization_root'],
        'source_projector':config['projector_source'],'isolated_python':config['isolated_python'],'backend_module':config['backend_module'],
        'actual_argv':command,'child_started':process is not None,'child_exit_code':None if cleanup is None else cleanup['exit_code'],
        'child_closed':cleanup is not None and cleanup['confirmed_closed'],'owned_child_cleanup':cleanup,
        'quantization_started':started,'quantization_completed':completed,
        'quantized_projector':result,'quantized_projector_bytes':None if result is None else final.stat().st_size,
        'GGUF_validation':header,'source_GGUF_metadata':source_header,
        'source_output_tensor_inventory_equal':header is not None and source_header is not None and header['tensor_name_shape_inventory_sha256']==source_header['tensor_name_shape_inventory_sha256'],
        'raw_stdout':common.pin(stdout) if stdout.exists() else None,'raw_stderr':common.pin(stderr) if stderr.exists() else None,
        'elapsed_seconds':time.monotonic()-began,'quantization':'Q4_0','allow_requantize':True,'maximum_buffer_MiB':16,
        'Windows_mmap_fragment_release_is_noop':True,'buffer_limit_is_not_total_RSS_guarantee':True,
        'model_calls':0,'OCR_calls':0,'source_image_decodes':0,'optimizer_updates':0,'baseline_cache_modified':False,'production_activation':False}
    common.save(out/'SUMMARY.json',summary)
    if failure:raise RuntimeError('Quantization failed; partial artifacts retained')
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--output',required=True);p.add_argument('--admission');p.add_argument('--admission-sha256');p.add_argument('--execute',action='store_true');args=p.parse_args()
    config_pin={'path':args.config,'sha256':args.config_sha256};config=common.read(common.checked(config_pin))
    if not args.execute:
        validate_config(config,args.output);print(json.dumps({'valid':True,'executed':False,'quantization_calls':0,'model_calls':0}));return
    if not args.admission or not args.admission_sha256:raise ValueError('Root admission required for execution')
    common.verify_admission(args.admission,args.admission_sha256,__file__,'glm-quantize')
    run_quantization(config,args.output,config_pin)

if __name__=='__main__':main()
