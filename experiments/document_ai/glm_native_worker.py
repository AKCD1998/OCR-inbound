"""One isolated, bounded HQ GLM batch. Images are read only by automatic tools."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime,timezone
import gc
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import glm_backend as backend
import glm_evidence as evidence
from glm_quantize_worker import close_owned_child
from component_common import checked,pin,read,require_HQ,RESOURCES,save,verify_admission

CONTRACT='document-ai-glm-native-config.v1'
MAX_HTTP_BYTES=2*1024*1024


def response_json(url,payload=None,timeout=30,raw_output=None):
    raw=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(url,data=raw,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        body=response.read(MAX_HTTP_BYTES+1)
    if raw_output is not None:
        with Path(raw_output).open('xb') as stream:
            stream.write(body);stream.flush();os.fsync(stream.fileno())
        save(Path(raw_output).with_suffix('.capture.json'),{'captured_bytes':len(body),
             'capture_truncated':len(body)>MAX_HTTP_BYTES,'wire_body':pin(raw_output)})
    if len(body)>MAX_HTTP_BYTES:raise ValueError('Native HTTP output exceeds explicit bound')
    return json.loads(body.decode('utf-8'))


def consumed_bytes(record,maximum):
    path=Path(record['path'])
    if path.stat().st_size>maximum:raise ValueError('Pinned input exceeds finite byte cap')
    data=path.read_bytes()
    if len(data)>maximum or hashlib.sha256(data).hexdigest()!=record['sha256']:
        raise ValueError('Actual consumed bytes differ from source pin')
    return data


def verified_model_closure(config,model,native):
    """Actual completed preparer/quantizer, never self-consistent file pins alone."""
    verifier_path=checked(config['sources']['quant_verifier'])
    if config['sources']['quant_verifier']['sha256']!='37409eccdf3273fab1ccb9de36b4560cc0505299a1573aecbf5e246b2ab4f150':
        raise ValueError('Selected complete-projector quantization verifier required')
    spec=importlib.util.spec_from_file_location('_glm_closed_quantization_verifier',verifier_path)
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    material,_=verifier.materialization_proof({
        'source_materialization_summary':model['materialization_summary'],
        'closed_materialization_root':model['materialization_root'],
        'projector_source':model['projector_source'],'isolated_python':config['isolated_python']})
    actual_decoder=[x for x in material['artifacts'] if x['role']=='decoder']
    if (len(actual_decoder)!=1 or actual_decoder[0]['file']!=model['decoder']
      or model['decoder']['sha256']!='f0613be35c46bb591234dd14913b7e1972463e4dcd961a57def0b6616438dc35'
      or native['server']!=material['backend']['server'] or native['files']!=material['backend']['files']):
        raise ValueError('Model/backend not derived from actual selected materialization')
    closed=read(checked(model['quantization_root']));summary=read(checked(model['quantization_summary']))
    if (closed.get('status')!='COMPLETE' or closed.get('failure') is not None
      or closed.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or closed.get('shared_lock_released_after_owned_closure') is not True
      or summary.get('status')!='COMPLETE' or summary.get('failure') is not None
      or summary.get('worker',{}).get('sha256')!=config['sources']['quant_verifier']['sha256']
      or summary.get('quantization_completed')!=1 or summary.get('child_closed') is not True
      or any(summary.get(k)!=0 for k in ('model_calls','source_image_decodes','optimizer_updates'))
      or summary.get('quantized_projector')!=model['projector'] or summary.get('source_projector')!=model['projector_source']
      or summary.get('source_materialization_summary')!=model['materialization_summary']
      or summary.get('closed_materialization_root')!=model['materialization_root']
      or summary.get('source_output_tensor_inventory_equal') is not True):
        raise ValueError('Actual complete quantization lineage required before model load')
    resources=[r for r in closed.get('resources',[]) if r.get('worker_summary')==model['quantization_summary']]
    if len(resources)!=1:raise ValueError('One actual closed quantizer summary required')
    resource=resources[0];argv=resource.get('actual_argv',[])
    if (resource.get('actual_exit_code')!=0 or resource.get('failure') is not None
      or resource.get('stop_reason') is not None or resource.get('child_started') is not True
      or resource.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or resource.get('logs_finalized_after_owned_cleanup') is not True
      or resource.get('peak_owned_process_tree_RSS_bytes',float('inf'))>RESOURCES['maximum_own_process_tree_RSS_bytes']
      or resource.get('minimum_free_RAM_bytes',0)<RESOURCES['stop_free_RAM_bytes']
      or summary['worker']['path'] not in argv or '--config' not in argv or '--config-sha256' not in argv
      or argv[argv.index('--config')+1]!=summary['config']['path']
      or argv[argv.index('--config-sha256')+1]!=summary['config']['sha256']):
        raise ValueError('Quantizer source/argv/resource/physical closure differs')
    serial=read(checked(closed['config']))
    if (serial.get('source',{}).get('sha256')!='87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'
      or serial.get('resource_policy')!=RESOURCES):raise ValueError('Original quantizer supervision required')
    checked(summary['config'])
    return {'materialization_verified':True,'quantization_verified':True,'original_shared_supervision_verified':True}


def prepare_image(request,folder):
    """Whole declared context, exact right-angle orientation, recorded resize."""
    from PIL import Image
    require_HQ();g=request['geometry'];limits=request['limits']
    data=consumed_bytes(request['source_image'],32*1024*1024)
    box=request['roi_upright']
    if box!=[0,0,*g['upright_size']]:raise ValueError('V1 uses complete page context; no cell-only crop')
    with Image.open(io.BytesIO(data)) as original:
        if list(original.size)!=g['original_size'] or original.width*original.height>40_000_000:
            raise ValueError('Actual image dimensions differ or exceed finite decode budget')
        upright=original.convert('RGB')
    try:
        angle=g['orientation_ccw']
        if angle not in (0,90,180,270):raise ValueError('Exact saved orientation required')
        if angle:
            rotated=upright.transpose({90:Image.Transpose.ROTATE_90,180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_270}[angle])
            upright.close();upright=rotated
        if list(upright.size)!=g['upright_size']:raise ValueError('Upright dimensions differ')
        scale=min(1,limits['maximum_long_side']/max(upright.size))
        size=[max(1,int(round(v*scale))) for v in upright.size]
        if size[0]*size[1]>limits['maximum_image_pixels']:raise ValueError('Prepared image exceeds explicit pixel cap')
        if tuple(size)!=upright.size:
            resized=upright.resize(size,Image.Resampling.LANCZOS);upright.close();upright=resized
        path=folder/'input.png';upright.save(path,format='PNG')
    finally:upright.close()
    return {'source':request['source_image'],'prepared':pin(path),'source_geometry':g,'roi_upright':box,
            'actual_source_bytes_consumed_sha256':hashlib.sha256(data).hexdigest(),
            'actual_prepared_size':size,'resampling':'LANCZOS' if scale<1 else 'NONE',
            'resize_scale_requested':scale,'source_context_clipped':False,
            'EXIF_reinterpreted':False,'glyph_or_cell_boxes_invented':False}


def validate_config(config,config_pin):
    if (config.get('contract')!=CONTRACT or config.get('resource_policy')!=RESOURCES
      or config.get('optimizer_updates_allowed') is not False or config.get('production_activation') is not False):
        raise ValueError('Exact isolated GLM native policy required')
    for key in ('backend','evidence','common'):
        checked(config['sources'][key])
    if pin(backend.__file__)!=config['sources']['backend'] or pin(evidence.__file__)!=config['sources']['evidence']:
        raise ValueError('Actual GLM source modules differ')
    if pin(sys.executable)!=config['isolated_python']:raise ValueError('Selected isolated GLM interpreter required')
    if pin(sys.modules['component_common'].__file__)!=config['sources']['common']:
        raise ValueError('Actual original admission helper differs')
    for key in ('load_timeout_seconds','read_timeout_seconds'):
        if type(config.get(key)) is not int or not 1<=config[key]<=600:
            raise ValueError('Explicit bounded load/read deadline required')
    model=read(checked(config['model_binding']));native=read(checked(config['backend_binding']))
    verified_model_closure(config,model,native)
    for record in (model['decoder'],model['projector'],native['server'],*[x['pin'] for x in native['files']]):checked(record)
    memory=backend.memory_preflight(Path(model['decoder']['path']).stat().st_size,Path(model['projector']['path']).stat().st_size,
                                    context_tokens=config['context_tokens'],reservations=config['reservations'])
    if memory['status']!='BOUNDED_CANARY_REQUIRED':raise ValueError('All-weights/KV/vision/runtime budget exceeds original cap')
    plan=read(checked(config['plan']))
    if plan.get('contract')!=evidence.PLAN or plan.get('expected_values_used') is not False:raise ValueError('Source-only pre-gate GLM plan required')
    ids=config['request_ids']
    if not isinstance(ids,list) or not 1<=len(ids)<=4 or len(set(ids))!=len(ids):raise ValueError('One-to-four serial requests per closed batch')
    requests=[x for x in plan['requests'] if x['request_id'] in ids]
    if [x['request_id'] for x in requests]!=ids:raise ValueError('Prospective plan order and unique requests required')
    prompt=read(checked(config['prompt_binding']))
    for req in requests:
        if (not evidence.validate_limits(req['limits']) or req['prompt']!=prompt['prompt']
          or req['limits']['context_tokens']!=config['context_tokens']
          or req['limits']['maximum_new_tokens']!=config['max_output_tokens']):raise ValueError('Fixed prompt/image/output/context limits differ')
    identity={'model':config['model_binding'],'backend':config['backend_binding'],
              'prompt':config['prompt_binding'],'config':config_pin}
    return model,native,requests,identity,memory


def execute(config,config_pin,output):
    require_HQ();model,native,requests,identity,memory=validate_config(config,config_pin)
    cutoff=datetime.fromisoformat(config['cutoff_utc']).timestamp()
    if type(config['maximum_seconds']) is not int or not 0<config['maximum_seconds']<=1800:
        raise ValueError('Finite native batch deadline required')
    if datetime.now(timezone.utc).timestamp()+config['maximum_seconds']+120>cutoff:
        raise ValueError('Native batch would cross clock-out boundary')
    allowed=Path(r'D:\OCR-Experiments\document-ai-20261028\glm-ocr-20261030').resolve()
    if not output.resolve().is_relative_to(allowed) or output.exists():raise ValueError('New isolated native output required')
    output.mkdir(parents=True);began=time.monotonic();end=began+config['maximum_seconds'];process=None;results=[];load_seconds=None;http_started=0;http_json_received=0
    def progress(phase,**values):
        with (output/'PROGRESS.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'phase':phase,'elapsed_seconds':time.monotonic()-began,**values})+'\n');stream.flush()
    save(output/'CONFIG.json',config);save(output/'PROSPECTIVE_MEMORY.json',memory)
    prepared=[]
    for req in requests:
        folder=output/req['request_id'];folder.mkdir()
        save(folder/'REQUEST.json',req);proof=prepare_image(req,folder);save(folder/'IMAGE_PROOF.json',proof)
        prepared.append((req,folder,proof))
    gc.collect()
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    argv=backend.server_command(native['server']['path'],model['decoder']['path'],model['projector']['path'],
         port=port,context_tokens=config['context_tokens'],max_output_tokens=config['max_output_tokens'],image_max_tokens=config['image_max_tokens'])
    save(output/'SERVER_ARGV.json',{'actual_argv':argv,'external_HTTP':False})
    stdout=output/'server.stdout.log';stderr=output/'server.stderr.log';failure=None;closed=False
    try:
        with stdout.open('xb') as out,stderr.open('xb') as err:
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            env.update({k:'1' for k in ('OMP_NUM_THREADS','OMP_THREAD_LIMIT','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')})
            started=time.monotonic();process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            import psutil
            owned=psutil.Process(process.pid);created=owned.create_time()
            progress('SERVER_STARTED',pid=process.pid,creation_time=created)
            url='http://127.0.0.1:'+str(port)
            while True:
                if process.poll() is not None:raise RuntimeError('Native backend exited before readiness')
                if time.monotonic()>min(end,started+config['load_timeout_seconds']):raise TimeoutError('Native model/vision load deadline')
                try:
                    if response_json(url+'/health',timeout=2).get('status')=='ok':break
                except (urllib.error.URLError,TimeoutError,ConnectionError):pass
                time.sleep(.25)
            if owned.create_time()!=created:raise ValueError('Native backend PID creation identity changed')
            listeners=[x for x in owned.net_connections(kind='tcp') if x.status=='LISTEN' and x.laddr.port==port and x.laddr.ip=='127.0.0.1']
            if len(listeners)!=1:raise ValueError('Actual local HTTP listener not owned by exact server child')
            load_seconds=time.monotonic()-started;progress('MODEL_AND_VISION_READY',load_seconds=load_seconds)
            for req,folder,proof in prepared:
                if time.monotonic()>=end or process.poll() is not None:raise RuntimeError('Native batch expired or backend closed')
                data=consumed_bytes(proof['prepared'],10*1024*1024);image_url='data:image/png;base64,'+base64.b64encode(data).decode('ascii')
                payload=backend.completion_request(image_url,prompt=req['prompt'],max_output_tokens=config['max_output_tokens'])
                save(folder/'HTTP_REQUEST.json',payload);read_began=time.monotonic()
                http_started+=1;progress('READ_STARTED',request_id=req['request_id'])
                response=response_json(url+'/v1/chat/completions',payload,
                     timeout=max(.1,min(config['read_timeout_seconds'],end-time.monotonic())),raw_output=folder/'HTTP_RESPONSE_BODY.bin')
                http_json_received+=1
                save(folder/'RAW_RESPONSE.json',response);raw_pin=pin(folder/'RAW_RESPONSE.json')
                generation=backend.completion_receipt(response,payload,context_tokens=config['context_tokens'])
                observation=evidence.wrap_response(req,identity,response,raw_pin)
                observation['native_input_proof']={'prepared_image':proof['prepared'],'image_proof':pin(folder/'IMAGE_PROOF.json'),
                                                  'actual_HTTP_request':pin(folder/'HTTP_REQUEST.json'),'plan':config['plan']}
                parsed=evidence.intake(req,observation,identity)
                save(folder/'GENERATION.json',generation);save(folder/'OBSERVATION.json',observation);save(folder/'STRUCTURE.json',parsed)
                result={'request_id':req['request_id'],'page_number':req['page_number'],'observation':pin(folder/'OBSERVATION.json'),
                        'raw_response':raw_pin,'generation':pin(folder/'GENERATION.json'),'structure':pin(folder/'STRUCTURE.json'),
                        'read_seconds':time.monotonic()-read_began,'generation_finished':generation['generation_complete'],
                        'structure_status':parsed['status'],'printed_content_coverage_verified':False}
                results.append(result);progress('READ_RETURNED',**result)
                del data,image_url,payload,response;gc.collect()
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc)}
    finally:
        cleanup_errors=[]
        if process is not None:
            cleanup=close_owned_child(process);closed=cleanup['confirmed_closed'];cleanup_errors=cleanup['errors']
        if not closed and failure is None:
            failure={'type':'OwnedChildClosureUncertain','message':'Original supervisor must verify final closure'}
        save(output/'SERVER_CLOSURE.json',{'server_started':process is not None,'server_closed':closed,
             'actual_exit_code':None if process is None else process.returncode,'failure':failure,'cleanup_errors':cleanup_errors})
    result={'contract':'document-ai-glm-native-batch.v1','status':'EXECUTION_FINISHED' if failure is None and closed else 'FAILED',
            'component':'glm-ocr','executed':True,'worker':pin(__file__),'config':config_pin,'plan':config['plan'],'identity':identity,
            'request_ids':config['request_ids'],'requests_prepared':len(prepared),
            'requests_started':http_started,'responses_returned':http_json_received,'completed_record_count':len(results),
            'HTTP_body_capture_count':sum((folder/'HTTP_RESPONSE_BODY.bin').exists() for _,folder,_ in prepared),
            'requests_not_started':len(requests)-http_started,'started_without_parsed_response':http_started-http_json_received,
            'parsed_response_without_completed_record':http_json_received-len(results),
            'generation_finished_count':sum(x['generation_finished'] for x in results),
            'structure_returned_count':sum(x['structure_status']=='COMPLETE' for x in results),
            'incomplete_or_unstructured_count':http_started-len(results)+sum(not x['generation_finished'] or x['structure_status']!='COMPLETE' for x in results),
            'request_results':results,'model_load_seconds':load_seconds,'elapsed_seconds':time.monotonic()-began,
            'server_closed':closed,'failure':failure,'source_image_decodes':len(prepared),'optimizer_updates':0,
            'baseline_cache_modified':False,'production_activation':False,'assistant_image_reads':0,
            'structured_generation_is_not_verified_full_transcription':True,'model_numeric_OCR_confidence':None}
    save(output/'SUMMARY.json',result)
    if failure is not None or not closed:raise RuntimeError('Native GLM batch failed; inspect source-bound partial artifacts')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--output',required=True);p.add_argument('--admission',required=True);p.add_argument('--admission-sha256',required=True);a=p.parse_args()
    cfg_pin={'path':a.config,'sha256':a.config_sha256};cfg=read(checked(cfg_pin))
    verify_admission(a.admission,a.admission_sha256,__file__,'glm-ocr')
    execute(cfg,cfg_pin,Path(a.output))


if __name__=='__main__':main()
