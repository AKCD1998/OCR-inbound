"""Independent synthetic heading-gap checks; no private data, models or images."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'experiments' / 'document_ai'), str(ROOT / 'src')]
from correction_bridge import _description_gap as propose_gap, _literal_header
from correction_guard import _description_gap as verify_gap
from tests.correction_source_fixture import core


class Rules:
    _height = staticmethod(lambda box: box[3] - box[1])
    _cy = staticmethod(lambda box: (box[1] + box[3]) / 2)

    @staticmethod
    def _inside(box, bounds):
        return (bounds[0] <= box[0] < box[2] <= bounds[2]
                and bounds[1] <= box[1] < box[3] <= bounds[3])


def source(extra=None):
    words = [('Material No.', 'code', [160, 100, 190, 120]),
             ('Description', 'description', [200, 100, 260, 120]),
             ('Quantity', 'quantity', [600, 100, 660, 120]),
             ('Unit', 'unit', [750, 100, 800, 120])]
    if extra:
        words.append(extra)
    return [{'token_id': key, 'text': text, 'bbox': box, 'box': box,
             'confidence': .99, 'engine': 'PADDLE_TH', 'aliases': [key]}
            for text, key, box in words]


def header_for(primary, size):
    clean, _ = core._read(primary, 'primary', size)
    return _literal_header(clean, core, size)


def source_claim(primary):
    lookup = {t['token_id']: t for t in primary}
    return {'method': 'SOURCE_HEADER_TEXT_GAP',
            'description_header_tokens': [deepcopy(lookup['description'])],
            'left_header': {'role': 'supplier_code', 'tokens': [deepcopy(lookup['code'])]},
            'right_header': {'role': 'quantity', 'tokens': [deepcopy(lookup['quantity'])]},
            'bounds': [190, 600], 'physical_cell_borders_claimed': False}


class IndependentGapTests(unittest.TestCase):
    anchor = [190, 220, 280, 240]

    def verify(self, proof, primary, size=(1000, 500)):
        return verify_gap(proof, primary, self.anchor, {'bbox': [0, 80, size[0], 400]},
                          core, Rules, list(size))

    def test_exact_left_price_intrusion_from_outside_center_refused_by_both(self):
        primary = source(('Unit Price', 'foreign-price', [0, 100, 300, 120]))
        header = header_for(primary, [1000, 500])
        self.assertIsNotNone(header)
        self.assertIsNone(propose_gap(self.anchor, header, {t['token_id']: t for t in primary}, Rules))
        with self.assertRaisesRegex(ValueError, 'competing_literal_heading'):
            self.verify(source_claim(primary), primary)

    def test_right_price_intrusion_from_outside_center_refused_by_both(self):
        primary = source(('Unit Price', 'foreign-price', [550, 100, 1100, 120]))
        header = header_for(primary, [1200, 500])
        self.assertIsNotNone(header)
        self.assertIsNone(propose_gap(self.anchor, header, {t['token_id']: t for t in primary}, Rules))
        with self.assertRaisesRegex(ValueError, 'competing_literal_heading'):
            self.verify(source_claim(primary), primary, (1200, 500))

    def test_neutral_heading_whole_box_intrusion_refused(self):
        self.assertIsNone(core._role('PRICE boundary'))
        primary = source(('PRICE boundary', 'neutral-price', [0, 100, 300, 120]))
        header = header_for(primary, [1000, 500])
        self.assertIsNotNone(header)
        self.assertIsNone(propose_gap(self.anchor, header, {t['token_id']: t for t in primary}, Rules))
        with self.assertRaisesRegex(ValueError, 'competing_neutral_heading'):
            self.verify(source_claim(primary), primary)

    def test_benign_bounded_gap_succeeds_without_changing_source(self):
        primary = source()
        before = deepcopy(primary)
        header = header_for(primary, [1000, 500])
        proof = propose_gap(self.anchor, header, {t['token_id']: t for t in primary}, Rules)
        self.assertIsNotNone(proof)
        self.assertEqual([190, 600], proof['bounds'])
        self.assertIsNone(self.verify(proof, primary))
        self.assertEqual(before, primary)

    def test_nonoverlapping_foreign_heading_on_either_side_is_not_rejected(self):
        for extra in [('Unit Price', 'outside-left', [0, 100, 150, 120]),
                      ('Unit Price', 'outside-right', [680, 100, 740, 120])]:
            with self.subTest(side=extra[1]):
                primary = source(extra)
                header = header_for(primary, [1000, 500])
                proof = propose_gap(self.anchor, header, {t['token_id']: t for t in primary}, Rules)
                self.assertIsNotNone(proof)
                self.assertIsNone(self.verify(proof, primary))

    def test_missing_or_forged_boundary_cannot_widen_gap(self):
        primary = source()
        proof = source_claim(primary)
        proof['bounds'] = [0, 600]
        with self.assertRaisesRegex(ValueError, 'whole_description_outside'):
            self.verify(proof, primary)
        proof = source_claim(primary)
        proof.pop('left_header')
        with self.assertRaisesRegex(ValueError, 'two_distinct_competing'):
            self.verify(proof, primary)


if __name__ == '__main__':
    unittest.main()
