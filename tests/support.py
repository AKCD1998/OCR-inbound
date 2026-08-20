from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ocr_inbound.config import repository_root
from ocr_inbound.service import Application


class AppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ocr-inbound-test-")
        self.root = Path(self.temp.name)
        self.app = Application.bootstrap(data_root=self.root, reviewer_id="test-reviewer")

    def tearDown(self) -> None:
        for run_id in list(self.app.automation._mutexes):
            self.app.automation._release(run_id)
        self.temp.cleanup()

    def prepare_ready(self, fixture: str = "woothi") -> str:
        base = repository_root() / "tests" / "fixtures" / "ocr_top3" / fixture
        imported = self.app.import_artifact(base / "invoice.svg", base / "artifact.json")
        document_id = imported["document"]["id"]
        predictions = self.app.generate_predictions(document_id)
        self.app.confirm_headers(document_id)
        expected = json.loads((base / "expected_review.json").read_text(encoding="utf-8"))
        for line, prediction in zip(self.app.repository.list_lines(document_id), predictions):
            correction = expected["line_corrections"].get(str(line["sequence"]))
            if correction:
                self.app.review_line_value(document_id, line["id"], "quantity", correction["quantity"], action="CORRECT", error_category="QUANTITY_EXTRACTION_ERROR")
                self.app.review_product(document_id, line["id"], correction["product_code"], correction["unit_code"], action="CORRECT", error_category=correction["error_category"])
            else:
                self.app.review_product(document_id, line["id"], prediction["product_code"], prediction["unit_code"], action="CONFIRM")
        self.app.mark_ready(document_id)
        return document_id
