"""Synthetic source-authority tests. No private OCR, image or SDK imports."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'experiments/document_ai/whole_cell_source_derivation.py'
SPEC = importlib.util.spec_from_file_location('tested_whole_cell_derivation', PATH)
d = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(d)


class DerivationTests(unittest.TestCase):
    def evidence(self):
        return {'row_index': 0, 'anchor_bbox': [20, 50, 60, 60],
                'source_header_band': [70, 40.25, 95, 70.75],
                'whole_source_headers': {'unit': [{'bbox': [70, 5, 90, 20]}]},
                'region': {'bbox': [0, 0, 100, 100]},
                'negative_row_barriers': [{'row_index': 1, 'kind': 'UNRESOLVED_CANONICAL_ROW_LOCATION',
                                          'bbox': [20, 80, 60, 90]}]}

    def test_physical_edges_not_fractional_logical_midpoint(self):
        interval, proof = d.row_interval(self.evidence())
        self.assertEqual([20, 80], interval)
        self.assertTrue(proof['source_band_fits_strict_interval'])
        self.assertFalse(proof['logical_midpoints_used_as_physical_edges'])
        self.assertLessEqual(interval[0], 40)
        self.assertGreaterEqual(interval[1], 71)

    def test_crossing_whole_foreign_barrier_is_explicit_hold(self):
        evidence = self.evidence(); evidence['source_header_band'][3] = 81
        interval, proof = d.row_interval(evidence)
        self.assertFalse(proof['source_band_fits_strict_interval'])
        self.assertEqual([40.25, 81], interval)
        evidence['negative_row_barriers'][0]['bbox'] = [20, 55, 60, 70]
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            d.row_interval(evidence)

    def test_inventory_includes_low_confidence_unknowns_all_families(self):
        word = {'box': [1, 1, 20, 5], 'text': 'MUST NOT COPY', 'confidence': 0.01,
                'engine': 'PADDLE', 'token_id': 'same'}
        cache = {'page_number': 1, 'source_sha256': 'a' * 64, 'working_tokens': [word],
                 'tesseract_working_tokens': [{**word, 'engine': 'TESS'}],
                 'targeted_views': [{'tokens': [word]}]}
        geometry = {'original_size': [100, 100], 'upright_size': [100, 100], 'orientation_ccw': 0}
        inventory, invalid = d.inventory(cache, geometry)
        self.assertFalse(invalid); self.assertEqual(3, len(inventory['tokens']))
        self.assertEqual(3, len({x['token_id'] for x in inventory['tokens']}))
        self.assertNotIn('MUST NOT COPY', json.dumps(inventory))
        cache['targeted_views'][0]['tokens'] = [{**word, 'box': [-1, 1, 20, 5]}]
        self.assertEqual([['targeted_views/0/tokens', 0]], d.inventory(cache, geometry)[1])

    def test_source_binding_and_explicit_hold_recomputed(self):
        actual = {'source_band': self.evidence()['source_header_band'], 'evidence': self.evidence()}
        geometry = {'original_size': [100, 100], 'upright_size': [100, 100], 'orientation_ccw': 0}
        cache = {'page_number': 1, 'source_sha256': 'a' * 64, 'working_tokens': []}
        request = {'source_band': actual['source_band'], 'row_barrier_interval': [20, 80]}
        context = {'contract': 'document-ai-whole-cell-source-context.v1', 'request_binding': deepcopy(request),
                   'derivation': {'recipe': {'path': 'recipe'}, 'crop_admission': {'eligible': False}}}
        with patch.object(d, '_read', return_value={}), patch.object(d, 'source_context', return_value=(cache, actual, geometry)):
            result = d.reconstruct(request, context, lambda record: 'recipe')
            self.assertFalse(result['crop_admission']['eligible'])
            context['derivation']['crop_admission']['eligible'] = True
            self.assertTrue(d.reconstruct(request, context, lambda record: 'recipe')['crop_admission']['eligible'])
            request['source_band'] = [70, 40, 95, 71]; context['request_binding'] = deepcopy(request)
            with self.assertRaisesRegex(ValueError, 'actual source reconstruction'):
                d.reconstruct(request, context, lambda record: 'recipe')

    def _fixture(self, folder):
        def save(name, value):
            path = folder / name; path.write_text(json.dumps(value), encoding='utf8')
            return {'path': str(path), 'sha256': __import__('hashlib').sha256(path.read_bytes()).hexdigest()}
        geometry = {'original_size': [100, 100], 'upright_size': [100, 100], 'orientation_ccw': 0}
        image = {'path': 'never-open-this-image.png', 'sha256': 'a' * 64}
        canonical = {'page_number': 1, 'source_sha256': 'a' * 64, 'product_rows': []}
        canonical_pin = save('canonical.json', canonical)
        cache_pin = save('cache.json', {'page_number': 1, 'source_sha256': 'a' * 64, 'geometry': geometry})
        native_pin = save('native.json', {'source_image': image})
        control_pin = save('control.json', {'status': 'COMPLETE', 'variant': 'control', 'pages': 484,
            'source_inventory': [{'page_number': 1, 'source_sha256': 'a' * 64, 'retained_cache': cache_pin,
                'native_observation': native_pin, 'prediction_content_sha256': d._digest(canonical)}]})
        root = folder / 'src/ocr_inbound'; root.mkdir(parents=True)
        adaptive = root / 'adaptive_recognition.py'; adaptive.write_text('# synthetic never imported')
        profile_pin = save('profile.json', {'bridge_sources': [{'path': 'eval_assets.py'}, {'path': 'eval_geometry.py'}],
            'parser_sources': [{'path': str(adaptive)}], 'dependencies': [], 'pins': {'frame_io': {'path': 'frame.py'}}})
        sources = {key: {'path': key, 'sha256': value} for key, value in d.SOURCE_SHA.items()}
        spec = {'profile': profile_pin, 'baseline_complete': control_pin,
                'native_summary': {'path': 'native-aggregate', 'sha256': d.FIXED['native_summary']}, 'sources': sources}
        spec_pin = save('experiment.json', spec)
        request = {'page_number': 1, 'row_index': 0, 'field': 'unit', 'source_image': image, 'geometry': geometry,
            'source_inputs': {'canonical': canonical_pin, 'cache': cache_pin, 'native': native_pin}}
        recipe = {'contract': d.CONTRACT, 'experiment': spec_pin}
        assets = SimpleNamespace(runtime=lambda profile: {'io': SimpleNamespace(upright_from_original=lambda *args: canonical), 'mapper': None})
        cells = SimpleNamespace(_contexts=lambda *args: ([{'row_index': 0, 'role': 'unit', 'evidence': self.evidence()}], []))
        def loader(name, record, check):
            return assets if name == '_whole_cell_original_eval_assets' else cells if name == '_whole_cell_original_source_cells' else SimpleNamespace()
        return save, recipe, request, spec, loader

    def test_canonical_repin_cannot_forge_original_control_content(self):
        with tempfile.TemporaryDirectory() as name:
            save, recipe, request, spec, loader = self._fixture(Path(name))
            fixed = {**d.FIXED, 'profile': spec['profile']['sha256'], 'baseline_complete': spec['baseline_complete']['sha256']}
            with patch.object(d, 'EXPERIMENT_SHA', recipe['experiment']['sha256']), patch.object(d, 'FIXED', fixed), patch.object(d, '_load', loader):
                check = lambda r: Path(r['path'])
                self.assertEqual(1, len(d.page_contexts(recipe, request, check)[1]))
                request['source_inputs']['canonical'] = save('forged.json', {'page_number': 1, 'source_sha256': 'a' * 64, 'product_rows': [{'fake': True}]})
                with self.assertRaisesRegex(ValueError, 'saved323 control'):
                    d.page_contexts(recipe, request, check)

    def test_repin_cache_native_and_image_alias_refused(self):
        with tempfile.TemporaryDirectory() as name:
            save, recipe, request, spec, loader = self._fixture(Path(name))
            fixed = {**d.FIXED, 'profile': spec['profile']['sha256'], 'baseline_complete': spec['baseline_complete']['sha256']}
            with patch.object(d, 'EXPERIMENT_SHA', recipe['experiment']['sha256']), patch.object(d, 'FIXED', fixed), patch.object(d, '_load', loader):
                for role in ('cache', 'native'):
                    changed = deepcopy(request); changed['source_inputs'][role] = save('forged-' + role + '.json', {})
                    with self.assertRaisesRegex(ValueError, 'actual saved control'):
                        d.page_contexts(recipe, changed, lambda r: Path(r['path']))
                request['source_image']['path'] = 'unbound-alias.png'
                with self.assertRaisesRegex(ValueError, 'alias/frame'):
                    d.page_contexts(recipe, request, lambda r: Path(r['path']))


if __name__ == '__main__':
    unittest.main()
