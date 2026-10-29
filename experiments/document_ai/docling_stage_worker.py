"""Separate Egret layout and TableFormer processes under the same HQ lock.

No text recognition is added. Table geometry consumes only a pinned, completed,
physically closed layout stage and retained machine OCR. Native prediction is
bounded at120s independently of SDK startup; the outer supervisor owns RAM/CPU.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import faulthandler
import gc
import json
import os
from pathlib import Path
import sys
import threading
import time
from component_common import RESOURCES,read,sha,pin,save,checked,validate_task,component_preflight,verify_admission,restore_box,rotate_box,valid_box,attach_tokens
from component_worker import materialization,plain,docling_native_cells
from python_cache import apply_cache

def selected_tasks(plan,start=0,count=None):
    tasks=plan['tasks'];count=len(tasks)-start if count is None else count
    if type(start) is not int or type(count) is not int or start<0 or not 0<count<=64 or start+count>len(tasks):raise ValueError('Explicit source-only slice must contain1..64 existing plan tasks')
    return tasks[start:start+count]

def actual_upstream(summary_path,summary_sha,resource_path,resource_sha,plan,registry_pin,chosen_tasks=None):
    chosen_tasks=plan['tasks'] if chosen_tasks is None else chosen_tasks
    summary=read(checked({'path':str(summary_path),'sha256':summary_sha}));resource=read(checked({'path':str(resource_path),'sha256':resource_sha}))
    if summary.get('status')!='COMPLETE' or summary.get('component')!='docling' or summary.get('stage')!='layout' or summary.get('registry')!=registry_pin:raise ValueError('Exact completed actual Docling layout required')
    if summary.get('new_text_OCR_calls')!=0 or summary.get('optimizer_updates')!=0 or summary.get('pages_completed')!=len(chosen_tasks) or summary.get('actual_completed_layout_model_calls')!=len(chosen_tasks):raise ValueError('Upstream layout count/recognition scope differs')
    if resource.get('actual_exit_code')!=0 or resource.get('failure') is not None or resource.get('stop_reason') is not None or resource.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True:raise ValueError('Upstream layout lifecycle not safely closed')
    if resource.get('logs_finalized_after_owned_cleanup') is not True:raise ValueError('Upstream logs/lifecycle not final')
    if resource.get('worker_summary')!=pin(summary_path) or not 0<resource.get('peak_owned_process_tree_RSS_bytes',0)<=RESOURCES['maximum_own_process_tree_RSS_bytes'] or resource.get('minimum_free_RAM_bytes',0)<RESOURCES['stop_free_RAM_bytes']:raise ValueError('Upstream layout resource/source proof differs')
    pages={}
    for record in summary['page_results']:
        page=read(checked(record))
        if page['page'] in pages:raise ValueError('Duplicate upstream page')
        pages[page['page']]=(record,page)
    if set(pages)!={t['page'] for t in chosen_tasks}:raise ValueError('Layout/task union differs')
    for task in chosen_tasks:
        record,page=pages[task['page']]
        if page.get('contract')!='document-ai-original-frame-geometry.v1' or page.get('source_image')!=task['source_image'] or page.get('source_size')!=task['source_size'] or page.get('source_frame')!='original_image' or page.get('rotation_ccw')!=task.get('rotation_ccw',0):raise ValueError('Upstream geometry does not bind original source frame')
        if page.get('new_text_OCR_calls')!=0 or page.get('assistant_image_transcription') is not False or page.get('layout_model_calls')!=1:raise ValueError('Upstream stage contains unpermitted recognition')
    return summary,pages

def native_call(output,name,fn):
    """Pure inference has no optimizer/checkpoint to lose; retain timeout proof."""
    start=time.monotonic();save(output/(name+'.PREDICT_STARTED.json'),{'utc':datetime.now(timezone.utc).isoformat(),'maximum_native_predict_seconds':120})
    def timeout():
        try:save(output/(name+'.PREDICT_TIMEOUT.json'),{'elapsed_seconds':time.monotonic()-start,'maximum_native_predict_seconds':120,'optimizer_updates':0})
        finally:os._exit(124)
    timer=threading.Timer(120,timeout);timer.daemon=True;timer.start()
    try:
        result=fn()
        save(output/(name+'.PREDICT_COMPLETED.json'),{'utc':datetime.now(timezone.utc).isoformat(),
             'elapsed_seconds':time.monotonic()-start,'maximum_native_predict_seconds':120})
        return result
    finally:timer.cancel()

def numpy_torch_abi(torch,progress):
    progress('NUMPY_TORCH_ABI_STARTED')
    import numpy as np
    try:
        original=np.arange(4,dtype=np.int64).reshape(2,2);tensor=torch.from_numpy(original)
        if int(tensor.sum().item())!=6 or not np.array_equal(tensor.numpy(),original) or tensor.device.type!='cpu':raise ValueError('Native NumPy/Torch CPU roundtrip differs')
    except BaseException as exc:
        progress('NUMPY_TORCH_ABI_FAILED',{'error':type(exc).__name__,'message':str(exc)});raise
    proof={'status':'PASS','versions':{'numpy':np.__version__,'torch':torch.__version__},'native_cpu_array_sum':6,'numpy_tensor_roundtrip':True,
           'model_calls':0,'source_image_decodes':0}
    progress('NUMPY_TORCH_ABI_PASSED',proof);return proof

def make_layout(root,progress):
    progress('TORCH_IMPORT_STARTED');import torch
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if torch.get_num_threads()!=1 or torch.get_num_interop_threads()!=1:raise ValueError('Native Torch thread binding differs')
    abi=numpy_torch_abi(torch,progress)
    progress('TRANSFORMERS_IMPORT_STARTED')
    from transformers import DFineForObjectDetection,RTDetrImageProcessor
    progress('EGRET_CONSTRUCTION_STARTED')
    processor=RTDetrImageProcessor.from_pretrained(root/'docling-layout',local_files_only=True)
    model=DFineForObjectDetection.from_pretrained(root/'docling-layout',local_files_only=True).to('cpu').eval()
    progress('EGRET_CONSTRUCTION_COMPLETED');return torch,processor,model,abi

def table_options(a):
    if a.stage!='tables':return None
    return {'do_matching':a.native_cell_matching=='enabled','evaluation_predictions_supplied':False,
            'cpu_backend':a.table_cpu_backend,'mkldnn_enabled':a.table_cpu_backend=='native'}

def configure_fault_diagnostics():
    # Periodic asynchronous thread walking itself has reported CPython races.
    # Fatal exception capture, phase files and all parent/watchdog limits remain.
    faulthandler.enable()
    return {'fatal_exception_handler':True,'periodic_thread_dump':False,
            'supervisor_deadlines_and_resource_limits_unchanged':True}

def bounded_native_tables(regions,size,query_bound):
    if type(query_bound) is not int or query_bound<=0 or len(regions)>query_bound:
        raise ValueError('Native regions exceed the pinned layout model query bound')
    ids=[r['id'] for r in regions]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate native region IDs')
    return [r for r in regions if r['label'].casefold()=='table' and valid_box(r['bbox'],size)]

def install_table_boundary_hooks(model,progress):
    """Observe the first real call at native boundaries; hooks replace no tensor."""
    neural=model.get_model();seen=set();handles=[]
    modules=[('CNN_ENCODER',neural._encoder),('CNN_FIRST_CONV',neural._encoder._resnet[0]),
             ('TAG_ENCODER',neural._tag_transformer._encoder),('TAG_DECODER',neural._tag_transformer._decoder)]
    for name,module in modules:
        def before(owner,args,label=name):
            key=label+'_STARTED'
            if key not in seen:
                seen.add(key);shape=getattr(args[0],'shape',None) if args else None
                progress(key,{'first_input_shape':list(shape) if shape is not None else None})
        def after(owner,args,value,label=name):
            key=label+'_COMPLETED'
            if key not in seen:seen.add(key);progress(key)
        handles.extend([module.register_forward_pre_hook(before),module.register_forward_hook(after)])
    return handles

def make_tables(root,progress,backend):
    progress('TORCH_IMPORT_STARTED');import torch
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if torch.get_num_threads()!=1 or torch.get_num_interop_threads()!=1:raise ValueError('Native Torch thread binding differs')
    abi=numpy_torch_abi(torch,progress)
    if backend not in ('native','aten'):raise ValueError('Explicit supported CPU backend required')
    torch.backends.mkldnn.enabled=backend=='native'
    backend_proof={'cpu_backend':backend,'mkldnn_enabled':bool(torch.backends.mkldnn.enabled),
                   'mkldnn_available':bool(torch.backends.mkldnn.is_available())}
    if backend_proof['mkldnn_enabled']!=(backend=='native'):raise ValueError('Native CPU backend binding differs')
    progress('TABLE_CPU_BACKEND_BOUND',backend_proof)
    progress('TABLEFORMER_SDK_IMPORT_STARTED')
    import docling_ibm_models.tableformer.common as common
    from docling_ibm_models.tableformer.data_management.tf_predictor import TFPredictor
    folder=root/'tableformer'/'model_artifacts'/'tableformer'/'fast'
    config=common.read_config(str(folder/'tm_config.json'));config['model']['save_dir']=str(folder)
    progress('TABLEFORMER_CONSTRUCTION_STARTED');model=TFPredictor(config,device='cpu',num_threads=1)
    progress('TABLEFORMER_CONSTRUCTION_COMPLETED');return model,abi,backend_proof

def table_geometry_predict(model,page,bbox,native_cell_matching):
    """Both documented SDK routes run model.predict; no eval answers supplied."""
    if type(native_cell_matching) is not bool:raise ValueError('Explicit native matching selection required')
    return model.multi_table_predict(page,[bbox.copy()],do_matching=native_cell_matching)

def execute(a,plan,registry,proof):
    verify_admission(a.admission,a.admission_sha256,__file__,'docling')
    if not component_preflight(registry,'docling')['admitted_for_bounded_canary']:raise ValueError('Missing or oversized Docling dependencies')
    chosen=selected_tasks(plan,a.slice_start,a.slice_count);upstream=None;upstream_pages={}
    if a.stage=='tables':
        upstream,upstream_pages=actual_upstream(a.upstream_layout_summary,a.upstream_layout_summary_sha256,a.upstream_resource,a.upstream_resource_sha256,plan,pin(a.registry),chosen)
        if upstream.get('plan')!=pin(a.plan) or upstream.get('selected_pages')!=[t['page'] for t in chosen] or upstream.get('full_source_inventory_pages')!=len(plan['tasks']):raise ValueError('Layout belongs to another parent plan or slice')
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=False);began=time.monotonic();phase=0
    save(output/'STARTED.json',{'contract':'document-ai-split-docling-stage.v1','component':'docling','stage':a.stage,'plan':pin(a.plan),'registry':pin(a.registry),
        'worker':pin(__file__),'upstream_layout_summary':pin(a.upstream_layout_summary) if upstream else None,'model_predict_calls_started':0,
        'native_cell_matching':a.native_cell_matching=='enabled' if a.stage=='tables' else None,
        'native_table_options':table_options(a),
        'full_source_inventory_pages':len(plan['tasks']),'selected_pages':[t['page'] for t in chosen],'slice_start':a.slice_start,'slice_count':len(chosen)})
    def progress(label,evidence=None):
        nonlocal phase
        phase+=1;save(output/(str(phase).zfill(2)+'-'+label+'.json'),{'phase':label,'elapsed_seconds':time.monotonic()-began,'utc':datetime.now(timezone.utc).isoformat(),'evidence':evidence})
    fault_diagnostics=configure_fault_diagnostics()
    save(output/'FAULT_DIAGNOSTICS.json',fault_diagnostics)
    def startup_timeout():
        try:save(output/'SDK_STARTUP_TIMEOUT.json',{'elapsed_seconds':time.monotonic()-began,'maximum_SDK_startup_seconds':480,'optimizer_updates':0})
        finally:os._exit(125)
    startup_watchdog=threading.Timer(480,startup_timeout);startup_watchdog.daemon=True;startup_watchdog.start()
    model_root=Path(proof['model_root']);completed=[];layout_calls=0;table_calls=0;started=0;decodes=0;hooks=[];runtime_cache=None
    layout_config=model_root/'docling-layout'/'config.json'
    query_bound=read(layout_config)['num_queries']
    if type(query_bound) is not int or query_bound<=0:raise ValueError('Pinned layout config must declare a finite query count')
    try:
        if a.runtime_cache_manifest:
            progress('VERIFIED_PYTHON_CACHE_STARTED')
            runtime_cache=apply_cache(a.runtime_cache_manifest,a.runtime_cache_manifest_sha256)
            save(output/'RUNTIME_CACHE_SELECTION.json',{'manifest':runtime_cache,'read_only':True,'cache_prefix':sys.pycache_prefix})
            progress('VERIFIED_PYTHON_CACHE_READ_ONLY_SELECTED',{'manifest':runtime_cache})
        progress('CV_IMPORT_STARTED');import cv2
        cv2.setNumThreads(1)
        if a.stage=='layout':
            torch,processor,model,abi=make_layout(model_root,progress)
            if model.config.num_queries!=query_bound:raise ValueError('Actual native model query count differs from pinned layout config')
        else:
            model,abi,backend_proof=make_tables(model_root,progress,a.table_cpu_backend)
            save(output/'ACTUAL_NATIVE_TABLE_BACKEND.json',backend_proof)
            hooks=install_table_boundary_hooks(model,progress)
        if upstream and upstream.get('runtime_versions')!=abi['versions']:raise ValueError('Layout/TableFormer runtime versions differ')
        save(output/'ACTUAL_RUNTIME_ABI_PROOF.json',abi)
        import torch as native_torch
        device=next(model.parameters()).device.type if a.stage=='layout' else str(model.get_device())
        cpu_binding={'torch_compute_threads':native_torch.get_num_threads(),'torch_interop_threads':native_torch.get_num_interop_threads(),
                     'opencv_threads':cv2.getNumThreads(),'model_device':device}
        if cpu_binding!={'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'model_device':'cpu'}:raise ValueError('Actual native CPU/thread binding differs')
        save(output/'ACTUAL_NATIVE_CPU_BINDING.json',cpu_binding)
        startup_watchdog.cancel()
        from PIL import Image
        for task in chosen:
            image_path=checked(task['source_image']);angle=task.get('rotation_ccw',0)
            with Image.open(image_path) as im:
                if list(im.size)!=task['source_size']:raise ValueError('Raster dimensions differ from pinned original frame')
                image=im.convert('RGB');decodes+=1
            if angle:image=image.transpose({90:Image.Transpose.ROTATE_90,180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_270}[angle])
            rejected=[];cells=[];upstream_pin=None;per_layout=0;per_tables=0
            try:
                if a.stage=='layout':
                    def predict_layout():
                        inputs=processor(images=[image],return_tensors='pt')
                        with torch.inference_mode():value=model(**inputs)
                        return processor.post_process_object_detection(value,target_sizes=torch.tensor([[image.height,image.width]]),threshold=.6)[0]
                    started+=1;value=native_call(output,'page-'+str(task['page']).zfill(4)+'-layout',predict_layout);layout_calls+=1;per_layout=1
                    raw=plain(value);regions=[]
                    for i,(label,score,box) in enumerate(zip(value['labels'].tolist(),value['scores'].tolist(),value['boxes'].tolist())):
                        try:b=restore_box(box,task['source_size'],angle)
                        except ValueError:rejected.append({'id':'layout-'+str(i),'reason':'native_region_outside_frame_no_clipping'});continue
                        regions.append({'id':'layout-'+str(i),'label':model.config.id2label[label],'score':score,'bbox':b,'coordinate_frame':'original_image'})
                else:
                    import numpy as np
                    upstream_pin,upstream_page=upstream_pages[task['page']];regions=upstream_page['regions']
                    tables=bounded_native_tables(regions,task['source_size'],query_bound)
                    rotated=[{**t,'bbox':rotate_box(t['bbox'],task['source_size'],angle)} for t in task.get('tokens',[])]
                    page={'width':image.width,'height':image.height,'image':np.asarray(image),'tokens':[{'id':i,'text':t['text'],'bbox':dict(zip(('l','t','r','b'),t['bbox']),coord_origin='TOPLEFT')} for i,t in enumerate(rotated)]}
                    outputs=[]
                    for table in tables:
                        bbox=rotate_box(table['bbox'],task['source_size'],angle);started+=1
                        value=native_call(output,'page-'+str(task['page']).zfill(4)+'-'+table['id'],lambda:table_geometry_predict(model,page,bbox,a.native_cell_matching=='enabled'))
                        if len(value)!=1:raise ValueError('One table request must yield one native result')
                        outputs.extend(value);table_calls+=1;per_tables+=1
                    raw={'upstream_layout_observation':upstream_pin,'tables':plain(outputs),
                         'native_table_options':table_options(a)}
                    for cell in docling_native_cells(outputs,[t['id'] for t in tables]):
                        try:b=restore_box(cell['bbox'],task['source_size'],angle)
                        except ValueError:rejected.append({'id':cell['id'],'reason':'native_cell_outside_frame_no_clipping'});continue
                        cells.append({**cell,'bbox':b,'coordinate_frame':'original_image'})
                association=attach_tokens(cells,task.get('tokens',[]),task['source_size'])
                page_result={'contract':'document-ai-original-frame-geometry.v1','component':'docling','stage':a.stage,'page':task['page'],'company':task.get('company'),
                    'source_image':task['source_image'],'source_size':task['source_size'],'source_frame':'original_image','rotation_ccw':angle,
                    'regions':regions,'cell_association':association,'rejected_native_geometry':rejected,'raw_native_result':raw,
                    'layout_model_calls':per_layout,'table_model_calls':per_tables,'new_text_OCR_calls':0,'assistant_image_transcription':False,
                    'upstream_layout_observation':upstream_pin,'upstream_layout_summary':pin(a.upstream_layout_summary) if upstream else None,
                    'upstream_layout_resource':pin(a.upstream_resource) if upstream else None,'endpoint_accuracy_gain':None,
                    'native_table_options':table_options(a),
                    'native_cell_matching':a.native_cell_matching=='enabled' if a.stage=='tables' else None,
                    'native_table_routing':{'detected_valid_tables':len(tables),'routed_tables':per_tables,
                        'layout_model_query_bound':query_bound,'skipped_due_to_fixed_page_cap':0} if a.stage=='tables' else None,
                    'geometry_detection_is_not_verified_product_table':True}
                dest=output/('page-'+str(task['page']).zfill(4)+'.json');save(dest,page_result);completed.append(pin(dest))
            finally:image.close()
        del model;gc.collect()
    finally:
        for handle in hooks:handle.remove()
        startup_watchdog.cancel()
    result={'contract':'document-ai-component-trial.v1','status':'COMPLETE','component':'docling','stage':a.stage,'plan':pin(a.plan),'registry':pin(a.registry),
        'worker':pin(__file__),'materialization':pin(a.materialization),'pages_completed':len(completed),'page_results':completed,
        'full_source_inventory_pages':len(plan['tasks']),'selected_pages':[t['page'] for t in chosen],
        'slice_start':a.slice_start,'slice_count':len(chosen),'complete_stage_shard':len(completed)==len(chosen),
        'complete_submitted_plan':len(completed)==len(plan['tasks']),
        'complete_full_inventory':plan['mode']=='full' and len(completed)==len(plan['tasks'])==484,
        'actual_model_predict_calls_started':started,'actual_completed_layout_model_calls':layout_calls,'actual_completed_table_model_calls':table_calls,
        'upstream_layout_summary':pin(a.upstream_layout_summary) if upstream else None,'source_image_decodes':decodes,'elapsed_seconds':time.monotonic()-began,
        'actual_native_CPU_binding':pin(output/'ACTUAL_NATIVE_CPU_BINDING.json'),
        'runtime_versions':abi['versions'],'actual_runtime_ABI_proof':pin(output/'ACTUAL_RUNTIME_ABI_PROOF.json'),
        'native_table_options':table_options(a),
        'actual_native_table_backend':pin(output/'ACTUAL_NATIVE_TABLE_BACKEND.json') if a.stage=='tables' else None,
        'native_cell_matching':a.native_cell_matching=='enabled' if a.stage=='tables' else None,
        'native_layout_query_bound':{'source':pin(layout_config),'num_queries':query_bound},
        'fault_diagnostics':pin(output/'FAULT_DIAGNOSTICS.json'),
        'runtime_cache':runtime_cache,'runtime_cache_selection':pin(output/'RUNTIME_CACHE_SELECTION.json') if runtime_cache else None,
        'new_text_OCR_calls':0,'optimizer_updates':0,'endpoint_score_status':'NOT_EVALUATED','endpoint_gain':None,'known_development_set':True,'production_activation':False}
    save(output/'SUMMARY.json',result);return result

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--registry',type=Path,required=True);ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--plan-sha256',required=True)
    ap.add_argument('--stage',choices=['layout','tables'],required=True);ap.add_argument('--materialization',type=Path);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--slice-start',type=int,default=0);ap.add_argument('--slice-count',type=int)
    ap.add_argument('--native-cell-matching',choices=['enabled','disabled'],default='enabled')
    ap.add_argument('--table-cpu-backend',choices=['native','aten'],default='native')
    ap.add_argument('--runtime-cache-manifest',type=Path);ap.add_argument('--runtime-cache-manifest-sha256')
    ap.add_argument('--upstream-layout-summary',type=Path);ap.add_argument('--upstream-layout-summary-sha256');ap.add_argument('--upstream-resource',type=Path);ap.add_argument('--upstream-resource-sha256')
    ap.add_argument('--execute',action='store_true');ap.add_argument('--admission',type=Path);ap.add_argument('--admission-sha256');a=ap.parse_args()
    if sha(a.plan)!=a.plan_sha256:raise ValueError('Plan SHA differs')
    plan=read(a.plan);registry=read(a.registry)
    if plan.get('contract')!='root-document-ai-source-only-trial-plan.v1' or plan.get('approved_by')!='root' or plan.get('component')!='docling' or plan.get('registry')!=pin(a.registry) or plan.get('resource_policy')!=RESOURCES:raise ValueError('Root Docling plan/source registry required')
    tasks=plan['tasks'];limit={'canary':1,'pilot':16,'full':484}[plan['mode']]
    if not 0<len(tasks)<=limit or len({t['page'] for t in tasks})!=len(tasks) or plan['mode']=='full' and len(tasks)!=484:raise ValueError('Stage source union differs')
    for task in tasks:validate_task(task)
    chosen=selected_tasks(plan,a.slice_start,a.slice_count)
    if not a.execute:print(json.dumps({'valid':True,'executed':False,'stage':a.stage,'full_source_inventory_pages':len(tasks),'selected_pages':[t['page'] for t in chosen],'model_calls':0}));return
    if not a.materialization or not a.admission or not a.admission_sha256:raise ValueError('Actual model data and active supervision required')
    if a.stage=='tables' and not all((a.upstream_layout_summary,a.upstream_layout_summary_sha256,a.upstream_resource,a.upstream_resource_sha256)):raise ValueError('Physically closed actual layout required before TableFormer')
    if bool(a.runtime_cache_manifest)!=bool(a.runtime_cache_manifest_sha256):raise ValueError('Cache selection must include exact manifest SHA')
    proof=materialization(registry,'docling',a.materialization,a.registry)
    print(json.dumps(execute(a,plan,registry,proof),ensure_ascii=False))

if __name__=='__main__':main()
