"""Invented detector/TSV observations; no images, files, models or references."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'experiments/document_ai'))
import correction_bridge
import fresh_source_cells as fresh
import source_cell_association as cells
import whole_cell_source as protocol
import whole_cell_source_derivation as derivation
from component_common import RESOURCES
from eval_geometry import digest
from tests.test_document_ai_correction_bridge import fixture, HELPERS, PIN


def fake_pin(name):
    return {'path': 'invented_'+name, 'sha256': 'd'*64}


def make_record(page, cache, obs, helpers, role='quantity', text='10', score=.99, tess_score=93,
                count=1, request_suffix=''):
    contexts, _ = cells._contexts(page, cache, obs, helpers, PIN)
    context = next(c for c in contexts if c['row_index'] == 0 and c['role'] == role)
    geometry = {k: deepcopy(cache['geometry'][k]) for k in ('original_size', 'upright_size', 'orientation_ccw')}
    interval, _ = derivation.row_interval(context['evidence'])
    identity = 'invented_r0_'+role+request_suffix
    request = {'request_id': identity, 'page_number': page['page_number'], 'row_index': 0, 'field': role,
        'source_image': fake_pin('source.jpg'), 'geometry': geometry, 'source_band': context['source_band'],
        'row_barrier_interval': interval, 'source_token_inventory': fake_pin('inventory.json'),
        'context_proof': fake_pin('context.json'),
        'source_inputs': {'cache': fake_pin('cache.json'), 'canonical': fake_pin('canonical.json'), 'native': PIN}}
    request['source_image']['sha256'] = page['source_sha256']
    inventory, invalid = derivation.inventory(cache, geometry)
    assert not invalid
    crop = protocol.whole_word_crop(request, inventory); crop['independently_reconstructed_source_context'] = True
    target = [530, 220, 570, 240] if role == 'quantity' else [690, 220, 750, 240]
    x, y = crop['crop_bbox_upright'][:2]
    polys = [[[target[0]-x, target[1]-y], [target[2]-x, target[1]-y],
              [target[2]-x, target[3]-y], [target[0]-x, target[3]-y]]] * count
    raw_detector = {'dt_polys': polys, 'dt_scores': [.88]*count, 'input_path': fake_pin('whole_ROI.png')['path']}
    detections = protocol.native_detections(polys, [.88]*count, crop, geometry)
    primary = [{**d, 'raw_text': text, 'confidence': score, 'engine_family': 'PADDLE',
        'engine': 'NEW_WHOLE_CELL_PADDLE_SERVER_DET_THAI_REC', 'token_id': identity+':paddle:%03d' % i,
        'recognition_image': fake_pin('recognition.png'), 'character_boxes_available': False,
        'same_family_as_cached_Paddle': True} for i, d in enumerate(detections)]
    header = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    tsv = header+'5\t1\t1\t1\t1\t1\t%d\t%d\t%d\t%d\t%s\t%s\n' % (
        target[0]-x, target[1]-y, target[2]-target[0], target[3]-target[1], tess_score, text)
    observations = {'contract': 'document-ai-whole-cell-source-result.v1', 'request_id': identity,
        'page_number': page['page_number'], 'row_index': 0, 'field': role, 'source_image': request['source_image'],
        'geometry': geometry, 'crop': crop, 'Paddle_observations': primary,
        'Tesseract_observations': fresh._tsv(tsv, crop, identity+':tesseract'),
        'literal_source_only': True, 'logical_field_values_assigned': False,
        'baseline_cache_modified': False, 'extra_independent_engine_families': 0}
    summary = {'contract': 'document-ai-whole-cell-source-result.v1', 'component': 'whole-cell-source',
        'status': 'COMPLETE', 'executed': True, 'request_id': identity, 'requests_selected': 1, 'requests_completed': 1,
        'optimizer_updates': 0, 'canonical_values_modified': False, 'baseline_cache_modified': False,
        'actual_detector_regions': count, 'positive_detector_recognizer_path': bool(count),
        'new_calls_completed': {'Paddle_detector': 1, 'Paddle_Thai_recognizer': count, 'Tesseract_ROI': 1},
        'assistant_image_reads': 0, 'source_image_decodes_completed': 1, 'resource_policy': RESOURCES,
        'worker': {'sha256': 'b5f498a65e9494f449f6aed9e073aea44958aa5dc22dfe75f0f22451a02324bf'},
        'models': {'detector': {'model_name': 'PP-OCRv5_server_det', 'files': {'inference.pdiparams': {
            'sha256': '183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d'}}},
            'recognizer': {'model_name': 'th_PP-OCRv5_mobile_rec', 'files': {'inference.pdiparams': {
            'sha256': '45ec91f2322b58b8d30ba27d18fcfdbb8bf388b918dd978162d2af91e0c66d4b'}}}},
        'tesseract': {'reader': {'sha256': 'c1b16bdd8e20dfd7faf4b91c7c8c11a0efe4ea4e715691cf554b6a39861cf4b1'},
            'tsv_config': {'sha256': '59d079bb75d8b3d7c839a3564580cb559e362c93a9d70f234e421c0c3e767e04'}}}
    return {'request': request, 'observations': observations, 'observations_pin': fake_pin('observations.json'),
        'summary': summary, 'summary_pin': fake_pin('summary.json'), 'closed_source': fake_pin('closed.json'),
        'crop': crop, 'physical_crop': fake_pin('whole_ROI.png'),
        'source_context': {'contract': 'document-ai-whole-cell-source-context.v1',
            'request_binding': {k: v for k, v in request.items() if k != 'context_proof'},
            'derivation': {'actual_context_sha256': digest(context['evidence']), 'crop_admission': {'eligible': True}}},
        'raw_proof': {'detector': raw_detector,
            'recognizers': [{'detection_index': i, 'raw': {'rec_text': text, 'rec_score': score,
                             'input_path': fake_pin('recognition.png')['path']}} for i in range(count)],
            'tesseract_tsv': tsv, 'pins': {'detector': fake_pin('detector.json'),
                'recognizers': [fake_pin('rec%d.json' % i) for i in range(count)], 'tesseract_tsv': fake_pin('actual.tsv')}}}


def fresh_fixture(role='quantity', text='10', score=.99, tess_score=93, count=1, weak_old=True):
    page, cache, obs = fixture()
    cache['geometry'].update(machine_only=True, vision_LLM_calls=0)
    helpers = {**HELPERS, 'correction_bridge': correction_bridge, 'cell_association': cells,
               'source_crop_protocol': protocol, 'fresh_source_derivation': derivation}
    page['product_rows'][0]['fields'][role] = {'raw_value': '9' if role == 'quantity' else 'B0X',
                                             'normalized_value': '9' if role == 'quantity' else 'B0X'}
    if weak_old:
        for token in cache['working_tokens']:
            if token['token_id'] == ('p:q1' if role == 'quantity' else 'p:u1'):
                token['confidence'] = .5
    record = make_record(page, cache, obs, helpers, role, text, score, tess_score, count)
    helpers['fresh_source_reads'] = {'contract': fresh.RUNTIME, 'manifest': fake_pin('manifest.json'), 'records': [record]}
    return page, cache, obs, helpers


class FreshSourceCellTests(unittest.TestCase):
    def test_new_whole_source_pair_can_replace_nonempty_wrong_value_and_verify_without_mutation(self):
        page, cache, obs, helpers = fresh_fixture(); original = deepcopy((page, cache, obs))
        audit = fresh.propose(page, cache, obs, helpers, PIN)
        self.assertEqual(1, len(audit['changes']), audit['rejected']); event = audit['changes'][0]
        self.assertEqual('9', event['before']['raw_value']); self.assertEqual('10', event['candidate']['raw_value'])
        self.assertEqual(event['before'], event['candidate']['prior_source_evidence'])
        self.assertEqual(0, event['candidate']['extra_independent_engine_families'])
        verified = fresh.verify(page, cache, obs, helpers, PIN, 0, 'quantity', event['evidence'])
        self.assertEqual(event['candidate']['fresh_source_evidence'], verified['fresh_source_evidence'])
        self.assertEqual(original, (page, cache, obs)); self.assertFalse(verified['old_conflict_audit']['old_pair_qualified'])

    def test_unit_literal_uses_same_grammar_and_never_infers_packing(self):
        for text, accepted in (('BOX', True), ('2 BOX', False), ('SET', False)):
            page, cache, obs, helpers = fresh_fixture('unit', text)
            audit = fresh.propose(page, cache, obs, helpers, PIN)
            self.assertEqual(accepted, bool(audit['changes']), audit['rejected'])

    def test_correct_existing_value_does_not_receive_provenance_only_replacement(self):
        page, cache, obs, helpers = fresh_fixture(); page['product_rows'][0]['fields']['quantity']['raw_value'] = '10'
        page['product_rows'][0]['fields']['quantity']['normalized_value'] = '10'
        self.assertFalse(fresh.propose(page, cache, obs, helpers, PIN)['changes'])

    def test_old_qualified_pair_disagreement_abstains_but_numeric_format_equivalence_does_not(self):
        page, cache, obs, helpers = fresh_fixture(text='20', weak_old=False)
        audit = fresh.propose(page, cache, obs, helpers, PIN)
        self.assertFalse(audit['changes']); self.assertIn('genuinely_qualified_old_and_fresh_source_pairs_disagree',
                                                       [r['reason'] for r in audit['rejected']])
        page, cache, obs, helpers = fresh_fixture(text='10.0', weak_old=False)
        self.assertTrue(fresh.propose(page, cache, obs, helpers, PIN)['changes'])

    def test_confidence_or_extra_fresh_detection_is_not_filtered_to_a_desired_answer(self):
        for score, tess, count in ((.949, 93, 1), (.99, 69.9, 1), (.99, 93, 2)):
            page, cache, obs, helpers = fresh_fixture(score=score, tess_score=tess, count=count)
            self.assertFalse(fresh.propose(page, cache, obs, helpers, PIN)['changes'])

    def test_zero_detection_is_per_context_hold_and_not_a_pagewide_failure(self):
        page, cache, obs, helpers = fresh_fixture()
        zero = make_record(page, cache, obs, helpers, 'unit', 'BOX', count=0)
        helpers['fresh_source_reads']['records'].append(zero)
        audit = fresh.propose(page, cache, obs, helpers, PIN)
        self.assertEqual([(0, 'quantity')], [(e['row_index'], e['field']) for e in audit['changes']], audit['rejected'])
        self.assertIn('fresh_read_rejected:complete_one_detection_per_reader_required', [r['reason'] for r in audit['rejected']])

    def test_actual_raw_polygon_recognizer_and_TSV_cannot_be_replaced_by_crop_boxes_or_scalar_claims(self):
        for mutate in (lambda r: r['observations']['Paddle_observations'][0].update(bbox_upright=r['crop']['crop_bbox_upright']),
                       lambda r: r['observations']['Paddle_observations'][0].update(raw_text='999'),
                       lambda r: r['observations']['Tesseract_observations'][0].update(raw_text='999'),
                       lambda r: r['summary']['new_calls_completed'].update(Paddle_detector=0),
                       lambda r: r['raw_proof']['detector'].update(input_path='invented_other_ROI.png'),
                       lambda r: r['raw_proof']['recognizers'][0]['raw'].update(input_path='invented_other_region.png'),
                       lambda r: r['summary']['worker'].update(sha256='0'*64)):
            page, cache, obs, helpers = fresh_fixture(); mutate(helpers['fresh_source_reads']['records'][0])
            self.assertFalse(fresh.propose(page, cache, obs, helpers, PIN)['changes'])

    def test_same_family_cannot_be_renamed_into_an_independent_reader(self):
        page, cache, obs, helpers = fresh_fixture(); record = helpers['fresh_source_reads']['records'][0]
        record['observations']['Tesseract_observations'][0]['engine_family'] = 'PADDLE'
        self.assertFalse(fresh.propose(page, cache, obs, helpers, PIN)['changes'])

    def test_original_foreign_geometry_owner_survives_new_ids_and_coarse_or_jittered_boxes(self):
        for field in ('unit_price', 'lot', 'description'):
            page, cache, obs, helpers = fresh_fixture()
            # Keeping the name itself unchanged is necessary for the original context.
            page['product_rows'][0]['fields'][field if field != 'description' else 'other_description'] = {
                'raw_value': 'preserved', 'bbox': [569.9, 210, 650, 250], 'token_ids': ['unrelated-old-id']}
            audit = fresh.propose(page, cache, obs, helpers, PIN)
            self.assertFalse(audit['changes']); self.assertIn('preserved_foreign_source_owner', [r['reason'] for r in audit['rejected']])

    def test_source_band_context_hash_frame_and_evidence_tampering_are_refused(self):
        for mutate in (lambda r: r['request']['geometry'].update(orientation_ccw=180),
                       lambda r: r['source_context']['derivation'].update(actual_context_sha256='0'*64),
                       lambda r: r['observations']['source_image'].update(sha256='0'*64)):
            page, cache, obs, helpers = fresh_fixture(); mutate(helpers['fresh_source_reads']['records'][0])
            self.assertFalse(fresh.propose(page, cache, obs, helpers, PIN)['changes'])
        page, cache, obs, helpers = fresh_fixture(); event = fresh.propose(page, cache, obs, helpers, PIN)['changes'][0]
        event['evidence']['fresh_source_evidence']['source_band'][0] -= 1
        with self.assertRaises(ValueError):
            fresh.verify(page, cache, obs, helpers, PIN, 0, 'quantity', event['evidence'])

    def test_old_high_confidence_coarse_box_is_preserved_but_not_a_qualified_third_vote(self):
        page, cache, obs, helpers = fresh_fixture(weak_old=False)
        primary = next(t for t in cache['working_tokens'] if t['token_id'] == 'p:q1')
        primary['box'] = [530, 210, 570, 300]
        helpers['fresh_source_reads']['records'] = [make_record(page, cache, obs, helpers)]
        audit = fresh.propose(page, cache, obs, helpers, PIN)
        self.assertEqual(1, len(audit['changes']), audit['rejected'])
        event = audit['changes'][0]
        verified = fresh.verify(page, cache, obs, helpers, PIN, 0, 'quantity', event['evidence'])
        self.assertFalse(verified['old_conflict_audit']['old_pair_qualified'])
        self.assertEqual([530, 210, 570, 300], next(t['bbox'] for t in
            verified['retained_source_alternatives']['primary'] if t['token_id'] == 'p:q1'))

    def test_same_row_source_swap_requires_both_independent_field_revisions(self):
        page, cache, obs, helpers = fresh_fixture()
        fields = page['product_rows'][0]['fields']
        fields['quantity'] = {'raw_value': 'BOX', 'token_ids': ['p:u1'], 'bbox': [690, 220, 750, 240]}
        fields['unit'] = {'raw_value': '10', 'token_ids': ['p:q1'], 'bbox': [530, 220, 570, 240]}
        good = make_record(page, cache, obs, helpers, 'unit', 'BOX')
        helpers['fresh_source_reads']['records'].append(good)
        audit = fresh.propose(page, cache, obs, helpers, PIN)
        self.assertEqual({(0, 'quantity'), (0, 'unit')}, {(e['row_index'], e['field']) for e in audit['changes']}, audit['rejected'])
        helpers['fresh_source_reads']['records'][-1] = make_record(page, cache, obs, helpers, 'unit', 'BOX', tess_score=69)
        self.assertFalse(fresh.propose(page, cache, obs, helpers, PIN)['changes'])


if __name__ == '__main__':
    unittest.main()
