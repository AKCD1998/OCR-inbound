"""Conservative, source-only documentary admission; never rewrites document type.

An unclassified page needs a printed title and independently established goods
structure. This module reads no files, images, references or business records.
Its result authorizes only the experimental correction route, not ERP release.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
import unicodedata
from statistics import median

from correction_eligibility import assess_row
from eval_geometry import normalize

VERSION = 'document-ai-source-document-admission.v1'
TITLE_CONFIDENCE = .95
HEADER_CONFIDENCE = .70
TITLE_TOP_FRACTION = .35
LIMIT = 32
POSITIVE = frozenset(('invoice', 'tax invoice', 'delivery note',
    'ใบกำกับภาษี', 'ใบส่งสินค้า', 'ใบส่งของ', 'ใบแจ้งหนี้'))
NEGATIVE = frozenset(('credit note', 'credit memo', 'return note', 'return invoice',
    'return goods', 'debit note', 'quotation', 'purchase order', 'pro forma',
    'proforma invoice', 'pro forma invoice', 'ใบลดหนี้', 'ใบคืนสินค้า', 'ใบเพิ่มหนี้', 'ใบเสนอราคา',
    'ใบสั่งซื้อ', 'รายงานภาษี', 'รายงานภาษีซื้อ', 'รายงานภาษีขาย'))
EXCLUDED_TYPES = frozenset(('credit_note', 'credit_memo', 'return_note',
    'purchase_vat_report', 'tax_register_report', 'quotation', 'purchase_order', 'proforma'))


def _fold(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip().casefold()


def _compact(value):
    return re.sub(r'\s+', '', str(value or '')).casefold()


def _union(tokens):
    return [min(t['bbox'][0] for t in tokens), min(t['bbox'][1] for t in tokens),
            max(t['bbox'][2] for t in tokens), max(t['bbox'][3] for t in tokens)]


def _title(text):
    """Whole title segments only; reference labels/body mentions are not titles."""
    segments = [_fold(part) for part in re.split(r'[/|]', text)]
    if not segments or any(not part for part in segments):
        return None
    # A slightly garbled Thai companion title may survive literally, but it
    # cannot establish a positive title itself. Unknown English/customer/PO
    # labels, numbers and free prose cannot hide behind an exact first segment.
    if any(part not in POSITIVE | NEGATIVE and not re.fullmatch(r'ใบ[ก-๙\s]{1,48}', part)
           for part in segments):
        return None
    positives = [part for part in segments if part in POSITIVE]
    negatives = [part for part in segments if part in NEGATIVE]
    if not positives and not negatives:
        return None
    return {'positive_segments': positives, 'negative_segments': negatives,
            'printed_segments': segments}


def _field_ids(value):
    """Only established field ownership, never historical proposed answers."""
    if not isinstance(value, dict):
        return set()
    return set(value.get('token_ids') or ()) | {
        span['token_id'] for span in value.get('source_spans', ())
        if isinstance(span, dict) and isinstance(span.get('token_id'), str)}


def _non_title_owners(page):
    owners = set()
    for row in page.get('product_rows') or ():
        for field in (row.get('fields') or {}).values():
            owners.update(_field_ids(field))
    document = page.get('document') or {}
    for key in ('supplier', 'customer', 'buyer', 'supplier_name', 'customer_name',
                'invoice_number', 'invoice_date', 'purchase_order', 'reference',
                'billing_address', 'delivery_address'):
        owners.update(_field_ids(document.get(key)))
    for field in (page.get('header_fields') or {}).values():
        owners.update(_field_ids(field))
    return owners


def _groups(tokens, rules):
    """Complete contiguous same-baseline detection runs, not token substrings."""
    result = []; seen = set()
    for seed in tokens:
        family = [t for t in tokens if t['engine'] == seed['engine'] and
                  abs(rules._cy(t['bbox'])-rules._cy(seed['bbox'])) <=
                  max(rules._height(t['bbox']), rules._height(seed['bbox']))*.45]
        family.sort(key=lambda t: (t['bbox'][0], t['token_id']))
        run = []
        for token in family:
            if run and (token['bbox'][0]-run[-1]['bbox'][2] >
                        max(rules._height(token['bbox']), rules._height(run[-1]['bbox']))*1.5):
                key = tuple(t['token_id'] for t in run)
                if key not in seen:
                    seen.add(key); result.append(run)
                run = []
            run.append(token)
        if run:
            key = tuple(t['token_id'] for t in run)
            if key not in seen:
                seen.add(key); result.append(run)
    return result


def _header(primary, core, size):
    clean, _ = core._read([{**t, 'box': t['bbox']} for t in primary], 'primary', size)
    clean = [t for t in clean if t.score is not None and t.score >= HEADER_CONFIDENCE and t.cy < size[1]*.70]
    if not clean:
        return None
    parts = core._header_parts(clean)
    parts = [(r, g) for r, g in parts if not any(
        {t.id for t in g} < {t.id for t in other} for _, other in parts)]
    height = median(t.height for t in clean)
    choices = []
    lookup = {t['token_id']: t for t in primary}
    for _, seed in parts:
        cy = median(t.cy for t in seed)
        band = [(r, g) for r, g in parts if abs(median(t.cy for t in g)-cy) <= height*1.8]
        roles = {}; ambiguous = set()
        for role, words in band:
            if role in roles and abs(median(t.cx for t in words)-median(t.cx for t in roles[role])) > size[0]*.045:
                ambiguous.add(role)
            elif role not in roles or min(t.score for t in words) > min(t.score for t in roles[role]):
                roles[role] = words
        if (not {'description', 'quantity'} <= set(roles) or
            not {'unit', 'amount', 'unit_price', 'supplier_code'} & set(roles) or
            ambiguous & {'description', 'quantity'}):
            continue
        actual = {role: [lookup[t.id] for t in words] for role, words in roles.items() if role not in ambiguous}
        if (len(actual) < 3 or not {'unit', 'amount', 'unit_price', 'supplier_code'} & set(actual)):
            continue
        if any(core._role(' '.join(t['text'] for t in words)) != role for role, words in actual.items()):
            continue
        used = [t for words in actual.values() for t in words]
        if len({t['token_id'] for t in used}) != len(used):
            continue
        box = _union(used)
        if box[2]-box[0] < size[0]*.32 or box[3]-box[1] > height*4:
            continue
        choices.append((len(actual), -box[1], {'roles': actual, 'bbox': box}))
    return max(choices, key=lambda value: value[:2])[2] if choices else None


def _shared_row_line(field, tokens, rules):
    """Classify a whole printed row line; never locate substring glyphs."""
    if (len(tokens) != 1 or 'shared_detection_bbox' not in (field.get('review_flags') or ()) or
        field.get('human_approved', False) is not False or field.get('human_verified', False) is not False or
        field.get('business_correction_applied', False) is not False):
        return None
    token = tokens[0]; spans = field.get('source_spans') or []
    if (len(spans) != 1 or not isinstance(spans[0], dict) or
        spans[0].get('token_id') != token['token_id'] or spans[0].get('raw_text') != token['text'] or
        rules._box(spans[0].get('bbox')) != token['bbox'] or
        spans[0].get('engine') != token['engine'] or spans[0].get('confidence') != token['confidence'] or
        field.get('engine') != token['engine'] or field.get('confidence') != token['confidence']):
        return None
    literal = re.sub(r'\s+', ' ', str(field.get('raw_value') or '')).strip()
    printed = re.sub(r'\s+', ' ', token['text']).strip()
    if len(literal) < 6 or not rules._name(literal):
        return None
    def word(character):
        return character.isalnum() or character == '_' or unicodedata.category(character).startswith('M')
    starts = []; offset = printed.find(literal)
    while offset != -1:
        end = offset+len(literal)
        if ((offset == 0 or not word(printed[offset-1])) and
            (end == len(printed) or not word(printed[end]))):
            starts.append(offset)
        offset = printed.find(literal, offset+1)
    if len(starts) != 1:
        return None
    return {'method': 'WHOLE_SHARED_SOURCE_ROW_LINE',
            'source_span': deepcopy(spans[0]), 'canonical_description_contiguous_in_source_line': True,
            'whole_detection_provenance': True, 'substring_glyph_bbox_claimed': False,
            'name_or_identity_corrected': False, 'name_identity_proof': False}


def _anchors(page, primary, header, rules, allow_shared_row_lines=False):
    lookup = {t['token_id']: t for t in primary}
    result = []; claimed = set()
    for index, row in enumerate(page.get('product_rows') or ()):
        if not assess_row(row, rules)['eligible']:
            continue
        field = (row.get('fields') or {}).get('description') or {}
        ids = field.get('token_ids') or [s.get('token_id') for s in field.get('source_spans', ()) if isinstance(s, dict)]
        if not ids or len(ids) != len(set(ids)) or any(key not in lookup for key in ids):
            continue
        tokens = sorted([lookup[key] for key in ids], key=lambda t: (rules._cy(t['bbox']), t['bbox'][0]))
        box = _union(tokens)
        if (rules._box(field.get('bbox')) != box or box[1] <= header['bbox'][3] or
            any(t['confidence'] < HEADER_CONFIDENCE for t in tokens) or
            not rules._name(' '.join(t['text'] for t in tokens))):
            continue
        exact = _compact(field.get('raw_value')) == _compact(' '.join(t['text'] for t in tokens))
        shared = _shared_row_line(field, tokens, rules) if not exact and allow_shared_row_lines else None
        if not exact and shared is None:
            continue
        aliases = {alias for token in tokens for alias in token['aliases']}
        if aliases & claimed:
            return []
        claimed.update(aliases)
        result.append({'row_index': index, 'tokens': deepcopy(tokens), 'bbox': box,
                       'row_line_proof': shared or {'method': 'EXACT_EXISTING_SOURCE_NAME',
                           'name_or_identity_corrected': False}})
    if (len(result) < 2 or len({rules._cy(row['bbox']) for row in result}) != len(result) or
        [row['row_index'] for row in sorted(result, key=lambda row: rules._cy(row['bbox']))] !=
        [row['row_index'] for row in result]):
        return []
    # Two detections on essentially one printed baseline are not two goods
    # rows, even when their source IDs and centre coordinates differ.
    for index, first in enumerate(result):
        a = first['bbox']
        for second in result[index+1:]:
            b = second['bbox']
            if (max(a[1], b[1]) < min(a[3], b[3]) or
                abs(rules._cy(a)-rules._cy(b)) <= max(rules._height(a), rules._height(b))*.75):
                return []
    return result


def _native_structure(page, cache, primary, rules, core, observation, observation_pin):
    """Separate classification proof, with no native cell/value assignments."""
    if (not isinstance(observation, dict) or observation.get('component') != 'docling' or
        not isinstance(observation_pin, dict) or not isinstance(observation_pin.get('path'), str) or
        not observation_pin['path'] or not isinstance(observation_pin.get('sha256'), str) or
        re.fullmatch(r'[a-f0-9]{64}', observation_pin['sha256']) is None):
        return []
    try:
        regions, _ = normalize(observation, cache)
    except (ValueError, KeyError, TypeError, AttributeError):
        return []
    auxiliary = frozenset(('row_index', 'supplier_code', 'quantity', 'quantity_partial',
                           'unit', 'packing', 'unit_price', 'amount'))
    lookup = {t['token_id']: t for t in primary}; result = []
    for table_id, region in regions.items():
        inside = [t for t in primary if rules._inside(t['bbox'], region['bbox'])]
        clean, _ = core._read([{**t, 'box': t['bbox']} for t in inside], 'primary', cache['geometry']['upright_size'])
        clean = [t for t in clean if t.score is not None and t.score >= HEADER_CONFIDENCE]
        if not clean:
            continue
        parts = core._header_parts(clean)
        parts = [(role, words) for role, words in parts if role in auxiliary and not any(
            {t.id for t in words} < {t.id for t in other} for _, other in parts)]
        for _, seed in parts:
            cy = median(t.cy for t in seed); height = max(t.height for t in seed)
            band = [(role, words) for role, words in parts if
                    abs(median(t.cy for t in words)-cy) <= height*1.8]
            roles = {}; ambiguous = set()
            for role, words in band:
                if role in roles and abs(median(t.cx for t in words)-median(t.cx for t in roles[role])) > cache['geometry']['upright_size'][0]*.045:
                    ambiguous.add(role)
                elif role not in roles or min(t.score for t in words) > min(t.score for t in roles[role]):
                    roles[role] = words
            actual = {role: [lookup[t.id] for t in words] for role, words in roles.items() if role not in ambiguous}
            if len(actual) < 2 or any(core._role(' '.join(t['text'] for t in words)) != role for role, words in actual.items()):
                continue
            words = [t for group in actual.values() for t in group]
            if len({t['token_id'] for t in words}) != len(words):
                continue
            columns = sorted((_union(group) for group in actual.values()), key=lambda b: b[0])
            if any(a[2] > b[0] for a, b in zip(columns, columns[1:])):
                continue
            header = {'roles': actual, 'bbox': _union(words)}
            if header['bbox'][3]-header['bbox'][1] > height*4:
                continue
            anchors = _anchors(page, primary, header, rules, allow_shared_row_lines=True)
            anchors = [anchor for anchor in anchors if rules._inside(anchor['bbox'], region['bbox'])]
            if len(anchors) < 2:
                continue
            result.append({'proof_kind': 'TITLE_NATIVE_TABLE_SOURCE_ROWS', 'header': deepcopy(header),
                'goods_name_anchors': anchors[:LIMIT], 'goods_name_anchor_count': len(anchors),
                'native_table_roi': {'native_observation': deepcopy(observation_pin),
                    'table_id': table_id, 'bbox_upright': deepcopy(region['bbox']),
                    'coordinate_space': 'upright_image'},
                'distinct_source_heading_columns': len(columns),
                'cell_roles_or_values_assigned': False, 'native_cells_or_physical_borders_claimed': False})
    return result


def assess_document(page, cache, rules, core, observation=None, observation_pin=None):
    """Assess an upright page, retaining canonical document/fields byte-for-byte."""
    audit = {'contract': VERSION, 'eligible': False, 'canonical_document_type':
        (page.get('document') or {}).get('document_type'), 'canonical_document_type_modified': False,
        'positive_title_evidence': [], 'negative_title_evidence': [], 'structure_evidence': None,
        'reasons': [], 'reference_access': False, 'new_OCR_calls': 0, 'new_model_calls': 0,
        'source_image_decodes': 0, 'human_approved': False, 'production_activation': False}
    flags = cache.get('inference_inputs') or {}; geometry = cache.get('geometry') or {}
    size = geometry.get('upright_size')
    if (not isinstance(cache.get('source_sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', cache['source_sha256']) or
        type(cache.get('page_number')) is not int or cache['page_number'] < 1 or
        not isinstance(size, (list, tuple)) or len(size) != 2 or
        any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in size) or
        page.get('source_sha256') != cache.get('source_sha256') or
        page.get('page_number') != cache.get('page_number') or page.get('coordinate_space') != 'upright_image' or
        page.get('image_size') != size or geometry.get('machine_only') is not True or geometry.get('vision_LLM_calls') != 0 or
        any(flags.get(key) is not False for key in ('reference', 'human_answers', 'Ada', 'StockDay')) or
        flags.get('assistant_image_reads') != 0):
        audit['reasons'].append('EXPLICIT_MACHINE_ONLY_UPRIGHT_SOURCE_FRAME_REQUIRED'); return audit
    kind = audit['canonical_document_type']
    if kind in EXCLUDED_TYPES or kind not in ('invoice_or_delivery', 'unclassified'):
        audit['reasons'].append('EXPLICIT_NON_RECEIPT_OR_UNSUPPORTED_DOCUMENT_TYPE'); return audit
    primary = rules._tokens(cache.get('working_tokens', ()))
    secondary = rules._tokens(cache.get('tesseract_working_tokens', ()), True)
    views = [(str(index), rules._tokens(view.get('tokens', ())))
             for index, view in enumerate(cache.get('targeted_views', ()))]
    alternatives = [t for _, tokens in views for t in tokens]
    if len(primary)+len(secondary)+len(alternatives) > 10000:
        audit['reasons'].append('BOUNDED_SOURCE_TOKEN_INVENTORY_REQUIRED'); return audit
    clean, _ = core._read([{**t, 'box': t['bbox']} for t in primary], 'primary', size)
    valid = {t.id for t in clean}
    primary = [t for t in primary if t['token_id'] in valid and t['engine'].upper().startswith('PADDLE')]
    if len({t['token_id'] for t in primary}) != len(primary):
        audit['reasons'].append('UNIQUE_ACTUAL_PRIMARY_DETECTION_IDENTITIES_REQUIRED'); return audit
    header = _header(primary, core, size)
    bottom = size[1]*TITLE_TOP_FRACTION
    owned = _non_title_owners(page)
    for reader, tokens in [('primary', primary), ('secondary', secondary)] + [('targeted:'+name, tokens) for name, tokens in views]:
        top = [t for t in tokens if t['bbox'][3] <= bottom]
        for words in _groups(top, rules):
            claim = _title(' '.join(t['text'] for t in words))
            if claim is None:
                continue
            foreign_owned = any(set(t['aliases']) & owned for t in words)
            proof = {**claim, 'reader': reader, 'tokens': deepcopy(words), 'bbox': _union(words)}
            # Prior associations may be the very bug under investigation.
            # They cannot erase a complete printed negative document title.
            if claim['negative_segments'] and all(t['confidence'] >= HEADER_CONFIDENCE for t in words):
                if len(audit['negative_title_evidence']) < LIMIT:
                    audit['negative_title_evidence'].append({**proof, 'prior_field_ownership_present': foreign_owned})
            if (not foreign_owned and reader == 'primary' and claim['positive_segments'] and
                all(t['confidence'] >= TITLE_CONFIDENCE for t in words)):
                if len(audit['positive_title_evidence']) < LIMIT:
                    audit['positive_title_evidence'].append(proof)
    if audit['negative_title_evidence']:
        audit['reasons'].append('PRINTED_NON_RECEIPT_TITLE_CONTRADICTION'); return audit
    if kind == 'invoice_or_delivery':
        audit.update(eligible=True, admission_basis='EXISTING_INVOICE_OR_DELIVERY_SOURCE_POLICY')
        return audit
    if not audit['positive_title_evidence']:
        audit['reasons'].append('HIGH_CONFIDENCE_WHOLE_PRIMARY_DOCUMENT_TITLE_REQUIRED'); return audit
    structures = []
    if header is not None:
        anchors = _anchors(page, primary, header, rules)
        if anchors:
            structures.append({'proof_kind': 'TITLE_LITERAL_GOODS_HEADER_SOURCE_ROWS',
                'header': deepcopy(header), 'goods_name_anchors': anchors[:LIMIT],
                'goods_name_anchor_count': len(anchors), 'native_cells_or_physical_borders_claimed': False})
    structures.extend(_native_structure(page, cache, primary, rules, core, observation, observation_pin))
    for structure in structures:
        titles = [proof for proof in audit['positive_title_evidence'] if proof['bbox'][3] < structure['header']['bbox'][1]]
        if not titles:
            continue
        audit['positive_title_evidence'] = titles
        audit['structure_evidence'] = structure
        audit.update(eligible=True, admission_basis=structure['proof_kind'])
        return audit
    audit['reasons'].append('COHERENT_LITERAL_GOODS_HEADER_REQUIRED' if header is None else
                            'ORDERED_SOURCE_GOODS_NAMES_AND_TITLE_ABOVE_STRUCTURE_REQUIRED')
    return audit
