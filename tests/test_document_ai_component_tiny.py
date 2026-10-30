"""Real pinned synthetic stage receipts, without models or invoice data."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import component_common as common
import correction_runner as runner


class ComponentTinyTests(unittest.TestCase):
    def test_quantity_only_policy_is_explicit_and_passed_to_the_source_verifier(self):
        import source_cell_association as cells
        spec={'active_components':['cell_association'],
              'sources':{'cell_association':common.pin(cells.__file__)}}
        legacy=runner.load_components(spec)
        self.assertNotIn('quantity_only_source_contexts',legacy)
        opted=runner.load_components({**spec,'quantity_only_source_contexts':True})
        self.assertTrue(opted['quantity_only_source_contexts'])
        self.assertIs(cells,opted['cell_association'])
        with self.assertRaises(ValueError):
            runner.load_components({'active_components':[],'sources':{},'quantity_only_source_contexts':True})

    def receipt(self,folder,mode=None):
        def put(name,value):
            common.save(folder/name,value)
            return common.pin(folder/name)
        experiment={'path':'source-only-experiment','sha256':'a'*64}
        worker={'path':'source-only-runner','sha256':'b'*64}
        panel={'path':'source-panel','sha256':'c'*64}
        spec={'sources':{'runner':worker},'panel':panel,'tiny_page':40,
              'requires_tiny_before_panel':True,'active_components':['cell_association']}
        children=[]
        for variant in ('control','candidate'):
            run={'experiment':experiment,'reference_access':False}
            if mode=='unexpected-fresh-manifest' and variant=='candidate':
                run['fresh_source_manifest']={'path':'unselected','sha256':'e'*64}
            run_pin=put(variant+'-run.json',run)
            done={'status':'COMPLETE','writer_readback_verified':True,'reference_access':False,
                  'scope':'tiny','variant':variant,'pages':1,'run_manifest':run_pin,
                  'source_inventory':[{'page_number':40}]}
            if variant=='candidate':
                if mode=='wrong-actual-page':done['source_inventory'][0]['page_number']=119
                if mode=='no-actual-page':done.pop('source_inventory')
                if mode=='failed-parser':done['status']='FAILED'
                if mode=='unverified-writer':done['writer_readback_verified']=False
                if mode=='parser-reference-access':done['reference_access']=True
            children.append(put(variant+'-complete.json',done))
        score={'status':'COMPLETE','scope':'CORRECTION_SOURCE_TINY','experiment':experiment,
               'panel':panel,'processed_images':1,'actual_scorer_invocations':2,
               'writer_readback_verified':True,'prior323_lost':0,
               'safety':{'exact_loss_count':0,'new_wrong_count_all602':0,'new_absence_falsefill_count':0},
               'control_complete':children[0],'candidate_complete':children[1]}
        score_pin=put('score.json',score)
        stages=['control','candidate','paired_score']
        config=put('serial.json',{'source':{'sha256':'87714bc07ea839a73115531e9358b2de0c17882a03d627a8353745fedf3c39d3'},
            'resource_policy':common.RESOURCES,'steps':[{'id':x,'worker':worker,'optimizer_updates_allowed':False} for x in stages]})
        resource={'actual_exit_code':0,'failure':None,'stop_reason':None,
                  'cleanup':{'confirmed_all_known_owned_exited':True},'logs_finalized_after_owned_cleanup':True,
                  'peak_owned_process_tree_RSS_bytes':1000,'minimum_free_RAM_bytes':2*1024**3,
                  'child_started':True,'worker_optimizer_updates_permission':False}
        closed={'status':'COMPLETE','failure':None,'cleanup':{'confirmed_all_known_owned_exited':True},
                'shared_lock_released_after_owned_closure':True,'config':config,
                'resources':[{**deepcopy(resource),'stage':stage,'worker_summary':pin}
                             for stage,pin in zip(stages,children+[score_pin])]}
        return experiment,spec,score_pin,put('closed.json',closed),score

    def test_cached_component_tiny_uses_real_receipts_without_a_fake_fresh_manifest(self):
        with tempfile.TemporaryDirectory() as name:
            experiment,spec,score,closed,expected=self.receipt(Path(name).resolve())
            self.assertNotIn('fresh_source_manifest',spec)
            self.assertEqual(expected,runner.tiny_gate(experiment,spec,score,closed))

    def test_other_actual_page_and_unselected_fresh_data_cannot_admit_the_panel(self):
        for mode in ('wrong-actual-page','no-actual-page','unexpected-fresh-manifest',
                     'failed-parser','unverified-writer','parser-reference-access'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as name:
                experiment,spec,score,closed,_=self.receipt(Path(name).resolve(),mode)
                with self.assertRaises(ValueError):runner.tiny_gate(experiment,spec,score,closed)

    def test_opted_in_component_panel_cannot_write_before_actual_tiny_completion(self):
        spec={'active_components':['cell_association'],'requires_tiny_before_panel':True,'tiny_page':40}
        context=(spec,{}, {},{40:'source'}, {},{})
        with patch.object(runner,'preflight',return_value=context),patch.object(runner,'outdir',side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(ValueError,'before38'):
                runner.parse({'path':'source','sha256':'a'*64},'panel','control','unused')


if __name__=='__main__':unittest.main()
