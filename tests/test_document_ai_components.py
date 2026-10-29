"""No models/images: geometry/provenance/resource contract checks for HQ trials."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import io
import time
from types import SimpleNamespace
import unittest
import subprocess
import zipfile
from unittest.mock import patch

MODULES=Path(__file__).resolve().parents[1]/'experiments'/'document_ai'
sys.path.insert(0,str(MODULES))
import component_common as c
import component_worker as w
import materialize_models as m
import serial_supervisor as s
import install_docling_environment as installer
import install_docling_environment_v2 as installer_v2
import pip_stage_runner
import docling_stage_worker as docling_stage
import docling_full_driver as docling_full
import python_cache
import py_compile

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

    def test_local_repair_requires_verified_retained_file_not_arbitrary_file_url(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'torch-test.whl';path.write_bytes(b'fake-wheel-metadata')
            local={'file_url':path.as_uri(),'path':str(path),'sha256':c.sha(path),'bytes':path.stat().st_size,'upstream_url':'https://download.pytorch.org/verified.whl'}
            item={'metadata':{'name':'torch','version':'test'},'download_info':{'url':path.as_uri(),'archive_info':{'hashes':{'sha256':local['sha256']}}}}
            spec={'allowed_artifact_hosts':['files.pythonhosted.org'],'maximum_resolved_download_bytes':1000}
            result=installer_v2.lock_resolution({'install':[item]},spec,[local]);self.assertEqual(result[0]['sha256'],local['sha256'])
            with self.assertRaises(ValueError):installer_v2.lock_resolution({'install':[item]},spec,[])
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):installer_v2.lock_resolution({'install':[item]},spec,[local])

    def test_repair_preserves_same_two_pinned_CPU_wheel_versions(self):
        spec=c.read(MODULES/'docling_environment.json');direct=installer_v2.direct_requirements(spec)
        self.assertEqual({x['name'] for x in direct},{'torch','torchvision'})
        self.assertEqual(next(x for x in direct if x['name']=='torch')['filename'],'torch-2.8.0+cpu-cp311-cp311-win_amd64.whl')
        bad=copy.deepcopy(spec);bad['primary_requirements'][0]='torch @ https://foreign.invalid/model.whl#sha256='+'a'*64
        with self.assertRaises(ValueError):installer_v2.direct_requirements(bad)

    def test_local_resolution_cannot_expand_download_budget(self):
        url='https://files.pythonhosted.org/a.whl';item={'metadata':{'name':'x','version':'1'},'download_info':{'url':url,'archive_info':{'hashes':{'sha256':'a'*64}}}}
        spec={'allowed_artifact_hosts':['files.pythonhosted.org'],'maximum_resolved_download_bytes':100}
        with self.assertRaises(ValueError):installer_v2.lock_resolution({'install':[item]},spec,[],{url:101})

    def test_larger_hash_reads_preserve_all_bytes_and_the_same_digest(self):
        raw=bytes(range(256))*1025
        for chunk in (1,8192,1048576,8388608):
            result=b''.join(pip_stage_runner.exact_hash_chunks(io.BytesIO(raw),chunk))
            self.assertEqual(result,raw);self.assertEqual(hashlib.sha256(result).digest(),hashlib.sha256(raw).digest())
        self.assertEqual(list(pip_stage_runner.exact_hash_chunks(io.BytesIO(b''))),[])

    def test_larger_install_copy_preserves_every_byte_and_explicit_buffer(self):
        raw=bytes(range(256))*1025
        class ReadTrace(io.BytesIO):
            def read(self,size=-1):
                observed.append(size);return super().read(size)
        for explicit,expected in ((0,8388608),(8192,8192)):
            observed=[];out=io.BytesIO();pip_stage_runner.exact_buffered_copy(ReadTrace(raw),out,explicit)
            self.assertEqual(out.getvalue(),raw);self.assertTrue(all(x==expected for x in observed))

    def test_pip_zip_bootstrap_executes_only_when_pinned_digest_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);wheel=root/'pip-fixture.whl'
            with zipfile.ZipFile(wheel,'w') as archive:
                for name in ('pip/__init__.py','pip/_internal/__init__.py','pip/_internal/utils/__init__.py'):archive.writestr(name,'')
                archive.writestr('pip/_internal/utils/hashes.py','def read_chunks(stream):\n    yield b""\n')
                archive.writestr('pip/__main__.py','print("PINNED_PIP_FIXTURE_EXECUTED")\n')
            for expected,success in ((c.sha(wheel),True),('0'*64,False)):
                journal=root/('success.json' if success else 'rejected.json')
                argv=[sys.executable,'-I','-B',str(MODULES/'pip_stage_runner.py'),'--journal',str(journal),
                      '--bootstrap-pip-wheel',str(wheel),'--bootstrap-pip-wheel-sha256',expected,'--','--isolated','install','--dry-run','--no-index']
                result=subprocess.run(argv,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode==0,success)
                self.assertEqual('PINNED_PIP_FIXTURE_EXECUTED' in result.stdout,success)

    def test_docling_native_timeout_remains_120_seconds_with_startup_separate(self):
        observed=[]
        class Timer:
            def __init__(self,seconds,callback):observed.append(seconds)
            def start(self):pass
            def cancel(self):observed.append('cancelled')
        with tempfile.TemporaryDirectory() as folder,patch.object(docling_stage.threading,'Timer',Timer):
            self.assertEqual(docling_stage.native_call(Path(folder),'synthetic-layout',lambda:7),7)
            marker=c.read(Path(folder)/'synthetic-layout.PREDICT_STARTED.json')
            self.assertEqual(marker['maximum_native_predict_seconds'],120)
            completed=c.read(Path(folder)/'synthetic-layout.PREDICT_COMPLETED.json')
            self.assertGreaterEqual(completed['elapsed_seconds'],0)
        self.assertEqual(observed,[120,'cancelled'])

    def test_table_stage_refuses_unclosed_or_foreign_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);registry={'path':'registry','sha256':'a'*64};source={'path':'image','sha256':'b'*64}
            task={'page':1,'source_image':source,'source_size':[100,200]};plan={'tasks':[task]}
            page={'contract':'document-ai-original-frame-geometry.v1','page':1,'source_image':source,'source_size':[100,200],'source_frame':'original_image',
                  'rotation_ccw':0,'new_text_OCR_calls':0,'assistant_image_transcription':False,'layout_model_calls':1}
            pagefile=root/'page.json';c.save(pagefile,page)
            summary={'status':'COMPLETE','component':'docling','stage':'layout','registry':registry,'new_text_OCR_calls':0,'optimizer_updates':0,
                     'pages_completed':1,'actual_completed_layout_model_calls':1,'page_results':[c.pin(pagefile)]}
            summaryfile=root/'summary.json';c.save(summaryfile,summary)
            resource={'actual_exit_code':0,'failure':None,'stop_reason':None,'cleanup':{'confirmed_all_known_owned_exited':True},'worker_summary':c.pin(summaryfile),
                      'peak_owned_process_tree_RSS_bytes':1024,'minimum_free_RAM_bytes':3*1024**3,'logs_finalized_after_owned_cleanup':True}
            resourcefile=root/'resource.json';c.save(resourcefile,resource)
            result,pages=docling_stage.actual_upstream(summaryfile,c.sha(summaryfile),resourcefile,c.sha(resourcefile),plan,registry)
            self.assertEqual(set(pages),{1})
            resource['cleanup']['confirmed_all_known_owned_exited']=False;bad=root/'unclosed.json';c.save(bad,resource)
            with self.assertRaises(ValueError):docling_stage.actual_upstream(summaryfile,c.sha(summaryfile),bad,c.sha(bad),plan,registry)
            with self.assertRaises(ValueError):docling_stage.actual_upstream(summaryfile,c.sha(summaryfile),resourcefile,c.sha(resourcefile),plan,{'path':'foreign','sha256':'c'*64})

    def test_docling_full_plan_uses_bounded_slices_without_rewriting_parent(self):
        plan={'tasks':[{'page':i} for i in range(1,485)]};before=copy.deepcopy(plan)
        shards=[docling_stage.selected_tasks(plan,start,min(64,484-start)) for start in range(0,484,64)]
        self.assertEqual([t['page'] for shard in shards for t in shard],list(range(1,485)))
        self.assertEqual(plan,before)
        for start,count in ((0,65),(484,1),(-1,1),(480,5)):
            with self.assertRaises(ValueError):docling_stage.selected_tasks(plan,start,count)

    def test_durable_full_driver_partitions_exact484_without_duplicates(self):
        for count in (1,16,32,64):
            shards=docling_full.ranges(484,count)
            actual=[p for start,n in shards for p in range(start,start+n)]
            self.assertEqual(actual,list(range(484)))
            self.assertTrue(all(0<n<=64 for _,n in shards))
        for total,count in ((483,32),(484,0),(484,65),(484,True)):
            with self.assertRaises(ValueError):docling_full.ranges(total,count)

    def test_retained_partitions_refuse_overlap_misalignment_and_boolean_ids(self):
        shards=docling_full.ranges(484,64);entry={'slice_start':0,'slice_count':64}
        self.assertEqual(docling_full.retained_partitions([entry],shards),{(0,64):entry})
        for entries in ([entry,entry],[{'slice_start':1,'slice_count':64}],
                        [{'slice_start':False,'slice_count':64}],[{'slice_start':0,'slice_count':True}]):
            with self.subTest(entries=entries),self.assertRaises(ValueError):docling_full.retained_partitions(entries,shards)

    def test_retained_table_preserves_failed_parent_and_rejects_changed_evidence(self):
        # Genuine files/hashes with synthetic geometry; no pixels or model SDK.
        with tempfile.TemporaryDirectory() as temporary:
            for case in ('good','failed_child','worker','runtime','frame','layout_owner','unfinished_calls'):
                root=Path(temporary)/case;root.mkdir()
                def write(name,value):
                    p=root/name;c.save(p,value);return c.pin(p)
                worker=root/'worker.py';worker.write_text('# synthetic original worker\n')
                task={'page':1,'source_image':{'path':'synthetic-image','sha256':'a'*64},'source_size':[100,200]}
                plan={'tasks':[task]};parent={'path':'frozen-parent','sha256':'b'*64}
                frame={'contract':'document-ai-original-frame-geometry.v1','component':'docling','page':1,
                       'source_image':task['source_image'],'source_size':task['source_size'],'source_frame':'original_image',
                       'rotation_ccw':0,'regions':[],'new_text_OCR_calls':0,'assistant_image_transcription':False}
                layout_page=write('layout-page.json',{**frame,'stage':'layout','layout_model_calls':1})
                layout=write('layout.json',{'page_results':[layout_page]})
                upstream={'summary':layout,'resource':write('layout-resource.json',{'synthetic_closed_layout':True})}
                options={'do_matching':False,'evaluation_predictions_supplied':False,'cpu_backend':'aten','mkldnn_enabled':False}
                versions={'numpy':'synthetic-numpy','torch':'synthetic-torch'}
                positive={'worker':c.pin(worker),'registry':{'path':'registry','sha256':'c'*64},
                          'materialization':{'path':'data','sha256':'d'*64},'runtime_versions':versions,'native_table_options':options,
                          'runtime_cache':{'path':'new-performance-only-cache','sha256':'e'*64}}
                page={**frame,'stage':'tables','table_model_calls':1,'native_table_options':options,
                      'upstream_layout_summary':layout,'upstream_layout_resource':upstream['resource'],'upstream_layout_observation':layout_page}
                if case=='frame':page['source_size']=[99,200]
                elif case=='layout_owner':page['upstream_layout_resource']={'path':'other','sha256':'f'*64}
                summary={**positive,'status':'COMPLETE','component':'docling','stage':'tables','plan':parent,
                         'runtime_cache':{'path':'original-retained-cache','sha256':'1'*64},
                         'full_source_inventory_pages':484,'selected_pages':[1],'pages_completed':1,'complete_stage_shard':True,
                         'new_text_OCR_calls':0,'optimizer_updates':0,'actual_completed_table_model_calls':1,
                         'actual_model_predict_calls_started':1,'upstream_layout_summary':layout,'page_results':[write('table-page.json',page)],
                         'actual_runtime_ABI_proof':write('abi.json',{'status':'PASS','versions':versions,'native_cpu_array_sum':6,
                           'numpy_tensor_roundtrip':True,'model_calls':0,'source_image_decodes':0}),
                         'actual_native_CPU_binding':write('cpu.json',{'torch_compute_threads':1,'torch_interop_threads':1,'opencv_threads':1,'model_device':'cpu'}),
                         'actual_native_table_backend':write('backend.json',{'cpu_backend':'aten','mkldnn_enabled':False,'mkldnn_available':True})}
                if case=='worker':summary['worker']={'path':'another-worker','sha256':'2'*64}
                elif case=='runtime':summary['runtime_versions']={'numpy':'changed','torch':'changed'}
                elif case=='unfinished_calls':summary['actual_model_predict_calls_started']=2
                summary_pin=write('table.json',summary)
                resource={'worker_summary':summary_pin,'actual_exit_code':0,'failure':None,'stop_reason':None,
                          'child_started':True,'worker_optimizer_updates_permission':False,'logs_finalized_after_owned_cleanup':True,
                          'peak_owned_process_tree_RSS_bytes':1024,'minimum_free_RAM_bytes':3*1024**3,
                          'cleanup':{'confirmed_all_known_owned_exited':True}}
                if case=='failed_child':resource['actual_exit_code']=1
                origin={'status':'FAILED','failure':{'message':'later child failed'},'resources':[resource],
                        'cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True}
                entry={'summary':summary_pin,'resource':write('table-resource.json',resource),
                       'closed_source_supervision':write('original-root.json',origin)}
                before=copy.deepcopy(origin)
                if case=='good':
                    actual=docling_full.retained_table(entry,plan,parent,[1],upstream,positive)
                    self.assertEqual(actual['worker'],positive['worker'])
                    self.assertEqual(actual['runtime_cache']['path'],'original-retained-cache')
                    self.assertEqual(c.read(entry['closed_source_supervision']['path']),before)
                else:
                    with self.subTest(case=case),self.assertRaises(ValueError):docling_full.retained_table(entry,plan,parent,[1],upstream,positive)

    def test_durable_table_template_requires_exact_closed_layout_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'actual-summary.json';resource=root/'actual-resource.json'
            source.write_text('{}');resource.write_text('{}')
            template={'component':'docling','optimizer_updates_allowed':False,
                      'args':['--stage','layout','--output','placeholder','--execute'],
                      'input_pins':[],'maximum_seconds':2400}
            before=copy.deepcopy(template)
            with self.assertRaises(ValueError):docling_full.step_for(template,root,0,0,16,'tables')
            upstream={'summary':c.pin(source),'resource':c.pin(resource)}
            step=docling_full.step_for(template,root,0,0,16,'tables',upstream)
            self.assertEqual(template,before)
            self.assertEqual(step['summary_equals']['pages_completed'],16)
            self.assertFalse(step['summary_equals']['complete_full_inventory'])
            self.assertEqual(step['input_pins'],[upstream['summary'],upstream['resource']])
            source.write_text('{"changed":true}')
            with self.assertRaises(ValueError):docling_full.step_for(template,root,0,0,16,'tables',upstream)

    def test_durable_full_gate_rejects_metadata_partial_or_unclosed_tiny(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);summaries=[]
            for i,kind in enumerate(('control','candidate','score')):
                data={'status':'COMPLETE','scope':'tiny','variant':kind} if i<2 else {'status':'COMPLETE','scope':'DIAGNOSTIC_TINY_NOT_FULL585','actual_scorer_invocations':2,'writer_readback_verified':True}
                path=root/(kind+'.json');c.save(path,data);summaries.append(c.pin(path))
            stages=['control','candidate','score']
            tiny={'contract':'document-ai-HQ-serial-result.v1','status':'COMPLETE',
                  'cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True,
                  'resources':[{'stage':stage,'child_started':True,'actual_exit_code':0,'failure':None,'stop_reason':None,
                                'worker_optimizer_updates_permission':False,'cleanup':{'confirmed_all_known_owned_exited':True},
                                'worker_summary':summaries[i]} for i,stage in enumerate(stages)]}
            self.assertEqual(len(docling_full.tiny_closed(tiny,stages)),3)
            bad=copy.deepcopy(tiny);bad['resources'][1]['actual_exit_code']=1
            with self.assertRaises(ValueError):docling_full.tiny_closed(bad,stages)
            bad=copy.deepcopy(tiny);bad['cleanup']['confirmed_all_known_owned_exited']=False
            with self.assertRaises(ValueError):docling_full.tiny_closed(bad,stages)
            with self.assertRaises(ValueError):docling_full.tiny_closed(tiny,['metadata','candidate','score'])

    def test_durable_union_rejects_wrong_parent_and_duplicate_actual_page(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'page.json';p.write_text('{"page":1}')
            parent={'path':'fixed-plan','sha256':'a'*64}
            summary={'status':'COMPLETE','component':'docling','stage':'layout','plan':parent,
                     'full_source_inventory_pages':484,'selected_pages':[1],'pages_completed':1,
                     'complete_stage_shard':True,'new_text_OCR_calls':0,'optimizer_updates':0,'page_results':[c.pin(p)]}
            self.assertEqual(docling_full.completed_pages(summary,parent,[1],'layout'),[1])
            with self.assertRaises(ValueError):docling_full.completed_pages(summary,{'path':'other','sha256':'a'*64},[1],'layout')
            bad=copy.deepcopy(summary);bad['page_results'].append(c.pin(p))
            with self.assertRaises(ValueError):docling_full.completed_pages(bad,parent,[1],'layout')

    def test_durable_full_gate_requires_actual_positive_table_cells(self):
        with tempfile.TemporaryDirectory() as folder:
            page=Path(folder)/'page.json';c.save(page,{'page':3,'table_model_calls':1,'cell_association':{'cells':[{'id':'native-cell'}]}})
            backend=Path(folder)/'backend.json';c.save(backend,{'cpu_backend':'aten','mkldnn_enabled':False,'mkldnn_available':True})
            summary={'status':'COMPLETE','component':'docling','stage':'tables','actual_completed_table_model_calls':1,
                     'new_text_OCR_calls':0,'optimizer_updates':0,'page_results':[c.pin(page)],
                     'actual_native_table_backend':c.pin(backend),'native_table_options':{'cpu_backend':'aten','mkldnn_enabled':False}}
            result={'status':'COMPLETE','cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True}
            self.assertEqual(docling_full.positive_table_canary(summary,result,3)['page'],3)
            with self.assertRaises(ValueError):docling_full.positive_table_canary(summary,result,2)
            bad=copy.deepcopy(summary);bad['actual_completed_table_model_calls']=0
            with self.assertRaises(ValueError):docling_full.positive_table_canary(bad,result,3)

    def test_docling_no_native_matching_still_calls_real_SDK_without_eval_answers(self):
        observed=[]
        class Model:
            def multi_table_predict(self,*args,**kwargs):
                observed.append((args,kwargs));return ['native-forward-result']
        page={'image':'synthetic-placeholder','tokens':[]};bbox=[1,2,10,20]
        for mode in (True,False):
            self.assertEqual(docling_stage.table_geometry_predict(Model(),page,bbox,mode),['native-forward-result'])
            args,kwargs=observed[-1]
            self.assertIs(args[0],page);self.assertEqual(args[1],[bbox]);self.assertIsNot(args[1][0],bbox)
            self.assertEqual(kwargs,{'do_matching':mode})
        with self.assertRaises(ValueError):docling_stage.table_geometry_predict(Model(),page,bbox,'False')

    def test_full_native_source_and_matching_mode_must_equal_positive_canary(self):
        positive={'worker':{'sha256':'a'*64},'native_table_options':{'do_matching':False,'evaluation_predictions_supplied':False,'cpu_backend':'aten','mkldnn_enabled':False}}
        template={'worker':{'sha256':'a'*64},'args':['--native-cell-matching','disabled','--table-cpu-backend','aten']}
        self.assertEqual(docling_full.accepted_worker_options(template,positive),positive['native_table_options'])
        for changed in ({'worker':{'sha256':'b'*64},'args':template['args']},
                        {'worker':template['worker'],'args':['--native-cell-matching','enabled']},
                        {'worker':template['worker'],'args':[]}):
            with self.assertRaises(ValueError):docling_full.accepted_worker_options(changed,positive)
        cached=copy.deepcopy(positive);cached['runtime_cache']={'path':'accepted-cache.json','sha256':'c'*64}
        with self.assertRaises(ValueError):docling_full.accepted_worker_options(template,cached)
        selected=copy.deepcopy(template);selected['args']+=['--runtime-cache-manifest','accepted-cache.json','--runtime-cache-manifest-sha256','c'*64]
        self.assertEqual(docling_full.accepted_worker_options(selected,cached),positive['native_table_options'])
        with self.assertRaises(ValueError):docling_full.accepted_worker_options(selected,positive)

    def test_table_boundary_hooks_observe_only_once_and_never_replace_output(self):
        class Module:
            def register_forward_pre_hook(self,callback):self.before=callback;return SimpleNamespace(remove=lambda:None)
            def register_forward_hook(self,callback):self.after=callback;return SimpleNamespace(remove=lambda:None)
        first=Module();encoder=Module();encoder._resnet=[first]
        neural=SimpleNamespace(_encoder=encoder,_tag_transformer=SimpleNamespace(_encoder=Module(),_decoder=Module()))
        model=SimpleNamespace(get_model=lambda:neural);observed=[]
        handles=docling_stage.install_table_boundary_hooks(model,lambda phase,evidence=None:observed.append((phase,evidence)))
        value=SimpleNamespace(shape=(1,3,448,448))
        for _ in range(2):
            self.assertIsNone(first.before(first,(value,)))
            self.assertIsNone(first.after(first,(value,),'unchanged-native-output'))
        self.assertEqual(len(handles),8);self.assertEqual([x[0] for x in observed],['CNN_FIRST_CONV_STARTED','CNN_FIRST_CONV_COMPLETED'])
        self.assertEqual(observed[0][1],{'first_input_shape':[1,3,448,448]})

    def test_native_table_routing_keeps_all_five_under_exact_model_query_bound(self):
        tables=[{'id':str(i),'label':'table','bbox':[0,0,10,10]} for i in range(5)]
        self.assertEqual(docling_stage.bounded_native_tables(tables,[20,20],300),tables)
        with self.assertRaises(ValueError):docling_stage.bounded_native_tables(tables,[20,20],4)
        with self.assertRaises(ValueError):docling_stage.bounded_native_tables(tables+[tables[0]],[20,20],300)
        with self.assertRaises(ValueError):docling_stage.bounded_native_tables(tables,[20,20],False)

    def test_fault_diagnostics_retain_fatal_capture_without_async_periodic_dump(self):
        with patch.object(docling_stage.faulthandler,'enable') as fatal,patch.object(docling_stage.faulthandler,'dump_traceback_later') as asynchronous:
            receipt=docling_stage.configure_fault_diagnostics()
        fatal.assert_called_once_with();asynchronous.assert_not_called()
        self.assertFalse(receipt['periodic_thread_dump'])
        self.assertTrue(receipt['supervisor_deadlines_and_resource_limits_unchanged'])

    def test_retained_layout_keeps_original_worker_and_allows_later_source_stage_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);registry={'path':'registry','sha256':'r'*64};parent={'path':'parent','sha256':'p'*64}
            original={'path':'old-native-worker','sha256':'a'*64};runtime={'numpy':'same-numpy','torch':'same-torch'}
            materialization={'path':'same-materialization','sha256':'m'*64}
            tasks=[{'page':n,'source_image':{'path':'source-'+str(n),'sha256':'b'*64},'source_size':[100,200]} for n in range(1,485)]
            plan={'tasks':tasks};task=tasks[0]
            page={'contract':'document-ai-original-frame-geometry.v1','page':1,'source_image':task['source_image'],
                  'source_size':task['source_size'],'source_frame':'original_image','rotation_ccw':0,
                  'new_text_OCR_calls':0,'assistant_image_transcription':False,'layout_model_calls':1}
            pagefile=root/'page.json';c.save(pagefile,page)
            summary={'status':'COMPLETE','component':'docling','stage':'layout','worker':original,'plan':parent,'registry':registry,
                     'new_text_OCR_calls':0,'optimizer_updates':0,'pages_completed':1,'actual_completed_layout_model_calls':1,
                     'full_source_inventory_pages':484,'selected_pages':[1],'complete_stage_shard':True,
                     'runtime_versions':runtime,'materialization':materialization,'page_results':[c.pin(pagefile)]}
            summaryfile=root/'summary.json';c.save(summaryfile,summary)
            resource={'actual_exit_code':0,'failure':None,'stop_reason':None,'cleanup':{'confirmed_all_known_owned_exited':True},
                      'worker_summary':c.pin(summaryfile),'peak_owned_process_tree_RSS_bytes':1024,'minimum_free_RAM_bytes':3*1024**3,
                      'logs_finalized_after_owned_cleanup':True}
            resourcefile=root/'resource.json';c.save(resourcefile,resource)
            execution={'status':'FAILED','cleanup':{'confirmed_all_known_owned_exited':True},'shared_lock_released_after_owned_closure':True,
                       'resources':[resource,{'stage':'unrelated_later_table','actual_exit_code':3221225477}]}
            executionfile=root/'execution.json';c.save(executionfile,execution)
            entry={'summary':c.pin(summaryfile),'resource':c.pin(resourcefile),'closed_source_supervision':c.pin(executionfile)}
            retained,upstream=docling_full.retained_layout(entry,plan,parent,registry,[1],runtime,materialization)
            self.assertEqual(retained['worker'],original);self.assertEqual(upstream['summary'],entry['summary'])
            with self.assertRaises(ValueError):docling_full.retained_layout(entry,plan,parent,registry,[1],{'numpy':'different','torch':'same-torch'},materialization)
            with self.assertRaises(ValueError):docling_full.retained_layout(entry,plan,parent,registry,[2],runtime,materialization)
            with self.assertRaises(ValueError):docling_full.retained_layout(entry,plan,parent,registry,[1],runtime,{'path':'foreign','sha256':'x'*64})
            resource['peak_owned_process_tree_RSS_bytes']=2048;foreign=root/'foreign-resource.json';c.save(foreign,resource)
            changed=copy.deepcopy(entry);changed['resource']=c.pin(foreign)
            with self.assertRaises(ValueError):docling_full.retained_layout(changed,plan,parent,registry,[1],runtime,materialization)

    def test_isolated_cache_preserves_source_and_quarantines_unregistered_pyc(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();cache=root/'cache';cache.mkdir();source=root/'needed.py';source.write_text('value=42\n')
            unused=root/'unused.py';unused.write_text('value=17\n');before=c.sha(source)
            with patch.object(sys,'pycache_prefix',str(cache)):
                for path in (source,unused):
                    dest=Path(importlib.util.cache_from_source(str(path)));dest.parent.mkdir(parents=True,exist_ok=True)
                    py_compile.compile(str(path),cfile=str(dest),doraise=True)
                records,quarantined=python_cache.collect_cache(cache,[SimpleNamespace(__file__=str(source))],{str(source.resolve()):before},[root])
            self.assertEqual(c.sha(source),before);self.assertEqual(len(records),1);self.assertEqual(len(quarantined),1)
            self.assertTrue(Path(quarantined[0]['preserved']['path']).is_file())
            self.assertEqual(len(list(cache.rglob('*.pyc'))),1)
            manifest={'contract':python_cache.CONTRACT,'status':'COMPLETE','python':c.pin(sys.executable),
                      'cache_tag':sys.implementation.cache_tag,'bytecode_magic':importlib.util.MAGIC_NUMBER.hex(),
                      'cache_root':str(cache),'cached_modules':records,'cached_module_count':1}
            self.assertEqual(python_cache.verify_cache(manifest),cache)
            source.write_text('value=43\n')
            with self.assertRaises(ValueError):python_cache.verify_cache(manifest)

    def test_cache_rejects_extra_bytecode_and_wrong_interpreter_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'module.py';source.write_text('x=1\n');cache=root/'cache';cache.mkdir();pyc=cache/'module.pyc'
            py_compile.compile(str(source),cfile=str(pyc),doraise=True)
            manifest={'contract':python_cache.CONTRACT,'status':'COMPLETE','python':c.pin(sys.executable),
                      'cache_tag':sys.implementation.cache_tag,'bytecode_magic':importlib.util.MAGIC_NUMBER.hex(),
                      'cache_root':str(cache),'cached_modules':[{'source':c.pin(source),'cache':c.pin(pyc),'compile_source_bytes_sha256':c.sha(source)}],
                      'cached_module_count':1}
            self.assertEqual(python_cache.verify_cache(manifest),cache)
            bad=copy.deepcopy(manifest);bad['cache_tag']='wrong-python'
            with self.assertRaises(ValueError):python_cache.verify_cache(bad)
            (cache/'untracked.pyc').write_bytes(pyc.read_bytes())
            with self.assertRaises(ValueError):python_cache.verify_cache(manifest)

    def test_lazy_cache_hashes_actual_returned_bytes_and_source_even_for_valid_pyc(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'module.py';source.write_text('x=1\n');cache=root/'cache';cache.mkdir();pyc=cache/'module.pyc'
            py_compile.compile(str(source),cfile=str(pyc),doraise=True)
            manifest={'contract':python_cache.CONTRACT,'status':'COMPLETE','python':c.pin(sys.executable),
                      'cache_tag':sys.implementation.cache_tag,'bytecode_magic':importlib.util.MAGIC_NUMBER.hex(),
                      'cache_root':str(cache),'cached_module_count':1,
                      'cached_modules':[{'source':c.pin(source),'cache':c.pin(pyc)}]}
            index={'contract':python_cache.SOURCE_INDEX,'python':c.pin(sys.executable),'sources':[{'source':c.pin(source)}]}
            original=pyc.read_bytes();reads=[]
            class Loader:
                path=str(source)
                def get_data(self,path):reads.append(str(path));return Path(path).read_bytes()
            observed=python_cache.install_lazy_checks(manifest,index,Loader)
            self.assertEqual(Loader().get_data(str(pyc)),original)
            self.assertEqual(reads,[str(pyc),str(source)])
            self.assertEqual(observed['source_checks'],1);self.assertEqual(observed['bytecode_checks'],1)
            source.write_text('x=2\n')
            with self.assertRaises(ImportError):Loader().get_data(str(pyc))
            self.assertEqual(pyc.read_bytes(),original)

    def test_lazy_cache_rejects_inflight_pyc_tamper_and_unknown_existing_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'module.py';source.write_text('x=1\n');cache=root/'cache';cache.mkdir();pyc=cache/'module.pyc'
            py_compile.compile(str(source),cfile=str(pyc),doraise=True)
            manifest={'contract':python_cache.CONTRACT,'status':'COMPLETE','python':c.pin(sys.executable),
                      'cache_tag':sys.implementation.cache_tag,'bytecode_magic':importlib.util.MAGIC_NUMBER.hex(),
                      'cache_root':str(cache),'cached_module_count':1,
                      'cached_modules':[{'source':c.pin(source),'cache':c.pin(pyc)}]}
            index={'contract':python_cache.SOURCE_INDEX,'python':c.pin(sys.executable),'sources':[{'source':c.pin(source)}]}
            class Loader:
                path=str(source)
                corrupt=False
                def get_data(self,path):
                    data=Path(path).read_bytes()
                    return data+b'changed_after_a_precheck' if self.corrupt and str(path)==str(pyc) else data
            python_cache.install_lazy_checks(manifest,index,Loader)
            # The provider changes returned bytes without modifying the file:
            # checking the filesystem in advance alone would miss this.
            malicious=Loader();malicious.corrupt=True
            with self.assertRaises(ImportError):malicious.get_data(str(pyc))
            self.assertEqual(c.sha(pyc),manifest['cached_modules'][0]['cache']['sha256'])
            unknown=cache/'unknown.pyc';unknown.write_bytes(pyc.read_bytes())
            with self.assertRaises(ImportError):Loader().get_data(str(unknown))
            with self.assertRaises(OSError):Loader().get_data(str(cache/'missing.pyc'))

    def test_source_index_deduplicates_record_separator_aliases_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            dist=SimpleNamespace(files=['pkg.dist-info/RECORD','pkg.dist-info\\RECORD'],
                                 locate_file=lambda x:root/str(x).replace('\\','/'))
            self.assertEqual(python_cache.distribution_record_path(dist),root/'pkg.dist-info/RECORD')
            dist.files.append('other.dist-info/RECORD')
            with self.assertRaises(ValueError):python_cache.distribution_record_path(dist)

    def test_source_index_requires_one_hash_across_blank_and_hashed_source_aliases(self):
        import base64
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);record=root/'RECORD';digest=hashlib.sha256(b'actual').digest()
            encoded=base64.urlsafe_b64encode(digest).decode().rstrip('=')
            dist=SimpleNamespace(locate_file=lambda x:root/str(x).replace('\\','/'))
            record.write_text('pkg/a.py,,\npkg\\a.py,sha256='+encoded+',6\n')
            self.assertEqual(python_cache.distribution_source_hashes(record,dist,root),[(root/'pkg/a.py',digest.hex())])
            record.write_text('pkg/a.py,,\n')
            with self.assertRaises(ValueError):python_cache.distribution_source_hashes(record,dist,root)
            other=base64.urlsafe_b64encode(hashlib.sha256(b'wrong').digest()).decode().rstrip('=')
            record.write_text('pkg/a.py,sha256='+encoded+',6\npkg\\a.py,sha256='+other+',5\n')
            with self.assertRaises(ValueError):python_cache.distribution_source_hashes(record,dist,root)

    def test_lazy_guard_leaves_noncode_resources_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'module.py';source.write_text('x=1\n');cache=root/'cache';cache.mkdir();pyc=cache/'module.pyc'
            py_compile.compile(str(source),cfile=str(pyc),doraise=True)
            data=root/'resource.json';data.write_bytes(b'{"unchanged":true}')
            manifest={'contract':python_cache.CONTRACT,'status':'COMPLETE','python':c.pin(sys.executable),
                      'cache_tag':sys.implementation.cache_tag,'bytecode_magic':importlib.util.MAGIC_NUMBER.hex(),
                      'cache_root':str(cache),'cached_module_count':1,'cached_modules':[{'source':c.pin(source),'cache':c.pin(pyc)}]}
            index={'contract':python_cache.SOURCE_INDEX,'python':c.pin(sys.executable),'sources':[{'source':c.pin(source)}]}
            class Loader:
                def get_data(self,path):return Path(path).read_bytes()
            observed=python_cache.install_lazy_checks(manifest,index,Loader)
            self.assertEqual(Loader().get_data(str(data)),b'{"unchanged":true}')
            self.assertEqual(observed['noncode_resource_reads'],1)

if __name__=='__main__':unittest.main()
