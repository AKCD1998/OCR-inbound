"""No models/images: geometry/provenance/resource contract checks for HQ trials."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULES=Path(__file__).resolve().parents[1]/'experiments'/'document_ai'
sys.path.insert(0,str(MODULES))
import component_common as c
import component_worker as w
import materialize_models as m
import serial_supervisor as s
import install_docling_environment as installer

class ComponentContracts(unittest.TestCase):
    def setUp(self):
        self.registry=c.read(MODULES/'model_registry.json')
        self.task={'page':1,'source_frame':'original_image','source_size':[100,200],'machine_only':True,
            'tokens':[{'id':'t1','text':'RAW MG','bbox':[10,20,30,40],'engine':'paddle','confidence':.9}]}

    def test_every_exact_rotation_round_trips_original_tokens(self):
        for angle in (0,90,180,270):
            box=[1,2,99,198]
            self.assertEqual(c.restore_box(c.rotate_box(box,[100,200],angle),[100,200],angle),box)

    def test_outside_geometry_is_rejected_without_clipping(self):
        for box in ([-1,0,10,20],[0,0,101,200],[0,0,0,1],[0,0,float('nan'),1]):
            with self.assertRaises(ValueError):c.restore_box(box,[100,200],0)

    def test_overlap_abstains_instead_of_double_counting_word(self):
        cells=[{'id':'a','bbox':[0,0,50,50]},{'id':'b','bbox':[0,0,100,100]}]
        result=c.attach_tokens(cells,self.task['tokens'],[100,200])
        self.assertEqual([x['token_ids'] for x in result['cells']],[[],[]])
        self.assertEqual(len(result['ambiguous_tokens']),1)
        self.assertFalse(result['actual_word_ownership_preserved'])

    def test_partial_token_is_not_trimmed_or_assigned(self):
        result=c.attach_tokens([{'id':'a','bbox':[10,20,20,40]}],self.task['tokens'],[100,200])
        self.assertEqual(result['cells'][0]['token_ids'],[])
        self.assertIsNone(result['cells'][0]['raw_text'])

    def test_association_preserves_raw_print_instead_of_business_correction(self):
        result=c.attach_tokens([{'id':'a','bbox':[0,0,100,200]}],self.task['tokens'],[100,200])
        self.assertEqual(result['cells'][0]['raw_text'],'RAW MG')
        self.assertFalse(result['cells'][0]['association_verified'])
        self.assertEqual(result['new_OCR_calls'],0)

    def test_task_blocks_manual_and_canonical_answers(self):
        for engine in ('ASSISTANT','USER','gold-confirmed','silver','HUMAN review'):
            task=copy.deepcopy(self.task);task['tokens'][0]['engine']=engine
            with self.assertRaises(ValueError):c.validate_task(task)
        task=copy.deepcopy(self.task);task['tokens'][0]['business_corrected_text']='replacement'
        with self.assertRaises(ValueError):c.validate_task(task)

    def test_task_blocks_duplicate_id_and_foreign_frame(self):
        task=copy.deepcopy(self.task);task['tokens'].append(copy.deepcopy(task['tokens'][0]))
        with self.assertRaises(ValueError):c.validate_task(task)
        task=copy.deepcopy(self.task);task['source_frame']='resized_crop'
        with self.assertRaises(ValueError):c.validate_task(task)

    def test_qwen_is_blocked_before_import_or_download(self):
        pre=c.component_preflight(self.registry,'qwen',available_ram=8*1024**3,packages={'torch':'x','transformers':'x'})
        self.assertFalse(pre['admitted_for_bounded_canary'])
        self.assertIn('selected_native_weights_alone_exceed_owned_RSS_cap',pre['blocked_reasons'])
        self.assertEqual(pre['model_imports'],0)
        self.assertEqual(pre['model_calls'],0)
        self.assertNotIn('torch',sys.modules)

    def test_small_weights_do_not_prove_runtime_ram(self):
        pre=c.component_preflight(self.registry,'pp-layout',available_ram=c.RESOURCES['minimum_start_free_RAM_bytes']-1,
            packages={'paddleocr':'3.7.0','paddlepaddle':'3.2.2','paddlex':'3.7.2'})
        self.assertFalse(pre['admitted_for_bounded_canary'])
        self.assertTrue(pre['actual_RAM_requirement_not_inferred_from_weight_bytes'])

    def test_missing_isolated_dependencies_are_explicit(self):
        pre=c.component_preflight(self.registry,'docling',available_ram=3*1024**3,packages={})
        self.assertIn('missing_isolated_dependencies',pre['blocked_reasons'])

    def test_materialization_git_blob_hash_and_length_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';path.write_bytes(b'{}')
            entry={'size':2,'git_blob_sha1':hashlib.sha1(b'blob 2\0{}').hexdigest()}
            self.assertTrue(m.matches(path,entry));path.write_bytes(b'[]')
            self.assertFalse(m.matches(path,entry))

    def test_native_docling_matched_strings_never_become_ocr_answers(self):
        output=[{'tf_responses':[{'bbox':{'l':1,'t':2,'r':3,'b':4,'token':'not trusted'},'text':'not trusted',
            'start_row_offset_idx':0,'end_row_offset_idx':1,'column_header':True}]}]
        cells=w.docling_native_cells(output,['table-1'])
        self.assertEqual(cells[0]['bbox'],[1,2,3,4]);self.assertNotIn('text',cells[0]);self.assertNotIn('token',cells[0])

    def test_paddle_json_wrapper_requires_structured_data(self):
        self.assertEqual(w.payload('{"res":{"boxes":[]}}'),{'boxes':[]})
        with self.assertRaises(ValueError):w.payload([])

    def test_unknown_external_process_is_not_blanket_exempt(self):
        probe={'process_inventory_uncertain':[],'model_like_processes':[{'pid':17,'creation_time':1}]}
        with self.assertRaises(ValueError):s.ordinary_process_gate(probe,{'ordinary_external_processes':[]})

    def test_registry_has_immutable_public_revisions_and_content_digests(self):
        for model in self.registry['models'].values():
            self.assertEqual(len(model['revision']),40)
            for artifact in model['files']:
                self.assertIn('/'+model['revision']+'/',artifact['url'])
                self.assertTrue(artifact.get('sha256') or artifact.get('git_blob_sha1'))

    def test_isolated_dependency_lock_rejects_foreign_hosts(self):
        item={'metadata':{'name':'torch','version':'1'},'download_info':{'url':'https://foreign.invalid/a.whl','archive_info':{'hashes':{'sha256':'a'*64}}}}
        spec={'allowed_artifact_hosts':['files.pythonhosted.org'],'maximum_resolved_download_bytes':100}
        with self.assertRaises(ValueError):installer.checked_report({'install':[item]},spec,{item['download_info']['url']:20})

    def test_isolated_dependency_lock_enforces_hash_binary_and_size(self):
        url='https://files.pythonhosted.org/a.whl';item={'metadata':{'name':'torch','version':'1'},'download_info':{'url':url,'archive_info':{'hashes':{'sha256':'a'*64}}}}
        spec={'allowed_artifact_hosts':['files.pythonhosted.org'],'maximum_resolved_download_bytes':100}
        lock=installer.checked_report({'install':[item]},spec,{url:20});self.assertEqual(lock[0]['bytes'],20)
        with self.assertRaises(ValueError):installer.checked_report({'install':[item]},spec,{url:101})
        del item['download_info']['archive_info']['hashes']['sha256']
        with self.assertRaises(ValueError):installer.checked_report({'install':[item]},spec,{url:20})

    def test_training_gate_requires_2point3_GiB_before_child(self):
        fake=SimpleNamespace(virtual_memory=lambda:SimpleNamespace(available=s.TRAIN_START_BYTES-1))
        with self.assertRaises(ValueError):s.run_stage({'optimizer_updates_allowed':True},{},Path('.'),None,None,fake,time.monotonic()+10)

    def test_invalid_worker_summary_still_retains_resource_receipt(self):
        class Registry:
            def add(self,p):self.process=p
            def sample(self):return 1024
            def cleanup(self):
                self.last_cleanup={'confirmed_all_known_owned_exited':self.process.poll() is not None,'uncertain_or_live_owned':[]}
                return self.last_cleanup
        fake=SimpleNamespace(virtual_memory=lambda:SimpleNamespace(available=3*1024**3),Process=lambda:SimpleNamespace(create_time=lambda:1),NoSuchProcess=ProcessLookupError)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);worker=root/'worker.py';worker.write_text('pass\n');summary=root/'summary.json';summary.write_text('{invalid')
            stage={'id':'invalid_summary','worker':c.pin(worker),'args':[],'maximum_seconds':5,'optimizer_updates_allowed':False,
                   'summary_path':str(summary),'summary_equals':{'status':'COMPLETE'}}
            with patch.object(s,'checked',side_effect=lambda record:Path(record['path'])):
                with self.assertRaises(RuntimeError):s.run_stage(stage,{'pins':{'python':{'path':sys.executable,'sha256':'0'*64}}},root,None,Registry(),fake,time.monotonic()+10)
            receipt=c.read(root/'invalid_summary.resource.json')
            self.assertTrue(receipt['child_started']);self.assertEqual(receipt['actual_exit_code'],0)
            self.assertEqual(receipt['failure']['type'],'JSONDecodeError');self.assertTrue(receipt['logs_finalized_after_owned_cleanup'])

if __name__=='__main__':unittest.main()
