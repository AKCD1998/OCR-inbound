"""Invented source-only row-band cases; no invoice/model/private helper IO."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/document_ai'))
import correction_bridge
import source_cell_association as cells
from tests.test_document_ai_correction_bridge import fixture,HELPERS,PIN


class SourceCellAssociationTests(unittest.TestCase):
    def setUp(self):
        self.page,self.cache,self.obs=fixture()
        self.helpers={**HELPERS,'correction_bridge':correction_bridge}

    def propose(self):return cells.propose(self.page,self.cache,self.obs,self.helpers,PIN)

    def quantity_only_fixture(self):
        self.cache['working_tokens']=[t for t in self.cache['working_tokens']
            if t['token_id'] not in ('p:h2','p:u1','p:u2')]
        self.cache['tesseract_working_tokens']=[t for t in self.cache['tesseract_working_tokens']
            if t['token_id'] not in ('tesseract:u1','tesseract:u2')]

    def test_explicit_quantity_only_context_does_not_wait_for_an_unobserved_unit_heading(self):
        self.quantity_only_fixture();before=deepcopy((self.page,self.cache,self.obs))
        self.assertFalse(self.propose()['source_contexts'])
        self.helpers['quantity_only_source_contexts']=True
        out=self.propose()
        self.assertEqual([(0,'quantity'),(1,'quantity')],[(x['row_index'],x['field']) for x in out['changes']],out['rejected'])
        for event in out['changes']:
            evidence=event['evidence'];proof=evidence['quantity_only_header_proof']
            self.assertEqual('EXPLICIT_QUANTITY_ONLY_PRIMARY_LITERAL_HEADERS',proof['method'])
            self.assertEqual(['description','quantity'],proof['required_roles'])
            self.assertNotIn('unit',evidence['whole_source_headers'])
            self.assertFalse(proof['unit_inferred']);self.assertFalse(proof['physical_cell_borders_claimed'])
            cells.verify(self.page,self.cache,self.obs,self.helpers,PIN,event['row_index'],'quantity',evidence)
            forged=deepcopy(evidence);forged['quantity_only_header_proof']['all_coherent_primary_header_groups'].pop()
            with self.assertRaises(ValueError):
                cells.verify(self.page,self.cache,self.obs,self.helpers,PIN,event['row_index'],'quantity',forged)
        self.assertEqual(before,(self.page,self.cache,self.obs))

    def test_quantity_only_route_keeps_competing_words_and_foreign_owners(self):
        self.quantity_only_fixture();self.helpers['quantity_only_source_contexts']=True
        self.page['product_rows'][0]['fields']['unit_price']={'raw_value':'10','token_ids':['p:q1']}
        out=self.propose();self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in out['changes']])
        self.assertIn('preserved_foreign_source_owner',[e['reason'] for e in out['rejected']])
        for mode in ('unbounded','competing_whole_heading','ambiguous_quantity','price_word','low_primary','protected_neighbour'):
            self.page,self.cache,self.obs=fixture();self.quantity_only_fixture()
            if mode=='unbounded':self.cache['working_tokens']=[t for t in self.cache['working_tokens'] if t['token_id']!='p:h3']
            elif mode=='competing_whole_heading':self.cache['working_tokens'].append({'text':'Price','token_id':'intruding-price',
                'box':[420,120,810,140],'confidence':.99,'engine':'PADDLE_TH'})
            elif mode=='ambiguous_quantity':self.cache['working_tokens'].append({'text':'QTY','token_id':'other-qty',
                'box':[760,120,800,140],'confidence':.99,'engine':'PADDLE_TH'})
            elif mode=='price_word':self.cache['working_tokens'].append({'text':'900','token_id':'foreign-price',
                'box':[580,220,610,240],'confidence':.99,'engine':'PADDLE_TH'})
            elif mode=='low_primary':next(t for t in self.cache['working_tokens'] if t['token_id']=='p:q1')['confidence']=.949
            else:self.page['product_rows'][1]['relationships']=[{'type':'unknown_receiving_semantics'}]
            with self.subTest(mode=mode):
                out=self.propose();self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in out['changes']])

    def test_quantity_only_opt_in_does_not_change_legacy_triplet_contexts(self):
        legacy,_=cells._contexts(self.page,self.cache,self.obs,self.helpers,PIN)
        self.helpers['quantity_only_source_contexts']=True
        enabled,_=cells._contexts(self.page,self.cache,self.obs,self.helpers,PIN)
        self.assertEqual(legacy,enabled)

    def test_quantity_only_retains_unknown_whole_detections_in_every_reader_family(self):
        for family in ('primary','secondary','alternative'):
            self.page,self.cache,self.obs=fixture();self.quantity_only_fixture()
            self.helpers['quantity_only_source_contexts']=True
            t={'token_id':'unexpected-source','text':'UNREGISTERED','box':[590,220,650,240],
               'engine':'PADDLE_TH','confidence':.99}
            if family=='primary':self.cache['working_tokens'].append(t)
            elif family=='secondary':
                t.update(token_id='tesseract:unexpected',engine='TESSERACT_THA_ENG',original_source_bbox=deepcopy(t['box']),
                    recognition_transform={'source_engine':'TESSERACT_THA_ENG','coordinate_space':'upright_image'})
                self.cache['tesseract_working_tokens'].append(t)
            else:self.cache['targeted_views']=[{'tokens':[t]}]
            before=deepcopy(self.cache);out=self.propose()
            with self.subTest(family=family):
                self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in out['changes']])
                self.assertEqual(before,self.cache)

    def test_ambiguous_or_observed_uom_cannot_be_relabelled_missing(self):
        for mode in ('ambiguous','observed'):
            self.page,self.cache,self.obs=fixture();self.quantity_only_fixture()
            self.helpers['quantity_only_source_contexts']=True
            self.cache['working_tokens'].append({'token_id':'uom-left','text':'UOM',
                'box':[680,120,750,140],'confidence':.99,'engine':'PADDLE_TH'})
            if mode=='ambiguous':self.cache['working_tokens'].append({'token_id':'uom-right','text':'UOM',
                'box':[760,120,810,140],'confidence':.99,'engine':'PADDLE_TH'})
            contexts,_=cells._contexts(self.page,self.cache,self.obs,self.helpers,PIN)
            with self.subTest(mode=mode):self.assertFalse([x for x in contexts if 'quantity_only_header_proof' in x['evidence']])

    def test_quantity_only_retains_lower_confidence_same_center_wide_price_heading(self):
        self.quantity_only_fixture();self.helpers['quantity_only_source_contexts']=True
        for tid,box,confidence in (('chosen-price',[680,120,700,140],.99),
                                   ('wide-price',[500,120,880,140],.98)):
            self.cache['working_tokens'].append({'token_id':tid,'text':'Price','box':box,
                'confidence':confidence,'engine':'PADDLE_TH'})
        out=self.propose()
        self.assertFalse(out['source_contexts']);self.assertFalse(out['changes'])

    def test_actual_roi_needs_no_native_content_cell_and_preserves_inputs(self):
        self.obs['cell_association']['cells']=[];before=deepcopy((self.page,self.cache,self.obs))
        out=self.propose();self.assertEqual(4,len(out['changes']),out['rejected'])
        event=out['changes'][0];field=event['candidate'];evidence=event['evidence']
        self.assertEqual('SOURCE_HEADER_ROW_BAND',field['association_basis'])
        self.assertEqual('ACTUAL_NATIVE_TABLE_ROI',evidence['region']['kind'])
        self.assertEqual(0,field['model_geometry_evidence']['native_cells_used'])
        self.assertNotIn('cell_id',field['model_geometry_evidence'])
        self.assertFalse(evidence['physical_cell_borders_claimed'])
        self.assertEqual(event['before'],field['prior_source_evidence'])
        self.assertEqual(before,(self.page,self.cache,self.obs))

    def test_zero_native_table_region_can_have_honest_source_derived_region(self):
        self.obs['regions']=[];self.obs['cell_association']['cells']=[]
        out=self.propose();self.assertEqual(4,len(out['changes']),out['rejected'])
        for event in out['changes']:
            region=event['evidence']['region']
            self.assertEqual('SOURCE_DERIVED_TABLE_REGION',region['kind']);self.assertIsNone(region['native_region_id'])
            context=cells.verify(self.page,self.cache,self.obs,self.helpers,PIN,event['row_index'],event['field'],event['evidence'])
            self.assertEqual(event['evidence']['source_header_band'],context['source_band'])
            self.assertIn('token',context['anchor']);self.assertIn('tokens',context['anchor'])

    def test_verify_rebuilds_from_original_and_refuses_any_forged_boundary(self):
        event=self.propose()['changes'][0]
        for mode in ('band','header','anchor','peers','native_claim','source','raw_tokens'):
            proof=deepcopy(event['evidence']);cache=deepcopy(self.cache)
            if mode=='band':proof['source_header_band'][0]-=1
            elif mode=='header':proof['role_header_tokens'][0]['text']='Amount'
            elif mode=='anchor':proof['anchor_token_ids']=['foreign']
            elif mode=='peers':proof['peer_source_rows'].pop()
            elif mode=='native_claim':proof['native_cells_used']=1
            elif mode=='source':proof['source_sha256']='b'*64
            else:cache['working_tokens'][-1]['text']='changed source token'
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                cells.verify(self.page,cache,self.obs,self.helpers,PIN,event['row_index'],event['field'],proof)

    def test_last_unit_column_uses_actual_roi_edge_without_clipping_a_detection(self):
        self.cache['working_tokens']=[t for t in self.cache['working_tokens'] if t['token_id'] not in ('p:h3','p:a1','p:a2')]
        original=deepcopy(self.cache);out=self.propose()
        self.assertEqual(4,len(out['changes']),out['rejected'])
        units=[x for x in out['changes'] if x['field']=='unit']
        for event in units:
            self.assertEqual(980,event['evidence']['source_column_bounds'][1])
            self.assertEqual('ACTUAL_ROI_EDGE',event['evidence']['source_column_boundary_basis']['right'])
            self.assertEqual([690,750],[event['candidate']['bbox'][0],event['candidate']['bbox'][2]])
        self.assertEqual(original,self.cache)

    def test_source_extent_contains_all_competing_primary_secondary_and_alternative_glyphs(self):
        self.obs['regions']=[];self.obs['cell_association']['cells']=[]
        self.cache['working_tokens']=[t for t in self.cache['working_tokens'] if t['token_id']!='p:h3']
        self.cache['targeted_views']=[{'tokens':[{'token_id':'alt:foreign','text':'NOT A UNIT',
            'box':[960,220,990,240],'engine':'PADDLE_TARGETED','confidence':.99}]}]
        out=self.propose()
        self.assertFalse([x for x in out['changes'] if x['field']=='unit'])
        proof=next(x for x in out['source_contexts'] if x['field']=='unit')
        self.assertEqual('SOURCE_CONTENT_EXTENT',proof['source_column_boundary_basis']['right'])
        self.assertEqual(990,proof['source_column_bounds'][1])
        provenance=proof['region']['extent_provenance'];words=provenance['content_detections']
        self.assertFalse(provenance['value_unit_type_filtering_applied'])
        self.assertTrue({'primary','secondary','alternative'}<={x['family'] for x in words})
        self.assertTrue({'p:a1','p:a2','alt:foreign'}<={x['token_id'] for x in words})
        forged=deepcopy(proof);forged['region']['extent_provenance']['content_detections'].pop()
        with self.assertRaises(ValueError):cells.verify(self.page,self.cache,self.obs,self.helpers,PIN,proof['row_index'],'unit',forged)

    def test_single_or_non_source_name_does_not_establish_table(self):
        for mode in ('single','business_name','missing_ids','shared_alias'):
            page=deepcopy(self.page)
            if mode=='single':page['product_rows']=page['product_rows'][:1]
            elif mode=='business_name':page['product_rows'][1]['fields']['description']['raw_value']='Business replacement'
            elif mode=='missing_ids':page['product_rows'][1]['fields']['description']['token_ids']=['not-source']
            else:
                for t in self.cache['working_tokens']:
                    if t['token_id'] in ('p:d1a','p:d2a'):t['source_detection_ids']=['shared-name']
            with self.subTest(mode=mode):self.assertFalse(cells.propose(page,self.cache,self.obs,self.helpers,PIN)['changes'])

    def test_false_quantity_in_price_column_cannot_be_borrowed(self):
        self.page['product_rows'][0]['fields']['unit_price']={'raw_value':'10','token_ids':['p:q1']}
        out=self.propose()
        self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in out['changes']])
        self.assertIn('preserved_foreign_source_owner',[x['reason'] for x in out['rejected']])

    def test_whole_word_crossing_row_band_is_withheld_without_clipping(self):
        primary=next(t for t in self.cache['working_tokens'] if t['token_id']=='p:q1');primary['box']=[530,210,570,350]
        before=deepcopy(primary);out=self.propose()
        self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in out['changes']])
        self.assertEqual(before,primary)

    def test_unproven_or_ambiguous_header_cannot_create_semantic_columns(self):
        for mode in ('missing_unit','duplicate_quantity','price_intrusion'):
            cache=deepcopy(self.cache)
            if mode=='missing_unit':cache['working_tokens']=[t for t in cache['working_tokens'] if t['token_id']!='p:h2']
            else:cache['working_tokens'].append({'text':'QTY' if mode=='duplicate_quantity' else 'Unit Price',
                'token_id':'extra-heading','box':[440,120,520,140] if mode=='duplicate_quantity' else [500,120,630,140],
                'confidence':.99,'engine':'PADDLE_TH'})
            with self.subTest(mode=mode):self.assertFalse(cells.propose(self.page,cache,self.obs,self.helpers,PIN)['changes'])

    def test_footer_and_protected_parent_rows_do_not_establish_goods(self):
        for mode in ('footer','bonus','unknown','set','non_receiving'):
            page=deepcopy(self.page);cache=deepcopy(self.cache)
            if mode=='footer':cache['working_tokens'].append({'text':'Grand Total','token_id':'footer','box':[800,220,950,240],
                'confidence':.99,'engine':'PADDLE_TH'})
            elif mode=='bonus':page['product_rows'][0]['source_row_role']='bonus'
            elif mode=='unknown':page['product_rows'][0]['relationships']=[{'type':'unknown_semantics'}]
            elif mode=='set':page['product_rows'][0]['relationships']=[{'type':'printed_set_and_detail_same_goods_candidate'}]
            else:page['product_rows'][0]['counted_in_receiving']=False
            with self.subTest(mode=mode):self.assertFalse(cells.propose(page,cache,self.obs,self.helpers,PIN)['changes'])

    def test_existing_source_row_order_and_disjointness_are_required(self):
        self.page['product_rows'].reverse();self.assertFalse(self.propose()['changes'])

    def test_overlapping_actual_table_regions_do_not_duplicate_source_owners(self):
        extra=deepcopy(self.obs['regions'][0]);extra['id']='other-table';self.obs['regions'].append(extra)
        out=self.propose();self.assertFalse(out['changes'])
        self.assertIn('ambiguous_multiple_source_regions',[x['reason'] for x in out['rejected']])

    def test_reader_confidence_and_independence_are_unchanged(self):
        for mode in ('primary','secondary','reuse','disagreement'):
            cache=deepcopy(self.cache);a=next(t for t in cache['working_tokens'] if t['token_id']=='p:q1');b=cache['tesseract_working_tokens'][0]
            if mode=='primary':a['confidence']=.949
            elif mode=='secondary':b['confidence']=.699
            elif mode=='reuse':a['source_detection_ids']=['shared'];b['source_detection_ids']=['shared']
            else:b['text']='999'
            with self.subTest(mode=mode):
                out=cells.propose(self.page,cache,self.obs,self.helpers,PIN)
                self.assertNotIn((0,'quantity'),[(e['row_index'],e['field']) for e in out['changes']])

    def test_canonical_negative_document_cannot_be_overridden_by_admission_flag(self):
        self.page['document']['document_type']='credit_note'
        self.helpers['document_admission']=SimpleNamespace(assess_document=lambda *a,**k:{'eligible':True})
        self.assertFalse(self.propose()['changes'])

    def test_source_document_admission_does_not_rewrite_canonical_type(self):
        self.page['document']['document_type']='unclassified';before=deepcopy(self.page)
        self.assertFalse(self.propose()['changes'])
        self.helpers['document_admission']=SimpleNamespace(assess_document=lambda *a,**k:{'eligible':True})
        self.assertEqual(4,len(self.propose()['changes']));self.assertEqual(before,self.page)

    def test_reference_native_model_text_or_foreign_source_never_supplies_answer(self):
        for mode in ('reference','no_reader','source'):
            cache=deepcopy(self.cache);obs=deepcopy(self.obs)
            if mode=='reference':cache['inference_inputs']['reference']=True
            elif mode=='no_reader':
                cache['tesseract_working_tokens']=[]
                for cell in obs['cell_association']['cells']:cell['raw_text']='10 BOX'
            else:obs['source_image']['sha256']='b'*64
            with self.subTest(mode=mode):self.assertFalse(cells.propose(self.page,cache,obs,self.helpers,PIN)['changes'])

    def test_mutually_proved_same_row_swap_vacates_only_its_own_source(self):
        row=self.page['product_rows'][0];row['fields']['quantity']={'raw_value':'BOX','token_ids':['p:u1']}
        row['fields']['unit']={'raw_value':'10','token_ids':['p:q1']}
        out=self.propose();self.assertTrue({(0,'quantity'),(0,'unit')}<={(e['row_index'],e['field']) for e in out['changes']})
        self.cache['tesseract_working_tokens']=[t for t in self.cache['tesseract_working_tokens'] if t['token_id']!='tesseract:u1']
        out=self.propose();self.assertFalse([e for e in out['changes'] if e['row_index']==0])

    def add_neighbour_values(self):
        self.cache['working_tokens']=[t for t in self.cache['working_tokens'] if t['token_id'] not in ('p:q1','p:u1')]
        self.cache['tesseract_working_tokens']=[t for t in self.cache['tesseract_working_tokens'] if t['token_id'] not in ('tesseract:q1','tesseract:u1')]
        for text,key,box in (('7','q',[530,245,570,253]),('BOX','u',[690,245,750,253])):
            self.cache['working_tokens'].append({'text':text,'token_id':'p:neighbour-'+key,'box':box,'confidence':.99,'engine':'PADDLE_TH'})
            self.cache['tesseract_working_tokens'].append({'text':text,'token_id':'tesseract:neighbour-'+key,'box':deepcopy(box),
                'confidence':.99,'engine':'TESSERACT_THA_ENG','original_source_bbox':deepcopy(box),
                'recognition_transform':{'source_engine':'TESSERACT_THA_ENG','coordinate_space':'upright_image'}})

    def test_null_canonical_neighbour_with_mismatched_name_is_still_a_negative_row_barrier(self):
        self.add_neighbour_values();box=[40,245,380,265]
        self.cache['working_tokens'].append({'text':'Synthetic Neighbour','token_id':'p:neighbour-name','box':box,
            'confidence':.99,'engine':'PADDLE_TH'})
        self.page['product_rows'].insert(1,{'row_number':2,'row_id':'unconfirmed-neighbour','source_row_role':'goods_detail',
            'relationships':[],'fields':{'description':{'raw_value':'MISMATCHED OLD NAME','bbox':box,
            'token_ids':['p:neighbour-name']},'quantity':None,'unit':None}})
        self.page['product_rows'][2]['row_number']=3;out=self.propose()
        self.assertFalse([e for e in out['changes'] if e['row_index'] in (0,1)])
        proof=next(p for p in out['source_contexts'] if p['row_index']==0 and p['field']=='quantity')
        barrier=next(b for b in proof['negative_row_barriers'] if b['row_index']==1)
        self.assertEqual('CANONICAL_SOURCE_ROW_BARRIER',barrier['kind'])
        self.assertFalse(barrier['raw_name_matching_used']);self.assertFalse(barrier['positive_goods_anchor'])
        self.assertLess(proof['source_header_band'][3],245)
        forged=deepcopy(proof);forged['negative_row_barriers'].remove(barrier)
        with self.assertRaises(ValueError):cells.verify(self.page,self.cache,self.obs,self.helpers,PIN,0,'quantity',forged)

    def test_next_row_values_without_a_modelled_name_cannot_attach_to_previous_baseline(self):
        self.add_neighbour_values();out=self.propose()
        self.assertFalse([e for e in out['changes'] if e['row_index']==0])
        self.assertIn('actual_value_not_on_established_name_baseline',[e['reason'] for e in out['rejected']])

    def test_unmodelled_dual_reader_name_is_negative_only_and_keeps_its_source_ids(self):
        self.add_neighbour_values();box=[40,245,380,265]
        self.cache['working_tokens'].append({'text':'Synthetic Neighbour','token_id':'p:unmodelled-name','box':box,
            'confidence':.99,'engine':'PADDLE_TH'})
        self.cache['tesseract_working_tokens'].append({'text':'Synthetic Neighbour','token_id':'tesseract:unmodelled-name',
            'box':deepcopy(box),'confidence':.99,'engine':'TESSERACT_THA_ENG','original_source_bbox':deepcopy(box),
            'recognition_transform':{'source_engine':'TESSERACT_THA_ENG','coordinate_space':'upright_image'}})
        out=self.propose();self.assertFalse([e for e in out['changes'] if e['row_index']==0])
        proof=next(p for p in out['source_contexts'] if p['row_index']==0)
        barriers=[b for b in proof['negative_row_barriers'] if b['kind']=='UNMODELED_DUAL_SOURCE_NAME_BARRIER']
        self.assertEqual(1,len(barriers));self.assertFalse(barriers[0]['positive_goods_anchor'])
        self.assertEqual(['p:unmodelled-name','tesseract:unmodelled-name'],barriers[0]['token_ids'])

    def test_overlapping_unconfirmed_canonical_row_abstains_without_guessing_side(self):
        box=[40,235,380,260]
        self.cache['working_tokens'].append({'text':'Synthetic Neighbour','token_id':'p:overlap-name','box':box,
            'confidence':.99,'engine':'PADDLE_TH'})
        self.page['product_rows'].insert(1,{'fields':{'description':{'raw_value':'MISMATCH','bbox':box,
            'token_ids':['p:overlap-name']},'quantity':None,'unit':None},'relationships':[]})
        out=self.propose();self.assertFalse([e for e in out['changes'] if e['row_index']==0])
        self.assertIn('ambiguous_or_overlapping_source_row_barrier',[e['reason'] for e in out['rejected']])

    def test_valid_same_baseline_jitter_and_different_detection_heights_pass_whole(self):
        a=next(t for t in self.cache['working_tokens'] if t['token_id']=='p:q1')
        b=next(t for t in self.cache['tesseract_working_tokens'] if t['token_id']=='tesseract:q1')
        a['box']=[530,224,570,231];b['box']=[532,218,572,250];b['original_source_bbox']=deepcopy(b['box'])
        out=self.propose();event=next(e for e in out['changes'] if e['row_index']==0 and e['field']=='quantity')
        self.assertEqual(a['box'],event['candidate']['bbox'])
        self.assertEqual(b['box'],event['candidate']['corroborating_observation']['bbox'])
        self.assertEqual(.5,event['evidence']['value_same_baseline_minimum_vertical_fraction'])


if __name__=='__main__':unittest.main()
