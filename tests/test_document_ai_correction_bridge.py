"""Synthetic source evidence, never invoice/reference answers or model calls."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'experiments'/'document_ai'))
sys.path.insert(0, str(ROOT/'src'))
from correction_bridge import propose_and_apply, _description_gap, _literal_header
from tests.test_document_ai_correction_eligibility import diagnostic
from tests.correction_source_fixture import core, parse_literal_unit


class SourceRules:
    SET = re.compile(r'\bSET\s*\d+\b|ชุด\s*\d+', re.I)
    FOOTER = re.compile(r'grand total|sub total|ยอดรวม|signature', re.I)
    NONRECEIPT_TITLE = re.compile(r'credit note|ใบลดหนี้', re.I)
    _box = staticmethod(lambda b: list(b) if isinstance(b, (list, tuple)) and len(b) == 4 else None)
    _area = staticmethod(lambda b: (b[2]-b[0])*(b[3]-b[1]))
    _cy = staticmethod(lambda b: (b[1]+b[3])/2)
    _height = staticmethod(lambda b: b[3]-b[1])
    @staticmethod
    def _intersection(a, b):
        x = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
        return x if x[0] < x[2] and x[1] < x[3] else None
    @classmethod
    def _inside(cls, a, b):
        hit = cls._intersection(a, b)
        return hit is not None and cls._area(hit)/cls._area(a) >= .98
    @staticmethod
    def _name(text):
        return len(re.findall(r'[A-Za-zก-๙]', text)) >= 3 and not SourceRules.FOOTER.search(text)
    @staticmethod
    def _protected(row):
        return (row.get('source_row_role') not in (None, '', 'goods', 'goods_detail') or
                row.get('counted_in_receiving') is False or bool(row.get('relationships')))
    @staticmethod
    def _missing(field):
        return not isinstance(field, dict) or all(field.get(k) in (None, '') for k in ('raw_value', 'normalized_value'))
    @staticmethod
    def _tokens(raw, secondary=False):
        values = []
        for t in raw:
            engine = t['engine'].upper()
            if secondary and not (engine.startswith('TESSERACT') and t['token_id'].startswith('tesseract:') and
                t.get('recognition_transform', {}).get('source_engine', '').startswith('TESSERACT') and
                t.get('recognition_transform', {}).get('coordinate_space') == 'upright_image' and
                t.get('original_source_bbox')):
                continue
            if not secondary and not engine.startswith('PADDLE'):
                continue
            values.append({**deepcopy(t), 'bbox': list(t['box']),
                'aliases': sorted(set([t['token_id']]+t.get('source_detection_ids', [])))})
        return values
    @classmethod
    def _read_cell(cls, box, primary, secondary, anchor, role, alternatives=()):
        pair = []
        for family, confidence in ((primary, .95), (secondary, .70)):
            touching = [t for t in family if cls._intersection(t['bbox'], box)]
            if len(touching) != 1:
                return None, 'complete_one_detection_per_reader_required'
            t = touching[0]
            if not cls._inside(t['bbox'], box) or cls._height(t['bbox']) > cls._height(anchor['token']['bbox'])*1.65:
                return None, 'whole_detection_crosses_cell_or_multiple_row_baselines'
            if t['confidence'] < confidence:
                return None, 'reader_confidence_below_frozen_gate'
            pair.append(t)
        a, b = pair
        if set(a['aliases']) & set(b['aliases']):
            return None, 'underlying_reader_identity_reused'
        if role == 'quantity':
            if any(not re.fullmatch(r'\d+(?:\.\d+)?', t['text']) for t in pair):
                return None, 'bare_quantity_literals_required_no_pack_arithmetic'
            try:
                if Decimal(a['text']) != Decimal(b['text']):
                    return None, 'independent_numeric_disagreement'
                value = format(Decimal(a['text']), 'f')
            except InvalidOperation:
                return None, 'numeric_literal_unresolved'
        else:
            parsed = [parse_literal_unit(t['text']) for t in pair]
            if any(not p or p['packing_raw'] or p['set_unit_requires_nonadditive_guard'] for p in parsed):
                return None, 'whole_literal_receiving_unit_required'
            if a['text'].casefold() != b['text'].casefold():
                return None, 'independent_literal_unit_disagreement'
            value = a['text']
        if any(cls._intersection(t['bbox'], box) and t['text'].casefold() != a['text'].casefold() for t in alternatives):
            return None, 'raw_alternative_nonempty_literal_disagreement'
        return {'tokens': pair, 'raw_value': a['text'], 'normalized_value': value}, None


def foreign_owners(rows, row_index, role, tokens):
    result = []
    for i, row in enumerate(rows):
        for field, value in row['fields'].items():
            if not isinstance(value, dict) or (i, field) == (row_index, role):
                continue
            for token in tokens:
                if set(value.get('token_ids', [])) & set(token['aliases']):
                    result.append({'row_index': i, 'field': field, 'candidate_token_id': token['token_id']})
    return result


HELPERS = {'rules': SourceRules, 'core': core, 'owners': SimpleNamespace(_foreign_owners=foreign_owners)}
PIN = {'path': 'synthetic-native.json', 'sha256': 'c'*64}


def fixture():
    def token(text, tid, box, secondary=False):
        value = {'text': text, 'token_id': tid, 'box': box, 'confidence': .99,
                 'engine': 'TESSERACT_THA_ENG' if secondary else 'PADDLE_TH'}
        if secondary:
            value.update(original_source_bbox=box, recognition_transform={
                'source_engine': 'TESSERACT_THA_ENG', 'coordinate_space': 'upright_image'})
        return value
    cache = {'page_number': 2, 'source_sha256': 'a'*64, 'geometry': {
        'original_size': [1000, 800], 'upright_size': [1000, 800], 'orientation_ccw': 0},
        'working_tokens': [], 'tesseract_working_tokens': [], 'targeted_views': []}
    cache['inference_inputs']={'reference':False,'human_answers':False,'Ada':False,'StockDay':False,'assistant_image_reads':0}
    page = {'page_number': 2, 'source_sha256': 'a'*64, 'coordinate_space': 'upright_image',
        'image_size': [1000, 800], 'document': {'document_type': 'invoice_or_delivery'}, 'product_rows': []}
    for text, tid, box in [('Product', 'p:h0a', [40, 120, 130, 140]), ('Description', 'p:h0b', [140, 120, 400, 140]),
        ('QTY', 'p:h1', [530, 120, 600, 140]), ('UOM', 'p:h2', [680, 120, 750, 140]), ('Amount', 'p:h3', [830, 120, 950, 140])]:
        cache['working_tokens'].append(token(text, tid, box))
    for i, y in enumerate((220, 320), 1):
        parts = [token('Synthetic', f'p:d{i}a', [40, y, 170, y+20]), token('Product'+str(i), f'p:d{i}b', [180, y, 380, y+20])]
        cache['working_tokens'] += parts + [token(str(i*10), f'p:q{i}', [530, y, 570, y+20]),
            token('BOX', f'p:u{i}', [690, y, 750, y+20]), token('999', f'p:a{i}', [850, y, 900, y+20])]
        cache['tesseract_working_tokens'] += [token(str(i*10), f'tesseract:q{i}', [532, y+1, 572, y+19], True),
            token('Box', f'tesseract:u{i}', [692, y+1, 752, y+19], True)]
        page['product_rows'].append({'row_number': i, 'row_id': 'keep-'+str(i), 'source_row_role': 'goods_detail',
            'relationships': [], 'fields': {'description': {'raw_value': 'Synthetic Product'+str(i),
                'normalized_value': 'Synthetic Product'+str(i), 'bbox': [40, y, 380, y+20],
                'token_ids': [t['token_id'] for t in parts]},
                'quantity': {'raw_value': '99', 'normalized_value': '99', 'bbox': [850, y, 900, y+20], 'token_ids': [f'p:a{i}']},
                'unit': {'raw_value': 'LOT123', 'normalized_value': 'LOT123', 'bbox': [700, y+30, 760, y+50], 'token_ids': ['old:lot']},
                'lot': {'raw_value': 'KEEPLOT', 'normalized_value': 'KEEPLOT'}, 'supplier_code': {'raw_value': 'KEEPCODE'}}})
    cells = []
    for r, (top, bottom) in enumerate(((105,160),(205,255),(305,355))):
        intervals = [(30,135),(135,460),(510,620),(670,770),(810,970)] if r == 0 else [(30,460),(470,500),(510,620),(670,770),(810,970)]
        for c, (left,right) in enumerate(intervals):
            cells.append({'id': f'c{r}-{c}', 'table_id': 'table1', 'bbox': [left,top,right,bottom],
                'coordinate_frame': 'original_image', 'start_row_offset_idx': r, 'end_row_offset_idx': r+1,
                'start_col_offset_idx': c, 'end_col_offset_idx': c+1, 'row_span': 1, 'col_span': 1})
    observation = {'contract': 'document-ai-original-frame-geometry.v1', 'component': 'docling', 'page': 2,
        'source_image': {'path': 'never-opened', 'sha256': 'a'*64}, 'source_size': [1000,800], 'source_frame': 'original_image',
        'regions': [{'id': 'table1', 'label': 'Table', 'bbox': [20,100,980,700]}],
        'cell_association': {'cells': cells}, 'new_text_OCR_calls': 0, 'assistant_image_transcription': False}
    return page,cache,observation


class CorrectionBridgeTests(unittest.TestCase):
    def apply(self, values=None):
        return propose_and_apply(*(values or fixture()), HELPERS, PIN)

    def test_corrects_nonempty_quantity_unit_with_multitoken_names_and_split_header_cells(self):
        page,cache,obs=fixture();before=deepcopy((page,cache,obs));out=self.apply((page,cache,obs))
        audit=out['document_ai_correction_association']
        self.assertEqual(4,len(audit['changes']))
        self.assertEqual('10',out['product_rows'][0]['fields']['quantity']['raw_value'])
        self.assertEqual('BOX',out['product_rows'][0]['fields']['unit']['raw_value'])
        for old,new in zip(page['product_rows'],out['product_rows']):
            for key in ('description','lot','supplier_code'):self.assertEqual(old['fields'][key],new['fields'][key])
            self.assertEqual(old['row_id'],new['row_id'])
        self.assertEqual(page['document'],out['document']);self.assertEqual(before,(page,cache,obs))
        change=audit['changes'][0]
        self.assertEqual(change['before'],change['candidate']['prior_source_evidence'])
        self.assertTrue(change['evidence']['role_header_token_ids'])
        self.assertEqual(2,len(change['evidence']['anchor_token_ids']))

    def test_correct_old_fields_are_not_rewritten(self):
        page,cache,obs=fixture()
        for i,row in enumerate(page['product_rows'],1):
            row['fields']['quantity']={'raw_value':str(i*10),'normalized_value':str(i*10),'special_old_metadata':'keep'}
            row['fields']['unit']={'raw_value':'Box','normalized_value':'Box','special_old_metadata':'keep'}
        out=self.apply((page,cache,obs));self.assertEqual(page['product_rows'],out['product_rows'])
        self.assertFalse(out['document_ai_correction_association']['changes'])

    def test_diagnostic_only_history_can_correct_without_consuming_historical_answers(self):
        values=fixture()
        for row in values[0]['product_rows']:
            row['relationships']=[diagnostic()]
            row['relationships'][0]['candidate']['raw_value']='NEVER USE THIS AS AN ANSWER'
        prior=deepcopy(values[0]);out=self.apply(values)
        self.assertEqual(4,len(out['document_ai_correction_association']['changes']))
        self.assertEqual('10',out['product_rows'][0]['fields']['quantity']['raw_value'])
        for old,new in zip(prior['product_rows'],out['product_rows']):
            self.assertEqual(old['relationships'],new['relationships'])
        self.assertTrue(out['document_ai_correction_association']['row_eligibility'][0]['ignored_diagnostic_types'])

    def test_long_existing_name_can_use_bounded_adjacent_heading_text_gap(self):
        values=fixture()
        values[1]['working_tokens'].append({'text':'CODE','token_id':'p:code',
            'box':[23,120,33,140],'confidence':.99,'engine':'PADDLE_TH'})
        out=self.apply(values);audit=out['document_ai_correction_association']
        self.assertEqual(4,len(audit['changes']))
        for event in audit['changes']:
            proof=event['evidence']['description_column_proof']
            self.assertEqual('SOURCE_HEADER_TEXT_GAP',proof['method'])
            self.assertEqual([33,530],proof['bounds'])
            self.assertEqual('supplier_code',proof['left_header']['role'])
            self.assertEqual('quantity',proof['right_header']['role'])
            self.assertFalse(proof['physical_cell_borders_claimed'])
            self.assertEqual(['p:h0a','p:h0b'],[t['token_id'] for t in proof['description_header_tokens']])

    def test_name_crossing_competing_code_or_quantity_text_edge_is_refused(self):
        for side in ('left','right'):
            values=fixture();values[1]['working_tokens'].append({'text':'CODE','token_id':'p:code',
                'box':[23,120,33,140],'confidence':.99,'engine':'PADDLE_TH'})
            for i,row in enumerate(values[0]['product_rows'],1):
                tid=f'p:d{i}a' if side=='left' else f'p:d{i}b'
                token=next(t for t in values[1]['working_tokens'] if t['token_id']==tid)
                token['box'][0 if side=='left' else 2]=30 if side=='left' else 550
                row['fields']['description']['bbox'][0 if side=='left' else 2]=30 if side=='left' else 550
            with self.subTest(side=side):
                out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])
                self.assertIn('DESCRIPTION_OUTSIDE_LITERAL_DESCRIPTION_COLUMN',
                    [r['reason'] for r in out['document_ai_correction_association']['rejected']])

    def test_gap_fallback_requires_two_unambiguous_adjacent_source_headings(self):
        for mode in ('ambiguous','missing_left','low_confidence','neutral_price_boundary'):
            values=fixture()
            # Move established names left of their midpoint description band.
            values[1]['working_tokens'].append({'text':'CODE','token_id':'p:code',
                'box':[23,120,33,140],'confidence':.99,'engine':'PADDLE_TH'})
            if mode=='ambiguous':
                values[1]['working_tokens'].append({'text':'CODE','token_id':'p:code2',
                    'box':[780,120,800,140],'confidence':.99,'engine':'PADDLE_TH'})
                # The unchanged midpoint path need not use a supplier heading.
                # Force the fallback, which must never ignore that ambiguity.
                for i,row in enumerate(values[0]['product_rows'],1):
                    next(t for t in values[1]['working_tokens'] if t['token_id']==f'p:d{i}b')['box'][2]=500
                    row['fields']['description']['bbox'][2]=500
            elif mode=='missing_left':
                values[1]['working_tokens']=[t for t in values[1]['working_tokens'] if t['token_id']!='p:code']
                # Without a left role the default interval is unbounded; make
                # names exceed its other side so only the fallback is tested.
                for i,row in enumerate(values[0]['product_rows'],1):
                    next(t for t in values[1]['working_tokens'] if t['token_id']==f'p:d{i}b')['box'][2]=500
                    row['fields']['description']['bbox'][2]=500
            elif mode=='low_confidence':
                next(t for t in values[1]['working_tokens'] if t['token_id']=='p:code')['confidence']=.699
            else:
                values[1]['working_tokens'].append({'text':'PRICE','token_id':'p:price_boundary',
                    'box':[35,120,39,140],'confidence':.99,'engine':'PADDLE_TH'})
            with self.subTest(mode=mode):
                out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])

    def test_mixed_semantic_unknown_and_bonus_history_stay_protected(self):
        for kind in ('printed_free_or_compensation_candidate','printed_set_and_detail_same_goods_candidate','unknown'):
            values=fixture()
            for row in values[0]['product_rows']:row['relationships']=[diagnostic(),{'type':kind}]
            with self.subTest(kind=kind):
                out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])
                self.assertTrue(all(not x['eligible'] for x in out['document_ai_correction_association']['row_eligibility']))

    def test_source_inventory_order_is_not_header_reading_order(self):
        values=fixture();values[1]['working_tokens'].reverse();values[1]['tesseract_working_tokens'].reverse()
        out=self.apply(values)
        self.assertEqual(4,len(out['document_ai_correction_association']['changes']))
        self.assertEqual('10',out['product_rows'][0]['fields']['quantity']['raw_value'])

    def test_bounded_audit_never_applies_an_unrecorded_proposal(self):
        with patch('correction_bridge.LIMIT',1):
            out=self.apply()
        audit=out['document_ai_correction_association']
        self.assertEqual(1,len(audit['proposed']))
        self.assertLessEqual(len(audit['changes']),1)
        self.assertTrue(all((c['row_index'],c['field']) in
            {(p['row_index'],p['field']) for p in audit['proposed']} for c in audit['changes']))
        self.assertGreater(audit['truncated_decisions'],0)

    def test_foreign_price_ownership_blocks_correction(self):
        values=fixture();values[0]['product_rows'][0]['fields']['unit_price']={'raw_value':'10','token_ids':['p:q1']}
        out=self.apply(values);self.assertEqual('99',out['product_rows'][0]['fields']['quantity']['raw_value'])
        self.assertIn('PRESERVED_FOREIGN_FIELD_OWNS_SOURCE',[r['reason'] for r in out['document_ai_correction_association']['rejected']])

    def test_joint_same_row_quantity_unit_misassignment_can_vacate(self):
        values=fixture();row=values[0]['product_rows'][0]
        row['fields']['quantity']={'raw_value':'BOX','token_ids':['p:u1']}
        row['fields']['unit']={'raw_value':'10','token_ids':['p:q1']}
        out=self.apply(values)
        self.assertEqual('10',out['product_rows'][0]['fields']['quantity']['raw_value'])
        self.assertEqual('BOX',out['product_rows'][0]['fields']['unit']['raw_value'])

    def test_complete_unit_can_correct_while_quantity_reader_abstains(self):
        values=fixture();before=deepcopy(values[0]['product_rows'][0])
        values[1]['tesseract_working_tokens']=[t for t in values[1]['tesseract_working_tokens'] if t['token_id']!='tesseract:q1']
        out=self.apply(values);row=out['product_rows'][0]
        self.assertEqual(before['fields']['quantity'],row['fields']['quantity'])
        self.assertEqual('BOX',row['fields']['unit']['raw_value'])
        self.assertEqual(before['fields']['unit'],row['fields']['unit']['prior_source_evidence'])
        changed=[c for c in out['document_ai_correction_association']['changes'] if c['row_index']==0]
        self.assertEqual(['unit'],[c['field'] for c in changed])

    def test_complete_quantity_can_correct_without_inventing_unit_observation(self):
        values=fixture();before=deepcopy(values[0]['product_rows'][0])
        values[1]['tesseract_working_tokens']=[t for t in values[1]['tesseract_working_tokens'] if t['token_id']!='tesseract:u1']
        out=self.apply(values);row=out['product_rows'][0]
        self.assertEqual('10',row['fields']['quantity']['raw_value'])
        self.assertEqual(before['fields']['unit'],row['fields']['unit'])
        changed=[c for c in out['document_ai_correction_association']['changes'] if c['row_index']==0]
        self.assertEqual(['quantity'],[c['field'] for c in changed])
        self.assertNotIn('compatible_unit_source_tokens',changed[0]['evidence'])

    def test_incomplete_same_row_swap_cannot_steal_preserved_companion_source(self):
        values=fixture();row=values[0]['product_rows'][0]
        row['fields']['quantity']={'raw_value':'BOX','token_ids':['p:u1']}
        row['fields']['unit']={'raw_value':'10','token_ids':['p:q1']}
        before=deepcopy(row)
        values[1]['tesseract_working_tokens']=[t for t in values[1]['tesseract_working_tokens'] if t['token_id']!='tesseract:u1']
        out=self.apply(values)
        self.assertEqual(before,out['product_rows'][0])
        self.assertIn('PRESERVED_FOREIGN_FIELD_OWNS_SOURCE',
            [r['reason'] for r in out['document_ai_correction_association']['rejected']])

    def test_foreign_header_whole_box_intruding_from_outside_gap_is_rejected(self):
        raw=[{'text':text,'token_id':tid,'box':box,'confidence':.99,'engine':'PADDLE_TH'}
             for text,tid,box in [('Unit Price','p:price',[0,100,300,120]),
               ('Material No.','p:code',[160,100,190,120]),
               ('Description','p:desc',[200,100,260,120]),
               ('QTY','p:qty',[600,100,660,120]),('Unit','p:unit',[750,100,800,120])]]
        primary=SourceRules._tokens(raw)
        clean,_=core._read([{**t,'box':t['bbox']} for t in primary],'primary',[1000,800])
        header=_literal_header(clean,core,[1000,800])
        self.assertIsNotNone(header)
        self.assertIsNone(_description_gap([190,220,280,240],header,
            {t['token_id']:t for t in primary},SourceRules))

    def test_foreign_preserved_other_row_never_borrowed(self):
        values=fixture();values[0]['product_rows'][1]['fields']['lot']['token_ids']=['p:q1']
        out=self.apply(values);self.assertEqual('99',out['product_rows'][0]['fields']['quantity']['raw_value'])

    def test_independent_reader_disagreement_and_confidence_cannot_be_relaxed(self):
        for edit in ('disagreement','primary_confidence','secondary_confidence','same_underlying_read'):
            values=fixture();p=next(t for t in values[1]['working_tokens'] if t['token_id']=='p:q1');s=values[1]['tesseract_working_tokens'][0]
            if edit=='disagreement':s['text']='100'
            elif edit=='primary_confidence':p['confidence']=.949
            elif edit=='secondary_confidence':s['confidence']=.699
            else:p['source_detection_ids']=['shared'];s['source_detection_ids']=['shared']
            with self.subTest(edit=edit):
                out=self.apply(values);self.assertEqual('99',out['product_rows'][0]['fields']['quantity']['raw_value'])
                self.assertTrue(out['document_ai_correction_association']['rejected'])

    def test_ambiguous_overlapping_native_cells_reject_source_ownership(self):
        values=fixture();extra=deepcopy(values[2]['cell_association']['cells'][7]);extra['id']='competing';extra['start_col_offset_idx']=7;extra['end_col_offset_idx']=8
        values[2]['cell_association']['cells'].append(extra)
        out=self.apply(values);self.assertEqual('99',out['product_rows'][0]['fields']['quantity']['raw_value'])

    def test_bonus_footer_and_nonreceipt_rows_are_not_candidates(self):
        for mode in ('bonus','footer','nonreceipt'):
            values=fixture()
            if mode=='bonus':values[0]['product_rows'][0]['source_row_role']='bonus'
            elif mode=='footer':values[1]['working_tokens'].append({'text':'Grand Total','token_id':'p:footer','box':[790,220,970,240],'confidence':.99,'engine':'PADDLE_TH'})
            else:values[0]['document']['document_type']='credit_note'
            with self.subTest(mode=mode):
                out=self.apply(values);self.assertEqual('99',out['product_rows'][0]['fields']['quantity']['raw_value'])

    def test_merged_header_distinct_roles_rejected_without_using_native_text(self):
        values=fixture();values[2]['cell_association']['cells'].append({'id':'mergedheader','table_id':'table1','bbox':[500,100,780,160],
            'coordinate_frame':'original_image','start_row_offset_idx':0,'end_row_offset_idx':1,'start_col_offset_idx':2,'end_col_offset_idx':4,'row_span':1,'col_span':2,
            'raw_text':'IGNORE MODEL ANSWERS'})
        out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])
        self.assertIn('MERGED_HEADER_CONTAINS_DISTINCT_SOURCE_ROLES',[r['reason'] for r in out['document_ai_correction_association']['rejected']])

    def test_wrong_source_frame_retains_data_and_audits_rejection(self):
        values=fixture();values[2]['source_image']['sha256']='b'*64
        out=self.apply(values);self.assertEqual(values[0]['product_rows'],out['product_rows'])
        self.assertEqual('SOURCE_FRAME_REJECTED',out['document_ai_correction_association']['status'])

    def test_non_source_corrected_name_cannot_anchor(self):
        values=fixture();values[0]['product_rows'][0]['fields']['description']['raw_value']='Business dictionary replacement'
        out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])

    def test_unconfirmed_native_text_cannot_supply_missing_read(self):
        values=fixture();values[1]['tesseract_working_tokens']=[]
        for c in values[2]['cell_association']['cells']:c['raw_text']='10 BOX'
        out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])

    def test_explicit_business_or_reference_inputs_never_reach_inference(self):
        for flag in ('reference','human_answers','Ada','StockDay'):
            values=fixture();values[1]['inference_inputs'][flag]=True
            with self.subTest(flag=flag):
                out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])

    def test_shared_original_name_detection_cannot_establish_two_rows(self):
        values=fixture()
        for t in values[1]['working_tokens']:
            if t['token_id'] in ('p:d1a','p:d2a'):t['source_detection_ids']=['one-original-name-detection']
        out=self.apply(values);self.assertFalse(out['document_ai_correction_association']['changes'])
        self.assertIn('SOURCE_NAME_IDENTITY_REUSED_ACROSS_ROWS',[r['reason'] for r in out['document_ai_correction_association']['rejected']])


if __name__=='__main__':unittest.main()
