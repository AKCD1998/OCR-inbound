"""Experimental source-only corrections to existing quantity/unit fields.

Native cells propose ownership, never text. Literal headers and two saved goods
anchors establish columns/rows; independent actual readers establish values.
No files, images, references, business catalogues or models are read here.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
from statistics import median
from eval_geometry import assign, digest, normalize
from correction_eligibility import BONUS, assess_row

VERSION = 'document-ai-source-corrections.v6'
LIMIT = 256
EDITABLE = ('quantity', 'unit')


def _union(tokens):
    return [min(t['bbox'][0] for t in tokens), min(t['bbox'][1] for t in tokens),
            max(t['bbox'][2] for t in tokens), max(t['bbox'][3] for t in tokens)]


def _compact(value):
    return re.sub(r'\s+', '', str(value or '')).casefold()


def _literal_header(clean, core, size):
    """Group exact printed phrases, including same-role subphrase suppression.

    'Description' inside 'Product Description' is one heading, not two distant
    competing description columns. Unit inside Unit Price is likewise never
    an independent UOM heading. No fuzzy role repair or supplier order is used.
    """
    if not clean:
        return None
    parts = core._header_parts([t for t in clean if t.cy < size[1] * .70])
    parts = [(role, words) for role, words in parts if not any(
        {t.id for t in words} < {t.id for t in other} for _, other in parts)]
    mh = median(t.height for t in clean)
    choices = []
    for _, seed in parts:
        y = median(t.cy for t in seed)
        band = [(r, g) for r, g in parts if abs(median(t.cy for t in g)-y) <= mh*1.8]
        groups = {}
        for role, words in band:
            groups.setdefault(role, []).append(words)
        anchors, ambiguous = {}, []
        for role, variants in groups.items():
            chosen = max(variants, key=lambda g: (min(t.score or 0 for t in g), sum(len(t.text) for t in g)))
            box = core._bbox(chosen);cx = (box[0]+box[2])/2
            if any(abs((core._bbox(g)[0]+core._bbox(g)[2])/2-cx) > size[0]*.045 for g in variants):
                ambiguous.append(role)
            else:
                anchors[role] = chosen
        if not {'description', 'quantity', 'unit'}.issubset(anchors) or set(ambiguous).intersection(('description', *EDITABLE)):
            continue
        selected = list(dict.fromkeys(t for g in anchors.values() for t in g))
        box = core._bbox(selected)
        if box[2]-box[0] < size[0]*.32 or box[3]-box[1] > mh*4:
            continue
        used = {t.id for t in selected}
        for token in clean:
            if (token.id not in used and box[1] <= token.cy <= box[3] and token.height <= mh*1.8 and
                re.match(r'^(?:ราคา|หน่วย.{1,5}$|ส่วนลด|DISCOUNT\b|PR[I1]CE\b)', token.text, re.I) and
                not any(abs(token.cx-(core._bbox(g)[0]+core._bbox(g)[2])/2) <= mh for g in anchors.values())):
                anchors['unclassified_numeric_boundary_'+str(len(anchors))] = (token,)
        centers = sorted(((core._bbox(g)[0]+core._bbox(g)[2])/2, role) for role, g in anchors.items())
        if any(b[0]-a[0] < mh*.7 for a,b in zip(centers, centers[1:])):
            continue
        bounds = {role: [0 if i == 0 else (centers[i-1][0]+cx)/2,
                         size[0] if i+1 == len(centers) else (cx+centers[i+1][0])/2]
                  for i,(cx,role) in enumerate(centers)}
        choices.append((len(anchors), -box[1], {'anchors': anchors, 'bounds': bounds,
            'bottom': box[3], 'bbox': box, 'mh': mh, 'ambiguous': ambiguous}))
    return max(choices, key=lambda v:v[:2])[2] if choices else None


def _old_same(old, new, role):
    if not isinstance(old, dict):
        return False
    def same(a, b):
        if role == 'quantity':
            try:
                return Decimal(str(a).replace(',', '')) == Decimal(str(b).replace(',', ''))
            except (InvalidOperation, ValueError):
                return False
        return _compact(a) == _compact(b)
    return (same(old.get('raw_value'), new['raw_value']) and
            (old.get('normalized_value') in (None, '') or same(old['normalized_value'], new['normalized_value'])))


def _description_gap(box, header, lookup, rules):
    """A bounded text gap, never a physical-cell or native-header claim.

    Short centred headings do not define a receiving row's text width. The
    fallback is bounded by BOTH nearest competing heading text edges, including
    neutral boundaries. Every established name still needs whole native-body
    ownership and all later quantity/unit proofs remain unchanged.
    """
    if header['ambiguous']:
        return None
    groups = []
    for role, words in header['anchors'].items():
        if not words or any(t.id not in lookup or lookup[t.id]['confidence'] < .70 for t in words):
            return None
        tokens = [lookup[t.id] for t in words]
        bounds = _union(tokens)
        groups.append(((bounds[0]+bounds[2])/2, role, tokens, bounds))
    groups.sort(key=lambda item: (item[0], item[1]))
    indices = [i for i, item in enumerate(groups) if item[1] == 'description']
    if len(indices) != 1 or indices[0] in (0, len(groups)-1):
        return None
    index = indices[0]
    _, _, description, description_box = groups[index]
    _, left_role, left, left_box = groups[index-1]
    _, right_role, right, right_box = groups[index+1]
    left_edge, right_edge = left_box[2], right_box[0]
    if (left_role == right_role or not left_edge < description_box[0] < description_box[2] < right_edge
            or not left_edge <= box[0] < box[2] <= right_edge):
        return None
    # Heading text may extend into this gap even if its centre is elsewhere.
    # Check every coherent whole role/boundary envelope, never centres alone.
    if any(role != 'description' and bounds[0] < right_edge and bounds[2] > left_edge
           for _, role, _, bounds in groups):
        return None
    return {'method': 'SOURCE_HEADER_TEXT_GAP',
            'description_header_tokens': deepcopy(description),
            'left_header': {'role': left_role, 'tokens': deepcopy(left)},
            'right_header': {'role': right_role, 'tokens': deepcopy(right)},
            'bounds': [left_edge, right_edge], 'physical_cell_borders_claimed': False}


def _anchor(row, primary, matched, table, header, rules):
    field = (row.get('fields') or {}).get('description') or {}
    ids = field.get('token_ids') or [s.get('token_id') for s in field.get('source_spans', [])]
    if not ids or len(set(ids)) != len(ids):
        return None, 'SAVED_DESCRIPTION_TOKEN_IDS_REQUIRED'
    lookup = {t['token_id']: t for t in primary}
    if any(key not in lookup for key in ids):
        return None, 'SAVED_DESCRIPTION_TOKEN_MISSING_FROM_PRIMARY_SOURCE'
    tokens = sorted([lookup[key] for key in ids], key=lambda t: (rules._cy(t['bbox']), t['bbox'][0], t['token_id']))
    box = _union(tokens)
    if (rules._box(field.get('bbox')) != box or
        _compact(field.get('raw_value')) != _compact(' '.join(t['text'] for t in tokens)) or
        not rules._name(' '.join(t['text'] for t in tokens)) or
        any(t['confidence'] < .70 for t in tokens) or not rules._inside(box, table['bbox'])):
        return None, 'MULTITOKEN_DESCRIPTION_NOT_EXACT_SOURCE_UNION'
    eligibility = assess_row(row, rules)
    if not eligibility['eligible']:
        return None, 'PROTECTED_BONUS_OR_NON_RECEIPT_ROW'
    heights = [rules._height(t['bbox']) for t in tokens]
    if rules._height(box) > max(heights) * 1.8 or box[1] <= header['bottom']:
        return None, 'MERGED_MULTILINE_OR_HEADER_DESCRIPTION'
    left, right = header['bounds']['description']
    description_proof = None
    if not all(rules._inside(t['bbox'], [left, header['bottom'], right, table['bbox'][3]]) for t in tokens):
        description_proof = _description_gap(box, header, lookup, rules)
        if description_proof is None:
            return None, 'DESCRIPTION_OUTSIDE_LITERAL_DESCRIPTION_COLUMN'
    owners = [matched.get(t['token_id']) for t in tokens]
    if any(c is None for c in owners) or len({c['row'] for c in owners}) != 1:
        return None, 'DESCRIPTION_NATIVE_ROW_NOT_UNIQUE'
    if any(c['row'] < 0 for c in owners):
        return None, 'INVALID_NATIVE_ANCHOR_ROW'
    return {'token': {**tokens[0], 'bbox': box}, 'tokens': tokens,
            'native_row': owners[0]['row'], 'native_columns': sorted({c['column'] for c in owners}),
            'row_eligibility': eligibility, 'description_column_proof': description_proof}, None


def _field(value, role, before, evidence, observation_pin):
    primary, secondary = value['tokens']
    return {'raw_value': primary['text'], 'normalized_value': value['normalized_value'],
        'bbox': deepcopy(primary['bbox']), 'token_ids': [primary['token_id']],
        'engine': primary['engine'], 'confidence': primary['confidence'],
        'source_bbox_kind': 'whole_actual_detection',
        'source_spans': [{'token_id': primary['token_id'], 'raw_text': primary['text'],
            'bbox': deepcopy(primary['bbox']), 'confidence': primary['confidence'], 'engine': primary['engine']}],
        'corroborating_observation': deepcopy(secondary),
        'association_basis': 'source_header_multitoken_existing_row_independent_readers_correction',
        'model_geometry_evidence': {'native_observation': deepcopy(observation_pin),
            'table_id': evidence['table_id'], 'cell_id': evidence['target_cell_id'],
            'row': evidence['native_row'], 'content_envelope_not_physical_border': True},
        'source_header_column_and_row_band': deepcopy(evidence['source_header_band']),
        'prior_source_evidence': deepcopy(before), 'printed_literal_value': primary['text'],
        'value_semantics': 'printed_literal_and_literal_normalization_only',
        'business_correction_applied': False, 'quantity_multiplication_applied': False,
        'human_approved': False, 'review_flags': ['experimental_source_correction_requires_final_review']}


def _native_propose_and_apply(page, cache, observation, helpers, observation_pin):
    """Return a conserved copy plus bounded proposal, rejection and revision audit."""
    frozen = digest([page, cache, observation]);out = deepcopy(page)
    rules, core, foreign = (helpers[k] for k in ('rules', 'core', 'owners'))
    audit = {'contract': VERSION, 'status': 'ABSTAINED', 'proposed': [], 'accepted': [],
        'rejected': [], 'changes': [], 'truncated_decisions': 0, 'native_observation': deepcopy(observation_pin),
        'new_OCR_calls': 0, 'new_model_calls': 0, 'reference_access': False,
        'assistant_image_reads': False, 'source_confidence_gates': [.95, .70],
        'minimum_whole_word_overlap': .8, 'maximum_competing_overlap': .2,
        'human_approved': False, 'nonempty_correction_enabled': True,
        'row_eligibility': []}
    out['document_ai_correction_association'] = audit
    rows = out.get('product_rows', [])
    def record(bucket, value):
        if len(audit[bucket]) < LIMIT:
            audit[bucket].append(deepcopy(value))
            return True
        else:
            audit['truncated_decisions'] += 1
            return False
    def reject(reason, row_index=None, role=None, evidence=None, candidate=None):
        old = (rows[row_index].get('fields') or {}).get(role) if row_index is not None and role else None
        evidence = deepcopy(evidence or {})
        if row_index is not None:
            evidence['row_eligibility'] = assess_row(rows[row_index], rules)
        record('rejected', {'row_index': row_index, 'field': role, 'before': old,
            'candidate': candidate, 'reason': reason, 'evidence': evidence})
    flags = cache.get('inference_inputs') or {}
    if (any(flags.get(k) is not False for k in ('reference', 'human_answers', 'Ada', 'StockDay')) or
        flags.get('assistant_image_reads') != 0):
        reject('EXPLICIT_MACHINE_ONLY_RUNTIME_INPUTS_REQUIRED');return out
    try:
        regions, cells = normalize(observation, cache)
    except (ValueError, KeyError, TypeError) as exc:
        reject('SOURCE_FRAME_OR_NATIVE_PROVENANCE_REJECTED', evidence={'error_type': type(exc).__name__})
        audit['status'] = 'SOURCE_FRAME_REJECTED';return out
    if (page.get('source_sha256') != cache['source_sha256'] or page.get('page_number') != cache['page_number'] or
        page.get('coordinate_space') != 'upright_image' or page.get('image_size') != cache['geometry']['upright_size']):
        reject('ESTABLISHED_INVOICE_UPRIGHT_SOURCE_FRAME_REQUIRED');return out
    classifier=helpers.get('document_admission')
    if classifier is not None:
        admission=classifier.assess_document(page,cache,rules,core,
            observation=observation,observation_pin=observation_pin)
        if digest([page,cache,observation]) != frozen:
            raise ValueError('Document admission mutated retained evidence')
        audit['document_admission']=deepcopy(admission)
        if admission.get('eligible') is not True:
            reject('DOCUMENT_SOURCE_ADMISSION_REJECTED');return out
    elif (page.get('document') or {}).get('document_type') != 'invoice_or_delivery':
        reject('ESTABLISHED_INVOICE_UPRIGHT_SOURCE_FRAME_REQUIRED');return out
    if observation.get('component') != 'docling' or not cells:
        reject('USABLE_SOURCE_BOUND_NATIVE_TABLE_CELLS_REQUIRED');return out
    audit['row_eligibility'] = [{'row_index': i, **assess_row(row, rules)}
                              for i, row in enumerate(rows[:LIMIT])]
    primary = rules._tokens(cache.get('working_tokens', []))
    secondary = rules._tokens(cache.get('tesseract_working_tokens', []), True)
    alternatives = []
    for view in cache.get('targeted_views', []):
        alternatives.extend(rules._tokens(view.get('tokens', [])))
    pending = []
    for table_id, table in regions.items():
        tc = [c for c in cells if c['table_id'] == table_id]
        inside = [t for t in primary if rules._inside(t['bbox'], table['bbox'])]
        clean, _ = core._read([{**t, 'box': t['bbox']} for t in inside], 'primary', cache['geometry']['upright_size'])
        header = _literal_header(clean, core, cache['geometry']['upright_size'])
        if not header or 'description' not in header['anchors'] or not set(EDITABLE).issubset(header['anchors']):
            reject('COHERENT_SEPARATE_LITERAL_DESCRIPTION_QUANTITY_UNIT_HEADERS_REQUIRED', evidence={'table_id': table_id});continue
        if (set(EDITABLE).intersection(header['ambiguous']) or
            any(t.score is None or t.score < .70 for words in header['anchors'].values() for t in words)):
            reject('AMBIGUOUS_OR_LOW_CONFIDENCE_LITERAL_HEADER', evidence={'table_id': table_id});continue
        header_lookup = {t['token_id']: t for t in inside}
        header_tokens = {role: [header_lookup[w.id] for w in words]
                         for role, words in header['anchors'].items()}
        if any(core._role(' '.join(t['text'] for t in header_tokens[r])) != r for r in ('description', *EDITABLE)):
            reject('WHOLE_PRIMARY_LITERAL_HEADER_GROUP_REQUIRED', evidence={'table_id': table_id});continue
        merged = False
        for native in observation.get('cell_association', {}).get('cells', []):
            if native.get('table_id') != table_id or not (native.get('col_span', 1) > 1 or native.get('row_span', 1) > 1):
                continue
            from component_common import rotate_box, valid_box
            if not valid_box(native.get('bbox'), cache['geometry']['original_size']):
                continue
            box = rotate_box(native['bbox'], cache['geometry']['original_size'], cache['geometry']['orientation_ccw'])
            touched = {role for role, tokens in header_tokens.items() if any(rules._inside(t['bbox'], box) for t in tokens)}
            if len(touched) > 1 and touched.intersection(EDITABLE):
                merged = True
        if merged:
            reject('MERGED_HEADER_CONTAINS_DISTINCT_SOURCE_ROLES', evidence={'table_id': table_id});continue
        if any(t['bbox'][3] <= header['bottom'] and rules.NONRECEIPT_TITLE.search(t['text']) for t in primary + secondary + alternatives):
            reject('SOURCE_NON_RECEIPT_TITLE', evidence={'table_id': table_id});continue
        matched = assign(primary + secondary, tc, rules)
        anchors = []
        for i, row in enumerate(rows):
            anchor, reason = _anchor(row, primary, matched, table, header, rules)
            if anchor is None:
                reject(reason, i, evidence={'table_id': table_id});continue
            anchor['row_index'] = i;anchors.append(anchor)
        if len(anchors) < 2 or len({a['native_row'] for a in anchors}) != len(anchors):
            reject('TWO_UNIQUE_EXISTING_MULTITOKEN_SOURCE_ROWS_REQUIRED', evidence={'table_id': table_id});continue
        name_aliases = {}
        for anchor in anchors:
            for token in anchor['tokens']:
                for alias in token['aliases']:
                    name_aliases.setdefault(alias, set()).add(anchor['row_index'])
        if any(len(owners) > 1 for owners in name_aliases.values()):
            reject('SOURCE_NAME_IDENTITY_REUSED_ACROSS_ROWS', evidence={'table_id': table_id});continue
        ordered = sorted(anchors, key=lambda a: rules._cy(a['token']['bbox']))
        if ([a['row_index'] for a in ordered] != sorted(a['row_index'] for a in ordered) or
            [a['native_row'] for a in ordered] != sorted(a['native_row'] for a in ordered)):
            reject('EXISTING_SOURCE_AND_NATIVE_ROW_ORDER_CONFLICT', evidence={'table_id': table_id});continue
        for ai, anchor in enumerate(ordered):
            i = anchor['row_index'];ab = anchor['token']['bbox'];cy = rules._cy(ab);height = rules._height(ab)
            top = max(table['bbox'][1], header['bottom'], ab[1] - height * .75)
            bottom = min(table['bbox'][3], ab[3] + height * .75)
            if ai:
                top = max(top, (cy + rules._cy(ordered[ai-1]['token']['bbox'])) / 2)
            if ai + 1 < len(ordered):
                bottom = min(bottom, (cy + rules._cy(ordered[ai+1]['token']['bbox'])) / 2)
            band = [table['bbox'][0], top, table['bbox'][2], bottom]
            if top >= bottom or any((rules.SET.search(t['text']) or rules.FOOTER.search(t['text']) or BONUS.search(t['text']))
                    and rules._intersection(t['bbox'], band) for t in primary + secondary + alternatives):
                reject('SET_BONUS_FOOTER_OR_AMBIGUOUS_ROW_BAND', i, evidence={'table_id': table_id});continue
            values = {}
            for role in EDITABLE:
                left, right = header['bounds'][role]
                evidence = {'table_id': table_id, 'coordinate_space': 'upright_image',
                    'row_eligibility': deepcopy(anchor['row_eligibility']),
                    'anchor_token_ids': [t['token_id'] for t in anchor['tokens']],
                    'native_row': anchor['native_row'], 'source_column_bounds': [left, right],
                    'source_row_band_bbox': band, 'role_header_tokens': header_tokens[role],
                    'role_header_token_ids': [t['token_id'] for t in header_tokens[role]],
                    'header_cell_ids': sorted({matched[t['token_id']]['id'] for t in header_tokens[role] if t['token_id'] in matched})}
                if anchor['description_column_proof'] is not None:
                    evidence['description_column_proof'] = deepcopy(anchor['description_column_proof'])
                cell_band = [left, top, right, bottom];evidence['source_header_band'] = cell_band
                if not table['bbox'][0] <= left < right <= table['bbox'][2] or role == 'quantity' and (left <= 0 or right >= cache['geometry']['upright_size'][0]):
                    reject('UNBOUNDED_OR_FOREIGN_NUMERIC_SOURCE_COLUMN', i, role, evidence);continue
                value, reason = rules._read_cell(cell_band, primary, secondary, anchor, role, alternatives)
                if value is None:
                    reject(reason, i, role, evidence);continue
                owners = [matched.get(t['token_id']) for t in value['tokens']]
                if (any(c is None for c in owners) or len({c['id'] for c in owners}) != 1 or
                    owners[0]['row'] != anchor['native_row'] or owners[0]['column'] in anchor['native_columns']):
                    reject('VALUE_DOES_NOT_HAVE_UNIQUE_NATIVE_BODY_CELL', i, role, evidence);continue
                cell = owners[0];evidence['target_cell_id'] = cell['id']
                evidence['native_column'] = cell['column']
                if any(len([t for t in family if matched.get(t['token_id'], {}).get('id') == cell['id']]) != 1 for family in (primary, secondary)):
                    reject('NATIVE_CELL_HAS_MULTIPLE_SOURCE_DETECTIONS', i, role, evidence);continue
                evidence['conditional_foreign_owners'] = foreign._foreign_owners(rows, i, role, value['tokens'])
                before = (rows[i].get('fields') or {}).get(role)
                candidate = _field(value, role, before, evidence, observation_pin)
                proposal = {'row_index': i, 'field': role, 'before': deepcopy(before), 'candidate': candidate,
                    'reason': 'INDEPENDENT_PRINTED_SOURCE_REASSOCIATION', 'evidence': evidence}
                if record('proposed', proposal):
                    values[role] = (proposal, value)
            if (set(values) == set(EDITABLE) and
                values['quantity'][0]['evidence']['target_cell_id'] == values['unit'][0]['evidence']['target_cell_id']):
                for role, (proposal, _) in values.items():
                    reject('QUANTITY_UNIT_SHARE_A_NATIVE_CELL', i, role, proposal['evidence'], proposal['candidate'])
                continue
            for role, (proposal, value) in values.items():
                # A proven single field need not wait for an unreadable
                # companion. Never infer a companion value; source-vacating
                # transactions still fail unless every actual owner vacates.
                if 'unit' in values:
                    proposal['evidence']['compatible_unit_source_tokens'] = deepcopy(values['unit'][1]['tokens'])
                if _old_same(proposal['before'], proposal['candidate'], role):
                    reject('EXISTING_FIELD_ALREADY_MATCHES_PRINTED_SOURCE', i, role, proposal['evidence'], proposal['candidate'])
                elif len(pending) < LIMIT:
                    pending.append((proposal, value))
                else:
                    audit['truncated_decisions'] += 1
    # Candidate transactions may vacate a mistaken same-row qty/unit owner;
    # preserved description/price/lot and all other rows are never borrowed.
    aliases = {}
    for proposal, value in pending:
        for token in value['tokens']:
            for alias in token['aliases']:
                aliases.setdefault(alias, set()).add((proposal['row_index'], proposal['field']))
    valid = {(p['row_index'], p['field']): (p, v) for p, v in pending}
    duplicate_keys = {key for key in valid if sum((p['row_index'], p['field']) == key for p, _ in pending) != 1}
    for key in duplicate_keys:
        valid.pop(key)
    rejected_keys = set(duplicate_keys)
    while True:
        failed = []
        for key, (proposal, value) in valid.items():
            reason = None
            if any(len(aliases[a]) != 1 for t in value['tokens'] for a in t['aliases']):
                reason = 'AMBIGUOUS_PROPOSAL_SOURCE_OWNERSHIP'
            for owner in proposal['evidence']['conditional_foreign_owners']:
                other = (owner['row_index'], owner['field'])
                if other[0] != key[0] or other[1] not in EDITABLE or other not in valid:
                    reason = 'PRESERVED_FOREIGN_FIELD_OWNS_SOURCE';break
                candidate_aliases = {a for t in valid[other][1]['tokens'] for a in t['aliases']}
                if any(set(t['aliases']) & candidate_aliases for t in value['tokens']):
                    reason = 'CONDITIONAL_OWNER_DOES_NOT_VACATE_SOURCE';break
            if reason:
                failed.append((key, reason))
        if not failed:
            break
        for key, reason in failed:
            proposal, _ = valid.pop(key)
            reject(reason, key[0], key[1], proposal['evidence'], proposal['candidate']);rejected_keys.add(key)
    for key in duplicate_keys:
        reject('MULTIPLE_TABLE_PROPOSALS_FOR_EXISTING_FIELD', key[0], key[1])
    for key, (proposal, _) in valid.items():
        rows[key[0]].setdefault('fields', {})[key[1]] = deepcopy(proposal['candidate'])
        record('accepted', proposal);record('changes', proposal)
    audit['status'] = 'APPLIED' if audit['changes'] else 'ABSTAINED'
    if digest([page, cache, observation]) != frozen:
        raise ValueError('Correction bridge mutated retained input evidence')
    return out


def propose_and_apply(page, cache, observation, helpers, observation_pin):
    """Combine explicit source-cell proposals without changing native evidence."""
    native=_native_propose_and_apply(page,cache,observation,helpers,observation_pin)
    cells=helpers.get('cell_association')
    if cells is None:
        return native
    frozen=digest([page,cache,observation])
    source=cells.propose(page,cache,observation,helpers,observation_pin)
    if digest([page,cache,observation])!=frozen:
        raise ValueError('Source cell association mutated retained inputs')
    native_audit=native['document_ai_correction_association']
    audit={'contract':VERSION,'status':'ABSTAINED','proposed':[],
        'accepted':[],'rejected':[],'changes':[], 'native_route':deepcopy(native_audit),
        'source_cell_route':deepcopy(source),'new_OCR_calls':0,'new_model_calls':0,
        'reference_access':False,'assistant_image_reads':False,'human_approved':False,
        'truncated_decisions':0,'source_confidence_gates':[.95,.70],
        'nonempty_correction_enabled':True}
    if 'document_admission' in native_audit:
        audit['document_admission']=deepcopy(native_audit['document_admission'])
    out=deepcopy(page);out['document_ai_correction_association']=audit
    raw_proposals=native_audit.get('proposed',[])+source.get('proposed',[])
    audit['proposed']=deepcopy(raw_proposals[:LIMIT])
    audit['truncated_decisions']=max(0,len(raw_proposals)-LIMIT)
    audit['rejected']=deepcopy((native_audit.get('rejected',[])+source.get('rejected',[]))[:LIMIT])
    groups={}
    for change in native_audit.get('changes',[])+source.get('changes',[]):
        key=(change['row_index'],change['field']);groups.setdefault(key,[]).append(change)
    if len(groups)>LIMIT:
        audit['rejected'].append({'reason':'bounded_combined_change_inventory_required'})
        audit['truncated_decisions']+=len(groups)-LIMIT
        return out
    for key,variants in sorted(groups.items()):
        literal=[tuple(digest(v['candidate'].get(k)) for k in ('raw_value','normalized_value','token_ids','bbox')) for v in variants]
        if len(set(literal))!=1:
            audit['rejected'].append({'row_index':key[0],'field':key[1],
                'reason':'INDEPENDENT_ASSOCIATION_ROUTES_DISAGREE'})
            continue
        # Prefer the stricter native proof when both routes use the same
        # whole detection. The guard independently resolves joint ownership.
        change=deepcopy(variants[0])
        out['product_rows'][key[0]].setdefault('fields',{})[key[1]]=deepcopy(change['candidate'])
        audit['accepted'].append(change);audit['changes'].append(deepcopy(change))
    audit['status']='PROPOSED' if audit['changes'] else 'ABSTAINED'
    return out
