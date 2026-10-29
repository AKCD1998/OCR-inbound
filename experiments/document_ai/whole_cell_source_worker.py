"""Root-admitted HQ ONE-ROI new Paddle detection/Thai recognition/Tess canary.

Defaults to model-free config validation. This worker cannot change canonical
data, reference scores or the original cache. Detection polygons are actual
text-region observations; recognition is tied to those polygons, not fake glyphs.
"""
from __future__ import annotations

import argparse
import gc
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import threading
import time

from component_common import RESOURCES, checked, pin, read, save, sha, verify_admission
from whole_cell_source import (LIMITS, assert_detector_settings, detector_options,
                               native_detections, recognition_crop, validate_plan,
                               validate_request, valid_pin, whole_word_crop)

COMPONENT = 'whole-cell-source'
CONFIG_CONTRACT = 'document-ai-whole-cell-source-config.v1'
SUMMARY_CONTRACT = 'document-ai-whole-cell-source-result.v1'
TESS_READER_SHA = 'c1b16bdd8e20dfd7faf4b91c7c8c11a0efe4ea4e715691cf554b6a39861cf4b1'
TESS_EXE_SHA = 'babb405f4366b480d02cd8ff2bac8d497170f6c1711ce6f3d5d8bf0fb7fa6ed9'
TESS_TSV_CONFIG_SHA = '59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04'
MODEL_FILES = {
    'detector': ('PP-OCRv5_server_det', {
        'inference.json': ('af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28', 402480),
        'inference.pdiparams': ('183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d', 87932887),
        'inference.yml': ('28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685', 903)}),
    'recognizer': ('th_PP-OCRv5_mobile_rec', {
        'inference.json': ('b92a9442af5ac6da3c6ba30ce1672d00a2d7a0fbd8068ed543ac6dcb9d5c7764', 217712),
        'inference.pdiparams': ('45ec91f2322b58b8d30ba27d18fcfdbb8bf388b918dd978162d2af91e0c66d4b', 7814907),
        'inference.yml': ('f6ba7fefc38ca1ff398ddafa75d67d16e0b3757c4e6c833adffee98a981766c9', 4667)})}
SDK_FILES = {
    'models/__init__.py': 'b4b5e5cfd94de3fa5b0edd5999226c202160c926f6b5450fac574371eb470812',
    'models/predictors/base_predictor.py': 'cda03a6aa84705d2ecfb6776cfe4bf28c78d64bfc5b3a5dadbadc5d6f7e495a8',
    'models/predictors/runner_predictor.py': '3b56d3736775038c7a470a1770bff969064cf14c535906c87c066e6ff9a20f37',
    'models/text_detection/predictor.py': '145d99a714a6cfa7a5d95ce823a78b218de2d1a53cdf427e26e9190c2675b0e6',
    'models/text_detection/processors.py': 'b23f2349e9e3439d748548730443459d7ed43a4f5e5beb04903f3e5ad58be7c1',
    'models/text_recognition/predictor.py': '3a85baae080f8778f0a131d15ccd39c9985cca9905752b939867f1efb6bb0c22'}
TESS_WEIGHTS = {'tha': '88032a9f21accff825efaed29604eb8a534e265cf8058a95ea5417a6df91c005',
                'eng': '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'}


def configuration_template(plan_pin, runtime_python_pin, model_directories, sdk_inference_root,
                           tess_reader_path, tess_executable_path, tessdata_dir, derivation_runtime):
    """Pure prospective canary config; caller must pin/freeze and validate real files.

    This performs no network/file IO and cannot publish or start a job. The
    selected native bytes are explicit; model directories are existing caches.
    """
    from copy import deepcopy
    c = {'contract': CONFIG_CONTRACT, 'mode': 'canary_one_ROI',
         'resource_policy': deepcopy(RESOURCES), 'limits': deepcopy(LIMITS),
         'plan': deepcopy(plan_pin), 'runtime_python': deepcopy(runtime_python_pin),
         'derivation_runtime': deepcopy(derivation_runtime),
         'models': {}, 'sdk_sources': {}, 'tesseract': {
             'reader': {'path': str(tess_reader_path), 'sha256': TESS_READER_SHA},
             'executable': {'path': str(tess_executable_path), 'sha256': TESS_EXE_SHA},
             'tessdata_dir': str(tessdata_dir), 'weights': {},
             'tsv_config': {'path': str(Path(tessdata_dir)/'configs'/'tsv'), 'sha256': TESS_TSV_CONFIG_SHA}},
         'production_activation_allowed': False, 'optimizer_updates_allowed': False}
    for role, (name, files) in MODEL_FILES.items():
        root = Path(model_directories[role])
        c['models'][role] = {'model_name': name, 'model_dir': str(root), 'files': {
            member: {'path': str(root/member), 'sha256': digest} for member, (digest, _) in files.items()}}
    c['sdk_sources'] = {name: {'path': str(Path(sdk_inference_root)/name), 'sha256': digest}
                        for name, digest in SDK_FILES.items()}
    c['tesseract']['weights'] = {name: {'path': str(Path(tessdata_dir)/(name+'.traineddata')), 'sha256': digest}
                                for name, digest in TESS_WEIGHTS.items()}
    validate_config(c, '', check_files=False)
    return c


def validate_config(c, request_id, check_files=True):
    required = {'contract', 'mode', 'resource_policy', 'limits', 'plan', 'runtime_python',
                'models', 'sdk_sources', 'tesseract', 'production_activation_allowed',
                'optimizer_updates_allowed', 'derivation_runtime'}
    if (type(c) is not dict or set(c) != required or c['contract'] != CONFIG_CONTRACT or
            c['mode'] != 'canary_one_ROI' or c['resource_policy'] != RESOURCES or c['limits'] != LIMITS or
            c['production_activation_allowed'] is not False or c['optimizer_updates_allowed'] is not False):
        raise ValueError('Exact root ONE-ROI/no-training experimental configuration required')
    if not valid_pin(c['plan']) or not valid_pin(c['runtime_python']):
        raise ValueError('Plan and runtime Python pins required')
    records = [c['plan'], c['runtime_python']]
    derivation = c['derivation_runtime']
    if (type(derivation) is not dict or set(derivation) != {'module', 'recipe'} or
            not all(valid_pin(p) for p in derivation.values()) or
            Path(derivation['module']['path']).name != 'whole_cell_source_derivation.py'):
        raise ValueError('Pinned independent source derivation module and recipe required')
    records.extend(derivation.values())
    if type(c['models']) is not dict or set(c['models']) != set(MODEL_FILES):
        raise ValueError('Exact detector+Thai recognizer model pair required')
    for role, (name, members) in MODEL_FILES.items():
        model = c['models'][role]
        if (type(model) is not dict or set(model) != {'model_name', 'model_dir', 'files'} or
                model['model_name'] != name or not isinstance(model['model_dir'], str) or
                type(model['files']) is not dict or set(model['files']) != set(members)):
            raise ValueError('Selected model member inventory differs')
        for member, (digest, size) in members.items():
            p = model['files'][member]
            if not valid_pin(p) or p['sha256'] != digest or Path(p['path']).name != member:
                raise ValueError('Selected model bytes/source differ: ' + role + '/' + member)
            if Path(p['path']).parent.resolve() != Path(model['model_dir']).resolve():
                raise ValueError('Model member outside its explicit model directory')
            if check_files and Path(p['path']).stat().st_size != size:
                raise ValueError('Model member byte size differs')
            records.append(p)
    if type(c['sdk_sources']) is not dict or set(c['sdk_sources']) != set(SDK_FILES):
        raise ValueError('Exact inspected SDK API source inventory required')
    for name, digest in SDK_FILES.items():
        p = c['sdk_sources'][name]
        if not valid_pin(p) or p['sha256'] != digest:
            raise ValueError('Actual SDK source bytes differ: ' + name)
        records.append(p)
    tess = c['tesseract']
    if (type(tess) is not dict or set(tess) != {'reader', 'executable', 'tessdata_dir', 'weights', 'tsv_config'} or
            not valid_pin(tess['reader']) or tess['reader']['sha256'] != TESS_READER_SHA or
            not valid_pin(tess['executable']) or tess['executable']['sha256'] != TESS_EXE_SHA or
            type(tess['weights']) is not dict or set(tess['weights']) != set(TESS_WEIGHTS)):
        raise ValueError('Original audited Tess reader/executable/languages required')
    if (not valid_pin(tess['tsv_config']) or tess['tsv_config']['sha256'] != TESS_TSV_CONFIG_SHA or
            Path(tess['tsv_config']['path']).resolve() != (Path(tess['tessdata_dir'])/'configs'/'tsv').resolve()):
        raise ValueError('Exact Tesseract TSV configuration dependency required')
    if check_files and Path(tess['tsv_config']['path']).stat().st_size != 22:
        raise ValueError('Tesseract TSV configuration byte size differs')
    records.extend([tess['reader'], tess['executable'], tess['tsv_config']])
    for language, digest in TESS_WEIGHTS.items():
        p = tess['weights'][language]
        if (not valid_pin(p) or p['sha256'] != digest or
                Path(p['path']).resolve() != (Path(tess['tessdata_dir'])/(language+'.traineddata')).resolve()):
            raise ValueError('Exact Tess language weights required')
        records.append(p)
    if check_files:
        for p in records:
            checked(p)
        plan = read(c['plan']['path']); requests = validate_plan(plan)
        matches = [r for r in requests if r['request_id'] == request_id]
        if len(matches) != 1:
            raise ValueError('Canary must select exactly ONE request from frozen ALL-source inventory')
        return matches[0], records
    return None, records


def load_source_artifacts(request):
    """Hash/binding checks only; this does NOT certify semantic crop provenance."""
    validate_request(request)
    for p in [request['source_image'], *request['source_inputs'].values()]:
        checked(p)
    context = read(checked(request['context_proof']))
    binding = {k: v for k, v in request.items() if k != 'context_proof'}
    if (context.get('contract') != 'document-ai-whole-cell-source-context.v1' or
            context.get('request_binding') != binding):
        raise ValueError('Source-only context proof does not bind the exact request')
    if (context.get('derivation') or {}).get('crop_admission', {}).get('eligible') is False:
        raise ValueError('Source-derived crop is explicitly HOLD/ineligible')
    inventory = read(checked(request['source_token_inventory']))
    return context, inventory


def compare_reconstruction(request, context, inventory, actual):
    """Require independently rebuilt original-source geometry before crop closure."""
    if (not isinstance(actual, dict) or
            not {'inventory', 'source_band', 'row_barrier_interval', 'crop_admission'} <= set(actual) or
            actual['inventory'] != inventory or actual['source_band'] != request['source_band'] or
            actual['row_barrier_interval'] != request['row_barrier_interval']):
        raise ValueError('Independently reconstructed actual source inventory/band/barriers differ')
    if (not isinstance(actual['crop_admission'], dict) or
            actual['crop_admission'].get('eligible') is not True or
            (context.get('derivation') or {}).get('crop_admission', {}).get('eligible') is False):
        raise ValueError('Independently reconstructed source crop is HOLD/ineligible')
    crop = whole_word_crop(request, inventory)
    crop['independently_reconstructed_source_context'] = True
    return crop


def load_source_request(request, derivation_runtime):
    if (type(derivation_runtime) is not dict or set(derivation_runtime) != {'module', 'recipe'} or
            not all(valid_pin(p) for p in derivation_runtime.values())):
        raise ValueError('Frozen independent source derivation is required before crop admission')
    context, inventory = load_source_artifacts(request)
    if (context.get('derivation') or {}).get('recipe') != derivation_runtime['recipe']:
        raise ValueError('Source context does not bind the selected frozen derivation recipe')
    path = checked(derivation_runtime['module']); checked(derivation_runtime['recipe'])
    spec = importlib.util.spec_from_file_location('_whole_cell_source_derivation', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    actual = module.reconstruct(request, context, checked)
    return compare_reconstruction(request, context, inventory, actual)


def plain(value):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, 'tolist'):
        return plain(value.tolist())
    raise TypeError('Unsupported actual native output type: ' + type(value).__name__)


def native_payload(result):
    # Avoid TextDetResult.json's whole input-image deepcopy. Preserve every
    # non-image native key/value; image bytes already have their own immutable pin.
    if not isinstance(result, dict):
        raise ValueError('Actual Paddle result must be dictionary-like')
    return plain({k: v for k, v in result.items() if k not in ('input_img', 'vis_font')})


def hard_deadline(name, progress):
    try:
        progress(name+'_DEADLINE')
    finally:
        os._exit(124)  # no optimizer; 620 supervisor closes all owned children


def phase_timer(seconds, name, progress):
    def stop():
        hard_deadline(name, progress)
    timer = threading.Timer(seconds, stop); timer.daemon = True; timer.start()
    return timer


def model_settings(model):
    actual = model.runner._config
    values = {'cpu_threads': 1, 'run_mode': 'paddle', 'device_type': 'cpu'}
    if any(actual.get(k) != v for k, v in values.items()):
        raise ValueError('Actual CPU1 paddle_static runner binding differs')
    return {k: actual[k] for k in values}


def bind_sdk_root(c, actual_inference_root):
    root = Path(actual_inference_root).resolve()
    for name, record in c['sdk_sources'].items():
        if Path(record['path']).resolve() != (root/name).resolve():
            raise ValueError('Inspected SDK pins do not bind actual imported SDK paths: '+name)
    return {'actual_inference_root': str(root), 'selected_source_paths_bound_to_actual_imports': True}


def package_versions():
    observed = {}
    for name in ('paddlepaddle', 'paddlex', 'paddleocr', 'pillow', 'numpy',
                 'opencv-python', 'opencv-contrib-python', 'psutil'):
        try:
            observed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            observed[name] = None
    for name, expected in {'paddlepaddle': '3.2.2', 'paddlex': '3.7.2', 'paddleocr': '3.7.0',
                           'pillow': '12.3.0', 'numpy': '1.26.4', 'psutil': '7.2.2'}.items():
        if observed[name] != expected:
            raise ValueError('Selected original runtime package differs: '+name)
    return observed


def load_tess_reader(record):
    checked(record)
    spec = importlib.util.spec_from_file_location('whole_cell_pinned_tess_reader', record['path'])
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for name in ('command_for', 'parse_tsv', 'run_owned_child'):
        if not callable(getattr(module, name, None)):
            raise ValueError('Pinned original Tess helper unavailable: ' + name)
    return module


def execute(args, c, request, crop):
    lease = verify_admission(args.admission, args.admission_sha256, __file__, COMPONENT)
    if pin(sys.executable) != c['runtime_python']:
        raise ValueError('Actual Python executable differs from pinned original runtime')
    output = args.output.resolve()
    if output.drive.upper() != 'D:' or 'OCR-Experiments' not in output.parts or output.exists():
        raise ValueError('New isolated HQ D:/OCR-Experiments output only')
    output.mkdir(parents=True, exist_ok=False)
    begun = time.monotonic(); model = None; total_timer = None
    calls = {'Paddle_detector': 0, 'Paddle_Thai_recognizer': 0, 'Tesseract_ROI': 0}
    started_calls = dict(calls); observations = []; resources = []; failure = None
    source_decodes_started = 0; source_decodes_completed = 0; actual_detection_count = None
    packages = None
    status = 'FAILED'; phase_log = (output/'PHASES.jsonl').open('x', encoding='utf-8')

    def progress(phase):
        item = {'phase': phase, 'elapsed_seconds': round(time.monotonic()-begun, 6),
                'timestamp_epoch': time.time()}
        phase_log.write(json.dumps(item, allow_nan=False)+'\n'); phase_log.flush()
        print(json.dumps(item, allow_nan=False), flush=True)

    def fresh_start():
        import psutil
        if psutil.virtual_memory().available < RESOURCES['minimum_start_free_RAM_bytes']:
            raise RuntimeError('Fresh native start RAM gate')

    try:
        packages = package_versions()
        save(output/'STARTED.json', {'contract': SUMMARY_CONTRACT, 'status': 'RUNNING',
             'component': COMPONENT, 'request_id': request['request_id'], 'config': pin(args.config),
             'worker': pin(__file__), 'protocol': pin(Path(__file__).with_name('whole_cell_source.py')),
             'derivation_runtime': c['derivation_runtime'],
             'admission': pin(args.admission), 'resource_policy': RESOURCES, 'limits': LIMITS, 'packages': packages,
             'new_calls_started': started_calls, 'optimizer_updates': 0,
             'expected_labels_passed_to_models': False, 'source_bbox_kind': 'actual_detection_not_characters'})
        total_timer = phase_timer(LIMITS['maximum_worker_seconds'], 'WORKER', progress)
        progress('SOURCE_DECODE_STARTED')
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = LIMITS['maximum_source_page_pixels']
        source_decodes_started += 1
        with Image.open(request['source_image']['path']) as source:
            if list(source.size) != request['geometry']['original_size']:
                raise ValueError('Actual source image dimensions differ')
            image = source.convert('RGB')
        source_decodes_completed += 1
        angle = request['geometry']['orientation_ccw']
        if angle:
            rotated = image.transpose({90: Image.Transpose.ROTATE_90,
                                       180: Image.Transpose.ROTATE_180,
                                       270: Image.Transpose.ROTATE_270}[angle])
            image.close(); image = rotated
        if list(image.size) != request['geometry']['upright_size']:
            raise ValueError('Actual saved orientation frame differs')
        roi = image.crop(tuple(crop['crop_bbox_upright'])); image.close()
        crop_path = output/'whole_ROI.png'; roi.save(crop_path, format='PNG')
        save(output/'CROP_PROOF.json', {'request': request, 'crop': crop, 'physical_crop': pin(crop_path),
             'source_image_decodes': 1, 'EXIF_reinterpretation': False,
             'pixel_resampling': False, 'assistant_image_reads': 0})
        os.environ.update({k: '1' for k in ('OMP_THREAD_LIMIT', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
            'OPENBLAS_NUM_THREADS', 'CPU_NUM', 'FLAGS_paddle_num_threads', 'PADDLE_PDX_CPU_NUM_THREADS')})
        os.environ.update(PADDLE_PDX_EAGER_INIT='0', PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True',
                          NO_ALBUMENTATIONS_UPDATE='1')
        fresh_start(); timer = phase_timer(LIMITS['SDK_startup_seconds'], 'DETECTOR_STARTUP', progress)
        try:
            progress('PADDLE_IMPORT_STARTED')
            import cv2
            cv2.setNumThreads(1)
            from paddlex.inference.models import create_predictor
            from paddlex.utils.flags import EAGER_INITIALIZATION
            sdk_root_proof = bind_sdk_root(c, Path(sys.modules['paddlex.inference.models'].__file__).parent.parent)
            if EAGER_INITIALIZATION is not False:
                raise ValueError('Inference-only official eager-init switch not bound')
            progress('DETECTOR_CONSTRUCTION_STARTED')
            model = create_predictor(model_name=c['models']['detector']['model_name'],
                model_dir=c['models']['detector']['model_dir'], device='cpu', engine='paddle_static',
                engine_config={'cpu_threads': 1, 'run_mode': 'paddle'}, **detector_options())
            detector_proof = assert_detector_settings(model)
            detector_proof['SDK_source_path_proof'] = sdk_root_proof
        finally:
            timer.cancel()
        save(output/'DETECTOR_RUNTIME_PROOF.json', detector_proof)
        timer = phase_timer(LIMITS['detector_predict_seconds'], 'DETECTOR_PREDICT', progress)
        try:
            progress('DETECTOR_PREDICT_STARTED'); started_calls['Paddle_detector'] += 1
            outputs = list(model(input=str(crop_path), batch_size=1, **detector_options()))
            calls['Paddle_detector'] += 1
            if len(outputs) != 1:
                raise ValueError('One ROI must yield one actual detector result')
            raw = native_payload(outputs[0])
            save(output/'PADDLE_DETECTOR_RAW.json', raw)
            actual_detection_count = len(raw['dt_polys'])
            detections = native_detections(raw['dt_polys'], raw['dt_scores'], crop, request['geometry'])
        finally:
            timer.cancel()
        model.close(); model = None; del outputs; gc.collect()
        progress('DETECTOR_CLOSED')
        if detections:
            fresh_start(); timer = phase_timer(LIMITS['SDK_startup_seconds'], 'RECOGNIZER_STARTUP', progress)
            try:
                progress('RECOGNIZER_CONSTRUCTION_STARTED')
                model = create_predictor(model_name=c['models']['recognizer']['model_name'],
                    model_dir=c['models']['recognizer']['model_dir'], device='cpu', engine='paddle_static',
                    engine_config={'cpu_threads': 1, 'run_mode': 'paddle'})
                save(output/'RECOGNIZER_RUNTIME_PROOF.json', {'runner': model_settings(model),
                     'return_word_box': False, 'recognizer_alone_provides_measured_boxes': False})
            finally:
                timer.cancel()
            for detection in detections:
                index = detection['detection_index']; local = recognition_crop(detection)
                path = output/('detected_region_%03d.png' % index)
                rec_image = roi.crop(tuple(local)); rec_image.save(path, format='PNG'); rec_image.close()
                timer = phase_timer(LIMITS['recognizer_predict_seconds'], 'RECOGNIZER_PREDICT', progress)
                try:
                    progress('RECOGNIZER_PREDICT_%03d_STARTED' % index)
                    started_calls['Paddle_Thai_recognizer'] += 1
                    outputs = list(model(input=str(path), batch_size=1, return_word_box=False))
                    calls['Paddle_Thai_recognizer'] += 1
                    if len(outputs) != 1:
                        raise ValueError('One detected text region must yield one recognizer result')
                    raw = native_payload(outputs[0])
                    save(output/('PADDLE_REC_RAW_%03d.json' % index), raw)
                    if (not isinstance(raw.get('rec_text'), str) or type(raw.get('rec_score')) not in (int, float)
                            or not math.isfinite(raw['rec_score']) or not 0 <= raw['rec_score'] <= 1):
                        raise ValueError('Actual recognizer text/score required, no fallback')
                    observations.append({**detection, 'raw_text': raw['rec_text'], 'confidence': raw['rec_score'],
                        'engine_family': 'PADDLE', 'engine': 'NEW_WHOLE_CELL_PADDLE_SERVER_DET_THAI_REC',
                        'token_id': request['request_id']+':paddle:%03d' % index,
                        'recognition_image': pin(path), 'character_boxes_available': False,
                        'same_family_as_cached_Paddle': True})
                finally:
                    timer.cancel()
            model.close(); model = None; del outputs; gc.collect()
        roi.close(); progress('RECOGNIZER_CLOSED')
        save(output/'PADDLE_OBSERVATIONS.json', {'request_id': request['request_id'],
             'source_image': request['source_image'], 'geometry': request['geometry'],
             'crop': crop, 'observations': observations, 'logical_field_values_assigned': False})
        fresh_start(); tess = load_tess_reader(c['tesseract']['reader'])
        command = tess.command_for(c['tesseract']['executable']['path'], crop_path,
                                   c['tesseract']['tessdata_dir'])
        child_lease = {**RESOURCES, 'maximum_wall_seconds': LIMITS['maximum_worker_seconds'],
            'per_crop_timeout_seconds': LIMITS['tesseract_seconds'],
            'stop_file': str(output.parent/'STOP_REQUEST.json')}
        progress('TESSERACT_STARTED'); started_calls['Tesseract_ROI'] += 1
        with (output/'TESSERACT_RAW.tsv').open('xb') as stdout, (output/'TESSERACT.stderr.log').open('xb') as stderr:
            resource = tess.run_owned_child(command, stdout, stderr, dict(os.environ), child_lease, begun,
                lambda identity: save(output/'TESSERACT_CHILD_STARTED.json', identity))
            stdout.flush(); os.fsync(stdout.fileno()); stderr.flush(); os.fsync(stderr.fileno())
        resources.append(resource); save(output/'TESSERACT_RESOURCE.json', resource)
        if resource['exit_code'] != 0 or resource['stop'] is not None or resource['model_child_exited'] is not True:
            raise RuntimeError('Actual owned Tesseract child failed/stopped')
        calls['Tesseract_ROI'] += 1
        tsv = (output/'TESSERACT_RAW.tsv').read_text(encoding='utf-8-sig', errors='strict')
        tess_tokens = tess.parse_tsv(tsv, crop['crop_bbox_upright'], request['request_id']+':tesseract',
                                     crop['physical_crop_size'])
        for token in tess_tokens:
            token.update(engine_family='TESSERACT', engine='NEW_WHOLE_CELL_TESSERACT_FAST_THA_ENG',
                         same_family_as_cached_Tesseract=True)
        save(output/'OBSERVATIONS.json', {'contract': SUMMARY_CONTRACT, 'request_id': request['request_id'],
            'page_number': request['page_number'], 'row_index': request['row_index'], 'field': request['field'],
            'source_image': request['source_image'], 'geometry': request['geometry'], 'crop': crop,
            'Paddle_observations': observations, 'Tesseract_observations': tess_tokens,
            'literal_source_only': True, 'logical_field_values_assigned': False,
            'baseline_cache_modified': False, 'extra_independent_engine_families': 0})
        status = 'COMPLETE'; progress('COMPLETED')
    except Exception as exc:
        failure = type(exc).__name__+': '+str(exc); progress('FAILED')
    finally:
        if model is not None:
            try:
                model.close()
            except Exception as exc:
                failure = (failure or '')+'; MODEL_CLOSE:'+type(exc).__name__
                status = 'FAILED'
        if total_timer is not None:
            total_timer.cancel()
        phase_log.flush(); os.fsync(phase_log.fileno()); phase_log.close()
        save(output/'SUMMARY.json', {'contract': SUMMARY_CONTRACT, 'component': COMPONENT, 'status': status,
            'executed': True, 'mode': c['mode'], 'request_id': request['request_id'],
            'requests_completed': int(status == 'COMPLETE'), 'requests_selected': 1,
            'config': pin(args.config), 'worker': pin(__file__), 'plan': c['plan'],
            'models': c['models'], 'sdk_sources': c['sdk_sources'], 'tesseract': c['tesseract'], 'packages': packages,
            'derivation_runtime': c['derivation_runtime'],
            'resource_policy': RESOURCES, 'limits': LIMITS, 'new_calls_started': started_calls,
            'new_calls_completed': calls, 'actual_detector_regions': actual_detection_count,
            'Paddle_recognized_observations': len(observations),
            'positive_detector_recognizer_path': bool(actual_detection_count and
                 calls['Paddle_Thai_recognizer'] == actual_detection_count and
                 len(observations) == actual_detection_count),
            'source_image_decodes_started': source_decodes_started,
            'source_image_decodes_completed': source_decodes_completed,
            'assistant_image_reads': 0, 'optimizer_updates': 0,
            'canonical_values_modified': False, 'baseline_cache_modified': False,
            'endpoint_accuracy_measured': False, 'endpoint_gain': None,
            'outer_07b_620_supervisor_is_authoritative_whole_tree_resource_and_closure_proof': True,
            'tesseract_child_resources': resources, 'elapsed_seconds': time.monotonic()-begun,
            'failure': failure, 'production_activation': False})
    if failure:
        raise RuntimeError(failure)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--config-sha256', required=True)
    p.add_argument('--request-id', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--admission-sha256')
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    if sha(args.config) != args.config_sha256:
        raise ValueError('Exact canary config SHA required')
    c = read(args.config); request, _ = validate_config(c, args.request_id)
    crop = load_source_request(request, c['derivation_runtime'])
    if args.execute:
        if not args.admission or not args.admission_sha256:
            raise ValueError('Root live supervisor admission required')
        execute(args, c, request, crop)
    else:
        print(json.dumps({'contract': SUMMARY_CONTRACT, 'status': 'VALIDATED_NOT_EXECUTED',
            'request_id': request['request_id'], 'crop': crop, 'new_model_calls': 0,
            'new_OCR_calls': 0, 'source_image_decodes': 0, 'optimizer_updates': 0}, allow_nan=False))


if __name__ == '__main__':
    main()
