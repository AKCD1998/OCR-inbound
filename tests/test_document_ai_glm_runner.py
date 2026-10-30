"""GLM runtime source continuity under unchanged parser/scorer supervision."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import component_common as c
import correction_runner as runner
import glm_read_manifest as loader
from tests import test_document_ai_component_tiny as tiny_tests


class GlmRunner(unittest.TestCase):
    def test_explicit_loader_source_and_no_implicit_dynamic_reads(self):
        spec={'active_components':['glm_ocr'],'sources':{'glm_loader':c.pin(loader.__file__)}}
        self.assertIs(loader,runner.load_glm_loader(spec))
        with self.assertRaises(ValueError):runner.load_glm_reads(spec,None,{3})
        with self.assertRaises(ValueError):runner.load_glm_reads({'active_components':[]},{'path':'unselected','sha256':'a'*64},{3})
        with patch.dict(sys.modules,{'glm_read_manifest':types.SimpleNamespace(__file__='unapproved.py')}):
            with self.assertRaises(ValueError):runner.load_glm_loader(spec)

    def tiny(self,folder,mode=None):
        experiment,spec,score_pin,closed_pin,score=tiny_tests.ComponentTinyTests().receipt(folder)
        old_reads={'path':'actually-closed-canary-manifest','sha256':'d'*64}
        recipe={'selected':'same immutable source recipe'}
        records={'40':{'request_id':'source40','observation':{'path':'actual','sha256':'a'*64}}}
        spec.update(active_components=['glm_ocr'],glm_recipe=recipe)
        spec['sources']['glm_loader']=c.pin(loader.__file__)
        child_pins=[]
        for i,key in enumerate(('control_complete','candidate_complete')):
            done=c.read(c.checked(score[key]));run=c.read(c.checked(done['run_manifest']));run.update(glm_reads=old_reads,glm_recipe=recipe,glm_request_records=records)
            if mode=='different-parser-record' and i==1:run['glm_request_records']={'40':{'request_id':'replacement'}}
            rp=folder/('glm-'+str(i)+'-run.json');c.save(rp,run);done['run_manifest']=c.pin(rp)
            dp=folder/('glm-'+str(i)+'-done.json');c.save(dp,done);child_pins.append(c.pin(dp));score[key]=child_pins[-1]
        score.update(glm_reads=old_reads,glm_recipe=recipe,glm_request_records=records)
        sp=folder/'glm-score.json';c.save(sp,score);sp=c.pin(sp)
        closed=c.read(c.checked(closed_pin))
        for r,p in zip(closed['resources'],child_pins+[sp]):r['worker_summary']=p
        cp=folder/'glm-closed.json';c.save(cp,closed)
        return experiment,spec,sp,c.pin(cp),score,records

    def test_canary_to_panel_allows_grown_manifest_but_never_replaces_old_read(self):
        with tempfile.TemporaryDirectory() as name:
            e,s,score,closed,expected,records=self.tiny(Path(name).resolve())
            current={'manifest':{'path':'new38-manifest','sha256':'e'*64},'request_records':{**records,'41':{'request_id':'new-source41'}}}
            self.assertEqual(expected,runner.tiny_gate(e,s,score,closed,glm_runtime=current))
            current['request_records']['40']={'request_id':'reread-even-if-same-text'}
            with self.assertRaises(ValueError):runner.tiny_gate(e,s,score,closed,glm_runtime=current)

    def test_parser_pair_cannot_mix_canary_glm_records(self):
        with tempfile.TemporaryDirectory() as name:
            e,s,score,closed,_,records=self.tiny(Path(name).resolve(),'different-parser-record')
            with self.assertRaises(ValueError):runner.tiny_gate(e,s,score,closed,glm_runtime={'request_records':records})

    def test_glm_parse_requires_read_closure_before_any_output_or_model_call(self):
        spec={'active_components':['glm_ocr'],'requires_tiny_before_panel':True,'tiny_page':3,'sources':{}}
        with patch.object(runner,'preflight',return_value=(spec,{}, {},{3:'source'}, {},{})),patch.object(runner,'outdir',side_effect=AssertionError('must not write')):
            with self.assertRaises(ValueError):runner.parse({'path':'source','sha256':'a'*64},'tiny','control','unused')

    def test_reporting_does_not_claim_no_VLM_use_across_the_combined_pipeline(self):
        runtime={'manifest':{'path':'closed-source','sha256':'a'*64},'recipe':{},'records':{3:{}},'request_records':{'3':{}}}
        report=runner.glm_reporting(runtime)
        self.assertEqual(1,report['upstream_automated_GLM_source_calls'])
        self.assertEqual(0,report['parser_new_model_calls'])
        self.assertEqual('original_baseline_only',report['retained_recognition_run_scope'])
        self.assertIn('not a claim of zero VLM use',report['legacy_provenance_limitation'])

if __name__=='__main__':unittest.main()
