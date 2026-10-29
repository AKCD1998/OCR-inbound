"""Synthetic source protocol tests: no images, native libraries or model loads."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import whole_cell_source as protocol
import whole_cell_source_worker as worker


def invented_pin(path='invented_source.json', digest='a'*64):
    return {'path': path, 'sha256': digest}


def request():
    return {'request_id': 'invented_source_row_1', 'page_number': 1, 'row_index': 0, 'field': 'unit',
            'source_image': invented_pin('invented_image.jpg'),
            'geometry': {'original_size': [1000, 800], 'upright_size': [1000, 800], 'orientation_ccw': 0},
            'source_band': [100, 200, 140, 220], 'row_barrier_interval': [190, 230],
            'source_token_inventory': invented_pin('invented_tokens.json'),
            'context_proof': invented_pin('invented_context.json'),
            'source_inputs': {k: invented_pin('invented_'+k+'.json') for k in ('cache', 'canonical', 'native')}}


def inventory(r, tokens=None):
    return {'contract': protocol.TOKEN_CONTRACT, 'page_number': r['page_number'],
            'source_sha256': r['source_image']['sha256'], 'geometry': deepcopy(r['geometry']),
            'tokens': tokens or [{'token_id': 'paddle:actual0', 'engine': 'PADDLE', 'bbox': [100, 200, 140, 220]}]}


def config():
    models = {}
    for role, (name, members) in worker.MODEL_FILES.items():
        root = str(Path('invented_models')/role)
        models[role] = {'model_name': name, 'model_dir': root,
                        'files': {n: invented_pin(str(Path(root)/n), digest) for n, (digest, _) in members.items()}}
    data = 'invented_tessdata'
    return {'contract': worker.CONFIG_CONTRACT, 'mode': 'canary_one_ROI',
            'resource_policy': deepcopy(worker.RESOURCES), 'limits': deepcopy(protocol.LIMITS),
            'plan': invented_pin('invented_plan.json'), 'runtime_python': invented_pin('invented_python'),
            'derivation_runtime': {'module': invented_pin('whole_cell_source_derivation.py'),
                                   'recipe': invented_pin('invented_source_recipe.json')},
            'models': models, 'sdk_sources': {n: invented_pin('invented_sdk/'+n, h) for n, h in worker.SDK_FILES.items()},
            'tesseract': {'reader': invented_pin('invented_reader.py', worker.TESS_READER_SHA),
                          'executable': invented_pin('invented_tesseract', worker.TESS_EXE_SHA), 'tessdata_dir': data,
                          'tsv_config': invented_pin(str(Path(data)/'configs'/'tsv'), worker.TESS_TSV_CONFIG_SHA),
                          'weights': {n: invented_pin(str(Path(data)/(n+'.traineddata')), h)
                                      for n, h in worker.TESS_WEIGHTS.items()}},
            'production_activation_allowed': False, 'optimizer_updates_allowed': False}


class WholeCellSourceTests(unittest.TestCase):
    def test_fixed_point_keeps_whole_words_from_all_readers_without_mutating_inputs(self):
        r = request(); inv = inventory(r, [
            {'token_id': 'paddle:0', 'engine': 'PADDLE', 'bbox': [140, 200, 200, 220]},
            {'token_id': 'tesseract:1', 'engine': 'TESSERACT', 'bbox': [190, 200, 250, 220]},
            {'token_id': 'paddle:touch', 'engine': 'PADDLE', 'bbox': [250, 200, 270, 220]}])
        before = deepcopy((r, inv)); out = protocol.whole_word_crop(r, inv)
        self.assertEqual(before, (r, inv)); self.assertEqual([92, 196, 250, 224], out['crop_bbox_upright'])
        self.assertEqual(['paddle:0', 'tesseract:1'], out['whole_cached_token_ids'])
        self.assertEqual([1, 0, 92, 0, 1, 196], out['crop_to_upright_affine'])
        self.assertFalse(out['source_band_clipped']); self.assertTrue(out['whole_word_closure_complete'])

    def test_intersecting_word_across_unknown_or_bonus_row_is_refused_not_clipped(self):
        r = request(); inv = inventory(r, [
            {'token_id': 'tesseract:whole', 'engine': 'TESSERACT', 'bbox': [120, 180, 200, 220]}])
        with self.assertRaisesRegex(ValueError, 'row barrier'):
            protocol.whole_word_crop(r, inv)

    def test_padding_can_stop_at_barrier_but_source_band_cannot_be_cut(self):
        r = request(); r['row_barrier_interval'] = [200, 220]
        out = protocol.whole_word_crop(r, inventory(r))
        self.assertEqual([92, 200, 148, 220], out['crop_bbox_upright'])
        r['source_band'][1] = 199
        with self.assertRaises(ValueError):
            protocol.whole_word_crop(r, inventory(r))

    def test_whole_word_budget_excess_does_not_drop_foreign_tokens(self):
        r = request(); r['geometry']['original_size'] = r['geometry']['upright_size'] = [4000, 800]
        inv = inventory(r, [{'token_id': 'paddle:long', 'engine': 'PADDLE', 'bbox': [100, 200, 3000, 220]}])
        with self.assertRaisesRegex(ValueError, 'pixel budget'):
            protocol.whole_word_crop(r, inv)

    def test_source_identity_duplicate_or_manual_inventory_is_refused(self):
        r = request(); inv = inventory(r)
        for mutate in (lambda x: x.update(source_sha256='b'*64),
                       lambda x: x['tokens'].append(deepcopy(x['tokens'][0])),
                       lambda x: x['tokens'][0].update(engine='ASSISTANT_CORRECTED'),
                       lambda x: x['tokens'][0].update(raw_text='must not reach geometric inventory')):
            sample = deepcopy(inv); mutate(sample)
            with self.assertRaises(ValueError):
                protocol.whole_word_crop(r, sample)

    def test_request_does_not_accept_expected_labels_or_business_fields(self):
        for key in ('expected_value', 'candidate', 'SKU', 'gold', 'business_unit'):
            r = request(); r[key] = 'INVENTED_ANSWER'
            with self.subTest(key=key), self.assertRaises(ValueError):
                protocol.validate_request(r)

    def test_frozen_all_source_plan_and_unique_safe_ids_are_required(self):
        r = request(); plan = {'contract': protocol.PLAN_CONTRACT, 'machine_only': True, 'requests': [r]}
        self.assertEqual([r], protocol.validate_plan(plan))
        plan['requests'].append(deepcopy(r))
        with self.assertRaises(ValueError):
            protocol.validate_plan(plan)
        r['request_id'] = '../../elsewhere'
        with self.assertRaises(ValueError):
            protocol.validate_request(r)

    def test_actual_detector_polygon_maps_crop_upright_and_original_without_fake_glyph_boxes(self):
        geometry = {'original_size': [1000, 800], 'upright_size': [800, 1000], 'orientation_ccw': 90}
        crop = {'crop_bbox_upright': [100, 200, 300, 260], 'physical_crop_size': [200, 60]}
        out = protocol.native_detections([[[10, 5], [50, 5], [50, 20], [10, 20]]], [.89], crop, geometry)[0]
        self.assertEqual([[110, 205], [150, 205], [150, 220], [110, 220]], out['polygon_upright'])
        self.assertEqual([[795, 110], [795, 150], [780, 150], [780, 110]], out['polygon_original'])
        self.assertEqual([10, 5, 50, 20], protocol.recognition_crop(out))
        self.assertIn('not_character', out['source_bbox_kind'])

    def test_native_invalid_or_excess_detections_are_refused_not_clipped_or_truncated(self):
        r = request(); crop = protocol.whole_word_crop(r, inventory(r)); geometry = r['geometry']
        good = [[1, 1], [20, 1], [20, 10], [1, 10]]
        for polys, scores in (([good]*17, [.9]*17), ([good], [float('nan')]),
                              ([[[-1, 1], [20, 1], [20, 10], [1, 10]]], [.9]),
                              ([[[1, 1], [20, 10], [20, 1], [1, 10]]], [.9])):
            with self.subTest(polys=polys), self.assertRaises(ValueError):
                protocol.native_detections(polys, scores, crop, geometry)

    def test_recognizer_extreme_aspect_is_not_silently_resized_or_truncated(self):
        with self.assertRaisesRegex(ValueError, 'aspect'):
            protocol.recognition_crop({'recognition_crop_bbox': [0, 0, 650, 10]})

    def test_actual_max_side_configuration_not_unrelated_internal_processor_default(self):
        model = SimpleNamespace(runner=SimpleNamespace(_config={'cpu_threads': 1, 'run_mode': 'paddle', 'device_type': 'cpu'}),
            max_side_limit=640, pre_tfs={'Resize': SimpleNamespace(resize_type=0, limit_type='max',
                                                                   limit_side_len=640, max_side_limit=4000)})
        out = protocol.assert_detector_settings(model)
        self.assertEqual(protocol.detector_options(), out['predict_call_overrides'])
        self.assertFalse(out['min_side_upscaling_to640'])
        model.pre_tfs['Resize'].limit_type = 'min'
        with self.assertRaises(ValueError):
            protocol.assert_detector_settings(model)

    def test_cpu_engine_and_model_resources_cannot_be_relaxed_through_configuration(self):
        c = config(); worker.validate_config(c, 'invented', check_files=False)
        for mutate in (lambda x: x['resource_policy'].update(maximum_own_process_tree_RSS_bytes=2**31),
                       lambda x: x['limits'].update(detector_predict_seconds=999),
                       lambda x: x.update(mode='all_ROIs'),
                       lambda x: x.update(optimizer_updates_allowed=True),
                       lambda x: x['models']['recognizer']['files']['inference.pdiparams'].update(sha256='b'*64)):
            sample = deepcopy(c); mutate(sample)
            with self.assertRaises(ValueError):
                worker.validate_config(sample, 'invented', check_files=False)

    def test_raw_native_payload_never_serializes_or_copies_pixels_fonts_or_invents_boxes(self):
        class ExplodingPixels:
            def tolist(self):
                raise AssertionError('Image/visualization font must not be touched')
        raw = worker.native_payload({'input_img': ExplodingPixels(), 'vis_font': ExplodingPixels(),
                                     'rec_text': 'INVENTED_LITERAL', 'rec_score': .42})
        self.assertEqual({'rec_text': 'INVENTED_LITERAL', 'rec_score': .42}, raw)
        self.assertNotIn('bbox', raw)

    def test_configuration_factory_is_source_only_and_has_no_publish_or_execution_side_effect(self):
        plan = invented_pin('invented_all60_plan.json'); runtime = invented_pin('invented_python')
        before = deepcopy((plan, runtime))
        out = worker.configuration_template(plan, runtime,
            {'detector': 'invented_models/detector', 'recognizer': 'invented_models/recognizer'},
            'invented_sdk/inference', 'invented_reader.py', 'invented_tesseract', 'invented_tessdata',
            config()['derivation_runtime'])
        self.assertEqual(before, (plan, runtime)); self.assertEqual('canary_one_ROI', out['mode'])
        self.assertEqual(protocol.LIMITS, out['limits'])
        self.assertEqual('183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d',
                         out['models']['detector']['files']['inference.pdiparams']['sha256'])
        self.assertFalse(out['optimizer_updates_allowed']); self.assertFalse(out['production_activation_allowed'])

    def test_inspected_source_copy_cannot_substitute_for_another_actual_SDK_import_path(self):
        c = config(); out = worker.bind_sdk_root(c, 'invented_sdk')
        self.assertTrue(out['selected_source_paths_bound_to_actual_imports'])
        with self.assertRaisesRegex(ValueError, 'actual imported SDK'):
            worker.bind_sdk_root(c, 'another_sdk')

    def test_source_request_cryptographically_binds_context_and_all_original_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); r = request()
            source = root/'invented_image'; source.write_bytes(b'NOT AN IMAGE: model-free test')
            r['source_image'] = worker.pin(source)
            for name in r['source_inputs']:
                p = root/(name+'.json'); p.write_text('{}', encoding='utf-8')
                r['source_inputs'][name] = worker.pin(p)
            p = root/'tokens.json'; p.write_text(json.dumps(inventory(r)), encoding='utf-8')
            r['source_token_inventory'] = worker.pin(p)
            context = {'contract': 'document-ai-whole-cell-source-context.v1',
                       'request_binding': {k: v for k, v in r.items() if k != 'context_proof'},
                       'derivation': {'invented_source_only': True}}
            p = root/'context.json'; p.write_text(json.dumps(context), encoding='utf-8')
            r['context_proof'] = worker.pin(p)
            source_context, source_inventory = worker.load_source_artifacts(r)
            self.assertEqual(context, source_context)
            self.assertEqual(inventory(r), source_inventory)
            # Hash-consistent {} cache/canonical/native files are NOT semantic proof.
            with self.assertRaisesRegex(ValueError, 'independent source derivation'):
                worker.load_source_request(r, None)
            # Altering a request while retaining its old context cannot select a different crop.
            changed = deepcopy(r); changed['source_band'][2] += 1
            with self.assertRaisesRegex(ValueError, 'exact request'):
                worker.load_source_artifacts(changed)
            held = deepcopy(context); held['derivation']['crop_admission'] = {'eligible': False}
            p.write_text(json.dumps(held), encoding='utf-8'); held_request = deepcopy(r)
            held_request['context_proof'] = worker.pin(p)
            with self.assertRaisesRegex(ValueError, 'HOLD'):
                worker.load_source_artifacts(held_request)
            p.write_text(json.dumps(context), encoding='utf-8')
            # None of the preserved cache/canonical/native artifacts may change under the request.
            Path(r['source_inputs']['canonical']['path']).write_text('{"tampered":true}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Input bytes differ'):
                worker.load_source_artifacts(r)

    def test_phase_hard_deadline_exits_even_if_progress_storage_fails(self):
        def broken_progress(_):
            raise OSError('invented storage failure')
        with patch.object(worker.os, '_exit') as exit_call:
            with self.assertRaises(OSError):
                worker.hard_deadline('INVENTED_PHASE', broken_progress)
            exit_call.assert_called_once_with(124)

    def test_TSV_dependency_is_bound_to_exact_selected_data_directory(self):
        c = config(); worker.validate_config(c, '', check_files=False)
        for mutate in (lambda x: x['tesseract'].pop('tsv_config'),
                       lambda x: x['tesseract']['tsv_config'].update(sha256='0'*64),
                       lambda x: x['tesseract']['tsv_config'].update(path='another/configs/tsv')):
            sample = deepcopy(c); mutate(sample)
            with self.assertRaises(ValueError):
                worker.validate_config(sample, '', check_files=False)

    def test_omitted_source_word_or_invented_barrier_is_rejected_against_reconstruction(self):
        r = request(); declared = inventory(r); context = {'derivation': {'crop_admission': {'eligible': True}}}
        actual = {'inventory': deepcopy(declared), 'source_band': deepcopy(r['source_band']),
                  'row_barrier_interval': deepcopy(r['row_barrier_interval']), 'crop_admission': {'eligible': True}}
        self.assertTrue(worker.compare_reconstruction(r, context, declared, actual)
                        ['independently_reconstructed_source_context'])
        # Synthetic independent source reconstruction contains a crossing cached word
        # omitted by the claimed token list; self-consistency cannot hide it.
        omitted = deepcopy(actual); omitted['inventory']['tokens'].append(
            {'token_id': 'tesseract:crossing', 'engine': 'TESSERACT', 'bbox': [120, 180, 200, 220]})
        with self.assertRaisesRegex(ValueError, 'reconstructed actual source'):
            worker.compare_reconstruction(r, context, declared, omitted)
        wrong_barrier = deepcopy(actual); wrong_barrier['row_barrier_interval'] = [200, 220]
        with self.assertRaisesRegex(ValueError, 'reconstructed actual source'):
            worker.compare_reconstruction(r, context, declared, wrong_barrier)
        failed = deepcopy(actual); failed['crop_admission']['eligible'] = False
        with self.assertRaisesRegex(ValueError, 'HOLD'):
            worker.compare_reconstruction(r, context, declared, failed)

    def test_fractional_logical_band_rounding_is_safe_inside_actual_independent_barriers(self):
        r = request(); r['source_band'] = [100.2, 200.2, 140.8, 220.8]
        r['row_barrier_interval'] = [190, 230]
        inv = inventory(r, [{'token_id': 'paddle:whole', 'engine': 'PADDLE', 'bbox': [100, 200, 141, 221]}])
        out = protocol.whole_word_crop(r, inv)
        self.assertEqual([92, 196, 149, 225], out['crop_bbox_upright'])
        self.assertFalse(out['source_band_clipped'])


if __name__ == '__main__':
    unittest.main()
