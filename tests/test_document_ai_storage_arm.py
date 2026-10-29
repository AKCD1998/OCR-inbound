"""Source/loader contracts only; no Torch, SDK, models, or document images."""
import ast
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

MODULES=Path(__file__).resolve().parents[1]/'experiments/document_ai'
sys.path.insert(0,str(MODULES))
import component_common as common
import docling_storage_worker as wrapper
import tableformer_storage_arm as arm
import tableformer_storage_probe as probe


FIXTURE=b'''# Synthetic source, never a production SDK implementation.
class TableModel04_rs:
    def predict(self, decoded, selector):
        tag_H_buf = []
        if selector:
            tag_H_buf.append(decoded[-1, :, :])
        else:
            tag_H_buf.append(decoded[-1, :, :])
        return tag_H_buf
'''


class IsolatedStorageArm(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.origin=self.root/'venv/Lib/site-packages/docling_ibm_models/tableformer/models/table04_rs/tablemodel04_rs.py'
        self.origin.parent.mkdir(parents=True);self.origin.write_bytes(FIXTURE)
        self.original=common.pin(self.origin)
        patcher=patch.object(arm,'ORIGIN_SHA',self.original['sha256']);patcher.start();self.addCleanup(patcher.stop)
        self.variant=self.root/'isolated/tablemodel04_rs.py';self.receipt=self.root/'isolated/ARM.json'

    def prepared(self,approve=True):
        record=arm.prepare(self.original,self.variant,self.receipt)
        if approve:
            data=common.read(self.receipt);data.update(status='ROOT_APPROVED_FOR_BOUNDED_TRIAL',approved_by='root')
            approved=self.root/'isolated/ROOT_APPROVAL.json';common.save(approved,data);record=common.pin(approved)
        return record

    def finder(self):return arm.ImplementationFinder(self.prepared())

    def load_fixture(self,finder):
        spec=finder.find_spec(arm.MODULE,[str(self.origin.parent)])
        module=importlib.util.module_from_spec(spec)
        self.assertNotIn(arm.MODULE,sys.modules)
        sys.modules[arm.MODULE]=module;self.addCleanup(sys.modules.pop,arm.MODULE,None)
        spec.loader.exec_module(module)
        return module

    def test_only_two_clone_insertions_and_normalized_full_ast(self):
        variant=arm.variant_bytes(FIXTURE);proof=arm.source_proof(FIXTURE,variant)
        self.assertEqual(FIXTURE.replace(b'decoded[-1, :, :]',b'decoded[-1, :, :].clone()'),variant)
        self.assertTrue(proof['all_other_bytes_identical']);self.assertTrue(proof['normalized_AST_identical'])
        self.assertEqual([6,8],proof['append_lines'])
        self.assertEqual('NOT_YET_MEASURED',proof['actual_model_output_equivalence'])
        self.assertEqual(len(FIXTURE)+16,len(variant))

    def test_extra_model_math_limit_or_clone_argument_change_rejected(self):
        valid=arm.variant_bytes(FIXTURE)
        for invalid in (valid+b'\nMAX_STEPS=512\n',valid.replace(b'.clone()',b'.clone(memory_format=None)',1),
                        valid.replace(b'return tag_H_buf',b'return tag_H_buf[:1]'),valid.replace(b'.clone()',b'.detach()',1)):
            with self.subTest(invalid=invalid[-60:]),self.assertRaises(ValueError):arm.source_proof(FIXTURE,invalid)
        for source in (FIXTURE.replace(b'[-1, :, :]',b'[0, :, :]',1),FIXTURE.replace(b'return tag_H_buf',b'tag_H_buf.append(decoded[-1, :, :])\n        return tag_H_buf')):
            with self.assertRaises(ValueError):arm.variant_bytes(source)

    def test_prepare_preserves_original_and_requires_explicit_root_approval(self):
        record=self.prepared(False)
        self.assertEqual(FIXTURE,self.origin.read_bytes());self.assertEqual(self.original,common.pin(self.origin))
        with self.assertRaises(ValueError):arm.validate_arm(record)
        self.assertFalse(arm.validate_arm(record,require_approval=False)['original_sdk_modified'])
        with self.assertRaises(ValueError):arm.prepare(self.original,self.variant,self.receipt)

    def test_no_write_anywhere_inside_original_sdk_environment(self):
        for variant,receipt in ((self.root/'venv/elsewhere/variant.py',self.receipt),
                                (self.variant,self.root/'venv/new/approval.json'),
                                (self.variant,self.variant)):
            with self.subTest(variant=variant,receipt=receipt),self.assertRaises(ValueError):
                arm.prepare(self.original,variant,receipt)
        self.assertFalse(self.variant.exists());self.assertEqual(FIXTURE,self.origin.read_bytes())

    def test_validation_rejects_receipt_moved_into_installed_environment(self):
        record=self.prepared();inside=self.root/'venv/moved-approval.json'
        common.save(inside,common.read(record['path']))
        with self.assertRaises(ValueError):arm.validate_arm(common.pin(inside))

    def test_original_variant_and_helper_tampering_are_rejected(self):
        record=self.prepared()
        self.variant.write_bytes(self.variant.read_bytes()+b'\n# tampered\n')
        with self.assertRaises(ValueError):arm.validate_arm(record)
        self.variant.write_bytes(arm.variant_bytes(FIXTURE));self.origin.write_bytes(FIXTURE+b'\n')
        with self.assertRaises(ValueError):arm.validate_arm(record)
        self.origin.write_bytes(FIXTURE);data=common.read(record['path']);data['implementation_helper']=self.original
        bad=self.root/'wrong-helper.json';common.save(bad,data)
        with self.assertRaises(ValueError):arm.validate_arm(common.pin(bad))

    def test_wrong_module_reload_and_ambiguous_parent_paths_are_rejected(self):
        finder=self.finder()
        self.assertIsNone(finder.find_spec('another.module',[str(self.origin.parent)]))
        for path in (None,[str(self.root)],[str(self.origin.parent),str(self.root)]):
            with self.assertRaises(ImportError):finder.find_spec(arm.MODULE,path)
        with self.assertRaises(ImportError):finder.find_spec(arm.MODULE,[str(self.origin.parent)],target=object())
        loader=arm._SourceLoader(arm.MODULE,self.variant,finder)
        with self.assertRaises(ImportError):loader.get_code('another.module')
        with self.assertRaises(ImportError):loader.exec_module(types.ModuleType('another.module'))
        loader.path=str(self.origin)
        with self.assertRaises(ImportError):loader.get_code(arm.MODULE)

    def test_preloaded_module_or_duplicate_finder_rejected(self):
        record=self.prepared()
        with patch.dict(sys.modules,{arm.MODULE:types.ModuleType(arm.MODULE)}),self.assertRaises(ValueError):arm.install(record)
        finder=arm.install(record);self.addCleanup(sys.meta_path.remove,finder)
        with self.assertRaises(ValueError):arm.install(record)

    def test_exact_custom_loader_preserves_guard_for_every_other_module(self):
        finder=self.finder();guard_error=ImportError('simulated084guard: source is not in cache manifest')
        with patch.object(importlib.machinery.SourceFileLoader,'get_code',side_effect=guard_error) as guarded:
            module=self.load_fixture(finder)
            self.assertEqual(arm.MODULE,module.__name__)
            self.assertEqual(0,guarded.call_count)
            ordinary=importlib.machinery.SourceFileLoader('ordinary',str(self.origin))
            with self.assertRaises(ImportError) as error:ordinary.get_code('ordinary')
            self.assertIs(error.exception,guard_error);self.assertEqual(1,guarded.call_count)
        self.assertFalse((self.variant.parent/'__pycache__').exists())
        observation=finder.observation()
        self.assertEqual(common.pin(self.variant),observation['actual_module_file'])
        self.assertEqual(self.original,observation['original_source'])
        self.assertFalse(observation['cache_guard_for_other_modules_modified'])

    def test_final_compiled_buffer_hash_rejects_check_read_race(self):
        finder=self.finder();loader=arm._SourceLoader(arm.MODULE,self.variant,finder)
        # The last bytes read after all metadata checks still need their own pin.
        with patch.object(arm,'validate_arm',return_value=finder.data),patch.object(Path,'read_bytes',return_value=b'EXECUTED_UNPINNED=True\n'):
            with self.assertRaisesRegex(ImportError,'Actual compiled implementation buffer differs'):loader.get_code(arm.MODULE)

    def test_actual_module_origin_loader_and_single_load_proof_required(self):
        finder=self.finder()
        with self.assertRaises(ValueError):finder.observation()
        module=self.load_fixture(finder);good=module.__loader__
        module.__loader__=object()
        with self.assertRaises(ValueError):finder.observation()
        module.__loader__=good;module.__file__=str(self.origin)
        with self.assertRaises(ValueError):finder.observation()
        module.__file__=str(self.variant);finder.loaded=2
        with self.assertRaises(ValueError):finder.observation()

    def test_native_delegate_keeps_real_admission_but_actual_wrapper_identity(self):
        # Source import only. None of native execute/main/model constructors run.
        base=common.pin(MODULES/'docling_stage_worker.py')
        with patch.object(wrapper,'BASE_WORKER_SHA',base['sha256']):namespace=wrapper.delegate_namespace(base,wrapper.__file__)
        self.assertIs(namespace['verify_admission'],common.verify_admission)
        self.assertEqual(str(Path(wrapper.__file__).resolve()),namespace['execute'].__globals__['__file__'])
        self.assertEqual(common.pin(wrapper.__file__),namespace['pin'](namespace['__file__']))
        self.assertNotEqual(base['sha256'],namespace['pin'](namespace['__file__'])['sha256'])
        tree=ast.parse((MODULES/'docling_stage_worker.py').read_bytes())
        execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute')
        call=execute.body[0].value
        self.assertEqual('verify_admission',call.func.id);self.assertEqual('__file__',call.args[2].id)
        with self.assertRaises(ValueError):wrapper.delegate_namespace(base,wrapper.__file__)

    def test_real_native_admission_rejects_lease_for_base_instead_of_wrapper(self):
        base=common.pin(MODULES/'docling_stage_worker.py')
        with patch.object(wrapper,'BASE_WORKER_SHA',base['sha256']):namespace=wrapper.delegate_namespace(base,wrapper.__file__)
        lease=self.root/'base-worker-admission.json'
        common.save(lease,{'contract':'root-HQ-document-ai-admission.v1','approved_by':'root','component':'docling',
            'resource_policy':common.RESOURCES,'production_activation_allowed':False,'optimizer_updates_allowed':False,
            'worker':base,'controller_sha256':common.CONTROLLER_SHA256,'shared_lock_held':True})
        args=types.SimpleNamespace(admission=lease,admission_sha256=common.sha(lease))
        # Only machine identity is synthetic. The original verify_admission and
        # native execute run their real worker-pin comparison before psutil/ML.
        with patch.object(common,'require_HQ'),self.assertRaisesRegex(ValueError,'Worker/shared07b admission differs'):
            namespace['execute'](args,None,None,None)

    def test_import_origin_receipt_is_written_before_any_prediction_or_summary(self):
        finder=self.finder();output=self.root/'actual-table-stage'
        writer=wrapper.ProvenanceWriter(common.save,self.original,'tables',output,finder.record,finder)
        worker=common.pin(wrapper.__file__)
        writer(output/'STARTED.json',{'worker':worker,'stage':'tables'})
        started=common.read(output/'STARTED.json')
        self.assertTrue(started['implementation_selected']);self.assertFalse(started['implementation_applied'])
        self.load_fixture(finder)
        actual=output/'ACTUAL_TABLEFORMER_IMPLEMENTATION.json'
        self.assertTrue(actual.is_file());self.assertFalse((output/'SUMMARY.json').exists())
        self.assertEqual(common.pin(self.variant),common.read(actual)['actual_module_file'])
        # The source receipt survives an inference failure without claiming a
        # successful model result. No real model was called by this fixture.
        with self.assertRaises(RuntimeError):raise RuntimeError('synthetic prediction failed after import')
        self.assertTrue(actual.is_file());self.assertFalse((output/'SUMMARY.json').exists())
        value={'worker':worker,'stage':'tables','cell_association':{'cells':[{'raw_text':'SYNTHETIC'}]}}
        writer(output/'SUMMARY.json',value);summary=common.read(output/'SUMMARY.json')
        self.assertEqual(value['worker'],summary['worker']);self.assertEqual(value['cell_association'],summary['cell_association'])
        self.assertTrue(summary['implementation_applied']);self.assertEqual(common.pin(actual),summary['actual_tableformer_implementation'])
        self.assertEqual(self.original,summary['native_base_worker'])

    def test_provenance_output_bound_and_missing_import_cannot_attest_success(self):
        finder=self.finder();output=self.root/'stage'
        writer=wrapper.ProvenanceWriter(common.save,self.original,'tables',output,finder.record,finder)
        with self.assertRaises(ValueError):writer.record_import()
        with self.assertRaises(ValueError):writer(self.root/'outside/STARTED.json',{})
        self.assertFalse((self.root/'outside').exists())
        with self.assertRaises(ValueError):writer(output/'SUMMARY.json',{})
        writer(output/'STARTED.json',{})
        with self.assertRaises(ValueError):writer(output/'SUMMARY.json',{})
        with self.assertRaises(ValueError):writer(output/'STARTED.json',{})
        self.load_fixture(finder)
        with self.assertRaises(ValueError):writer.record_import()
        (output/'ACTUAL_TABLEFORMER_IMPLEMENTATION.json').write_text('{}',encoding='utf8')
        with self.assertRaises(ValueError):writer(output/'SUMMARY.json',{})

    def test_layout_neither_requires_nor_installs_variant_and_records_applied_false(self):
        output=self.root/'layout';namespace={'save':common.save}
        def native_main():
            for name in ('STARTED.json','SUMMARY.json'):
                namespace['save'](output/name,{'worker':common.pin(wrapper.__file__),'stage':'layout','regions':[]})
        namespace['main']=native_main
        argv=[wrapper.__file__,'--base-worker','pinned-native129.py','--base-worker-sha256',arm.BASE_WORKER_SHA,
              '--stage','layout','--output',str(output)]
        with patch.object(sys,'argv',argv),patch.object(wrapper,'require_HQ'),patch.object(wrapper,'delegate_namespace',return_value=namespace),\
             patch.object(wrapper,'validate_arm',side_effect=AssertionError('layout cannot require clone proof')),\
             patch.object(wrapper,'install',side_effect=AssertionError('layout cannot install a variant')):
            wrapper.main()
        summary=common.read(output/'SUMMARY.json')
        self.assertFalse(summary['implementation_selected']);self.assertFalse(summary['implementation_applied'])
        self.assertIsNone(summary['native_implementation_arm']);self.assertNotIn('actual_tableformer_implementation',summary)
        self.assertEqual([],summary['regions']);self.assertFalse((output/'ACTUAL_TABLEFORMER_IMPLEMENTATION.json').exists())

    def test_stage_ambiguity_and_table_without_arm_are_rejected(self):
        for args in ([],['--stage'],['--stage','tables'],['--stage','tables','--output'],
                     ['--stage','layout','--stage','tables','--output','elsewhere'],['--stage','unknown','--output','elsewhere']):
            with self.assertRaises(ValueError):wrapper.stage_output(args)
        with self.assertRaises(ValueError):wrapper.ProvenanceWriter(common.save,self.original,'layout',self.root,arm={})
        argv=[wrapper.__file__,'--base-worker','pinned-native129.py','--base-worker-sha256',arm.BASE_WORKER_SHA,
              '--stage','tables','--output',str(self.root/'tables-no-arm')]
        with patch.object(sys,'argv',argv),patch.object(wrapper,'require_HQ'),patch.object(wrapper,'delegate_namespace',return_value={}),\
             self.assertRaisesRegex(ValueError,'Root-approved table implementation arm required'):
            wrapper.main()

    def test_probe_bounds_and_no_model_or_rng_operations_in_source(self):
        for steps in (True,1,65,-1):
            with self.assertRaises(ValueError):probe.storage_probe(object(),steps)
        with self.assertRaises(ValueError):probe.storage_probe(object(),64,1024)
        source=Path(probe.__file__).read_bytes();tree=ast.parse(source)
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        self.assertIn('torch',imports)
        self.assertFalse(any(n.startswith(('docling_ibm_models','transformers','PIL','cv2')) for n in imports if n))
        forbidden={'rand','randn','randint','manual_seed','seed','load','load_state_dict','optim','backward'}
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in forbidden for n in ast.walk(tree)))
        self.assertNotIn('torch',sys.modules)


if __name__=='__main__':unittest.main()
