"""Synthetic metadata only: split-stage, shard, transport and real-plan gates."""
from __future__ import annotations
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path,PureWindowsPath
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import component_common as c
import eval_geometry as geometry
import eval_native as n
import eval_merge as merge
import eval_runner as runner
import eval_plan as planner
from eval_transport import ReadTransport

def closed(summary):
    return {'worker_summary':summary,'actual_exit_code':0,'failure':None,'stop_reason':None,
      'cleanup':{'confirmed_all_known_owned_exited':True},'logs_finalized_after_owned_cleanup':True,
      'peak_owned_process_tree_RSS_bytes':1000000,'minimum_free_RAM_bytes':4000000000}

class SyntheticMetadata:
    def __init__(self):self.items={};self.count=0
    def put(self,value,name):
        self.count+=1;path=str(PureWindowsPath(r'D:\synthetic-only')/(str(self.count)+'-'+name+'.json'))
        self.items[path]=deepcopy(value);return {'path':path,'sha256':geometry.digest(value)}
    def read(self,path):return deepcopy(self.items[str(path)])
    def check(self,record):
        if not record or geometry.digest(self.items[record['path']])!=record['sha256']:raise ValueError('Synthetic metadata bytes changed')
        return record['path']
    def context(self):
        stack=ExitStack()
        for module in (n,runner,merge):stack.enter_context(patch.object(module,'read',self.read))
        return stack

class SplitStages(unittest.TestCase):
    def setUp(self):
        self.data=SyntheticMetadata();self.cache={'path':'retained-cache','sha256':'c'*64}
        self.registry=self.data.put({},'registry');self.models=self.data.put({'only':'synthetic model metadata'},'models')
        tasks=[{'page':i,'source_image':{'path':'unused-image-'+str(i),'sha256':format(i,'064x')},'source_size':[100,200],'rotation_ccw':0} for i in range(1,485)]
        self.plan=self.data.put({'component':'docling','mode':'full','tasks':tasks,'new_text_OCR_calls':0,
                                 'retained_cache_manifest':self.cache},'plan')
        self.versions={'numpy':'1.26.4','torch':'2.6.0+cpu'}
        self.abi=self.data.put({'status':'PASS','versions':self.versions,'native_cpu_array_sum':6,
          'numpy_tensor_roundtrip':True,'model_calls':0,'source_image_decodes':0},'ABI')
        self.cpu=self.data.put({'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'model_device':'cpu'},'CPU')
        self.worker=self.data.put({'synthetic_worker':'metadata only, never executed'},'worker')
        self.options={'do_matching':False,'evaluation_predictions_supplied':False,'cpu_backend':'aten','mkldnn_enabled':False}
        self.backend=self.data.put({'cpu_backend':'aten','mkldnn_enabled':False,'mkldnn_available':True},'backend')

    def stages(self,start,count):
        tasks=self.data.read(self.plan['path'])['tasks'][start:start+count];selected=[t['page'] for t in tasks];layout=[]
        base={'contract':'document-ai-component-trial.v1','status':'COMPLETE','component':'docling','plan':self.plan,
          'registry':self.registry,'materialization':self.models,'runtime_versions':self.versions,
          'actual_runtime_ABI_proof':self.abi,'actual_native_CPU_binding':self.cpu,'new_text_OCR_calls':0,'optimizer_updates':0,
          'pages_completed':count,'full_source_inventory_pages':484,'selected_pages':selected,'slice_start':start,'slice_count':count,
          'complete_stage_shard':True,'complete_full_inventory':False,'elapsed_seconds':1.0}
        for task in tasks:
            layout.append(self.data.put({'contract':'document-ai-original-frame-geometry.v1','component':'docling','stage':'layout',
              **task,'source_frame':'original_image','regions':[{'id':'t1','label':'table','bbox':[1,1,99,199]}],
              'layout_model_calls':1,'table_model_calls':0,'new_text_OCR_calls':0,'assistant_image_transcription':False},'layout-page'))
        layout_summary=self.data.put({**base,'stage':'layout','page_results':layout,'actual_model_predict_calls_started':count,
          'actual_completed_layout_model_calls':count,'actual_completed_table_model_calls':0},'layout-summary')
        resource=self.data.put(closed(layout_summary),'layout-resource');tables=[]
        for source in layout:
            page=self.data.read(source['path']);page.update(stage='tables',layout_model_calls=0,table_model_calls=1,
              native_table_options=self.options,
              upstream_layout_observation=source,upstream_layout_summary=layout_summary,upstream_layout_resource=resource)
            tables.append(self.data.put(page,'table-page'))
        summary={**base,'stage':'tables','page_results':tables,'upstream_layout_summary':layout_summary,
          'native_table_options':self.options,'worker':self.worker,'actual_native_table_backend':self.backend,
          'actual_model_predict_calls_started':count,'actual_completed_layout_model_calls':0,'actual_completed_table_model_calls':count}
        return self.data.put(summary,'table-summary'),layout_summary,resource

    def profile(self):
        return {'component':'docling','tiny_page':2,'pins':{'cache':self.cache},
          'selected_native_table_options':self.options}

    def test_two_page_table_canary_keeps_exact_layout_slice_and_resource_chain(self):
        record,_,_=self.stages(0,2);profile=self.profile()
        with self.data.context():
            records,summary=runner.native_records(record,profile,'tiny',self.data.check)
            self.assertEqual({1,2},set(records))
            totals=n.native_totals(summary,check=self.data.check)
            self.assertEqual(2,totals['unique_original_sources'])
            self.assertEqual(4,totals['all_native_stages_without_double_counting']['actual_model_predict_calls_started'])

    def test_layout_table_different_plan_runtime_or_unclosed_resource_rejected(self):
        record,_,_=self.stages(0,2);original=self.data.read(record['path'])
        observations={self.data.read(p['path'])['page']:self.data.read(p['path']) for p in original['page_results']}
        with self.data.context():
            bad=deepcopy(original);bad['plan']=self.registry
            with self.assertRaises(ValueError):n.table_upstream(bad,observations,self.data.check)
            bad=deepcopy(original);bad['runtime_versions']={**self.versions,'torch':'2.7.0+cpu'}
            with self.assertRaises(ValueError):n.table_upstream(bad,observations,self.data.check)
            bad_observations=deepcopy(observations)
            bad_resource=self.data.put({**closed(bad_observations[1]['upstream_layout_summary']),'cleanup':{'confirmed_all_known_owned_exited':False}},'unclosed')
            for page in bad_observations.values():page['upstream_layout_resource']=bad_resource
            with self.assertRaises(ValueError):n.table_upstream(original,bad_observations,self.data.check)

    def test_eight_table_shards_have_full484_union_and_no_call_double_counting(self):
        shards=[self.stages(start,min(64,484-start))[0] for start in range(0,484,64)]
        supervision=self.data.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,
          'resources':[closed(p) for p in shards]},'supervision')
        with self.data.context():
            result=merge.aggregate(shards,[supervision],check=self.data.check)
            self.assertTrue(result['complete_full_inventory']);self.assertEqual(484,result['pages_completed'])
            self.assertEqual(self.versions,result['runtime_versions']);self.assertEqual(8,len(result['native_runtime_proofs']))
            totals=n.native_totals(result,check=self.data.check)
            self.assertEqual(8,len(totals['unique_upstream_layout_summaries']))
            self.assertEqual((484,484,968),(totals['unique_original_sources'],result['actual_completed_table_model_calls'],
              totals['all_native_stages_without_double_counting']['actual_model_predict_calls_started']))
            record=self.data.put(result,'full-aggregate')
            pages,_=runner.native_records(record,self.profile(),'full484',self.data.check)
            self.assertEqual(set(range(1,485)),set(pages))

    def test_sixteen_and_thirtytwo_partitions_keep_same484_identity_and_counters(self):
        for count in (16,32):
            with self.subTest(partitions=count):
                width,remainder=divmod(484,count);start=0;shards=[]
                for i in range(count):
                    size=width+(i<remainder);shards.append(self.stages(start,size)[0]);start+=size
                supervision=self.data.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,
                  'resources':[closed(p) for p in shards]},'supervision-partitions')
                with self.data.context():
                    result=merge.aggregate(shards,[supervision],check=self.data.check)
                    self.assertEqual(count,result['native_shards']);self.assertEqual(484,result['pages_completed'])
                    totals=n.native_totals(result,check=self.data.check)
                    self.assertEqual(968,totals['all_native_stages_without_double_counting']['actual_model_predict_calls_started'])
                    record=self.data.put(result,'aggregate-partitions')
                    pages,_=runner.native_records(record,self.profile(),'full484',self.data.check)
                    self.assertEqual(set(range(1,485)),set(pages))

    def test_table_options_missing_wrong_types_or_evaluation_predictions_rejected(self):
        record,_,_=self.stages(0,2);summary=self.data.read(record['path'])
        for options in (None,{}, {**self.options,'do_matching':0},
                        {**self.options,'evaluation_predictions_supplied':True},
                        {**self.options,'cpu_backend':'aten','mkldnn_enabled':True}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                n.model_identity({**summary,'native_table_options':options})
        altered={**summary,'native_table_options':{**self.options,'do_matching':True}}
        with self.data.context(),self.assertRaises(ValueError):
            runner.native_records(self.data.put(altered,'enabled-tables'),self.profile(),'tiny',self.data.check)
        self.assertNotEqual(n.model_identity(summary),n.model_identity(altered))

    def test_table_page_options_and_mixed_shard_options_rejected(self):
        record,_,_=self.stages(0,2);summary=self.data.read(record['path'])
        observations={self.data.read(p['path'])['page']:self.data.read(p['path']) for p in summary['page_results']}
        observations[1]['native_table_options']={**self.options,'do_matching':True}
        with self.data.context(),self.assertRaises(ValueError):n.table_upstream(summary,observations,self.data.check)
        shards=[self.stages(start,min(64,484-start))[0] for start in range(0,484,64)]
        changed=self.data.read(shards[1]['path']);changed['native_table_options']={**self.options,'do_matching':True}
        shards[1]=self.data.put(changed,'mixed-option-shard')
        supervision=self.data.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,
          'resources':[closed(p) for p in shards]},'mixed-option-supervision')
        with self.data.context(),self.assertRaises(ValueError):merge.aggregate(shards,[supervision],check=self.data.check)

    def test_actual_backend_proof_must_match_options_and_worker_bytes(self):
        record,_,_=self.stages(0,2);summary=self.data.read(record['path'])
        wrong_backend=self.data.put({'cpu_backend':'mkldnn','mkldnn_enabled':True,'mkldnn_available':True},'wrong-backend')
        with self.data.context(),self.assertRaises(ValueError):n.runtime_proof({**summary,'actual_native_table_backend':wrong_backend},self.data.check)
        with self.data.context(),self.assertRaises(ValueError):n.runtime_proof({**summary,'worker':{**self.worker,'sha256':'f'*64}},self.data.check)

    def test_full_shards_must_keep_same_table_worker_and_backend(self):
        for change in ('worker','backend'):
            with self.subTest(change=change):
                shards=[self.stages(start,min(64,484-start))[0] for start in range(0,484,64)]
                altered=self.data.read(shards[1]['path'])
                if change=='worker':altered['worker']=self.data.put({'synthetic_worker':'different source'},'different-worker')
                else:altered['native_table_options']={**self.options,'cpu_backend':'mkldnn','mkldnn_enabled':True}
                shards[1]=self.data.put(altered,'altered-identity')
                supervision=self.data.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,
                  'resources':[closed(p) for p in shards]},'altered-identity-supervision')
                with self.data.context(),self.assertRaises(ValueError):merge.aggregate(shards,[supervision],check=self.data.check)

    def test_partition_missing_duplicate_empty_or_oversized_never_claim_full484(self):
        valid=[self.stages(start,min(32,484-start))[0] for start in range(0,484,32)]
        too_large=self.stages(0,65)[0]
        empty=self.stages(0,0)[0]
        cases=[valid[:-1],[*valid[:-1],valid[0]],[empty,*valid],[too_large,*valid]]
        for shards in cases:
            with self.subTest(partitions=len(shards)):
                supervision=self.data.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,
                  'resources':[closed(p) for p in shards]},'bad-partitions-supervision')
                with self.data.context(),self.assertRaises(ValueError):
                    merge.aggregate(shards,[supervision],check=self.data.check)

class ClientPlanTransport(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.native=PureWindowsPath(r'D:\endpoint-unit')
    def tearDown(self):self.temp.cleanup()
    def put(self,value,name):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);c.save(path,value)
        return {'path':str(self.native/name),'sha256':c.sha(path)}
    def fixture(self):
        worker=self.root/'code/eval_runner.py';worker.parent.mkdir();worker.write_text('# synthetic worker; never executed\n',encoding='utf-8')
        worker_pin={'path':str(self.native/'code/eval_runner.py'),'sha256':c.sha(worker)}
        registry=self.put({},'registry.json');models=self.put({},'models.json');cache={'sha256':'c'*64,'path':'same-retained-cache'}
        plan=self.put({'component':'pp-layout','new_text_OCR_calls':0,'retained_cache_manifest':cache},'plan.json')
        page=self.put({'page':2,'component':'pp-layout'},'native-page.json')
        summary=self.put({'contract':'document-ai-component-trial.v1','status':'COMPLETE','component':'pp-layout',
          'new_text_OCR_calls':0,'optimizer_updates':0,'plan':plan,'registry':registry,'materialization':models,
          'page_results':[page],'pages_completed':1},'native-summary.json')
        supervision=self.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,'resources':[closed(summary)]},'supervision.json')
        profile=self.put({'component':'pp-layout','tiny_page':2,'pins':{'cache':cache},'results_root':str(self.native/'runs'),
          'bridge_sources':[worker_pin]},'profile.json')
        return profile,summary,supervision,worker_pin
    def test_read_transport_is_explicit_and_does_not_change_logical_pins(self):
        profile,_,_,_=self.fixture();transport=ReadTransport([(str(self.native),self.root)])
        self.assertEqual(profile,transport.pin(profile['path']))
        with self.assertRaises(ValueError):transport.physical(str(self.native/'..'/'escape'))
    def test_plan_uses_deployed_pinned_worker_and_native_paths_without_HQ_process(self):
        profile,summary,supervision,worker=self.fixture()
        with patch.object(planner,'preflight',return_value={'valid':True}):
            result=planner.build(profile['path'],summary['path'],'tiny','future_canary',supervision_paths=[supervision['path']],
              read_mappings=[(str(self.native),self.root)])
        self.assertEqual(3,len(result['steps']));self.assertFalse(result['executed'])
        self.assertEqual(worker,result['steps'][0]['worker'])
        self.assertIn(profile['path'],result['steps'][0]['args']);self.assertIn(summary['path'],result['steps'][0]['args'])
        self.assertIn(supervision,result['steps'][0]['input_pins'])
        self.assertFalse((self.root/'runs').exists())
    def test_complete_canary_without_closed_native_supervision_is_not_a_plan(self):
        profile,summary,_,_=self.fixture()
        with patch.object(planner,'preflight',return_value={'valid':True}):
            with self.assertRaises(ValueError):planner.build(profile['path'],summary['path'],'tiny','future_canary',
              read_mappings=[(str(self.native),self.root)])

if __name__=='__main__':unittest.main()
