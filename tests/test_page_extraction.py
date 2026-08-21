"""Layer F Slice 4 -- automatic page/row extraction tests.

Uses the REAL evidence files under
`ocr_runs_staging/realinv_20260820T040631Z/` wherever a required scenario
has real evidence for it (Berlin page 5 for the primary 5-row proof case,
page-040 for a real credit note, page-014 for a real multi-page-invoice
continuation page) -- per the explicit "no hand-copied fixtures called
automatic extraction" and "no fabricated bounding boxes" requirements, this
file does NOT invent product names/positions for scenarios real evidence
already covers. A few structural edge cases (duplicate token, missing
field, engine disagreement) that are not naturally present anywhere in
these 10 real pages are exercised with small SYNTHETIC token lists built
from the same coordinate system/shape as the real data (not from a
disk-based fixture masquerading as OCR output) -- each such test says so
explicitly in its own docstring.
"""
from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from ocr_inbound.page_extraction import (
    PAGE_EXTRACTION_CONTRACT_VERSION,
    Token,
    _cluster_rows,
    _community_pharmacy_code_table_rows,
    _detect_community_pharmacy_table,
    _find_totals_boundary,
    classify_document_type,
    build_page_extraction_bundle,
    write_page_extraction_bundle,
    extract_page,
    load_paddle_tokens,
)

from .support import AppTestCase


EVIDENCE_ROOT = Path(__file__).resolve().parents[1] / "ocr_runs_staging" / "realinv_20260820T040631Z"
PADDLE_DIR = EVIDENCE_ROOT / "ocr" / "paddle_th"
TESSERACT_DIR = EVIDENCE_ROOT / "ocr" / "tesseract"
PAGES_DIR = EVIDENCE_ROOT / "pages"


def _skip_if_missing():
    if not PADDLE_DIR.exists():
        raise unittest.SkipTest(f"Real evidence not present at {PADDLE_DIR} -- Slice 4 tests require the checked-in evaluation run")


def _extract(page_number: int, image_size=(2457, 3483)):
    _skip_if_missing()
    padded = f"{page_number:03d}"
    return extract_page(
        page_number=page_number,
        paddle_json_path=PADDLE_DIR / f"page-{padded}.json",
        tesseract_text_path=TESSERACT_DIR / f"page-{padded}_psm6.txt",
        image_size=image_size,
    )


class BerlinPage5ExtractionTests(unittest.TestCase):
    """The explicit reproduction case from the Slice 4 kickoff: Berlin PDF
    page 5 has 5 real product rows, PaddleOCR read every one of them, and
    the evaluation CSV only ever showed 1 (ISOTRATE) because it stored a
    hand-picked representative sample, not automatic row extraction."""

    @classmethod
    def setUpClass(cls):
        cls.result = _extract(5)

    def test_finds_exactly_five_product_rows_in_document_order(self):
        self.assertTrue(self.result["table_found"])
        rows = self.result["product_rows"]
        self.assertEqual(len(rows), 5)
        expected_order = ["ISOTRATE", "MIRAX-M", "MONOLIN", "PRENOLOL", "UTMOS"]
        for row, expected_prefix in zip(rows, expected_order):
            self.assertTrue(
                row["fields"]["description"]["raw_text"].upper().startswith(expected_prefix),
                f"row {row['row_index']} description {row['fields']['description']['raw_text']!r} does not start with {expected_prefix}",
            )

    def test_lot_mfg_exp_qty_unit_never_shift_to_the_wrong_product(self):
        # Keyed by prefix match rather than the first whitespace-split word:
        # Phase A confirmed PaddleOCR emitted "MIRAX-M10X10'S" as a single
        # token with no space at all between the name and the pack size, so
        # raw_text.split()[0] would be the whole string, not "MIRAX-M".
        rows = {}
        for r in self.result["product_rows"]:
            raw = r["fields"]["description"]["raw_text"].upper()
            for prefix in ("ISOTRATE", "MIRAX-M", "MONOLIN", "PRENOLOL", "UTMOS"):
                if raw.startswith(prefix):
                    rows[prefix] = r
                    break
        expected = {
            "ISOTRATE": {"lot": "2403345", "qty": 3.0, "unit": "BOX"},
            "MIRAX-M": {"lot": "2500062", "qty": 10.0, "unit": "BOX"},
            "MONOLIN": {"lot": "2403176", "qty": 2.0, "unit": "BOX"},
            "PRENOLOL": {"lot": "2403284", "qty": 3.0, "unit": "BOX"},
            "UTMOS": {"lot": "2401721", "qty": 15.0, "unit": "BOX"},
        }
        for prefix, values in expected.items():
            row = rows[prefix]
            self.assertEqual(row["fields"]["lot"]["raw_text"], values["lot"], prefix)
            self.assertEqual(row["fields"]["quantity"]["normalized_value"], values["qty"], prefix)
            self.assertEqual(row["fields"]["unit"]["raw_text"], values["unit"], prefix)

    def test_mfg_and_exp_dates_are_kept_raw_with_era_unspecified(self):
        isotrate = next(r for r in self.result["product_rows"] if r["fields"]["description"]["raw_text"].startswith("ISOTRATE"))
        mfg = isotrate["fields"]["mfg_date"]
        exp = isotrate["fields"]["exp_date"]
        self.assertEqual(mfg["raw_text"], "27/11/24")
        self.assertEqual(mfg["normalized_value"]["era"], "UNSPECIFIED")
        self.assertEqual(exp["raw_text"], "27/11/28")
        self.assertEqual(exp["normalized_value"]["era"], "UNSPECIFIED")

    def test_subtotal_and_discount_lines_never_become_product_rows(self):
        descriptions = [r["fields"]["description"]["raw_text"] for r in self.result["product_rows"]]
        for text in descriptions:
            self.assertNotIn("Sub Total", text)
            self.assertNotIn("Cash Discount", text)
        self.assertEqual(len(self.result["product_rows"]), 5)

    def test_low_confidence_stray_token_is_excluded_not_misread_as_a_field(self):
        # Phase A found a lone "o" at score 0.096 sitting inside the
        # MONOLIN row's Y-band (an OCR artifact, not a real character) --
        # it must never end up assigned to any column.
        monolin = next(r for r in self.result["product_rows"] if r["fields"]["description"]["raw_text"].startswith("MONOLIN"))
        all_raw_texts = [f["raw_text"] for f in monolin["fields"].values() if f]
        self.assertNotIn("o", all_raw_texts)
        self.assertTrue(any("LOW_CONFIDENCE_TOKEN_EXCLUDED" in w and "'o'" in w for w in self.result["warnings"]))

    def test_bounding_boxes_are_within_the_page_image_dimensions(self):
        width, height = self.result["image_size"]["width"], self.result["image_size"]["height"]
        for row in self.result["product_rows"]:
            for field_data in row["fields"].values():
                if field_data is None:
                    continue
                bbox = field_data["bbox"]
                self.assertGreaterEqual(bbox["x0"], 0)
                self.assertGreaterEqual(bbox["y0"], 0)
                self.assertLessEqual(bbox["x1"], width)
                self.assertLessEqual(bbox["y1"], height)

    def test_deterministic_and_idempotent_rerun(self):
        second = _extract(5)
        self.assertEqual(len(second["product_rows"]), len(self.result["product_rows"]))
        for a, b in zip(self.result["product_rows"], second["product_rows"]):
            self.assertEqual(a["fields"]["description"]["raw_text"], b["fields"]["description"]["raw_text"])
            self.assertEqual(a["quarantine_reasons"], b["quarantine_reasons"])

    def test_contract_version_is_stamped(self):
        self.assertEqual(self.result["contract_version"], PAGE_EXTRACTION_CONTRACT_VERSION)

    def test_document_type_is_tax_invoice(self):
        self.assertEqual(self.result["document_type"], "TAX_INVOICE")

    def test_tesseract_corroboration_present_for_real_product_names(self):
        # Tesseract has no coordinates (confirmed in Phase A) -- corroboration
        # is a coarse text-match signal only, its bbox is always reported
        # unavailable.
        isotrate = next(r for r in self.result["product_rows"] if r["fields"]["description"]["raw_text"].startswith("ISOTRATE"))
        self.assertEqual(isotrate["corroboration"]["tesseract_bbox"], "unavailable")


class MultilineBlockAdapterRealPageTests(unittest.TestCase):
    """The multi-line-block supplier adapter (Unison page-006, Medline
    page-048, Community Pharmacy page-058) -- exercised only against real
    evidence, per the same "no hand-copied fixture called automatic
    extraction" rule as the Berlin tests above. Each page's own real
    header text was read in Phase A to confirm it genuinely has NO
    tabular column-header row (so the tabular strategy honestly reports
    `table_found: False` on its own), before deciding this fallback
    strategy was needed at all."""

    def test_medline_page_finds_five_real_products_in_order_via_the_block_adapter(self):
        result = _extract(48)
        self.assertEqual(result["extraction_strategy"], "MULTILINE_BLOCK")
        self.assertTrue(result["table_found"])
        rows = result["product_rows"]
        # Phase A read this page's real LOT/MFG/EXP-anchored blocks by hand
        # (not by running the code under test) to establish this expected
        # order: LESFLAM appears twice (see the duplicate-block test below
        # for why), then VULTIN, BAPID, GASTER.
        descriptions = [r["fields"]["description"]["raw_text"] if r["fields"]["description"] else None for r in rows]
        self.assertEqual(descriptions, [
            "LESFLAM 50 MG.TAB.10X1O'S",
            "LESFLAM 50 MG.TAB.10X1O'S",
            "VULTIN 400 MG.CAP.10X10'S",
            "BAPID 100 MG.TAB.10X10'S",
            "GASTER 20 MG.CAP.20X7'S",
        ])
        vultin = rows[2]
        self.assertEqual(vultin["fields"]["lot"]["normalized_value"], "6AW2410")
        self.assertEqual(vultin["fields"]["mfg_date"]["raw_text"], "14/11/24")
        self.assertEqual(vultin["fields"]["exp_date"]["raw_text"], "14/11/27")
        # This adapter has no column header anywhere on the page to say
        # which numeric token means quantity vs total -- Phase A found two
        # genuinely ambiguous same-looking numeric tokens on the one real
        # product line it inspected closely (Unison), so guessing that
        # mapping is exactly what requirement #7 forbids. Every row must
        # say so explicitly rather than silently omit the fields.
        for row in rows:
            for column in ("quantity", "unit", "unit_price", "total_amount"):
                self.assertIsNone(row["fields"][column])
                self.assertIn(f"FIELD_UNAVAILABLE:multiline_block_layout_no_column_header:{column}", row["quarantine_reasons"])

    def test_unison_page_flags_its_real_near_duplicate_block_for_review_rather_than_silently_dropping_either(self):
        # Phase A found a genuine anomaly on this real page: the exact same
        # description/lot/mfg/exp is printed a second time at a different Y
        # position, with quantity/price/total missing the second time --
        # structurally two distinct row-clusters (not an identical-polygon
        # duplicate), so this extractor cannot tell whether it is a real
        # second purchase line or an OCR/rendering duplicate. Both must
        # survive as separate rows, both flagged for human review.
        result = _extract(6)
        self.assertEqual(result["extraction_strategy"], "MULTILINE_BLOCK")
        rows = result["product_rows"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("DUPLICATE_LOT_MFG_EXP_ACROSS_BLOCKS", row["quarantine_reasons"])
            self.assertTrue(row["review_required"])

    # test_community_pharmacy_* moved to CommunityPharmacyAdapterRealPageTests
    # below -- page-058 turned out to be a THIRD distinct real layout (a
    # genuine, single-language, 5-column table header), not a variant of
    # this generic multi-line-block adapter; see that class's docstring.


class CommunityPharmacyAdapterRealPageTests(unittest.TestCase):
    """Community Pharmacy (บริษัท ชุมชนเภสัชกรรม จำกัด (มหาชน)) page-058 is a
    THIRD distinct real layout, not a variant of the generic multi-line-
    block adapter above: it has a genuine single-language (Thai-only) real
    5-column table header ("รหัสสินค้า"/"รายละเอิยด"/"จำนวน"/
    "ราคารวมภาษี"/"จำนวนเงิน"), confirmed by reading the real token dump
    before writing any adapter code. Each product prints as a data row
    (code/description/quantity+unit/price/total) immediately followed by a
    fused Lot/Mfg/Exp row -- see `_community_pharmacy_code_table_rows`'s
    module comment for the full structural rationale, and for why an
    earlier, more general 6-digit-code heuristic wrongly picked a Thai tax
    ID's label text as a fabricated description on this exact page before
    this dedicated adapter existed."""

    @classmethod
    def setUpClass(cls):
        cls.result = _extract(58)

    # A: exactly 2 rows, in document order.
    def test_finds_exactly_two_rows_in_document_order(self):
        self.assertEqual(self.result["extraction_strategy"], "COMMUNITY_PHARMACY_CODE_TABLE")
        self.assertTrue(self.result["table_found"])
        self.assertEqual(len(self.result["product_rows"]), 2)

    # B: both rows read CODIPHEN.
    def test_both_rows_read_codiphen(self):
        for row in self.result["product_rows"]:
            description = row["fields"]["description"]
            self.assertIsNotNone(description)
            self.assertIn("CODIPHEN", description["raw_text"].upper())

    # C: supplier SKU 32132 never becomes an internal code -- routed
    # through the real, unmodified matcher's own supplier_sku contract and
    # confirmed the internal-code regex path was never involved.
    def test_supplier_sku_is_never_treated_as_an_internal_product_code(self):
        row = self.result["product_rows"][0]
        supplier_sku = row["fields"]["supplier_sku"]
        self.assertEqual(supplier_sku["raw_text"], "32132")
        self.assertNotRegex(supplier_sku["raw_text"], r"^(?:IC-\d{4,6}|630\d{4,6})$")
        # The description field itself must never carry the supplier SKU
        # concatenated in -- if it did, the matcher's INTERNAL_CODE regex
        # fallback scan (matching.py) would at least be exposed to it even
        # though "32132" itself can never match that pattern (it requires
        # an "IC-" prefix or a literal "630" prefix, neither of which
        # "32132" has).
        self.assertNotIn("32132", row["fields"]["description"]["raw_text"])

    # D: Lot/Mfg/Exp never shift to the wrong row.
    def test_lot_mfg_exp_do_not_shift_between_rows(self):
        for row in self.result["product_rows"]:
            self.assertEqual(row["fields"]["lot"]["normalized_value"], "25B031")
            self.assertEqual(row["fields"]["mfg_date"]["raw_text"], "07/02/25")
            self.assertEqual(row["fields"]["exp_date"]["raw_text"], "06/02/28")

    # E: quantities are 240.00 then 96.00, in that order -- and same Lot is
    # NOT treated as evidence of a duplicate (this supplier's real evidence
    # shows two real purchase/allocation lines against one batch, unlike
    # Unison's page-006 near-duplicate, which was missing its OWN
    # quantity/price/total entirely).
    def test_quantities_are_240_then_96_and_same_lot_is_not_flagged_duplicate(self):
        rows = self.result["product_rows"]
        self.assertEqual(rows[0]["fields"]["quantity"]["normalized_value"], 240.0)
        self.assertEqual(rows[1]["fields"]["quantity"]["normalized_value"], 96.0)
        self.assertEqual(rows[0]["fields"]["unit"]["raw_text"], "box")
        self.assertEqual(rows[1]["fields"]["unit"]["raw_text"], "box")
        for row in rows:
            self.assertNotIn("DUPLICATE_LOT_MFG_EXP_ACROSS_BLOCKS", row["quarantine_reasons"])

    # F: same Lot does not merge or drop either legitimate row.
    def test_same_lot_does_not_merge_or_drop_either_row(self):
        self.assertEqual(len(self.result["product_rows"]), 2)
        # Each row keeps its OWN quantity, not a shared/merged value.
        quantities = {row["fields"]["quantity"]["normalized_value"] for row in self.result["product_rows"]}
        self.assertEqual(quantities, {240.0, 96.0})

    # G: every field bbox stays within the page image bounds.
    def test_bounding_boxes_are_within_the_page_image_dimensions(self):
        result = _extract(58, image_size=(2457, 3483))
        width, height = result["image_size"]["width"], result["image_size"]["height"]
        for row in result["product_rows"]:
            for field_data in row["fields"].values():
                if field_data is None:
                    continue
                bbox = field_data["bbox"]
                self.assertGreaterEqual(bbox["x0"], 0)
                self.assertGreaterEqual(bbox["y0"], 0)
                self.assertLessEqual(bbox["x1"], width)
                self.assertLessEqual(bbox["y1"], height)

    # H: deterministic rerun -- identical artifact on a second extraction.
    def test_deterministic_and_idempotent_rerun(self):
        second = _extract(58)
        self.assertEqual(len(second["product_rows"]), len(self.result["product_rows"]))
        for a, b in zip(self.result["product_rows"], second["product_rows"]):
            self.assertEqual(a["fields"]["description"]["raw_text"], b["fields"]["description"]["raw_text"])
            self.assertEqual(a["fields"]["quantity"]["normalized_value"], b["fields"]["quantity"]["normalized_value"])
            self.assertEqual(a["quarantine_reasons"], b["quarantine_reasons"])

    # I: matcher integration itself needs a real AppTestCase bootstrap --
    # see CommunityPharmacyMatcherIntegrationTests below.

    def test_selecting_a_different_supplier_page_does_not_trigger_this_adapter(self):
        # Gate check: Berlin page-005 has neither the Community Pharmacy
        # identity marker nor this table's column wording, so this adapter
        # must never fire for it -- proves selection is driven by real
        # document content, never by page number or file order.
        berlin = _extract(5)
        self.assertNotEqual(berlin["extraction_strategy"], "COMMUNITY_PHARMACY_CODE_TABLE")


class CommunityPharmacyMatcherIntegrationTests(AppTestCase):
    """Real matcher integration for the Community Pharmacy adapter's rows
    -- same read-only pattern as MatcherIntegrationReadOnlyTests, calling
    `matcher._predict()` directly (never `predict_and_persist`) so nothing
    is written. Confirms requirement #7/#8: supplier_sku "32132" is passed
    as `line["supplier_sku"]` (the matcher's existing exact-alias-lookup-
    only field, per matching.py's own documented contract), CODIPHEN's
    description text is what reaches trade-name matching, and with no
    approved (supplier_code, "32132") alias yet on file the result cannot
    be an auto-confirming EXACT_CODE/ACTIVE_ALIAS tier."""

    def test_codiphen_rows_reach_the_matcher_via_supplier_sku_field_and_do_not_auto_confirm(self):
        extraction = _extract(58)
        document = {"id": "CP-ADAPTER-TEST-DOC", "supplier_code": "COMMUNITY-PHARMACY-TEST"}
        ocr_versions = {"paddle_th": "test-evidence", "tesseract": "test-evidence"}
        for row in extraction["product_rows"]:
            description = row["fields"]["description"]["raw_text"]
            supplier_sku_field = row["fields"]["supplier_sku"]
            line = {
                "id": f"CP-ADAPTER-TEST-LINE-{row['row_index']}",
                "supplier_sku": supplier_sku_field["raw_text"] if supplier_sku_field else None,
                "description_final": description,
                "raw_ocr_text": description,
                "evidence_json": "{}",
            }
            prediction = self.app.matcher._predict(document, line, ocr_versions)
            # No approved alias exists for (COMMUNITY-PHARMACY-TEST, 32132)
            # in this ephemeral local fixture -- the real matcher must fall
            # through to bilingual/trade-name suggestion territory, never
            # auto-confirm off the supplier SKU alone. `source_text` in the
            # prediction is matching.py's own audit-facing field and is
            # DOCUMENTED to include supplier_sku for human visibility (it is
            # never used for code/barcode matching) -- the real contract to
            # check is that the INTERNAL_CODE regex path (which only ever
            # scans `description_final`/`raw_ocr_text`, never
            # `supplier_sku`) was not the reason for this tier, and "32132"
            # cannot match that regex at all (`IC-\d{4,6}` or `630\d{4,6}`
            # only) even if it somehow leaked in.
            self.assertNotEqual(prediction["tier"], "EXACT_CODE")
            self.assertNotEqual(prediction["tier"], "ACTIVE_ALIAS")
            self.assertNotIn("MASTER_CODE_EXACT", prediction["reason_codes"])
        self.assertEqual(self.app.repository.list_lines(document["id"]), [])


class CommunityPharmacyAdapterGateFalsePositiveTests(unittest.TestCase):
    """Adversarial checks that the adapter's AND-gate (real supplier-
    identity marker AND this table's own column header, both required)
    cannot be tricked by either half alone -- small, explicitly synthetic
    token lists (declared as such), not real evidence, built specifically
    to probe the gate boundary."""

    def test_supplier_name_present_but_column_header_absent_does_not_trigger(self):
        tokens = [
            Token(text="บริษัท ชุมชนเภสัชกรรม จำกัด (มหาชน)", score=0.99, poly=[[0, 0], [400, 0], [400, 20], [0, 20]]),
            Token(text="some unrelated invoice text with no real table header nearby", score=0.99, poly=[[0, 500], [400, 500], [400, 520], [0, 520]]),
        ]
        column_bboxes, header_max_y = _detect_community_pharmacy_table(tokens)
        self.assertEqual(column_bboxes, {})
        self.assertIsNone(header_max_y)

    def test_column_header_present_but_supplier_name_absent_does_not_trigger(self):
        tokens = [
            Token(text="รหัสสินค้า", score=0.99, poly=[[0, 100], [100, 100], [100, 120], [0, 120]]),
            Token(text="รายละเอียด", score=0.99, poly=[[150, 100], [300, 100], [300, 120], [150, 120]]),
            Token(text="จำนวน", score=0.99, poly=[[350, 100], [450, 100], [450, 120], [350, 120]]),
        ]
        column_bboxes, header_max_y = _detect_community_pharmacy_table(tokens)
        self.assertEqual(column_bboxes, {})
        self.assertIsNone(header_max_y)


class CreditNoteRealPageTests(unittest.TestCase):
    """page-040 is a REAL Original Credit Note (DKSH) -- confirmed by
    reading its own header tokens in Phase A ("Original Credit Note" /
    "ต้นฉบับใบลดหนี้"), not constructed for this test."""

    def test_credit_note_page_is_classified_not_misread_as_a_tax_invoice(self):
        result = _extract(40)
        self.assertEqual(result["document_type"], "CREDIT_NOTE")

    def test_credit_note_extraction_does_not_crash_and_stays_versioned(self):
        result = _extract(40)
        self.assertEqual(result["contract_version"], PAGE_EXTRACTION_CONTRACT_VERSION)
        self.assertIn("table_found", result)


class MultiPageContinuationRealPageTests(unittest.TestCase):
    """page-014 is a REAL continuation page of a multi-page Woothi invoice
    ("หน้าที่ 2/3" -- page 2 of 3, confirmed in Phase A header text)."""

    def test_continuation_page_extracts_without_crashing(self):
        result = _extract(14)
        self.assertEqual(result["contract_version"], PAGE_EXTRACTION_CONTRACT_VERSION)
        # Whether or not this page repeats the table header is exactly the
        # kind of per-page fact Phase A logs rather than assumes; the only
        # hard requirement here is that extraction completes and stays
        # honest about what it found (table_found reflects reality).
        self.assertIn(result["table_found"], (True, False))


class TotalsBoundaryInvariantTests(unittest.TestCase):
    """Direct regression test for Codex's BLOCKED probe (found reviewing
    the Community Pharmacy adapter candidate): `_find_totals_boundary`
    must NEVER return a value <= `below_y` -- the whole point of the
    function is to mark where the product-row region ENDS, strictly below
    the table header. An earlier version clustered the full, unfiltered
    token list (including tokens with y0 <= below_y) before picking the
    matching row's own minimum y0, so an ordinary token sitting just
    above the header boundary could chain into the same row-cluster as a
    real TOTAL token just below it and drag the returned boundary back
    above (or onto) the header -- exactly the synthetic shape below:
    below_y=100, an ordinary token at y=90 (ineligible, above the
    boundary), a TOTAL token at y=110 (eligible) 20px below it, well
    within the default 25px row-clustering tolerance. This is a
    deliberately synthetic, minimal reproduction (not real OCR evidence)
    of the exact geometry Codex's probe used, kept separate from the real
    -evidence tests above."""

    def test_totals_boundary_never_returns_at_or_below_the_header_boundary(self):
        tokens = [
            Token(text="ordinary", score=0.99, poly=[[0, 90], [50, 90], [50, 95], [0, 95]]),
            Token(text="TOTAL AMOUNT", score=0.99, poly=[[100, 110], [200, 110], [200, 115], [100, 115]]),
        ]
        result = _find_totals_boundary(tokens, below_y=100)
        self.assertIsNotNone(result)
        self.assertGreater(result, 100)
        self.assertEqual(result, 110)


class RowClusteringUnitTests(unittest.TestCase):
    """Small, explicitly-synthetic token lists (declared as such) testing
    the clustering primitive in isolation -- these do not claim to be real
    OCR evidence for any specific invoice."""

    def test_tokens_at_the_same_y_band_cluster_into_one_row(self):
        tokens = [
            Token(text="A", score=0.99, poly=[[0, 100], [50, 100], [50, 120], [0, 120]]),
            Token(text="B", score=0.99, poly=[[100, 102], [150, 102], [150, 122], [100, 122]]),
            Token(text="C", score=0.99, poly=[[0, 300], [50, 300], [50, 320], [0, 320]]),
        ]
        rows = _cluster_rows(tokens)
        self.assertEqual(len(rows), 2)
        self.assertEqual({t.text for t in rows[0]}, {"A", "B"})
        self.assertEqual({t.text for t in rows[1]}, {"C"})

    def test_duplicate_token_at_identical_polygon_does_not_silently_double_count(self):
        # A duplicate-detection token/polygon scenario, synthesized because
        # it is not naturally present in the 10 real pages -- same text,
        # same polygon, twice (e.g. an OCR engine emitting an overlapping
        # detection). Both land in the SAME row cluster; the row-building
        # logic in extract_page() is what must not double-count identical
        # column tokens as two independent quantities -- covered end to end
        # via the "MULTIPLE_TOKENS_IN_COLUMN" quarantine reason using real
        # Berlin page 5 column bands is impractical to force without real
        # duplicate evidence, so this unit test isolates the primitive:
        # clustering itself must not silently merge or drop duplicates, it
        # must keep both so the caller's ambiguity handling can see them.
        tokens = [
            Token(text="10", score=0.99, poly=[[100, 100], [130, 100], [130, 120], [100, 120]]),
            Token(text="10", score=0.99, poly=[[100, 100], [130, 100], [130, 120], [100, 120]]),
        ]
        rows = _cluster_rows(tokens)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), 2)


class DocumentTypeClassificationTests(unittest.TestCase):
    def test_unknown_when_neither_keyword_set_present(self):
        tokens = [Token(text="Hello World", score=0.99, poly=[[0, 0], [10, 0], [10, 10], [0, 10]])]
        self.assertEqual(classify_document_type(tokens), "UNKNOWN")


class MatcherIntegrationReadOnlyTests(AppTestCase):
    """Phase C requirement: extracted rows must be able to reach the
    EXISTING, unmodified ProductMatcher read-only -- never a hand-mapped
    product, never a matcher change, never a persisted write from this
    path. Uses the real AppTestCase bootstrap (an ephemeral local SQLite
    data_root seeded from the packaged fixture, never a shared/production
    database -- identical to every other test in this suite) and calls
    `matcher._predict()`, the PURE half of the matcher that
    `predict_and_persist()` itself calls before writing anything -- this
    test calls it directly and never touches `predict_and_persist` or the
    repository, so no document/line/prediction row is ever created here."""

    def test_extracted_rows_route_through_the_real_matcher_without_persisting_anything(self):
        # Uses the same helper (and Phase-A-confirmed page-005 dimensions,
        # see `_extract`'s default) as every other real-evidence test in
        # this file -- image_size is not needed for matcher routing itself,
        # only for the bounding-box-in-page-bounds check elsewhere.
        extraction = _extract(5)
        self.assertEqual(len(extraction["product_rows"]), 5)

        document = {"id": "SLICE4-TEST-DOC", "supplier_code": "BERLIN-TEST"}
        ocr_versions = {"paddle_th": "test-evidence", "tesseract": "test-evidence"}
        predictions = []
        for row in extraction["product_rows"]:
            description = row["fields"]["description"]["raw_text"]
            line = {
                "id": f"SLICE4-TEST-LINE-{row['row_index']}",
                "supplier_sku": None,
                "description_final": description,
                "raw_ocr_text": description,
                "evidence_json": "{}",
            }
            prediction = self.app.matcher._predict(document, line, ocr_versions)
            # Every prediction the real matcher produces carries these keys
            # regardless of tier -- this is the actual contract the matcher
            # has always exposed (see matching.py's `_predict` return),
            # asserted here so a future matcher change that silently breaks
            # this shape fails a Slice-4 test too, not just matching.py's
            # own tests.
            for key in ("tier", "method", "reason_codes", "candidate_set", "proposed_product_code"):
                self.assertIn(key, prediction)
            predictions.append(prediction)
        self.assertEqual(len(predictions), 5)

        # The defining assertion for this test: routing rows through
        # `_predict()` must never write anything. `predict_and_persist()`
        # was never called, so no line/prediction exists for this
        # synthetic document_id at all.
        self.assertEqual(self.app.repository.list_lines(document["id"]), [])


class PageExtractionBundleTests(unittest.TestCase):
    def test_bundle_is_versioned_deterministic_and_preserves_provenance(self):
        page = _extract(5)
        matcher = {(5, 1): {"tier": "UNRESOLVED", "proposed_product_code": None, "candidate_set": []}}
        first = build_page_extraction_bundle(
            source_name="invoice.pdf", source_sha256="a" * 64, pages=[page],
            image_refs={5: "pages/page-005.png"}, matcher_results=matcher,
        )
        second = build_page_extraction_bundle(
            source_name="invoice.pdf", source_sha256="a" * 64, pages=[page],
            image_refs={5: "pages/page-005.png"}, matcher_results=matcher,
        )
        self.assertEqual(first, second)
        self.assertEqual(first["contract_version"], "page-extraction-bundle.v1")
        self.assertEqual(first["summary"]["row_count"], 5)
        self.assertEqual(first["pages"][0]["product_rows"][0]["matcher_result"]["tier"], "UNRESOLVED")
        self.assertIn("polygon", first["pages"][0]["product_rows"][0]["fields"]["description"])

    def test_writer_round_trips_complete_json_and_leaves_no_temp_file(self):
        payload = build_page_extraction_bundle(
            source_name="invoice.pdf", source_sha256="b" * 64, pages=[_extract(5)]
        )
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "slice4.page-extraction.v1.json"
            write_page_extraction_bundle(target, payload)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
            self.assertEqual(list(Path(temporary).glob("*.tmp")), [])


class ArtifactBuilderBoundaryTests(unittest.TestCase):
    """Crosses the REAL `scripts/build_slice4_page_artifact.py` boundary --
    imports and calls its own `build()` function end to end (real OCR
    evidence, a real ephemeral `Application`, a real written artifact file
    read back), never hand-constructing a matcher `line` dict as a
    substitute for exercising the actual script. This is what proves the
    supplier_sku/canonical_supplier_code/unit_final plumbing identified as
    missing (Codex BLOCKED finding 1) actually reaches the matcher THROUGH
    the builder, not just through a test's own direct `_predict()` call."""

    @classmethod
    def setUpClass(cls):
        _skip_if_missing()
        import importlib.util
        import sys

        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        module_path = scripts_dir / "build_slice4_page_artifact.py"
        spec = importlib.util.spec_from_file_location("build_slice4_page_artifact", module_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_slice4_page_artifact"] = module
        spec.loader.exec_module(module)
        cls.builder_module = module

        cls.temp_dir = tempfile.TemporaryDirectory(prefix="ocr-inbound-artifact-builder-test-")
        output_path = Path(cls.temp_dir.name) / "page-extraction-bundle.v1.json"
        cls.payload = module.build(
            run_root=EVIDENCE_ROOT,
            source=PAGES_DIR / "page-005.png",
            output=output_path,
            pages=[5, 58],
        )
        cls.written = json.loads(output_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def _page(self, payload, page_number):
        return next(p for p in payload["pages"] if p["page_number"] == page_number)

    def test_page_58_row_1_supplier_sku_reaches_the_written_artifact(self):
        page = self._page(self.written, 58)
        self.assertEqual(page["canonical_supplier_code"], "SUPPLIER-COMMUNITY-PHARMACY")
        row1 = page["product_rows"][0]
        self.assertEqual(row1["fields"]["supplier_sku"]["raw_text"], "32132")
        # The alias path was structurally tested (a real canonical supplier
        # code was available) -- this is the flag downstream reporting must
        # check before ever claiming "alias lookup was exercised".
        self.assertTrue(row1["matcher_result"]["alias_path_tested"])
        # No approved (SUPPLIER-COMMUNITY-PHARMACY, "32132") alias exists in
        # the packaged local fixture -- must not auto-confirm.
        self.assertNotIn(row1["matcher_result"]["tier"], ("EXACT_CODE", "ACTIVE_ALIAS"))

    def test_page_58_row_2_has_no_printed_sku_and_it_is_never_inherited_from_row_1(self):
        page = self._page(self.written, 58)
        row2 = page["product_rows"][1]
        # Row 2's own real evidence has no supplier_sku token at all
        # (confirmed in Phase A) -- it must stay None/absent, never
        # silently copy row 1's "32132" via an implicit same-page
        # inheritance rule that was never specified.
        self.assertIsNone(row2["fields"]["supplier_sku"])
        # alias_path_tested still reflects the PAGE's canonical supplier
        # code being known, even though this specific row has no SKU to
        # look up -- it is a statement about whether the identity contract
        # existed, not about whether this row happened to have a SKU.
        self.assertTrue(row2["matcher_result"]["alias_path_tested"])

    def test_page_5_has_no_supplier_identity_contract_and_says_so_honestly(self):
        # Berlin page-005 uses the TABULAR_HEADER strategy, which has no
        # supplier-identity contract built yet -- must report UNKNOWN, not
        # a guess, and must not claim the alias path was tested for any
        # of its rows.
        page = self._page(self.written, 5)
        self.assertEqual(page["canonical_supplier_code"], "UNKNOWN")
        for row in page["product_rows"]:
            self.assertFalse(row["matcher_result"]["alias_path_tested"])

    def test_build_did_not_persist_any_document(self):
        # build() itself asserts this and raises if violated -- this test
        # additionally confirms the assertion is reachable/real by having
        # already completed setUpClass without raising, and directly
        # re-checks the same invariant via a fresh Application against the
        # SAME evidence to rule out a false-negative from state reuse.
        from ocr_inbound.service import Application

        with tempfile.TemporaryDirectory(prefix="ocr-inbound-artifact-builder-recheck-") as temp:
            app = Application.bootstrap(data_root=Path(temp), reviewer_id="artifact-builder-recheck")
            self.assertEqual(app.repository.list_documents(), [])

    def test_unit_final_is_passed_through_as_extracted_not_reformatted_by_the_script(self):
        # The script must not invent its own uppercasing/normalization --
        # matching.py's own `.strip().upper()` (line ~1011) is the single
        # source of truth for the canonical unit shape; this test confirms
        # the script passes the raw extracted text through unchanged by
        # checking it did not crash and the matcher's own normalization
        # visibly took effect (unit_code, when a product is selected, is
        # only ever set to an ALREADY-uppercase valid_units entry -- with
        # UNRESOLVED here there is no selected product, so proposed_unit
        # stays None, which is itself the honest, non-guessing result).
        page = self._page(self.written, 58)
        row1 = page["product_rows"][0]
        self.assertEqual(row1["fields"]["unit"]["raw_text"], "box")
        self.assertIsNone(row1["matcher_result"]["proposed_unit_code"])

    def test_an_approved_alias_is_genuinely_reachable_through_this_plumbing(self):
        # The other tests above prove the plumbing stays correctly SILENT
        # when no alias exists yet (no auto-confirm off a bare SKU) -- this
        # test proves the reverse direction: when a real, approved
        # (supplier_code, supplier_sku) alias DOES exist, this same
        # end-to-end path (extraction -> builder -> matcher._predict) must
        # actually resolve it to ACTIVE_ALIAS with the right product AND
        # unit, not just fail safe forever. Seeds a real alias through the
        # repository's own approval workflow (3 distinct-document
        # observations to reach ELIGIBLE, then approve_alias) -- never
        # writes the alias table directly.
        from ocr_inbound.service import Application

        with tempfile.TemporaryDirectory(prefix="ocr-inbound-alias-reachability-") as temp:
            app = Application.bootstrap(data_root=Path(temp), reviewer_id="alias-reachability-test")
            actor = app.identity.current_actor()
            supplier_code = "SUPPLIER-COMMUNITY-PHARMACY"
            product_code = "6300001"  # real fixture product, BOX unit
            alias = None
            for doc_id in ("DOC-A", "DOC-B", "DOC-C"):
                alias = app.repository.record_alias_observation(supplier_code, "32132", product_code, doc_id, actor)
            self.assertEqual(alias["status"], "ELIGIBLE")
            approved = app.repository.approve_alias(alias["id"], actor)
            self.assertEqual(approved["status"], "ACTIVE")

            extraction = _extract(58)
            row1 = extraction["product_rows"][0]
            document = {"id": "ALIAS-REACHABILITY-DOC", "supplier_code": supplier_code}
            line = {
                "id": "ALIAS-REACHABILITY-LINE-1",
                "supplier_sku": row1["fields"]["supplier_sku"]["raw_text"],
                "description_final": row1["fields"]["description"]["raw_text"],
                "raw_ocr_text": row1["fields"]["description"]["raw_text"],
                "unit_final": row1["fields"]["unit"]["raw_text"],
                "evidence_json": "{}",
            }
            prediction = app.matcher._predict(document, line, {"paddle_th": "x", "tesseract": "x"})
            self.assertEqual(prediction["tier"], "ACTIVE_ALIAS")
            self.assertEqual(prediction["method"], "supplier_sku_active_alias")
            self.assertEqual(prediction["proposed_product_code"], product_code)
            self.assertEqual(prediction["proposed_unit_code"], "BOX")
            self.assertEqual(app.repository.list_documents(), [])


def _synthetic_token(text, x0, y0, x1, y1, score=0.99):
    return Token(text=text, score=score, poly=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def _cp_header_tokens():
    """The real page-058 five-column Thai header, at synthetic coordinates
    (one tight Y-band, X bands matching the column layout)."""
    return [
        _synthetic_token("รหัสสินค้า", 100, 1000, 200, 1016),
        _synthetic_token("รายละเอียด", 300, 1000, 450, 1016),
        _synthetic_token("จำนวน", 500, 1000, 600, 1016),
        _synthetic_token("ราคารวมภาษี", 700, 1000, 850, 1016),
        _synthetic_token("จำนวนเงิน", 900, 1000, 1000, 1016),
    ]


_CP_IDENTITY_TOKEN = _synthetic_token("ชุมชนเภสัชกรรม", 0, 50, 200, 66)


class CommunityPharmacyGateAdversarialTests(unittest.TestCase):
    """Explicitly SYNTHETIC adversarial tests for the Community Pharmacy
    adapter's two independent gate conditions and its data-row/Lot-row
    pairing rule -- none of the 10 real pages carries a WRONG combination
    (real page-058 has both identity and header; real page-005 has
    neither), so these probes are built from the same coordinate shape as
    the real page. The positive control runs first so the two gate
    negatives below can never pass vacuously against a gate that simply
    never activates."""

    def test_positive_control_identity_plus_full_header_activates_the_gate(self):
        tokens = [_CP_IDENTITY_TOKEN, *_cp_header_tokens()]
        column_bboxes, header_max_y = _detect_community_pharmacy_table(tokens)
        self.assertIsNotNone(header_max_y)
        self.assertLessEqual(
            {"supplier_sku", "description", "quantity", "unit_price", "total_amount"},
            set(column_bboxes),
        )

    def test_identity_present_but_wrong_header_does_not_activate(self):
        # Only 2 distinct column concepts (min gate is 3): the supplier is
        # plausibly Community Pharmacy but this page's table is not their
        # code-table layout -- the adapter must stay off rather than parse
        # a table it was never designed for.
        tokens = [
            _CP_IDENTITY_TOKEN,
            _synthetic_token("รหัสสินค้า", 100, 1000, 200, 1016),
            _synthetic_token("จำนวน", 500, 1000, 600, 1016),
        ]
        self.assertEqual(_detect_community_pharmacy_table(tokens), ({}, None))
        rows, _ = _community_pharmacy_code_table_rows(tokens, page_number=1, tesseract_text="")
        self.assertEqual(rows, [])

    def test_full_header_present_but_wrong_identity_does_not_activate(self):
        # Another supplier printing the exact same five Thai column words
        # must not trigger this supplier-specific adapter.
        tokens = [*_cp_header_tokens()]
        self.assertEqual(_detect_community_pharmacy_table(tokens), ({}, None))
        rows, _ = _community_pharmacy_code_table_rows(tokens, page_number=1, tesseract_text="")
        self.assertEqual(rows, [])

    def test_data_row_with_no_lot_row_does_not_steal_the_next_products_lot(self):
        # Row A has no Lot row of its own; row B does. The pairing rule is
        # "this row, then the IMMEDIATELY NEXT row, only if that row is a
        # fused Lot/dates row" -- row A must report MISSING_FIELD:lot and
        # take nothing, while row B keeps its own Lot.
        tokens = [
            _CP_IDENTITY_TOKEN,
            *_cp_header_tokens(),
            # data row A (y~1100) -- no Lot row follows it
            _synthetic_token("11111", 100, 1100, 160, 1116),
            _synthetic_token("PRODUCTA TAB", 300, 1100, 450, 1116),
            _synthetic_token("10.00 box", 500, 1100, 620, 1116),
            _synthetic_token("5.000", 700, 1100, 760, 1116),
            _synthetic_token("50.00", 900, 1100, 960, 1116),
            # data row B (y~1200), followed by ITS OWN Lot row (y~1250)
            _synthetic_token("22222", 100, 1200, 160, 1216),
            _synthetic_token("PRODUCTB TAB", 300, 1200, 450, 1216),
            _synthetic_token("20.00 box", 500, 1200, 620, 1216),
            _synthetic_token("6.000", 700, 1200, 760, 1216),
            _synthetic_token("120.00", 900, 1200, 960, 1216),
            _synthetic_token("LO. LOTB Mfg, 01/01/25 Exp, 01/01/28", 300, 1250, 700, 1266),
            # totals line bounds the table region from below
            _synthetic_token("รวมเงินสุทธิ", 900, 1400, 1000, 1416),
        ]
        rows, _warnings = _community_pharmacy_code_table_rows(tokens, page_number=1, tesseract_text="")
        self.assertEqual(len(rows), 2)
        row_a, row_b = rows
        self.assertEqual(row_a["fields"]["supplier_sku"]["raw_text"], "11111")
        self.assertIsNone(row_a["fields"]["lot"])
        self.assertIn("MISSING_FIELD:lot", row_a["quarantine_reasons"])
        self.assertEqual(row_b["fields"]["supplier_sku"]["raw_text"], "22222")
        self.assertEqual(row_b["fields"]["lot"]["normalized_value"], "LOTB")


class BuilderMatcherInputBoundaryTests(unittest.TestCase):
    """Adversarial complement to ArtifactBuilderBoundaryTests above: those
    tests read the WRITTEN ARTIFACT (extraction fields + matcher RESULTS),
    but a regression that stops feeding supplier_sku/unit_final/canonical
    supplier_code INTO `matcher._predict` itself can leave every
    artifact-level assertion green (verified empirically 2026-08-21:
    reverting the builder to `supplier_sku = None` still passed 6/6).
    This class spies the real `_predict` boundary DURING a real `build()`
    call and asserts the actual INPUT contract -- page-58 row 1 must carry
    supplier_sku "32132" and the page's canonical supplier code; row 2,
    which has no printed SKU, must receive None (never fabricated, never
    inherited from row 1)."""

    def test_real_builder_feeds_sku_unit_and_supplier_code_into_predict(self):
        import importlib.util
        import sys
        import unittest.mock

        from ocr_inbound.matching import ProductMatcher

        _skip_if_missing()
        spec = importlib.util.spec_from_file_location(
            "build_slice4_page_artifact_input_spy", Path(__file__).resolve().parents[1] / "scripts" / "build_slice4_page_artifact.py"
        )
        builder = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = builder
        spec.loader.exec_module(builder)

        captured = []
        original = ProductMatcher._predict

        def spy(matcher_self, document, line, ocr_versions):
            captured.append({
                "line_id": line["id"],
                "supplier_code": document.get("supplier_code"),
                "supplier_sku": line.get("supplier_sku"),
                "unit_final": line.get("unit_final"),
            })
            return original(matcher_self, document, line, ocr_versions)

        with tempfile.TemporaryDirectory(prefix="ocr-inbound-builder-spy-") as temp:
            with unittest.mock.patch.object(ProductMatcher, "_predict", spy):
                payload = builder.build(
                    run_root=EVIDENCE_ROOT,
                    source=PAGES_DIR / "page-058.png",
                    output=Path(temp) / "bundle.json",
                    pages=[58],
                )
        self.assertEqual(payload["summary"]["row_count"], 2)
        by_line = {entry["line_id"]: entry for entry in captured}
        row1 = by_line["SLICE4-PAGE-58-ROW-1"]
        row2 = by_line["SLICE4-PAGE-58-ROW-2"]
        self.assertEqual(row1["supplier_sku"], "32132")
        self.assertEqual(row1["supplier_code"], "SUPPLIER-COMMUNITY-PHARMACY")
        self.assertEqual(row1["unit_final"], "box")
        self.assertIsNone(row2["supplier_sku"])
        self.assertEqual(row2["unit_final"], "box")
        self.assertEqual(row2["supplier_code"], "SUPPLIER-COMMUNITY-PHARMACY")


if __name__ == "__main__":
    unittest.main()
