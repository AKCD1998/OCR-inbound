"""Immutable private evaluation plan; no image decoding or reference answers."""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path
import sys
from component_common import checked,pin,read,save

EXPECTED={
 'final164':'5bdadecb71bfde9c1c045314269ec298c1da3463c036335fbbe6ae95f8135f45',
 'reference':'889b868928ed35c89e37ac3e9eaa3b9a0ff068b5cf4166e9fab3ccc083f1f372',
 'scorer':'cd82645409267fc1ed9ec9c1c05017486f154510a376d184abbc66a02e9f0f7f',
 'shared':'6c7a58f5262158d3929bd5b2f7c3fd6cdd943d3f6477c342a818baf2ce51cef0',
 'groups':'0855d55c74ecb2dc5471b139dd99d7ec8ea098e72c5579cff66fedc66ebe064b',
 'cache':'a2531aea9fb92747893c4341c5401cb8373bc377a6305060e7e193d5a247fe6e',
 'parent_predictions':'66237f3d033145a9d867a333461f6e37fff6d15e5dac7fa0088907dabbd6dcb8',
}

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

def build(evidence_root,results_root,component,tiny_page=2,final164_source_root=None):
    if component not in ('pp-layout','pp-layout-l','docling') or type(tiny_page) is not int or not 1<=tiny_page<=484:raise ValueError('Bounded known component/source page required')
    root=Path(evidence_root).resolve();q=root/'quantity_unit_164_20261024';e=q/'evaluation'
    n=root/'ocr_engine_upgrade_20261025';content=n/'C_slanet_integration/content_v2/CONTENT_PARSER_FREEZE_V2.json'
    final=q/'FINAL_164_PIPELINE_FREEZE.json';f=read(final)
    if f.get('selected_product_exact')!=323 or f.get('product_present_denominator')!=585 or f.get('actual_source_file_count')!=48:raise ValueError('Exact FINAL164 scope required')
    paths={'final164':final,'C4_freeze':n/'C_geometry/C_GRID_PARSER_FREEZE_V5.json',
      'cache':q/'baseline_cache/manifest.json','parent_predictions':n/'C_geometry/arms/C_grid_candidate_v4/page_extractions.json',
      'parent_complete':n/'C_geometry/arms/C_grid_candidate_v4/COMPLETE.json',
      'reference':e/'frozen_inputs/reference_frozen_v4.json','scorer':e/'scripts/frozen/recognition_benchmark_v2.py',
      'shared':e/'scripts/evaluate_quantity_unit_v2.py','groups':e/'scripts/frozen/score_pattern_eval_frozen_v1.py',
      'mapping':e/'frozen_inputs/issuer_mapping_38.json','sources':e/'frozen_inputs/source_manifest.json',
      'prior323':e/'PRIOR_EXACT_323_BEFORE_MODEL_LABEL_KEYS.json','cohort164':e/'RESIDUAL_QUANTITY_UNIT_164_COHORT.json',
      'frame_io':n/'C_slanet_integration/slanet_arm_io.py'}
    records={key:pin(path) for key,path in paths.items()}
    for key,expected in EXPECTED.items():
        if records[key]['sha256']!=expected:raise ValueError('Frozen identity changed: '+key)
    frozen=q/'baseline_cache/code/src';sources=[]
    for key,record in f['pins'].items():
        if key.startswith('actual_source:'):
            # FINAL164 live-source seal and retained-cache parser snapshots are
            # distinct historical closures. Do not relabel an older cache file
            # as the later FINAL164 file just because its basename matches.
            path=Path(final164_source_root)/key.split(':',1)[1] if final164_source_root else Path(record['path'])
            r=pin(path)
            if r['sha256']!=record['sha256']:raise ValueError('48-file frozen source differs: '+key)
            sources.append(r)
    if len(sources)!=48:raise ValueError('Exactly48 parser-source assets required')
    # Only pure grammar/ownership/header helpers, never SLANet native admission
    # or its model-specific normalizer. New geometry has its own honest schema.
    historical=read(content);dependencies=historical['dependencies'][:5]
    retained_sources=historical['source_code_files']
    for r in retained_sources:checked(r)
    for r in dependencies:checked(r)
    if [r['module_name'] for r in dependencies]!=['ocr_inbound.literal_uom_grammar','line_grid_refinement_v4','goods_table_router','slanet_structure_adapter','slanet_cell_projection_v2']:raise ValueError('Pure helper order changed')
    files=[pin(Path(__file__).with_name(name)) for name in ['eval_assets.py','eval_geometry.py','eval_runner.py','eval_plan.py','eval_merge.py','eval_native.py','eval_transport.py','component_common.py']]
    return {'contract':'document-ai-fixed323-evaluation-plan.v1','component':component,
      'selected_native_table_options':{'do_matching':False,'evaluation_predictions_supplied':False,'cpu_backend':'aten','mkldnn_enabled':False} if component=='docling' else None,
      'baseline':'retained FINAL164 + saved C4 canonical; never fresh324 or a new OCR read',
      'pins':records,'parser_sources':retained_sources,'final164_source_files':sources,'dependencies':dependencies,'bridge_sources':files,
      'frozen_source_root':str(frozen),'results_root':str(Path(results_root).resolve()),'tiny_page':tiny_page,
      'expected_scope':{'pages':484,'product_present':585,'all_present':602,'critical':329,'supplier_code':57,'absence':18,'prior_exact':323},
      'new_OCR_calls':0,'assistant_image_reads':0,'production_activation':False,'known_development_set':True,
      'gold_labels':0,'full_native_coverage_required':484,'full_requires_actual_tiny_parser_scorer_write_receipt':True}

def preflight(profile,check=checked):
    if profile.get('contract')!='document-ai-fixed323-evaluation-plan.v1' or profile['expected_scope']!={'pages':484,'product_present':585,'all_present':602,'critical':329,'supplier_code':57,'absence':18,'prior_exact':323}:raise ValueError('Frozen evaluation scope required')
    if profile.get('component')=='docling':
        from eval_native import validate_table_options
        if validate_table_options(profile.get('selected_native_table_options'))['do_matching'] is not False:raise ValueError('Selected source-only Docling table options required')
    records=list(profile['pins'].values())+profile['parser_sources']+profile['final164_source_files']+profile['dependencies']+profile['bridge_sources']
    for r in records:check(r)
    for k,v in EXPECTED.items():
        if profile['pins'][k]['sha256']!=v:raise ValueError('Metric/control identity changed')
    manifest=read(check(profile['pins']['cache']))
    if manifest.get('complete') is not True or {p['page_number'] for p in manifest['pages']}!=set(range(1,485)) or len(manifest['pages'])!=484:raise ValueError('Retained484 cache union required')
    return {'valid':True,'assets_checked':len(records),'cache_pages':484,'model_imports':0,'image_decodes':0,'reference_answers_loaded':False,'executed':False}

def runtime(profile):
    sys.path.insert(0,profile['frozen_source_root'])
    import ocr_inbound
    if not Path(ocr_inbound.__file__).resolve().is_relative_to(Path(profile['frozen_source_root']).resolve()):raise ValueError('Live package import refused')
    for r in profile['dependencies']:load(r['module_name'],checked(r))
    from ocr_inbound import cell_extraction,adaptive_recognition,source_overlay_guard,recognition_contract
    io=load('_docai_eval_frame',checked(profile['pins']['frame_io']))
    return {'rules':sys.modules['line_grid_refinement_v4'],'owners':sys.modules['slanet_cell_projection_v2'],
      'core':cell_extraction,'mapper':adaptive_recognition.map_page_geometry,'guard':source_overlay_guard.conserve_source_overlay,
      'finalize':recognition_contract.finalize_result,'io':io}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence-root',type=Path,required=True)
    p.add_argument('--results-root',type=Path,required=True);p.add_argument('--component',choices=['pp-layout','pp-layout-l','docling'],required=True)
    p.add_argument('--tiny-page',type=int,default=2);p.add_argument('--final164-source-root',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    plan=build(a.evidence_root,a.results_root,a.component,a.tiny_page,a.final164_source_root);proof=preflight(plan);save(a.output,plan)
    print({'plan':pin(a.output),'preflight':proof})
