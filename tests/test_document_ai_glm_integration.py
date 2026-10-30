"""End-to-end invented GLM proposal/guard/projection, without model or images."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import correction_bridge as bridge
import correction_guard as guard
import glm_evidence as glm
from tests.test_document_ai_glm_evidence import data,PIN
from tests.test_document_ai_correction_bridge import fixture


class GlmIntegrationTests(unittest.TestCase):
    def values(self):
        page,cache,_,record,helpers=data();_,_,native=fixture()
        cache['geometry'].update(machine_only=True,vision_LLM_calls=0)
        # The old primary value reader is uncertain. GLM corroboration uses
        # the genuine independent Tess word rather than inventing a .95 score.
        for token in cache['working_tokens']:
            if token['token_id'] in ('p:q1','p:q2','p:u1','p:u2'):token['confidence']=.94
        helpers.update(glm_ocr=glm,glm_source_record={'observation':record,'pin':PIN})
        return page,cache,native,helpers

    def test_nonempty_revisions_survive_guard_and_original_projection_without_model_confidence(self):
        page,cache,native,helpers=self.values();sealed=deepcopy((page,cache,native))
        proposal=bridge.propose_and_apply(page,cache,native,helpers,PIN)
        revised,audit=guard.conserve_corrections(page,proposal,cache,native,helpers,PIN)
        self.assertEqual(4,len(audit['accepted_changes']),audit)
        projected,_=guard.project_corrections(page,revised,audit)
        field=projected['product_rows'][0]['fields']['quantity']
        self.assertEqual('10',field['raw_value']);self.assertIsNone(field['confidence'])
        self.assertEqual(page['product_rows'][0]['fields']['quantity'],field['source_revision']['previous_source_field'])
        self.assertEqual(sealed,(page,cache,native))
        for old,new in zip(page['product_rows'],projected['product_rows']):
            for key in ('description','lot','supplier_code'):self.assertEqual(old['fields'].get(key),new['fields'].get(key))

    def test_unknown_document_and_missing_old_headers_reach_GLM_before_legacy_gates(self):
        page,cache,native,helpers=self.values();page['document']['document_type']='unclassified'
        cache['working_tokens']=[t for t in cache['working_tokens'] if not t['token_id'].startswith('p:h')]
        proposal=bridge.propose_and_apply(page,cache,native,helpers,PIN)
        revised,audit=guard.conserve_corrections(page,proposal,cache,native,helpers,PIN)
        self.assertEqual(4,len(audit['accepted_changes']),audit)
        self.assertEqual('unclassified',revised['document']['document_type'])
        self.assertFalse(revised['product_rows'][0]['fields']['quantity']['receiving_approval'])

    def test_raw_literal_confidence_or_missing_record_cannot_replace_independent_proof(self):
        for mode in ('literal','confidence','missing-record','geometry'):
            page,cache,native,helpers=self.values()
            proposal=bridge.propose_and_apply(page,cache,native,helpers,PIN)
            event=proposal['document_ai_correction_association']['changes'][0]
            field=proposal['product_rows'][event['row_index']]['fields'][event['field']]
            if mode=='literal':field['raw_value']='UNPROVEN'
            elif mode=='confidence':field['confidence']=.999
            elif mode=='missing-record':helpers.pop('glm_source_record')
            else:field['bbox'][0]-=1
            event['candidate']=deepcopy(field)
            with self.subTest(mode=mode):
                _,audit=guard.conserve_corrections(page,proposal,cache,native,helpers,PIN)
                self.assertNotIn((event['row_index'],event['field']),[(e['row_index'],e['field']) for e in audit['accepted_changes']])

    def test_GLM_component_never_silently_activates_without_source_record(self):
        page,cache,native,helpers=self.values();helpers.pop('glm_source_record')
        page['document']['document_type']='unclassified'
        proposed=bridge.propose_and_apply(page,cache,native,helpers,PIN)
        _,audit=guard.conserve_corrections(page,proposed,cache,native,helpers,PIN)
        self.assertEqual([],audit['accepted_changes'])


if __name__=='__main__':unittest.main()
