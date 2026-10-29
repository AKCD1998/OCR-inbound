"""Independent proof-forgery and projection probes using synthetic cache data."""
from copy import deepcopy
import unittest

from tests.test_document_ai_correction_bridge import fixture, HELPERS, PIN, propose_and_apply
from correction_guard import conserve_corrections, project_corrections


class IndependentCorrectionGuardTests(unittest.TestCase):
    def normal(self):
        before,cache,observation=fixture()
        candidate=propose_and_apply(before,cache,observation,HELPERS,PIN)
        return before,cache,observation,candidate

    def one_change(self,candidate,index=0,role='quantity'):
        audit=candidate['document_ai_correction_association']
        change=next(x for x in audit['changes'] if x['row_index']==index and x['field']==role)
        audit['changes']=[change]
        return change

    def test_real_dual_source_revision_is_admitted_and_old_snapshot_retained(self):
        before,cache,obs,candidate=self.normal()
        output,audit=conserve_corrections(before,candidate,cache,obs,HELPERS,PIN)
        self.assertEqual(4,len(audit['accepted_changes']))
        self.assertEqual(before['product_rows'][0]['fields']['quantity'],
            output['product_rows'][0]['fields']['quantity']['source_revision']['previous_source_field'])

    def test_top_level_engine_and_confidence_cannot_contradict_actual_source(self):
        before,cache,obs,candidate=self.normal();change=self.one_change(candidate)
        field=candidate['product_rows'][0]['fields']['quantity']
        field['engine']='HUMAN_VERIFIED';field['confidence']=1.0
        change['candidate']=deepcopy(field)
        _,audit=conserve_corrections(before,candidate,cache,obs,HELPERS,PIN)
        self.assertEqual(0,len(audit['accepted_changes']))

    def test_field_native_cell_claim_cannot_differ_from_checked_evidence(self):
        before,cache,obs,candidate=self.normal();change=self.one_change(candidate)
        field=candidate['product_rows'][0]['fields']['quantity']
        field['model_geometry_evidence']['cell_id']='unrelated-native-cell'
        change['candidate']=deepcopy(field)
        _,audit=conserve_corrections(before,candidate,cache,obs,HELPERS,PIN)
        self.assertEqual(0,len(audit['accepted_changes']))

    def test_equal_printed_name_does_not_allow_borrowing_other_row_source_ids(self):
        before,cache,obs=fixture()
        for token in cache['working_tokens']:
            if token['token_id']=='p:d2b':token['text']='Product1'
        before['product_rows'][1]['fields']['description']['raw_value']='Synthetic Product1'
        before['product_rows'][1]['fields']['description']['normalized_value']='Synthetic Product1'
        candidate=propose_and_apply(before,cache,obs,HELPERS,PIN)
        original=deepcopy(next(x for x in candidate['document_ai_correction_association']['changes']
                              if x['row_index']==1 and x['field']=='quantity'))
        # An old merged bbox is insufficient proof that another row's name
        # detections belong to this existing row. Its token IDs remain row1.
        before['product_rows'][0]['fields']['description']['bbox']=[40,220,380,340]
        candidate=deepcopy(before)
        original['row_index']=0
        original['before']=deepcopy(before['product_rows'][0]['fields']['quantity'])
        original['candidate']['prior_source_evidence']=deepcopy(original['before'])
        candidate['product_rows'][0]['fields']['quantity']=deepcopy(original['candidate'])
        candidate['document_ai_correction_association']={'changes':[original]}
        _,audit=conserve_corrections(before,candidate,cache,obs,HELPERS,PIN)
        self.assertEqual(0,len(audit['accepted_changes']))

    def test_native_row_number_alone_cannot_replace_actual_source_row_band(self):
        before,cache,obs,candidate=self.normal()
        change=deepcopy(next(x for x in candidate['document_ai_correction_association']['changes']
                             if x['row_index']==1 and x['field']=='quantity'))
        # Simulate incorrect native row topology: the row2 numeric content is
        # labelled native row1 at another column. Literal source geometry still
        # places it 100px below the existing row1 name.
        for cell in obs['cell_association']['cells']:
            if cell['id']=='c2-2':
                cell.update(start_row_offset_idx=1,end_row_offset_idx=2,
                    start_col_offset_idx=8,end_col_offset_idx=9)
        change['row_index']=0;change['before']=deepcopy(before['product_rows'][0]['fields']['quantity'])
        change['evidence']['anchor_token_ids']=['p:d1a','p:d1b'];change['evidence']['native_row']=1
        change['candidate']['model_geometry_evidence']['row']=1
        change['candidate']['prior_source_evidence']=deepcopy(change['before'])
        candidate=deepcopy(before);candidate['product_rows'][0]['fields']['quantity']=deepcopy(change['candidate'])
        candidate['document_ai_correction_association']={'changes':[change]}
        _,audit=conserve_corrections(before,candidate,cache,obs,HELPERS,PIN)
        self.assertEqual(0,len(audit['accepted_changes']))

    def test_projection_copies_only_admitted_fields_and_exact_original_previous_evidence(self):
        before,cache,obs,candidate=self.normal()
        admitted,guard=conserve_corrections(before,candidate,cache,obs,HELPERS,PIN)
        parent=deepcopy(before)
        parent['product_rows'][0]['fields']['quantity']['bbox']=[11,22,33,44]
        mapped=deepcopy(admitted)
        mapped['document']={'unrelated':'mapper alteration must not survive'}
        mapped['product_rows'][0]['fields']['lot']={'raw_value':'FORGED MAPPER CHANGE'}
        output,_=project_corrections(parent,mapped,guard)
        self.assertEqual(parent['document'],output['document'])
        self.assertEqual(parent['product_rows'][0]['fields']['lot'],output['product_rows'][0]['fields']['lot'])
        field=output['product_rows'][0]['fields']['quantity']
        self.assertEqual(parent['product_rows'][0]['fields']['quantity'],field['prior_source_evidence'])
        self.assertEqual(parent['product_rows'][0]['fields']['quantity'],field['source_revision']['previous_source_field'])
        self.assertEqual('upright_image',field['source_revision']['source_evidence_coordinate_space'])


if __name__=='__main__':unittest.main()
