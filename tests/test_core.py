from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest import mock

from ocr_inbound.config import assert_physical_isolation, build_profile, repository_root
from ocr_inbound.db import new_id
from ocr_inbound.errors import DomainError
from ocr_inbound.identity import StagingIdentityProvider
from ocr_inbound.money import line_total_minor, parse_decimal, parse_thai_date
from ocr_inbound.ocr_adapter import ExistingOcrPipelineAdapter, VersionedOcrArtifactImporter

from .support import AppTestCase


class FoundationTests(AppTestCase):
    def test_schema_wal_and_all_required_tables(self):
        expected = {"documents","document_fields","document_lines","automation_runs","automation_events","audit_events","erp_ground_truth","document_links","line_links","supplier_product_aliases","layer_f_predictions","review_events"}
        with self.app.repository.connect() as connection:
            actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertTrue(expected.issubset(actual))

    def test_environment_isolation_and_identity_boundary(self):
        staging = build_profile("staging", self.root / "staging")
        production = build_profile("production", self.root / "production")
        assert_physical_isolation(staging, production)
        with self.assertRaises(DomainError):
            StagingIdentityProvider("dao1")
        with self.assertRaises(DomainError):
            type(self.app).bootstrap(environment="production", data_root=self.root / "blocked", reviewer_id="named")

    def test_immutable_source_and_hash_duplicate_open_existing(self):
        fixture = repository_root() / "tests/fixtures/ocr_top3/woothi"
        first = self.app.import_artifact(fixture / "invoice.svg", fixture / "artifact.json")
        second = self.app.import_artifact(fixture / "invoice.svg", fixture / "artifact.json")
        self.assertFalse(first["duplicate"]); self.assertTrue(second["duplicate"])
        self.assertEqual(first["document"]["id"], second["document"]["id"])
        self.assertTrue(any(event["action"] == "DUPLICATE_FILE_OPEN_EXISTING" for event in self.app.repository.list_audit_events(first["document"]["id"])))

    def test_existing_ocr_command_plan_names_all_layers_without_rewrite(self):
        adapter = ExistingOcrPipelineAdapter(Path("python"))
        plan = adapter.command_plan(Path("invoice.pdf"), Path("ocr_runs_staging"), Path("ocr_runs_staging/run"))
        self.assertIn("ocr_feasibility.py", plan.base_command[1])
        flags = [command[4] for command in plan.layer_commands]
        self.assertEqual(flags, ["--table-band-run-dir","--table-row-run-dir","--table-column-run-dir","--table-semantics-run-dir","--row-classification-run-dir","--layer-e-extract-run-dir"])

    def test_artifact_contract_rejects_non_scaled_money(self):
        payload = json.loads((repository_root()/"tests/fixtures/ocr_top3/woothi/artifact.json").read_text(encoding="utf-8"))
        payload["lines"][0]["unit_price_minor"] = 10.5
        with self.assertRaises(DomainError) as caught:
            VersionedOcrArtifactImporter().validate(payload)
        self.assertEqual(caught.exception.code, "OCR_MONEY_NOT_SCALED_INTEGER")

    def test_decimal_thai_numeral_date_and_exact_line_total(self):
        self.assertEqual(parse_decimal("๑,๒๓๔.๕๐"), parse_decimal("1234.50"))
        self.assertEqual(parse_thai_date("๒๒/๐๗/๒๕๖๙").isoformat(), "2026-07-22")
        self.assertEqual(line_total_minor("3", 5000), 15000)


class LearningPlaneTests(AppTestCase):
    def test_prediction_is_committed_before_dto_and_events_are_append_only(self):
        fixture = repository_root()/"tests/fixtures/ocr_top3/woothi"
        document_id = self.app.import_artifact(fixture/"invoice.svg", fixture/"artifact.json")["document"]["id"]
        dto = self.app.generate_predictions(document_id)
        self.assertEqual(len(dto), 3)
        line = self.app.repository.list_lines(document_id)[0]
        self.assertEqual(line["current_prediction_id"], dto[0]["prediction_id"])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.app.repository.transaction() as connection:
                connection.execute("UPDATE layer_f_predictions SET tier='X' WHERE id=?", (dto[0]["prediction_id"],))

    def test_repository_failure_cannot_return_unpersisted_prediction_dto(self):
        fixture = repository_root()/"tests/fixtures/ocr_top3/woothi"
        document_id = self.app.import_artifact(fixture/"invoice.svg", fixture/"artifact.json")["document"]["id"]
        document = self.app.repository.get_document(document_id); line = self.app.repository.list_lines(document_id)[0]
        with mock.patch.object(self.app.repository, "persist_prediction_before_display", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                self.app.matcher.predict_and_persist(document, line, {})

    def test_product_and_header_review_reference_rules(self):
        fixture = repository_root()/"tests/fixtures/ocr_top3/woothi"
        document_id = self.app.import_artifact(fixture/"invoice.svg", fixture/"artifact.json")["document"]["id"]
        predictions = self.app.generate_predictions(document_id)
        header_event = self.app.repository.review_header(document_id,"invoice_number","WOO-2026-0001","CONFIRM",None,120,self.app.actor,"test")
        line = self.app.repository.list_lines(document_id)[0]
        product_event = self.app.review_product(document_id,line["id"],predictions[0]["product_code"],predictions[0]["unit_code"],action="CONFIRM")
        self.assertIsNone(header_event["prediction_id"]); self.assertTrue(header_event["source_prediction_ref"])
        self.assertEqual(product_event["prediction_id"], predictions[0]["prediction_id"])
        with self.assertRaises(DomainError):
            self.app.review_product(document_id,line["id"],"NOT-IN-MASTER","BOX",action="CORRECT",error_category="OCR_ERROR")

    def test_correction_requires_category_and_revision_invalidates_ready(self):
        document_id = self.prepare_ready()
        before = self.app.repository.get_document(document_id)
        line = self.app.repository.list_lines(document_id)[0]
        with self.assertRaises(DomainError):
            self.app.review_line_value(document_id,line["id"],"quantity","4",action="CORRECT")
        self.app.review_line_value(document_id,line["id"],"quantity","2",action="CONFIRM")
        after = self.app.repository.get_document(document_id)
        self.assertGreater(after["revision"], before["revision"])
        self.assertEqual(after["status"], "NEEDS_REVIEW")
        self.assertIsNone(after["review_snapshot_hash"])

    def test_alias_distinct_document_gate_approval_and_conflict_quarantine(self):
        alias = None
        for document_id in ("doc-a","doc-b","doc-c"):
            alias = self.app.repository.record_alias_observation("WOOTHI","พารา 500","6300001",document_id,self.app.actor)
        self.assertEqual(alias["status"], "ELIGIBLE")
        active = self.app.repository.approve_alias(alias["id"], self.app.actor)
        self.assertEqual(active["status"], "ACTIVE")
        conflict = self.app.repository.record_alias_observation("WOOTHI","พารา 500","6300002","doc-d",self.app.actor)
        self.assertEqual(conflict["status"], "QUARANTINED")
        self.assertTrue(all(row["status"] == "QUARANTINED" for row in self.app.repository.list_aliases("WOOTHI")))

    def test_erp_and_alignment_fixture_writers_have_readers(self):
        document_id = self.prepare_ready()
        line = self.app.repository.list_lines(document_id)[0]
        erp_id = self.app.repository.write_erp_fixture({"supplier_code":"WOOTHI","receipt_number":"FIXTURE-001","line_sequence":1,"product_code":"6300001","product_name_as_entered":"พารา","quantity_decimal":"2","unit_code":"BOX","price_minor":10000,"source_kind":"FIXTURE"})
        self.app.repository.write_document_link(document_id,"FIXTURE-001","fixture_exact",{"signals":3},self.app.actor)
        self.app.repository.write_line_link(line["id"],erp_id,"fixture_exact",{"signals":3},self.app.actor)
        self.assertEqual(len(self.app.repository.list_erp_ground_truth()),1)
        self.assertEqual(len(self.app.repository.list_document_links()),1)
        self.assertEqual(len(self.app.repository.list_line_links()),1)

    def test_bulk_confirm_uses_one_interaction_duration_and_blocks_bad_line(self):
        fixture=repository_root()/"tests/fixtures/ocr_top3/woothi"
        document_id=self.app.import_artifact(fixture/"invoice.svg",fixture/"artifact.json")["document"]["id"]
        self.app.generate_predictions(document_id);self.app.confirm_headers(document_id)
        lines=self.app.repository.list_lines(document_id)
        with self.assertRaises(DomainError):self.app.bulk_confirm_products(document_id,[line["id"] for line in lines])
        events=self.app.bulk_confirm_products(document_id,[lines[0]["id"],lines[2]["id"]],duration_ms=900)
        self.assertEqual(len({event["interaction_id"] for event in events}),1)
        self.assertEqual(self.app.repository.metrics()["review_duration_ms"],1900)


class ValidationTests(AppTestCase):
    def test_exact_ready_row_count_total_and_revision_snapshot(self):
        document_id = self.prepare_ready()
        document = self.app.repository.get_document(document_id)
        result = self.app.validator.validate(document_id)
        self.assertTrue(result.ready)
        self.assertEqual(result.canonical_snapshot["row_count"],3)
        self.assertEqual(result.canonical_snapshot["grand_total_minor"],42500)
        self.assertEqual(result.snapshot_hash, document["review_snapshot_hash"])

    def test_line_total_mismatch_blocks_ready(self):
        document_id = self.prepare_ready()
        line = self.app.repository.list_lines(document_id)[0]
        self.app.review_line_value(document_id,line["id"],"quantity","9",action="CORRECT",error_category="QUANTITY_EXTRACTION_ERROR")
        result = self.app.validator.validate(document_id)
        self.assertFalse(result.ready)
        self.assertIn("LINE_TOTAL_MISMATCH", {issue.code for issue in result.issues})

    def test_business_duplicate_blocks_second_document(self):
        first = self.prepare_ready("woothi")
        fixture = repository_root()/"tests/fixtures/ocr_top3/woothi"
        copied = self.root/"different-source.svg"; copied.write_text((fixture/"invoice.svg").read_text(encoding="utf-8")+" ",encoding="utf-8")
        second = self.app.import_artifact(copied,fixture/"artifact.json")["document"]["id"]
        predictions=self.app.generate_predictions(second);self.app.confirm_headers(second)
        for line,prediction in zip(self.app.repository.list_lines(second),predictions):
            code="6300002" if line["sequence"]==2 else prediction["product_code"]
            if line["sequence"]==2:self.app.review_line_value(second,line["id"],"quantity","3",action="CORRECT",error_category="QUANTITY_EXTRACTION_ERROR")
            self.app.review_product(second,line["id"],code,"BOX",action="CORRECT" if line["sequence"]==2 else "CONFIRM",error_category="OCR_ERROR" if line["sequence"]==2 else None)
        result=self.app.validator.validate(second)
        self.assertIn("DUPLICATE_EXACT",{issue.code for issue in result.issues})
