"""Synthetic closed-task/metadata/ownership gates; no model or image access."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import docling_post_eval as post
from component_common import RESOURCES,CONTROLLER_SHA256

def record(name,digest='a'*64):return {'path':name,'sha256':digest}
def resource(stage,summary):
    return {'stage':stage,'worker_summary':summary,'actual_exit_code':0,'failure':None,'stop_reason':None,
      'child_started':True,'worker_optimizer_updates_permission':False,
      'cleanup':{'confirmed_all_known_owned_exited':True},'logs_finalized_after_owned_cleanup':True,
      'peak_owned_process_tree_RSS_bytes':1000000,'minimum_free_RAM_bytes':4000000000}

class PostEvaluationGates(unittest.TestCase):
    def setUp(self):
        self.items={};self.driver=record('post-driver')
        native_read=patch('eval_native.read',side_effect=self.read);native_read.start();self.addCleanup(native_read.stop)
        self.c={'contract':'root-HQ-docling-post-eval.v1','approved_by':'root','driver':self.driver,
          'source':record('serial',post.SERIAL_SHA),'profile':record('profile','b'*64),
          'native_config':record('native-config'),'full_parent_plan':record('full-parent',post.FULL_PARENT_SHA),
          'tiny_score':record('tiny-score'),'closed_tiny':record('tiny-closed'),
          'resource_policy':deepcopy(RESOURCES),'production_activation_allowed':False,
          'pins':{'controller':record('controller',CONTROLLER_SHA256),'ownership':record('ownership',post.OWNERSHIP_SHA),
                  'python':record('python'),'metadata_probe':record('probe')},
          'ordinary_external_processes':[],'maximum_total_seconds':7200,
          'expected_profile_sha256':'b'*64,'expected_table_worker_sha256':'c'*64,'selected_table_options':deepcopy(post.OPTIONS),
          'native_task_name':'OCR_DOCAI_SYNTHETIC_ONLY','native_result_path':'synthetic-native-result'}
        self.now=datetime(2026,10,29,2,0,tzinfo=timezone.utc)

    def check(self,pin):return pin['path']
    def read(self,path):return deepcopy(self.items[str(path)])

    def test_static_config_keeps_frozen_profile_resources_deadline_and_source(self):
        self.assertIs(self.c,post.validate_config(self.c,self.driver,self.check))
        for edit in ({'maximum_total_seconds':7201},{'resource_policy':{}},{'production_activation_allowed':True},
                     {'profile':record('other','d'*64)},{'source':record('other','b'*64)},
                     {'expected_table_worker_sha256':'not-a-frozen-hash'},
                     {'selected_table_options':{**post.OPTIONS,'mkldnn_enabled':True}}):
            with self.subTest(edit=edit),self.assertRaises(ValueError):post.validate_config({**self.c,**edit},self.driver,self.check)

    def test_root_can_pin_new_accepted_worker_and_profile_without_weakening_metric_sources(self):
        selected={**self.c,'profile':record('new-selected-profile','d'*64),'expected_profile_sha256':'d'*64,
                  'expected_table_worker_sha256':'e'*64}
        self.assertIs(selected,post.validate_config(selected,self.driver,self.check))
        with self.assertRaises(ValueError):post.validate_config({**selected,'full_parent_plan':record('other-parent','f'*64)},self.driver,self.check)

    def completion(self):
        return {'contract':'document-ai-native-task-ready.v1','task_name':self.c['native_task_name'],
          'native_config':self.c['native_config'],'state':3,'last_task_result':0,'running_instances':0,
          'observed_at_utc':self.now.isoformat(),'native_result':record(self.c['native_result_path'])}

    def test_actual_task_ready_result_zero_and_recent_source_bound_observation_required(self):
        ready=self.completion();self.assertEqual(ready['native_result'],post.completion_ready(self.c,ready,self.now))
        for edit in ({'state':4},{'last_task_result':1},{'running_instances':1},{'state':True},
                     {'task_name':'OCR_DOCAI_OTHER'},{'native_config':record('wrong-config')},
                     {'native_result':record('another-result')},
                     {'observed_at_utc':(self.now-timedelta(seconds=301)).isoformat()}):
            with self.subTest(edit=edit),self.assertRaises(ValueError):post.completion_ready(self.c,{**ready,**edit},self.now)

    def native(self,retained=False,retain_table=False):
        native_driver=record('native-driver');config={'docling_full_driver':native_driver,
          'full_parent_plan':self.c['full_parent_plan'],'shard_size':64}
        resources=[];pages=list(range(1,485))
        for i,start in enumerate(range(0,484,64)):
            selected=pages[start:start+64]
            for stage in ('layout','tables'):
                name=stage+'_'+str(i).zfill(3);pin=record(name)
                self.items[name]={'status':'COMPLETE','component':'docling','stage':stage,
                  'plan':self.c['full_parent_plan'],'selected_pages':selected,'pages_completed':len(selected),
                  'complete_stage_shard':True,'new_text_OCR_calls':0,'optimizer_updates':0,
                  'worker':record('accepted-native-worker',self.c['expected_table_worker_sha256']),
                  'registry':record('registry'),'materialization':record('models'),
                  'native_table_options':deepcopy(post.OPTIONS) if stage=='tables' else None}
                resources.append(resource(name,pin))
        result={'contract':'document-ai-HQ-serial-result.v1','status':'COMPLETE','failure':None,
          'config':self.c['native_config'],'driver':native_driver,'cleanup':{'confirmed_all_known_owned_exited':True},
          'shared_lock_acquired':True,'shared_lock_released_after_owned_closure':True,'complete_full_inventory':True,
          'full_parent_plan':self.c['full_parent_plan'],'new_text_OCR_calls':0,'optimizer_updates':0,
          'actual_layout_pages':pages,'actual_table_stage_pages':pages,'resources':resources,
          'fresh_layout_pages':pages,'retained_layout_pages':[],
          'fresh_table_pages':pages,'retained_table_pages':[]}
        if retained:
            versions={'numpy':'2.2.6','torch':'2.6.0+cpu'}
            self.items['ABI']={'status':'PASS','versions':versions,'native_cpu_array_sum':6,'numpy_tensor_roundtrip':True,'model_calls':0,'source_image_decodes':0}
            self.items['CPU']={'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'model_device':'cpu'}
            self.items['full-parent']={'tasks':[{'page':n,'source_image':record('unused-source-'+str(n)),
              'source_size':[100,200],'rotation_ccw':0} for n in pages]}
            layout_pages=[]
            for task in self.items['full-parent']['tasks'][:64]:
                name='retained-page-'+str(task['page']);layout_pages.append(record(name))
                self.items[name]={'contract':'document-ai-original-frame-geometry.v1',**task,
                  'component':'docling','stage':'layout','regions':[],
                  'source_frame':'original_image','layout_model_calls':1,'new_text_OCR_calls':0,'assistant_image_transcription':False}
            origin=deepcopy(self.items['layout_000']);origin.update(worker=record('older-closed-layout-worker','e'*64),
              full_source_inventory_pages=484,actual_completed_layout_model_calls=64,page_results=layout_pages,
              runtime_versions=versions,actual_runtime_ABI_proof=record('ABI'),actual_native_CPU_binding=record('CPU'))
            self.items['origin-layout']=origin
            original_resource=resource('layout_000',record('origin-layout'));self.items['origin-resource']=deepcopy(original_resource)
            self.items['failed-source-root']={'status':'FAILED','failure':{'message':'later table child failed'},
              'cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True,
              'resources':[deepcopy(original_resource)]}
            for name,summary in self.items.items():
                if name.startswith(('layout_','tables_')):summary['runtime_versions']=versions
            entry={'slice_start':0,'slice_count':64,'summary':record('origin-layout'),'resource':record('origin-resource'),
                   'closed_source_supervision':record('failed-source-root')}
            config['retained_layout_shards']=[entry]
            result['resources']=result['resources'][1:];result['fresh_layout_pages']=pages[64:];result['retained_layout_pages']=pages[:64]
            proof_path=str(Path(self.c['native_result_path']).resolve().parent/'layout_000.RETAINED.json')
            self.items[proof_path]={'origin_summary':entry['summary'],'origin_resource':entry['resource'],
              'origin_closed_supervision':entry['closed_source_supervision'],'origin_worker':origin['worker'],
              'selected_pages':pages[:64],'new_model_calls':0,'source_prediction_identity_relabelled':False}
            if retain_table:
                self.items['BACKEND']={'cpu_backend':'aten','mkldnn_enabled':False,'mkldnn_available':True}
                table_pages=[]
                for original in layout_pages:
                    page=deepcopy(self.items[original['path']]);name='retained-table-page-'+str(page['page'])
                    page.update(stage='tables',layout_model_calls=0,table_model_calls=1,native_table_options=deepcopy(post.OPTIONS),
                      upstream_layout_observation=original,upstream_layout_summary=record('origin-layout'),
                      upstream_layout_resource=record('origin-resource'))
                    self.items[name]=page;table_pages.append(record(name))
                table=deepcopy(self.items['tables_000']);table.update(worker=record('older-closed-table-worker',self.c['expected_table_worker_sha256']),
                  full_source_inventory_pages=484,page_results=table_pages,
                  actual_runtime_ABI_proof=record('ABI'),actual_native_CPU_binding=record('CPU'),actual_native_table_backend=record('BACKEND'),
                  actual_completed_layout_model_calls=0,actual_completed_table_model_calls=64,actual_model_predict_calls_started=64)
                self.items['origin-table']=table
                table_resource=resource('tables_000',record('origin-table'));table_resource['actual_argv']=['original-python','original-worker','--old-source']
                self.items['origin-table-resource']=deepcopy(table_resource)
                self.items['failed-table-source-root']={'status':'FAILED','failure':{'message':'later layout child failed'},
                  'cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True,
                  'resources':[deepcopy(table_resource)]}
                table_entry={'slice_start':0,'slice_count':64,'summary':record('origin-table'),'resource':record('origin-table-resource'),
                  'closed_source_supervision':record('failed-table-source-root')}
                config['retained_table_shards']=[table_entry]
                result['resources']=result['resources'][1:];result['fresh_table_pages']=pages[64:];result['retained_table_pages']=pages[:64]
                proof_path=str(Path(self.c['native_result_path']).resolve().parent/'tables_000.RETAINED.json')
                self.items[proof_path]={'origin_summary':table_entry['summary'],'origin_resource':table_entry['resource'],
                  'origin_closed_supervision':table_entry['closed_source_supervision'],'origin_worker':table['worker'],
                  'selected_pages':pages[:64],'new_model_calls':0,'source_prediction_identity_relabelled':False}
        return result,config

    def test_native_complete_requires_all_sixteen_closed_children_and_returns_eight_tables(self):
        result,config=self.native()
        with patch.object(post,'read',self.read):tables=post.native_tables(self.c,result,config,self.check)
        self.assertEqual(8,len(tables));self.assertEqual('tables_007',tables[-1]['path'])

    def test_fifteen_fresh_children_plus_sixtyfour_retained_source_pages_are_complete(self):
        result,config=self.native(retained=True)
        with patch.object(post,'read',self.read):tables=post.native_tables(self.c,result,config,self.check)
        self.assertEqual(8,len(tables));self.assertEqual(15,len(result['resources']))
        self.assertEqual((420,64),(len(result['fresh_layout_pages']),len(result['retained_layout_pages'])))
        self.assertEqual('FAILED',self.items['failed-source-root']['status'])
        self.assertEqual('e'*64,self.items['origin-layout']['worker']['sha256'])

    def test_retained_origin_and_fresh_inventory_cannot_be_forged_or_double_counted(self):
        for case in ('invented_child','overlap','duplicate_partition','wrong_partition','boolean_page'):
            result,config=self.native(retained=True)
            if case=='invented_child':result['resources'].insert(0,resource('layout_000',record('origin-layout')))
            elif case=='overlap':result['fresh_layout_pages']=list(range(1,485))
            elif case=='duplicate_partition':config['retained_layout_shards']*=2
            elif case=='wrong_partition':config['retained_layout_shards'][0]['slice_start']=1
            else:result['actual_layout_pages'][0]=True
            with self.subTest(case=case),patch.object(post,'read',self.read),self.assertRaises(ValueError):post.native_tables(self.c,result,config,self.check)

    def test_retained_requires_pristine_successful_child_and_closed_original_source(self):
        for case in ('bad_child','unclosed_root','no_witness','wrong_frame','wrong_runtime','relabelled_worker','fresh_call_claim'):
            result,config=self.native(retained=True)
            proof=self.items[str(Path(self.c['native_result_path']).resolve().parent/'layout_000.RETAINED.json')]
            if case=='bad_child':self.items['origin-resource']['failure']={'message':'failed child'}
            elif case=='unclosed_root':self.items['failed-source-root']['cleanup']['confirmed_all_known_owned_exited']=False
            elif case=='no_witness':self.items['failed-source-root']['resources']=[]
            elif case=='wrong_frame':self.items['retained-page-1']['source_size']=[200,100]
            elif case=='wrong_runtime':self.items['origin-layout']['runtime_versions']={'numpy':'different','torch':'different'}
            elif case=='relabelled_worker':proof['origin_worker']=record('new-worker',self.c['expected_table_worker_sha256'])
            else:proof['new_model_calls']=64
            with self.subTest(case=case),patch.object(post,'read',self.read),self.assertRaises(ValueError):post.native_tables(self.c,result,config,self.check)

    def test_fourteen_fresh_children_plus_retained_layout_and_table64(self):
        result,config=self.native(retained=True,retain_table=True)
        with patch.object(post,'read',self.read):tables=post.native_tables(self.c,result,config,self.check)
        self.assertEqual(8,len(tables));self.assertEqual('origin-table',tables[0]['path'])
        self.assertEqual(14,len(result['resources']))
        self.assertEqual((420,64),(len(result['fresh_table_pages']),len(result['retained_table_pages'])))
        self.assertEqual('FAILED',self.items['failed-table-source-root']['status'])
        self.assertEqual('older-closed-table-worker',self.items['origin-table']['worker']['path'])

    def test_retained_table_rejects_failed_changed_or_duplicate_sources(self):
        for case in ('failed_child','wrong_worker','wrong_runtime','wrong_frame','duplicate','overlap','relabelled_worker'):
            result,config=self.native(retained=True,retain_table=True)
            if case=='failed_child':self.items['origin-table-resource']['actual_exit_code']=1
            elif case=='wrong_worker':self.items['origin-table']['worker']=record('wrong-worker','f'*64)
            elif case=='wrong_runtime':self.items['origin-table']['runtime_versions']={'numpy':'different','torch':'different'}
            elif case=='wrong_frame':self.items['retained-table-page-1']['source_size']=[200,100]
            elif case=='duplicate':config['retained_table_shards']*=2
            elif case=='overlap':result['fresh_table_pages']=list(range(1,485))
            else:self.items[str(Path(self.c['native_result_path']).resolve().parent/'tables_000.RETAINED.json')]['origin_worker']=record('relabeled-worker',self.c['expected_table_worker_sha256'])
            with self.subTest(case=case),patch.object(post,'read',self.read),self.assertRaises(ValueError):post.native_tables(self.c,result,config,self.check)

    def test_composed_source_witness_is_verification_only_and_preserves_failed_root_and_argv(self):
        import eval_native
        result,config=self.native(retained=True,retain_table=True);original=deepcopy(result)
        self.items['new-native-root']=deepcopy(result);native_pin=record('new-native-root')
        c={**self.c,'allow_composed_retained_table_source_witness':True}
        with patch.object(post,'read',self.read):
            tables=post.native_tables(c,result,config,self.check)
            witness=post.composed_source_witness(c,native_pin,result,config,tables,self.check,lambda p:record(str(p)))
        self.assertTrue(witness['verification_only']);self.assertEqual('document-ai-composed-closed-source-verification.v1',witness['contract'])
        self.assertEqual((14,1,1),(witness['fresh_native_children'],witness['retained_table_children'],witness['retained_layout_children_separate']))
        self.assertEqual(['COMPLETE','FAILED','FAILED'],[root['original_status'] for root in witness['source_roots']])
        self.assertEqual(self.items['origin-table-resource'],witness['resources'][-1])
        self.assertEqual(['original-python','original-worker','--old-source'],witness['resources'][-1]['actual_argv'])
        self.assertEqual(original,result);self.assertEqual(0,witness['new_children_started']);self.assertEqual(0,witness['new_model_calls'])
        self.items['composed-witness']=witness
        eval_native.witness(tables,[record('composed-witness')],self.check)

    def test_composition_requires_authority_and_rejects_bad_child_or_duplicate_summary(self):
        for case in ('no_authority','bad_child','duplicate'):
            result,config=self.native(retained=True,retain_table=True);self.items['new-native-root']=deepcopy(result)
            c={**self.c,'allow_composed_retained_table_source_witness':case!='no_authority'}
            with patch.object(post,'read',self.read):tables=post.native_tables(self.c,result,config,self.check)
            if case=='bad_child':self.items['origin-table-resource']['failure']={'message':'failed child'}
            elif case=='duplicate':config['retained_table_shards']*=2
            with self.subTest(case=case),patch.object(post,'read',self.read),self.assertRaises(ValueError):post.composed_source_witness(c,record('new-native-root'),result,config,tables,self.check,lambda p:record(str(p)))

    def test_native_partial_wrong_config_missing_duplicate_or_unclosed_children_rejected(self):
        result,config=self.native()
        edits=[{'status':'FAILED'},{'config':record('other')},{'complete_full_inventory':False},
          {'actual_table_stage_pages':list(range(1,484))},{'resources':result['resources'][:-1]},
          {'resources':[result['resources'][0],*result['resources'][0:-1]]},
          {'shared_lock_released_after_owned_closure':False}]
        for edit in edits:
            with self.subTest(edit=list(edit)),patch.object(post,'read',self.read),self.assertRaises(ValueError):post.native_tables(self.c,{**result,**edit},config,self.check)
        result['resources'][1]['cleanup']['confirmed_all_known_owned_exited']=False
        with patch.object(post,'read',self.read),self.assertRaises(ValueError):post.native_tables(self.c,result,config,self.check)

    def test_native_selected_table_worker_options_and_source_partition_cannot_change(self):
        for edit in ({'worker':record('other-worker','b'*64)},
                     {'native_table_options':{**post.OPTIONS,'cpu_backend':'mkldnn','mkldnn_enabled':True}},
                     {'selected_pages':[1,1]},{'new_text_OCR_calls':1}):
            result,config=self.native();self.items['tables_000'].update(edit)
            with self.subTest(edit=list(edit)),patch.object(post,'read',self.read),self.assertRaises(ValueError):post.native_tables(self.c,result,config,self.check)

    def tiny(self):
        self.items['tiny-control']={'status':'COMPLETE','scope':'tiny','variant':'control'}
        self.items['tiny-candidate']={'status':'COMPLETE','scope':'tiny','variant':'candidate'}
        self.items['tiny-score']={'status':'COMPLETE','scope':'DIAGNOSTIC_TINY_NOT_FULL585',
                                 'actual_scorer_invocations':2,'writer_readback_verified':True}
        return {'contract':'document-ai-HQ-serial-result.v1','status':'COMPLETE','failure':None,
          'cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True,
          'resources':[resource(stage,record(name)) for stage,name in zip(post.STAGES,('tiny-control','tiny-candidate','tiny-score'))]}

    def test_tiny_requires_real_matched_parser_and_two_scorer_children_closed(self):
        closed=self.tiny()
        with patch.object(post,'read',self.read):post.tiny_closed(self.c['tiny_score'],closed,self.check)
        self.items['tiny-score']['actual_scorer_invocations']=1
        with patch.object(post,'read',self.read),self.assertRaises(ValueError):post.tiny_closed(self.c['tiny_score'],closed,self.check)
        closed=self.tiny();closed['resources'][1]['child_started']=False
        with patch.object(post,'read',self.read),self.assertRaises(ValueError):post.tiny_closed(self.c['tiny_score'],closed,self.check)

    def test_full_timing_override_is_explicit_and_inputs_are_preserved(self):
        steps=[{'id':name,'maximum_seconds':600,'worker':record('immutable-v4-worker'),'optimizer_updates_allowed':False} for name in post.STAGES]
        plan={'scope':'full484','steps':steps,'required_supervisor_output_root':'isolated-full-output'}
        serial=post.serial_config(self.c,plan)
        self.assertEqual([1800,1800,600],[s['maximum_seconds'] for s in serial['steps']])
        self.assertEqual([600,600,600],[s['maximum_seconds'] for s in plan['steps']])
        self.assertEqual(self.c['source'],serial['source']);self.assertEqual(RESOURCES,serial['resource_policy'])
        self.assertFalse(serial['production_activation_allowed']);self.assertEqual(7200,serial['maximum_total_seconds'])
        with self.assertRaises(ValueError):post.serial_config(self.c,{**plan,'scope':'tiny'})

if __name__=='__main__':unittest.main()
