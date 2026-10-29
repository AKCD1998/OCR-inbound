"""Model-free V6 preparation. This module cannot publish or launch an HQ job.

Every native geometry page is new in this implementation arm. The fixed323 RAW,
parser, reference and scorer assets are reused; no historical producer is renamed.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path,PureWindowsPath
from component_common import checked,pin,read,save,RESOURCES
from eval_native import record_key,witness,resource_closed,model_identity
from tableformer_storage_arm import validate_arm,BASE_WORKER_SHA

BASE='D:/OCR-Experiments/document-ai-20261028'
V4_SHA='07ab2e030189d49f70e5a65f3ac538eab769fd7150b255abf5cde6415f87fe52'
CACHE_SHA='08422a5674144aa2dc1e72131e99020849a55ca153e315f175b629c173ff3377'
FULL_SHA='8be0d59634dc9078582821965600eee63b9edc7ac174993be87ef766df407d0a'
CODE_NAMES=('eval_assets.py','eval_geometry.py','eval_runner.py','eval_plan.py','eval_merge.py','eval_native.py',
 'eval_transport.py','component_common.py','eval_lifecycle.py','docling_full_driver.py','docling_post_eval.py',
 'serial_supervisor.py','metadata_probe.py','component_worker.py','python_cache.py','bytecode_bundle.py',
 'docling_stage_worker.py','tableformer_storage_arm.py','docling_storage_worker.py')
BRIDGE_NAMES=('eval_assets.py','eval_geometry.py','eval_runner.py','eval_plan.py','eval_merge.py','eval_native.py',
              'eval_transport.py','component_common.py','eval_lifecycle.py')

def same(a,b):return isinstance(a,dict) and isinstance(b,dict) and record_key(a)==record_key(b)

def profile_value(base,root,code,approval,arm,base_worker,tiny_page=160):
    if type(tiny_page) is not int or not 1<=tiny_page<=484:raise ValueError('One real source page required')
    value=deepcopy(base)
    value.pop('lifecycle_equivalence',None);value.pop('selected_fresh_worker_sha256',None)
    value.update(bridge_version='V6-tableformer-two-clone-all-fresh',tiny_page=tiny_page,
                 results_root=str(PureWindowsPath(root)/'runs/docling'),bridge_sources=[deepcopy(code[n]) for n in BRIDGE_NAMES])
    selected={'contract':'document-ai-selected-two-clone-implementation.v1','arm_receipt':deepcopy(approval),
      'original_source':deepcopy(arm['original_source']),'variant_source':deepcopy(arm['variant_source']),
      'implementation_helper':deepcopy(arm['implementation_helper']),'base_worker':deepcopy(base_worker),
      'actual_wrapper':deepcopy(code['docling_storage_worker.py']),
      'runtime_cache':{'path':BASE+'/runtime-caches/docling-pyc-blob-v1/CACHE_MANIFEST.json','sha256':CACHE_SHA},
      'all_fresh_layout_pages':484,'all_fresh_table_pages':484,'retained_layout_pages':0,'retained_table_pages':0}
    value['selected_tableformer_implementation']=selected
    for key in ('lifecycle_equivalence','approved_base_worker','approved_variant_origin','approved_lifecycle_verifier'):
        value['pins'].pop(key,None)
    for key in ('arm_receipt','original_source','variant_source','implementation_helper','base_worker','actual_wrapper','runtime_cache'):
        value['pins']['selected_implementation:'+key]=deepcopy(selected[key])
    return value

def prepare(transport,approval,root=BASE+'/endpoint-bridge-v6',tiny_page=160):
    arm=validate_arm(approval,transport.checked)
    old=transport.pin(BASE+'/endpoint-bridge-v4/profiles/docling-tiny-page1.json')
    if old['sha256']!=V4_SHA:raise ValueError('Frozen V4 reference/control profile differs')
    original=read(transport.checked(old));code={};copies=[];directory=Path(__file__).resolve().parent
    base_worker={'path':BASE+'/runtime-lifecycle/startup900-v1/docling_stage_worker.py','sha256':BASE_WORKER_SHA}
    transport.checked(base_worker)
    for name in CODE_NAMES:
        source=deepcopy(base_worker) if name=='docling_stage_worker.py' else pin(directory/name)
        if name not in ('tableformer_storage_arm.py','docling_storage_worker.py'):
            previous=transport.pin(BASE+'/endpoint-bridge-v5/code/'+name)
            if previous['sha256']!=source['sha256']:raise ValueError('Frozen V5 source changed: '+name)
        destination={'path':str(PureWindowsPath(root)/'code'/name),'sha256':source['sha256']}
        code[name]=destination;copies.append({'source':source,'destination':destination['path']})
    if code['docling_full_driver.py']['sha256']!=FULL_SHA:raise ValueError('Frozen full driver8be source differs')
    if (arm.get('resource_policy')!=RESOURCES or arm.get('native_entrypoint',{}).get('sha256')!=code['docling_storage_worker.py']['sha256']
      or arm['implementation_helper']['sha256']!=code['tableformer_storage_arm.py']['sha256']):raise ValueError('Actual root-approved wrapper/helper/resource identity required')
    transport.checked(arm['native_entrypoint'])
    # Only the known frozen bridge/native coordinator bytes are copied. New arm
    # source is separately named; no SDK/env/source file is overwritten.
    profile=profile_value(original,root,code,approval,arm,base_worker,tiny_page)
    return {'contract':'document-ai-V6-all-fresh-preparation.v1','status':'PREPARED_NOT_PUBLISHED',
      'source_profile':old,'root_implementation_approval':approval,'code_copy_files':copies,'code_pins':code,
      'prospective_profile':profile,'proposed_profile_path':str(PureWindowsPath(root)/'profiles/docling-two-clone-page160.json'),
      'expected_native_stages':16,'fresh_layout_pages':484,'fresh_table_pages':484,'retained_layout_pages':0,'retained_table_pages':0,
      'reference_RAW_parser_assets_reused':True,'new_BASE_OCR_calls':0,'new_model_calls':0,'HQ_processes_started':0,
      'production_activation':False,'factory':pin(__file__)}

def validate_selected(summary,profile,check=checked):
    selected=profile['selected_tableformer_implementation']
    if (summary.get('status')!='COMPLETE' or summary.get('stage')!='tables'
      or summary.get('worker',{}).get('sha256')!=selected['actual_wrapper']['sha256']
      or not same(summary.get('native_base_worker'),selected['base_worker'])
      or not same(summary.get('native_implementation_arm'),selected['arm_receipt'])
      or not same(summary.get('runtime_cache'),selected['runtime_cache'])
      or summary.get('implementation_selected') is not True or summary.get('implementation_applied') is not True
      or summary.get('vanilla_sdk_claimed') is not False):raise ValueError('Actual selected modified implementation/source/cache required')
    proof=read(check(summary['actual_tableformer_implementation']))
    if (proof.get('contract')!='document-ai-actual-tableformer-implementation.v1'
      or not same(proof.get('arm_receipt'),selected['arm_receipt'])
      or not same(proof.get('actual_module_file'),selected['variant_source'])
      or not same(proof.get('original_source'),selected['original_source'])
      or type(proof.get('actual_load_count')) is not int or proof['actual_load_count']!=1
      or proof.get('loader')!='exact-module-verified-source-no-pyc'
      or proof.get('original_sdk_modified') is not False or proof.get('vanilla_sdk_claimed') is not False
      or proof.get('cache_guard_for_other_modules_modified') is not False):raise ValueError('Actual imported isolated module-origin proof differs')
    for key in ('arm_receipt','original_source','variant_source','implementation_helper','base_worker','actual_wrapper','runtime_cache'):
        check(selected[key])
    check(summary['worker'])
    return proof

def positive_source(profile,positive,closed,check=checked):
    root=read(check(closed));summary=read(check(positive));witness([positive],[closed],check)
    if root.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True:raise ValueError('Native root closure required')
    validate_selected(summary,profile,check)
    from eval_runner import native_records
    pages,_=native_records(positive,profile,'tiny',check)
    page=read(check(pages[profile['tiny_page']]))
    if summary.get('actual_completed_table_model_calls',0)<1 or page.get('table_model_calls',0)<1 or not page.get('cell_association',{}).get('cells'):
        raise ValueError('Actual positive modified-model prediction and cells required')
    # Preserve the exact source-child record, including its original path spelling.
    matches=[r['worker_summary'] for r in root['resources'] if same(r.get('worker_summary'),positive)]
    if len(matches)!=1:raise ValueError('One exact successful source witness required')
    return deepcopy(matches[0]),summary

def tiny_plan(profile_pin,positive,closed,name,transport):
    profile=read(transport.checked(profile_pin));positive,summary=positive_source(profile,positive,closed,transport.checked)
    from eval_plan import build
    return build(profile_pin['path'],positive['path'],'tiny',name,supervision_paths=[closed['path']],read_mappings=transport.mappings)

def argument(args,key,value):
    result=list(args)
    if result.count(key)>1:raise ValueError('Duplicate native argument: '+key)
    if key in result:
        index=result.index(key)
        if index+1>=len(result) or result[index+1].startswith('--'):raise ValueError('Missing native argument value')
        result[index+1]=str(value)
    else:result.extend((key,str(value)))
    return result

def full_config(canary,code,profile_pin,profile,positive_pin,positive,closed,tiny,tiny_score,task_root,output):
    """Called only after actual positive source and new tiny validation by client."""
    if canary.get('resource_policy')!=RESOURCES:raise ValueError('Original resource policy required')
    selected=profile['selected_tableformer_implementation']
    candidates=[s for s in canary['steps'] if s.get('worker',{}).get('sha256')==selected['actual_wrapper']['sha256'] and '--stage' in s['args'] and s['args'][s['args'].index('--stage')+1]=='tables']
    if len(candidates)!=1:raise ValueError('One actual selected table-stage template required')
    step=deepcopy(candidates[0]);target={n:{'path':str(PureWindowsPath(task_root)/n),'sha256':r['sha256']} for n,r in code.items()}
    if step.get('component')!='docling' or step.get('optimizer_updates_allowed') is not False:raise ValueError('Inference-only native component required')
    for key,value in (('--native-cell-matching','disabled'),('--table-cpu-backend','aten')):
        if step['args'].count(key)!=1 or step['args'][step['args'].index(key)+1]!=value:raise ValueError('Selected source-only native options/cache differ')
    flags=('--runtime-cache-manifest','--runtime-cache-manifest-sha256')
    if any(step['args'].count(k)!=1 for k in flags):raise ValueError('One actual selected cache argument pair required')
    actual_cache={'path':step['args'][step['args'].index(flags[0])+1],'sha256':step['args'][step['args'].index(flags[1])+1]}
    if not same(actual_cache,selected['runtime_cache']) or not same(positive.get('runtime_cache'),selected['runtime_cache']):
        raise ValueError('Full template/actual positive selected cache differ')
    # Frozen8be compares this dictionary exactly; retain the real native pin's
    # spelling instead of re-pinning an equivalent forward/backslash path.
    for flag,key in zip(flags,('path','sha256')):step['args']=argument(step['args'],flag,positive['runtime_cache'][key])
    pins={k:deepcopy(canary['pins'][k]) for k in ('controller','ownership','python')}
    pins.update({('common' if n=='component_common.py' else 'metadata_probe' if n=='metadata_probe.py' else 'source:'+n):r for n,r in target.items()})
    # Per-stage native implementation is the wrapper; base129 remains a separate
    # read-only input. Endpoint runner continues to use the V6 profile code path.
    step['worker']=target['docling_storage_worker.py'];step['maximum_seconds']=2400;step['id']='native_template'
    for key,value in (('--base-worker',selected['base_worker']['path']),('--base-worker-sha256',selected['base_worker']['sha256']),
      ('--implementation-arm',selected['arm_receipt']['path']),('--implementation-arm-sha256',selected['arm_receipt']['sha256']),
      ('--stage','layout'),('--output',str(PureWindowsPath(output)/'native-template')),('--slice-start',0),('--slice-count',64)):
        step['args']=argument(step['args'],key,value)
    for flag in ('--upstream-layout-summary','--upstream-layout-summary-sha256','--upstream-resource','--upstream-resource-sha256'):
        if flag in step['args']:
            i=step['args'].index(flag);del step['args'][i:i+2]
    if step['args'].count('--execute')!=1:raise ValueError('Actual native --execute route required')
    plan={'path':step['args'][step['args'].index('--plan')+1],'sha256':step['args'][step['args'].index('--plan-sha256')+1]}
    if not same(plan,positive['plan']):raise ValueError('Full parent plan differs from the actual positive canary')
    pins.update(full_plan=plan,endpoint_profile=deepcopy(profile_pin),implementation_arm=deepcopy(selected['arm_receipt']),
                base_native_worker=deepcopy(selected['base_worker']),positive_summary=deepcopy(positive_pin),
                positive_supervision=deepcopy(closed),closed_endpoint_tiny=deepcopy(tiny),tiny_score=deepcopy(tiny_score))
    step['input_pins']=[deepcopy(r) for r in pins.values()]
    step['summary_path']=str(PureWindowsPath(output)/'native-template/SUMMARY.json')
    return {'contract':'root-HQ-document-ai-serial.v1','approved_by':'root','source':target['serial_supervisor.py'],
      'docling_full_driver':target['docling_full_driver.py'],'resource_policy':deepcopy(RESOURCES),'pins':pins,
      'ordinary_external_processes':deepcopy(canary['ordinary_external_processes']),'output_root':output,
      'maximum_total_seconds':43200,'steps':[step],'production_activation_allowed':False,'full_parent_plan':plan,
      'actual_positive_table_summary':deepcopy(positive_pin),'actual_closed_table_canary':deepcopy(closed),
      'actual_positive_table_page':profile['tiny_page'],'actual_closed_endpoint_tiny':deepcopy(tiny),
      'endpoint_tiny_stage_ids':['control','candidate','paired_score'],'endpoint_profile':deepcopy(profile_pin),
      'shard_size':64,'retained_layout_shards':[],'retained_table_shards':[],
      'expected_fresh_model_stage_children':16,'expected_retained_layout_pages':0,'expected_retained_table_pages':0,
      'explicit_modified_implementation':deepcopy(selected),'new_BASE_OCR_calls':0}

def tiny_configuration(plan,canary,profile_pin,task_root):
    if (plan.get('scope')!='tiny' or not same(plan.get('source_profile'),profile_pin)
      or [s.get('id') for s in plan.get('steps',[])]!=['control','candidate','paired_score']
      or canary.get('resource_policy')!=RESOURCES):raise ValueError('Actual three-step tiny and unchanged policy required')
    for step in plan['steps']:
        if (step.get('component')!='endpoint-eval' or step.get('optimizer_updates_allowed') is not False or step.get('maximum_seconds')!=600
          or step.get('worker',{}).get('sha256')!='1538e7b5ba42cf178c24b70abf6081c5c39d02161afce2fe44b5802ef39eb5f9'):
            raise ValueError('Exact pure1538 runner/600s/no optimization required')
    source={'path':str(PureWindowsPath(task_root)/'serial.py'),'sha256':'87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'}
    pins={k:deepcopy(canary['pins'][k]) for k in ('controller','ownership','python')}
    for name,role,sha in (('component_common.py','common','70178f992d1b64735daeed5919fbcbbbaf0a8a8bea9bd35e5a9e80547f9b0d36'),
      ('metadata_probe.py','metadata_probe','43504d05f1c300262a01ef27f29339baa1a651360783aeff5b73aee0117bf9c9')):
        pins[role]={'path':str(PureWindowsPath(task_root)/name),'sha256':sha}
    pins['endpoint_profile']=deepcopy(profile_pin)
    return {'contract':'root-HQ-document-ai-serial.v1','approved_by':'root','source':source,'resource_policy':deepcopy(RESOURCES),
      'pins':pins,'ordinary_external_processes':deepcopy(canary['ordinary_external_processes']),
      'output_root':plan['required_supervisor_output_root'],'maximum_total_seconds':2100,
      'steps':deepcopy(plan['steps']),'production_activation_allowed':False}

def full_preparation(manifest,profile_pin,positive,closed,canary_config_pin,tiny,task_root,output,transport):
    profile=read(transport.checked(profile_pin))
    if profile!=manifest['prospective_profile']:raise ValueError('Actual selected immutable V6 profile required')
    positive,summary=positive_source(profile,positive,closed,transport.checked)
    native_root=read(transport.checked(closed))
    if not same(native_root.get('config'),canary_config_pin):raise ValueError('Actual selected canary config/closure differs')
    canary=read(transport.checked(canary_config_pin));done=read(transport.checked(tiny))
    if (done.get('status')!='COMPLETE' or done.get('failure') is not None
      or done.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or done.get('shared_lock_released_after_owned_closure') is not True
      or [r.get('stage') for r in done.get('resources',[])]!=['control','candidate','paired_score']):raise ValueError('Actual closed NEW V6 tiny required')
    for i,r in enumerate(done['resources']):
        resource_closed(r)
        if r.get('child_started') is not True or r.get('worker_optimizer_updates_permission') is not False:raise ValueError('Actual inference-only tiny children required')
        result=read(transport.checked(r['worker_summary']))
        if i<2:
            run=read(transport.checked(result['run_manifest']))
            if (result.get('status')!='COMPLETE' or result.get('scope')!='tiny' or result.get('variant')!=('control','candidate')[i]
              or not same(run.get('profile'),profile_pin) or not same(run.get('native_summary'),positive)):
                raise ValueError('New tiny must consume the exact selected positive clone source/profile')
    score=done['resources'][-1]['worker_summary']
    from eval_runner import tiny_gate
    tiny_gate(profile,score,transport.checked,model_identity(summary))
    config=full_config(canary,manifest['code_pins'],profile_pin,profile,positive,summary,closed,tiny,score,task_root,output)
    return {'config':config,'actual_positive_table_summary':positive,'actual_closed_canary':closed,'actual_closed_tiny':tiny,
      'actual_tiny_score':score,'profile':profile_pin,'expected_native_stages':16,'expected_fresh_layout_pages':484,
      'expected_fresh_table_pages':484,'expected_retained_layout_pages':0,'expected_retained_table_pages':0,
      'actual_native_worker_sha256':summary['worker']['sha256'],'new_BASE_OCR_calls':0,'HQ_jobs_started':0}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root-approval',required=True)
    ap.add_argument('--root-approval-sha256',required=True);ap.add_argument('--manifest-output',type=Path,required=True)
    ap.add_argument('--target-root',default=BASE+'/endpoint-bridge-v6');a=ap.parse_args()
    from eval_transport import ReadTransport
    transport=ReadTransport([('D:/','//100.90.166.72/D'),('C:/','//100.90.166.72/C')])
    result=prepare(transport,{'path':a.root_approval,'sha256':a.root_approval_sha256},a.target_root)
    save(a.manifest_output,result);print(json.dumps({'manifest':pin(a.manifest_output),'HQ_processes_started':0}))
