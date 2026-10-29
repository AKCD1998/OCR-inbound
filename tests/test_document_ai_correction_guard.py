"""Adversarial source-conservation checks on synthetic printed evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments'/'document_ai'))
sys.path.insert(0,str(ROOT/'tests'))
from correction_bridge import propose_and_apply
from correction_guard import conserve_corrections, project_corrections
from tests.test_document_ai_correction_bridge import fixture, HELPERS, PIN


class CorrectionConservationTests(unittest.TestCase):
    def setUp(self):
        self.page,self.cache,self.observation=fixture()
        self.cache['inference_inputs']={'reference':False,'human_answers':False,
            'Ada':False,'StockDay':False,'assistant_image_reads':0}

    def bridge(self):
        return propose_and_apply(self.page,self.cache,self.observation,HELPERS,PIN)

    def guard(self,candidate):
        return conserve_corrections(self.page,candidate,self.cache,self.observation,HELPERS,PIN)

    def test_nonempty_wrong_literal_can_change_with_old_evidence_preserved(self):
        frozen=deepcopy([self.page,self.cache,self.observation])
        proposed=self.bridge()
        revised,audit=self.guard(proposed)
        self.assertEqual(len(audit['accepted_changes']),4,audit['rejected_changes'])
        quantity=revised['product_rows'][0]['fields']['quantity']
        self.assertEqual(quantity['raw_value'],'10')
        self.assertEqual(quantity['source_revision']['kind'],'replace')
        self.assertEqual(quantity['source_revision']['previous_source_field'],
                         self.page['product_rows'][0]['fields']['quantity'])
        for old,new in zip(self.page['product_rows'],revised['product_rows']):
            self.assertEqual(old['row_number'],new['row_number'])
            for field in ('description','lot','supplier_code'):
                self.assertEqual(old['fields'][field],new['fields'][field])
        self.assertEqual(frozen,[self.page,self.cache,self.observation])

    def test_forged_candidate_cannot_replace_source_literal(self):
        proposed=self.bridge()
        proposed['product_rows'][0]['fields']['quantity']['raw_value']='1234'
        proposed['document_ai_correction_association']['changes'][0]['candidate']['raw_value']='1234'
        revised,audit=self.guard(proposed)
        self.assertEqual(revised['product_rows'][0]['fields']['quantity'],self.page['product_rows'][0]['fields']['quantity'])
        self.assertTrue(audit['rejected_changes'])

    def test_diagnostic_relationship_does_not_change_canonical_metadata(self):
        # Exact diagnostic metadata from a source conflict, with no receiving
        # role or business answer. Eligibility must not delete the real note.
        from correction_eligibility import assess_row
        relation = self.diagnostic_relation()
        self.page['product_rows'][0]['relationships'] = [relation]
        self.assertTrue(assess_row(self.page['product_rows'][0], HELPERS['rules'])['eligible'])
        revised,audit=self.guard(self.bridge())
        self.assertEqual(4,len(audit['accepted_changes']),audit['rejected_changes'])
        self.assertEqual(revised['product_rows'][0]['relationships'],[relation])
        self.assertEqual(self.page['product_rows'][0]['relationships'],[relation])

    def gap_candidate(self):
        self.cache['working_tokens'].append({'token_id':'p:code-heading',
            'text':'รหัสสินค้า','box':[21,120,30,140],'confidence':.99,'engine':'PADDLE_TH'})
        candidate=self.bridge()
        lookup={t['token_id']:t for t in HELPERS['rules']._tokens(self.cache['working_tokens'])}
        proof={'method':'SOURCE_HEADER_TEXT_GAP',
            'description_header_tokens':[lookup['p:h0a'],lookup['p:h0b']],
            'left_header':{'role':'supplier_code','tokens':[lookup['p:code-heading']]},
            'right_header':{'role':'quantity','tokens':[lookup['p:h1']]},
            'bounds':[30,530],'physical_cell_borders_claimed':False}
        for change in candidate['document_ai_correction_association']['changes']:
            change['evidence']['description_column_proof']=deepcopy(proof)
        return candidate

    def test_source_heading_gap_proof_is_independently_reconstructed(self):
        revised,audit=self.guard(self.gap_candidate())
        self.assertEqual(4,len(audit['accepted_changes']),audit['rejected_changes'])
        self.assertEqual('10',revised['product_rows'][0]['fields']['quantity']['raw_value'])

    def test_description_gap_cannot_claim_wider_edges_or_forged_heading(self):
        candidate=self.gap_candidate()
        for scenario in ('bounds','literal','physical_border'):
            forged=deepcopy(candidate)
            for change in forged['document_ai_correction_association']['changes']:
                proof=change['evidence']['description_column_proof']
                if scenario=='bounds':proof['bounds'][0]=20
                elif scenario=='literal':proof['left_header']['tokens'][0]['text']='FORGED'
                else:proof['physical_cell_borders_claimed']=True
            with self.subTest(scenario=scenario):
                revised,audit=self.guard(forged)
                self.assertEqual([],audit['accepted_changes'])
                self.assertEqual(revised['product_rows'],self.page['product_rows'])

    def test_description_gap_cannot_skip_a_nearer_monetary_heading(self):
        candidate=self.gap_candidate()
        self.cache['working_tokens'].append({'token_id':'p:nearer-price',
            'text':'PRICE','box':[405,120,430,140],'confidence':.99,'engine':'PADDLE_TH'})
        revised,audit=self.guard(candidate)
        self.assertEqual([],audit['accepted_changes'])
        self.assertEqual(revised['product_rows'],self.page['product_rows'])
        self.assertTrue(any('heading_inside_description_gap' in r['reason']
                            for r in audit['rejected_changes']))

    @staticmethod
    def diagnostic_relation():
        # Populated using the diagnostic policy's documented exact schema;
        # this synthetic relation never supplies a recognition answer.
        return {'type':'adaptive_field_conflict','field':'lot',
                'previous':{'raw_value':'SYNTHETIC_OLD'},
                'candidate':{'raw_value':'SYNTHETIC_NEW'},
                'source_association_approved':False}

    def test_forged_revision_cannot_bypass_unknown_or_bonus_relationship(self):
        proposed=self.bridge()
        for relation in ({'type':'unknown_relationship'},
                         {'type':'printed_free_or_compensation_candidate'}):
            with self.subTest(relation=relation):
                self.page['product_rows'][0]['relationships']=[self.diagnostic_relation(),relation]
                revised,audit=self.guard(proposed)
                self.assertNotIn(0,[x['row_index'] for x in audit['accepted_changes']])
                self.assertEqual(revised['product_rows'][0],self.page['product_rows'][0])
                self.assertIn('protected_source_row',[x['reason'] for x in audit['rejected_changes']])

    def test_false_previous_snapshot_is_rejected(self):
        proposed=self.bridge()
        change=proposed['document_ai_correction_association']['changes'][0]
        change['before']['raw_value']='not-the-previous-value'
        revised,audit=self.guard(proposed)
        self.assertEqual(revised['product_rows'][change['row_index']]['fields'][change['field']],
                         self.page['product_rows'][change['row_index']]['fields'][change['field']])
        self.assertIn('explicit_before_after_snapshot_differs',[r['reason'] for r in audit['rejected_changes']])

    def test_independent_source_confidence_is_not_taken_from_candidate(self):
        proposed=self.bridge()
        self.cache['working_tokens'][7]['confidence']=.94
        _,audit=self.guard(proposed)
        self.assertTrue(audit['rejected_changes'])

    def test_unchanged_price_owner_cannot_be_stolen(self):
        self.page['product_rows'][0]['fields']['unit_price']={'raw_value':'10','normalized_value':'10','token_ids':['p:q1']}
        proposed=self.bridge()
        # A malicious bridge can still emit a claim; the guard checks old
        # ownership independently instead of trusting the proposed decision.
        clean_page,clean_cache,clean_observation=fixture()
        clean_cache['inference_inputs']=self.cache['inference_inputs']
        forged=propose_and_apply(clean_page,clean_cache,clean_observation,HELPERS,PIN)
        _,audit=self.guard(forged)
        self.assertNotIn((0,'quantity'),[(x['row_index'],x['field']) for x in audit['accepted_changes']])
        self.assertIn('preserved_foreign_source_owner',[r['reason'] for r in audit['rejected_changes']])

    def test_one_native_cell_cannot_claim_both_name_and_quantity(self):
        proposed=self.bridge()
        # A valid quantity read does not justify a native cell that also owns
        # this row's product name. Keep all source literals untouched.
        for cell in self.observation['cell_association']['cells']:
            if cell['id']=='c1-0':cell['bbox']=[20,250,30,260]
            elif cell['id']=='c1-2':cell['bbox']=[20,210,590,250]
        revised,audit=self.guard(proposed)
        self.assertNotIn((0,'quantity'),[(x['row_index'],x['field']) for x in audit['accepted_changes']])
        self.assertEqual(revised['product_rows'][0]['fields']['quantity'],
                         self.page['product_rows'][0]['fields']['quantity'])
        self.assertIn('description_and_value_share_native_column',
                      [r['reason'] for r in audit['rejected_changes']])

    def test_same_row_quantity_unit_swap_is_one_proved_transaction(self):
        row=self.page['product_rows'][0]
        row['fields']['quantity']={'raw_value':'BOX','normalized_value':'BOX','token_ids':['p:u1'],'bbox':[690,220,750,240]}
        row['fields']['unit']={'raw_value':'10','normalized_value':'10','token_ids':['p:q1'],'bbox':[530,220,570,240]}
        revised,audit=self.guard(self.bridge())
        self.assertEqual(revised['product_rows'][0]['fields']['quantity']['raw_value'],'10')
        self.assertEqual(revised['product_rows'][0]['fields']['unit']['raw_value'],'BOX')
        self.assertTrue({(0,'quantity'),(0,'unit')}<=set((x['row_index'],x['field']) for x in audit['accepted_changes']))

    def test_failed_swap_side_rolls_back_its_dependent(self):
        row=self.page['product_rows'][0]
        row['fields']['quantity']={'raw_value':'BOX','normalized_value':'BOX','token_ids':['p:u1'],'bbox':[690,220,750,240]}
        row['fields']['unit']={'raw_value':'10','normalized_value':'10','token_ids':['p:q1'],'bbox':[530,220,570,240]}
        proposed=self.bridge()
        for change in proposed['document_ai_correction_association']['changes']:
            if change['row_index']==0 and change['field']=='unit':
                change['candidate']['raw_value']='forged'
                proposed['product_rows'][0]['fields']['unit']['raw_value']='forged'
        revised,audit=self.guard(proposed)
        self.assertEqual(revised['product_rows'][0],self.page['product_rows'][0])
        self.assertNotIn((0,'quantity'),[(x['row_index'],x['field']) for x in audit['accepted_changes']])

    def test_changed_row_identity_is_not_a_correction(self):
        proposed=self.bridge();proposed['product_rows'][0]['row_number']=99
        revised,audit=self.guard(proposed)
        self.assertEqual(revised,self.page)
        self.assertEqual(audit['accepted_changes'],[])

    def test_reference_inputs_are_refused_before_source_proposals(self):
        proposed=self.bridge();self.cache['inference_inputs']['reference']=True
        revised,audit=self.guard(proposed)
        self.assertEqual(revised,self.page)
        self.assertEqual(audit['accepted_changes'],[])

    def document_helpers(self):
        import document_source_admission
        self.cache['geometry'].update(machine_only=True,vision_LLM_calls=0)
        self.cache['working_tokens'].append({'token_id':'p:document-title','text':'INVOICE',
            'box':[40,20,200,40],'confidence':.99,'engine':'PADDLE_TH'})
        return {**HELPERS,'document_admission':document_source_admission}

    def test_printed_document_admission_preserves_original_unclassified_metadata(self):
        helpers=self.document_helpers();self.page['document']['document_type']='unclassified'
        before=deepcopy(self.page)
        proposed=propose_and_apply(self.page,self.cache,self.observation,helpers,PIN)
        revised,audit=conserve_corrections(self.page,proposed,self.cache,self.observation,helpers,PIN)
        self.assertEqual(4,len(audit['accepted_changes']),audit)
        self.assertTrue(audit['document_admission']['eligible'])
        self.assertEqual(before['document'],revised['document'])
        self.assertEqual(before,self.page)

    def test_guard_rechecks_negative_document_title_in_actual_source(self):
        proposed=self.bridge()
        helpers=self.document_helpers()
        self.cache['working_tokens'][ -1 ]['text']='CREDIT NOTE'
        revised,audit=conserve_corrections(self.page,proposed,self.cache,self.observation,helpers,PIN)
        self.assertEqual([],audit['accepted_changes'])
        self.assertEqual(self.page,revised)
        self.assertFalse(audit['document_admission']['eligible'])

    def test_candidate_document_approval_annotation_is_not_authority(self):
        proposed=self.bridge()
        helpers=self.document_helpers();self.page['document']['document_type']='unclassified'
        self.cache['working_tokens'][ -1 ]['confidence']=.94
        proposed['document_ai_correction_association']['document_admission']={'eligible':True}
        revised,audit=conserve_corrections(self.page,proposed,self.cache,self.observation,helpers,PIN)
        self.assertEqual([],audit['accepted_changes'])
        self.assertEqual(self.page,revised)

    def test_source_identity_and_frame_are_rechecked_without_trusting_bridge(self):
        proposed=self.bridge()
        for key,value in (('source_sha256','f'*64),('page_number',999),
                          ('image_size',[101,202])):
            with self.subTest(key=key):
                before=deepcopy(self.page);before[key]=value
                revised,audit=conserve_corrections(before,proposed,self.cache,
                                                  self.observation,HELPERS,PIN)
                self.assertEqual(revised,before)
                self.assertEqual(audit['accepted_changes'],[])

    def test_original_frame_projection_changes_only_admitted_fields(self):
        upright,audit=self.guard(self.bridge())
        parent=deepcopy(self.page);parent['coordinate_space']='original_image'
        parent['product_rows'][0]['fields']['quantity']['bbox']=[1,2,3,4]
        mapped=deepcopy(upright);mapped['coordinate_space']='original_image'
        mapped['product_rows'][0]['fields']['lot']['raw_value']='ILLEGAL'
        mapped['document']={'document_type':'ILLEGAL'}
        result,projection=project_corrections(parent,mapped,audit)
        self.assertEqual(result['document'],parent['document'])
        self.assertEqual(result['product_rows'][0]['fields']['lot'],parent['product_rows'][0]['fields']['lot'])
        changed=result['product_rows'][0]['fields']['quantity']
        self.assertEqual(changed['source_revision']['previous_source_field'],parent['product_rows'][0]['fields']['quantity'])
        self.assertEqual(changed['prior_source_evidence'],parent['product_rows'][0]['fields']['quantity'])
        self.assertEqual(changed['source_revision']['source_evidence_coordinate_space'],'upright_image')
        self.assertEqual(len(projection['accepted_changes']),4)


if __name__=='__main__':unittest.main()
