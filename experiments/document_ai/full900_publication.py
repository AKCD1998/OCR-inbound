"""Prepare the frozen V5 full484 configuration; publication requires explicit --publish.

The factory consumes closed positive900/tiny receipts. It copies the exact V5
17-file import closure, preserving old layout960/tableb1d origins separately.
No model, parser, source image or recognition answer is loaded by this client.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

NATIVE=r'D:\OCR-Experiments\document-ai-20261028'
REMOTE=Path(r'\\100.90.166.72\D\OCR-Experiments\document-ai-20261028')
TASK='OCR_DOCAI_DOCLING_FULL484_20261029_V3'
FULL_SHA='8be0d59634dc9078582821965600eee63b9edc7ac174993be87ef766df407d0a'
VARIANT_SHA='129df26e2a56a3be213d322c2734fe2e7ecab862e1f2daec551e6fb30af57e25'
PROFILE_SHA='171fd61035b495f9656b579f9064a3c3a528c359ecc384a64827ebcbc98ab242'
RECEIPT_SHA='e349c5f5ce85525cff2219c2b8d725b7da129e541d5b0365e7e62dd36b10eb0e'
CACHE_SHA='08422a5674144aa2dc1e72131e99020849a55ca153e315f175b629c173ff3377'
FILES={'bytecode_bundle.py','component_common.py','component_worker.py','docling_full_driver.py',
       'docling_post_eval.py','docling_stage_worker.py','eval_assets.py','eval_geometry.py','eval_lifecycle.py',
       'eval_merge.py','eval_native.py','eval_plan.py','eval_runner.py','eval_transport.py','metadata_probe.py',
       'python_cache.py','serial_supervisor.py'}


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def remote(path):
    value=str(path).replace('\\','/');prefix=NATIVE.replace('\\','/')+'/'
    if not value.startswith(prefix):raise ValueError('Selected HQ experiment path required')
    return REMOTE/value[len(prefix):]
def native_pin(path):return {'path':NATIVE+'\\'+str(Path(path).relative_to(REMOTE)),'sha256':sha(path)}
def checked(record):
    path=remote(record['path'])
    if sha(path)!=record['sha256']:raise ValueError('Actual selected bytes differ: '+str(path))
    return path
def arg(args,name,value):
    if args.count(name)!=1:raise ValueError('One frozen argument required: '+name)
    args[args.index(name)+1]=value


def make_config(base,code_pins,profile_pin,profile,positive_pin,positive,closed_positive_pin,
                tiny_pin,tiny_score_pin,approval,retained_table):
    """Pure factory; actual completion/byte checks are performed by prepare()."""
    if set(code_pins)!=FILES:raise ValueError('Complete17-file V5 import closure required')
    if code_pins['docling_full_driver.py']['sha256']!=FULL_SHA or code_pins['docling_stage_worker.py']['sha256']!=VARIANT_SHA:raise ValueError('Frozen full/900 worker source differs')
    if profile_pin['sha256']!=PROFILE_SHA or profile['lifecycle_equivalence']['sha256']!=RECEIPT_SHA:raise ValueError('Frozen V5 profile/lifecycle approval differs')
    if positive['worker']['sha256']!=VARIANT_SHA or positive['runtime_cache']['sha256']!=CACHE_SHA:raise ValueError('Actual positive900/cache source differs')
    c=copy.deepcopy(base);source=NATIVE+'\\'+TASK;output=NATIVE+r'\components\docling-full484-20261029-v3'
    target={name:{'path':source+'\\'+name,'sha256':record['sha256']} for name,record in code_pins.items()}
    c['source']=target['serial_supervisor.py'];c['docling_full_driver']=target['docling_full_driver.py'];c['output_root']=output
    roles={'component_common.py':'common','metadata_probe.py':'metadata_probe','component_worker.py':'component_helper',
           'docling_stage_worker.py':'docling_worker','python_cache.py':'cache_helper','bytecode_bundle.py':'bundle_helper'}
    for name,record in target.items():c['pins'][roles.get(name,'V5_source:'+name)]=record
    # Preserve exact spelling from the real profile, not a path-equivalent reconstruction.
    c['lifecycle_equivalence']=copy.deepcopy(profile['lifecycle_equivalence']);c['pins']['lifecycle_equivalence']=copy.deepcopy(c['lifecycle_equivalence'])
    c['endpoint_profile']=copy.deepcopy(profile_pin);c['pins']['endpoint_profile']=copy.deepcopy(profile_pin);c['fixed_endpoint_profile']=copy.deepcopy(profile_pin)
    c['pins']['approved_base_worker']=copy.deepcopy(approval['original_worker']);c['pins']['approved_variant_origin']=copy.deepcopy(approval['variant_worker']);c['pins']['approved_lifecycle_verifier']=copy.deepcopy(approval['verifier'])
    c['actual_positive_table_summary']=copy.deepcopy(positive_pin);c['pins']['positive_summary']=copy.deepcopy(positive_pin)
    c['actual_closed_table_canary']=copy.deepcopy(closed_positive_pin);c['pins']['positive_supervision']=copy.deepcopy(closed_positive_pin)
    c['actual_closed_endpoint_tiny']=copy.deepcopy(tiny_pin);c['pins']['closed_endpoint_tiny']=copy.deepcopy(tiny_pin);c['pins']['tiny_score']=copy.deepcopy(tiny_score_pin)
    c['pins']['accepted_python_cache']=copy.deepcopy(positive['runtime_cache'])
    c['retained_table_shards']=[copy.deepcopy(retained_table)]
    for name in ('summary','resource','closed_source_supervision'):c['pins']['retained_table000_'+name]=copy.deepcopy(retained_table[name])
    c['expected_fresh_model_stage_children']=14;c['expected_retained_layout_pages']=64;c['expected_retained_table_pages']=64
    c['accepted_canary_dependency_equivalence']={'fresh_worker_sha256':VARIANT_SHA,'actual_positive_canary':copy.deepcopy(closed_positive_pin),
             'actual_source_hashes':{name:r['sha256'] for name,r in code_pins.items()},'lifecycle_approval':copy.deepcopy(c['lifecycle_equivalence']),
             'old_source_observations_relabelled':False}
    c['explicit_new_lifecycle_arm']={'startup_seconds':900,'prediction_seconds':120,'stage_seconds':2400,'job_seconds':43200,
             'original480_failures_remain_failed':True,'actual_worker_identities_preserved':True}
    c['actual_preflight_gate']={'status':'VERIFIED_FROM_ACTUAL_CLOSED_900_AND_NEW_V5_TINY','profile':copy.deepcopy(profile_pin),
             'positive_native_summary':copy.deepcopy(positive_pin),'tiny_score':copy.deepcopy(tiny_score_pin),
             'new_BASE_OCR_required':False,'fresh_model_stage_children':14,'retained_layout_pages':64,'retained_table_pages':64}
    step=c['steps'][0];step['worker']=target['docling_stage_worker.py'];step['maximum_seconds']=2400
    arg(step['args'],'--output',output+r'\native-template');arg(step['args'],'--runtime-cache-manifest',positive['runtime_cache']['path']);arg(step['args'],'--runtime-cache-manifest-sha256',positive['runtime_cache']['sha256'])
    step['summary_path']=output+r'\native-template\SUMMARY.json'
    # The old template's positive/cache pins must not silently remain in the new arm.
    stale={json.dumps(base[k],sort_keys=True) for k in ('actual_positive_table_summary','actual_closed_table_canary')}
    step['input_pins']=[r for r in step['input_pins'] if json.dumps(r,sort_keys=True) not in stale and 'CACHE_MANIFEST.json' not in r['path']]
    step['input_pins'] += [copy.deepcopy(r) for r in (positive_pin,closed_positive_pin,positive['runtime_cache'],c['lifecycle_equivalence'],
            approval['original_worker'],approval['variant_worker'],approval['verifier'],profile_pin)]
    return c


def prepare(tiny_result):
    canary=REMOTE/'components/docling-startup900-validate-20261029-v9';closed=read(canary/'RESULT.json')
    if closed.get('status')!='COMPLETE' or closed.get('shared_lock_released_after_owned_closure') is not True or closed.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True:raise ValueError('Actual closed900 canary required')
    resources=closed['resources']
    if [r['stage'] for r in resources]!=['layout_canary','tables_canary'] or any(r.get('actual_exit_code')!=0 or r.get('failure') is not None or r.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True for r in resources):raise ValueError('Both actual900 model stages must close successfully')
    positive_pin=resources[-1]['worker_summary'];positive=read(checked(positive_pin));closed_pin=native_pin(canary/'RESULT.json')
    tiny=read(checked(tiny_result))
    if tiny.get('status')!='COMPLETE' or tiny.get('shared_lock_released_after_owned_closure') is not True or tiny.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True or [r['stage'] for r in tiny.get('resources',[])]!=['control','candidate','paired_score']:raise ValueError('Actual closed NEW V5 tiny required')
    if any(r.get('child_started') is not True or r.get('actual_exit_code')!=0 or r.get('failure') is not None or r.get('stop_reason') is not None or r.get('worker_optimizer_updates_permission') is not False or r.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True for r in tiny['resources']):raise ValueError('All three real tiny children must close successfully')
    first=read(checked(tiny['resources'][0]['worker_summary']));run=read(checked(first['run_manifest']));profile_pin=run['profile'];profile=read(checked(profile_pin))
    if run.get('native_summary')!=positive_pin:raise ValueError('Tiny must use this actual positive900 summary')
    tiny_score_pin=tiny['resources'][-1]['worker_summary'];score=read(checked(tiny_score_pin))
    if score.get('status')!='COMPLETE' or score.get('actual_scorer_invocations')!=2 or score.get('writer_readback_verified') is not True:raise ValueError('Real paired scorer/output preflight required')
    approval=read(checked(profile['lifecycle_equivalence']))
    code=REMOTE/'endpoint-bridge-v5/code';placement=read(REMOTE/'endpoint-bridge-v5/CODE_PLACEMENT_RECEIPT.json')
    addendum=read(REMOTE/'endpoint-bridge-v5/CODE_IMPORT_CLOSURE_ADDENDUM.json')
    records=placement['files']+[addendum['only_added_file']]
    pins={Path(r['path']).name:{'path':r['path'],'sha256':r['sha256']} for r in records}
    for record in pins.values():checked(record)
    base=read(REMOTE/'configs/docling-full484-20261029-v2.json')
    retained={'slice_start':0,'slice_count':64,**{k:approval['retained_table'][k] for k in ('summary','resource','closed_source_supervision')}}
    config=make_config(base,pins,profile_pin,profile,positive_pin,positive,closed_pin,tiny_result,tiny_score_pin,approval,retained)
    # Actual V5 verification is pure metadata and must pass before publishing a long native job.
    sys.path.insert(0,str(code))
    import docling_full_driver
    docling_full_driver.lifecycle_tiny(config,positive_pin,positive,check=checked)
    return config,pins


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tiny-result',required=True);p.add_argument('--tiny-result-sha256',required=True)
    p.add_argument('--config-output',type=Path,required=True);p.add_argument('--publish',action='store_true');a=p.parse_args()
    config,pins=prepare({'path':a.tiny_result,'sha256':a.tiny_result_sha256})
    with a.config_output.open('x',encoding='utf-8') as stream:json.dump(config,stream,ensure_ascii=False,indent=2)
    result={'config':str(a.config_output),'config_sha256':sha(a.config_output),'published':False,'expected_fresh_model_children':14,'retained_layout_pages':64,'retained_table_pages':64}
    if a.publish:
        if a.config_output!=REMOTE/'configs/docling-full484-20261029-v3.json':raise ValueError('Exact new HQ fullV3 config path required')
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'));from hq_document_ai_job import publish
        source=checked(pins['docling_full_driver.py']);extras=[checked(record) for name,record in pins.items() if name!='docling_full_driver.py']
        result['publication']=publish(source,['--config',NATIVE+r'\configs\docling-full484-20261029-v3.json','--config-sha256',sha(a.config_output)],TASK,extra_files=extras,max_minutes=730);result['published']=True
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
