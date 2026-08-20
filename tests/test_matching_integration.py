"""Layer F Slice 1 remediation -- real persistence-boundary integration tests.

Codex's second adjudication of Slice 1 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
section 17) found that `tests/test_matching.py`'s Slice-1 tests all construct
`line["evidence_json"]` as an already-decoded Python dict directly, which
skips the exact boundary where the real bug lived: `Repository.list_lines()`
returns `document_lines.evidence_json` as the raw JSON TEXT column value
(written by `canonical_json(...)` at import time), never a dict, and the
matcher's old `_barcode_candidates()` silently returned `[]` for anything
that wasn't already a dict.

This file goes through the REAL path end to end for both remediated bugs:
`Application.import_uploaded_artifact()` -> SQLite `document_lines` insert
-> `Repository.list_lines()` read-back -> `ProductMatcher._predict()`
(via `Application.generate_predictions()`), so a false-green result here is
not possible the way it was before -- if the decode boundary regresses,
these tests fail on a real prediction reaching the wrong tier.

Also covers the OTHER Slice-1-remediation finding (Codex finding 1): a
supplier SKU echoed inline into the OCR text of a REAL, persisted line must
not shadow a correctly-approved supplier alias reached through the real
`record_alias_observation` / `approve_alias` promotion path (not the
`_StaticAliasRepository` test double used elsewhere).
"""
from __future__ import annotations

import tempfile
import unittest
import sqlite3
import importlib.resources
from pathlib import Path

from ocr_inbound.config import build_profile
from ocr_inbound.db import Repository
from ocr_inbound.identity import Actor
from ocr_inbound.service import Application


CONTRACT_VERSION = "ocr-inbound-artifact.v1"


def _header_field(value, raw_text=None):
    return {
        "value": value,
        "raw_text": raw_text if raw_text is not None else str(value),
        "required": True,
        "confidence": "0.99",
        "source_prediction_ref": "integration-test:header",
        "evidence": {},
    }


def _artifact(*, supplier_code: str, line_description: str, line_raw_ocr_text: str, supplier_sku: str | None, line_evidence: dict, invoice_number: str) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "ocr_run_id": f"integration-test-{invoice_number}",
        "ocr_engine_versions": {"layers_a_e": "integration-test", "tesseract": "n/a", "paddle": "n/a", "easyocr": "n/a"},
        "header": {
            "fields": {
                "supplier_code": _header_field(supplier_code),
                "invoice_number": _header_field(invoice_number),
                "invoice_date": _header_field("2026-08-20", raw_text="20/08/2569"),
                "grand_total_minor": _header_field(10000, raw_text="100.00"),
            }
        },
        "lines": [
            {
                "source_row_ref": "integration-test:r1",
                "raw_ocr_text": line_raw_ocr_text,
                "supplier_sku": supplier_sku,
                "description": line_description,
                "unit": "BOX",
                "quantity": "1",
                "unit_price_minor": 10000,
                "line_total_minor": 10000,
                "evidence": line_evidence,
            }
        ],
    }


# A minimal, valid SVG payload -- enough for FilesystemArtifactStore's MIME
# sniff (`sniff_mime`) to accept it as a real source file without needing an
# actual invoice image on disk.
_FAKE_SOURCE_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"


class MatchingPersistenceBoundaryIntegrationTests(unittest.TestCase):
    """Real `Application` + SQLite `Repository`, not the offline
    `AdaReferenceCache`/`_StaticAliasRepository` test doubles used in
    `tests/test_matching.py`."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="layerf-integration-")
        self.app = Application.bootstrap(data_root=Path(self._tmpdir.name), reviewer_id="integration-test-reviewer")
        # Replace the packaged default fixture with a small, controlled
        # catalog so these scenarios are deterministic and do not depend on
        # (or risk colliding with) the real product master shape.
        self.app.cache.refresh_from_fixture(
            {
                "products": [
                    {
                        "product_code": "IC-BC900",
                        "barcode": "8859990000001",
                        "name": "REAL BARCODE INTEGRATION PRODUCT",
                        "normalized_name": "REAL BARCODE INTEGRATION PRODUCT",
                        "ingredient": "",
                        "strength": "",
                        "size": "",
                        "manufacturer": "",
                        "active": True,
                        "units": [{"unit_code": "BOX", "factor": "1", "active": True}],
                    },
                    {
                        "product_code": "630010124",
                        "barcode": None,
                        "name": "UNRELATED COINCIDENTAL CODE PRODUCT",
                        "normalized_name": "UNRELATED COINCIDENTAL CODE PRODUCT",
                        "ingredient": "",
                        "strength": "",
                        "size": "",
                        "manufacturer": "",
                        "active": True,
                        "units": [{"unit_code": "BOX", "factor": "1", "active": True}],
                    },
                    {
                        "product_code": "IC-RIGHT",
                        "barcode": None,
                        "name": "THE ACTUAL CORRECT INTEGRATION PRODUCT",
                        "normalized_name": "THE ACTUAL CORRECT INTEGRATION PRODUCT",
                        "ingredient": "",
                        "strength": "",
                        "size": "",
                        "manufacturer": "",
                        "active": True,
                        "units": [{"unit_code": "BOX", "factor": "1", "active": True}],
                    },
                    {
                        "product_code": "IC-CONF-001",
                        "barcode": None,
                        "name": "CONFLICTING INTERNAL CODE PRODUCT ONE",
                        "normalized_name": "CONFLICTING INTERNAL CODE PRODUCT ONE",
                        "ingredient": "",
                        "strength": "",
                        "size": "",
                        "manufacturer": "",
                        "active": True,
                        "units": [{"unit_code": "BOX", "factor": "1", "active": True}],
                    },
                    {
                        "product_code": "IC-CONF-002",
                        "barcode": None,
                        "name": "CONFLICTING INTERNAL CODE PRODUCT TWO",
                        "normalized_name": "CONFLICTING INTERNAL CODE PRODUCT TWO",
                        "ingredient": "",
                        "strength": "",
                        "size": "",
                        "manufacturer": "",
                        "active": True,
                        "units": [{"unit_code": "BOX", "factor": "1", "active": True}],
                    },
                ],
                "suppliers": [{"supplier_code": "ACME", "name": "Acme Wholesale", "active": True}],
                "purchase_history": [],
            }
        )

    def tearDown(self) -> None:
        for run_id in list(self.app.automation._mutexes):
            self.app.automation._release(run_id)
        self._tmpdir.cleanup()

    def _import_and_predict(self, artifact: dict) -> dict:
        result = self.app.import_uploaded_artifact("integration-test.svg", _FAKE_SOURCE_BYTES, artifact)
        document_id = result["document"]["id"]
        predictions = self.app.generate_predictions(document_id)
        self.assertEqual(len(predictions), 1)
        return predictions[0]

    def test_barcode_evidence_resolves_through_a_real_import_persist_readback_cycle(self):
        # Reproduces Codex adjudication finding 2 end to end: evidence_json
        # travels through canonical_json() at import, is stored as SQLite
        # TEXT, and is read back as a plain string by Repository.list_lines()
        # before ever reaching the matcher -- exactly the boundary the old
        # `isinstance(evidence, dict)` check silently failed at.
        artifact = _artifact(
            supplier_code="ACME",
            line_description="COMPLETELY UNRELATED DESCRIPTION TEXT",
            line_raw_ocr_text="COMPLETELY UNRELATED DESCRIPTION TEXT",
            supplier_sku=None,
            line_evidence={"page": 1, "bbox": [0.0, 0.0, 1.0, 1.0], "barcode_candidates": ["8859990000001"]},
            invoice_number="INT-BARCODE-0001",
        )
        prediction = self._import_and_predict(artifact)
        self.assertEqual(prediction["tier"], "EXACT_BARCODE")
        self.assertEqual(prediction["product_code"], "IC-BC900")

    def test_supplier_sku_echoed_in_real_persisted_ocr_text_does_not_shadow_a_real_active_alias(self):
        # Reproduces Codex adjudication finding 1 end to end, using the REAL
        # alias promotion path (record_alias_observation x3 -> approve_alias)
        # instead of a hand-built test double, and a REAL persisted line
        # whose OCR text echoes the printed supplier SKU inline -- exactly
        # like the `berlin`/`woothi` golden fixtures already do in
        # tests/fixtures/ocr_top3 (raw_ocr_text = "6300001 <description>").
        actor = self.app.actor
        alias = None
        for i in range(3):
            alias = self.app.repository.record_alias_observation("ACME", "630010124", "IC-RIGHT", f"seed-doc-{i}", actor)
        self.assertEqual(alias["status"], "ELIGIBLE")
        approved = self.app.repository.approve_alias(alias["id"], actor)
        self.assertEqual(approved["status"], "ACTIVE")

        artifact = _artifact(
            supplier_code="ACME",
            line_description="630010124 SOME ITEM DESCRIPTION TEXT",
            line_raw_ocr_text="630010124 SOME ITEM DESCRIPTION TEXT",
            supplier_sku="630010124",
            line_evidence={"page": 1, "bbox": [0.0, 0.0, 1.0, 1.0]},
            invoice_number="INT-ALIAS-0001",
        )
        prediction = self._import_and_predict(artifact)
        self.assertEqual(prediction["tier"], "ACTIVE_ALIAS")
        self.assertEqual(prediction["product_code"], "IC-RIGHT")
        self.assertNotEqual(prediction["product_code"], "630010124")

    def test_missing_supplier_sku_free_text_code_hit_is_never_auto_confirmed_through_real_persistence(self):
        # Codex's second Slice-1 re-adjudication, finding 1
        # (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 18): the earlier
        # supplier_sku-equality exclusion only protects a line where
        # supplier_sku was actually parsed by the extraction stage. Here the
        # OCR text contains the wholesaler code but the artifact's
        # `supplier_sku` field is None (a realistic parser failure) -- the
        # persisted line must still never auto-confirm EXACT_CODE.
        artifact = _artifact(
            supplier_code="ACME",
            line_description="630010124 SOME ITEM DESCRIPTION TEXT",
            line_raw_ocr_text="630010124 SOME ITEM DESCRIPTION TEXT",
            supplier_sku=None,
            line_evidence={"page": 1, "bbox": [0.0, 0.0, 1.0, 1.0]},
            invoice_number="INT-MISSING-SKU-0001",
        )
        prediction = self._import_and_predict(artifact)
        self.assertNotEqual(prediction["tier"], "EXACT_CODE")
        self.assertEqual(prediction["tier"], "INTERNAL_CODE_TEXT_MATCH")
        self.assertTrue(prediction["provenance"]["human_confirmation_required"])

    def test_explicit_internal_code_conflict_quarantines_through_real_persistence(self):
        # Codex's second Slice-1 re-adjudication, finding 2: explicit
        # evidence_json["internal_code_candidates"] resolving to more than
        # one real product must quarantine (UNRESOLVED, no auto-pick of the
        # first array entry), exactly like conflicting barcode evidence --
        # verified through the real import/persist/read-back cycle.
        artifact = _artifact(
            supplier_code="ACME",
            line_description="UNRELATED TEXT",
            line_raw_ocr_text="UNRELATED TEXT",
            supplier_sku=None,
            line_evidence={"page": 1, "bbox": [0.0, 0.0, 1.0, 1.0], "internal_code_candidates": ["IC-CONF-001", "IC-CONF-002"]},
            invoice_number="INT-CODE-CONFLICT-0001",
        )
        prediction = self._import_and_predict(artifact)
        self.assertEqual(prediction["tier"], "UNRESOLVED")
        self.assertIsNone(prediction["product_code"])
        candidate_codes = {c["product_code"] for c in prediction["candidates"]}
        self.assertEqual(candidate_codes, {"IC-CONF-001", "IC-CONF-002"})


class ProductNameAliasSQLiteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="name-alias-sqlite-")
        self.profile = build_profile("staging", Path(self._tmpdir.name))
        self.repository = Repository(self.profile)
        self.actor = Actor("alias-reviewer", "Alias Reviewer", "TEST IDENTITY")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_fresh_bootstrap_applies_v1_and_v2(self):
        self.repository.migrate()
        with self.repository.connect() as connection:
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
            table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='product_name_aliases'").fetchone()
        self.assertEqual(versions, [1, 2, 3])
        self.assertIsNotNone(table)

    def test_existing_v1_database_upgrades_to_v2(self):
        sql_v1 = importlib.resources.files("ocr_inbound").joinpath("migrations/0001_initial.sql").read_text(encoding="utf-8")
        connection = sqlite3.connect(self.profile.app_db)
        try:
            connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            connection.executescript(sql_v1)
            connection.commit()
        finally:
            connection.close()
        self.repository.migrate()
        with self.repository.connect() as connection:
            versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
            table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='product_name_aliases'").fetchone()
        self.assertEqual(versions, [1, 2, 3])
        self.assertIsNotNone(table)

    def test_three_distinct_documents_promote_then_human_approval_activates(self):
        self.repository.migrate()
        first = self.repository.record_name_alias_observation("MINIDIAB", "IC-000648", "doc-1", self.actor)
        duplicate = self.repository.record_name_alias_observation("MINIDIAB", "IC-000648", "doc-1", self.actor)
        second = self.repository.record_name_alias_observation("MINIDIAB", "IC-000648", "doc-2", self.actor)
        self.assertEqual(first["status"], "CANDIDATE")
        self.assertEqual(duplicate["distinct_document_count"], 1)
        self.assertEqual(second["status"], "CANDIDATE")
        eligible = self.repository.record_name_alias_observation("MINIDIAB", "IC-000648", "doc-3", self.actor)
        self.assertEqual(eligible["status"], "ELIGIBLE")
        active = self.repository.approve_name_alias(eligible["id"], self.actor)
        self.assertEqual(active["status"], "ACTIVE")
        self.assertEqual(active["approved_by"], self.actor.actor_id)
        self.assertEqual(self.repository.list_name_aliases()[0]["status"], "ACTIVE")

    def test_conflicting_products_quarantine_every_mapping_for_the_phrase(self):
        self.repository.migrate()
        first = self.repository.record_name_alias_observation("MINIDIAB", "IC-A", "doc-a", self.actor)
        second = self.repository.record_name_alias_observation("MINIDIAB", "IC-B", "doc-b", self.actor)
        rows = self.repository.list_name_aliases()
        self.assertEqual(first["status"], "CANDIDATE")
        self.assertEqual(second["status"], "QUARANTINED")
        self.assertEqual({row["status"] for row in rows}, {"QUARANTINED"})


if __name__ == "__main__":
    unittest.main()
