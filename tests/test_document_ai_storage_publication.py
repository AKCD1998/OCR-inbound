"""Model-free V6 source/config tests. No document data, SDK, Torch, or HQ jobs."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

MODULES=Path(__file__).resolve().parents[1]/'experiments/document_ai'
sys.path.insert(0,str(MODULES))
import component_common as c
import storage_arm_publication as factory


class StoragePublication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.counter=0
        self.code={name:self.put({'source':name}) for name in factory.CODE_NAMES}
        self.base={'component':'docling','pins':{'reference':self.put({'frozen':'reference'})},'dependencies':[],
          'expected_scope':{'pages':484,'product_present':585,'prior_exact':323},'lifecycle_equivalence':self.put({'old':'e349'}),
          'selected_fresh_worker_sha256':'f'*64}
        self.approval=self.put({'root':'new-explicit-implementation'})
        self.arm={k:self.put({'source':k}) for k in ('original_source','variant_source','implementation_helper')}
        self.native=self.put({'source':'base129'})
        self.profile=factory.profile_value(self.base,'D:/OCR-Experiments/new-V6',self.code,self.approval,self.arm,self.native)
        selected=self.profile['selected_tableformer_implementation'];selected['runtime_cache']=self.put({'cache':'084'})
        self.proof={'contract':'document-ai-actual-tableformer-implementation.v1','arm_receipt':self.approval,
          'actual_module_file':self.arm['variant_source'],'original_source':self.arm['original_source'],'actual_load_count':1,
          'loader':'exact-module-verified-source-no-pyc','original_sdk_modified':False,'vanilla_sdk_claimed':False,
          'cache_guard_for_other_modules_modified':False}
        self.summary={'status':'COMPLETE','component':'docling','stage':'tables','worker':self.code['docling_storage_worker.py'],
          'native_base_worker':self.native,'native_implementation_arm':self.approval,'runtime_cache':selected['runtime_cache'],
          'implementation_selected':True,'implementation_applied':True,'vanilla_sdk_claimed':False,
          'actual_tableformer_implementation':self.put(self.proof),'plan':self.put({'mode':'full','pages':484})}

    def put(self,value):
        self.counter+=1;p=self.root/(str(self.counter)+'.json');c.save(p,value);return c.pin(p)

    def test_v6_preserves_metric_assets_and_removes_old_family_without_relabelling(self):
        self.assertEqual(160,self.profile['tiny_page'])
        self.assertNotIn('lifecycle_equivalence',self.profile);self.assertNotIn('selected_fresh_worker_sha256',self.profile)
        self.assertEqual(self.base['pins']['reference'],self.profile['pins']['reference'])
        self.assertEqual(self.base['expected_scope'],self.profile['expected_scope'])
        self.assertIn('lifecycle_equivalence',self.base)
        selected=self.profile['selected_tableformer_implementation']
        self.assertEqual((484,484,0,0),tuple(selected[k] for k in ('all_fresh_layout_pages','all_fresh_table_pages','retained_layout_pages','retained_table_pages')))
        self.assertEqual(self.approval,self.profile['pins']['selected_implementation:arm_receipt'])

    def test_actual_selected_implementation_origin_and_every_pin_must_match(self):
        self.assertEqual(self.proof,factory.validate_selected(self.summary,self.profile))
        for field,value in (('native_implementation_arm',self.put({'wrong':'arm'})),('native_base_worker',self.put({'wrong':'base'})),
                            ('implementation_applied',False),('runtime_cache',self.put({'wrong':'cache'})),('vanilla_sdk_claimed',True)):
            bad=deepcopy(self.summary);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):factory.validate_selected(bad,self.profile)
        for field,value in (('actual_module_file',self.arm['original_source']),('actual_load_count',2),('actual_load_count',True),
                            ('cache_guard_for_other_modules_modified',True),('loader','ordinary unguarded source loader')):
            proof=deepcopy(self.proof);proof[field]=value;bad=deepcopy(self.summary);bad['actual_tableformer_implementation']=self.put(proof)
            with self.subTest(field=field),self.assertRaises(ValueError):factory.validate_selected(bad,self.profile)

    def test_actual_wrapper_copy_keeps_its_own_path_and_same_bytes(self):
        source=Path(self.code['docling_storage_worker.py']['path']);copy=self.root/'actual-task-wrapper.py';copy.write_bytes(source.read_bytes())
        value=deepcopy(self.summary);value['worker']=c.pin(copy)
        factory.validate_selected(value,self.profile)
        self.assertEqual(str(copy),value['worker']['path'])
        copy.write_bytes(b'changed wrapper')
        with self.assertRaises(ValueError):factory.validate_selected(value,self.profile)

    def canary(self):
        selected=self.profile['selected_tableformer_implementation'];p=self.summary['plan']
        return {'resource_policy':deepcopy(c.RESOURCES),'ordinary_external_processes':[],
          'pins':{'controller':self.put({'controller':'07b'}),'ownership':self.put({'ownership':'620'}),
                  'python':self.put({'python':'runtime'}),'lifecycle_equivalence':self.base['lifecycle_equivalence']},
          'steps':[{'id':'tables160','component':'docling','optimizer_updates_allowed':False,
            'worker':deepcopy(self.summary['worker']),'args':['--stage','tables','--output','old-canary','--slice-start','159',
              '--slice-count','1','--plan',p['path'],'--plan-sha256',p['sha256'],'--runtime-cache-manifest',selected['runtime_cache']['path'],
              '--runtime-cache-manifest-sha256',selected['runtime_cache']['sha256'],'--native-cell-matching','disabled',
              '--table-cpu-backend','aten','--upstream-layout-summary','old160','--upstream-layout-summary-sha256','a'*64,
              '--upstream-resource','old160resource','--upstream-resource-sha256','b'*64,'--execute'],
             'input_pins':[self.base['lifecycle_equivalence']]}]}

    def test_all_fresh_full_config_is16_children_with_actual_new_source_and_no_old_geometry(self):
        canary=self.canary();before=deepcopy(canary)
        result=factory.full_config(canary,self.code,self.put(self.profile),self.profile,self.put(self.summary),self.summary,
          self.put({'actual':'closed canary'}),self.put({'actual':'new tiny'}),self.put({'actual':'new score'}),
          'D:/OCR-Experiments/newTask','D:/OCR-Experiments/new-full-output')
        self.assertEqual(16,result['expected_fresh_model_stage_children']);self.assertEqual([],result['retained_layout_shards'])
        self.assertEqual([],result['retained_table_shards']);self.assertNotIn('lifecycle_equivalence',result)
        self.assertNotIn('lifecycle_equivalence',result['pins']);self.assertEqual(before,canary)
        args=result['steps'][0]['args']
        self.assertNotIn('--upstream-layout-summary',args);self.assertNotIn('--upstream-resource',args)
        self.assertEqual('layout',args[args.index('--stage')+1]);self.assertEqual('64',args[args.index('--slice-count')+1])
        self.assertEqual(self.approval['path'],args[args.index('--implementation-arm')+1])
        self.assertEqual(self.native['path'],args[args.index('--base-worker')+1])
        self.assertEqual(self.code['docling_storage_worker.py']['sha256'],result['steps'][0]['worker']['sha256'])
        self.assertEqual(43200,result['maximum_total_seconds']);self.assertEqual(2400,result['steps'][0]['maximum_seconds'])

    def test_full_refuses_wrong_parent_duplicate_template_and_missing_execute(self):
        for scenario in ('plan','duplicate','execute'):
            canary=self.canary()
            if scenario=='plan':canary['steps'][0]['args'][canary['steps'][0]['args'].index('--plan-sha256')+1]='0'*64
            elif scenario=='duplicate':canary['steps'].append(deepcopy(canary['steps'][0]))
            else:canary['steps'][0]['args'].remove('--execute')
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):
                factory.full_config(canary,self.code,self.put(self.profile),self.profile,self.put(self.summary),self.summary,
                  self.put({}),self.put({}),self.put({}),'D:/OCR-Experiments/task','D:/OCR-Experiments/output')

    def test_full_cache_argument_preserves_actual_positive_pin_spelling(self):
        positive=deepcopy(self.summary)
        positive['runtime_cache']['path']=positive['runtime_cache']['path'].replace('\\','/')
        original=deepcopy(self.profile)
        result=factory.full_config(self.canary(),self.code,self.put(self.profile),self.profile,self.put(positive),positive,
          self.put({}),self.put({}),self.put({}),'D:/OCR-Experiments/task','D:/OCR-Experiments/output')
        args=result['steps'][0]['args']
        self.assertEqual(positive['runtime_cache']['path'],args[args.index('--runtime-cache-manifest')+1])
        self.assertEqual(original,self.profile)

    def test_tiny_configuration_has_only_three_pure_steps_and_no_old_approval(self):
        pp=self.put(self.profile)
        plan={'scope':'tiny','source_profile':pp,'steps':[{'id':name,'component':'endpoint-eval','optimizer_updates_allowed':False,
              'maximum_seconds':600,'worker':{'path':'deployed1538.py','sha256':'1538e7b5ba42cf178c24b70abf6081c5c39d02161afce2fe44b5802ef39eb5f9'}} for name in ('control','candidate','paired_score')],
              'required_supervisor_output_root':'D:/OCR-Experiments/new-V6/tiny'}
        value=factory.tiny_configuration(plan,self.canary(),pp,'D:/OCR-Experiments/new-tiny-Task')
        self.assertEqual(2100,value['maximum_total_seconds']);self.assertNotIn('lifecycle_equivalence',value['pins'])
        self.assertTrue(value['source']['path'].endswith('serial.py'))
        plan['steps'].pop()
        with self.assertRaises(ValueError):factory.tiny_configuration(plan,self.canary(),pp,'D:/OCR-Experiments/task')


if __name__=='__main__':unittest.main()
