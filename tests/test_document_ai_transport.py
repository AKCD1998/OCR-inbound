"""Transport receipt checks only: generated JSON, no HQ job/model/network call."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ocr_inbound.document_ai.hq_transport import completed_proposals


class CompletedProposalsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'proposals.json'
        self.payload={'contract':'document-ai-proposals.v1','pages':[],'rows':[],'synthetic':True}
        self.path.write_text(json.dumps(self.payload),encoding='utf-8')
        self.native=r'D:\isolated-synthetic-job\processing\proposals.json'
        self.execution={'status':'COMPLETE','shared_lock_released_after_owned_closure':True,
                        'resources':[{'stage':'ingress','worker_summary':{'path':self.native,
                            'sha256':hashlib.sha256(self.path.read_bytes()).hexdigest()}}]}

    def tearDown(self):self.temp.cleanup()

    def test_complete_exact_bytes_are_consumed_without_mutation(self):
        result=completed_proposals(self.execution,self.path,self.native)
        self.assertEqual(self.payload,result)
        self.assertEqual(self.payload,json.loads(self.path.read_text(encoding='utf-8')))

    def test_changed_valid_json_is_rejected_before_consuming_results(self):
        self.path.write_text(json.dumps({**self.payload,'rows':[{'id':'changed'}]}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'bytes changed'):
            completed_proposals(self.execution,self.path,self.native)

    def test_summary_native_path_must_match_exact_job_output(self):
        receipt=copy.deepcopy(self.execution)
        receipt['resources'][0]['worker_summary']['path']=r'D:\other-job\proposals.json'
        with self.assertRaisesRegex(ValueError,'binding'):
            completed_proposals(receipt,self.path,self.native)

    def test_missing_duplicate_or_unclosed_summary_is_not_complete(self):
        for edit in [{'resources':[]},{'resources':self.execution['resources']*2},
                     {'shared_lock_released_after_owned_closure':False},{'status':'RUNNING'}]:
            with self.subTest(edit=edit):
                with self.assertRaises((ValueError,RuntimeError)):
                    completed_proposals({**self.execution,**edit},self.path,self.native)


if __name__=='__main__':unittest.main()
