import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'/'document_ai'))
from paired_roi_diagnostic import same_geometry


class PairedROIDiagnosticTests(unittest.TestCase):
    def fixture(self):
        return dict(contract='document-ai-original-frame-geometry.v1', component='docling',
            stage='layout', page=160, source_image={'path':'private.jpg','sha256':'0'*64},
            source_size=[2100,3184], source_frame='original_image', rotation_ccw=0,
            regions=[{'id':'layout-6','bbox':[1,2,3,4],'score':.648,'label':'Table'}],
            rejected_native_geometry=[], layout_model_calls=1, new_text_OCR_calls=0,
            assistant_image_transcription=False)

    def test_exact_geometry_accepts_without_counting_field_gain(self):
        old=self.fixture();fresh=copy.deepcopy(old)
        fresh['worker']={'sha256':'different_delivery_metadata'}
        result=same_geometry(old,fresh)
        self.assertTrue(result['geometry_equal'])
        self.assertTrue(result['comparison_is_not_endpoint_accuracy'])
        self.assertEqual(result['new_model_calls_by_comparison'],0)

    def test_changed_source_frame_or_roi_rejected(self):
        for field,value in [('page',161),('source_size',[1,2]),('rotation_ccw',90),
                            ('regions',[]),('new_text_OCR_calls',1)]:
            with self.subTest(field=field):
                old=self.fixture();fresh=copy.deepcopy(old);fresh[field]=value
                with self.assertRaises(ValueError):same_geometry(old,fresh)

    def test_missing_field_and_nonlayout_rejected(self):
        old=self.fixture();fresh=copy.deepcopy(old);del fresh['source_image']
        with self.assertRaises(ValueError):same_geometry(old,fresh)
        old=self.fixture();old['stage']='tables'
        with self.assertRaises(ValueError):same_geometry(old,copy.deepcopy(old))


if __name__=='__main__':unittest.main()
