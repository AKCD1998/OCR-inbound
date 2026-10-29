"""Native-stage lineage/closure metadata only; never imports a model runtime."""
from pathlib import Path,PureWindowsPath
import re
from component_common import RESOURCES,checked,read

def record_key(record):
    p=PureWindowsPath(record['path'])
    name=str(p).casefold() if p.drive else str(Path(record['path']).resolve())
    return name,record['sha256']

def resource_closed(resource):
    if (resource.get('actual_exit_code')!=0 or resource.get('failure') is not None
      or resource.get('stop_reason') is not None
      or resource.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or resource.get('logs_finalized_after_owned_cleanup') is not True
      or not 0<resource.get('peak_owned_process_tree_RSS_bytes',0)<=RESOURCES['maximum_own_process_tree_RSS_bytes']
      or resource.get('minimum_free_RAM_bytes',0)<RESOURCES['stop_free_RAM_bytes']):raise ValueError('Actual native resource/owned closure proof required')

def witness(summary_records,supervision_records,check=checked):
    observed={}
    for pin in supervision_records:
        execution=read(check(pin))
        if (execution.get('status')!='COMPLETE' or execution.get('shared_lock_released_after_owned_closure') is not True
          or execution.get('failure') is not None):raise ValueError('Actual closed native supervision required')
        for resource in execution.get('resources',[]):
            record=resource.get('worker_summary')
            if record:observed[record_key(record)]=resource
    for record in summary_records:
        check(record)
        if record_key(record) not in observed:raise ValueError('Native summary has no actual closed supervisor witness')
        resource_closed(observed[record_key(record)])
    return observed

def runtime_proof(summary,check=checked):
    if summary.get('component')!='docling' or summary.get('stage') not in ('layout','tables'):return None
    abi=read(check(summary['actual_runtime_ABI_proof']));cpu=read(check(summary['actual_native_CPU_binding']))
    versions=summary.get('runtime_versions')
    if (not isinstance(versions,dict) or not all(isinstance(versions.get(k),str) and versions[k] for k in ('numpy','torch'))
      or abi.get('status')!='PASS' or abi.get('versions')!=versions or abi.get('native_cpu_array_sum')!=6
      or abi.get('numpy_tensor_roundtrip') is not True or abi.get('model_calls')!=0 or abi.get('source_image_decodes')!=0
      or cpu!={'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'model_device':'cpu'}):raise ValueError('Actual Docling ABI/CPU/runtime identity differs')
    result={'runtime_versions':versions,'CPU_binding':cpu,'ABI_proof':summary['actual_runtime_ABI_proof'],
      'CPU_proof':summary['actual_native_CPU_binding']}
    if summary.get('stage')=='tables':
        worker_identity(summary);check(summary['worker']);options=table_options(summary)
        backend=read(check(summary['actual_native_table_backend']))
        if (not isinstance(backend,dict) or set(backend)!={'cpu_backend','mkldnn_enabled','mkldnn_available'}
          or backend.get('cpu_backend')!=options['cpu_backend'] or backend.get('mkldnn_enabled') is not options['mkldnn_enabled']
          or type(backend.get('mkldnn_available')) is not bool
          or options['mkldnn_enabled'] and not backend['mkldnn_available']):raise ValueError('Actual table backend does not match declared native options')
        result.update(table_backend=backend,table_backend_proof=summary['actual_native_table_backend'])
    return result

def validate_table_options(options):
    if (not isinstance(options,dict) or set(options)!={'do_matching','evaluation_predictions_supplied','cpu_backend','mkldnn_enabled'}
      or type(options.get('do_matching')) is not bool or options.get('evaluation_predictions_supplied') is not False
      or type(options.get('mkldnn_enabled')) is not bool or options.get('cpu_backend') not in ('aten','mkldnn')
      or options['mkldnn_enabled']!=(options['cpu_backend']=='mkldnn')):raise ValueError('Actual Docling table options/backend are missing, contradictory or use evaluation predictions')
    return options

def table_options(summary):
    if summary.get('component')!='docling' or summary.get('stage')!='tables':return None
    return validate_table_options(summary.get('native_table_options'))

def worker_identity(summary):
    if summary.get('native_shard_summaries'):
        value=summary.get('worker_sha256')
        if summary.get('component')=='docling' and summary.get('stage')=='tables' and not isinstance(value,str):raise ValueError('Aggregated table worker identity required')
        if value is not None and not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('Aggregated worker identity differs')
        return value
    record=summary.get('worker')
    if summary.get('component')=='docling' and summary.get('stage')=='tables':
        if not isinstance(record,dict) or not isinstance(record.get('path'),str) or not re.fullmatch('[0-9a-f]{64}',record.get('sha256','')):raise ValueError('Actual table worker identity required')
    return record.get('sha256') if isinstance(record,dict) else None

def table_upstream(summary,observations,check=checked):
    if summary.get('component')!='docling' or summary.get('stage')!='tables':return []
    options=table_options(summary)
    runtime_proof(summary,check);selected=summary.get('selected_pages');actual=set(observations)
    if (not isinstance(selected,list) or len(selected)!=len(set(selected)) or set(selected)!=actual
      or summary.get('pages_completed')!=len(actual) or summary.get('complete_stage_shard') is not True):raise ValueError('Actual Docling table shard coverage differs')
    seen={};proofs=[]
    for n,page in observations.items():
        upstream_pin=page.get('upstream_layout_summary');resource_pin=page.get('upstream_layout_resource')
        layout_pin=page.get('upstream_layout_observation')
        if not upstream_pin or not resource_pin or not layout_pin:raise ValueError('Actual table page is missing its upstream layout chain')
        key=record_key(upstream_pin)
        if key not in seen:
            upstream=read(check(upstream_pin));resource=read(check(resource_pin));resource_closed(resource)
            runtime_proof(upstream,check)
            if (upstream.get('status')!='COMPLETE' or upstream.get('stage')!='layout'
              or any(upstream.get(k)!=summary.get(k) for k in ('component','plan','registry','materialization','runtime_versions','selected_pages','full_source_inventory_pages'))
              or upstream.get('pages_completed')!=len(actual) or upstream.get('actual_completed_layout_model_calls')!=len(actual)
              or upstream.get('complete_stage_shard') is not True or upstream.get('new_text_OCR_calls')!=0
              or upstream.get('optimizer_updates')!=0 or resource.get('worker_summary')!=upstream_pin):raise ValueError('Layout/table plan, slice, runtime or lifecycle differs')
            records={read(check(r))['page']:r for r in upstream['page_results']}
            if len(records)!=len(upstream['page_results']) or set(records)!=actual:raise ValueError('Upstream layout shard source union differs')
            seen[key]=(upstream,records,resource_pin);proofs.append({'layout_summary':upstream_pin,'layout_resource':resource_pin})
        upstream,records,original_resource=seen[key]
        layout=read(check(layout_pin))
        if (resource_pin!=original_resource or page.get('native_table_options')!=options
          or page.get('stage')!='tables' or records.get(n)!=layout_pin or layout.get('contract')!='document-ai-original-frame-geometry.v1'
          or layout.get('stage')!='layout' or layout.get('component')!='docling'
          or any(layout.get(k)!=page.get(k) for k in ('page','source_image','source_size','source_frame','rotation_ccw','regions'))
          or layout.get('source_frame')!='original_image' or layout.get('layout_model_calls')!=1
          or layout.get('new_text_OCR_calls')!=0 or layout.get('assistant_image_transcription') is not False):raise ValueError('Table geometry does not retain its actual layout source')
    return proofs

def model_identity(summary):
    result={'component':summary['component'],'stage':summary.get('stage','combined'),
      'registry_sha256':summary['registry']['sha256'],'model_data_sha256':summary['materialization']['sha256'],
      'runtime_versions':summary.get('runtime_versions'),'native_table_options':table_options(summary)}
    if summary.get('native_shard_summaries') and 'actual_worker_sha256s' in summary:
        workers=summary['actual_worker_sha256s']
        if (not isinstance(workers,list) or not workers or workers!=sorted(set(workers))
          or any(not isinstance(s,str) or not re.fullmatch('[0-9a-f]{64}',s) for s in workers)
          or not re.fullmatch('[0-9a-f]{64}',summary.get('model_recipe_family_sha256',''))):raise ValueError('Actual mixed-source identity/approved recipe family required')
        return {**result,'actual_worker_sha256s':workers,'model_recipe_family_sha256':summary['model_recipe_family_sha256']}
    return {**result,'worker_sha256':worker_identity(summary)}

def native_totals(summary,observations=None,check=checked):
    upstream={}
    for page in (observations or {}).values():
        record=page.get('upstream_layout_summary')
        if record:upstream[record_key(record)]=record
    for chain in summary.get('actual_upstream_layout_chains',[]):
        record=chain['layout_summary'];upstream[record_key(record)]=record
    if summary.get('upstream_layout_summary'):
        record=summary['upstream_layout_summary'];upstream[record_key(record)]=record
    keys=('actual_model_predict_calls_started','actual_completed_layout_model_calls','actual_completed_table_model_calls')
    own={key:summary.get(key) for key in keys};totals=dict(own)
    for record in upstream.values():
        old=read(check(record))
        for key in keys:
            value=old.get(key)
            if type(value) is not int or value<0:raise ValueError('Actual upstream counters required')
            if type(totals[key]) is not int or totals[key]<0:raise ValueError('Actual current-stage counters required')
            totals[key]+=value
    return {'current_stage':own,'unique_upstream_layout_summaries':list(upstream.values()),
      'all_native_stages_without_double_counting':totals,'unique_original_sources':summary['pages_completed']}
