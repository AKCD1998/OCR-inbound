"""Model-free source/cell/evaluation boundaries. No source image is opened."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]/'experiments/document_ai'
sys.path.insert(0,str(HERE))
import component_common as common
import eval_assets as assets
import eval_geometry as geometry
import eval_runner as runner
import eval_merge as merge
import eval_native as native_proof
import eval_plan as planner
from eval_transport import ReadTransport

def synthetic():
    cache={'page_number':2,'source_sha256':'a'*64,'geometry':{'original_size':[1000,800],
      'upright_size':[1000,800],'orientation_ccw':0},'working_tokens':[],
      'tesseract_working_tokens':[],'targeted_views':[]}
    page={'source_sha256':'a'*64,'coordinate_space':'upright_image','image_size':[1000,800],
      'page_number':2,'document':{'document_type':'invoice_or_delivery'},'product_rows':[]}
    def token(text,tid,box,secondary=False):
        value={'text':text,'token_id':tid,'box':box,'confidence':.99,'engine':'TESSERACT_THA_ENG' if secondary else 'PADDLE_TH'}
        if secondary:value.update(original_source_bbox=box,recognition_transform={'source_engine':'TESSERACT_THA_ENG','coordinate_space':'upright_image'})
        return value
    for text,tid,box in [('Description','primary:h0',[40,120,400,140]),('QTY','primary:h1',[530,120,600,140]),
                         ('UOM','primary:h2',[680,120,750,140]),('Amount','primary:h3',[830,120,950,140])]:
        cache['working_tokens'].append(token(text,tid,box))
    for i,y in enumerate((220,320),1):
        d=token('Synthetic product '+str(i),f'primary:d{i}',[40,y,380,y+20])
        cache['working_tokens'] += [d,token(str(i*10),f'primary:q{i}',[530,y,570,y+20]),token('BOX',f'primary:u{i}',[690,y,750,y+20])]
        cache['tesseract_working_tokens'] += [token(str(i*10),f'tesseract:q{i}',[532,y+1,572,y+19],True),token('Box',f'tesseract:u{i}',[692,y+1,752,y+19],True)]
        page['product_rows'].append({'row_number':i,'fields':{'description':{'raw_value':d['text'],'normalized_value':d['text'],'bbox':d['box'],'token_ids':[d['token_id']]},
          'quantity':None,'unit':None},'source_row_role':'goods_detail','relationships':[],'counted_in_receiving':None})
    cells=[]
    for row,(top,bottom) in enumerate([(105,160),(205,255),(305,355)]):
        for col,(left,right) in enumerate([(30,460),(510,620),(670,770),(810,970)]):
            cells.append({'id':f'c{row}-{col}','table_id':'table1','bbox':[left,top,right,bottom],
              'coordinate_frame':'original_image','start_row_offset_idx':row,'end_row_offset_idx':row+1,
              'start_col_offset_idx':col,'end_col_offset_idx':col+1,'row_span':1,'col_span':1,
              'raw_text':'NATIVE GENERATED TEXT IS NEVER AN ANSWER'})
    observation={'contract':'document-ai-original-frame-geometry.v1','component':'docling','page':2,
      'source_image':{'path':'unused-image','sha256':'a'*64},'source_size':[1000,800],'source_frame':'original_image',
      'regions':[{'id':'table1','label':'table','bbox':[20,100,980,700]}],'cell_association':{'cells':cells},
      'new_text_OCR_calls':0,'assistant_image_transcription':False}
    return page,cache,observation

class GeometryBoundaries(unittest.TestCase):
    def test_exact_source_topology_and_input_conservation(self):
        _,cache,obs=synthetic();before=copy.deepcopy(obs)
        tables,cells=geometry.normalize(obs,cache)
        self.assertEqual(12,len(cells));self.assertEqual([20,100,980,700],tables['table1']['bbox'])
        self.assertEqual([30,105,460,160],cells[0]['original_bbox']);self.assertEqual(before,obs)

    def test_wrong_source_page_frame_and_assisted_observation_rejected(self):
        for edit in [{'source_frame':'upright_image'},{'page':3},{'source_size':[800,1000]},
                     {'assistant_image_transcription':True},{'new_text_OCR_calls':1},
                     {'source_image':{'sha256':'b'*64}}]:
            _,cache,obs=synthetic();obs.update(edit)
            with self.subTest(edit=edit):
                with self.assertRaises(ValueError):geometry.normalize(obs,cache)

    def test_bad_or_merged_cells_are_never_clipped_or_split(self):
        _,cache,obs=synthetic()
        obs['cell_association']['cells'][0]['bbox']=[-1,105,460,160]
        obs['cell_association']['cells'][1]['col_span']=2
        obs['cell_association']['cells'][2]['start_row_offset_idx']=True
        _,cells=geometry.normalize(obs,cache)
        self.assertEqual(9,len(cells))

    def test_duplicate_native_row_column_ownership_is_rejected(self):
        _,cache,obs=synthetic();obs['cell_association']['cells'].append(copy.deepcopy(obs['cell_association']['cells'][0]))
        with self.assertRaises(ValueError):geometry.normalize(obs,cache)

    def test_duplicate_cell_id_cannot_join_different_native_rows(self):
        _,cache,obs=synthetic();obs['cell_association']['cells'][4]['id']=obs['cell_association']['cells'][0]['id']
        with self.assertRaises(ValueError):geometry.normalize(obs,cache)

    def test_native_boxes_rotate_once_from_explicit_original_frame(self):
        _,cache,obs=synthetic();cache['geometry']['orientation_ccw']=90
        _,cells=geometry.normalize(obs,cache)
        self.assertEqual([105,540,160,970],cells[0]['bbox'])
        self.assertEqual([30,105,460,160],cells[0]['original_bbox'])

    def test_region_only_never_fills_fields_or_claims_endpoint_gain(self):
        page,cache,obs=synthetic();obs['cell_association']['cells']=[]
        result=geometry.apply(page,cache,obs,{'rules':None,'core':None,'owners':None},{'sha256':'c'*64})
        self.assertEqual(page['product_rows'],result['product_rows'])
        self.assertEqual('NO_USABLE_NATIVE_CELL_TOPOLOGY',result['document_ai_geometry_association']['status'])

    def test_PP_without_native_table_region_does_not_run_generic_global_fill(self):
        page,cache,obs=synthetic();obs['component']='pp-layout';obs['regions']=[];obs['cell_association']['cells']=[]
        result=geometry.apply(page,cache,obs,{'rules':None,'core':None,'owners':None},{'sha256':'c'*64})
        self.assertEqual(page['product_rows'],result['product_rows'])
        self.assertEqual('PP_REGION_SOURCE_HEADER_ROW',result['document_ai_geometry_association']['route'])
        self.assertEqual(0,result['document_ai_geometry_association']['native_cells_used'])

    def test_unique_whole_detection_overlap_rejects_competing_owner(self):
        rules=SimpleNamespace(_intersection=lambda a,b:[max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])] if max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3]) else None,
                              _area=lambda b:(b[2]-b[0])*(b[3]-b[1]))
        token={'token_id':'t','bbox':[0,0,10,10]};a={'id':'a','bbox':[0,0,10,10]}
        self.assertEqual('a',geometry.assign([token],[a],rules)['t']['id'])
        self.assertEqual({},geometry.assign([token],[a,{'id':'b','bbox':[0,0,9,10]}],rules))

class EvaluationGuards(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def fixture(self,value,name):
        path=self.root/name;common.save(path,value);return common.pin(path)

    def test_output_cannot_reuse_existing_or_escape_isolated_root(self):
        profile={'results_root':str(self.root/'results')}
        with self.assertRaises(ValueError):runner.output_path(profile,self.root/'outside')
        good=runner.output_path(profile,self.root/'results'/'new')
        self.assertTrue(good.is_dir())
        with self.assertRaises(ValueError):runner.output_path(profile,good)

    def test_changed_asset_bytes_fail_before_import(self):
        record=self.fixture({'synthetic':True},'a.json');Path(record['path']).write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):common.checked(record)

    def test_modified_denominators_fail_preflight_before_assets(self):
        with self.assertRaises(ValueError):assets.preflight({'contract':'document-ai-fixed323-evaluation-plan.v1','expected_scope':{'product_present':586}})

    def native(self):
        _,cache,obs=synthetic();obs['component']='pp-layout';obs['cell_association']['cells']=[]
        record=self.fixture(obs,'page.json');cache_pin={'path':'cache','sha256':'c'*64}
        plan=self.fixture({'component':'pp-layout','new_text_OCR_calls':0,'retained_cache_manifest':cache_pin},'plan.json')
        registry=self.fixture({},'registry.json');materialization=self.fixture({},'materialization.json')
        summary={'status':'COMPLETE','contract':'document-ai-component-trial.v1','component':'pp-layout',
          'new_text_OCR_calls':0,'optimizer_updates':0,'plan':plan,'registry':registry,'materialization':materialization,
          'page_results':[record],'pages_completed':1}
        return summary,{'component':'pp-layout','tiny_page':2,'pins':{'cache':cache_pin}}

    def test_tiny_native_does_not_masquerade_as_full484(self):
        summary,profile=self.native();record=self.fixture(summary,'summary.json')
        self.assertEqual({2},set(runner.native_records(record,profile,'tiny')[0]))
        with self.assertRaises(ValueError):runner.native_records(record,profile,'full484')

    def test_identical_cache_bytes_can_be_relocated_without_reading_new_baseline(self):
        summary,profile=self.native();profile['pins']['cache']={**profile['pins']['cache'],'path':'isolated-same-byte-cache'}
        self.assertEqual({2},set(runner.native_records(self.fixture(summary,'relocated-summary.json'),profile,'tiny')[0]))

    def test_native_changed_or_duplicate_page_is_not_admitted(self):
        summary,profile=self.native();summary['page_results']*=2;summary['pages_completed']=2
        record=self.fixture(summary,'summary.json')
        with self.assertRaises(ValueError):runner.native_records(record,profile,'tiny')

    def test_Docling_layout_only_is_readiness_not_table_component_endpoint(self):
        summary,profile=self.native();summary.update(stage='layout',component='docling');profile['component']='docling'
        with self.assertRaises(ValueError):runner.native_records(self.fixture(summary,'layout-only-summary.json'),profile,'tiny')

    def test_split_stage_regions_must_match_actual_upstream_pin(self):
        summary,profile=self.native();record=summary['page_results'][0];obs=common.read(record['path'])
        upstream=copy.deepcopy(obs);upstream['source_size']=[800,1000]
        obs['upstream_layout_observation']=self.fixture(upstream,'upstream.json')
        obs_record=self.fixture(obs,'table-page.json');summary['page_results']=[obs_record]
        with self.assertRaises(ValueError):runner.native_records(self.fixture(summary,'summary.json'),profile,'tiny')

    def test_metadata_only_tiny_receipt_cannot_unlock_full(self):
        profile={'component':'docling'}
        with self.assertRaises(ValueError):runner.tiny_gate(profile,self.fixture({'status':'COMPLETE','executed':False},'tiny.json'))

    def test_real_tiny_receipt_requires_both_scorers_writer_and_same_profile(self):
        profile={'component':'docling'};asset=self.fixture({},'complete.json')
        result={'status':'COMPLETE','scope':'DIAGNOSTIC_TINY_NOT_FULL585','actual_scorer_invocations':2,
          'profile_sha256':geometry.digest(profile),'component':'docling','writer_readback_verified':True,
          **{k:asset for k in ('control_complete','candidate_complete','control_metrics','candidate_metrics')}}
        record=self.fixture(result,'tiny.json');runner.tiny_gate(profile,record)
        with self.assertRaises(ValueError):runner.tiny_gate({'component':'pp-layout'},record)

    def test_coverage_separates_processed_images_and_labelled_field_scope(self):
        ref={'corpus_page_count':484,'pages':[{'page_number':1,'rows_complete':False,'rows':[{'fields':{'quantity':{'state':'present'},'unit':{'state':'unknown'}}}]},
                                           {'page_number':2,'rows_complete':True,'rows':[]}]}
        metric={'coverage':{'kept':'unchanged'},'by_label_scope':{'product_fields':{'present':1}}}
        report=runner.coverage_summary(ref,484,metric)
        self.assertEqual((484,2,1,482,483,1),(report['processed_original_images'],report['images_with_any_frozen_reference'],
          report['images_with_product_present_reference'],report['images_without_any_reference'],report['images_without_product_present_reference'],report['product_present_reference_fields']))
        self.assertIs(report['frozen_scorer_coverage'],metric['coverage'])

    def test_tiny_full_gate_binds_actual_model_data_not_only_profile(self):
        profile={'component':'docling'};asset=self.fixture({},'metrics.json')
        old={'component':'docling','stage':'tables','registry':{'sha256':'a'*64},'materialization':{'sha256':'b'*64},
          'worker':{'path':'synthetic-worker','sha256':'d'*64},
          'native_table_options':{'do_matching':False,'evaluation_predictions_supplied':False,'cpu_backend':'aten','mkldnn_enabled':False}}
        native_pin=self.fixture(old,'native.json');run=self.fixture({'native_summary':native_pin},'run.json')
        complete=self.fixture({'run_manifest':run},'complete.json')
        result={'status':'COMPLETE','scope':'DIAGNOSTIC_TINY_NOT_FULL585','actual_scorer_invocations':2,
          'profile_sha256':geometry.digest(profile),'component':'docling','writer_readback_verified':True,
          'control_complete':complete,'candidate_complete':complete,'control_metrics':asset,'candidate_metrics':asset}
        receipt=self.fixture(result,'tiny-receipt.json')
        runner.tiny_gate(profile,receipt,native_identity=native_proof.model_identity(old))
        changed={**old,'materialization':{'sha256':'c'*64}}
        with self.assertRaises(ValueError):runner.tiny_gate(profile,receipt,native_identity=native_proof.model_identity(changed))
        changed={**old,'native_table_options':{**old['native_table_options'],'do_matching':True}}
        with self.assertRaises(ValueError):runner.tiny_gate(profile,receipt,native_identity=native_proof.model_identity(changed))
        changed={**old,'worker':{'path':'same-bytes-relocated','sha256':'e'*64}}
        with self.assertRaises(ValueError):runner.tiny_gate(profile,receipt,native_identity=native_proof.model_identity(changed))
        changed={**old,'native_table_options':{**old['native_table_options'],'cpu_backend':'mkldnn','mkldnn_enabled':True}}
        with self.assertRaises(ValueError):runner.tiny_gate(profile,receipt,native_identity=native_proof.model_identity(changed))


class FrozenHelperSyntheticIntegration(unittest.TestCase):
    def test_actual_frozen_parser_scorer_and_writers_on_synthetic_only_fixture(self):
        root=Path(os.environ.get('OCR_INBOUND_PRIVATE_EVIDENCE_ROOT',Path(__file__).resolve().parents[2]/'OCR-inbound-main/outputs'))
        if not (root/'quantity_unit_164_20261024/FINAL_164_PIPELINE_FREEZE.json').is_file():self.skipTest('Private frozen helper closure not distributed')
        script="""
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
from test_document_ai_eval import synthetic
from eval_assets import build,preflight,runtime
from component_common import save,pin,read
import eval_runner as runner
real=build(Path(sys.argv[3]),Path(sys.argv[3])/'unused-unit-root','pp-layout');preflight(real);helpers=runtime(real)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    def artifact(value,name):
        path=root/name;save(path,value);return pin(path)
    page,cache,obs=synthetic();page.update(coordinate_space='original_image',source_file='synthetic-2.png',table={},
      recognition_run={'machine_only':True,'assistant_overlays':False,'vision_llm_calls':0})
    cache['geometry'].update(machine_only=True,vision_LLM_calls=0)
    cache['inference_inputs']={'reference':False,'human_answers':False,'Ada':False,'StockDay':False,'assistant_image_reads':0}
    obs['component']='pp-layout';obs['cell_association']['cells']=[]
    cached=artifact(cache,'cache-page.json');manifest=artifact({'pages':[{'page_number':2,**cached}]},'cache-manifest.json')
    parent=artifact({'pages':[page]},'parent.json');observation=artifact(obs,'observation.json')
    registry=artifact({},'registry.json');models=artifact({},'models.json')
    # These are synthetic parser inputs, not a fabricated actual model receipt.
    native=artifact({'synthetic_unit_fixture':True,'component':'pp-layout','registry':registry,'materialization':models,
      'pages_completed':1,'actual_model_predict_calls_started':0,'actual_completed_layout_model_calls':0,'actual_completed_table_model_calls':0},'synthetic-input.json')
    sources=[{'file':'synthetic-'+str(i)+'.png','sha256':('a'*64 if i==2 else format(i,'064x'))} for i in range(1,485)]
    mapping={'records':[{'page_number':i,'source_sha256':sources[i-1]['sha256'],'issuer_key':'group-'+str(i%38)} for i in range(1,125)],
      'inference_input_allowed':False,'issuer_groups':['group-'+str(i) for i in range(38)]}
    rows=[]
    for i,y in enumerate((220,320),1):
        rows.append({'id':'synthetic-'+str(i),'bbox':[40,y,750,y+20],'fields':{
          'quantity':{'state':'present','tier':'silver','expected_raw':str(i*10),'expected_normalized':str(i*10),'bbox':[530,y,570,y+20]},
          'unit':{'state':'present','tier':'silver','expected_raw':'BOX','expected_normalized':'BOX','bbox':[690,y,750,y+20]}}})
    reference={'contract':'image-source-recognition-reference.v4','corpus_page_count':484,'gold_fields':0,
      'pages':[{'page_number':2,'source_sha256':'a'*64,'image_size':[1000,800],'company_key':'synthetic',
                'rows':rows,'rows_complete':True,'expected_row_count':2,'header_fields':{},'table_headers':[]}]}
    profile={**real,'component':'pp-layout','tiny_page':2,'results_root':str(root/'results'),'synthetic_unit_fixture_ineligible_for_production':True,
      'pins':{**real['pins'],'cache':manifest,'parent_predictions':parent,'reference':artifact(reference,'synthetic-reference.json'),
              'mapping':artifact(mapping,'synthetic-groups.json'),'sources':artifact({'files':sources},'synthetic-sources.json')}}
    profile_pin=artifact(profile,'unit-profile.json')
    # Only test dependency injection bypasses production-native admission and
    # the real benchmark profile pins. No CLI escape hatch exists or is added.
    runner.preflight=lambda value:None
    runner.runtime=lambda value:helpers
    runner.native_records=lambda *args,**kwargs:({2:observation},read(native['path']))
    control=root/'results/control';candidate=root/'results/candidate'
    runner.parse(profile,profile_pin,native,'control','tiny',control)
    runner.parse(profile,profile_pin,native,'candidate','tiny',candidate)
    result_pin=runner.score(profile,control,candidate,'tiny',root/'results/score');result=read(result_pin['path'])
    assert result['actual_scorer_invocations']==2 and result['writer_readback_verified']
    assert result['scope']=='DIAGNOSTIC_TINY_NOT_FULL585' and not result['primary585_claim_allowed']
    before=read(result['control_metrics']['path']);after=read(result['candidate_metrics']['path'])
    assert before['by_label_scope']['product_fields'].get('exact',0)==0,before['by_label_scope']
    assert after['by_label_scope']['product_fields'].get('exact',0)==4,after['by_label_scope']
preflight(real)
assert not any(x.startswith(('paddle','torch','cv2','PIL')) for x in sys.modules)
print(json.dumps({'synthetic_only':True,'actual_frozen_scorer_invocations':2,'writer_readback':True,'images':0,'model_calls':0}))
"""
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,str(HERE),str(Path(__file__).parent),str(root)],
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(0,result.returncode,result.stderr+result.stdout)
        self.assertEqual(2,json.loads(result.stdout)['actual_frozen_scorer_invocations'])

    def test_positive_and_wrong_secondary_using_actual_frozen_helpers_no_images(self):
        root=Path(os.environ.get('OCR_INBOUND_PRIVATE_EVIDENCE_ROOT',Path(__file__).resolve().parents[2]/'OCR-inbound-main/outputs'))
        if not (root/'quantity_unit_164_20261024/FINAL_164_PIPELINE_FREEZE.json').is_file():self.skipTest('Private frozen helper closure not distributed')
        # Fresh process enforces the isolated frozen package; this test never
        # imports a recognizer, opens images, or evaluates real reference labels.
        script="""
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
from test_document_ai_eval import synthetic
from eval_assets import build,preflight,runtime
from eval_geometry import apply
p=build(Path(sys.argv[3]),Path(sys.argv[3])/'unused-synthetic-output','docling');preflight(p);h=runtime(p)
page,cache,obs=synthetic();first=apply(page,cache,obs,h,{'sha256':'d'*64})
assert len(first['document_ai_geometry_association']['changes'])==4,first['document_ai_geometry_association']
assert first['product_rows'][0]['fields']['quantity']['raw_value']=='10'
assert first['product_rows'][0]['fields']['quantity']['bbox']==[530,220,570,240]
assert not first['product_rows'][0]['fields']['quantity']['human_approved']
cache['tesseract_working_tokens'][0]['text']='999'
second=apply(page,cache,obs,h,{'sha256':'d'*64})
assert second['product_rows'][0]['fields']['quantity'] is None
assert page['product_rows'][0]['fields']['quantity'] is None
page,cache,obs=synthetic();page['product_rows'][0]['fields']['quantity']={'raw_value':'999','normalized_value':'999','bbox':[530,220,570,240]}
third=apply(page,cache,obs,h,{'sha256':'d'*64})
assert third['product_rows'][0]['fields']['quantity']==page['product_rows'][0]['fields']['quantity']
page,cache,obs=synthetic();obs['component']='pp-layout';obs['cell_association']['cells']=[]
pp=apply(page,cache,obs,h,{'sha256':'d'*64})
assert len(pp['document_ai_geometry_association']['changes'])==4,pp['document_ai_geometry_association']
assert pp['document_ai_geometry_association']['native_cells_used']==0
assert pp['product_rows'][0]['fields']['quantity']['association_basis']=='PP_REGION_SOURCE_HEADER_ROW'
assert pp['product_rows'][0]['fields']['quantity']['bbox']==[530,220,570,240]
assert not pp['product_rows'][0]['fields']['quantity']['model_geometry_evidence']['physical_cell_border']
obs['regions'][0]['bbox']=[0,0,100,80]
outside=apply(page,cache,obs,h,{'sha256':'d'*64});assert not outside['document_ai_geometry_association']['changes']
page,cache,obs=synthetic();obs['component']='pp-layout';obs['cell_association']['cells']=[]
obs['regions'].append({**obs['regions'][0],'id':'ambiguous-overlapping-table'})
ambiguous=apply(page,cache,obs,h,{'sha256':'d'*64});assert not ambiguous['document_ai_geometry_association']['changes']
page,cache,obs=synthetic();obs['component']='pp-layout';obs['cell_association']['cells']=[]
page['product_rows'][0]['fields']['amount']={'raw_value':'10','normalized_value':'10','bbox':[530,220,570,240],'token_ids':['primary:q1']}
foreign=apply(page,cache,obs,h,{'sha256':'d'*64});assert foreign['product_rows'][0]['fields']['quantity'] is None
assert foreign['product_rows'][0]['fields']['unit']['raw_value']=='BOX'
page,cache,obs=synthetic();obs['component']='pp-layout';obs['cell_association']['cells']=[]
cache['working_tokens'][5]['confidence']=.949
low=apply(page,cache,obs,h,{'sha256':'d'*64});assert low['product_rows'][0]['fields']['quantity'] is None
assert not any(x.startswith(('paddle','torch','cv2','PIL')) for x in sys.modules)
print(json.dumps({'synthetic_fills':4,'PP_region_fills':4,'PP_outside_ambiguous_foreign_rejected':True,'wrong_secondary_rejected':True,'model_imports':0,'image_reads':0}))
"""
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,str(HERE),str(Path(__file__).parent),str(root)],
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(0,result.returncode,result.stderr+result.stdout)
        self.assertEqual(4,json.loads(result.stdout)['synthetic_fills'])


class NativeShardUnion(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.plan=self.write({'tasks':[{'page':n,'source_image':{'path':'unused-'+str(n),'sha256':str(n).zfill(64)},'source_size':[100,200]} for n in range(1,485)]},'plan.json')
        self.registry=self.write({},'registry.json');self.materialization=self.write({'models':'same-pinned-test-data'},'models.json')
        pages=[]
        for task in common.read(self.plan['path'])['tasks']:
            pages.append(self.write({'contract':'document-ai-original-frame-geometry.v1','component':'pp-layout','page':task['page'],
              'source_image':task['source_image'],'source_size':task['source_size'],'source_frame':'original_image',
              'new_text_OCR_calls':0,'assistant_image_transcription':False},f'p{task["page"]}.json'))
        self.shards=[]
        for i,start in enumerate(range(0,484,64)):
            selected=pages[start:start+64];numbers=list(range(start+1,start+len(selected)+1))
            self.shards.append(self.write({'contract':'document-ai-component-trial.v1','component':'pp-layout','status':'COMPLETE',
              'plan':self.plan,'registry':self.registry,'materialization':self.materialization,'page_results':selected,
              'pages_completed':len(selected),'full_source_inventory_pages':484,'selected_pages':numbers,'complete_full_inventory':False,
              'new_text_OCR_calls':0,'optimizer_updates':0,'actual_model_predict_calls_started':len(selected),
              'actual_completed_layout_model_calls':len(selected),'actual_completed_table_model_calls':0,'elapsed_seconds':1.0},f's{i}.json'))
        self.supervision=self.witness(self.shards,'supervision.json')
    def tearDown(self):self.temp.cleanup()
    def write(self,value,name):
        path=self.root/name;common.save(path,value);return common.pin(path)
    def witness(self,shards,name):return self.write({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,'resources':[{
      'worker_summary':r,'actual_exit_code':0,'failure':None,'stop_reason':None,
      'cleanup':{'confirmed_all_known_owned_exited':True},'logs_finalized_after_owned_cleanup':True,
      'peak_owned_process_tree_RSS_bytes':1000000,'minimum_free_RAM_bytes':4000000000} for r in shards]},name)
    def test_eight_exact_shards_produce_full_union_but_no_endpoint_accuracy(self):
        result=merge.aggregate(self.shards,[self.supervision])
        self.assertTrue(result['complete_full_inventory']);self.assertEqual(484,result['pages_completed'])
        self.assertEqual(484,result['actual_completed_layout_model_calls']);self.assertIsNone(result['endpoint_gain'])
        self.assertEqual('NOT_EVALUATED',result['endpoint_score_status'])
    def test_missing_and_duplicate_shards_never_become_full(self):
        with self.assertRaises(ValueError):merge.aggregate(self.shards[:-1],[self.supervision])
        duplicated=[*self.shards[:-1],self.shards[0]]
        with self.assertRaises(ValueError):merge.aggregate(duplicated,[self.supervision])
    def test_unwitnessed_or_wrong_model_identity_is_rejected(self):
        altered=common.read(self.shards[0]['path']);altered['materialization']=self.registry
        changed=[self.write(altered,'changed.json'),*self.shards[1:]]
        with self.assertRaises(ValueError):merge.aggregate(changed,[self.supervision])
        with self.assertRaises(ValueError):merge.aggregate(changed,[self.witness(changed,'changed-witness.json')])

if __name__=='__main__':unittest.main()
