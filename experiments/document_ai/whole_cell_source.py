"""Source-only protocol for a bounded NEW detector/recognizer/Tess experiment.

No image, SDK, model, subprocess or business/reference dependency is imported.
Detector polygons are text-region detections, never character/glyph boxes.
"""
from __future__ import annotations

import math
import re

PLAN_CONTRACT = 'document-ai-whole-cell-source-plan.v1'
TOKEN_CONTRACT = 'document-ai-source-token-geometry.v1'
REQUEST_KEYS = {'request_id', 'page_number', 'row_index', 'field', 'source_image',
                'geometry', 'source_band', 'row_barrier_interval',
                'source_token_inventory', 'context_proof', 'source_inputs'}
LIMITS = {'maximum_source_page_pixels': 20000000,
          'maximum_ROI_pixels': 1000000, 'maximum_ROI_side': 2048,
          'maximum_detections_per_ROI': 16, 'maximum_recognition_aspect_ratio': 64,
          'SDK_startup_seconds': 480, 'detector_predict_seconds': 120,
          'recognizer_predict_seconds': 60, 'tesseract_seconds': 120,
          'maximum_worker_seconds': 2100}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def valid_pin(value):
    return (type(value) is dict and set(value) == {'path', 'sha256'} and
            isinstance(value['path'], str) and bool(value['path']) and
            isinstance(value['sha256'], str) and
            re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None)


def validate_geometry(value):
    if type(value) is not dict or set(value) != {'original_size', 'upright_size', 'orientation_ccw'}:
        raise ValueError('Exact saved source geometry required')
    for key in ('original_size', 'upright_size'):
        if (type(value[key]) is not list or len(value[key]) != 2 or
                any(type(v) is not int or v <= 0 for v in value[key])):
            raise ValueError('Exact positive source pixel dimensions required')
    angle = value['orientation_ccw']
    if type(angle) is not int or angle not in (0, 90, 180, 270):
        raise ValueError('Only exact saved right-angle orientation is permitted')
    expected = value['original_size'][::-1] if angle in (90, 270) else value['original_size']
    if value['upright_size'] != expected:
        raise ValueError('Source and upright dimensions disagree')
    if math.prod(value['original_size']) > LIMITS['maximum_source_page_pixels']:
        raise ValueError('Source decode pixel budget exceeded')
    return value


def valid_box(box, size):
    return (type(box) in (list, tuple) and len(box) == 4 and all(finite(x) for x in box)
            and 0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1])


def validate_request(request):
    if type(request) is not dict or set(request) != REQUEST_KEYS:
        raise ValueError('Request accepts source identity/geometry only, no expected answers')
    if (not isinstance(request['request_id'], str) or
            re.fullmatch('[A-Za-z0-9_-]{1,100}', request['request_id']) is None or
            type(request['page_number']) is not int or not 1 <= request['page_number'] <= 484 or
            type(request['row_index']) is not int or request['row_index'] < 0 or
            request['field'] not in ('quantity', 'unit')):
        raise ValueError('Bound source request identity required')
    validate_geometry(request['geometry'])
    if not valid_box(request['source_band'], request['geometry']['upright_size']):
        raise ValueError('Whole source band must fit the actual upright source')
    barrier = request['row_barrier_interval']
    if (type(barrier) is not list or len(barrier) != 2 or not all(finite(x) for x in barrier)
            or not 0 <= barrier[0] < barrier[1] <= request['geometry']['upright_size'][1]
            or not barrier[0] <= request['source_band'][1] < request['source_band'][3] <= barrier[1]):
        raise ValueError('Source band crosses a canonical row barrier')
    for key in ('source_image', 'source_token_inventory', 'context_proof'):
        if not valid_pin(request[key]):
            raise ValueError('Exact source artifact pins required: ' + key)
    inputs = request['source_inputs']
    if (type(inputs) is not dict or set(inputs) != {'cache', 'canonical', 'native'} or
            not all(valid_pin(v) for v in inputs.values())):
        raise ValueError('Original cache/canonical/native provenance required')
    return request


def validate_plan(plan):
    if (type(plan) is not dict or set(plan) != {'contract', 'machine_only', 'requests'} or
            plan['contract'] != PLAN_CONTRACT or plan['machine_only'] is not True or
            type(plan['requests']) is not list or not 1 <= len(plan['requests']) <= 60):
        raise ValueError('Bounded source-only request inventory required')
    ids = []
    for request in plan['requests']:
        validate_request(request)
        ids.append(request['request_id'])
    if len(set(ids)) != len(ids):
        raise ValueError('Request IDs must be unique')
    return plan['requests']


def validate_tokens(inventory, request):
    if (type(inventory) is not dict or set(inventory) !=
            {'contract', 'page_number', 'source_sha256', 'geometry', 'tokens'} or
            inventory['contract'] != TOKEN_CONTRACT or
            inventory['page_number'] != request['page_number'] or
            inventory['source_sha256'] != request['source_image']['sha256'] or
            inventory['geometry'] != request['geometry'] or type(inventory['tokens']) is not list or
            not 1 <= len(inventory['tokens']) <= 50000):
        raise ValueError('Whole-page cached token geometry/source identity differs')
    seen = set()
    for token in inventory['tokens']:
        if (type(token) is not dict or set(token) != {'token_id', 'engine', 'bbox'} or
                not isinstance(token['token_id'], str) or not token['token_id'] or
                token['token_id'] in seen or not isinstance(token['engine'], str) or
                not token['engine'] or token['engine'].upper().startswith(
                    ('HUMAN', 'ASSISTANT', 'USER', 'GOLD', 'SILVER', 'BUSINESS')) or
                not valid_box(token['bbox'], request['geometry']['upright_size'])):
            raise ValueError('Unique actual machine token geometry required')
        seen.add(token['token_id'])
    return inventory['tokens']


def intersect(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def whole_word_crop(request, inventory, padding=(8, 4)):
    """Fixed-point expansion includes ALL intersecting cached detections, or refuses.

    Padding may stop at an image/row boundary; source word geometry is never cut.
    The canonical row interval includes protected/unknown neighbour barriers.
    """
    validate_request(request)
    tokens = validate_tokens(inventory, request)
    if (type(padding) not in (list, tuple) or len(padding) != 2 or
            any(type(x) is not int or not 0 <= x <= 32 for x in padding)):
        raise ValueError('Bounded integer padding required')
    size = request['geometry']['upright_size']; band = request['source_band']
    lo, hi = request['row_barrier_interval']; px, py = padding
    crop = [max(0, math.floor(band[0]-px)), max(math.ceil(lo), math.floor(band[1]-py)),
            min(size[0], math.ceil(band[2]+px)), min(math.floor(hi), math.ceil(band[3]+py))]
    if not (crop[0] <= band[0] and crop[1] <= band[1] and
            crop[2] >= band[2] and crop[3] >= band[3]):
        raise ValueError('Integer physical crop would cut the source band')
    included = set()
    for _ in range(len(tokens)+1):
        newly = [t for t in tokens if intersect(crop, t['bbox'])]
        next_box = list(crop)
        for token in newly:
            b = token['bbox']
            if b[1] < lo or b[3] > hi:
                raise ValueError('Whole intersecting cached word crosses canonical row barrier')
            next_box = [min(next_box[0], math.floor(b[0])), min(next_box[1], math.floor(b[1])),
                        max(next_box[2], math.ceil(b[2])), max(next_box[3], math.ceil(b[3]))]
            included.add(token['token_id'])
        if next_box[1] < lo or next_box[3] > hi:
            raise ValueError('Integer whole-word expansion crosses canonical row barrier')
        w, h = next_box[2]-next_box[0], next_box[3]-next_box[1]
        if w*h > LIMITS['maximum_ROI_pixels'] or max(w, h) > LIMITS['maximum_ROI_side']:
            raise ValueError('Whole-word ROI exceeds finite input pixel budget')
        if next_box == crop:
            return {'source_band': list(band), 'crop_bbox_upright': crop,
                    'physical_crop_size': [w, h], 'row_barrier_interval': [lo, hi],
                    'crop_to_upright_affine': [1, 0, crop[0], 0, 1, crop[1]],
                    'whole_cached_token_ids': sorted(included), 'source_band_clipped': False,
                    'whole_word_closure_complete': True, 'padding': list(padding)}
        crop = next_box
    raise ValueError('Whole-word closure did not converge')


def detector_options():
    return {'limit_side_len': 640, 'limit_type': 'max', 'max_side_limit': 640}


def assert_detector_settings(model):
    actual = model.runner._config
    if any(actual.get(k) != v for k, v in
           {'cpu_threads': 1, 'run_mode': 'paddle', 'device_type': 'cpu'}.items()):
        raise ValueError('Actual CPU1 paddle_static runner required')
    resize = model.pre_tfs['Resize']
    if (resize.resize_type != 0 or resize.limit_type != 'max' or
            resize.limit_side_len != 640 or model.max_side_limit != 640):
        raise ValueError('Actual detector max-side640 resize required')
    return {'runner': {k: actual[k] for k in ('cpu_threads', 'run_mode', 'device_type')},
            'resize_type': resize.resize_type, 'limit_type': resize.limit_type,
            'limit_side_len': resize.limit_side_len, 'predictor_max_side_limit': model.max_side_limit,
            'predict_call_overrides': detector_options(),
            'stride32_alignment_may_raise_short_side_to32': True,
            'min_side_upscaling_to640': False}


def point_to_original(point, geometry):
    x, y = point; w, h = geometry['original_size']; a = geometry['orientation_ccw']
    return {0: [x, y], 90: [w-y, x], 180: [w-x, h-y], 270: [y, h-x]}[a]


def native_detections(polygons, scores, crop, geometry):
    """Translate actual detector polygons. No clipping, split boxes or glyph claim."""
    validate_geometry(geometry)
    if (not valid_box(crop.get('crop_bbox_upright'), geometry['upright_size']) or
            crop.get('physical_crop_size') != [crop['crop_bbox_upright'][2]-crop['crop_bbox_upright'][0],
                                               crop['crop_bbox_upright'][3]-crop['crop_bbox_upright'][1]]):
        raise ValueError('Exact physical detector input frame required')
    if (type(polygons) is not list or type(scores) is not list or len(polygons) != len(scores)
            or len(polygons) > LIMITS['maximum_detections_per_ROI']):
        raise ValueError('Actual detector output count invalid/exceeds bounded ROI budget')
    result = []; w, h = crop['physical_crop_size']; x0, y0 = crop['crop_bbox_upright'][:2]
    for i, (polygon, score) in enumerate(zip(polygons, scores)):
        if (type(polygon) is not list or len(polygon) != 4 or
                any(type(p) is not list or len(p) != 2 or not all(finite(v) for v in p)
                    or not 0 <= p[0] <= w or not 0 <= p[1] <= h for p in polygon) or
                not finite(score) or not 0 <= score <= 1):
            raise ValueError('Actual native text polygon/score is invalid; never clip')
        xs, ys = zip(*polygon)
        if min(xs) == max(xs) or min(ys) == max(ys):
            raise ValueError('Degenerate actual detector polygon')
        crosses = []
        for j in range(4):
            a, b, c = polygon[j], polygon[(j+1) % 4], polygon[(j+2) % 4]
            crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
        if not (all(v > 0 for v in crosses) or all(v < 0 for v in crosses)):
            raise ValueError('Native quadrilateral is degenerate or self-intersecting')
        upright = [[x+x0, y+y0] for x, y in polygon]
        result.append({'detection_index': i, 'polygon_crop': polygon, 'polygon_upright': upright,
                       'polygon_original': [point_to_original(p, geometry) for p in upright],
                       'detection_score': score,
                       'bbox_upright': [min(xs)+x0, min(ys)+y0, max(xs)+x0, max(ys)+y0],
                       'recognition_crop_bbox': [math.floor(min(xs)), math.floor(min(ys)),
                                                 math.ceil(max(xs)), math.ceil(max(ys))],
                       'source_bbox_kind': 'actual_detector_text_region_polygon_not_character_boxes'})
    return result


def recognition_crop(detection):
    b = detection['recognition_crop_bbox']; w, h = b[2]-b[0], b[3]-b[1]
    if w <= 0 or h <= 0 or max(w/h, h/w) > LIMITS['maximum_recognition_aspect_ratio']:
        raise ValueError('Recognition crop aspect budget exceeded; no truncation')
    return b
