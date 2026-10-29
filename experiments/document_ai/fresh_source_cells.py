"""Pure association of separately supervised, measured fresh OCR observations.

No IO, images, SDK, reference, catalogue or model calls. Both new and old
recognition are evaluated with the same frozen field reader. Old incomplete
reads remain evidence; they are not promoted into an independent third vote.
"""
from copy import deepcopy
import csv
from collections import defaultdict
import io
import math

from component_common import RESOURCES
from eval_geometry import digest

VERSION = 'document-ai-fresh-whole-source-cells.v1'
ROUTE = 'FRESH_WHOLE_SOURCE_ROW_BAND'
RUNTIME = 'document-ai-fresh-source-runtime.v1'
MAX_RECORDS = 46


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _pin(value):
    return (isinstance(value, dict) and set(value) == {'path', 'sha256'} and
            isinstance(value['path'], str) and bool(value['path']) and
            isinstance(value['sha256'], str) and len(value['sha256']) == 64 and
            all(c in '0123456789abcdef' for c in value['sha256']))


def _path_same(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.replace('\\', '/').casefold() == b.replace('\\', '/').casefold()


def _tsv(raw, crop, identity):
    """Independently regenerate every original-reader word span and line."""
    if not isinstance(raw, str):
        raise ValueError('exact_actual_TSV_text_required')
    reader = csv.DictReader(io.StringIO(raw.lstrip('\ufeff')), delimiter='\t', quoting=csv.QUOTE_NONE)
    needed = {'level', 'page_num', 'block_num', 'par_num', 'line_num', 'word_num',
              'left', 'top', 'width', 'height', 'conf', 'text'}
    if not needed <= set(reader.fieldnames or []):
        raise ValueError('actual_TSV_header_required')
    groups = defaultdict(list); width, height = crop['physical_crop_size']
    left, top = crop['crop_bbox_upright'][:2]
    for row in reader:
        if row['level'] != '5' or not row.get('text', '').strip():
            continue
        score = float(row['conf']); x, y, w, h = [int(row[k]) for k in ('left', 'top', 'width', 'height')]
        if (not math.isfinite(score) or not 0 <= score <= 100 or min(x, y) < 0 or w <= 0 or h <= 0
                or x+w > width or y+h > height):
            raise ValueError('actual_TSV_word_geometry_or_confidence_invalid')
        key = tuple(int(row[k]) for k in ('page_num', 'block_num', 'par_num', 'line_num'))
        groups[key].append({'raw_text': row['text'], 'confidence': score/100,
            'word_num': int(row['word_num']), 'local_bbox': [x, y, x+w, y+h],
            'bbox': [x+left, y+top, x+w+left, y+h+top]})
    result = []
    for index, (key, words) in enumerate(sorted(groups.items())):
        words.sort(key=lambda w: (w['word_num'], w['local_bbox'][0]))
        result.append({'raw_text': ' '.join(w['raw_text'] for w in words),
            'confidence': min(w['confidence'] for w in words), 'token_id': identity+':line'+str(index),
            'bbox': [min(w['bbox'][0] for w in words), min(w['bbox'][1] for w in words),
                     max(w['bbox'][2] for w in words), max(w['bbox'][3] for w in words)],
            'word_source_spans': words, 'actual_tsv_line_key': list(key),
            'source_bbox_kind': 'actual_TSV_word_union_not_whole_crop_glyph',
            'engine_family': 'TESSERACT', 'engine': 'NEW_WHOLE_CELL_TESSERACT_FAST_THA_ENG',
            'same_family_as_cached_Tesseract': True})
    return result


def _same_baseline(a, b):
    overlap = max(0, min(a[3], b[3])-max(a[1], b[1]))
    return overlap >= .5*min(a[3]-a[1], b[3]-b[1])


def _old_aliases(box, words, band, anchor, rules):
    """Only actual whole-word spatial identity may connect old ownership IDs."""
    aliases = set()
    for word in words:
        old = word['bbox']; hit = rules._intersection(box, old)
        if (hit and rules._inside(old, band) and _same_baseline(anchor, old) and
                rules._area(hit) >= .8*min(rules._area(box), rules._area(old))):
            aliases.update(word['aliases'])
    return aliases


def _foreign(rows, row_index, role, tokens, helpers):
    """New IDs cannot bypass preserved ownership, including coarse old boxes."""
    rules = helpers['rules']
    result = list(helpers['owners']._foreign_owners(rows, row_index, role, tokens))
    seen = {(r['row_index'], r['field']) for r in result}
    for index, row in enumerate(rows):
        for field, value in (row.get('fields') or {}).items():
            if (index, field) == (row_index, role) or not isinstance(value, dict):
                continue
            boxes = [rules._box(value.get('bbox'))]
            boxes += [rules._box(s.get('bbox')) for s in value.get('source_spans', []) if isinstance(s, dict)]
            if ((index, field) not in seen and any(box is not None and rules._intersection(box, t['bbox'])
                                                 for box in boxes for t in tokens)):
                result.append({'row_index': index, 'field': field, 'basis': 'actual_positive_geometry_intersection'})
                seen.add((index, field))
    return result


def _normalized(text, box, score, tid, family, physical, old, context, helpers, actual_engine):
    rules = helpers['rules']; band = context['source_band']; anchor = context['anchor']['token']['bbox']
    engine = 'PADDLE_FRESH_WHOLE_CELL_SERVER_DET_THAI_REC' if family == 'paddle' else 'TESSERACT_FRESH_WHOLE_CELL_FAST_THA_ENG'
    geom_alias = 'fresh-physical:'+family+':'+context['evidence']['source_sha256']+':'+digest(physical)
    raw = {'text': text, 'box': list(box), 'bbox': list(box), 'confidence': score, 'token_id': family+':'+tid,
           'engine': engine, 'source_detection_ids': sorted({geom_alias} | _old_aliases(box, old, band, anchor, rules))}
    if family == 'tesseract':
        raw.update(original_source_bbox=list(box), recognition_transform={
            'source_engine': engine, 'coordinate_space': 'upright_image',
            'source_geometry': 'actual_TSV_word_union'})
    found = rules._tokens([raw], family == 'tesseract')
    if len(found) != 1:
        raise ValueError('fresh_source_family_or_actual_token_normalization_failed')
    token = found[0]
    token.update(actual_engine=actual_engine, fresh_read_family=family,
                 actual_measured_geometry=deepcopy(physical), same_family_is_not_extra_vote=True)
    return token


def _record(record, page, cache, context, helpers, observation_pin, manifest):
    """Recheck raw outputs, crop/source frame and typed-source provenance."""
    request = record['request']; observations = record['observations']; summary = record['summary']
    protocol = helpers['source_crop_protocol']; derivation = helpers['fresh_source_derivation']
    protocol.validate_request(request)
    geometry = {k: deepcopy(cache['geometry'][k]) for k in ('original_size', 'upright_size', 'orientation_ccw')}
    if (request['page_number'] != page['page_number'] or request['row_index'] != context['row_index'] or
            request['field'] != context['role'] or request['geometry'] != geometry or
            request['source_image']['sha256'] != page['source_sha256'] or
            request['source_band'] != context['source_band'] or
            request['source_inputs']['native'] != observation_pin):
        raise ValueError('fresh_request_original_context_or_source_frame_differs')
    source_context = record['source_context']
    if (source_context.get('contract') != 'document-ai-whole-cell-source-context.v1' or
            source_context.get('request_binding') != {k: v for k, v in request.items() if k != 'context_proof'} or
            source_context.get('derivation', {}).get('actual_context_sha256') != digest(context['evidence']) or
            source_context.get('derivation', {}).get('crop_admission', {}).get('eligible') is not True):
        raise ValueError('fresh_source_context_hash_or_original_request_binding_differs')
    inventory, invalid = derivation.inventory(cache, geometry)
    interval, proof = derivation.row_interval(context['evidence'])
    if invalid or not proof['source_band_fits_strict_interval'] or request['row_barrier_interval'] != interval:
        raise ValueError('fresh_request_does_not_fit_reconstructed_whole_source_barriers')
    crop = protocol.whole_word_crop(request, inventory)
    crop['independently_reconstructed_source_context'] = True
    if record['crop'] != crop or observations.get('crop') != crop:
        raise ValueError('fresh_physical_crop_differs_from_original_source_closure')
    if (observations.get('contract') != 'document-ai-whole-cell-source-result.v1' or
            any(observations.get(k) != request[k] for k in ('request_id', 'page_number', 'row_index', 'field')) or
            observations.get('source_image') != request['source_image'] or observations.get('geometry') != geometry or
            observations.get('literal_source_only') is not True or observations.get('logical_field_values_assigned') is not False or
            observations.get('baseline_cache_modified') is not False or observations.get('extra_independent_engine_families') != 0):
        raise ValueError('fresh_observation_source_or_no_business_policy_differs')
    for key in ('observations_pin', 'summary_pin', 'closed_source'):
        if not _pin(record.get(key)):
            raise ValueError('fresh_actual_closed_source_artifact_pin_required')
    raw = record['raw_proof']; detector = raw['detector']; recognizers = raw['recognizers']; pins = raw['pins']
    if (not _pin(pins.get('detector')) or not _pin(pins.get('tesseract_tsv')) or
            not isinstance(pins.get('recognizers'), list) or not all(_pin(p) for p in pins['recognizers'])):
        raise ValueError('fresh_actual_raw_detector_recognizer_TSV_pins_required')
    if (not _pin(record.get('physical_crop')) or
            not _path_same(detector.get('input_path'), record['physical_crop']['path'])):
        raise ValueError('actual_detector_input_must_be_pinned_whole_ROI_crop')
    detected = protocol.native_detections(detector['dt_polys'], detector['dt_scores'], crop, geometry)
    count = len(detected)
    if (summary.get('contract') != 'document-ai-whole-cell-source-result.v1' or summary.get('component') != 'whole-cell-source'
            or summary.get('status') != 'COMPLETE' or summary.get('executed') is not True or
            summary.get('request_id') != request['request_id'] or summary.get('requests_selected') != 1 or
            summary.get('requests_completed') != 1 or summary.get('optimizer_updates') != 0 or
            summary.get('canonical_values_modified') is not False or summary.get('baseline_cache_modified') is not False or
            summary.get('assistant_image_reads') != 0 or summary.get('source_image_decodes_completed') != 1 or
            summary.get('resource_policy') != RESOURCES or
            summary.get('worker', {}).get('sha256') != 'b5f498a65e9494f449f6aed9e073aea44958aa5dc22dfe75f0f22451a02324bf' or
            summary.get('actual_detector_regions') != count or summary.get('positive_detector_recognizer_path') is not bool(count) or
            summary.get('new_calls_completed') != {'Paddle_detector': 1, 'Paddle_Thai_recognizer': count, 'Tesseract_ROI': 1} or
            len(recognizers) != count or len(pins['recognizers']) != count):
        raise ValueError('actual_complete_fresh_native_calls_or_scope_required')
    models = summary.get('models') or {}; tess = summary.get('tesseract') or {}
    selected = {'detector': ('PP-OCRv5_server_det', '183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d'),
                'recognizer': ('th_PP-OCRv5_mobile_rec', '45ec91f2322b58b8d30ba27d18fcfdbb8bf388b918dd978162d2af91e0c66d4b')}
    if any(models.get(k, {}).get('model_name') != name or
           models.get(k, {}).get('files', {}).get('inference.pdiparams', {}).get('sha256') != sha
           for k, (name, sha) in selected.items()):
        raise ValueError('actual_selected_fresh_detector_and_Thai_recognizer_required')
    if (tess.get('reader', {}).get('sha256') != 'c1b16bdd8e20dfd7faf4b91c7c8c11a0efe4ea4e715691cf554b6a39861cf4b1' or
            tess.get('tsv_config', {}).get('sha256') != '59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04'):
        raise ValueError('actual_original_Tess_reader_and_TSV_dependency_required')
    new_primary = observations.get('Paddle_observations')
    if not isinstance(new_primary, list) or len(new_primary) != count:
        raise ValueError('all_actual_fresh_primary_detections_required')
    primary = []; old_primary = context['primary']+context['alternatives']
    for index, (native, rec, observation) in enumerate(zip(detected, recognizers, new_primary)):
        if (rec.get('detection_index') != index or any(observation.get(k) != v for k, v in native.items()) or
                observation.get('raw_text') != rec['raw'].get('rec_text') or
                observation.get('confidence') != rec['raw'].get('rec_score') or
                not isinstance(observation.get('raw_text'), str) or not _finite(observation.get('confidence')) or
                not 0 <= observation['confidence'] <= 1 or observation.get('engine_family') != 'PADDLE' or
                observation.get('engine') != 'NEW_WHOLE_CELL_PADDLE_SERVER_DET_THAI_REC' or
                observation.get('token_id') != request['request_id']+':paddle:%03d' % index or
                observation.get('character_boxes_available') is not False or
                observation.get('same_family_as_cached_Paddle') is not True):
            raise ValueError('fresh_recognizer_literal_not_tied_to_actual_detector_polygon')
        if not _pin(observation.get('recognition_image')):
            raise ValueError('actual_detected_region_recognition_crop_pin_required')
        if not _path_same(rec['raw'].get('input_path'), observation['recognition_image']['path']):
            raise ValueError('actual_recognizer_input_differs_from_detected_region_crop')
        primary.append(_normalized(observation['raw_text'], native['bbox_upright'], observation['confidence'],
            observation['token_id'], 'paddle', native['polygon_original'], old_primary, context, helpers, observation['engine']))
    expected_tess = _tsv(raw['tesseract_tsv'], crop, request['request_id']+':tesseract')
    if observations.get('Tesseract_observations') != expected_tess:
        raise ValueError('fresh_secondary_does_not_match_all_actual_TSV_words_and_lines')
    secondary = [_normalized(t['raw_text'], t['bbox'], t['confidence'], t['token_id'], 'tesseract',
        t['word_source_spans'], context['secondary'], context, helpers, t['engine']) for t in expected_tess]
    proof = {'manifest': deepcopy(manifest), 'request_id': request['request_id'],
        'observations': deepcopy(record['observations_pin']), 'native_summary': deepcopy(record['summary_pin']),
        'closed_source': deepcopy(record['closed_source']), 'raw_outputs': deepcopy(pins),
        'original_context_sha256': digest(context['evidence']), 'source_band': deepcopy(context['source_band']),
        'physical_crop': deepcopy(crop), 'actual_detector_regions': count,
        'geometry_kind': 'measured_text_region_polygon_and_TSV_word_union_not_characters',
        'cached_and_fresh_same_family_are_not_extra_votes': True}
    return {'primary': primary, 'secondary': secondary, 'evidence': proof, 'request_id': request['request_id']}


def _all(page, cache, observation, helpers, observation_pin):
    runtime = helpers.get('fresh_source_reads')
    if (not isinstance(runtime, dict) or runtime.get('contract') != RUNTIME or not _pin(runtime.get('manifest')) or
            not isinstance(runtime.get('records'), list) or len(runtime['records']) > MAX_RECORDS):
        raise ValueError('explicit_pinned_fresh_source_runtime_required')
    if cache.get('geometry', {}).get('machine_only') is not True or cache['geometry'].get('vision_LLM_calls') != 0:
        raise ValueError('machine_only_retained_geometry_required')
    cells = helpers['cell_association']; contexts, rejected = cells._contexts(page, cache, observation, helpers, observation_pin)
    by_key = {(c['row_index'], c['role']): c for c in contexts}; records = {}; seen = set()
    for record in runtime['records']:
        request = record.get('request') or {}
        if request.get('page_number') != page['page_number']:
            continue
        key = (request.get('row_index'), request.get('field')); identity = request.get('request_id')
        if identity in seen or key in records or key not in by_key:
            raise ValueError('unique_original_source_request_context_required')
        seen.add(identity)
        records[key] = _record(record, page, cache, by_key[key], helpers, observation_pin, runtime['manifest'])
    return by_key, records, rejected


def _value(context, actual, all_records, helpers):
    rules = helpers['rules']; band = context['source_band']; anchor = context['anchor']
    # Other overlapping new requests remain alternative views, never extra votes.
    alternatives = [token for item in all_records.values() if item is not actual
                    for token in item['primary']+item['secondary'] if rules._intersection(token['bbox'], band)]
    value, reason = rules._read_cell(band, actual['primary'], actual['secondary'], anchor, context['role'], alternatives)
    if value is None:
        raise ValueError('fresh_read_rejected:'+str(reason))
    if any(not _same_baseline(anchor['token']['bbox'], t['bbox']) for t in value['tokens']):
        raise ValueError('fresh_value_not_on_established_source_name_baseline')
    old, old_reason = rules._read_cell(band, context['primary'], context['secondary'], anchor,
                                     context['role'], context['alternatives'])
    if old is not None:
        old_field = {'raw_value': old['tokens'][0]['text'], 'normalized_value': old['normalized_value']}
        new_field = {'raw_value': value['tokens'][0]['text'], 'normalized_value': value['normalized_value']}
        if not helpers['correction_bridge']._old_same(old_field, new_field, context['role']):
            raise ValueError('genuinely_qualified_old_and_fresh_source_pairs_disagree')
    return value, alternatives, {'old_pair_qualified': old is not None, 'old_pair_rejection': old_reason,
        'policy': 'UNCHANGED_FROZEN_READER_EACH_FULL_READING_QUALIFIED_PAIR_CONFLICT_ABSTAINS'}


def verify(page, cache, observation, helpers, observation_pin, row_index, role, evidence):
    frozen = digest([page, cache, observation]); contexts, records, _ = _all(page, cache, observation, helpers, observation_pin)
    key = (row_index, role)
    if key not in contexts or key not in records:
        raise ValueError('completed_fresh_read_for_exact_original_context_required')
    context = contexts[key]; actual = records[key]
    value, alternatives, conflict = _value(context, actual, records, helpers)
    expected = {'route': ROUTE, 'original_context': deepcopy(context['evidence']),
                'fresh_source_evidence': deepcopy(actual['evidence'])}
    if evidence != expected:
        raise ValueError('fresh_source_evidence_differs_from_original_and_native_raw_records')
    out = deepcopy(context)
    out.update(fresh_primary=actual['primary'], fresh_secondary=actual['secondary'], fresh_alternatives=alternatives,
               fresh_source_evidence=actual['evidence'], fresh_value=value, old_conflict_audit=conflict,
               retained_source_alternatives={'primary': deepcopy(context['primary']),
                   'secondary': deepcopy(context['secondary']), 'alternatives': deepcopy(context['alternatives'])})
    if digest([page, cache, observation]) != frozen:
        raise ValueError('fresh_source_verification_mutated_original_inputs')
    return out


def propose(page, cache, observation, helpers, observation_pin):
    frozen = digest([page, cache, observation]); audit = {'contract': VERSION, 'route': ROUTE,
        'status': 'ABSTAINED', 'proposed': [], 'changes': [], 'rejected': [], 'source_contexts': [],
        'new_OCR_calls': 0, 'new_model_calls': 0, 'source_image_decodes': 0, 'reference_access': False,
        'native_cells_used': 0, 'physical_cell_borders_claimed': False, 'old_cache_modified': False}
    try:
        contexts, records, rejects = _all(page, cache, observation, helpers, observation_pin)
        audit['rejected'].extend(rejects)
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        audit['rejected'].append({'reason': str(exc)}); return audit
    pending = {}; pairs = {}; rules = helpers['rules']; rows = page['product_rows']
    for key, actual in records.items():
        context = contexts[key]; index, role = key
        evidence = {'route': ROUTE, 'original_context': deepcopy(context['evidence']),
                    'fresh_source_evidence': deepcopy(actual['evidence'])}
        audit['source_contexts'].append(deepcopy(evidence))
        try:
            value, _, conflict = _value(context, actual, records, helpers)
            before = (rows[index].get('fields') or {}).get(role)
            field = helpers['cell_association']._field(value, before, context['evidence'])
            field.update(association_basis=ROUTE, fresh_source_evidence=deepcopy(actual['evidence']),
                         measured_geometry_kind='actual_text_region_not_character_boxes',
                         extra_independent_engine_families=0)
            event = {'row_index': index, 'field': role, 'before': deepcopy(before), 'candidate': field,
                     'evidence': evidence, 'reason': 'FRESH_INDEPENDENT_PRINTED_SOURCE_REASSOCIATION',
                     'old_source_conflict_audit': conflict}
            audit['proposed'].append(deepcopy(event))
            if helpers['correction_bridge']._old_same(before, field, role):
                raise ValueError('existing_field_already_matches_fresh_printed_source')
            pending[key] = event; pairs[key] = value['tokens']
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            audit['rejected'].append({'row_index': index, 'field': role, 'reason': str(exc)})
    aliases = {}
    for key, words in pairs.items():
        for token in words:
            for alias in token['aliases']:
                aliases.setdefault(alias, set()).add(key)
    while True:
        failed = []
        for key, event in pending.items():
            reason = None
            if any(len(aliases[a]) != 1 for t in pairs[key] for a in t['aliases']):
                reason = 'ambiguous_fresh_physical_source_owner'
            for owner in _foreign(rows, key[0], key[1], pairs[key], helpers):
                other = (owner['row_index'], owner['field'])
                if other[0] != key[0] or other[1] not in ('quantity', 'unit') or other not in pending:
                    reason = 'preserved_foreign_source_owner'; break
            if reason:
                failed.append((key, reason))
        if not failed:
            break
        for key, reason in failed:
            pending.pop(key); audit['rejected'].append({'row_index': key[0], 'field': key[1], 'reason': reason})
    audit['changes'] = [deepcopy(event) for event in pending.values()]
    audit['status'] = 'PROPOSED' if audit['changes'] else 'ABSTAINED'
    if digest([page, cache, observation]) != frozen:
        raise ValueError('fresh_source_proposal_mutated_original_inputs')
    return audit
