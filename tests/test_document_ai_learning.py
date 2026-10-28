"""Model-free checks: no optimizer/fitting, OCR or live database access."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ocr_inbound.document_ai.learning import (
    FEATURES, ProductMatcher, evaluate, file_sha256, group_split, require_hq, specifications)

_spec = importlib.util.spec_from_file_location("document_ai_prepare_teacher", Path(__file__).parents[1] / "scripts/document_ai_prepare_teacher.py")
teacher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(teacher)


CATALOG = [
    {"code": "A", "names": ["ACME antihistamine tablet 10mg 20 s"], "barcodes": ["8850000000001"]},
    {"code": "B", "names": ["ACME antihistamine tablet 20mg 20 s"], "barcodes": ["8850000000002"]},
    {"code": "C", "names": ["ACME antihistamine cream 10mg 20 s"], "barcodes": []},
    {"code": "D", "names": ["ACME antihistamine tablet 10mg 100 s"], "barcodes": []},
]


class ProductMatcherTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ProductMatcher(CATALOG)

    def test_correct_strength_form_and_pack_rank_first(self):
        result = self.matcher.match({"description": "ACME antihistamine tablet 10mg 20 s"})
        self.assertEqual(result["proposed_code"], "A")
        self.assertTrue(result["review_required"])
        self.assertFalse(result["production_ready"])

    def test_semantic_hard_negative_explanations(self):
        query = {"description": "ACME antihistamine tablet 10mg 20 s"}
        candidates = {c["code"]: c for c in self.matcher.retrieve(query)}
        self.assertIn("strength_conflict", candidates["B"]["blocks"])
        self.assertIn("form_conflict", candidates["C"]["blocks"])
        self.assertIn("pack_conflict", candidates["D"]["blocks"])
        self.assertEqual(list(candidates["A"]["features"]), list(FEATURES))

    def test_unknown_description_abstains(self):
        self.assertEqual(self.matcher.match({"description": "alien spacecraft replacement"})["status"], "ABSTAIN")

    def test_catalogue_absence_cannot_be_overridden_by_similar_name(self):
        result = self.matcher.match({"description": CATALOG[0]["names"][0], "catalogue_pending": True})
        self.assertIsNone(result["proposed_code"])
        self.assertIn("known_catalogue_absence_or_new_item", result["reasons"])

    def test_exact_barcode_still_respects_strength_conflict(self):
        result = self.matcher.match({"description": "ACME tablet 20mg", "barcode": "8850000000001",
                                     "identifier_evidence": "source_exact"})
        self.assertIsNone(result["proposed_code"])
        self.assertIn("strength_conflict", result["reasons"])

    def test_supplier_code_never_becomes_internal_identifier(self):
        result = self.matcher.match({"description": "", "supplier_code": "A"})
        self.assertIsNone(result["proposed_code"])

    def test_exact_code_barcode_disagreement_abstains(self):
        result = self.matcher.match({"description": "ACME antihistamine tablet 10mg 20 s", "company_code": "A",
                                    "barcode": "8850000000002", "identifier_evidence": "source_exact"})
        self.assertIn("conflicting_or_nonunique_exact_identifiers", result["reasons"])

    def test_nonunique_barcode_abstains(self):
        matcher = ProductMatcher([CATALOG[0], dict(CATALOG[1], barcodes=CATALOG[0]["barcodes"])])
        self.assertEqual(matcher.match({"barcode": "8850000000001", "identifier_evidence": "source_exact"})["status"], "ABSTAIN")

    def test_untrusted_barcode_never_forces_candidate(self):
        result = self.matcher.match({"description": "unrelated xyz", "barcode": "8850000000001"})
        self.assertIsNone(result["proposed_code"])

    def test_duplicate_catalogue_rejected(self):
        with self.assertRaises(ValueError):
            ProductMatcher([CATALOG[0], CATALOG[0]])

    def test_model_contract_rejected(self):
        with self.assertRaises(ValueError):
            ProductMatcher(CATALOG, {"schema": "wrong"})

    def test_mcg_mg_are_unit_converted_not_interchangeable(self):
        self.assertEqual(specifications("100 mcg")["strength"], specifications("0.1 mg")["strength"])
        self.assertNotEqual(specifications("100 mcg")["strength"], specifications("100 mg")["strength"])


def fact(row_id="r1", source="source1", invoice="invoice1", code="A"):
    return {"id": row_id, "source_sha256": source, "source_file": source + ".jpg", "supplier_layout_key": "supplier",
            "source_group_id": row_id, "company_sku": code, "sku_match_status": "STRONG_CANDIDATE",
            "receipt_header": {"FTXihRefExt": invoice},
            "receipt_match_evidence": {"receipt_line": {"FTPdtCode": code}, "specification_conflicts": []},
            "scan_row": {"fields": {"description": {"engine": "ASSISTANT_VISUAL", "raw_value": "saved proposal",
                "raw_ocr_field": {"raw_value": "ACME tablet 10mg", "engine": "PADDLE_TH", "token_ids": ["p:1"]}}}}}


class TeacherManifestTests(unittest.TestCase):
    def test_uses_machine_raw_instead_of_saved_visual_proposal(self):
        examples = teacher.build_examples([fact()], {}, {}, CATALOG)
        self.assertEqual(examples[0]["query"]["description"], "ACME tablet 10mg")
        self.assertEqual(examples[0]["printed_source_proposal"]["description"], "saved proposal")
        self.assertFalse(examples[0]["glyph_training_eligible"])
        self.assertEqual(examples[0]["authority"], "receipt_corroborated_llm_silver")

    def test_unconfirmed_proposal_excluded(self):
        row = fact()
        row["sku_match_status"] = "HIGH_MASTER_NAME_CANDIDATE"
        self.assertFalse(teacher.build_examples([row], {}, {}, CATALOG)[0]["eligible"])

    def test_missing_machine_raw_excluded(self):
        row = fact()
        del row["scan_row"]["fields"]["description"]["raw_ocr_field"]
        self.assertEqual(teacher.build_examples([row], {}, {}, CATALOG)[0]["eligibility_reason"], "no_machine_description_evidence")

    def test_receipt_code_disagreement_excluded(self):
        row = fact()
        row["receipt_match_evidence"]["receipt_line"]["FTPdtCode"] = "B"
        self.assertFalse(teacher.build_examples([row], {}, {}, CATALOG)[0]["eligible"])

    def test_invoice_and_source_transitive_components_do_not_leak(self):
        rows = [fact("a", "source1", "invoice1"), fact("b", "source2", "invoice1"),
                fact("c", "source2", "invoice2"), fact("d", "source3", "invoice2")]
        examples = teacher.build_examples(rows, {}, {}, CATALOG)
        self.assertEqual(len({e["dependency_group"] for e in examples}), 1)
        self.assertEqual(len({e["split"] for e in examples}), 1)
        self.assertEqual(group_split(examples[0]["dependency_group"]), examples[0]["split"])

    def test_shared_source_event_conflicts_quarantined(self):
        a, b = fact("a"), fact("b", code="B")
        a["source_group_id"] = b["source_group_id"] = "sameevent"
        result = teacher.build_examples([a, b], {}, {}, CATALOG)
        self.assertTrue(all(not e["eligible"] for e in result))

    def test_user_identity_does_not_approve_full_row(self):
        row = fact()
        row["sku_match_status"] = "USER_CONFIRMED_ROW_SCOPED_PRODUCT_IDENTITY"
        e = teacher.build_examples([row], {}, {}, CATALOG)[0]
        self.assertEqual(e["authority"], "user_row_identity_only")
        self.assertFalse(e["human_whole_row_verified"])

    def test_unknown_control_evaluated_separately(self):
        row = fact()
        row["catalogue_pending_excluded"] = True
        e = teacher.build_examples([row], {}, {}, CATALOG)[0]
        report = evaluate(ProductMatcher(CATALOG), [e])
        self.assertEqual(report["split_metrics"][e["split"]]["unknown_false_accept"], 0)
        self.assertEqual(report["split_metrics"][e["split"]]["unknown_examples"], 1)

    def test_manifest_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            teacher.write_new(path / "catalogue.json", CATALOG)
            teacher.write_new(path / "examples.json", [])
            teacher.write_new(path / "manifest.json", {"outputs": {"catalogue.json": file_sha256(path / "catalogue.json"),
                "examples.json": file_sha256(path / "examples.json")}, "split_groups": {"train": [], "validation": [], "test": []}})
            teacher.load_frozen(path)
            (path / "catalogue.json").write_text("[]")
            with self.assertRaises(ValueError):
                teacher.load_frozen(path)

    def test_hq_gate_refuses_laptop_without_fitting(self):
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("192.168.1.2", 0))]), patch("os.name", "posix"):
            with self.assertRaises(RuntimeError):
                require_hq()

    def test_atomic_output_is_exclusive_and_fsynced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            with patch.object(teacher.os, "fsync", wraps=teacher.os.fsync) as sync:
                teacher.write_new(path, {"weights": [1., 2.]})
                self.assertTrue(sync.called)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                teacher.write_new(path, {"weights": [3.]})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_failed_serialization_never_publishes_partial_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            with self.assertRaises(ValueError):
                teacher.write_new(path, {"weights": [float("nan")]})
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_checkpoint_callback_records_only_supplied_actual_progress_without_fitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "checkpoints"
            publish = teacher.checkpoint_writer(folder, {"manifest_sha256": "frozen"})
            sample = {"final": False, "actual_updates": 256, "actual_pairs": 256, "actual_examples": 32,
                      "completed_epochs": 0, "training_example_ids": ["train-1"], "all_weights_finite": True,
                      "weights": [1., 2.]}
            publish(sample)
            publish(dict(sample, final=True, actual_updates=300, actual_pairs=300, completed_epochs=1))
            records = [json.loads(line) for line in (folder / "trace.jsonl").read_text().splitlines()]
            self.assertEqual([r["actual_updates"] for r in records], [256, 300])
            self.assertEqual(records[0]["training_example_ids"], ["train-1"])
            for record in records:
                self.assertEqual(file_sha256(folder / record["checkpoint"]), record["sha256"])
            with self.assertRaises(FileExistsError):
                teacher.checkpoint_writer(folder, {})


if __name__ == "__main__":
    unittest.main()
