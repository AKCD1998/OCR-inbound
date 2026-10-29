"""Separate proof-bound correction arm, using retained OCR/native geometry only.

Parse never opens reference/outcome files. Score alone loads the frozen labels
and calls the original scorer twice. The old missing-only adapter/guard remains
unchanged; this arm explicitly uses correction_guard's revision policy.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import time
from component_common import checked,pin,read,save,sha,verify_admission,RESOURCES
from eval_assets import load,runtime,EXPECTED
from eval_geometry import digest
from eval_native import record_key,resource_closed

PROFILE_SHA='2c7a3759bf2edc3fd55662581a9d30b2e0eaf203e3066d865018dfdbd32ed153'
NATIVE_SHA='f48092df6a7ae7abeabad7588c397e053eb8e4a7487712ec38fcbde3f679fde3'
CLOSED_SHA='b9ab4f9bc4a3b80622a1aec9da04ac9b749e105c66bcf5fde112980b3cef4852'
CONTROL_SHA='20c70db63ee7a47305230468a50aa80ad637f1ea6ca7dfa56fb43ce9c5b73017'
PREDICTION_SHA='8efb98656df2df56ee28393b5a0b90ee9e3ff2d295bd9c2dab27e0e88379b7a4'
SCOPE={'pages':484,'product_present':585,'all_present':602,'critical':329,'supplier_code':57,'absence':18,'prior_exact':323}
RUNTIME_KEYS=('cache','frame_io','sources')
LEGACY_CORRECTION_SOURCES={'bridge':'a0ba699ee400ff8c60828b5dc78c5aba35851aeedebbb40c99656d0eb14ec73b',
 'guard':'96ec134180bdc7a0e35317abe2c0752c717cd116afdba8451e98944e6bd090a4'}
COMPONENT_MODULES={'document_admission':'document_source_admission',
                   'cell_association':'source_cell_association'}

def same(a,b):return isinstance(a,dict) and isinstance(b,dict) and record_key(a)==record_key(b)

def panel_pages(panel,sources):
    if set(panel)!={'contract','pages','source_inventory'} or panel['contract']!='document-ai-correction-pilot-panel.v1':
        raise ValueError('Source-only runtime panel; labels/outcomes/rationale forbidden')
    pages=panel['pages']
    if not isinstance(pages,list) or not 12<=len(pages)<=64:raise ValueError('Prospectively pinned12..64 source pages required')
    result={}
    for item in pages:
        if set(item)!={'page_number','source_sha256'}:raise ValueError('Runtime panel contains non-source information')
        n=item['page_number']
        if type(n) is not int or n not in sources or n in result or item['source_sha256']!=sources[n]['sha256']:
            raise ValueError('Unbound/duplicate panel source')
        result[n]=item['source_sha256']
    return result

def preflight(experiment_record,check=checked):
    spec=read(check(experiment_record))
    if (spec.get('contract')!='document-ai-source-correction-experiment.v1' or spec.get('approved_by')!='root'
      or spec.get('production_activation') is not False or spec.get('parser_reference_access') is not False
      or spec.get('new_OCR_calls')!=0 or spec.get('new_model_calls')!=0):raise ValueError('Explicit isolated root correction arm required')
    expected={'profile':PROFILE_SHA,'native_summary':NATIVE_SHA,'native_closed_source':CLOSED_SHA,
              'baseline_complete':CONTROL_SHA,'baseline_prediction':PREDICTION_SHA}
    for key,value in expected.items():
        if spec[key]['sha256']!=value:raise ValueError('Frozen source/control identity changed: '+key)
        check(spec[key])
    required={'runner','bridge','guard','frozen_eval_runner'}
    active=spec.get('active_components',[])
    if (not isinstance(active,list) or any(type(name) is not str for name in active) or len(set(active))!=len(active)
      or any(name not in COMPONENT_MODULES for name in active)
      or set(spec['sources']) not in (required|set(active),required|{'eligibility'}|set(active))
      or active and 'eligibility' not in spec['sources']):raise ValueError('Explicit bounded component/source closure required')
    if ('eligibility' in spec['sources'])!=('eligibility_policy' in spec):raise ValueError('Explicit eligibility policy/source binding required')
    if 'eligibility' in spec['sources'] and not same(spec['eligibility_policy'],spec['sources']['eligibility']):raise ValueError('Eligibility policy/source differs')
    if 'eligibility' not in spec['sources'] and any(spec['sources'][key]['sha256']!=value for key,value in LEGACY_CORRECTION_SOURCES.items()):
        raise ValueError('Only exact original V1 bridge/guard may omit the eligibility dependency pin')
    if spec['sources']['runner']['sha256']!=sha(__file__) or spec['sources']['frozen_eval_runner']['sha256']!='1538e7b5ba42cf178c24b70abf6081c5c39d02161afce2fe44b5802ef39eb5f9':
        raise ValueError('Actual correction runner/frozen scorer bridge differs')
    for record in spec['sources'].values():check(record)
    profile=read(check(spec['profile']))
    if profile.get('expected_scope')!=SCOPE:raise ValueError('Fixed585/602/329/57/18/prior323 scope changed')
    for key,value in EXPECTED.items():
        if profile['pins'][key]['sha256']!=value:raise ValueError('Frozen metric/control pin changed')
    # Intentionally no reference, prior323, metric, cohort or issuer-mapping read.
    for record in [profile['pins'][k] for k in RUNTIME_KEYS]+profile['parser_sources']+profile['final164_source_files']+profile['dependencies']+profile['bridge_sources']:
        check(record)
    sources=dict(enumerate(read(check(profile['pins']['sources']))['files'],1))
    if set(sources)!=set(range(1,485)):raise ValueError('Fixed source inventory required')
    panel=read(check(spec['panel']))
    if not same(panel.get('source_inventory'),profile['pins']['sources']):raise ValueError('Panel source inventory differs')
    selected=panel_pages(panel,sources)
    native=read(check(spec['native_summary']));closed=read(check(spec['native_closed_source']))
    if (native.get('status')!='COMPLETE' or native.get('pages_completed')!=484 or native.get('complete_full_inventory') is not True
      or native.get('selected_pages')!=list(range(1,485)) or len(native.get('page_results',[]))!=484
      or not any(same(r,spec['native_closed_source']) for r in native.get('actual_closed_supervision_receipts',[]))
      or closed.get('status')!='COMPLETE' or closed.get('failure') is not None
      or closed.get('shared_lock_released_after_owned_closure') is not True
      or closed.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True or len(closed.get('resources',[]))!=16):
        raise ValueError('Already-completed native484/closed source required')
    for resource in closed['resources']:resource_closed(resource)
    control=read(check(spec['baseline_complete']));run=read(check(control['run_manifest']))
    if (control.get('status')!='COMPLETE' or control.get('variant')!='control' or control.get('scope')!='full484' or control.get('pages')!=484
      or not same(control.get('prediction'),spec['baseline_prediction']) or not same(run.get('profile'),spec['profile'])
      or not same(run.get('native_summary'),spec['native_summary'])):raise ValueError('Canonical saved323 control differs')
    return spec,profile,sources,selected,native,control

def selected_numbers(scope,panel):
    if scope=='panel':return set(panel)
    if scope=='full484':return set(range(1,485))
    raise ValueError('Explicit panel or full484 required')

def load_eligibility(spec,check=checked):
    """Pin the one added dependency before Python resolves bridge imports."""
    record=spec['sources'].get('eligibility')
    if record is None:return None
    actual=Path(check(record)).resolve();existing=sys.modules.get('correction_eligibility')
    if existing is not None and (not getattr(existing,'__file__',None) or Path(existing.__file__).resolve()!=actual or sha(actual)!=record['sha256']):
        raise ValueError('Unapproved preloaded correction eligibility module')
    module=existing if existing is not None else load('correction_eligibility',actual)
    if sys.modules.get('correction_eligibility') is not module or Path(module.__file__).resolve()!=actual or sha(actual)!=record['sha256']:
        raise ValueError('Actual correction eligibility import/source differs')
    return module


def load_components(spec,check=checked):
    """Resolve only explicitly selected, hash-bound experimental components."""
    result={}
    for role in spec.get('active_components',[]):
        name=COMPONENT_MODULES[role];record=spec['sources'][role]
        actual=Path(check(record)).resolve();existing=sys.modules.get(name)
        if existing is not None and (not getattr(existing,'__file__',None)
          or Path(existing.__file__).resolve()!=actual or sha(actual)!=record['sha256']):
            raise ValueError('Unapproved preloaded component: '+role)
        module=existing if existing is not None else load(name,actual)
        if (sys.modules.get(name) is not module or Path(module.__file__).resolve()!=actual
          or sha(actual)!=record['sha256']):raise ValueError('Actual component import/source differs: '+role)
        result[role]=module
    return result

def pilot_gate(spec_record,spec,score_record,closed_record,check=checked):
    score=read(check(score_record));closed=read(check(closed_record))
    if (score.get('status')!='COMPLETE' or score.get('scope')!='CORRECTION_PILOT_PANEL'
      or not same(score.get('experiment'),spec_record) or not same(score.get('panel'),spec['panel'])
      or score.get('actual_scorer_invocations')!=2 or score.get('writer_readback_verified') is not True
      or type(score.get('fixed')) is not int or score['fixed']<=0 or score.get('prior323_lost')!=0
      or score.get('safety',{}).get('exact_loss_count')!=0 or score['safety'].get('new_wrong_count_all602')!=0
      or score['safety'].get('new_absence_falsefill_count')!=0):raise ValueError('Actual gaining, zero-regression pilot required before full484')
    if (closed.get('status')!='COMPLETE' or closed.get('failure') is not None
      or closed.get('cleanup',{}).get('confirmed_all_known_owned_exited') is not True
      or closed.get('shared_lock_released_after_owned_closure') is not True):raise ValueError('Pilot physical closure required')
    resources=closed.get('resources',[]);expected=[score['control_complete'],score['candidate_complete'],score_record]
    if [r.get('stage') for r in resources]!=['control','candidate','paired_score']:raise ValueError('Actual pilot parser pair/scorer required')
    config=read(check(closed['config']))
    if (config.get('source',{}).get('sha256')!='87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'
      or config.get('resource_policy')!=RESOURCES or [s.get('id') for s in config.get('steps',[])]!=['control','candidate','paired_score']
      or any(s.get('worker',{}).get('sha256')!=spec['sources']['runner']['sha256'] or s.get('optimizer_updates_allowed') is not False for s in config['steps'])):
        raise ValueError('Actual pilot must use this correction source/original supervision')
    for index,(resource,record) in enumerate(zip(resources,expected)):
        resource_closed(resource)
        if (resource.get('child_started') is not True or resource.get('worker_optimizer_updates_permission') is not False
          or not same(resource.get('worker_summary'),record)):raise ValueError('Actual pilot child/source differs')
        check(record)
        if index<2:
            done=read(check(record));run=read(check(done['run_manifest']))
            if (done.get('scope')!='panel' or done.get('variant')!=('control','candidate')[index]
              or not same(run.get('experiment'),spec_record) or not same(run.get('panel'),spec['panel'])
              or run.get('reference_access') is not False):raise ValueError('Pilot parser completion/source binding differs')
    return score

def nonempty(field):
    return isinstance(field,dict) and any(v is not None and (not isinstance(v,str) or bool(v.strip())) for v in (field.get('raw_value'),field.get('normalized_value')))

def revisions(before,after,accepted):
    seen=set();counts={'accepted_field_revisions':0,'nonempty_replacements':0,'missing_fills':0,'source_provenance_only_changes':0};events=[]
    for event in accepted:
        i,field=event['row_index'],event['field'];key=(i,field)
        if type(i) is not int or i<0 or field not in ('quantity','unit') or key in seen:raise ValueError('Unique admitted quantity/unit revision required')
        seen.add(key);a=(before['product_rows'][i].get('fields') or {}).get(field);b=(after['product_rows'][i].get('fields') or {}).get(field)
        if a==b:raise ValueError('Admitted revision did not change its source field')
        changed=[(a or {}).get(k) for k in ('raw_value','normalized_value')]!=[(b or {}).get(k) for k in ('raw_value','normalized_value')]
        counts['accepted_field_revisions']+=1
        if changed:counts['nonempty_replacements' if nonempty(a) else 'missing_fills']+=1
        else:counts['source_provenance_only_changes']+=1
        events.append({'row_index':i,'field':field,'before':deepcopy(a),'after':deepcopy(b),'prior_nonempty':nonempty(a),'semantic_value_changed':changed})
    return counts,events

def outdir(spec,path):
    path=Path(path).resolve()
    if not path.is_relative_to(Path(spec['results_root']).resolve()) or path.exists():raise ValueError('New isolated correction output required')
    path.mkdir(parents=True);return path

def parse(experiment_record,scope,variant,output,pilot_score=None,pilot_closed=None):
    spec,profile,sources,panel,native,control=preflight(experiment_record)
    if variant not in ('control','candidate'):raise ValueError('Explicit parser arm required')
    if scope=='full484':pilot_gate(experiment_record,spec,pilot_score,pilot_closed)
    numbers=selected_numbers(scope,panel);out=outdir(spec,output);began=time.monotonic()
    shared=load('_correction_stream',checked(profile['pins']['shared']))
    bridge=guard=helpers=None
    if variant=='candidate':
        load_eligibility(spec)
        helpers=runtime(profile);bridge=load('correction_bridge',checked(spec['sources']['bridge']))
        helpers.update(load_components(spec));helpers['correction_bridge']=bridge
        guard=load('correction_guard',checked(spec['sources']['guard']))
    cache={p['page_number']:p for p in read(checked(profile['pins']['cache']))['pages']}
    expected={x['page_number']:x for x in control['source_inventory']};seen=set();inventory=[]
    counts={'accepted_field_revisions':0,'nonempty_replacements':0,'missing_fills':0,'source_provenance_only_changes':0}
    run={'contract':'document-ai-source-correction-parser.v1','experiment':experiment_record,'profile':spec['profile'],
      'native_summary':spec['native_summary'],'baseline_complete':spec['baseline_complete'],'baseline_prediction':spec['baseline_prediction'],
      'panel':spec['panel'],'scope':scope,'variant':variant,'new_correction_policy':spec['sources']['guard'],
      'active_components':deepcopy(spec.get('active_components',[])),
      'old_missing_only_policy_modified':False,'reference_access':False,'new_OCR_calls':0,'new_model_calls':0,'source_image_decodes':0,
      'pilot_score':pilot_score,'pilot_closed':pilot_closed}
    save(out/'run_manifest.json',run)
    with (out/'page_extractions.json').open('x',encoding='utf8') as stream:
        stream.write('{"pages":[');first=True
        for parent in shared.PageBundle(checked(spec['baseline_prediction'])):
            n=parent['page_number']
            if n not in numbers:continue
            before=digest(parent)
            if n in seen or parent['source_sha256']!=sources[n]['sha256'] or expected[n]['prediction_content_sha256']!=before:
                raise ValueError('Canonical baseline page/source/content differs')
            seen.add(n);candidate=deepcopy(parent);events=[];audit={'status':'CONTROL_REUSED_WITHOUT_ADAPTER','accepted_changes':[]}
            if variant=='candidate':
                item=read(checked(cache[n]));g=item['geometry'];flags=item['inference_inputs'];observation_pin=native['page_results'][n-1]
                observation=read(checked(observation_pin))
                if (item['source_sha256']!=parent['source_sha256'] or g.get('machine_only') is not True or g.get('vision_LLM_calls')!=0
                  or any(flags.get(k) is not False for k in ('reference','human_answers','Ada','StockDay')) or flags.get('assistant_image_reads')!=0
                  or observation.get('page')!=n or observation.get('source_image',{}).get('sha256')!=parent['source_sha256']):raise ValueError('Unbound/assisted retained input')
                sealed=digest([item,observation]);upright=helpers['io'].upright_from_original(parent,g,helpers['mapper'])
                proposal=bridge.propose_and_apply(upright,item,observation,helpers,observation_pin)
                guarded,audit=guard.conserve_corrections(upright,proposal,item,observation,helpers,observation_pin)
                mapped=helpers['mapper'](helpers['io'].core(guarded),g['original_size'],g['orientation_ccw'])
                for event in audit['accepted_changes']:
                    field=mapped['product_rows'][event['row_index']]['fields'][event['field']]
                    if field.get('source_header_column_and_row_band'):
                        field['source_header_column_and_row_band']=helpers['mapper']({'bbox':field['source_header_column_and_row_band']},g['original_size'],g['orientation_ccw'])['bbox']
                        field['source_header_column_and_row_band_coordinate_space']='original_image'
                candidate,projection=guard.project_corrections(parent,mapped,audit)
                page_counts,events=revisions(parent,candidate,audit['accepted_changes'])
                for key,value in page_counts.items():counts[key]+=value
                candidate['document_ai_correction_association']={'contract':'document-ai-correction-canonical-audit.v1',
                  'bridge_proposal':deepcopy(proposal['document_ai_correction_association']),'changes':deepcopy(events),
                  'final_acceptance_authority':'document_ai_correction_conservation','effective_changes_coordinate_space':'original_image',
                  'bridge_proposal_coordinate_space':'upright_image'}
                candidate['document_ai_correction_conservation']={'upright_policy':audit,'original_projection':projection,'audit_coordinate_space':'upright_image','canonical_coordinate_space':'original_image'}
                typed=helpers['finalize'](candidate,source_sha256=parent['source_sha256'],image_size=g['original_size'])
                save(out/f'typed_results/page-{n:04d}.json',typed)
                if read(out/f'typed_results/page-{n:04d}.json')!=typed or typed['raw_page_sha256']!=digest(candidate):raise ValueError('Typed correction writer readback differs')
                if digest([item,observation])!=sealed:raise ValueError('Correction mutated retained/native input')
            if digest(parent)!=before:raise ValueError('Canonical baseline was mutated')
            save(out/f'extractions/page-{n:04d}.json',candidate)
            if read(out/f'extractions/page-{n:04d}.json')!=candidate:raise ValueError('Correction writer readback differs')
            if not first:stream.write(',')
            first=False;json.dump(candidate,stream,ensure_ascii=False,allow_nan=False)
            inventory.append({'page_number':n,'source_sha256':parent['source_sha256'],'parent_content_sha256':before,
              'prediction_content_sha256':digest(candidate),'changes':events,'guard_status':audit.get('status')})
        stream.write('],"metadata":{"assistant_overlays":false,"vision_llm_calls":0,"new_OCR_calls":0}}')
    if seen!=numbers:raise ValueError('Incomplete selected canonical source union')
    done={'status':'COMPLETE','scope':scope,'variant':variant,'pages':len(seen),'source_inventory':inventory,'revision_counts':counts,
      'prediction':pin(out/'page_extractions.json'),'run_manifest':pin(out/'run_manifest.json'),'elapsed_seconds':time.monotonic()-began,
      'reference_access':False,'new_OCR_calls':0,'new_model_calls':0,'source_image_decodes':0,'writer_readback_verified':True}
    save(out/'COMPLETE.json',done);return pin(out/'COMPLETE.json')

def compare_panel(reference,metrics,shared,scorer,prior,mapping,primary_names=None):
    a,b=[shared.present_outcomes(reference,m) for m in metrics];all_a,all_b=[shared.present_outcomes(reference,m,True) for m in metrics]
    numbers={p['page_number'] for p in reference['pages']};expected={tuple(k) for k in prior['label_keys'] if k[0] in numbers}
    if set(a)!=set(b) or {k for k,v in a.items() if v=='exact'}!=expected:raise ValueError('Panel control is not the frozen prior323 subset')
    fixed=[list(k) for k in a if a[k]!='exact' and b[k]=='exact'];lost=[list(k) for k in a if a[k]=='exact' and b[k]!='exact']
    wrong=[list(k) for k in all_a if all_a[k]!='wrong' and all_b[k]=='wrong'];losses=[list(k) for k in all_a if all_a[k]=='exact' and all_b[k]!='exact']
    absence={(p['page_number'],str(r['id']),f) for p in reference['pages'] for r in p['rows'] for f,v in r['fields'].items() if v.get('state','present')=='absent'}
    fills=[{(e['page'],str(e['row_id']),e['field']) for e in m['errors'] if e['status']=='unexpected_present'} for m in metrics]
    falsefills=[list(k) for k in sorted(absence & (fills[1]-fills[0]))]
    safety={'scope_present':len(all_a),'scope_critical':sum(k[2] in scorer.CRITICAL_FIELDS for k in all_a),
      'scope_supplier_code':sum(k[2]=='supplier_code' for k in all_a),'absence_scope_separate':len(absence),
      'new_wrong_count_all602':len(wrong),'new_wrong_fields_all602':wrong,'exact_loss_count':len(losses),'exact_loss_fields':losses,
      'new_critical_wrong_count':sum(k[2] in scorer.CRITICAL_FIELDS for k in wrong),
      'new_source_code_wrong_count':sum(k[2]=='supplier_code' for k in wrong),
      'new_absence_falsefill_count':len(falsefills),'new_absence_falsefill_fields':falsefills,
      'passed_no_new_wrong_exact_loss_or_falsefill':not wrong and not losses and not falsefills,'subset_only':True,
      'no_old_wrong_withdrawal_offsets_new_wrong':True}
    result={'before_exact':sum(v=='exact' for v in a.values()),'after_exact':sum(v=='exact' for v in b.values()),
      'product_present_denominator':len(a),'fixed':len(fixed),'fixed_fields':fixed,'prior323_lost':len(lost),'lost_fields':lost,
      'safety':safety,'full585_claim_allowed':False,'absence_zero_scope_is_not_all18_test':len(absence)==0,
      'absence_test_is_full18':len(absence)==18,
      'all_frozen_sections':scorer.compare(*metrics),'production_activation':False,'known_development_set':True,'gold_labels':0}
    primary={p['page_number']:p['company_key'] for p in reference['pages']}
    diagnostic={(r['page_number'],r['source_sha256']):r['issuer_key'] for r in mapping['records']}
    axes={'primary13':primary,'diagnostic38_and_unmapped':{p['page_number']:diagnostic.get((p['page_number'],p['source_sha256']),shared.UNMAPPED) for p in reference['pages']}}
    for name,axis in axes.items():
        names=sorted(set(axis.values()) | (set(mapping['issuer_groups']) if name.startswith('diagnostic') else set(primary_names or [])))
        result[name]=[]
        for company in names:
            keys=[k for k in a if axis[k[0]]==company];allkeys=[k for k in all_a if axis[k[0]]==company];abskeys=[k for k in absence if axis[k[0]]==company]
            result[name].append({'group':company,'denominator':len(keys),'before_exact':sum(a[k]=='exact' for k in keys),'after_exact':sum(b[k]=='exact' for k in keys),
              'fixed':sum(a[k]!='exact' and b[k]=='exact' for k in keys),'lost':sum(a[k]=='exact' and b[k]!='exact' for k in keys),
              'all_present_denominator':len(allkeys),'critical_denominator':sum(k[2] in scorer.CRITICAL_FIELDS for k in allkeys),
              'supplier_code_denominator':sum(k[2]=='supplier_code' for k in allkeys),'absence_denominator':len(abskeys),
              'all_present_exact_losses':sum(all_a[k]=='exact' and all_b[k]!='exact' for k in allkeys),
              'new_wrong':sum(all_a[k]!='wrong' and all_b[k]=='wrong' for k in allkeys),'new_falsefills':sum(list(k) in falsefills for k in abskeys)})
    return result

def score(experiment_record,scope,control_path,candidate_path,output):
    spec,profile,sources,panel,native,baseline=preflight(experiment_record);numbers=selected_numbers(scope,panel)
    from eval_assets import preflight as metric_preflight
    metric_preflight(profile)
    shared=load('_correction_score_shared',checked(profile['pins']['shared']));scorer=load('_correction_frozen_scorer',checked(profile['pins']['scorer']))
    groups=load('_correction_frozen_groups',checked(profile['pins']['groups']));frozen=load('_correction_prior_eval',checked(spec['sources']['frozen_eval_runner']))
    done=[read(Path(p)/'COMPLETE.json') for p in (control_path,candidate_path)]
    for name,item in zip(('control','candidate'),done):
        run=read(checked(item['run_manifest']))
        if (item.get('status')!='COMPLETE' or item.get('scope')!=scope or item.get('variant')!=name
          or not same(run.get('experiment'),experiment_record) or run.get('reference_access') is not False):raise ValueError('Actual matched correction parser completions required')
        if scope=='full484':pilot_gate(experiment_record,spec,run['pilot_score'],run['pilot_closed'])
    reference=read(checked(profile['pins']['reference']));full_reference=reference;mapping=read(checked(profile['pins']['mapping']));prior=read(checked(profile['pins']['prior323']))
    groups.validate_mapping(mapping,sources)
    if scope=='panel':reference={**reference,'pages':[p for p in reference['pages'] if p['page_number'] in numbers]}
    out=outdir(spec,output);metrics=[]
    for name,item in zip(('control','candidate'),done):
        pages=[];seen=set()
        for page in shared.PageBundle(checked(item['prediction'])):
            n=page['page_number']
            if n in seen or n not in numbers or page['source_sha256']!=sources[n]['sha256']:raise ValueError('Unbound scored correction source')
            seen.add(n);pages.append(shared.validated_compact_page(page,scorer))
        if seen!=numbers:raise ValueError('Scoring selected union differs')
        prediction={'pages':pages,'metadata':{'assistant_overlays':False,'vision_llm_calls':0}}
        if not groups.provenance(prediction,{n:sources[n] for n in numbers})['passed']:raise ValueError('Machine-only correction provenance failed')
        metric=scorer.assess(reference,prediction,machine_only=True);save(out/(name+'_metrics.json'),metric)
        if read(out/(name+'_metrics.json'))!=metric:raise ValueError('Actual metric writer readback failed')
        metrics.append(metric)
        if scope=='full484':save(out/(name+'_company_metrics.json'),shared.make_groups(groups,scorer,reference,prediction,metric,mapping))
    result=frozen.compare_outcomes(reference,metrics,shared,scorer,prior,mapping) if scope=='full484' else compare_panel(reference,metrics,shared,scorer,prior,mapping,{p['company_key'] for p in full_reference['pages']})
    result.update(status='COMPLETE',scope='CORRECTION_FULL484_FIXED585' if scope=='full484' else 'CORRECTION_PILOT_PANEL',
      experiment=experiment_record,panel=spec['panel'],profile=spec['profile'],control_complete=pin(Path(control_path)/'COMPLETE.json'),
      candidate_complete=pin(Path(candidate_path)/'COMPLETE.json'),control_metrics=pin(out/'control_metrics.json'),candidate_metrics=pin(out/'candidate_metrics.json'),
      actual_scorer_invocations=2,writer_readback_verified=True,revision_counts=done[1]['revision_counts'],processed_images=len(numbers),
      new_OCR_calls=0,new_model_calls=0,source_image_decodes=0)
    result['coverage_summary']=frozen.coverage_summary(full_reference,len(numbers),metrics[0])
    result['coverage_summary'].update(parser_processed_images=len(numbers),previously_processed_native_geometry_images=484,
      selected_reference_product_fields=result['product_present_denominator'],selected_reference_all_present_fields=result['safety']['scope_present'],
      selected_absence_fields=result['safety']['absence_scope_separate'],new_model_images=0,
      meaning='Agreement only on selected frozen labels; panel is not all585/full484 accuracy; original full coverage remains separately reported')
    save(out/'RESULT.json',result)
    if read(out/'RESULT.json')!=result:raise ValueError('Actual paired result readback failed')
    return pin(out/'RESULT.json')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('preflight','parse','score'))
    p.add_argument('--experiment',type=Path,required=True);p.add_argument('--experiment-sha256',required=True)
    p.add_argument('--scope',choices=('panel','full484'));p.add_argument('--variant',choices=('control','candidate'))
    p.add_argument('--output',type=Path);p.add_argument('--control',type=Path);p.add_argument('--candidate',type=Path)
    p.add_argument('--pilot-score',type=Path);p.add_argument('--pilot-score-sha256');p.add_argument('--pilot-closed',type=Path);p.add_argument('--pilot-closed-sha256')
    p.add_argument('--execute',action='store_true');p.add_argument('--admission',type=Path);p.add_argument('--admission-sha256');a=p.parse_args()
    record={'path':str(a.experiment.resolve()),'sha256':a.experiment_sha256}
    if not a.execute or a.action=='preflight':
        spec,profile,sources,panel,native,control=preflight(record);print({'valid':True,'executed':False,'panel_pages':len(panel),'reference_access':False});return
    verify_admission(a.admission,a.admission_sha256,__file__,'endpoint-eval')
    if a.action=='parse':
        result=parse(record,a.scope,a.variant,a.output,
          {'path':str(a.pilot_score.resolve()),'sha256':a.pilot_score_sha256} if a.pilot_score else None,
          {'path':str(a.pilot_closed.resolve()),'sha256':a.pilot_closed_sha256} if a.pilot_closed else None)
    else:result=score(record,a.scope,a.control,a.candidate,a.output)
    print(result)

if __name__=='__main__':main()
