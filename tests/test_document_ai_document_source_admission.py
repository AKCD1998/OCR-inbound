"""Invented source-page evidence; no invoice/reference files or model calls."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'experiments/document_ai'))
from document_source_admission import assess_document
from tests.test_document_ai_correction_bridge import fixture, SourceRules
from tests.correction_source_fixture import core


def token(text='Tax Invoice', key='p:title', box=None, confidence=.99, secondary=False):
    box = box or [500,40,800,60]
    result = {'text':text, 'token_id':key, 'box':box, 'confidence':confidence,
              'engine':'TESSERACT_THA_ENG' if secondary else 'PADDLE_TH'}
    if secondary:
        result.update(original_source_bbox=box, recognition_transform={
            'source_engine':'TESSERACT_THA_ENG', 'coordinate_space':'upright_image'})
    return result


def source():
    page, cache, _ = fixture()
    page['document']['document_type'] = 'unclassified'
    cache['geometry'].update(machine_only=True, vision_LLM_calls=0)
    cache['working_tokens'].append(token())
    return page, cache


class DocumentSourceAdmissionTests(unittest.TestCase):
    def assess(self, values=None):
        return assess_document(*(values or source()), SourceRules, core)

    def test_unclassified_requires_printed_title_and_exact_source_goods_structure_without_type_write(self):
        values=source();before=deepcopy(values);audit=self.assess(values)
        self.assertTrue(audit['eligible']);self.assertEqual(before,values)
        self.assertEqual('unclassified',audit['canonical_document_type'])
        self.assertFalse(audit['canonical_document_type_modified'])
        self.assertFalse(audit['production_activation'])
        self.assertEqual(2,audit['structure_evidence']['goods_name_anchor_count'])
        claim=audit['positive_title_evidence'][0]['tokens'][0]
        self.assertEqual('p:title',claim['token_id']);self.assertEqual(.99,claim['confidence'])
        self.assertEqual([500,40,800,60],claim['bbox'])

    def test_existing_invoice_policy_does_not_newly_require_a_title_or_goods_header(self):
        page,cache=source();page['document']['document_type']='invoice_or_delivery'
        cache['working_tokens']=[];page['product_rows']=[]
        audit=self.assess((page,cache))
        self.assertTrue(audit['eligible'])
        self.assertEqual('EXISTING_INVOICE_OR_DELIVERY_SOURCE_POLICY',audit['admission_basis'])

    def test_explicit_non_receipt_classification_never_admitted_by_positive_printed_title(self):
        for kind in ('credit_note','return_note','purchase_vat_report','purchase_order','unknown_type'):
            values=source();values[0]['document']['document_type']=kind
            with self.subTest(kind=kind):self.assertFalse(self.assess(values)['eligible'])

    def test_exact_negative_title_veto_across_reader_families_and_existing_invoice(self):
        for text in ('Credit Note','Return Invoice','Quotation','Purchase Order','Pro Forma Invoice','ใบคืนสินค้า','รายงานภาษีซื้อ'):
            for reader in ('primary','secondary','targeted'):
                values=source();values[0]['document']['document_type']='invoice_or_delivery'
                negative=token(text,'tesseract:negative' if reader=='secondary' else 'p:negative',[500,75,800,95],.9,reader=='secondary')
                if reader=='targeted':values[1]['targeted_views']=[{'tokens':[negative]}]
                else:values[1]['working_tokens' if reader=='primary' else 'tesseract_working_tokens'].append(negative)
                with self.subTest(text=text,reader=reader):
                    audit=self.assess(values);self.assertFalse(audit['eligible'])
                    self.assertTrue(audit['negative_title_evidence'])

    def test_credit_terms_customer_po_label_and_delivery_order_are_not_negative_document_titles(self):
        for text in ('Credit Terms','Delivery Order','ใบสั่งซื้อ /Cust PO No.'):
            values=source();values[1]['working_tokens'].append(token(text,'p:ordinary',[500,75,800,95]))
            with self.subTest(text=text):
                audit=self.assess(values);self.assertTrue(audit['eligible']);self.assertFalse(audit['negative_title_evidence'])

    def test_prior_wrong_field_ownership_cannot_hide_a_whole_negative_document_title(self):
        values=source()
        values[1]['tesseract_working_tokens'].append(token('Quotation','tesseract:negative',[500,75,800,95],.90,True))
        values[0]['document']['invoice_number']={'raw_value':'UNTRUSTED_OLD_ASSOCIATION','token_ids':['tesseract:negative']}
        before=deepcopy(values);audit=self.assess(values)
        self.assertFalse(audit['eligible']);self.assertEqual(before,values)
        self.assertIn('PRINTED_NON_RECEIPT_TITLE_CONTRADICTION',audit['reasons'])
        self.assertTrue(audit['negative_title_evidence'][0]['prior_field_ownership_present'])

    def test_low_confidence_secondary_only_and_unknown_primary_titles_do_not_admit(self):
        for mode in ('low','secondary','unknown','body_reference'):
            values=source();values[1]['working_tokens']=[t for t in values[1]['working_tokens'] if t['token_id']!='p:title']
            if mode=='secondary':values[1]['tesseract_working_tokens'].append(token('Invoice','tesseract:title',secondary=True))
            else:values[1]['working_tokens'].append(token('Shipping Memo' if mode=='unknown' else 'See Invoice' if mode=='body_reference' else 'Invoice',confidence=.949 if mode=='low' else .99))
            with self.subTest(mode=mode):self.assertFalse(self.assess(values)['eligible'])

    def test_title_mentioned_in_body_customer_reference_or_product_is_not_document_title(self):
        for role in ('body','customer','reference','product','same_line_customer'):
            values=source()
            if role=='body':next(t for t in values[1]['working_tokens'] if t['token_id']=='p:title')['box']=[500,500,800,520]
            elif role in ('customer','reference'):values[0]['document'][role]={'raw_value':'Tax Invoice','token_ids':['p:title']}
            elif role=='product':values[0]['product_rows'][0]['fields']['supplier_code']={'raw_value':'Tax Invoice','token_ids':['p:title']}
            else:values[1]['working_tokens'].append(token('Customer','p:customer',[360,40,490,60]))
            with self.subTest(role=role):self.assertFalse(self.assess(values)['eligible'])

    def test_whole_adjacent_split_title_and_literal_slash_segment(self):
        for mode in ('split','slash'):
            values=source();values[1]['working_tokens']=[t for t in values[1]['working_tokens'] if t['token_id']!='p:title']
            if mode=='split':values[1]['working_tokens'] += [token('Tax','p:tax',[500,40,550,60]),token('Invoice','p:invoice',[560,40,650,60])]
            else:values[1]['working_tokens'].append(token('ใบส่งสินค้า/ใบหัวข้อทดสอบ'))
            with self.subTest(mode=mode):self.assertTrue(self.assess(values)['eligible'])
        values=source();values[1]['working_tokens'].append(token('No. 123','p:number',[810,40,900,60]))
        self.assertFalse(self.assess(values)['eligible'])

    def test_source_hash_page_frame_and_machine_provenance_are_bound(self):
        for mode in ('hash','page','space','size','human','business','llm'):
            values=source()
            if mode=='hash':values[0]['source_sha256']='b'*64
            elif mode=='page':values[0]['page_number']=3
            elif mode=='space':values[0]['coordinate_space']='original_image'
            elif mode=='size':values[0]['image_size']=[800,1000]
            elif mode=='human':values[1]['inference_inputs']['human_answers']=True
            elif mode=='business':values[1]['inference_inputs']['StockDay']=True
            else:values[1]['geometry']['vision_LLM_calls']=1
            with self.subTest(mode=mode):self.assertFalse(self.assess(values)['eligible'])

    def test_title_alone_cannot_replace_header_or_two_ordered_source_goods_names(self):
        for mode in ('header','one_row','changed_name','bonus','row_order','shared_alias'):
            values=source()
            if mode=='header':values[1]['working_tokens']=[t for t in values[1]['working_tokens'] if not t['token_id'].startswith('p:h')]
            elif mode=='one_row':values[0]['product_rows']=values[0]['product_rows'][:1]
            elif mode=='changed_name':values[0]['product_rows'][0]['fields']['description']['raw_value']='Not the printed name'
            elif mode=='bonus':values[0]['product_rows'][0]['source_row_role']='bonus'
            elif mode=='row_order':values[0]['product_rows'].reverse()
            else:
                for t in values[1]['working_tokens']:
                    if t['token_id'] in ('p:d1a','p:d2a'):t['source_detection_ids']=['shared-name']
            with self.subTest(mode=mode):self.assertFalse(self.assess(values)['eligible'])

    def test_ambiguous_only_third_heading_cannot_count_as_structure_support(self):
        values=source()
        values[1]['working_tokens']=[t for t in values[1]['working_tokens'] if t['token_id']!='p:h3']
        values[1]['working_tokens'].append(token('Unit','p:second-uom',[800,120,850,140]))
        audit=self.assess(values)
        self.assertFalse(audit['eligible'])
        self.assertIn('COHERENT_LITERAL_GOODS_HEADER_REQUIRED',audit['reasons'])

    def native_source(self):
        page,cache=source();_,_,observation=fixture()
        # No exact description-heading role remains. This is an explicit
        # alternative classification proof, never a repaired field heading.
        cache['working_tokens']=[t for t in cache['working_tokens'] if t['token_id'] not in ('p:h0a','p:h0b')]
        observation['cell_association']['cells']=[]
        pin={'path':'invented-native-source.json','sha256':'c'*64}
        return page,cache,observation,pin

    def test_native_table_roi_and_auxiliary_headers_classify_without_assigning_cells_or_values(self):
        page,cache,observation,pin=self.native_source();before=deepcopy((page,cache,observation))
        audit=assess_document(page,cache,SourceRules,core,observation,pin)
        self.assertTrue(audit['eligible']);self.assertEqual(before,(page,cache,observation))
        self.assertEqual('TITLE_NATIVE_TABLE_SOURCE_ROWS',audit['admission_basis'])
        proof=audit['structure_evidence']
        self.assertEqual(pin,proof['native_table_roi']['native_observation'])
        self.assertGreaterEqual(proof['distinct_source_heading_columns'],2)
        self.assertFalse(proof['cell_roles_or_values_assigned'])
        self.assertFalse(proof['native_cells_or_physical_borders_claimed'])
        self.assertFalse(audit['canonical_document_type_modified'])

    def test_native_alternative_rejects_unbound_fake_or_outside_table_region(self):
        for mode in ('pin','component','hash','frame','not_table','outside'):
            page,cache,observation,pin=self.native_source()
            if mode=='pin':pin=None
            elif mode=='component':observation['component']='unknown'
            elif mode=='hash':observation['source_image']['sha256']='b'*64
            elif mode=='frame':observation['source_frame']='unregistered_frame'
            elif mode=='not_table':observation['regions'][0]['label']='Text'
            else:observation['regions'][0]['bbox']=[20,100,980,200]
            with self.subTest(mode=mode):self.assertFalse(assess_document(page,cache,SourceRules,core,observation,pin)['eligible'])

    def test_native_alternative_still_requires_exact_title_two_source_names_and_proper_order(self):
        for mode in ('no_title','one_anchor','order','source_name','one_aux_role','title_below_header'):
            page,cache,observation,pin=self.native_source()
            if mode=='no_title':cache['working_tokens']=[t for t in cache['working_tokens'] if t['token_id']!='p:title']
            elif mode=='one_anchor':page['product_rows']=page['product_rows'][:1]
            elif mode=='order':page['product_rows'].reverse()
            elif mode=='source_name':page['product_rows'][0]['fields']['description']['raw_value']='Unconfirmed business name'
            elif mode=='one_aux_role':cache['working_tokens']=[t for t in cache['working_tokens'] if t['token_id'] not in ('p:h2','p:h3')]
            else:next(t for t in cache['working_tokens'] if t['token_id']=='p:title')['box']=[500,170,800,190]
            with self.subTest(mode=mode):self.assertFalse(assess_document(page,cache,SourceRules,core,observation,pin)['eligible'])

    def test_native_alternative_cannot_make_overlapping_auxiliary_headings_distinct_columns(self):
        page,cache,observation,pin=self.native_source()
        cache['working_tokens']=[t for t in cache['working_tokens'] if t['token_id']!='p:h3']
        next(t for t in cache['working_tokens'] if t['token_id']=='p:h2')['box']=[550,120,700,140]
        self.assertFalse(assess_document(page,cache,SourceRules,core,observation,pin)['eligible'])

    def test_two_different_source_names_on_overlapping_printed_baselines_are_not_two_rows(self):
        for native in (False,True):
            values=self.native_source() if native else (*source(),None,None)
            page,cache,observation,pin=values
            second=page['product_rows'][1]['fields']['description'];second['bbox'][1:4:2]=[221,241]
            for t in cache['working_tokens']:
                if t['token_id'] in ('p:d2a','p:d2b'):t['box'][1:4:2]=[221,241]
            with self.subTest(native=native):
                self.assertFalse(assess_document(page,cache,SourceRules,core,observation,pin)['eligible'])

    def shared_source(self):
        page,cache,observation,pin=self.native_source()
        for i,row in enumerate(page['product_rows'],1):
            cache['working_tokens']=[t for t in cache['working_tokens'] if t['token_id']!=f'p:d{i}b']
            whole=next(t for t in cache['working_tokens'] if t['token_id']==f'p:d{i}a')
            whole['text']=f'IC000{i}-Synthetic Product{i}'
            whole['box']=deepcopy(row['fields']['description']['bbox'])
            field=row['fields']['description']
            field.update(token_ids=[whole['token_id']],engine=whole['engine'],confidence=whole['confidence'],
                review_flags=['shared_detection_bbox'],source_spans=[{
                    'token_id':whole['token_id'],'raw_text':whole['text'],'bbox':deepcopy(whole['box']),
                    'engine':whole['engine'],'confidence':whole['confidence']}])
        return page,cache,observation,pin

    def test_shared_whole_source_row_line_can_classify_without_claiming_name_or_glyph_correction(self):
        page,cache,observation,pin=self.shared_source();before=deepcopy((page,cache,observation))
        audit=assess_document(page,cache,SourceRules,core,observation,pin)
        self.assertTrue(audit['eligible']);self.assertEqual(before,(page,cache,observation))
        self.assertEqual('TITLE_NATIVE_TABLE_SOURCE_ROWS',audit['admission_basis'])
        for anchor in audit['structure_evidence']['goods_name_anchors']:
            proof=anchor['row_line_proof']
            self.assertEqual('WHOLE_SHARED_SOURCE_ROW_LINE',proof['method'])
            self.assertFalse(proof['substring_glyph_bbox_claimed'])
            self.assertFalse(proof['name_or_identity_corrected'])
            self.assertFalse(proof['name_identity_proof'])

    def test_shared_source_classification_rejects_wrong_span_provenance_and_fuzzy_substrings(self):
        for mode in ('span_text','span_box','span_engine','span_confidence','span_id','no_flag','fuzzy','part_word','too_short','repeated_part','business'):
            page,cache,observation,pin=self.shared_source();field=page['product_rows'][0]['fields']['description'];span=field['source_spans'][0]
            if mode=='span_text':span['raw_text']='Different unconfirmed printed line'
            elif mode=='span_box':span['bbox'][2]-=1
            elif mode=='span_engine':span['engine']='OTHER'
            elif mode=='span_confidence':span['confidence']=.98
            elif mode=='span_id':span['token_id']='another-source-id'
            elif mode=='no_flag':field['review_flags']=[]
            elif mode=='fuzzy':field['raw_value']='Synthetlc Product1'
            elif mode=='part_word':field['raw_value']='nthetic Product1'
            elif mode=='too_short':field['raw_value']='IC'
            elif mode=='repeated_part':
                whole=next(t for t in cache['working_tokens'] if t['token_id']=='p:d1a')
                whole['text']='Synthetic Product1 / Synthetic Product1';span['raw_text']=whole['text']
            else:field['business_correction_applied']=True
            with self.subTest(mode=mode):self.assertFalse(assess_document(page,cache,SourceRules,core,observation,pin)['eligible'])

    def test_shared_whole_source_rows_must_not_reuse_identity_or_cross_the_actual_table(self):
        for mode in ('shared_id','source_alias','outside_roi'):
            page,cache,observation,pin=self.shared_source()
            if mode=='shared_id':
                page['product_rows'][1]['fields']['description']=deepcopy(page['product_rows'][0]['fields']['description'])
            elif mode=='source_alias':
                for t in cache['working_tokens']:
                    if t['token_id'] in ('p:d1a','p:d2a'):t['source_detection_ids']=['shared-underlying-line']
            else:observation['regions'][0]['bbox']=[50,100,980,700]
            with self.subTest(mode=mode):self.assertFalse(assess_document(page,cache,SourceRules,core,observation,pin)['eligible'])


if __name__=='__main__':unittest.main()
