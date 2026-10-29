"""Source-only lifecycle proof and producer admission; no SDK/image/model."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import eval_lifecycle as life
from component_common import pin, read, save

class LifecycleProofTests(unittest.TestCase):
    def setUp(self):
        self.source=(Path(life.__file__).with_name('docling_stage_worker.py')).read_bytes()
        self.variant=self.source.replace(b"'maximum_SDK_startup_seconds':480",b"'maximum_SDK_startup_seconds':900").replace(b'Timer(480,startup_timeout)',b'Timer(900,startup_timeout)')

    def test_exact_two_tokens_and_normalized_ast_accept_the_real_source_structure(self):
        proof=life.prove_source(self.source,self.variant)
        self.assertEqual(['timeout_report','startup_watchdog'],[r['role'] for r in proof['replacements']])
        self.assertTrue(proof['other_bytes_identical']);self.assertTrue(proof['normalized_AST_identical'])
        self.assertEqual(0,proof['model_calls']);self.assertEqual(0,proof['image_decodes'])

    def test_third_token_comment_eol_threshold_prediction_import_and_partial_edits_rejected(self):
        for bad in (self.variant+b'\n# harmless-looking extra change\n',self.variant.replace(b'Timer(120,timeout)',b'Timer(121,timeout)'),
                    self.variant.replace(b'threshold=.6',b'threshold=.5'),self.variant.replace(b'import cv2',b'import cv3'),
                    self.variant.replace(b'Timer(900,startup_timeout)',b'Timer(480,startup_timeout)'),
                    self.variant.replace(b':900',b':900.0',1),self.variant.replace(b'\n',b'\r\n')):
            if bad==self.variant:continue
            with self.subTest(tail=bad[-60:]),self.assertRaises(ValueError):life.prove_source(self.source,bad)

    def fixture(self,root):
        def write(name,value):
            path=root/name
            if isinstance(value,bytes):path.write_bytes(value)
            else:save(path,value)
            return pin(path)
        original=write('original.py',self.source);variant=write('variant.py',self.variant)
        parent=write('parent.json',{'tasks':[]})
        versions={'numpy':'2.2.6','torch':'2.6.0+cpu'}
        abi=write('abi.json',{'status':'PASS','versions':versions,'native_cpu_array_sum':6,'numpy_tensor_roundtrip':True,'model_calls':0,'source_image_decodes':0})
        cpu=write('cpu.json',{'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'model_device':'cpu'})
        backend=write('backend.json',{'cpu_backend':'aten','mkldnn_enabled':False,'mkldnn_available':True})
        table={'contract':'document-ai-component-trial.v1','status':'COMPLETE','component':'docling','stage':'tables',
               'plan':parent,'selected_pages':list(range(1,65)),'pages_completed':64,'complete_stage_shard':True,
               'worker':original,'new_text_OCR_calls':0,'optimizer_updates':0,
               'registry':write('registry.json',{}),'materialization':write('model.json',{}),'runtime_versions':versions,
               'native_table_options':{'do_matching':False,'evaluation_predictions_supplied':False,'cpu_backend':'aten','mkldnn_enabled':False},
               'actual_runtime_ABI_proof':abi,'actual_native_CPU_binding':cpu,'actual_native_table_backend':backend}
        table_pin=write('table.json',table)
        resource={'worker_summary':table_pin,'child_started':True,'actual_exit_code':0,'failure':None,'stop_reason':None,
                  'worker_optimizer_updates_permission':False,'cleanup':{'confirmed_all_known_owned_exited':True},
                  'logs_finalized_after_owned_cleanup':True,'peak_owned_process_tree_RSS_bytes':1000000,'minimum_free_RAM_bytes':4000000000}
        resource_pin=write('resource.json',resource)
        origin_pin=write('failed-origin.json',{'status':'FAILED','failure':{'message':'later stage failed'},'resources':[resource],
             'cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True})
        entry={'summary':table_pin,'resource':resource_pin,'closed_source_supervision':origin_pin,'selected_pages':list(range(1,65))}
        return write,original,variant,parent,table,entry

    def test_root_receipt_and_exact_producer_roles_preserve_failed_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            write,old,new,parent,table,entry=self.fixture(Path(folder).resolve())
            with patch.object(life,'ORIGINAL_NATIVE_SHA',old['sha256']),patch.object(life,'FULL_PARENT_SHA',parent['sha256']):
                data=life.build_approval(old,new,entry,parent);approval=life.validate_approval(write('approval.json',data))
                self.assertEqual('retained_startup480',life.validate_producer(table,entry['summary'],approval))
                self.assertEqual('FAILED',read(entry['closed_source_supervision']['path'])['status'])
                fresh={**table,'worker':new};self.assertEqual('fresh_startup900',life.validate_producer(fresh,write('fresh.json',fresh),approval,'fresh'))
                # A deployment copy has the same source SHA, its own true path.
                deployed=write('deployed-copy.py',self.variant)
                self.assertEqual('fresh_startup900',life.validate_producer({**fresh,'worker':deployed},write('copy.json',fresh),approval,'fresh'))
                self.assertEqual(old,table['worker']);self.assertNotEqual(old['sha256'],new['sha256'])
                for bad,record,role in ((table,entry['summary'],'fresh'),(table,write('foreign.json',table),'candidate'),
                    ({**table,'worker':{'path':'old960.py','sha256':'9'*64}},entry['summary'],'candidate'),
                    ({**table,'selected_pages':[65]},entry['summary'],'candidate'),
                    ({**fresh,'runtime_versions':{'torch':'different'}},write('wrong-runtime.json',fresh),'fresh')):
                    with self.subTest(role=role,record=record),self.assertRaises(ValueError):life.validate_producer(bad,record,approval,role)

    def test_receipt_rejects_modified_policy_proof_sources_scope_and_failed_child(self):
        with tempfile.TemporaryDirectory() as folder:
            write,old,new,parent,table,entry=self.fixture(Path(folder).resolve())
            with patch.object(life,'ORIGINAL_NATIVE_SHA',old['sha256']),patch.object(life,'FULL_PARENT_SHA',parent['sha256']):
                data=life.build_approval(old,new,entry,parent)
                for key,value in (('policy',{**life.POLICY,'maximum_native_predict_seconds':121}),('approved_by','other'),
                                  ('same_operational_admission_claimed',True),('source_proof',{}),('fixed_evaluation_scope',{}),
                                  ('retained_table',{**entry,'selected_pages':[1,2]})):
                    with self.subTest(key=key),self.assertRaises(ValueError):life.validate_approval(write('bad-'+key+'.json',{**data,key:value}))
                resource=read(entry['resource']['path']);resource['actual_exit_code']=125
                tampered=write('bad-resource.json',resource);bad=deepcopy(data);bad['retained_table']['resource']=tampered
                with self.assertRaises(ValueError):life.validate_approval(write('bad-child.json',bad))

    def test_model_family_is_not_producer_identity_or_cache_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            write,old,new,parent,table,entry=self.fixture(Path(folder).resolve())
            with patch.object(life,'ORIGINAL_NATIVE_SHA',old['sha256']),patch.object(life,'FULL_PARENT_SHA',parent['sha256']):
                approval=life.validate_approval(write('approval.json',life.build_approval(old,new,entry,parent)))
                fresh={**table,'worker':new,'runtime_cache':{'path':'selected084','sha256':'8'*64}}
                self.assertEqual(life.recipe_identity(table,approval),life.recipe_identity(fresh,approval))
                self.assertNotEqual(life.lineage(table,entry['summary'],approval),life.lineage(fresh,write('fresh.json',fresh),approval))
                self.assertEqual(new,life.lineage(fresh,write('fresh2.json',fresh),approval)['actual_worker'])

    def test_selected_fresh_delivery_cache_is_enforced_without_relabelling_old_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            write,old,new,parent,table,entry=self.fixture(Path(folder).resolve())
            selected=write('selected-cache.json',{'selected':'084 metadata only'})
            with patch.object(life,'ORIGINAL_NATIVE_SHA',old['sha256']),patch.object(life,'FULL_PARENT_SHA',parent['sha256']):
                data=life.build_approval(old,new,entry,parent,{'selected_runtime_cache':selected})
                record=write('approval.json',data);approval=life.validate_approval(record)
                profile={'lifecycle_equivalence':record,'selected_fresh_worker_sha256':new['sha256']}
                self.assertEqual(approval.family_sha256,life.context(profile).family_sha256)
                fresh={**table,'worker':new,'runtime_cache':selected}
                self.assertEqual('fresh_startup900',life.validate_producer(fresh,write('fresh.json',fresh),approval,'fresh'))
                for cache in (None,{'path':'foreign','sha256':'8'*64}):
                    with self.assertRaises(ValueError):life.validate_producer({**fresh,'runtime_cache':cache},{},approval,'fresh')
                self.assertEqual('retained_startup480',life.validate_producer(table,entry['summary'],approval))

if __name__=='__main__':unittest.main()
