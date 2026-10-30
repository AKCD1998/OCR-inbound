"""Consumed-byte and bounded wire provenance; no models or invoice decoding."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/document_ai'))
import glm_native_worker as native
import glm_backend as backend


class GlmNativeProvenanceTests(unittest.TestCase):
    def test_actual_consumed_buffer_is_checked_after_read_not_an_earlier_path_check(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'synthetic';p.write_bytes(b'exact source bytes')
            record={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            self.assertEqual(b'exact source bytes',native.consumed_bytes(record,100))
            p.write_bytes(b'different bytes')
            with self.assertRaises(ValueError):native.consumed_bytes(record,100)

    def test_oversize_input_refused_before_consumption(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'synthetic';p.write_bytes(b'large')
            with self.assertRaises(ValueError):native.consumed_bytes({'path':str(p),'sha256':'a'*64},2)

    def test_wire_JSON_is_preserved_even_if_parsing_fails(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'HTTP_RESPONSE_BODY.bin'
            with patch.object(native.urllib.request,'urlopen',return_value=io.BytesIO(b'not valid JSON')):
                with self.assertRaises(json.JSONDecodeError):native.response_json('http://127.0.0.1:9999',raw_output=p)
            self.assertEqual(b'not valid JSON',p.read_bytes())
            self.assertFalse(json.loads(p.with_suffix('.capture.json').read_text())['capture_truncated'])

    def test_wire_capture_limit_is_explicit_and_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as name:
            p=Path(name)/'HTTP_RESPONSE_BODY.bin'
            with patch.object(native,'MAX_HTTP_BYTES',16),patch.object(native.urllib.request,'urlopen',return_value=io.BytesIO(b'x'*100)):
                with self.assertRaises(ValueError):native.response_json('http://127.0.0.1:9999',raw_output=p)
            self.assertEqual(17,p.stat().st_size)
            self.assertTrue(json.loads(p.with_suffix('.capture.json').read_text())['capture_truncated'])

    def test_both_actual_weights_and_all_runtime_budgets_choose_the_tight_context(self):
        reserves={'vision_scratch_bytes':128*1024**2,'decoder_prefill_scratch_bytes':32*1024**2,
                  'runtime_and_owned_parent_bytes':64*1024**2}
        tight=backend.memory_preflight(450131264,271280576,context_tokens=1024,reservations=reserves)
        wide=backend.memory_preflight(450131264,271280576,context_tokens=2048,reservations=reserves)
        self.assertEqual('BOUNDED_CANARY_REQUIRED',tight['status'])
        self.assertEqual(1027596032,tight['total_budget_bytes'])
        self.assertFalse(tight['runtime_fit_proven'])
        self.assertEqual('REJECTED_RESOURCE_BUDGET',wide['status'])


if __name__=='__main__':unittest.main()
