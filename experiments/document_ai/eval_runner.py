"""Queued, pure parser/scorer bridge. No readers, models or image decoding."""
from __future__ import annotations
import argparse
from copy import deepcopy
import csv
import json
from pathlib import Path
import sys
import time
from component_common import RESOURCES,checked,pin,read,save,verify_admission
from eval_assets import load,preflight,runtime
from eval_geometry import apply,digest

def output_path(profile,path):
    path=Path(path).resolve()
    if not path.is_relative_to(Path(profile['results_root']).resolve()) or path.exists():raise ValueError('New isolated result directory required')
    path.mkdir(parents=True);return path

def native_records(summary_record,profile,scope,check=checked):
    from eval_native import runtime_proof,table_upstream,table_options,validate_table_options
    summary=read(check(summary_record))
    if (summary.get('status')!='COMPLETE' or summary.get('contract')!='document-ai-component-trial.v1'
      or summary.get('component')!=profile['component'] or summary.get('new_text_OCR_calls')!=0
      or summary.get('optimizer_updates')!=0):raise ValueError('Actual completed geometry-only component required')
    if profile['component']=='docling' and summary.get('stage')=='layout':raise ValueError('Docling endpoint arm requires the completed table stage, not layout-only readiness')
    if profile['component']=='docling':
        selected=validate_table_options(profile.get('selected_native_table_options'))
        if selected['do_matching'] is not False or table_options(summary)!=selected:raise ValueError('Selected Docling table options differ from the frozen profile')
    plan=read(check(summary['plan']));check(summary['registry']);check(summary['materialization'])
    if (plan['component']!=profile['component'] or plan.get('new_text_OCR_calls')!=0
      or (plan.get('retained_cache_manifest') or {}).get('sha256')!=profile['pins']['cache']['sha256']):raise ValueError('Native source-only/cache bytes changed')
    records={};observations={}
    for record in summary['page_results']:
        page=read(check(record));n=page['page']
        if page.get('component')!=profile['component']:raise ValueError('Native observation component differs from its summary/profile')
        if n in records:raise ValueError('Duplicate native source page')
        records[n]=record;observations[n]=page
    if any(p.get('upstream_layout_observation') for p in observations.values()) and summary.get('stage')!='tables':raise ValueError('Split-stage layout provenance requires an explicit tables summary')
    if len(records)!=summary['pages_completed']:raise ValueError('Native completion count mismatch')
    if summary.get('native_shard_summaries'):
        from eval_merge import aggregate
        actual=aggregate(summary['native_shard_summaries'],summary['actual_closed_supervision_receipts'],check=check)
        if actual!=summary:raise ValueError('Aggregated native metadata differs from its actual shards')
    else:
        runtime_proof(summary,check);table_upstream(summary,observations,check)
    required={profile['tiny_page']} if scope=='tiny' else set(range(1,485))
    if (not required<=set(records) or scope=='full484' and (set(records)!=required
      or summary.get('complete_full_inventory') is not True)):raise ValueError('Native coverage incomplete; not an all484 component measurement')
    return records,summary


def tiny_gate(profile,receipt,check=checked,native_identity=None):
    result=read(check(receipt))
    if (result.get('status')!='COMPLETE' or result.get('scope')!='DIAGNOSTIC_TINY_NOT_FULL585'
      or result.get('actual_scorer_invocations')!=2 or result.get('profile_sha256')!=digest(profile)
      or result.get('component')!=profile['component'] or result.get('writer_readback_verified') is not True):raise ValueError('Actual tiny parser/scorer/output preflight required before full484')
    for key in ('control_complete','candidate_complete','control_metrics','candidate_metrics'):check(result[key])
    if native_identity is not None:
        from eval_native import model_identity
        done=read(check(result['control_complete']));run=read(check(done['run_manifest']))
        old=read(check(run['native_summary']))
        if model_identity(old)!=native_identity:raise ValueError('Tiny/full native component/model/runtime identity differs')

def parse(profile,profile_record,native_record,variant,scope,out,tiny_receipt=None):
    preflight(profile)
    records,native=native_records(native_record,profile,scope)
    if scope=='full484':
        from eval_native import model_identity
        tiny_gate(profile,tiny_receipt,native_identity=model_identity(native))
    helpers=runtime(profile)
    shared=load('_docai_parse_stream',checked(profile['pins']['shared']))
    cache={p['page_number']:p for p in read(checked(profile['pins']['cache']))['pages']}
    numbers={profile['tiny_page']} if scope=='tiny' else set(range(1,485))
    out=output_path(profile,out);run={'contract':'document-ai-fixed323-parser-arm.v1','profile':profile_record,
      'native_summary':native_record,'variant':variant,'scope':scope,'baseline_reading':'saved_C4_323_same_RAW',
      'reference_access':False,'new_OCR_calls':0,'new_model_calls':0,'source_image_decodes':0,
      'tiny_receipt':tiny_receipt,'actual_native_model_calls_in_separate_stage':native['actual_model_predict_calls_started']}
    save(out/'run_manifest.json',run);seen=set();inventory=[];began=time.monotonic()
    with (out/'page_extractions.json').open('x',encoding='utf-8') as stream:
        stream.write('{"pages":[');first=True
        for parent in shared.PageBundle(checked(profile['pins']['parent_predictions'])):
            n=parent['page_number']
            if n not in numbers:continue
            if n in seen:raise ValueError('Duplicate canonical parent source')
            seen.add(n);item=read(checked(cache[n]));g=item['geometry'];before=digest(parent)
            if item['source_sha256']!=parent['source_sha256']:raise ValueError('Parent/cache source mismatch')
            if g.get('machine_only') is not True or g.get('vision_LLM_calls')!=0:raise ValueError('Retained recognition geometry must remain machine-only')
            flags=item['inference_inputs']
            if any(flags.get(k) is not False for k in ('reference','human_answers','Ada','StockDay')) or flags.get('assistant_image_reads')!=0:raise ValueError('Assisted cache refused')
            upright=helpers['io'].upright_from_original(parent,g,helpers['mapper'])
            observation=read(checked(records[n]));working=apply(upright,item,observation,helpers,records[n])
            # Control exercises the same actual adapter and conservation path,
            # then retains the verified canonical323 bytes instead of changes.
            guarded,guard=helpers['guard'](upright,working)
            mapped=helpers['mapper'](helpers['io'].core(guarded),g['original_size'],g['orientation_ccw'])
            for event in working['document_ai_geometry_association']['changes']:
                field=mapped['product_rows'][event['row_index']]['fields'][event['field']]
                proof=helpers['mapper']({'bbox':field['source_header_column_and_row_band']},g['original_size'],g['orientation_ccw'])
                field['source_header_column_and_row_band']=proof['bbox']
                field['source_header_column_and_row_band_coordinate_space']='original_image'
            candidate=deepcopy(parent);candidate.update(helpers['io'].core(mapped))
            if variant=='control':candidate=deepcopy(parent)
            else:
                candidate['document_ai_geometry_association']={**working['document_ai_geometry_association'],
                  'coordinate_space':'upright_image','canonical_coordinate_space':'original_image'}
                candidate['document_ai_source_conservation']=guard
                conserved,_=helpers['guard'](parent,candidate)
                if helpers['io'].core(conserved)!=helpers['io'].core(candidate):raise ValueError('Original-frame missing-only conservation failed')
            typed=helpers['finalize'](candidate,source_sha256=parent['source_sha256'],image_size=g['original_size'])
            if digest(parent)!=before:raise ValueError('Canonical parent mutated')
            save(out/f'extractions/page-{n:04d}.json',candidate);save(out/f'typed_results/page-{n:04d}.json',typed)
            if read(out/f'extractions/page-{n:04d}.json')!=candidate or typed['raw_page_sha256']!=digest(candidate):raise ValueError('Actual parser/typed writer readback differs')
            if not first:stream.write(',')
            first=False;json.dump(candidate,stream,ensure_ascii=False,allow_nan=False)
            inventory.append({'page_number':n,'source_sha256':parent['source_sha256'],'parent_content_sha256':before,
              'retained_cache':cache[n],
              'native_observation':records[n],'prediction_content_sha256':digest(candidate),
              'adapter_status':working['document_ai_geometry_association']['status'],
              'changes':working['document_ai_geometry_association']['changes'] if variant=='candidate' else []})
        stream.write('],"metadata":{"assistant_overlays":false,"vision_llm_calls":0,"new_OCR_calls":0}}')
    if seen!=numbers:raise ValueError('Incomplete canonical/source union')
    preflight(profile)
    save(out/'COMPLETE.json',{'status':'COMPLETE','scope':scope,'variant':variant,'pages':len(seen),'source_inventory':inventory,
      'prediction':pin(out/'page_extractions.json'),'run_manifest':pin(out/'run_manifest.json'),
      'elapsed_seconds':time.monotonic()-began,'new_OCR_calls':0,'new_model_calls':0,'source_image_decodes':0,'reference_access':False})
    return pin(out/'COMPLETE.json')

def compare_outcomes(reference,metrics,shared,scorer,prior,mapping):
    a,b=[shared.present_outcomes(reference,m) for m in metrics]
    if len(a)!=585 or set(a)!=set(b) or len({tuple(k) for k in prior['label_keys']})!=323 or {k for k,v in a.items() if v=='exact'}!={tuple(k) for k in prior['label_keys']}:raise ValueError('Control is not the exact frozen323 identity set')
    fixed=[list(k) for k in a if a[k]!='exact' and b[k]=='exact'];lost=[list(k) for k in a if a[k]=='exact' and b[k]!='exact']
    safety=shared.safety_transitions(reference,*metrics,scorer.CRITICAL_FIELDS)
    if safety['scope_supplier_code']!=57:raise ValueError('Supplier-code57 scope changed')
    company={p['page_number']:p['company_key'] for p in reference['pages']}
    diagnostic={(p['page_number'],p['source_sha256']):p['issuer_key'] for p in mapping['records']}
    axes={'primary13':company,'diagnostic38_and_unmapped':{p['page_number']:diagnostic.get((p['page_number'],p['source_sha256']),shared.UNMAPPED) for p in reference['pages']}}
    all_a,all_b=[shared.present_outcomes(reference,m,True) for m in metrics]
    absent={(p['page_number'],str(r['id']),k) for p in reference['pages'] for r in p['rows'] for k,v in r['fields'].items() if v.get('state','present')=='absent'}
    falsefills={tuple(k) for k in safety['new_absence_falsefill_fields']}
    result={'before_exact':323,'after_exact':sum(v=='exact' for v in b.values()),'product_present_denominator':585,
      'fixed':len(fixed),'fixed_fields':fixed,'prior323_lost':len(lost),'lost_fields':lost,'safety':safety,
      'all_frozen_sections':scorer.compare(*metrics),'numerical_release_eligible':safety['passed_no_new_wrong_exact_loss_or_falsefill'] and not lost,
      'production_activation':False,'known_development_set':True,'gold_labels':0}
    for name,axis in axes.items():
        names=sorted(set(axis.values()) | (set(mapping['issuer_groups']) if name.startswith('diagnostic') else set()))
        result[name]=[]
        for company_key in names:
            keys=[k for k in a if axis[k[0]]==company_key]
            all_keys=[k for k in all_a if axis[k[0]]==company_key]
            absence_keys=[k for k in absent if axis[k[0]]==company_key]
            result[name].append({'group':company_key,'denominator':len(keys),'before_exact':sum(a[k]=='exact' for k in keys),
              'after_exact':sum(b[k]=='exact' for k in keys),'fixed':sum(a[k]!='exact' and b[k]=='exact' for k in keys),
              'lost':sum(a[k]=='exact' and b[k]!='exact' for k in keys),
              'all_present_denominator':len(all_keys),'critical_denominator':sum(k[2] in scorer.CRITICAL_FIELDS for k in all_keys),
              'supplier_code_denominator':sum(k[2]=='supplier_code' for k in all_keys),'absence_denominator':len(absence_keys),
              'all_present_exact_losses':sum(all_a[k]=='exact' and all_b[k]!='exact' for k in all_keys),
              'new_wrong':sum(all_a[k]!='wrong' and all_b[k]=='wrong' for k in all_keys),
              'new_falsefills':sum(k in falsefills for k in absence_keys)})
    return result

def coverage_summary(reference,processed_images,metric):
    any_reference={p['page_number'] for p in reference['pages']}
    product_pages={p['page_number'] for p in reference['pages'] if any(v.get('state','present')=='present'
      for row in p['rows'] for v in row['fields'].values())}
    fields=sum(v.get('state','present')=='present' for p in reference['pages'] for row in p['rows'] for v in row['fields'].values())
    corpus=reference['corpus_page_count']
    return {'processed_original_images':processed_images,'full_source_inventory_images':corpus,
      'images_with_any_frozen_reference':len(any_reference),'images_with_product_present_reference':len(product_pages),
      'product_present_reference_fields':fields,'images_without_any_reference':corpus-len(any_reference),
      'images_without_product_present_reference':corpus-len(product_pages),
      'reference_row_completeness_scope_images':sum(p.get('rows_complete') is True for p in reference['pages']),
      'frozen_scorer_coverage':metric.get('coverage'),'frozen_label_scope_metrics':metric.get('by_label_scope'),
      'meaning':'Field agreement on the frozen labelled subset; never whole-page or all-content accuracy on484 images',
      'gold_labels':0,'known_development_set':True}

def score(profile,control,candidate,scope,out):
    preflight(profile);shared=load('_docai_eval_shared',checked(profile['pins']['shared']))
    scorer=load('_docai_eval_frozen_scorer',checked(profile['pins']['scorer']))
    groups=load('_docai_eval_groups',checked(profile['pins']['groups']))
    records=[read(Path(p)/'COMPLETE.json') for p in (control,candidate)]
    for expected,done in zip(('control','candidate'),records):
        if done.get('status')!='COMPLETE' or done.get('scope')!=scope or done.get('variant')!=expected:raise ValueError('Actual matched parser completions required')
        run=read(checked(done['run_manifest']))
        if run['profile']['sha256']!=pin(checked(run['profile']))['sha256'] or read(checked(run['profile']))!=profile:raise ValueError('Parser/evaluator profile differs')
    runs=[read(checked(r['run_manifest'])) for r in records]
    if runs[0]['native_summary']!=runs[1]['native_summary']:raise ValueError('Control/candidate native geometry differs')
    reference=read(checked(profile['pins']['reference']));mapping=read(checked(profile['pins']['mapping']))
    sources=dict(enumerate(read(checked(profile['pins']['sources']))['files'],1));groups.validate_mapping(mapping,sources)
    if scope=='tiny':reference['pages']=[p for p in reference['pages'] if p['page_number']==profile['tiny_page']]
    out=output_path(profile,out);metrics=[];reports=[]
    for name,done in zip(('control','candidate'),records):
        pages=[];seen=set()
        for page in shared.PageBundle(checked(done['prediction'])):
            n=page['page_number']
            if n in seen or n not in sources or page['source_sha256']!=sources[n]['sha256']:raise ValueError('Unbound/duplicate scored page')
            seen.add(n);pages.append(shared.validated_compact_page(page,scorer))
        required={profile['tiny_page']} if scope=='tiny' else set(range(1,485))
        if seen!=required:raise ValueError('Scoring source union differs')
        prediction={'pages':pages,'metadata':{'assistant_overlays':False,'vision_llm_calls':0}}
        if not groups.provenance(prediction,{n:sources[n] for n in required})['passed']:raise ValueError('Machine-only provenance failed')
        metric=scorer.assess(reference,prediction,machine_only=True);save(out/f'{name}_metrics.json',metric)
        if read(out/f'{name}_metrics.json')!=metric:raise ValueError('Actual metric writer readback failed')
        metrics.append(metric)
        if scope=='full484':
            report=shared.make_groups(groups,scorer,reference,prediction,metric,mapping)
            save(out/f'{name}_company_metrics.json',report);reports.append(report)
    if scope=='full484':
        result=compare_outcomes(reference,metrics,shared,scorer,read(checked(profile['pins']['prior323'])),mapping)
        result['coverage_summary']=coverage_summary(reference,484,metrics[0])
        cohort=read(checked(profile['pins']['cohort164']));keys=shared.cohort_keys(cohort);a,b=[shared.present_outcomes(reference,m) for m in metrics]
        if len(keys)!=164:raise ValueError('Residual164 diagnostic changed')
        result['residual_quantity_unit_164']={'denominator':164,'before_exact':sum(a[k]=='exact' for k in keys),
          'after_exact':sum(b[k]=='exact' for k in keys),'fixed':sum(a[k]!='exact' and b[k]=='exact' for k in keys),
          'lost':sum(a[k]=='exact' and b[k]!='exact' for k in keys)}
    else:result={'primary585_claim_allowed':False}
    from eval_native import model_identity,native_totals
    native=read(checked(runs[0]['native_summary']))
    result['native_component_identity']=model_identity(native)
    result['native_call_coverage']=native_totals(native)
    result.update(status='COMPLETE',scope='DIAGNOSTIC_TINY_NOT_FULL585' if scope=='tiny' else 'FULL484_FIXED585',
      component=profile['component'],profile_sha256=digest(profile),control_complete=pin(Path(control)/'COMPLETE.json'),
      candidate_complete=pin(Path(candidate)/'COMPLETE.json'),control_metrics=pin(out/'control_metrics.json'),
      candidate_metrics=pin(out/'candidate_metrics.json'),actual_scorer_invocations=2,writer_readback_verified=True,
      new_OCR_calls=0,new_model_calls=0,source_image_decodes=0)
    save(out/'RESULT.json',result);return pin(out/'RESULT.json')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['preflight','parse','score'])
    p.add_argument('--profile',type=Path,required=True);p.add_argument('--profile-sha256',required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--admission',type=Path);p.add_argument('--admission-sha256')
    p.add_argument('--variant',choices=['control','candidate']);p.add_argument('--scope',choices=['tiny','full484'])
    p.add_argument('--native-summary',type=Path);p.add_argument('--native-sha256');p.add_argument('--tiny-receipt',type=Path);p.add_argument('--tiny-sha256')
    p.add_argument('--control',type=Path);p.add_argument('--candidate',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    profile_record={'path':str(a.profile.resolve()),'sha256':a.profile_sha256};profile=read(checked(profile_record));proof=preflight(profile)
    if not a.execute or a.action=='preflight':print(proof);return
    verify_admission(a.admission,a.admission_sha256,__file__,'endpoint-eval')
    if a.action=='parse':
        result=parse(profile,profile_record,{'path':str(a.native_summary.resolve()),'sha256':a.native_sha256},a.variant,a.scope,a.output,
          {'path':str(a.tiny_receipt.resolve()),'sha256':a.tiny_sha256} if a.tiny_receipt else None)
    else:result=score(profile,a.control,a.candidate,a.scope,a.output)
    print(result)

if __name__=='__main__':main()
