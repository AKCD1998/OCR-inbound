"""Synthetic source/closure wiring, not recognition or native model tests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import eval_lifecycle as life
import eval_merge as merge
import eval_native as native
import eval_runner as runner
import docling_post_eval as post
import docling_full_driver as full
from eval_geometry import digest
from tests import test_document_ai_eval_interfaces as interfaces
from tests import test_document_ai_post_eval as post_tests

class LifecycleBridgeIntegration(unittest.TestCase):
    def setup_union(self):
        f=interfaces.SplitStages();f.setUp();d=f.data
        shards=[f.stages(start,min(64,484-start))[0] for start in range(0,484,64)]
        old=d.read(shards[0]['path']);newworker=d.put({'synthetic':'different new900 source'},'new-worker')
        selectedcache=d.put({'synthetic':'selected084 delivery'},'selected-cache')
        approval_pin=d.put({'synthetic':'approval already tested by source-verifier tests'},'approval')
        approval=life.Approval(approval_pin,{'original_worker':old['worker'],'variant_worker':newworker,
           'retained_table':{'summary':shards[0],'selected_pages':list(range(1,65))},
           'model_recipe':life.raw_recipe(old),'delivery_provenance':{'selected_runtime_cache':selectedcache}},'f'*64,d.check)
        for i in range(1,len(shards)):
            value=d.read(shards[i]['path']);value.update(worker=newworker,runtime_cache=selectedcache)
            shards[i]=d.put(value,'fresh900-table-summary')
        supervision=d.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,
                           'resources':[interfaces.closed(s) for s in shards]},'actual-source-witness')
        return f,shards,supervision,approval

    def test_v5_union_preserves_actual_sources_and_caches_with_exact64_old420_fresh(self):
        f,shards,witness,approval=self.setup_union();d=f.data
        before=d.read(shards[0]['path'])
        with d.context(),patch.object(life,'validate_approval',return_value=approval):
            result=merge.aggregate(shards,[witness],check=d.check,lifecycle_equivalence=approval.record)
            self.assertEqual(sorted([approval.data['original_worker']['sha256'],approval.data['variant_worker']['sha256']]),result['actual_worker_sha256s'])
            self.assertNotIn('worker_sha256',result)
            self.assertEqual(list(range(1,65)),result['retained_startup480_pages'])
            self.assertEqual(list(range(65,485)),result['fresh_startup900_pages'])
            self.assertEqual(before['worker'],result['actual_native_producers'][0]['actual_worker'])
            self.assertEqual(before,d.read(shards[0]['path']))
            self.assertFalse(result['original_producer_identities_relabelled'])
            profile={**f.profile(),'tiny_page':1,'lifecycle_equivalence':approval.record,
                     'selected_fresh_worker_sha256':approval.data['variant_worker']['sha256']}
            record=d.put(result,'actual-full-union')
            pages,_=runner.native_records(record,profile,'full484',d.check)
            self.assertEqual(484,len(pages));identity=native.model_identity(result)
            self.assertEqual(result['actual_worker_sha256s'],identity['actual_worker_sha256s'])
            self.assertEqual('f'*64,identity['model_recipe_family_sha256'])

    def test_mixed_sources_require_explicit_approval_and_all_fresh_cache_and_source_pins(self):
        for scenario in ('no_approval','unknown_worker','missing_fresh_cache','wrong_fresh_cache','all_fresh_no_retained'):
            with self.subTest(scenario=scenario):
                f,shards,witness,approval=self.setup_union();d=f.data
                if scenario!='no_approval':
                    i=0 if scenario=='all_fresh_no_retained' else 1
                    value=d.read(shards[i]['path'])
                    if scenario=='unknown_worker':value['worker']=d.put({'unapproved':'worker'},'unapproved')
                    elif scenario=='missing_fresh_cache':value['runtime_cache']=None
                    elif scenario=='wrong_fresh_cache':value['runtime_cache']=d.put({'unapproved':'cache'},'wrong-cache')
                    else:value.update(worker=approval.data['variant_worker'],runtime_cache=approval.data['delivery_provenance']['selected_runtime_cache'])
                    shards[i]=d.put(value,'bad-shard')
                    witness=d.put({'status':'COMPLETE','shared_lock_released_after_owned_closure':True,'resources':[interfaces.closed(s) for s in shards]},'bad-witness')
                with d.context(),patch.object(life,'validate_approval',return_value=approval),self.assertRaises(ValueError):
                    merge.aggregate(shards,[witness],check=d.check,lifecycle_equivalence=None if scenario=='no_approval' else approval.record)

    def test_old_tiny_cannot_authorize_new_family_but_new_tiny_can_authorize_mixed_full(self):
        f,shards,witness,approval=self.setup_union();d=f.data
        profile={**f.profile(),'tiny_page':1,'lifecycle_equivalence':approval.record,
                 'selected_fresh_worker_sha256':approval.data['variant_worker']['sha256']}
        with d.context(),patch.object(life,'validate_approval',return_value=approval):
            merged=merge.aggregate(shards,[witness],check=d.check,lifecycle_equivalence=approval.record)
            identity=native.model_identity(merged)
            def score_for(source):
                run=d.put({'native_summary':source},'tiny-run')
                done=d.put({'run_manifest':run},'tiny-complete')
                return d.put({'status':'COMPLETE','scope':'DIAGNOSTIC_TINY_NOT_FULL585','actual_scorer_invocations':2,
                    'profile_sha256':digest(profile),'component':'docling','writer_readback_verified':True,
                    'control_complete':done,'candidate_complete':done,'control_metrics':done,'candidate_metrics':done},'tiny-score')
            with self.assertRaises(ValueError):runner.tiny_gate(profile,score_for(shards[0]),d.check,identity)
            runner.tiny_gate(profile,score_for(shards[1]),d.check,identity)
            bad={**identity,'actual_worker_sha256s':[approval.data['variant_worker']['sha256']]}
            with self.assertRaises(ValueError):runner.tiny_gate(profile,score_for(shards[1]),d.check,bad)

    def test_post_evaluation_accepts_only_exact_retained_entry_without_rewriting_its_worker(self):
        f=post_tests.PostEvaluationGates();f.setUp()
        try:
            result,config=f.native(retained=True,retain_table=True)
            entry=config['retained_table_shards'][0]
            old=f.items['origin-table'];old['worker']={'path':'actual-old-b1d','sha256':'b'*64}
            new=f.items['tables_001'];selected={'path':'selected084','sha256':'8'*64}
            for value in f.items.values():
                if isinstance(value,dict) and value.get('worker',{}).get('sha256')==f.c['expected_table_worker_sha256']:
                    value['runtime_cache']=selected
            # The retained receipt is original evidence, so bind its actual old worker.
            receipt=str(Path(f.c['native_result_path']).resolve().parent/'tables_000.RETAINED.json')
            f.items[receipt]['origin_worker']=deepcopy(old['worker'])
            approval_record={'path':'approval','sha256':'a'*64}
            approval=life.Approval(approval_record,{'original_worker':old['worker'],'variant_worker':new['worker'],
                'retained_table':{**entry,'selected_pages':list(range(1,65))},'model_recipe':life.raw_recipe(old),
                'delivery_provenance':{'selected_runtime_cache':selected}},'f'*64,f.check)
            f.c['lifecycle_equivalence']=approval_record;config['lifecycle_equivalence']=approval_record
            with patch.object(post,'read',f.read),patch.object(life,'validate_approval',return_value=approval):
                tables=post.native_tables(f.c,result,config,f.check)
                self.assertEqual(entry['summary'],tables[0]);self.assertEqual('b'*64,old['worker']['sha256'])
                bad=deepcopy(config);bad['retained_table_shards'][0]['closed_source_supervision']={'path':'other-root','sha256':'a'*64}
                with self.assertRaises((ValueError,KeyError)):post.native_tables(f.c,result,bad,f.check)
        finally:f.doCleanups()

    def test_full_native_requires_new_tiny_profile_and_exact_positive900_source(self):
        f,shards,witness,approval=self.setup_union();d=f.data
        profile={**f.profile(),'tiny_page':1,'lifecycle_equivalence':approval.record,
                 'selected_fresh_worker_sha256':approval.data['variant_worker']['sha256']}
        profile_pin=d.put(profile,'profile');positive=shards[1]
        run=d.put({'profile':profile_pin,'native_summary':positive},'tiny-run')
        complete=d.put({'run_manifest':run},'tiny-complete')
        metrics=d.put({'synthetic':'paired result'},'metrics')
        score=d.put({'status':'COMPLETE','scope':'DIAGNOSTIC_TINY_NOT_FULL585','actual_scorer_invocations':2,
            'profile_sha256':digest(profile),'component':'docling','writer_readback_verified':True,
            'control_complete':complete,'candidate_complete':complete,'control_metrics':metrics,'candidate_metrics':metrics},'tiny-score')
        root=d.put({'resources':[{'worker_summary':complete},{'worker_summary':complete},{'worker_summary':score}]},'closed-tiny')
        config={'lifecycle_equivalence':approval.record,'endpoint_profile':profile_pin,
                'pins':{'lifecycle_equivalence':approval.record,'endpoint_profile':profile_pin},'actual_closed_endpoint_tiny':root}
        with d.context(),patch.object(full,'read',d.read),patch.object(full,'checked',d.check),patch.object(life,'validate_approval',return_value=approval):
            self.assertIs(approval,full.lifecycle_tiny(config,positive,d.read(positive['path']),d.check))
            with self.assertRaises(ValueError):full.lifecycle_tiny(config,shards[2],d.read(shards[2]['path']),d.check)
            with self.assertRaises(ValueError):full.lifecycle_tiny(config,shards[0],d.read(shards[0]['path']),d.check)
            with self.assertRaises(ValueError):full.lifecycle_tiny({**config,'endpoint_profile':metrics},positive,d.read(positive['path']),d.check)

if __name__=='__main__':unittest.main()
