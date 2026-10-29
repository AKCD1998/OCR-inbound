"""Pure factory checks catch source closure/path identity errors before full484."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import full900_publication as factory


class FullPublication(unittest.TestCase):
    def values(self):
        pin=lambda name:{'path':'D:/exact/'+name,'sha256':name}
        source={name:pin(name) for name in factory.FILES};source['docling_full_driver.py']['sha256']=factory.FULL_SHA;source['docling_stage_worker.py']['sha256']=factory.VARIANT_SHA
        profilepin={'path':'D:/exact/profile.json','sha256':factory.PROFILE_SHA}
        lifecycle={'path':'D:/preserve/forward/ROOT_APPROVAL.json','sha256':factory.RECEIPT_SHA}
        positive={'worker':{'sha256':factory.VARIANT_SHA},'runtime_cache':{'path':'D:/exact/cache.json','sha256':factory.CACHE_SHA}}
        retained={'slice_start':0,'slice_count':64,'summary':pin('old-b1d-summary'),'resource':pin('old-b1d-resource'),'closed_source_supervision':pin('old-failed-parent')}
        approval={'original_worker':pin('b1d'),'variant_worker':pin('129'),'verifier':pin('87ec')}
        base={'pins':{},'actual_positive_table_summary':pin('old-positive'),'actual_closed_table_canary':pin('old-positive-parent'),
              'retained_layout_shards':[{'summary':pin('original-960-layout')}],
              'steps':[{'args':['--output','old','--runtime-cache-manifest','old','--runtime-cache-manifest-sha256','old'],
                        'input_pins':[pin('old-positive'),pin('old-positive-parent'),{'path':'D:/old/CACHE_MANIFEST.json','sha256':'old'}]}]}
        return [base,source,profilepin,{'lifecycle_equivalence':lifecycle},pin('new-positive'),positive,pin('new-closed'),pin('new-tiny'),pin('new-score'),approval,retained]

    def test_exact_profile_and_lifecycle_dicts_preserved_with_all17_fresh_sources(self):
        values=self.values();result=factory.make_config(*values)
        self.assertEqual(result['lifecycle_equivalence'],values[3]['lifecycle_equivalence'])
        self.assertEqual(result['pins']['lifecycle_equivalence'],values[3]['lifecycle_equivalence'])
        self.assertEqual(result['endpoint_profile'],values[2]);self.assertEqual(result['pins']['endpoint_profile'],values[2])
        self.assertEqual(result['retained_layout_shards'],values[0]['retained_layout_shards']);self.assertEqual(result['retained_table_shards'],[values[-1]])
        self.assertEqual(result['expected_fresh_model_stage_children'],14)
        self.assertEqual(result['steps'][0]['worker']['sha256'],factory.VARIANT_SHA)
        self.assertFalse(any(r['sha256']=='old' or r['sha256']=='old-positive' for r in result['steps'][0]['input_pins']))
        self.assertTrue(any(r['sha256']=='eval_runner.py' for r in result['pins'].values()))

    def test_missing_bytecode_or_eval_import_source_is_refused_before_publication(self):
        for name in ('bytecode_bundle.py','eval_runner.py','eval_assets.py','eval_lifecycle.py'):
            values=self.values();values[1].pop(name)
            with self.assertRaises(ValueError):factory.make_config(*values)

    def test_old_worker_profile_or_cache_cannot_be_reused_as_fresh900(self):
        for mutation in ('worker','profile','cache'):
            values=self.values()
            if mutation=='worker':values[5]['worker']['sha256']='b1d'
            elif mutation=='profile':values[2]['sha256']='old-V4'
            else:values[5]['runtime_cache']['sha256']='417-old'
            with self.assertRaises(ValueError):factory.make_config(*values)


if __name__=='__main__':unittest.main()
