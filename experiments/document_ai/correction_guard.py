"""Source-bound experimental revisions; no reference answers or live writes.

The established additive guard remains unchanged. This policy admits explicit
quantity/unit revisions, keeps their previous evidence, and projects only those
fields onto a copy of the canonical page. It never revises row identities.
"""
from __future__ import annotations

from copy import deepcopy
import re

from eval_geometry import assign, digest, normalize
from correction_eligibility import assess_row
from component_common import valid_box

VERSION = 'source-bound-quantity-unit-revisions.v6'
ROLES = frozenset(('quantity', 'unit'))


def _literal(text):
    return re.sub(r'\s+', '', str(text or '')).casefold()


def _same_token(claim, actual):
    return (isinstance(claim, dict) and claim.get('token_id') == actual['token_id']
            and claim.get('text', claim.get('raw_text')) == actual['text']
            and claim.get('bbox') == actual['bbox']
            and claim.get('confidence') == actual['confidence']
            and claim.get('engine') == actual['engine'])


def _tokens(cache, rules):
    primary = rules._tokens(cache.get('working_tokens', []))
    secondary = rules._tokens(cache.get('tesseract_working_tokens', []), True)
    alternatives = []
    for view in cache.get('targeted_views', []):
        alternatives.extend(rules._tokens(view.get('tokens', [])))
    return primary, secondary, alternatives


def _identity(page):
    return [(r.get('row_number'), r.get('page_number')) for r in page.get('product_rows', [])]


def _description_gap(proof, primary, anchor_box, table, core, rules, size):
    """Verify printed heading edges, never infer physical cell borders."""
    if (not isinstance(proof,dict) or proof.get('method')!='SOURCE_HEADER_TEXT_GAP'
            or proof.get('physical_cell_borders_claimed') is not False):
        raise ValueError('explicit_source_heading_gap_proof_required')
    lookup={t['token_id']:t for t in primary}
    def group(claims,role):
        if not isinstance(claims,list) or not claims:
            raise ValueError('whole_actual_description_boundary_headings_required')
        words=[];seen=set()
        for claim in claims:
            key=claim.get('token_id') if isinstance(claim,dict) else None
            actual=lookup.get(key)
            if (actual is None or key in seen or not _same_token(claim,actual)
                    or actual['confidence']<.70 or not rules._inside(actual['bbox'],table['bbox'])):
                raise ValueError('actual_description_boundary_header_token_differs')
            seen.add(key);words.append(actual)
        text=' '.join(t['text'] for t in sorted(words,key=lambda t:t['bbox'][0]))
        actual_role=core._role(text)
        if role.startswith('unclassified_numeric_boundary_'):
            if len(words)!=1 or not re.match(r'^(?:ราคา|หน่วย.{1,5}$|ส่วนลด|DISCOUNT\b|PR[I1]CE\b)',text,re.I):
                raise ValueError('unverified_neutral_description_boundary')
        elif actual_role!=role:
            raise ValueError('literal_description_boundary_role_differs')
        return words
    description=group(proof.get('description_header_tokens'),'description')
    neighbors=[]
    for side in ('left_header','right_header'):
        claim=proof.get(side)
        if not isinstance(claim,dict) or not isinstance(claim.get('role'),str) or claim['role']=='description':
            raise ValueError('two_distinct_competing_heading_roles_required')
        neighbors.append(group(claim.get('tokens'),claim['role']))
    left,right=neighbors
    if (proof['left_header']['role']==proof['right_header']['role']
            or len({t['token_id'] for t in description+left+right})!=len(description+left+right)):
        raise ValueError('distinct_whole_heading_identities_required')
    left_edge=max(t['bbox'][2] for t in left);right_edge=min(t['bbox'][0] for t in right)
    desc_box=[min(t['bbox'][0] for t in description),min(t['bbox'][1] for t in description),
              max(t['bbox'][2] for t in description),max(t['bbox'][3] for t in description)]
    if (proof.get('bounds')!=[left_edge,right_edge] or not left_edge<right_edge
            or not left_edge<=desc_box[0]<desc_box[2]<=right_edge
            or not left_edge<=anchor_box[0]<anchor_box[2]<=right_edge):
        raise ValueError('whole_description_outside_literal_heading_text_gap')
    words=description+left+right
    height=max(rules._height(t['bbox']) for t in words)
    desc_y=sum(rules._cy(t['bbox']) for t in description)/len(description)
    if (any(abs(rules._cy(t['bbox'])-desc_y)>height*1.8 for t in words)
            or max(t['bbox'][3] for t in words)>=anchor_box[1]):
        raise ValueError('coherent_headings_above_source_name_required')
    # Reconstruct all maximal exact phrases in this actual source header band.
    # A claimant cannot omit a nearer price/code/quantity boundary to widen it.
    local=[t for t in primary if rules._inside(t['bbox'],table['bbox'])]
    clean,_=core._read([{**t,'box':t['bbox']} for t in local],'primary',size)
    parts=core._header_parts(clean)
    parts=[(r,g) for r,g in parts if not any({t.id for t in g}<{t.id for t in other} for _,other in parts)]
    description_ids={t['token_id'] for t in description}
    for role,part in parts:
        leftmost=min(t.box[0] for t in part);rightmost=max(t.box[2] for t in part)
        cy=sum(t.cy for t in part)/len(part)
        ids={t.id for t in part}
        if (abs(cy-desc_y)<=height*1.8 and leftmost<right_edge and rightmost>left_edge
                and not ids<=description_ids):
            raise ValueError('competing_literal_heading_inside_description_gap')
    for token in clean:
        if (abs(token.cy-desc_y)<=height*1.8 and token.box[0]<right_edge and token.box[2]>left_edge
                and token.id not in description_ids
                and re.match(r'^(?:ราคา|หน่วย.{1,5}$|ส่วนลด|DISCOUNT\b|PR[I1]CE\b)',token.text,re.I)):
            raise ValueError('competing_neutral_heading_inside_description_gap')


def _source_cell_proof(before,row_index,role,field,evidence,cache,observation,helpers,observation_pin,source):
    policy=helpers.get('cell_association')
    if policy is None:
        raise ValueError('explicit_source_cell_component_required')
    geometry=cache.get('geometry') or {}
    if geometry.get('machine_only') is not True or geometry.get('vision_LLM_calls')!=0:
        raise ValueError('machine_only_source_geometry_required')
    context=policy.verify(before,cache,observation,helpers,observation_pin,row_index,role,evidence)
    rules,core=helpers['rules'],helpers['core'];primary,secondary,alternatives=source
    band=context['source_band'];anchor=context['anchor'];region=context['region']
    if (not valid_box(band,geometry['upright_size']) or not valid_box(region['bbox'],geometry['upright_size'])
            or not rules._inside(band,region['bbox']) or band!=field.get('source_header_column_and_row_band')
            or evidence.get('source_header_band')!=band or evidence.get('row_index')!=row_index
            or evidence.get('field')!=role or evidence.get('native_cells_used')!=0
            or evidence.get('physical_cell_borders_claimed') is not False):
        raise ValueError('source_derived_cell_geometry_or_identity_differs')
    model=field.get('model_geometry_evidence') or {}
    if (model.get('native_observation')!=observation_pin or model.get('region')!=region
            or model.get('native_cells_used')!=0 or model.get('physical_cell_borders_claimed') is not False
            or any(k in model for k in ('cell_id','table_id','row'))
            or field.get('association_basis')!='SOURCE_HEADER_ROW_BAND'):
        raise ValueError('derived_cell_cannot_claim_native_cell_identity')
    desc=(before['product_rows'][row_index].get('fields') or {}).get('description') or {}
    lookup={t['token_id']:t for t in primary};ids=evidence.get('anchor_token_ids') or []
    desc_ids=desc.get('token_ids') or [s.get('token_id') for s in desc.get('source_spans',[]) if isinstance(s,dict)]
    words=[lookup[k] for k in ids if k in lookup]
    if (not ids or len(words)!=len(set(ids)) or set(ids)!=set(desc_ids)
            or [t['token_id'] for t in anchor['tokens']]!=ids
            or any(not _same_token(t,lookup[t['token_id']]) for t in anchor['tokens'])):
        raise ValueError('source_cell_name_detection_identity_differs')
    box=[min(t['bbox'][0] for t in words),min(t['bbox'][1] for t in words),
         max(t['bbox'][2] for t in words),max(t['bbox'][3] for t in words)]
    literal=''.join(t['text'] for t in sorted(words,key=lambda t:(rules._cy(t['bbox']),t['bbox'][0],t['token_id'])))
    if (box!=rules._box(desc.get('bbox')) or box!=anchor['token']['bbox']
            or _literal(literal)!=_literal(desc.get('raw_value')) or not rules._name(literal)
            or any(t['confidence']<.70 for t in words) or not rules._inside(box,region['bbox'])
            or band[1]<box[1]-.75*rules._height(box)-1e-6
            or band[3]>box[3]+.75*rules._height(box)+1e-6
            or not band[1]<=rules._cy(box)<=band[3]):
        raise ValueError('whole_source_name_and_bounded_row_proof_required')
    # Even an unconfirmed neighbour is a barrier. A failed name match must
    # not erase an existing row and expose its unowned quantity/unit tokens.
    cy=rules._cy(box);height=rules._height(box)
    for index,row in enumerate(before.get('product_rows',[])):
        if index==row_index:
            continue
        other=rules._box(((row.get('fields') or {}).get('description') or {}).get('bbox'))
        if other is None or not valid_box(other,geometry['upright_size']):
            continue
        other_cy=rules._cy(other)
        if abs(other_cy-cy)<=.75*max(height,rules._height(other)):
            raise ValueError('ambiguous_neighbouring_canonical_source_rows')
        midpoint=(cy+other_cy)/2
        if (other_cy<cy and band[1]<midpoint-1e-6
                or other_cy>cy and band[3]>midpoint+1e-6):
            raise ValueError('source_band_crosses_canonical_neighbour_barrier')
    header=evidence.get('role_header_tokens') or []
    if (not header or any(t.get('token_id') not in lookup or not _same_token(t,lookup[t['token_id']])
                         or lookup[t['token_id']]['confidence']<.70 for t in header)
            or core._role(' '.join(t['text'] for t in sorted(header,key=lambda t:t['bbox'][0])))!=role
            or max(t['bbox'][3] for t in header)>band[1]):
        raise ValueError('actual_source_cell_literal_role_heading_required')
    # Independent cached read; evidence/candidate strings never become answers.
    value,reason=rules._read_cell(band,primary,secondary,anchor,role,alternatives)
    if value is None:
        raise ValueError('source_read_rejected:'+str(reason))
    a,b=value['tokens']
    if any(max(0,min(box[3],t['bbox'][3])-max(box[1],t['bbox'][1]))
           <.5*min(rules._height(box),rules._height(t['bbox'])) for t in (a,b)):
        raise ValueError('whole_value_not_on_proven_source_name_baseline')
    if (field.get('human_approved') is not False or field.get('human_verified',False) is not False
            or field.get('business_correction_applied',False) is not False
            or field.get('quantity_multiplication_applied',False) is not False
            or field.get('raw_value')!=a['text'] or field.get('normalized_value')!=value['normalized_value']
            or field.get('bbox')!=a['bbox'] or field.get('token_ids')!=[a['token_id']]
            or field.get('engine')!=a['engine'] or field.get('confidence')!=a['confidence']
            or field.get('source_bbox_kind')!='whole_actual_detection'
            or not _same_token(field.get('corroborating_observation'),b)
            or a['confidence']<.95 or b['confidence']<.70 or set(a['aliases'])&set(b['aliases'])
            or any(not rules._inside(t['bbox'],band) for t in (a,b))):
        raise ValueError('candidate_literal_or_dual_source_differs')
    spans=field.get('source_spans') or []
    if len(spans)!=1 or not _same_token(spans[0],a):
        raise ValueError('whole_primary_source_span_required')
    return [a,b]


def _proof(before, row_index, role, field, evidence, cache, observation,
           helpers, observation_pin, regions, cells, source):
    rules, core = helpers['rules'], helpers['core']
    primary, secondary, alternatives = source
    rows = before.get('product_rows') or []
    if not assess_row(rows[row_index], rules)['eligible']:
        raise ValueError('protected_source_row')
    if not isinstance(field, dict) or not isinstance(evidence, dict):
        raise ValueError('explicit_candidate_and_source_proof_required')
    if field.get('human_approved') is not False:
        raise ValueError('unreviewed_machine_candidate_required')
    if evidence.get('route')=='SOURCE_HEADER_ROW_BAND':
        return _source_cell_proof(before,row_index,role,field,evidence,cache,observation,
                                  helpers,observation_pin,source)
    native = field.get('model_geometry_evidence') or {}
    if native.get('native_observation') != observation_pin:
        raise ValueError('native_source_pin_differs')
    table_id = evidence.get('table_id')
    table = regions.get(table_id)
    cell = next((c for c in cells if c['id'] == evidence.get('target_cell_id')
                 and c['table_id'] == table_id), None)
    if table is None or cell is None or cell['row'] != evidence.get('native_row'):
        raise ValueError('actual_native_target_cell_required')
    if (native.get('table_id') != table_id or native.get('cell_id') != cell['id']
            or native.get('row') != cell['row']):
        raise ValueError('candidate_geometry_identity_differs_from_source_proof')
    band = rules._box(field.get('source_header_column_and_row_band'))
    if (band is None or band != rules._box(evidence.get('source_header_band'))
            or not rules._inside(band, table['bbox'])
            or evidence.get('source_column_bounds') != [band[0], band[2]]):
        raise ValueError('source_column_and_row_band_differs')
    lookup = {t['token_id']: t for t in primary}
    anchors = [lookup[k] for k in evidence.get('anchor_token_ids', []) if k in lookup]
    if not anchors or len(anchors) != len(set(evidence.get('anchor_token_ids', []))):
        raise ValueError('actual_unique_description_tokens_required')
    desc = (rows[row_index].get('fields') or {}).get('description') or {}
    desc_ids = desc.get('token_ids') or [s.get('token_id') for s in desc.get('source_spans',[]) if isinstance(s,dict)]
    if (not desc_ids or set(desc_ids) != set(evidence.get('anchor_token_ids',[]))
            or len(desc_ids) != len(set(desc_ids))):
        raise ValueError('anchor_detection_identity_differs_from_established_description')
    desc_box = rules._box(desc.get('bbox'))
    if (desc_box is None or not rules._name(' '.join(t['text'] for t in anchors))
            or any(not rules._inside(t['bbox'], desc_box) for t in anchors)
            or _literal(''.join(t['text'] for t in sorted(anchors, key=lambda t:(rules._cy(t['bbox']),t['bbox'][0],t['token_id']))))
            != _literal(desc.get('raw_value'))):
        raise ValueError('source_description_row_anchor_differs')
    anchor_box = [min(t['bbox'][0] for t in anchors), min(t['bbox'][1] for t in anchors),
                  max(t['bbox'][2] for t in anchors), max(t['bbox'][3] for t in anchors)]
    if anchor_box != desc_box or not rules._inside(anchor_box, table['bbox']):
        raise ValueError('description_anchor_outside_native_table')
    if 'description_column_proof' in evidence:
        _description_gap(evidence['description_column_proof'],primary,anchor_box,table,core,rules,
                         cache['geometry']['upright_size'])
    height=rules._height(anchor_box)
    if (not band[1] <= rules._cy(anchor_box) <= band[3]
            or band[1] < anchor_box[1]-.75*height-1e-6
            or band[3] > anchor_box[3]+.75*height+1e-6):
        raise ValueError('source_band_not_bounded_to_established_row_baseline')
    header_claims = evidence.get('role_header_tokens') or []
    header = []
    for claim in header_claims:
        actual = lookup.get(claim.get('token_id'))
        if actual is None or not _same_token(claim, actual) or actual['confidence'] < .70:
            raise ValueError('actual_literal_header_tokens_required')
        header.append(actual)
    if (not header or core._role(' '.join(t['text'] for t in sorted(header, key=lambda t:t['bbox'][0]))) != role
            or max(t['bbox'][3] for t in header) > band[1]
            or not band[0] <= sum((t['bbox'][0]+t['bbox'][2])/2 for t in header)/len(header) <= band[2]):
        raise ValueError('source_header_role_or_column_differs')
    # Re-run the frozen literal/independent-reader decision on actual cache
    # tokens. Candidate text is never accepted merely because the audit says so.
    value, reason = rules._read_cell(band, primary, secondary,
                                    {'token': {'bbox': anchor_box}}, role, alternatives)
    if value is None:
        raise ValueError('source_read_rejected:' + str(reason))
    a, b = value['tokens']
    assignments = assign(primary+secondary, [c for c in cells if c['table_id']==table_id], rules)
    if any(assignments.get(t['token_id'], {}).get('id') != cell['id'] for t in (a,b)):
        raise ValueError('actual_value_detection_not_owned_by_target_native_cell')
    if any(assignments.get(t['token_id'], {}).get('row') != cell['row'] for t in anchors):
        raise ValueError('description_and_value_native_rows_differ')
    if any(assignments[t['token_id']]['column'] == cell['column'] for t in anchors):
        raise ValueError('description_and_value_share_native_column')
    if (field.get('raw_value') != a['text'] or field.get('normalized_value') != value['normalized_value']
            or field.get('bbox') != a['bbox'] or field.get('token_ids') != [a['token_id']]
            or field.get('engine') != a['engine'] or field.get('confidence') != a['confidence']
            or field.get('source_bbox_kind') != 'whole_actual_detection'
            or field.get('business_correction_applied',False) is not False
            or field.get('quantity_multiplication_applied',False) is not False
            or field.get('human_verified',False) is not False
            or not _same_token(field.get('corroborating_observation'), b)
            or a['confidence'] < .95 or b['confidence'] < .70
            or set(a['aliases']) & set(b['aliases'])
            or any(not rules._inside(t['bbox'], band) for t in (a, b))):
        raise ValueError('candidate_literal_or_dual_source_differs')
    spans = field.get('source_spans') or []
    if len(spans) != 1 or not _same_token(spans[0], a):
        raise ValueError('whole_primary_source_span_required')
    if (not rules._inside(a['bbox'], table['bbox'])
            or not rules._inside(b['bbox'], table['bbox'])
            or rules._cy(a['bbox']) < band[1] or rules._cy(a['bbox']) > band[3]):
        raise ValueError('value_outside_proven_source_row')
    # A frozen header reader can identify a competing price/amount/packing
    # role. A proposal cannot silently widen a quantity/unit column over it.
    local_tokens = [t for t in primary+secondary if rules._inside(t['bbox'], table['bbox'])]
    clean, _ = core._read([{**t, 'box':t['bbox']} for t in local_tokens], 'primary', cache['geometry']['upright_size'])
    coherent = core._header(clean, cache['geometry']['upright_size'])
    if coherent:
        for other_role, words in coherent.get('anchors', {}).items():
            if other_role == role:
                continue
            cx = sum(t.cx for t in words)/len(words)
            if band[0] < cx < band[2]:
                raise ValueError('competing_literal_column_inside_proposed_band')
    # The old coherent-header helper may abstain on nested phrase ambiguity.
    # Independently keep maximal exact printed roles and neutral monetary
    # boundaries, rather than treating a missing header result as permission.
    if hasattr(core, '_header_parts'):
        parts = core._header_parts(clean)
        parts = [(r,words) for r,words in parts if not any(
            {t.id for t in words} < {t.id for t in other} for _,other in parts)]
        hc = sum((t['bbox'][1]+t['bbox'][3])/2 for t in header)/len(header)
        hh = max(t['bbox'][3]-t['bbox'][1] for t in header)
        for other_role,words in parts:
            cx = (min(t.box[0] for t in words)+max(t.box[2] for t in words))/2
            cy = sum(t.cy for t in words)/len(words)
            if other_role != role and abs(cy-hc)<=hh*1.8 and band[0]<cx<band[2]:
                raise ValueError('competing_printed_header_role_inside_proposed_band')
        for token in clean:
            if (abs(token.cy-hc)<=hh*1.8 and band[0]<token.cx<band[2]
                    and token.id not in {t['token_id'] for t in header}
                    and re.match(r'^(?:ราคา|ส่วนลด|DISCOUNT\b|PR[I1]CE\b)',token.text,re.I)):
                raise ValueError('unresolved_monetary_header_boundary_inside_proposed_band')
    return [a, b]


def conserve_corrections(before, candidate, cache, observation, helpers, observation_pin):
    """Admit proof-bound revisions onto ``before``, retaining every old field."""
    started = digest([before, candidate, cache, observation])
    audit = {'version':VERSION, 'accepted_changes':[], 'rejected_changes':[],
             'reference_access':False, 'human_approved':False, 'production_activation':False}
    result = deepcopy(before)
    flags = cache.get('inference_inputs') or {}
    if (any(flags.get(k) is not False for k in ('reference','human_answers','Ada','StockDay'))
            or flags.get('assistant_image_reads') != 0
            or before.get('coordinate_space') != 'upright_image'
            or before.get('source_sha256') != cache.get('source_sha256')
            or before.get('page_number') != cache.get('page_number')
            or before.get('image_size') != (cache.get('geometry') or {}).get('upright_size')):
        audit['rejected_changes'].append({'reason':'machine_only_invoice_frame_required'})
        return result, audit
    classifier=helpers.get('document_admission')
    if classifier is not None:
        admission=classifier.assess_document(before,cache,helpers['rules'],helpers['core'],
            observation=observation,observation_pin=observation_pin)
        if digest([before,candidate,cache,observation]) != started:
            raise ValueError('Document admission mutated correction inputs')
        audit['document_admission']=deepcopy(admission)
        if (admission.get('eligible') is not True or admission.get('reference_access') is not False
                or admission.get('canonical_document_type_modified') is not False):
            audit['rejected_changes'].append({'reason':'document_source_admission_rejected'})
            return result,audit
    elif (before.get('document') or {}).get('document_type') != 'invoice_or_delivery':
        audit['rejected_changes'].append({'reason':'machine_only_invoice_frame_required'})
        return result,audit
    regions, cells = normalize(observation, cache)
    raw = candidate.get('document_ai_correction_association') or {}
    if _identity(before) != _identity(candidate):
        audit['rejected_changes'].append({'reason':'existing_row_identity_or_order_changed'})
        return result, audit
    source = _tokens(cache, helpers['rules'])
    rows = before.get('product_rows') or []
    choices, keys = {}, set()
    for change in raw.get('changes', []):
        index, role = change.get('row_index'), change.get('field')
        key = (index, role)
        try:
            if type(index) is not int or not 0 <= index < len(rows) or role not in ROLES:
                raise ValueError('only_existing_row_quantity_unit_revisions_allowed')
            if key in keys:
                raise ValueError('duplicate_revision_identity')
            keys.add(key)
            old = (rows[index].get('fields') or {}).get(role)
            field = ((candidate['product_rows'][index].get('fields') or {}).get(role))
            if change.get('before') != old or change.get('candidate') != field:
                raise ValueError('explicit_before_after_snapshot_differs')
            if isinstance(old,dict) and all(old.get(k)==field.get(k) for k in ('raw_value','normalized_value')):
                raise ValueError('no_literal_or_normalized_value_change')
            tokens = _proof(before,index,role,field,change.get('evidence'),cache,observation,
                            helpers,observation_pin,regions,cells,source)
            choices[key] = {'change':change,'tokens':tokens,'old':old,'field':field}
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            choices.pop(key, None)
            audit['rejected_changes'].append({'row_index':index,'field':role,'reason':str(exc)})
    # Reject both sides of ambiguous new ownership; never pick a winner using
    # labels. Existing qty/unit owners may be vacated only as one valid joint
    # transaction. A rejected dependent revision invalidates its dependants.
    owners = {}
    for key, item in choices.items():
        for alias in {a for t in item['tokens'] for a in t['aliases']}:
            owners.setdefault(alias,set()).add(key)
    for key in list(choices):
        if any(len(owners[a]) != 1 for t in choices[key]['tokens'] for a in t['aliases']):
            choices.pop(key)
            audit['rejected_changes'].append({'row_index':key[0],'field':key[1],'reason':'ambiguous_new_source_owner'})
    while True:
        dropped=[]
        for key,item in choices.items():
            for owner in helpers['owners']._foreign_owners(rows,key[0],key[1],item['tokens']):
                other=(owner['row_index'],owner['field'])
                if other[0] != key[0] or other not in choices:
                    dropped.append(key);break
        if not dropped:
            break
        for key in set(dropped):
            choices.pop(key)
            audit['rejected_changes'].append({'row_index':key[0],'field':key[1],'reason':'preserved_foreign_source_owner'})
    for (index,role),item in sorted(choices.items()):
        field = deepcopy(item['field'])
        field['source_revision']={'policy':VERSION,'previous_source_field':deepcopy(item['old']),
                                  'kind':'fill' if helpers['rules']._missing(item['old']) else 'replace',
                                  'source_evidence':deepcopy(item['change']['evidence']),
                                  'reference_access':False,'human_approved':False}
        result['product_rows'][index].setdefault('fields',{})[role]=field
        audit['accepted_changes'].append({'row_index':index,'field':role,'kind':field['source_revision']['kind'],
            'before':deepcopy(item['old']),'candidate':deepcopy(field),
            'evidence':deepcopy(item['change']['evidence']),
            'row_eligibility':assess_row(rows[index],helpers['rules'])})
    if digest([before,candidate,cache,observation]) != started:
        raise ValueError('Correction guard mutated its inputs')
    result['document_ai_correction_conservation']=deepcopy(audit)
    return result,audit


def project_corrections(parent_original, mapped_upright_core, guard_audit):
    """Copy only admitted fields; canonical unrelated source bytes survive."""
    if _identity(parent_original) != _identity(mapped_upright_core):
        raise ValueError('Projected existing source row identities differ')
    result=deepcopy(parent_original)
    audit={'version':VERSION,'coordinate_space':'original_image','accepted_changes':[],
           'reference_access':False,'human_approved':False,'production_activation':False}
    seen=set()
    for change in guard_audit.get('accepted_changes',[]):
        index,role=change['row_index'],change['field']
        if (index,role) in seen or role not in ROLES:
            raise ValueError('Projected correction identity differs')
        seen.add((index,role))
        field=deepcopy(mapped_upright_core['product_rows'][index]['fields'][role])
        previous=deepcopy((parent_original['product_rows'][index].get('fields') or {}).get(role))
        # The mapper transforms nested boxes; the archived original evidence
        # must remain the exact original-frame object, with no roundtrip drift.
        field['source_revision']['previous_source_field']=previous
        field['source_revision']['source_evidence']=deepcopy(change['evidence'])
        field['source_revision']['source_evidence_coordinate_space']='upright_image'
        if 'prior_source_evidence' in field:
            field['prior_source_evidence']=deepcopy(previous)
        result['product_rows'][index].setdefault('fields',{})[role]=field
        audit['accepted_changes'].append({'row_index':index,'field':role,
              'before':previous,'candidate':deepcopy(field),'kind':change['kind']})
    result['document_ai_correction_conservation']=deepcopy(audit)
    return result,audit
