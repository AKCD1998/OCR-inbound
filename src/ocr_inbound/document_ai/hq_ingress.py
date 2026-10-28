"""Source-bound automatic proposals; imports no reader or fits a model on import.

The command-line worker runs on HQ under the shared supervised queue. These pure
adapters preserve TSV source tokens and distinguish catalogue proposals from ink.
"""
from __future__ import annotations

import csv
import copy
from collections import defaultdict
from io import StringIO
import math


def tsv_tokens(text, width, height):
    tokens, rejected = [], []
    for i, row in enumerate(csv.DictReader(StringIO(text), delimiter='\t')):
        if row.get('level') != '5' or not row.get('text', '').strip():
            continue
        try:
            x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
            confidence = float(row['conf']) / 100
            if not (math.isfinite(confidence) and 0 <= confidence <= 1 and
                    0 <= x < x+w <= width and 0 <= y < y+h <= height):
                raise ValueError('Source geometry/confidence outside frame')
            tokens.append({'token_id': f'tesseract:{i}', 'text': row['text'],
                           'box': [[x,y],[x+w,y],[x+w,y+h],[x,y+h]],
                           'confidence': confidence, 'engine': 'TESSERACT_TSV',
                           'line_id': ':'.join(row.get(k,'') for k in
                               ('page_num','block_num','par_num','line_num'))})
        except (ValueError, KeyError, TypeError):
            rejected.append({'index': i, 'reason': 'invalid_TSV_geometry_or_confidence'})
    return tokens, rejected


def field_from_parser(field, reason='อ่านอัตโนมัติ ยังรอผู้ตรวจยืนยัน'):
    if not field:
        return {'raw': None, 'normalized': None, 'bbox': None, 'reason': reason}
    return {'raw': field.get('raw_value'), 'normalized': field.get('normalized_value'),
            'bbox': field.get('bbox'), 'bbox_frame': 'original_image',
            'reason': reason, 'engine': field.get('engine'),
            'source_spans': field.get('source_spans', []),
            'confidence': field.get('confidence'),
            'issues': field.get('review_flags', [])}

def needs_retry(parsed):
    return not parsed['product_rows'] or any(not row['fields'].get(key) for row in parsed['product_rows']
                                            for key in ('description','quantity','unit'))

def merge_retry(primary, secondary):
    """A second automatic reading may fill a missing field on ONE exact owner.

    It never takes a neighbour's quantity, overwrites a conflicting primary value,
    or calls agreement between two modes of one engine independent verification.
    """
    result=copy.deepcopy(primary)
    if not result['product_rows'] and secondary['product_rows']:
        result=copy.deepcopy(secondary)
        result['review_flags'].append('secondary_layout_read_requires_human_review')
        return result
    def value(row,key):
        f=row['fields'].get(key)
        return str(f.get('normalized_value') or '').strip() if f else ''
    for row in result['product_rows']:
        code,description,lot=(value(row,key) for key in ('supplier_code','description','lot'))
        matches=[r for r in secondary['product_rows'] if
                 ((code and value(r,'supplier_code')==code) or
                  (not code and description and value(r,'description')==description)) and
                 (not lot or value(r,'lot')==lot)]
        if len(matches)!=1:
            row['review_flags'].append('secondary_read_row_owner_not_unique');continue
        for key in ('quantity','unit','lot','exp_date','mfg_date'):
            first,second=value(row,key),value(matches[0],key)
            if first and second and first!=second:
                row['review_flags'].append('two_readings_disagree_'+key)
            elif not first and second:
                row['fields'][key]=copy.deepcopy(matches[0]['fields'][key])
                row['fields'][key].setdefault('review_flags',[]).append('secondary_PSM_read_unverified')
                row['review_flags'].append('secondary_PSM_filled_missing_'+key)
    return result


def adapt_page(parsed, tokens, page_id, matcher=None):
    """No SKU is passed as OCR text, and no supplier code becomes an internal SKU."""
    rows = []
    for n, item in enumerate(parsed['product_rows'], 1):
        fields = {k: field_from_parser(v) for k,v in item['fields'].items()}
        query = {'description': fields.get('description', {}).get('raw'),
                 'supplier_code': fields.get('supplier_code', {}).get('raw')}
        match = matcher.match(query) if matcher and query['description'] else None
        candidate = match.get('proposed_code') if match else None
        fields['product_code'] = {'raw': None, 'normalized': candidate,
            'catalogue': candidate, 'bbox': None,
            'reason': 'ข้อเสนอจับคู่ทะเบียน ไม่ใช่รหัสที่อ่านจากภาพ ต้องตรวจ SKU/สูตร/ขนาด',
            'alternatives': [{'value':c['code'],'label':c['code']+' · '+' / '.join(c.get('names',[])),
                              'reason':' / '.join(c.get('blocks',[])) or 'ตัวเลือกใกล้เคียง ยังไม่ใช่คำยืนยัน'}
                             for c in match.get('candidates', [])] if match else [],
            'matching': match, 'authority': 'catalogue_match_proposal'}
        for key in ('description', 'quantity', 'unit', 'lot', 'exp_date'):
            fields.setdefault(key, field_from_parser(None))
        issues = list(dict.fromkeys(item.get('review_flags', []) +
                                    ['SKU และแถวสินค้ายังไม่ยืนยันโดยมนุษย์']))
        if not candidate: issues.append('ยังจับคู่ SKU ไม่ได้ ห้ามเติมรหัสผู้ขายแทน')
        rows.append({'id': f'{page_id}-r{n}', 'page_id': page_id,
                     'line_kind': 'purchase', 'issues': issues, 'fields': fields})
    # Page metadata and every unparsed line stay visible at the FINAL review.
    # A page with zero goods is explicitly unresolved, not silently "complete".
    document = parsed.get('document', {})
    fields = {k: field_from_parser(document.get(k)) for k in ('invoice_number','invoice_date')}
    fields['description'] = {'raw': '\n'.join(t['text'] for t in tokens),
                            'normalized': None, 'bbox': None,
                            'reason': 'คำอ่านทั้งหน้าสำหรับตรวจรายการตกหล่น ไม่ใช่รายการสินค้า'}
    rows.append({'id': f'{page_id}-context', 'page_id': page_id, 'line_kind': 'context',
                 'issues': list(parsed.get('review_flags', [])) +
                    (['ไม่พบแถวสินค้า ต้องเพิ่มรายการจากต้นฉบับก่อนส่งต่อ หรือยืนยันว่าไม่มีสินค้า']
                     if not parsed['product_rows'] else ['ต้องตรวจว่ารายการสินค้าไม่ตกหล่น']),
                 'fields': fields})
    return rows
