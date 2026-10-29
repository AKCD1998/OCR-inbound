"""Independent composition/conservation probes using invented source tokens."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/document_ai'))
import correction_bridge as bridge
import correction_guard as guard
import source_cell_association as cells
from tests.test_document_ai_correction_bridge import fixture,HELPERS,PIN


class SourceComponentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.page,self.cache,self.obs=fixture()
        self.cache['geometry'].update(machine_only=True,vision_LLM_calls=0)
        self.helpers={**HELPERS,'correction_bridge':bridge,'cell_association':cells}

    def no_native(self):
        self.obs['regions']=[];self.obs['cell_association']['cells']=[]

    def propose(self):
        return bridge.propose_and_apply(self.page,self.cache,self.obs,self.helpers,PIN)

    def verify(self,candidate):
        return guard.conserve_corrections(self.page,candidate,self.cache,self.obs,self.helpers,PIN)

    def test_source_cells_recover_whole_proofs_with_no_native_table(self):
        self.no_native();before=deepcopy((self.page,self.cache,self.obs))
        revised,audit=self.verify(self.propose())
        self.assertEqual(4,len(audit['accepted_changes']),audit)
        self.assertEqual('10',revised['product_rows'][0]['fields']['quantity']['raw_value'])
        self.assertEqual('SOURCE_HEADER_ROW_BAND',revised['product_rows'][0]['fields']['unit']['association_basis'])
        self.assertEqual(self.page['document'],revised['document'])
        for old,new in zip(self.page['product_rows'],revised['product_rows']):
            self.assertEqual(old['row_number'],new['row_number'])
            self.assertEqual(old['fields']['description'],new['fields']['description'])
            self.assertEqual(old['fields']['lot'],new['fields']['lot'])
            self.assertEqual(old['fields']['quantity'],new['fields']['quantity']['source_revision']['previous_source_field'])
        self.assertEqual(before,(self.page,self.cache,self.obs))

    def test_guard_recomputes_cell_geometry_and_actual_literal(self):
        self.no_native();candidate=self.propose()
        for scenario in ('band','literal','native_identity'):
            forged=deepcopy(candidate)
            event=forged['document_ai_correction_association']['changes'][0]
            field=forged['product_rows'][event['row_index']]['fields'][event['field']]
            if scenario=='band':event['evidence']['source_header_band'][0]-=1
            elif scenario=='literal':field['raw_value']='123456';event['candidate']=deepcopy(field)
            else:field['model_geometry_evidence']['cell_id']='invented';event['candidate']=deepcopy(field)
            with self.subTest(scenario=scenario):
                _,audit=self.verify(forged)
                self.assertNotIn((event['row_index'],event['field']),
                    [(e['row_index'],e['field']) for e in audit['accepted_changes']])
                self.assertTrue(audit['rejected_changes'])

    def test_missing_machine_geometry_or_component_cannot_authorize_bands(self):
        self.no_native();candidate=self.propose()
        for scenario in ('geometry','component'):
            cache=deepcopy(self.cache);helpers=dict(self.helpers)
            if scenario=='geometry':cache['geometry']['machine_only']=False
            else:helpers.pop('cell_association')
            with self.subTest(scenario=scenario):
                revised,audit=guard.conserve_corrections(self.page,candidate,cache,self.obs,helpers,PIN)
                self.assertEqual([],audit['accepted_changes'])
                self.assertEqual(self.page['product_rows'],revised['product_rows'])

    def test_source_band_cannot_steal_preserved_price_token(self):
        self.no_native();candidate=self.propose()
        self.page['product_rows'][0]['fields']['unit_price']={'raw_value':'10','token_ids':['p:q1']}
        revised,audit=self.verify(candidate)
        self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in audit['accepted_changes']])
        self.assertEqual(self.page['product_rows'][0]['fields']['unit_price'],revised['product_rows'][0]['fields']['unit_price'])

    def test_equal_native_and_source_routes_are_not_double_applied(self):
        proposed=self.propose();revised,audit=self.verify(proposed)
        self.assertEqual(4,len(audit['accepted_changes']))
        self.assertEqual(4,len(proposed['document_ai_correction_association']['changes']))
        self.assertNotEqual('SOURCE_HEADER_ROW_BAND',revised['product_rows'][0]['fields']['quantity']['association_basis'])

    def test_conflicting_route_literals_abstain_instead_of_overriding(self):
        fake=cells.propose(self.page,self.cache,self.obs,self.helpers,PIN)
        event=fake['changes'][0];event['candidate']['raw_value']='CONFLICT'
        self.helpers['cell_association']=SimpleNamespace(propose=lambda *args:fake)
        candidate=self.propose()
        self.assertNotIn((event['row_index'],event['field']),
            [(e['row_index'],e['field']) for e in candidate['document_ai_correction_association']['changes']])
        self.assertEqual(self.page['product_rows'][event['row_index']]['fields'][event['field']],
            candidate['product_rows'][event['row_index']]['fields'][event['field']])

    def borrowed_row_candidate(self,with_neighbour):
        self.no_native()
        event=next(e for e in cells.propose(self.page,self.cache,self.obs,self.helpers,PIN)['changes']
                   if e['row_index']==0 and e['field']=='quantity')
        context=cells.verify(self.page,self.cache,self.obs,self.helpers,PIN,0,'quantity',event['evidence'])
        for family,tid,newid in (('working_tokens','p:q1','p:other-q'),
                                 ('tesseract_working_tokens','tesseract:q1','tesseract:other-q')):
            token=next(t for t in self.cache[family] if t['token_id']==tid)
            token['token_id']=newid;token['text']='7';token['box'][1:4:2]=[245,253]
            if 'original_source_bbox' in token:token['original_source_bbox']=deepcopy(token['box'])
        if with_neighbour:
            self.page['product_rows'].insert(1,{'row_number':99,'page_number':2,'source_row_role':'goods',
                'fields':{'description':{'raw_value':'UNCONFIRMED OTHER ROW','bbox':[40,245,380,265]},
                          'quantity':None,'unit':None}})
        rules=self.helpers['rules']
        value,reason=rules._read_cell(context['source_band'],rules._tokens(self.cache['working_tokens']),
            rules._tokens(self.cache['tesseract_working_tokens'],True),context['anchor'],'quantity')
        self.assertIsNotNone(value,reason)
        field=cells._field(value,self.page['product_rows'][0]['fields']['quantity'],event['evidence'])
        event['candidate']=field
        proposal=deepcopy(self.page);proposal['product_rows'][0]['fields']['quantity']=deepcopy(field)
        proposal['document_ai_correction_association']={'changes':[event]}
        # Simulate a faulty geometry verifier; the guard must still verify
        # immutable neighbours and the actual source text baseline itself.
        self.helpers['cell_association']=SimpleNamespace(verify=lambda *args:deepcopy(context))
        return proposal

    def test_guard_itself_rejects_an_unconfirmed_canonical_neighbour(self):
        proposed=self.borrowed_row_candidate(True)
        revised,audit=self.verify(proposed)
        self.assertEqual([],audit['accepted_changes'])
        self.assertEqual(self.page['product_rows'],revised['product_rows'])
        self.assertIn('source_band_crosses_canonical_neighbour_barrier',
                      [e['reason'] for e in audit['rejected_changes']])

    def test_guard_itself_rechecks_whole_value_text_baseline(self):
        proposed=self.borrowed_row_candidate(False)
        revised,audit=self.verify(proposed)
        self.assertEqual([],audit['accepted_changes'])
        self.assertEqual(self.page['product_rows'],revised['product_rows'])
        self.assertIn('whole_value_not_on_proven_source_name_baseline',
                      [e['reason'] for e in audit['rejected_changes']])


if __name__=='__main__':unittest.main()
