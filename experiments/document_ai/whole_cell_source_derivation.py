"""Rebuild a requested OCR region from the fixed retained machine sources.

This module never decodes an image or opens a reference/score file. Request
geometry is compared with a newly rebuilt context; its self-consistent JSON is
not evidence that the geometry came from the retained cache.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

CONTRACT = 'document-ai-whole-cell-derivation-recipe.v1'
EXPERIMENT_SHA = '4abb9793646ae14d4897b59870ac06507f7a092d8190728c9d66911444cc34b6'
FIXED = {
    'profile': '2c7a3759bf2edc3fd55662581a9d30b2e0eaf203e3066d865018dfdbd32ed153',
    'baseline_complete': '20c70db63ee7a47305230468a50aa80ad637f1ea6ca7dfa56fb43ce9c5b73017',
    'native_summary': 'f48092df6a7ae7abeabad7588c397e053eb8e4a7487712ec38fcbde3f679fde3',
}
SOURCE_SHA = {
    'bridge': '130e5d1e37b725b0b2e9b1b2439fcad7c43bd443ccdd40672d570f9b248c5096',
    'eligibility': 'c2ae9ef32d1057ce836249c43e2e5a05dd4f4c120d2e92c2a1afadbd3a0982bd',
    'cell_association': 'bf41b9114165d83b72b651a6ec4aa1fd4a5e046485d4f081b3adff499c3e616b',
}


def _read(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return json.load(stream)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _same(a, b):
    return (isinstance(a, dict) and isinstance(b, dict) and
            a.get('sha256') == b.get('sha256') and
            str(a.get('path')).replace('\\', '/').casefold() ==
            str(b.get('path')).replace('\\', '/').casefold())


def _load(name, record, check):
    actual = Path(check(record)).resolve()
    current = sys.modules.get(name)
    if current is not None:
        origin = getattr(current, '__file__', None)
        if not origin or hashlib.sha256(Path(origin).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Foreign preloaded derivation helper: ' + name)
        return current
    spec = importlib.util.spec_from_file_location(name, actual)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _box(value):
    if not isinstance(value, (list, tuple)):
        return None
    try:
        if len(value) == 4 and all(type(x) in (int, float) for x in value):
            box = list(map(float, value))
        else:
            xs, ys = zip(*value)
            if any(type(x) not in (int, float) for x in (*xs, *ys)):
                return None
            box = [min(xs), min(ys), max(xs), max(ys)]
        return box if all(math.isfinite(x) for x in box) and box[0] < box[2] and box[1] < box[3] else None
    except (TypeError, ValueError):
        return None


def inventory(cache, geometry):
    """ALL cached records, including low confidence/unrecognised text types."""
    tokens = []
    invalid = []
    size = geometry['upright_size']
    families = [('working_tokens', cache.get('working_tokens', [])),
                ('tesseract_working_tokens', cache.get('tesseract_working_tokens', []))]
    families += [('targeted_views/' + str(i) + '/tokens', v.get('tokens', []))
                 for i, v in enumerate(cache.get('targeted_views', []))]
    for family, words in families:
        for index, word in enumerate(words):
            if not isinstance(word, dict):
                invalid.append([family, index]); continue
            box = _box(word.get('bbox', word.get('box')))
            engine = word.get('engine') or 'UNSPECIFIED_MACHINE_CACHE_RECORD'
            if (box is None or not 0 <= box[0] < box[2] <= size[0] or
                    not 0 <= box[1] < box[3] <= size[1] or not isinstance(engine, str) or
                    engine.upper().startswith(('HUMAN', 'ASSISTANT', 'USER', 'GOLD', 'SILVER', 'BUSINESS'))):
                invalid.append([family, index]); continue
            key = family.replace('/', '_') + ':' + str(index) + ':' + str(word.get('token_id') or 'no_original_id')
            tokens.append({'token_id': key, 'engine': engine, 'bbox': box})
    return {'contract': 'document-ai-source-token-geometry.v1', 'page_number': cache['page_number'],
            'source_sha256': cache['source_sha256'], 'geometry': deepcopy(geometry), 'tokens': tokens}, invalid


def row_interval(evidence):
    """Physical permission uses foreign WHOLE edges, not a fractional midpoint.

    The old logical band remains unchanged. Floor/ceil may use genuinely empty
    space between rows; a foreign whole word is never clipped to make it fit.
    """
    band = evidence['source_header_band']; anchor = evidence['anchor_bbox']
    cy = (anchor[1] + anchor[3]) / 2
    low = max(w['bbox'][3] for words in evidence['whole_source_headers'].values() for w in words)
    high = evidence['region']['bbox'][3]
    used = []
    for barrier in evidence['negative_row_barriers']:
        if barrier['row_index'] == evidence['row_index']:
            continue
        box = barrier['bbox']; other = (box[1] + box[3]) / 2
        if max(anchor[1], box[1]) < min(anchor[3], box[3]) or cy == other:
            raise ValueError('Ambiguous negative row barrier')
        if other < cy:
            low = max(low, box[3])
        else:
            high = min(high, box[1])
        used.append({'row_index': barrier['row_index'], 'kind': barrier['kind'],
                     'bbox': deepcopy(box), 'side': 'above' if other < cy else 'below'})
    fits = low <= band[1] < band[3] <= high
    # Held requests remain schema-valid in the ALL60 inventory. The native
    # worker must refuse crop_admission=false before attempting any decode.
    interval = [low, high] if fits else [band[1], band[3]]
    return interval, {'strict_row_interval': [low, high], 'source_band_fits_strict_interval': fits,
                      'foreign_whole_row_edges': used, 'logical_midpoints_used_as_physical_edges': False}


def page_contexts(recipe, request, check):
    """Selected-page-only authoritative baseline/cache/native reconstruction."""
    if set(recipe) != {'contract', 'experiment'} or recipe.get('contract') != CONTRACT:
        raise ValueError('Exact fixed source derivation recipe required')
    if recipe['experiment'].get('sha256') != EXPERIMENT_SHA:
        raise ValueError('Actual closed cell-v2 source authority changed')
    spec = _read(check(recipe['experiment']))
    for key, expected in FIXED.items():
        if spec[key].get('sha256') != expected:
            raise ValueError('Fixed source authority differs: ' + key)
    for role, expected in SOURCE_SHA.items():
        if spec['sources'][role].get('sha256') != expected:
            raise ValueError('Original source-cell recipe differs: ' + role)
    control = _read(check(spec['baseline_complete']))
    if control.get('status') != 'COMPLETE' or control.get('variant') != 'control' or control.get('pages') != 484:
        raise ValueError('Original completed canonical control required')
    records = [x for x in control['source_inventory'] if x['page_number'] == request['page_number']]
    if len(records) != 1:
        raise ValueError('Unique authoritative canonical source page required')
    authority = records[0]
    if (not _same(authority['retained_cache'], request['source_inputs']['cache']) or
            not _same(authority['native_observation'], request['source_inputs']['native'])):
        raise ValueError('Cache/native request not in actual saved control')
    canonical = _read(check(request['source_inputs']['canonical']))
    if _digest(canonical) != authority['prediction_content_sha256']:
        raise ValueError('Canonical extraction content differs from saved323 control')
    cache = _read(check(request['source_inputs']['cache']))
    observation = _read(check(request['source_inputs']['native']))
    geometry = {k: deepcopy(cache['geometry'][k]) for k in ('original_size', 'upright_size', 'orientation_ccw')}
    if (request['geometry'] != geometry or canonical.get('page_number') != request['page_number'] or
            canonical.get('source_sha256') != authority['source_sha256'] or
            not _same(request['source_image'], observation['source_image']) or
            request['source_image']['sha256'] != authority['source_sha256']):
        raise ValueError('Original source/image alias/frame differs')
    profile = _read(check(spec['profile']))
    helpers_by_name = {Path(r['path'].replace('\\', '/')).name: r for r in profile['bridge_sources']}
    _load('eval_geometry', helpers_by_name['eval_geometry.py'], check)
    assets = _load('_whole_cell_original_eval_assets', helpers_by_name['eval_assets.py'], check)
    # Only retained source and grammar/frame helpers. No reference, mapping,
    # score, labels, source images, model SDK or native model imports are read.
    paths = [Path(check(r)) for r in profile['parser_sources']]
    adaptive = [p for p in paths if p.name == 'adaptive_recognition.py']
    if len(adaptive) != 1:
        raise ValueError('Retained parser package source root required')
    local_profile = deepcopy(profile)
    local_profile['frozen_source_root'] = str(adaptive[0].parent.parent)
    local_profile['dependencies'] = [{**r, 'path': str(check(r))} for r in profile['dependencies']]
    local_profile['pins']['frame_io'] = {**profile['pins']['frame_io'], 'path': str(check(profile['pins']['frame_io']))}
    _load('correction_eligibility', spec['sources']['eligibility'], check)
    bridge = _load('_whole_cell_original_correction_bridge', spec['sources']['bridge'], check)
    cells = _load('_whole_cell_original_source_cells', spec['sources']['cell_association'], check)
    helpers = assets.runtime(local_profile); helpers['correction_bridge'] = bridge
    upright = helpers['io'].upright_from_original(canonical, cache['geometry'], helpers['mapper'])
    sealed = _digest([canonical, cache, observation])
    contexts, _ = cells._contexts(upright, cache, observation, helpers, request['source_inputs']['native'])
    if sealed != _digest([canonical, cache, observation]):
        raise ValueError('Immutable recomputed source-cell context required')
    return cache, contexts, geometry


def source_context(recipe, request, check):
    cache, contexts, geometry = page_contexts(recipe, request, check)
    matches = [x for x in contexts if x['row_index'] == request['row_index'] and x['role'] == request['field']]
    if len(matches) != 1:
        raise ValueError('Unique immutable recomputed source-cell context required')
    return cache, matches[0], geometry


def reconstruct(request, context, check):
    """Worker entry point. The caller must pin this module and the recipe."""
    if (context.get('contract') != 'document-ai-whole-cell-source-context.v1' or
            context.get('request_binding') != {k: v for k, v in request.items() if k != 'context_proof'}):
        raise ValueError('Exact context request binding required')
    recipe = _read(check(context['derivation']['recipe']))
    cache, actual, geometry = source_context(recipe, request, check)
    tokens, invalid = inventory(cache, geometry)
    interval, proof = row_interval(actual['evidence'])
    band = deepcopy(actual['source_band'])
    if band != request['source_band'] or interval != request['row_barrier_interval']:
        raise ValueError('Request band/row barriers differ from actual source reconstruction')
    explicit = context['derivation'].get('crop_admission', {})
    allowed = proof['source_band_fits_strict_interval'] and not invalid and explicit.get('eligible') is True
    return {'inventory': tokens, 'source_band': band, 'row_barrier_interval': interval,
            'crop_admission': {'eligible': allowed}, 'actual_context_sha256': _digest(actual['evidence']),
            'row_interval_proof': proof, 'unrepresentable_cache_records': invalid,
            'source_reconstructed': True, 'reference_files_opened': 0, 'source_image_decodes': 0}
