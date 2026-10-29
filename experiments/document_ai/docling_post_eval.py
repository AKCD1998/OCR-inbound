"""Finite pure post-evaluation after a physically closed full Docling task.

The PowerShell waiter owns waiting. This program never waits for a model task,
imports a model runtime, opens an image, changes a frozen metric, or starts any
child except through the exact audited serial supervisor's run_stage.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import importlib.util
from pathlib import Path
import re
import sys
import time
import traceback
from component_common import RESOURCES,CONTROLLER_SHA256,checked,pin,read,require_HQ,save,sha

SERIAL_SHA='87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'
OWNERSHIP_SHA='620df01cdc5037b922bc6b28586a0d94c8a266c936ebb05a57b42b22a5fefb45'
FULL_PARENT_SHA='7dad9462ce75ecadf9279fd28c255916dfa365ddaa49eace7053e4364c93e96e'
OPTIONS={'do_matching':False,'evaluation_predictions_supplied':False,'cpu_backend':'aten','mkldnn_enabled':False}
STAGES=['control','candidate','paired_score']

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

def validate_config(c,driver,check=checked):
    if (c.get('contract')!='root-HQ-docling-post-eval.v1' or c.get('approved_by')!='root'
      or c.get('driver')!=driver or c.get('resource_policy')!=RESOURCES
      or c.get('production_activation_allowed') is not False):raise ValueError('Root post-evaluation source/resource/no-production config required')
    for record in [c['source'],c['profile'],c['native_config'],c['full_parent_plan'],c['tiny_score'],c['closed_tiny'],*c['pins'].values()]:check(record)
    if (c['source']['sha256']!=SERIAL_SHA or c['pins']['controller']['sha256']!=CONTROLLER_SHA256
      or c['pins']['ownership']['sha256']!=OWNERSHIP_SHA
      or c['full_parent_plan']['sha256']!=FULL_PARENT_SHA
      or c.get('selected_table_options')!=OPTIONS):raise ValueError('Original source/control/options pins differ')
    for key in ('expected_profile_sha256','expected_table_worker_sha256'):
        if not isinstance(c.get(key),str) or not re.fullmatch('[0-9a-f]{64}',c[key]):raise ValueError('Root-frozen profile and accepted table worker identities required')
    if c['profile']['sha256']!=c['expected_profile_sha256']:raise ValueError('Selected root profile differs')
    if type(c.get('maximum_total_seconds')) is not int or not 0<c['maximum_total_seconds']<=7200:raise ValueError('Post-evaluation total must be prospectively bounded <=7200s')
    if not c.get('native_task_name','').startswith('OCR_DOCAI_'):raise ValueError('Exact isolated native task identity required')
    return c

def completion_ready(c,completion,now=None):
    if (completion.get('contract')!='document-ai-native-task-ready.v1'
      or completion.get('task_name')!=c['native_task_name'] or completion.get('native_config')!=c['native_config']
      or type(completion.get('state')) is not int or completion['state']!=3
      or type(completion.get('last_task_result')) is not int or completion['last_task_result']!=0
      or type(completion.get('running_instances')) is not int or completion['running_instances']!=0):raise ValueError('Actual native Task Ready/0/no-instance proof required')
    observed=datetime.fromisoformat(completion['observed_at_utc'].replace('Z','+00:00'))
    if observed.tzinfo is None:raise ValueError('Timezone-aware actual task observation required')
    age=((now or datetime.now(timezone.utc))-observed).total_seconds()
    if not -10<=age<=300:raise ValueError('Fresh post-native task completion receipt required')
    if Path(completion['native_result']['path']).resolve()!=Path(c['native_result_path']).resolve():raise ValueError('Task completion points to another native result')
    return completion['native_result']

def exact_pages(actual,expected):
    return isinstance(actual,list) and all(type(n) is int for n in actual) and actual==expected

def retained_stage(c,entry,expected,stage,reference_summary,check=checked):
    """Check original successful child, even when its source run later failed."""
    from eval_native import resource_closed,runtime_proof,model_identity,table_upstream
    if stage not in ('layout','tables'):raise ValueError('Explicit retained native stage required')
    summary_pin,resource_pin=entry['summary'],entry['resource']
    summary=read(check(summary_pin));resource=read(check(resource_pin))
    origin=read(check(entry['closed_source_supervision']));resource_closed(resource)
    if (origin.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or origin.get('shared_lock_released_after_owned_closure') is not True
      or resource.get('child_started') is not True or resource.get('worker_optimizer_updates_permission') is not False
      or resource.get('worker_summary')!=summary_pin or resource not in origin.get('resources',[])):raise ValueError('Retained stage has no pristine successful source-child closure')
    if (summary.get('status')!='COMPLETE' or summary.get('component')!='docling' or summary.get('stage')!=stage
      or summary.get('plan')!=c['full_parent_plan'] or summary.get('full_source_inventory_pages')!=484
      or not exact_pages(summary.get('selected_pages'),expected) or summary.get('pages_completed')!=len(expected)
      or summary.get('complete_stage_shard') is not True or stage=='layout' and summary.get('actual_completed_layout_model_calls')!=len(expected)
      or summary.get('new_text_OCR_calls')!=0 or summary.get('optimizer_updates')!=0
      or any(summary.get(k)!=reference_summary.get(k) for k in ('registry','materialization','runtime_versions'))):raise ValueError('Retained stage source/model/runtime differs')
    check(summary['worker']);runtime_proof(summary,check)
    if stage=='tables' and model_identity(summary)!=model_identity(reference_summary):raise ValueError('Retained table worker/options/model differ from accepted source')
    plan=read(check(c['full_parent_plan']));tasks={t['page']:t for t in plan['tasks']}
    observed=[];observations={}
    for record in summary['page_results']:
        page=read(check(record));number=page['page']
        if type(number) is not int or number not in tasks:raise ValueError('Retained native page number differs from source inventory')
        task=tasks[number];observed.append(number);observations[number]=page
        if (page.get('contract')!='document-ai-original-frame-geometry.v1'
          or page.get('source_image')!=task['source_image'] or page.get('source_size')!=task['source_size']
          or page.get('source_frame')!='original_image' or page.get('rotation_ccw')!=task.get('rotation_ccw',0)
          or stage=='layout' and page.get('layout_model_calls')!=1 or page.get('new_text_OCR_calls')!=0
          or page.get('assistant_image_transcription') is not False):raise ValueError('Retained original geometry/source frame differs')
    if not exact_pages(observed,expected):raise ValueError('Retained stage page files differ from its partition')
    if stage=='tables':table_upstream(summary,observations,check)
    return summary

def retained_layout(c,entry,expected,table_summary,check=checked):
    return retained_stage(c,entry,expected,'layout',table_summary,check)

def retained_receipt(c,entry,summary,stage,index,expected):
    proof_path=Path(c['native_result_path']).resolve().parent/(stage+'_'+str(index).zfill(3)+'.RETAINED.json')
    proof=read(proof_path)
    if (not exact_pages(proof.get('selected_pages'),expected) or type(proof.get('new_model_calls')) is not int
      or proof.get('source_prediction_identity_relabelled') is not False
      or proof!={'origin_summary':entry['summary'],'origin_resource':entry['resource'],
      'origin_closed_supervision':entry['closed_source_supervision'],'origin_worker':summary['worker'],
      'selected_pages':expected,'new_model_calls':0,'source_prediction_identity_relabelled':False}):raise ValueError('Retained receipt changes original lineage or claims fresh calls')

def retained_partitions(config,key,selections):
    partitions={(selected[0]-1,len(selected)):i for i,selected in enumerate(selections)};retained={}
    for entry in config.get(key,[]):
        start,count=entry.get('slice_start'),entry.get('slice_count')
        if type(start) is not int or type(count) is not int or (start,count) not in partitions:raise ValueError('Retained stage must equal an actual source partition')
        index=partitions[(start,count)]
        if index in retained:raise ValueError('Duplicate retained stage partition')
        retained[index]=entry
    return retained

def native_tables(c,result,config,check=checked):
    """Validate all native resources, returning only actual completed table pins."""
    from eval_native import resource_closed,model_identity
    if (result.get('contract')!='document-ai-HQ-serial-result.v1' or result.get('status')!='COMPLETE'
      or result.get('failure') is not None or result.get('config')!=c['native_config']
      or result.get('driver')!=config.get('docling_full_driver')
      or result.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or result.get('shared_lock_acquired') is not True or result.get('shared_lock_released_after_owned_closure') is not True
      or result.get('complete_full_inventory') is not True or result.get('full_parent_plan')!=c['full_parent_plan']
      or config.get('full_parent_plan')!=c['full_parent_plan']
      or result.get('new_text_OCR_calls')!=0 or result.get('optimizer_updates')!=0):raise ValueError('Actual complete and safely closed fixed484 native result required')
    check(config['docling_full_driver'])
    pages=list(range(1,485))
    if not exact_pages(result.get('actual_layout_pages'),pages) or not exact_pages(result.get('actual_table_stage_pages'),pages):raise ValueError('Actual native layout/table source union must equal integer1..484')
    size=config.get('shard_size')
    if type(size) is not int or not 1<=size<=64:raise ValueError('Source-bound native shard size required')
    selections=[pages[start:start+size] for start in range(0,484,size)]
    retained={'layout':retained_partitions(config,'retained_layout_shards',selections),
      'tables':retained_partitions(config,'retained_table_shards',selections)}
    for stage,field in (('layout','layout'),('tables','table')):
        expected_retained=[n for i,selected in enumerate(selections) if i in retained[stage] for n in selected]
        expected_fresh=[n for i,selected in enumerate(selections) if i not in retained[stage] for n in selected]
        actual_fresh=result.get('fresh_'+field+'_pages',pages if not retained[stage] and stage=='tables' else [])
        if not exact_pages(result.get('retained_'+field+'_pages',[]),expected_retained) or not exact_pages(actual_fresh,expected_fresh):raise ValueError('Fresh and retained '+stage+' inventories must be exact disjoint partitions')
    stage_specs=[(stage+'_'+str(i).zfill(3),stage,i) for i in range(len(selections)) for stage in ('layout','tables') if i not in retained[stage]]
    names=[name for name,_,_ in stage_specs]
    resources=result.get('resources',[])
    if [r.get('stage') for r in resources]!=names:raise ValueError('Only actual fresh native children must be accounted in source-stage order')
    tables={};table_summaries={}
    for (name,stage,index),resource in zip(stage_specs,resources):
        resource_closed(resource)
        if resource.get('child_started') is not True or resource.get('worker_optimizer_updates_permission') is not False:raise ValueError('Actual native inference child/optimizer proof differs')
        record=resource['worker_summary'];summary=read(check(record))
        if (summary.get('status')!='COMPLETE' or summary.get('component')!='docling' or summary.get('stage')!=stage
          or summary.get('plan')!=c['full_parent_plan'] or not exact_pages(summary.get('selected_pages'),selections[index])
          or summary.get('pages_completed')!=len(selections[index]) or summary.get('complete_stage_shard') is not True
          or summary.get('new_text_OCR_calls')!=0 or summary.get('optimizer_updates')!=0):raise ValueError('Actual native child/source partition differs')
        if summary.get('worker',{}).get('sha256')!=c['expected_table_worker_sha256']:raise ValueError('Fresh native worker differs from accepted source')
        if stage=='tables':
            identity=model_identity(summary)
            if identity['worker_sha256']!=c['expected_table_worker_sha256'] or identity['native_table_options']!=OPTIONS:raise ValueError('Full table worker/options differ from accepted canary')
            tables[index]=record;table_summaries[index]=summary
    reference=next(iter(table_summaries.values()),None)
    if reference is None:reference=read(check(config['actual_positive_table_summary']))
    for stage in ('tables','layout'):
        for index,entry in retained[stage].items():
            expected_reference=reference if stage=='tables' else table_summaries[index]
            summary=retained_stage(c,entry,selections[index],stage,expected_reference,check)
            retained_receipt(c,entry,summary,stage,index,selections[index])
            if stage=='tables':tables[index]=entry['summary'];table_summaries[index]=summary
    return [tables[index] for index in range(len(selections))]

def composed_source_witness(c,native_pin,native,config,table_records,check=checked,make_pin=pin):
    """Verify closed source children; never pretend their failed roots succeeded."""
    from eval_native import resource_closed,record_key
    if c.get('allow_composed_retained_table_source_witness') is not True:raise ValueError('Explicit root authority for verification-only retained-table witness required')
    if native.get('status')!='COMPLETE' or native.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True or native.get('shared_lock_released_after_owned_closure') is not True:raise ValueError('Current native source must complete and close before composition')
    resources=deepcopy(native['resources']);roots=[];retained_tables=[];retained_layouts=[];seen_roots=set()
    def original_root(record):
        value=read(check(record))
        if value.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True or value.get('shared_lock_released_after_owned_closure') is not True:raise ValueError('Every original source root must physically close')
        if record_key(record) not in seen_roots:
            seen_roots.add(record_key(record));roots.append({'source_root':record,'readback_pin':make_pin(check(record)),
              'original_status':value.get('status'),'original_failure':value.get('failure'),
              'original_status_relabelled':False,'source_lock_released_after_owned_closure':True})
        return value
    original_root(native_pin)
    table_keys={record_key(record) for record in table_records};seen_tables=set()
    for stage,key,destination in (('tables','retained_table_shards',retained_tables),('layout','retained_layout_shards',retained_layouts)):
        for entry in config.get(key,[]):
            root=original_root(entry['closed_source_supervision']);summary=read(check(entry['summary']));resource=read(check(entry['resource']))
            resource_closed(resource)
            if (resource.get('worker_summary')!=entry['summary'] or resource not in root.get('resources',[])
              or resource.get('child_started') is not True or resource.get('worker_optimizer_updates_permission') is not False):raise ValueError('Retained witness must preserve an actual successful source child verbatim')
            if summary.get('stage')!=stage or summary.get('plan')!=c['full_parent_plan'] or summary.get('status')!='COMPLETE':raise ValueError('Retained witness source summary differs')
            if stage=='tables':
                identity=record_key(entry['summary'])
                if identity not in table_keys or identity in seen_tables:raise ValueError('Duplicate or unverified retained table summary')
                seen_tables.add(identity);resources.append(deepcopy(resource))
            index=entry['slice_start']//config['shard_size']
            proof=Path(c['native_result_path']).resolve().parent/(stage+'_'+str(index).zfill(3)+'.RETAINED.json')
            destination.append({'origin_summary':entry['summary'],'origin_resource':entry['resource'],
              'origin_source_root':entry['closed_source_supervision'],'origin_source_status':root.get('status'),
              'origin_worker':summary['worker'],'original_actual_argv':resource.get('actual_argv'),
              'original_resource_content':deepcopy(resource),
              'readback_pins':{'summary':make_pin(check(entry['summary'])),'resource':make_pin(check(entry['resource'])),
                'source_root':make_pin(check(entry['closed_source_supervision'])),'retained_receipt':make_pin(proof)},
              'assertions':{'source_child_is_pristine_and_successful':True,'source_root_is_physically_closed':True,
                'geometry_model_runtime_and_partition_previously_verified':True,'original_identity_relabelled':False},
              'new_model_calls':0,'new_children_started':0})
    keys=[record_key(resource['worker_summary']) for resource in resources]
    if len(keys)!=len(set(keys)):raise ValueError('Composed source witness cannot duplicate a source child')
    return {'contract':'document-ai-composed-closed-source-verification.v1','status':'COMPLETE','verification_only':True,
      'meaning':'COMPLETE means source-closure verification completed; original source job statuses remain unchanged',
      'native_source_result':native_pin,'source_roots':roots,'resources':resources,'failure':None,
      'fresh_native_children':len(native['resources']),'retained_table_children':len(retained_tables),
      'retained_layout_children_separate':len(retained_layouts),'retained_table_sources':retained_tables,
      'retained_layout_sources':retained_layouts,'cleanup':{'confirmed_all_known_owned_exited':True},
      'shared_lock_released_after_owned_closure':True,'shared_lock_claim_scope':'all cited source jobs only; not the active post-evaluation lock',
      'new_children_started':0,'new_model_calls':0,'new_text_OCR_calls':0,'optimizer_updates':0,'production_activation':False}

def tiny_closed(score_record,closed,check=checked):
    from eval_native import resource_closed
    if (closed.get('contract')!='document-ai-HQ-serial-result.v1' or closed.get('status')!='COMPLETE'
      or closed.get('failure') is not None or closed.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or closed.get('shared_lock_released_after_owned_closure') is not True):raise ValueError('Actual tiny serial closure required')
    resources=closed.get('resources',[])
    if [r.get('stage') for r in resources]!=STAGES or resources[-1].get('worker_summary')!=score_record:raise ValueError('Actual tiny control/candidate/scorer ownership required')
    for index,resource in enumerate(resources):
        resource_closed(resource)
        if resource.get('child_started') is not True or resource.get('worker_optimizer_updates_permission') is not False:raise ValueError('Actual tiny inference-only child required')
        summary=read(check(resource['worker_summary']))
        if index<2:
            if summary.get('status')!='COMPLETE' or summary.get('scope')!='tiny' or summary.get('variant')!=('control','candidate')[index]:raise ValueError('Actual matched tiny parser summaries required')
        elif (summary.get('status')!='COMPLETE' or summary.get('scope')!='DIAGNOSTIC_TINY_NOT_FULL585'
          or summary.get('actual_scorer_invocations')!=2 or summary.get('writer_readback_verified') is not True):raise ValueError('Actual tiny paired scorer and writer proof required')

def serial_config(c,plan):
    if plan.get('scope')!='full484' or [s.get('id') for s in plan.get('steps',[])]!=STAGES:raise ValueError('Actual fixed full paired plan required')
    steps=deepcopy(plan['steps'])
    for step,seconds in zip(steps,(1800,1800,600)):step['maximum_seconds']=seconds
    return {'contract':'root-HQ-document-ai-serial.v1','approved_by':'root','source':c['source'],
      'resource_policy':RESOURCES,'pins':c['pins'],'ordinary_external_processes':c['ordinary_external_processes'],
      'output_root':plan['required_supervisor_output_root'],'maximum_total_seconds':c['maximum_total_seconds'],
      'steps':steps,'production_activation_allowed':False,
      'prospective_timing_reason':'Root-approved full parser1800/scorer600 from historical549..1296s; no OCR/model/metric changes'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--config-sha256',required=True)
    p.add_argument('--completion-receipt',type=Path,required=True);p.add_argument('--completion-sha256',required=True);p.add_argument('--execute',action='store_true');a=p.parse_args()
    require_HQ()
    if sha(a.config)!=a.config_sha256 or sha(a.completion_receipt)!=a.completion_sha256:raise ValueError('Actual config/completion bytes differ')
    c=read(a.config);validate_config(c,pin(__file__))
    if not a.execute:print({'valid':True,'executed':False,'model_calls':0});return
    profile=read(checked(c['profile']));bridge=Path(next(r['path'] for r in profile['bridge_sources'] if Path(r['path']).name=='eval_assets.py')).parent
    sys.path.insert(0,str(bridge))
    from eval_assets import preflight
    from eval_merge import aggregate
    from eval_plan import build
    from eval_runner import tiny_gate
    from eval_native import model_identity
    import psutil
    process=psutil.Process();process.cpu_affinity([process.cpu_affinity()[0]])
    preparation=Path(c['preparation_root']).resolve()
    if preparation.drive.upper()!='D:' or 'OCR-Experiments' not in preparation.parts or preparation.exists():raise ValueError('New isolated post-eval preparation root required')
    preparation.mkdir(parents=True,exist_ok=False)
    supervisor=load('_docling_post_frozen_serial',checked(c['source']))
    ownership=supervisor.load('_docling_post_original620',c['pins']['ownership']['path'])
    probe=supervisor.load('_docling_post_fresh_metadata',c['pins']['metadata_probe']['path'])
    registry=ownership.OwnedRegistry(psutil);resources=[];failure=None;acquired=False;output=None;started=time.monotonic();native_pin=None;score_pin=None
    save(preparation/'STARTED.json',{'config':pin(a.config),'completion':pin(a.completion_receipt),'driver':pin(__file__),'started_utc':datetime.now(timezone.utc).isoformat(),'workers_started':0})
    try:
        with ownership.safe_owned_lock(ownership.LOCK,registry):
            acquired=True;end=time.monotonic()+c['maximum_total_seconds']
            def guarded(record):
                if (time.monotonic()>=end or process.memory_info().rss>RESOURCES['maximum_own_process_tree_RSS_bytes']
                  or psutil.virtual_memory().available<RESOURCES['stop_free_RAM_bytes']):raise RuntimeError('Pure preparation deadline/RAM/RSS guard')
                return checked(record)
            fresh=probe.probe(c['pins']['controller']['path'],ownership.LOCK)
            reviewed=supervisor.ordinary_process_gate(fresh,c);save(preparation/'EXTERNAL_PROCESS_CLOSURE.json',{'fresh_metadata':fresh,'source_verified_ordinary_processes':reviewed})
            native_pin=completion_ready(c,read(a.completion_receipt));native=read(guarded(native_pin));native_config=read(guarded(c['native_config']))
            tables=native_tables(c,native,native_config,guarded);tiny_closed(c['tiny_score'],read(guarded(c['closed_tiny'])),guarded)
            preflight(profile,guarded)
            source_witnesses=[native_pin]
            if native_config.get('retained_table_shards'):
                witness=composed_source_witness(c,native_pin,native,native_config,tables,guarded)
                witness_path=preparation/'COMPOSED_CLOSED_SOURCE_WITNESS.json';save(witness_path,witness)
                source_witnesses=[pin(witness_path)]
            merged=aggregate(tables,source_witnesses,check=guarded)
            tiny_gate(profile,c['tiny_score'],guarded,model_identity(merged))
            merged_path=preparation/'FULL_NATIVE_SUMMARY.json';save(merged_path,merged)
            plan=build(c['profile']['path'],str(merged_path),'full484',c['trial_name'],c['tiny_score']['path'])
            if plan['source_profile']!=c['profile']:raise ValueError('Full plan/profile bytes differ')
            save(preparation/'FULL_STEPS.json',plan)
            serial=serial_config(c,plan);output=supervisor.validate(serial);save(preparation/'ACTUAL_SERIAL_CONFIG.json',serial)
            output.mkdir(parents=True,exist_ok=False)
            for step in serial['steps']:
                if sha(a.config)!=a.config_sha256 or (output/'STOP_REQUEST.json').exists():raise ValueError('Config changed or stop requested')
                for record in [step['worker'],*step.get('input_pins',[])]:guarded(record)
                fresh=probe.probe(c['pins']['controller']['path'],ownership.LOCK)
                reviewed=supervisor.ordinary_process_gate(fresh,c);save(output/(step['id']+'.fresh_admission.json'),{'metadata':fresh,'ordinary_processes':reviewed})
                resources.append(supervisor.run_stage(step,serial,output,ownership,registry,psutil,end))
            score_pin=pin(output/'score/RESULT.json');score=read(guarded(score_pin))
            if score.get('status')!='COMPLETE' or score.get('scope')!='FULL484_FIXED585' or score.get('actual_scorer_invocations')!=2 or score.get('writer_readback_verified') is not True:raise ValueError('Actual full paired score/write result required')
    except BaseException as exc:
        failure={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
        if output is not None and 'step' in locals():
            receipt=output/(step['id']+'.resource.json')
            if receipt.is_file() and not any(r['stage']==step['id'] for r in resources):resources.append(read(receipt))
    cleanup=registry.last_cleanup or registry.cleanup();safe=cleanup['confirmed_all_known_owned_exited'] is True
    result={'contract':'document-ai-HQ-serial-result.v1','status':'COMPLETE' if failure is None and safe else 'FAILED',
      'failure':failure,'config':pin(a.config),'driver':pin(__file__),'resources':resources,'cleanup':cleanup,
      'shared_lock_acquired':acquired,'shared_lock_released_after_owned_closure':safe and acquired,
      'actual_native_result':native_pin,'actual_full_score':score_pin,'elapsed_seconds':time.monotonic()-started,
      'new_text_OCR_calls':0,'new_model_calls':0,'optimizer_updates':0,'production_activation':False,
      'endpoint_score_status':'COMPLETE' if failure is None and safe else 'NOT_COMPLETED'}
    save(preparation/'RESULT.json',result)
    if output is not None and output.exists():save(output/'RESULT.json',result)
    if failure or not safe:raise SystemExit(1)

if __name__=='__main__':main()
