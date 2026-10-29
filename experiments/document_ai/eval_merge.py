"""Verify all native shards before declaring a full484 model observation union."""
from __future__ import annotations
import argparse
from pathlib import Path
from component_common import checked,pin,read,save
from eval_native import witness,runtime_proof,table_upstream,table_options,worker_identity

def aggregate(shards,supervision_receipts,expected_shards=None,check=checked,lifecycle_equivalence=None):
    # Partition size is an execution choice, not an accuracy denominator.
    # Closure, identity and the exact source union below establish completeness.
    if not 1<=len(shards)<=484 or expected_shards is not None and len(shards)!=expected_shards:raise ValueError('All expected nonempty native shards required')
    witness(shards,supervision_receipts,check)
    base=None;pages={};calls={'actual_model_predict_calls_started':0,'actual_completed_layout_model_calls':0,'actual_completed_table_model_calls':0};elapsed=0
    runtime_proofs=[];upstream_chains=[];producers=[];approval=None
    if lifecycle_equivalence is not None:
        from eval_lifecycle import validate_approval
        approval=validate_approval(lifecycle_equivalence,check)
    for record in shards:
        summary=read(check(record))
        if (summary.get('contract')!='document-ai-component-trial.v1' or summary.get('status')!='COMPLETE'
          or summary.get('full_source_inventory_pages')!=484 or summary.get('new_text_OCR_calls')!=0
          or summary.get('optimizer_updates')!=0):raise ValueError('Partial/incorrect source regime')
        identity={k:summary[k] for k in ('component','plan','registry','materialization')}
        identity['stage']=summary.get('stage','combined')
        identity['runtime_versions']=summary.get('runtime_versions')
        identity['native_table_options']=table_options(summary)
        if approval:
            from eval_lifecycle import recipe_identity,lineage
            identity.update(recipe_identity(summary,approval))
            producers.append(lineage(summary,record,approval))
        else:identity['worker_sha256']=worker_identity(summary)
        for key in ('plan','registry','materialization'):check(identity[key])
        if base is None:base=identity
        if identity!=base:raise ValueError('Shard model/data/plan/registry identities differ')
        plan=read(check(summary['plan']));tasks={t['page']:t for t in plan['tasks']}
        if len(plan['tasks'])!=484 or set(tasks)!=set(range(1,485)):raise ValueError('Frozen original484 native plan required')
        selected=summary.get('selected_pages')
        if (not isinstance(selected,list) or not 1<=len(selected)<=64
          or any(type(n) is not int for n in selected) or len(set(selected))!=len(selected)):raise ValueError('Native partitions must contain1..64 unique source pages')
        actual=set();observations={}
        for page_record in summary['page_results']:
            page=read(check(page_record));n=page['page']
            if n in actual or n in pages or n not in tasks:raise ValueError('Duplicate/outside native page')
            if (page.get('contract')!='document-ai-original-frame-geometry.v1' or page.get('component')!=base['component'] or page.get('source_image')!=tasks[n]['source_image']
              or page.get('source_frame')!='original_image' or page.get('source_size')!=tasks[n]['source_size']
              or page.get('new_text_OCR_calls')!=0 or page.get('assistant_image_transcription') is not False):raise ValueError('Native page/source binding changed')
            actual.add(n);pages[n]=page_record;observations[n]=page
        if (len(actual)!=summary['pages_completed'] or actual!=set(selected)
          or summary.get('complete_full_inventory') is not (len(actual)==484)):raise ValueError('Shard claimed completion/coverage differs')
        proof=runtime_proof(summary,check)
        if proof:runtime_proofs.append({'native_summary':record,**proof})
        if summary['component']=='docling' and summary.get('stage') in ('layout','tables'):
            start=summary.get('slice_start');count=summary.get('slice_count')
            if (type(start) is not int or type(count) is not int or start<0 or not 0<count<=64
              or summary.get('complete_stage_shard') is not True
              or summary['selected_pages']!=[t['page'] for t in plan['tasks'][start:start+count]]):raise ValueError('Actual Docling full-plan shard slice differs')
            upstream_chains+=table_upstream(summary,observations,check)
        for key in calls:
            value=summary.get(key)
            if type(value) is not int or value<0:raise ValueError('Actual native call counters required')
            calls[key]+=value
        elapsed+=summary['elapsed_seconds']
    if set(pages)!=set(range(1,485)):raise ValueError('Missing native pages; no full484 claim allowed')
    provenance={}
    if approval:
        fresh=[n for p in producers if p['lifecycle']=='fresh_startup900' for n in p['selected_pages']]
        retained=[n for p in producers if p['lifecycle']=='retained_startup480' for n in p['selected_pages']]
        if sorted(retained)!=list(range(1,65)) or sorted(fresh)!=list(range(65,485)):
            raise ValueError('Lifecycle union must retain exact64b1d and execute exact420fresh900 table pages')
        provenance={'lifecycle_equivalence':lifecycle_equivalence,
          'actual_worker_sha256s':sorted({p['actual_worker']['sha256'] for p in producers}),
          'actual_native_producers':producers,'fresh_startup900_pages':sorted(fresh),'retained_startup480_pages':sorted(retained),
          'original_producer_identities_relabelled':False,'same_operational_admission_claimed':False}
    return {'contract':'document-ai-component-trial.v1','status':'COMPLETE',**base,**provenance,'page_results':[pages[n] for n in sorted(pages)],
      'pages_completed':484,'full_source_inventory_pages':484,'selected_pages':list(range(1,485)),'complete_full_inventory':True,
      'native_shard_summaries':shards,'actual_closed_supervision_receipts':supervision_receipts,'native_shards':len(shards),
      'partition_policy':{'maximum_sources_per_shard':64,'unique_source_union':484,'duplicates':0,'missing':0},
      'native_runtime_proofs':runtime_proofs,'actual_upstream_layout_chains':upstream_chains,
      **calls,'elapsed_seconds':elapsed,'new_text_OCR_calls':0,'optimizer_updates':0,'endpoint_score_status':'NOT_EVALUATED',
      'endpoint_gain':None,'known_development_set':True,'production_activation':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--shard',type=Path,action='append',required=True)
    p.add_argument('--supervision',type=Path,action='append',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--lifecycle-equivalence',type=Path);a=p.parse_args()
    result=aggregate([pin(x) for x in a.shard],[pin(x) for x in a.supervision],lifecycle_equivalence=pin(a.lifecycle_equivalence) if a.lifecycle_equivalence else None)
    save(a.output,result);print(pin(a.output))
