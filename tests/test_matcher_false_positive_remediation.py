"""Track B -- matcher false-positive remediation (B1 guard + B2 suffix recovery).

The defect these tests lock down was reproduced against the REAL 6,671-row
production-derived cache on 2026-08-21:

    supplier_sku=None, description="CODIPHENTABLET(XIOS)"
      -> IC-002993 "BEDSIDE TABLE ABS 1 S" / FUZZY_SUGGESTION / 0.5000

The space between the trade name and the dosage form was lost, so trade-name
retrieval produced only the junk token "CODIPHENTABLET", nothing matched, and
the whole-catalog character-level SequenceMatcher sweep proposed an unrelated
piece of furniture on shared letters alone.

Two independently testable changes, proved separately below:

  B1  a fuzzy candidate needs meaningful shared trade-name token evidence;
      generic dosage-form/packaging/furniture overlap can never qualify alone.
      Insufficient evidence -> UNRESOLVED, never a different product.
  B2  a fused KNOWN dosage-form suffix is split back off before trade-name
      tokenization, for matching only -- OCR evidence is never rewritten.

Every prediction here goes through the pure `_predict()` boundary;
`predict_and_persist()` is never called, so nothing is written.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ocr_inbound import matching
from ocr_inbound.config import build_profile
from ocr_inbound.master_cache import refresh_master_cache
from ocr_inbound.matching import (
    _FUSED_DOSAGE_FORM_SUFFIXES,
    meaningful_shared_tokens,
    recover_fused_dosage_form,
)
from ocr_inbound.text_normalize import normalize_product_text

from tests.test_master_cache import FakePgSession, _row


class FusedDosageFormRecoveryTests(unittest.TestCase):
    """B2 -- a closed allowlist, applied at most once per token, never
    unrestricted dictionary segmentation."""

    def test_the_reproduced_defect_string_is_recovered(self):
        self.assertEqual(recover_fused_dosage_form("CODIPHENTABLET"), "CODIPHEN TABLET")
        self.assertEqual(recover_fused_dosage_form("CODIPHENTABLET XIOS"), "CODIPHEN TABLET XIOS")

    def test_every_allowlisted_suffix_splits(self):
        self.assertEqual(set(_FUSED_DOSAGE_FORM_SUFFIXES), {"TABLET", "CAPSULE", "SYRUP", "CREAM", "OINTMENT"})
        for word, expected in (
            ("CODIPHENTABLET", "CODIPHEN TABLET"),
            ("AMOXYCAPSULE", "AMOXY CAPSULE"),
            ("PARACETSYRUP", "PARACET SYRUP"),
            ("BETADINECREAM", "BETADINE CREAM"),
            ("ZINCOOINTMENT", "ZINCO OINTMENT"),
        ):
            with self.subTest(word=word):
                self.assertEqual(recover_fused_dosage_form(word), expected)

    def test_generic_words_ending_in_TABLE_are_never_split(self):
        # This is the whole safety point: TABLE is not a dosage form, and
        # splitting it is how a furniture product would be manufactured out of
        # thin air.
        for word in ("BEDSIDETABLE", "FOLDINGTABLE", "VEGETABLE", "OVERBEDTABLE", "TABLE", "TABLES"):
            with self.subTest(word=word):
                self.assertEqual(recover_fused_dosage_form(word), word)

    def test_near_miss_prefixes_too_short_to_be_evidence_are_not_split(self):
        # Splitting these would invent a 3-character "trade name" that is not
        # specific enough to retrieve on.
        for word in ("ICECREAM", "SUNCREAM"):
            with self.subTest(word=word):
                self.assertEqual(recover_fused_dosage_form(word), word)

    def test_a_bare_dosage_form_is_left_alone(self):
        for word in _FUSED_DOSAGE_FORM_SUFFIXES:
            with self.subTest(word=word):
                self.assertEqual(recover_fused_dosage_form(word), word)

    def test_only_one_split_per_token_no_recursive_segmentation(self):
        # "CODIPHENTABLETTABLET" yields exactly one split, not a cascade.
        self.assertEqual(recover_fused_dosage_form("CODIPHENTABLETTABLET"), "CODIPHENTABLET TABLET")

    def test_tokens_with_digits_and_thai_script_are_untouched(self):
        self.assertEqual(recover_fused_dosage_form("500MGTABLET"), "500MGTABLET")
        self.assertEqual(recover_fused_dosage_form("เม็ด"), "เม็ด")

    def test_empty_and_already_spaced_text_is_unchanged(self):
        self.assertEqual(recover_fused_dosage_form(""), "")
        self.assertEqual(recover_fused_dosage_form("CODIPHEN TABLET"), "CODIPHEN TABLET")


class FuzzyEvidenceGuardTests(unittest.TestCase):
    """B1 -- what counts as evidence, independent of any catalog."""

    def test_generic_furniture_and_dosage_overlap_is_not_evidence(self):
        source = normalize_product_text("UNKNOWN TABLET")
        candidate = normalize_product_text("BEDSIDE TABLE ABS 1 S")
        self.assertEqual(meaningful_shared_tokens(source, candidate), set())

    def test_a_real_shared_trade_name_token_is_evidence(self):
        source = normalize_product_text("CODIPHEN TABLET")
        candidate = normalize_product_text("CHUMCHON CODIPHEN DIPHENHYDRAMINE 50 MG 10 S")
        self.assertEqual(meaningful_shared_tokens(source, candidate), {"CODIPHEN"})

    def test_the_fused_token_is_not_evidence_until_recovery_runs(self):
        candidate = normalize_product_text("CHUMCHON CODIPHEN DIPHENHYDRAMINE 50 MG 10 S")
        fused = normalize_product_text("CODIPHENTABLET(XIOS)")
        self.assertEqual(meaningful_shared_tokens(fused, candidate), set())
        self.assertEqual(meaningful_shared_tokens(recover_fused_dosage_form(fused), candidate), {"CODIPHEN"})

    def test_furniture_still_matches_furniture_on_its_own_real_token(self):
        # The guard must not make legitimate non-drug products unmatchable:
        # BEDSIDE is a real, specific token and remains usable evidence.
        source = normalize_product_text("BEDSIDE TABLE")
        candidate = normalize_product_text("BEDSIDE TABLE ABS 1 S")
        self.assertEqual(meaningful_shared_tokens(source, candidate), {"BEDSIDE"})


class CodiphenFalsePositiveIntegrationTests(unittest.TestCase):
    """The reproduced defect, end to end, against a cache containing BOTH the
    right product and the wrong one that used to win."""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory(prefix="ocr-trackb-")
        cls.profile = build_profile("staging", Path(cls._temp.name))
        rows = [
            _row("IC-001962", "เภสัช โคดิเฟน 50 มก 10 เม็ด", "CHUMCHON CODIPHEN DIPHENHYDRAMINE 50 MG 10 S", "8853144321324", "แผง"),
            _row("IC-002993", "สามัญ โต๊ะพาดเตียง ABS 1 ชิ้น", "BEDSIDE TABLE ABS 1 S", "9999900082517", "ตัว"),
            _row("IC-002022", None, "FOLDING TABLE D-WOODEN : S-120601D.W", None, "ตัว"),
            _row("630020259", None, "V GIFF TABLET 30 S", None, "กล่อง"),
        ]
        refresh_master_cache(cls.profile, session=FakePgSession(rows=rows), min_products=1, max_products=10)
        from ocr_inbound.service import Application

        cls.app = Application.bootstrap(data_root=cls.profile.root)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def _predict(self, supplier_sku, description):
        line = {
            "id": "TRACKB-LINE",
            "supplier_sku": supplier_sku,
            "description_final": description,
            "raw_ocr_text": description,
            "unit_final": "แผง",
            "evidence_json": "{}",
        }
        prediction = self.app.matcher._predict({"id": "TRACKB", "supplier_code": "SUPPLIER-COMMUNITY-PHARMACY"}, line, {})
        return prediction, line

    def _without_recovery(self):
        """Disables ONLY B2, leaving the B1 guard live -- the middle column of
        the staged proof."""
        original = matching.recover_fused_dosage_form
        matching.recover_fused_dosage_form = lambda text: text
        self.addCleanup(lambda: setattr(matching, "recover_fused_dosage_form", original))

    # --- staged proof ----------------------------------------------------
    def test_guard_only_returns_unresolved_and_never_another_product(self):
        self._without_recovery()
        prediction, _ = self._predict(None, "CODIPHENTABLET(XIOS)")
        self.assertEqual(prediction["tier"], "UNRESOLVED")
        self.assertIsNone(prediction["proposed_product_code"])
        self.assertNotIn("IC-002993", str(prediction["candidate_set"]))

    def test_final_resolves_the_fused_row_to_codiphen_requiring_human_confirmation(self):
        prediction, line = self._predict(None, "CODIPHENTABLET(XIOS)")
        self.assertEqual(prediction["proposed_product_code"], "IC-001962")
        self.assertEqual(prediction["tier"], "TRADE_NAME_MATCH")
        self.assertTrue(prediction["provenance"]["human_confirmation_required"])
        self.assertNotIn(prediction["tier"], {"EXACT_CODE", "EXACT_BARCODE", "ACTIVE_ALIAS", "SPELLING_ALIAS"})
        # Row 2 carries no supplier SKU and must never inherit Row 1's.
        self.assertIsNone(line["supplier_sku"])
        self.assertNotIn("32132", prediction["source_text"])

    def test_spaced_row_with_supplier_sku_is_unchanged(self):
        prediction, line = self._predict("32132", "CODIPHEN TABLET(XIOS)")
        self.assertEqual(prediction["proposed_product_code"], "IC-001962")
        self.assertEqual(prediction["tier"], "TRADE_NAME_MATCH")
        self.assertEqual(line["supplier_sku"], "32132")

    def test_clean_control_is_unchanged(self):
        prediction, _ = self._predict(None, "CODIPHEN TABLET (1X10'S)")
        self.assertEqual(prediction["proposed_product_code"], "IC-001962")
        self.assertEqual(prediction["tier"], "TRADE_NAME_MATCH")

    def test_unknown_tablet_never_suggests_bedside_table(self):
        prediction, _ = self._predict(None, "UNKNOWN TABLET")
        self.assertEqual(prediction["tier"], "UNRESOLVED")
        self.assertIsNone(prediction["proposed_product_code"])
        self.assertNotIn("IC-002993", str(prediction["candidate_set"]))

    def test_recovery_never_rewrites_the_stored_ocr_evidence(self):
        prediction, _ = self._predict(None, "CODIPHENTABLET(XIOS)")
        # The audit fields keep the ORIGINAL fused text, exactly as OCR read it.
        self.assertIn("CODIPHENTABLET", prediction["source_text"])
        self.assertIn("CODIPHENTABLET", prediction["normalized_text"])
        self.assertNotIn("CODIPHEN TABLET", prediction["normalized_text"])

    def test_a_genuine_furniture_line_still_resolves(self):
        # The guard must not have made non-drug products unmatchable.
        prediction, _ = self._predict(None, "BEDSIDE TABLE ABS 1 S")
        self.assertEqual(prediction["proposed_product_code"], "IC-002993")


if __name__ == "__main__":
    unittest.main()
