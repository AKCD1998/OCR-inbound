"""Narrow, source-proved lifecycle compatibility; never producer relabelling.

This is pure metadata code. The approval permits only the exact b1d worker and
its two-token startup900 variant to share a model recipe. A retained observation
keeps its original worker, cache, source-root status and successful-child proof.
"""
from __future__ import annotations
import argparse
import ast
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import tokenize
from component_common import RESOURCES, CONTROLLER_SHA256, checked, pin, read, save, sha

ORIGINAL_NATIVE_SHA = 'b1d43e7b85eca724666db331384a81edf23ad1bff637fae514ce51ebb187757c'
OWNERSHIP_SHA = '620df01cdc5037b922bc6b28586a0d94c8a266c936ebb05a57b42b22a5fefb45'
FULL_PARENT_SHA = '7dad9462ce75ecadf9279fd28c255916dfa365ddaa49eace7053e4364c93e96e'
CONTRACT = 'document-ai-lifecycle-equivalence.v1'
SCOPE = {'pages':484,'product_present':585,'all_present':602,'critical':329,'supplier_code':57,'absence':18,'prior_exact':323}
POLICY = {'old_startup_seconds':480,'new_startup_seconds':900,'maximum_native_predict_seconds':120,
          'maximum_stage_seconds':2400,'maximum_job_seconds':43200,'resource_policy':RESOURCES,
          'controller_sha256':CONTROLLER_SHA256,'ownership_sha256':OWNERSHIP_SHA}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def _startup_nodes(tree, value):
    execute = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute']
    if len(execute)!=1:raise ValueError('Exactly one execute function required')
    timeout = [n for n in execute[0].body if isinstance(n,ast.FunctionDef) and n.name=='startup_timeout']
    if len(timeout)!=1:raise ValueError('Exactly one named startup_timeout required')
    reports=[]
    for node in ast.walk(timeout[0]):
        if isinstance(node,ast.Dict):
            reports.extend(v for k,v in zip(node.keys,node.values)
                if isinstance(k,ast.Constant) and k.value=='maximum_SDK_startup_seconds')
    timers=[n for n in ast.walk(execute[0]) if isinstance(n,ast.Call)
        and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name)
        and n.func.value.id=='threading' and n.func.attr=='Timer'
        and len(n.args)==2 and isinstance(n.args[1],ast.Name) and n.args[1].id=='startup_timeout'
        and not n.keywords]
    if len(reports)!=1 or len(timers)!=1:raise ValueError('Unique startup report and watchdog call required')
    nodes=[reports[0],timers[0].args[0]]
    if any(not isinstance(n,ast.Constant) or type(n.value) is not int or n.value!=value for n in nodes):
        raise ValueError('Startup literals must be exactly the approved integer budget')
    return list(zip(('timeout_report','startup_watchdog'),nodes))

def prove_source(original, variant):
    """Reject even comment/EOL edits; AST equality alone is insufficient."""
    old_tree=ast.parse(original);new_tree=ast.parse(variant)
    old_nodes=_startup_nodes(old_tree,480);new_nodes=_startup_nodes(new_tree,900)
    old_tokens=list(tokenize.tokenize(io.BytesIO(original).readline))
    new_tokens=list(tokenize.tokenize(io.BytesIO(variant).readline))
    expected={(n.lineno,n.col_offset) for _,n in old_nodes}
    if len(expected)!=2 or {(n.lineno,n.col_offset) for _,n in new_nodes}!=expected:
        raise ValueError('Startup source positions changed')
    changed=[]
    if len(old_tokens)!=len(new_tokens):raise ValueError('Only two NUMBER token replacements are allowed')
    for before,after in zip(old_tokens,new_tokens):
        if before==after:continue
        if (before.type!=tokenize.NUMBER or after.type!=tokenize.NUMBER or before.string!='480'
            or after.string!='900' or before.start!=after.start or before.end!=after.end
            or before.start not in expected):
            # TokenInfo.line also changes for neighbouring tokens on the same
            # physical line, so compare lexical identity before rejecting.
            if before[:4]==after[:4]:continue
            raise ValueError('Unapproved token change outside startup budget')
        changed.append(before.start)
    if set(changed)!=expected or len(changed)!=2:raise ValueError('Exactly two startup NUMBER tokens required')
    lines=original.splitlines(keepends=True);patched=bytearray(original);replacements=[]
    for role,node in old_nodes:
        start=sum(len(line) for line in lines[:node.lineno-1])+node.col_offset
        end=start+3
        if original[start:end]!=b'480':raise ValueError('Startup byte span differs from AST')
        patched[start:end]=b'900'
        replacements.append({'role':role,'line':node.lineno,'column':node.col_offset,
                             'byte_start':start,'byte_end':end,'old':'480','new':'900'})
    if bytes(patched)!=variant:raise ValueError('Bytes outside the two approved tokens changed')
    for _,node in new_nodes:node.value=480
    before=ast.dump(old_tree,include_attributes=False);after=ast.dump(new_tree,include_attributes=False)
    if before!=after:raise ValueError('Normalized AST differs outside startup lifecycle')
    return {'contract':'document-ai-two-token-startup-source-proof.v1','original_sha256':hashlib.sha256(original).hexdigest(),
            'variant_sha256':hashlib.sha256(variant).hexdigest(),'normalized_AST_sha256':hashlib.sha256(before.encode()).hexdigest(),
            'original_bytes':len(original),'variant_bytes':len(variant),'replacements':replacements,
            'other_bytes_identical':True,'normalized_AST_identical':True,'model_calls':0,'image_decodes':0}

def raw_recipe(summary):
    return {'component':summary['component'],'stage':summary.get('stage','combined'),
            'registry_sha256':summary['registry']['sha256'],'model_data_sha256':summary['materialization']['sha256'],
            'runtime_versions':summary.get('runtime_versions'),'native_table_options':summary.get('native_table_options')}

@dataclass(frozen=True)
class Approval:
    record: dict
    data: dict
    family_sha256: str
    check: object = field(repr=False,compare=False,default=checked)

def build_approval(original_worker,variant_worker,retained_table,full_parent_plan,delivery_provenance=None,check=checked):
    original=Path(check(original_worker)).read_bytes();variant=Path(check(variant_worker)).read_bytes()
    proof=prove_source(original,variant)
    if original_worker['sha256']!=ORIGINAL_NATIVE_SHA or proof['original_sha256']!=ORIGINAL_NATIVE_SHA:
        raise ValueError('Only the immutable original b1d source is approved')
    table=read(check(retained_table['summary']))
    return {'contract':CONTRACT,'approved_by':'root','arm':'startup900-lifecycle-only',
            'verifier':pin(__file__),'original_worker':deepcopy(original_worker),'variant_worker':deepcopy(variant_worker),
            'source_proof':proof,'full_parent_plan':deepcopy(full_parent_plan),
            'retained_table':deepcopy(retained_table),'model_recipe':raw_recipe(table),'policy':deepcopy(POLICY),
            'fixed_evaluation_scope':deepcopy(SCOPE),'delivery_provenance':deepcopy(delivery_provenance or {}),
            'production_activation_allowed':False,'source_prediction_identity_relabelled':False,
            'same_operational_admission_claimed':False}

def validate_approval(record,check=checked):
    data=read(check(record))
    if (data.get('contract')!=CONTRACT or data.get('approved_by')!='root'
        or data.get('arm')!='startup900-lifecycle-only' or data.get('policy')!=POLICY
        or data.get('fixed_evaluation_scope')!=SCOPE or data.get('production_activation_allowed') is not False
        or data.get('source_prediction_identity_relabelled') is not False or data.get('same_operational_admission_claimed') is not False):
        raise ValueError('Explicit root-approved unchanged metric/resource lifecycle contract required')
    check(data['verifier'])
    if data['verifier']['sha256']!=sha(__file__):raise ValueError('Lifecycle verifier source differs')
    original,variant=data['original_worker'],data['variant_worker']
    if original['sha256']!=ORIGINAL_NATIVE_SHA or original==variant:raise ValueError('Original b1d and distinct exact variant required')
    proof=prove_source(Path(check(original)).read_bytes(),Path(check(variant)).read_bytes())
    if proof!=data['source_proof'] or proof['original_sha256']!=original['sha256'] or proof['variant_sha256']!=variant['sha256']:
        raise ValueError('Approved source proof/pins do not match actual bytes')
    if data['full_parent_plan']['sha256']!=FULL_PARENT_SHA:raise ValueError('Original full484 parent plan required')
    check(data['full_parent_plan'])
    entry=data['retained_table']
    if entry.get('selected_pages')!=list(range(1,65)) or any(type(n) is not int for n in entry['selected_pages']):
        raise ValueError('Only the explicitly pinned original64 table pages may use b1d')
    for key in ('summary','resource','closed_source_supervision'):check(entry[key])
    table=read(check(entry['summary']));resource=read(check(entry['resource']));origin=read(check(entry['closed_source_supervision']))
    from eval_native import resource_closed,runtime_proof,validate_table_options
    resource_closed(resource);runtime_proof(table,check);validate_table_options(table.get('native_table_options'))
    if (table.get('status')!='COMPLETE' or table.get('component')!='docling' or table.get('stage')!='tables'
        or table.get('plan')!=data['full_parent_plan'] or table.get('selected_pages')!=entry['selected_pages']
        or table.get('pages_completed')!=64 or table.get('complete_stage_shard') is not True
        or table.get('worker')!=original or table.get('new_text_OCR_calls')!=0 or table.get('optimizer_updates')!=0
        or raw_recipe(table)!=data['model_recipe'] or resource.get('worker_summary')!=entry['summary']
        or resource not in origin.get('resources',[]) or resource.get('child_started') is not True
        or resource.get('worker_optimizer_updates_permission') is not False
        or origin.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
        or origin.get('shared_lock_released_after_owned_closure') is not True):
        raise ValueError('Pinned retained successful child/source/model/closure differs')
    for delivery in data.get('delivery_provenance',{}).values():
        if isinstance(delivery,dict) and set(delivery)>={'path','sha256'}:check(delivery)
    family=digest({'normalized_AST_sha256':proof['normalized_AST_sha256'],'model_recipe':data['model_recipe']})
    return Approval(deepcopy(record),data,family,check)

def context(profile,check=checked):
    record=profile.get('lifecycle_equivalence')
    if record is None:return None
    approval=validate_approval(record,check)
    if not isinstance(approval.data.get('delivery_provenance',{}).get('selected_runtime_cache'),dict):
        raise ValueError('V5 requires an explicitly pinned selected fresh cache; retained cache remains separate')
    if profile.get('selected_fresh_worker_sha256')!=approval.data['variant_worker']['sha256']:
        raise ValueError('Profile fresh source must be the exact approved startup900 variant')
    return approval

def recipe_identity(summary,approval):
    recipe=raw_recipe(summary)
    if recipe!=approval.data['model_recipe']:raise ValueError('Model/runtime/options differ from approved lifecycle family')
    return {**recipe,'model_recipe_family_sha256':approval.family_sha256}

def validate_producer(summary,record,approval,role='candidate'):
    """An approved family is not permission to accept arbitrary old outputs."""
    recipe_identity(summary,approval)
    actual=summary.get('worker')
    if isinstance(actual,dict) and actual.get('sha256')==approval.data['variant_worker']['sha256']:
        approval.check(actual)
        delivery=approval.data.get('delivery_provenance',{})
        if 'selected_runtime_cache' in delivery and summary.get('runtime_cache')!=delivery['selected_runtime_cache']:
            raise ValueError('Fresh runtime cache differs from explicitly selected delivery provenance')
        return 'fresh_startup900'
    retained=approval.data['retained_table']
    if (role!='fresh' and actual==approval.data['original_worker'] and record==retained['summary']
        and summary.get('selected_pages')==retained['selected_pages']):return 'retained_startup480'
    raise ValueError('Producer is neither exact fresh900 nor explicitly pinned retained64b1d')

def lineage(summary,record,approval,role='candidate'):
    return {'native_summary':record,'actual_worker':deepcopy(summary['worker']),
            'selected_pages':deepcopy(summary['selected_pages']),
            'lifecycle':validate_producer(summary,record,approval,role),
            'runtime_cache':deepcopy(summary.get('runtime_cache'))}

def profile_variant(base,approval_record,results_root,check=checked):
    """Reuse immutable data/parser assets; bind NEW bridge code and one profile."""
    approval=validate_approval(approval_record,check);profile=deepcopy(base)
    if profile.get('component')!='docling' or profile.get('expected_scope')!=SCOPE:raise ValueError('Original fixed323 Docling profile required')
    names=[Path(r['path']).name for r in base['bridge_sources']]
    if 'eval_lifecycle.py' not in names:names.append('eval_lifecycle.py')
    profile['bridge_sources']=[pin(Path(__file__).with_name(name)) for name in names]
    profile.update(lifecycle_equivalence=deepcopy(approval_record),selected_fresh_worker_sha256=approval.data['variant_worker']['sha256'],
                   bridge_version='V5-startup900-family',results_root=str(results_root),tiny_page=1)
    return profile

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--original',type=Path,required=True);ap.add_argument('--variant',type=Path,required=True)
    ap.add_argument('--retained-entry',type=Path,required=True);ap.add_argument('--full-parent',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--delivery-provenance',type=Path);a=ap.parse_args()
    if a.output.exists():raise ValueError('Preserve immutable approval receipts')
    result=build_approval(pin(a.original),pin(a.variant),read(a.retained_entry),pin(a.full_parent),read(a.delivery_provenance) if a.delivery_provenance else None)
    save(a.output,result);validate_approval(pin(a.output));print(json.dumps({'approval':pin(a.output),'new_models':0,'image_decodes':0}))
