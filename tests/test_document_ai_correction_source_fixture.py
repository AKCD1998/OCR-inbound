"""The portable helper deliberately supports synthetic fixtures only."""
import unittest
from tests.correction_source_fixture import core, parse_literal_unit


class SyntheticSourceContract(unittest.TestCase):
    def token(self,text,key,box,**extra):
        return {'text':text,'token_id':key,'box':box,'confidence':.99,'engine':'PADDLE_TH',**extra}

    def test_unit_test_double_cannot_supply_arithmetic_or_strengths(self):
        self.assertIsNotNone(parse_literal_unit('BOX'))
        self.assertIsNotNone(parse_literal_unit('Box'))
        self.assertTrue(parse_literal_unit('SET')['set_unit_requires_nonadditive_guard'])
        for text in ('10 BOX','BOX [100]','50 MG','mcg','unknown',None):
            with self.subTest(text=text):self.assertIsNone(parse_literal_unit(text))

    def test_whole_typed_detections_refuse_manual_answers_and_bad_geometry(self):
        rows=[self.token('QTY','good',[40,10,70,30]),
              self.token('QTY','manual',[40,10,70,30],engine='HUMAN'),
              self.token('QTY','outside',[-1,10,70,30]),
              self.token('QTY','answer',[40,10,70,30],expected_raw='answer'),
              self.token('QTY','nonfinite',[40,10,70,30],confidence=float('nan'))]
        clean,rejected=core._read(rows,'primary',[100,100])
        self.assertEqual(['good'],[t.id for t in clean]);self.assertEqual(4,len(rejected))
        self.assertEqual((40.,10.,70.,30.),clean[0].box)

    def test_literal_labels_join_only_adjacent_whole_source_words(self):
        rows=[self.token('Product','a',[10,10,80,30]),self.token('Description','b',[90,10,190,30])]
        clean,_=core._read(rows,'primary',[500,500])
        self.assertIn(('description',('a','b')),[(r,tuple(t.id for t in g)) for r,g in core._header_parts(clean)])
        self.assertIsNone(core._role('PRICE boundary'))
        self.assertIsNone(core._role('not a known synthetic heading'))
        rows[1]['box']=[300,10,400,30];clean,_=core._read(rows,'primary',[500,500])
        self.assertNotIn(('a','b'),[tuple(t.id for t in g) for _,g in core._header_parts(clean)])

    def test_conflicting_source_ids_cannot_become_unique_typed_anchors(self):
        rows=[self.token('QTY','same',[10,10,40,30]),self.token('UOM','same',[50,10,90,30])]
        clean,_=core._read(rows,'primary',[100,100]);self.assertEqual([],clean)


if __name__=='__main__':unittest.main()
