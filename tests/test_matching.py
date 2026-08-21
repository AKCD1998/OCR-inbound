"""Layer F product matcher tests.

Phase A - characterization tests documenting the CURRENT (pre-fix) matcher
behavior on the existing packaged fixture (630XXXX codes), used as a
regression net so the new trade-name/attribute-guard work cannot silently
break the original exact-code/barcode/alias/fuzzy cascade.

Phase B/C/D - new capability: trade-name token retrieval, ingredient/
strength/pack-size contradiction guards, and the internal-code regex fix for
real six-digit `IC-XXXXXX` and nine-digit `630XXXXXX` codes (with an explicit
partial-code-match guard).

This file builds its own small ADA reference caches from literal fixture
dicts (not the packaged `ada_fixture.json`, not a live DB connection) so
every test here is fully offline and deterministic. Product identities used
below for the "real invoice" scenarios (IC-000648 MINIDIAB, IC-002268
ISOTRATE, IC-002001/IC-002002 PRESOLIN 150/300mg, IC-004874 RELESTAT,
IC-002137 LESFLAM, IC-001962 CODIPHEN, plus the real confusable competitor
products IC-001609/IC-001593 APROVEL and IC-000103 the calamine decoy) are
the codes/names Codex confirmed by reading the live PaaSRTSM product master
read-only (see docs/DEV_LAPTOP_SETUP_LEDGER_TH.md R-006..R-011 and
ocr_runs_staging/realinv_20260820T040631Z/FULL_MASTER_LAYER_F_RESULTS.json).
The gauze and MATRACOL/MATRADOL products are test-only placeholders (labelled
TESTGZ-/TESTMX-) since no real product identity for those two lines was
established -- they exist only to prove the contradiction guard and the
no-auto-confirm-on-ambiguity rule, not to assert real catalog content.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ocr_inbound.config import AppProfile
from ocr_inbound.ada_read import AdaReferenceCache
from ocr_inbound.db import canonical_json
from ocr_inbound.matching import (
    INTERNAL_CODE,
    ProductMatcher,
    attributes_conflict,
    extract_attributes,
    extract_trade_name_tokens,
    normalize_product_text,
)


# Slice 2 adds SPELLING_ALIAS (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22)
# to the auto-confirmable set -- it goes through the exact same
# observe-3-times-then-approve human lifecycle as ACTIVE_ALIAS (see
# Repository.record_name_alias_observation/approve_name_alias), just scoped
# globally instead of per-supplier. SPELLING_SUGGESTION ("did you mean") is
# deliberately NOT in this set -- it is never auto-confirmable.
AUTO_CONFIRMABLE_TIERS = {"EXACT_CODE", "EXACT_BARCODE", "ACTIVE_ALIAS", "SPELLING_ALIAS"}


class _NoAliasRepository:
    """Read-only stand-in: no supplier_product_aliases in these fixtures."""

    def list_aliases(self, supplier_code):
        return []

    def list_name_aliases(self):
        return []


class _StaticAliasRepository:
    """Read-only stand-in carrying one pre-approved, human-confirmed alias,
    used to prove ACTIVE_ALIAS outranks TRADE_NAME_MATCH (Codex adjudication
    finding 1). Slice 2: also carries `name_aliases`, an optional list of
    pre-approved (ACTIVE-status) supplier-agnostic spelling/name aliases."""

    def __init__(self, aliases, name_aliases=None):
        self._aliases = aliases
        self._name_aliases = name_aliases or []

    def list_aliases(self, supplier_code):
        return [a for a in self._aliases if a["supplier_code"] == supplier_code]

    def list_name_aliases(self):
        return list(self._name_aliases)


def _build_matcher(tmp_root: Path, products: list[dict], suppliers: list[dict] | None = None, repository=None) -> ProductMatcher:
    profile = AppProfile(
        environment="staging",
        root=tmp_root,
        app_db=tmp_root / "unused_app.db",
        ada_cache_db=tmp_root / "ada_cache.db",
        artifacts=tmp_root / "artifacts",
        logs=tmp_root / "logs",
        backups=tmp_root / "backups",
        badge="STAGING - NOT PRODUCTION AUTH",
        mutex_name="Global\\OCRInbound.ADA.matching-tests",
        target_allowlist=("STAGING_TEST",),
    )
    profile.ensure_directories()
    cache = AdaReferenceCache(profile)
    cache.refresh_from_fixture(
        {
            "products": products,
            "suppliers": suppliers or [],
            "purchase_history": [],
        }
    )
    return ProductMatcher(repository if repository is not None else _NoAliasRepository(), cache)


def _product(code, name, *, barcode=None, ingredient="", strength="", size="", units=None, name_thai=None, name_eng=None):
    # Slice 2: `name_thai`/`name_eng`, when given, are passed through to
    # AdaReferenceCache.refresh_from_fixture verbatim (real bilingual
    # products). When neither is given, `name` alone is still accepted --
    # the cache auto-splits it by detected script (see
    # ada_read._split_bilingual_name) so every pre-Slice-2 call site of
    # this helper keeps working unchanged.
    product = {
        "product_code": code,
        "barcode": barcode,
        "name": name,
        "normalized_name": normalize_product_text(name),
        "ingredient": ingredient,
        "strength": strength,
        "size": size,
        "manufacturer": "",
        "active": True,
        "units": units or [{"unit_code": "BOX", "factor": "1", "active": True}],
    }
    if name_thai is not None:
        product["name_thai"] = name_thai
    if name_eng is not None:
        product["name_eng"] = name_eng
    return product


def _predict(
    matcher: ProductMatcher,
    description: str,
    *,
    supplier_sku=None,
    supplier_code="UNKNOWN",
    barcode_candidates=None,
    internal_code_candidates=None,
    raw_ocr_text=None,
    unit_final="",
    evidence_json=None,
) -> dict:
    document = {"id": "doc-1", "supplier_code": supplier_code}
    if evidence_json is not None:
        evidence: dict | str = evidence_json
    else:
        evidence = {}
        if barcode_candidates is not None:
            evidence["barcode_candidates"] = barcode_candidates
        if internal_code_candidates is not None:
            evidence["internal_code_candidates"] = internal_code_candidates
        evidence = evidence or None
    line = {
        "id": "line-1",
        "supplier_sku": supplier_sku,
        "description_final": description,
        "raw_ocr_text": raw_ocr_text if raw_ocr_text is not None else description,
        "unit_final": unit_final,
        "evidence_json": evidence,
    }
    return matcher._predict(document, line, {"source": "test"})


class TmpCacheTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="layerf-test-")
        self.tmp_root = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Phase A - characterization of the ORIGINAL (pre-fix) fixture cascade.
# These lock in behavior that must survive the new trade-name/guard stages
# being inserted between EXACT_BARCODE and ACTIVE_ALIAS.
# ---------------------------------------------------------------------------
class CharacterizationOriginalCascade(TmpCacheTestCase):
    """Uses the same 630XXXX-style fixture shape as the packaged
    ada_fixture.json (see src/ocr_inbound/resources/ada_fixture.json) so
    these tests double as a regression net for the 37 pre-existing tests
    that depend on Application.bootstrap()'s default fixture."""

    def setUp(self) -> None:
        super().setUp()
        products = [
            _product("6300001", "ยาพาราเซตามอล 500 มก", ingredient="PARACETAMOL", strength="500 MG"),
            _product("6300003", "ยาแก้แพ้ เซทิริซีน 10 มก", ingredient="CETIRIZINE", strength="10 MG",
                      barcode="885000000003"),
        ]
        self.matcher = _build_matcher(self.tmp_root, products)

    def test_exact_code_still_resolves_with_explicit_provenance(self):
        # Slice 1 remediation (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 18):
        # EXACT_CODE now auto-confirms only from explicit-provenance
        # evidence_json["internal_code_candidates"] -- a bare digit run
        # found by scanning free OCR text is never trusted enough to
        # auto-confirm on its own (see InternalCodeTextMatchTests below for
        # that downgraded, human-review-only path).
        result = _predict(
            self.matcher,
            "6300001 ยาพาราเซตามอล 500 มก BOX 2 100.00 200.00",
            internal_code_candidates=["6300001"],
        )
        self.assertEqual(result["tier"], "EXACT_CODE")
        self.assertEqual(result["proposed_product_code"], "6300001")

    def test_exact_barcode_still_resolves(self):
        # Slice 1 field-contract rework: EXACT_BARCODE now requires explicit
        # barcode evidence (evidence_json["barcode_candidates"]), never a
        # bare supplier_sku value -- see BarcodeEvidenceTests for the
        # dedicated coverage of that separation. This still proves the
        # EXACT_BARCODE tier itself resolves correctly end to end.
        result = _predict(self.matcher, "ยาแก้แพ้ เซทิริซีน 10 มก", barcode_candidates=["885000000003"])
        self.assertEqual(result["tier"], "EXACT_BARCODE")
        self.assertEqual(result["proposed_product_code"], "6300003")

    def test_no_match_still_unresolved(self):
        result = _predict(self.matcher, "ยาที่ไม่มีอยู่ในระบบเลย XYZQQQ")
        self.assertEqual(result["tier"], "UNRESOLVED")
        self.assertIsNone(result["proposed_product_code"])


# ---------------------------------------------------------------------------
# Phase A (continued) - the two documented root causes, proven directly.
# ---------------------------------------------------------------------------
class CharacterizationRootCauses(unittest.TestCase):
    def test_internal_code_regex_rejects_real_six_digit_ic_code(self):
        # Before the D-phase fix: IC-000648 (a real product code) does not
        # match because the old pattern requires exactly four digits after
        # "IC-". This is why EXACT_CODE could never fire for the real
        # invoice lines even when the line happened to contain a code.
        self.assertEqual(INTERNAL_CODE.findall("SOME TEXT IC-000648 MORE TEXT"), ["IC-000648"],
                          "if this fails, the regex fix in matching.py has not been applied yet")

    def test_whole_string_fuzzy_prefers_wrong_variant_over_correct_trade_name(self):
        # Documents the exact failure mode Codex captured empirically in
        # FULL_MASTER_LAYER_F_RESULTS.json line 2: PRESOLIN's OCR text
        # whole-string-fuzzy-matched APROVEL (0.6400) ahead of the correct
        # MEDLINE PRESOLIN entry (0.6190), purely because SequenceMatcher's
        # character-level ratio favors overall string-shape similarity over
        # the literal trade-name substring. Reproduced here with a small
        # local fixture so the claim doesn't depend on live DB access.
        from difflib import SequenceMatcher

        ocr_text = normalize_product_text("PRESOLIN 150 MG.TAB.10X10'S (Irbesartan 150 mg)")
        correct_name = normalize_product_text("MEDLINE PRESOLIN IRBESARTAN 150 MG 10 S")
        decoy_name = normalize_product_text("APROVEL 150 MG. (IRBESARTAN) 28 S")
        correct_score = SequenceMatcher(None, ocr_text, correct_name).ratio()
        decoy_score = SequenceMatcher(None, ocr_text, decoy_name).ratio()
        self.assertGreater(
            decoy_score, correct_score,
            "if this fails, whole-string fuzzy no longer prefers the wrong variant on this "
            "input and the trade-name-retrieval fix may no longer be necessary for this case",
        )


# ---------------------------------------------------------------------------
# Phase B/C - trade-name token retrieval + attribute contradiction guards,
# using the real product identities Codex confirmed against the live master.
# ---------------------------------------------------------------------------
_REAL_MASTER_PRODUCTS = [
    _product("IC-000648", "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S"),
    _product("IC-002268", "BERLIN ISOTRATE ISOSORBIDE DINITRATE 10 MG 10 S"),
    _product("IC-002001", "MEDLINE PRESOLIN IRBESARTAN 150 MG 10 S"),
    _product("IC-002002", "MEDLINE PRESOLIN IRBESARTAN 300 MG 10 S"),
    _product("IC-001609", "APROVEL 150 MG. (IRBESARTAN) 28 S"),
    _product("IC-001593", "APROVEL 300 MG. (IRBESARTAN) 28 S"),
    _product("IC-004874", "ABBVIE RELESTAT OLOPATADINE 0.05% 5 ML"),
    _product("IC-002137", "MEDLINE LESFLAM DICLOFENAC POTASSIUM 50 MG 10 S"),
    _product("IC-003658", "MEGA DOFLAM DICLOFENAC POTASSIUM 50 MG 10 S"),
    _product("IC-001962", "CHUMCHON CODIPHEN DIPHENHYDRAMINE 50 MG 10 S"),
    _product("IC-002993", "BEDSIDE TABLE ABS 1 S"),
    _product("IC-000103", "สามัญคาลาไมน์ตราเสือดาว 60 มล"),
    # Test-only placeholders (no real catalog identity was established for
    # gauze/MATRACOL in this evaluation round) -- these exist purely to
    # prove the contradiction guard and the ambiguity/no-auto-confirm rule.
    _product("TESTGZ-001", "GAUZE PAD 10X20 CM 2S"),
    _product("TESTGZ-002", "GAUZE PAD 3X3 INCH 5S"),
    _product("TESTMX-001", "MATRACOL SYRUP 100 ML"),
    _product("TESTMX-002", "MATRADOL TABLET 50 MG"),
]


class TradeNameRetrievalAcceptanceMatrix(TmpCacheTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.matcher = _build_matcher(self.tmp_root, _REAL_MASTER_PRODUCTS)

    def _candidate_codes(self, result: dict) -> set[str]:
        return {c["product_code"] for c in result["candidate_set"]}

    def test_minidiab_candidate_includes_real_code(self):
        result = _predict(self.matcher, "MINIDIAB 5mg 2x15's", supplier_sku="844")
        self.assertIn("IC-000648", self._candidate_codes(result) | {result["proposed_product_code"]})
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_isotrate_candidate_includes_real_code(self):
        result = _predict(self.matcher, "ISOTRATE 10 MG. (W) 50X10'S")
        self.assertIn("IC-002268", self._candidate_codes(result) | {result["proposed_product_code"]})
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_presolin_150_selects_150mg_not_300mg(self):
        result = _predict(self.matcher, "PRESOLIN 150 MG.TAB.10X10'S (Irbesartan 150 mg)", supplier_sku="1000000513")
        codes = self._candidate_codes(result) | {result["proposed_product_code"]}
        self.assertIn("IC-002001", codes)
        self.assertNotEqual(result["proposed_product_code"], "IC-002002",
                             "must not select the 300 MG variant when OCR states 150 MG")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_relestat_candidate_includes_real_code(self):
        # The bare Thai-transliterated OCR text alone ("รีเลสตาต") cannot be
        # substring/token-matched against the English trade name "RELESTAT"
        # without phonetic transliteration mapping, which is out of scope
        # here (see report section on residual risks). The evaluation's own
        # fusion_text for this line legitimately carries an English hint
        # inferred from the invoice's own department field ("ABBVIE-EYE
        # CARE") -- see OCR_REAL_INVOICE_LINES.csv line 5 -- so that is what
        # Phase E actually feeds the matcher, and what this test mirrors.
        result = _predict(
            self.matcher,
            "รีเลสตาต 0.05% 5ML (คาดว่าคือ Relestat - อยู่ในแผนก ABBVIE-EYE CARE ตามหัวบิล)",
            supplier_sku="100754916",
        )
        self.assertIn("IC-004874", self._candidate_codes(result) | {result["proposed_product_code"]})
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_relestat_bare_thai_transliteration_alone_is_unresolved(self):
        # Documents the residual gap explicitly: without the English hint,
        # this line cannot be resolved by substring/token retrieval. This is
        # expected, not a bug in the new matcher -- flagged in the report as
        # a case that still needs either a curated alias or genuine
        # phonetic-transliteration matching (future work, out of scope).
        result = _predict(self.matcher, "รีเลสตาต 0.05% 5ML", supplier_sku="100754916")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_lesflam_50_candidate_includes_real_code(self):
        result = _predict(self.matcher, "LESFLAM 50 MG.TAB.10X10'S (Diclofenac Potassium 50 mg)", supplier_sku="1000000316")
        self.assertIn("IC-002137", self._candidate_codes(result) | {result["proposed_product_code"]})
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_codiphen_candidate_includes_real_code(self):
        result = _predict(self.matcher, "CODIPHEN TABLET (1X10's)", supplier_sku="32132")
        self.assertIn("IC-001962", self._candidate_codes(result) | {result["proposed_product_code"]})
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_gauze_10x20_does_not_select_3x3_inch_variant(self):
        result = _predict(self.matcher, "GAUZE PAD 10X20 CM 2S", supplier_sku="100553082")
        self.assertNotEqual(result["proposed_product_code"], "TESTGZ-002")

    def test_matracol_matradol_ambiguity_never_auto_confirms(self):
        # A near-miss typo between two genuinely different real products
        # must never be resolved with confidence; human review is required
        # either way, and the tier must never land in the auto-confirmable
        # set regardless of which (if either) candidate comes out on top.
        result = _predict(self.matcher, "มาทราคอล (50 x 10 แคปซูล)", supplier_sku="0102004")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_minor_typo_may_suggest_but_never_auto_confirms(self):
        result = _predict(self.matcher, "MINIDIAG 5mg 2x15's")  # typo: G instead of B
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_candidate_set_always_agrees_with_proposed_product_code(self):
        # Found while running Phase E against the real ~6,700-product master
        # (never visible on the small 16-product fixture above): the
        # whole-catalog fuzzy pool used to be computed unconditionally and
        # could silently disagree with whichever tier actually resolved
        # `selected`, so candidate_set[0]["name"] and proposed_product_code
        # could name two different products in the same prediction. This
        # must never happen for ANY tier, not just TRADE_NAME_MATCH.
        for description, supplier_sku in (
            ("MINIDIAB 5mg 2x15's", "844"),
            ("CODIPHEN TABLET (1X10's)", "32132"),
            ("LESFLAM 50 MG.TAB.10X10'S (Diclofenac Potassium 50 mg)", "1000000316"),
        ):
            with self.subTest(description=description):
                result = _predict(self.matcher, description, supplier_sku=supplier_sku)
                if result["proposed_product_code"] is not None:
                    self.assertTrue(result["candidate_set"], "a selected product must always carry a non-empty candidate_set")
                    self.assertEqual(
                        result["candidate_set"][0]["product_code"], result["proposed_product_code"],
                        "candidate_set[0] must always be the same product as proposed_product_code",
                    )

    def test_conflicting_strength_blocks_that_candidate(self):
        result = _predict(self.matcher, "PRESOLIN 300 MG.TAB.10X10'S (Irbesartan 300 mg)")
        self.assertNotEqual(result["proposed_product_code"], "IC-002001",
                             "150 MG variant must not be selected when OCR clearly states 300 MG")


# ---------------------------------------------------------------------------
# Phase C - attribute extraction / contradiction-guard unit tests (isolated
# from candidate retrieval, so a guard bug is diagnosable on its own).
# ---------------------------------------------------------------------------
class AttributeGuardUnitTests(unittest.TestCase):
    def test_extract_strength(self):
        attrs = extract_attributes("PRESOLIN 150 MG TAB 10X10 S")
        self.assertIn((150.0, "MG"), attrs["strengths"])

    def test_extract_pack_dimension(self):
        attrs = extract_attributes("GAUZE PAD 10X20 CM 2S")
        self.assertIn((10, 20), attrs["packs"])

    def test_no_conflict_when_one_side_silent(self):
        a = extract_attributes("MINIDIAB 5MG 2X15 S")
        b = extract_attributes("PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S")
        # a states a pack (2x15), b states none -- must not be treated as a
        # contradiction; only an explicit disagreement blocks a candidate.
        self.assertFalse(attributes_conflict(a, b))

    def test_conflict_when_strength_disagrees(self):
        a = extract_attributes("PRESOLIN 150 MG")
        b = extract_attributes("MEDLINE PRESOLIN IRBESARTAN 300 MG 10 S")
        self.assertTrue(attributes_conflict(a, b))

    def test_conflict_when_pack_dimension_disagrees(self):
        a = extract_attributes("GAUZE PAD 10X20 CM 2S")
        b = extract_attributes("GAUZE PAD 3X3 INCH 5S")
        self.assertTrue(attributes_conflict(a, b))

    def test_no_conflict_when_strength_agrees(self):
        a = extract_attributes("MINIDIAB 5MG")
        b = extract_attributes("PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S")
        self.assertFalse(attributes_conflict(a, b))


# ---------------------------------------------------------------------------
# Phase D - internal-code regex: real formats + explicit partial-match guard.
# ---------------------------------------------------------------------------
class InternalCodeRegexTests(unittest.TestCase):
    def test_matches_six_digit_ic_code(self):
        self.assertEqual(INTERNAL_CODE.findall("IC-000648"), ["IC-000648"])

    def test_matches_nine_digit_630_code(self):
        self.assertEqual(INTERNAL_CODE.findall("630010124"), ["630010124"])

    def test_still_matches_legacy_seven_digit_630_code(self):
        # The packaged fixture and the 37 pre-existing tests use 630XXXX
        # (three-digit prefix + four digits = seven total); the widened
        # regex must not stop matching this shorter, older format.
        self.assertEqual(INTERNAL_CODE.findall("6300001"), ["6300001"])

    def test_still_matches_legacy_four_digit_ic_code(self):
        self.assertEqual(INTERNAL_CODE.findall("IC-0006"), ["IC-0006"])

    def test_does_not_match_partial_code_embedded_in_longer_digit_run(self):
        # A 13-digit barcode that happens to contain "630010124" as a
        # substring must never be misread as the internal code
        # 630010124 -- there is no digit/non-digit boundary in the middle
        # of an unbroken run of digits, so \b correctly refuses to match
        # here. This is the explicit partial-code-match guard required by
        # the task brief.
        self.assertEqual(INTERNAL_CODE.findall("8630010124123"), [])

    def test_does_not_match_ic_prefix_without_boundary(self):
        self.assertEqual(INTERNAL_CODE.findall("STATIC-000648"), [])

    def test_does_not_overmatch_beyond_six_digits(self):
        # A seven-digit run after "IC-" is not a recognized code shape. Since
        # \b can never fire in the middle of an unbroken run of digits, a
        # greedy \d{4,6} backtracking through 6/5/4 digits still leaves
        # trailing digits before the next boundary every time -- the whole
        # match correctly fails rather than silently capturing a truncated,
        # wrong six-digit code.
        self.assertEqual(INTERNAL_CODE.findall("IC-0006481"), [])


# ---------------------------------------------------------------------------
# Codex adjudication fixes (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 11):
# 1. gate order -- ACTIVE_ALIAS must outrank TRADE_NAME_MATCH
# 2. confidence must be numeric [0,1], never a placeholder string
# 3. dosage-form contradiction guard (TABLET vs SYRUP/CREAM/DROPS)
# 4. generic/supplier tokens excluded; no auto-pick on a genuine tie
# ---------------------------------------------------------------------------
class GateOrderTests(TmpCacheTestCase):
    def test_active_alias_outranks_trade_name_match(self):
        # Two products both plausibly reachable via trade-name retrieval on
        # the same OCR text, but a human already approved an alias mapping
        # this exact supplier text to the OTHER one. The approved alias must
        # win -- an unapproved heuristic guess must never shadow it.
        products = [
            _product("IC-000648", "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S"),
            _product("IC-999999", "SOME OTHER MINIDIAB REPACK 5 MG 30 S"),
        ]
        alias_repo = _StaticAliasRepository(
            [
                {
                    "supplier_code": "WOOTHI",
                    "status": "ACTIVE",
                    "normalized_supplier_text": "MINIDIAB",
                    "ada_product_code": "IC-999999",
                }
            ]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=alias_repo)
        result = _predict(matcher, "MINIDIAB 5mg 2x15's", supplier_sku="844", supplier_code="WOOTHI")
        self.assertEqual(result["tier"], "ACTIVE_ALIAS")
        self.assertEqual(result["proposed_product_code"], "IC-999999")

    def test_trade_name_match_still_fires_when_no_alias_applies(self):
        products = [_product("IC-000648", "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S")]
        matcher = _build_matcher(self.tmp_root, products, repository=_StaticAliasRepository([]))
        result = _predict(matcher, "MINIDIAB 5mg 2x15's", supplier_sku="844", supplier_code="WOOTHI")
        self.assertEqual(result["tier"], "TRADE_NAME_MATCH")
        self.assertEqual(result["proposed_product_code"], "IC-000648")


class ExactNameBeforeTradeNameTests(TmpCacheTestCase):
    """Codex's second BLOCKED adjudication (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
    section 14): reproduces the two probes Codex used to prove the gate
    order and name-length tie-break were unsafe.

    Probe 1 ("ALPHA PLUS 10 MG"): "PLUS" was wrongly classified as a
    trade-name stopword, so trade-name retrieval could only see "ALPHA" for
    both the exact-name master row and an unrelated shorter row -- and
    because TRADE_NAME_MATCH still ran before EXACT_NAME, that tied,
    length-biased trade-name guess reached the answer before the
    deterministic full-string-exact check ever got a chance to fire.
    Fixed by (a) removing "PLUS" from the stopword set and (b) moving
    EXACT_NAME ahead of TRADE_NAME_MATCH in the cascade.

    Probe 2: separately, even with correct tokens, `tie_key()` used to break
    an otherwise-equal-evidence tie by preferring the SHORTER product name --
    silent, non-meaningful, and unsafe. Fixed by dropping name length from
    tie_key() entirely; equal evidence must now surface as an ambiguous,
    human-reviewed UNRESOLVED result instead of auto-picking either side.
    """

    def test_exact_full_name_match_wins_over_shorter_trade_name_candidate(self):
        products = [
            _product("TESTEX-001", "ALPHA PLUS 10 MG"),
            _product("TESTEX-002", "ALPHA 10 MG"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "ALPHA PLUS 10 MG")
        self.assertEqual(result["tier"], "EXACT_NAME")
        self.assertEqual(result["proposed_product_code"], "TESTEX-001")
        self.assertNotEqual(result["proposed_product_code"], "TESTEX-002")

    def test_trade_name_tie_is_not_broken_by_shorter_product_name(self):
        # Neither candidate's full name matches the OCR text exactly (both
        # carry a pack-size suffix the OCR text omits), so this exercises
        # TRADE_NAME_MATCH's own tie_key(), not EXACT_NAME. Both share the
        # single distinctive trade-name token ("ZYNOFAST") and both state
        # the same strength with no contradiction -- hits and attribute
        # agreement are exactly equal, and only the display-only pack-size
        # suffix makes one name one character longer than the other. Under
        # the old length-biased tie_key(), the shorter name silently won;
        # correct behavior is to treat this as ambiguous and let a human
        # choose.
        products = [
            _product("TESTLEN-001", "ZYNOFAST 50 MG 100 S"),
            _product("TESTLEN-002", "ZYNOFAST 50 MG 10 S"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "ZYNOFAST 50 MG")
        self.assertNotEqual(result["tier"], "EXACT_NAME")
        self.assertIsNone(
            result["proposed_product_code"],
            "equal hits + equal attribute agreement must stay ambiguous, "
            "not be decided by which product name happens to be shorter",
        )
        candidate_codes = {c["product_code"] for c in result["candidate_set"]}
        self.assertEqual(candidate_codes, {"TESTLEN-001", "TESTLEN-002"})


class ConfidenceContractTests(TmpCacheTestCase):
    def test_trade_name_match_confidence_is_numeric_in_unit_interval(self):
        matcher = _build_matcher(self.tmp_root, _REAL_MASTER_PRODUCTS)
        result = _predict(matcher, "MINIDIAB 5mg 2x15's", supplier_sku="844")
        self.assertEqual(result["tier"], "TRADE_NAME_MATCH")
        confidence = float(result["confidence"])
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)
        for candidate in result["candidate_set"]:
            score = float(candidate["score"])
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_trade_name_match_confidence_never_reaches_exact_tier_ceiling(self):
        # TRADE_NAME_MATCH always requires human confirmation -- its score
        # must stay visibly below the 1.0000 reserved for EXACT_CODE/
        # EXACT_BARCODE/ACTIVE_ALIAS/EXACT_NAME, so a reviewer scanning
        # confidence numbers can tell the tiers apart at a glance.
        matcher = _build_matcher(self.tmp_root, _REAL_MASTER_PRODUCTS)
        result = _predict(matcher, "MINIDIAB 5mg 2x15's", supplier_sku="844")
        self.assertLess(float(result["confidence"]), 1.0)


class DosageFormGuardTests(TmpCacheTestCase):
    def test_tablet_does_not_match_syrup_variant(self):
        products = [
            _product("TESTDF-001", "ZANTIX TABLET 150 MG 10 S"),
            _product("TESTDF-002", "ZANTIX SYRUP 150 MG 60 ML"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "ZANTIX TABLET 150 MG")
        self.assertEqual(result["proposed_product_code"], "TESTDF-001")
        self.assertNotEqual(result["proposed_product_code"], "TESTDF-002")

    def test_cream_does_not_match_drops_variant(self):
        products = [
            _product("TESTDF-003", "OPTIWASH CREAM 30 G"),
            _product("TESTDF-004", "OPTIWASH DROPS 10 ML"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "OPTIWASH DROPS 10 ML")
        self.assertEqual(result["proposed_product_code"], "TESTDF-004")
        self.assertNotEqual(result["proposed_product_code"], "TESTDF-003")

    def test_extract_attributes_reads_dosage_form(self):
        attrs = extract_attributes("ZANTIX TABLET 150 MG")
        self.assertIn("TABLET", attrs["dosage_forms"])

    def test_dosage_form_conflict_detected(self):
        a = extract_attributes("ZANTIX TABLET 150 MG")
        b = extract_attributes("ZANTIX SYRUP 150 MG")
        self.assertTrue(attributes_conflict(a, b))


class GenericTokenAndTieTests(TmpCacheTestCase):
    def test_supplier_own_name_token_excluded_from_retrieval(self):
        # Codex's probe: "MEDLINE UNKNOWN ITEM" on an invoice FROM Medline
        # must not let the supplier's own name alone select a product --
        # "MEDLINE" identifies WHO sold it, not WHAT was sold. Two
        # unrelated Medline-branded products exist; neither should be
        # confidently selected from this text.
        products = [
            _product("IC-002137", "MEDLINE LESFLAM DICLOFENAC POTASSIUM 50 MG 10 S"),
            _product("IC-000316", "MEDLINE OTHERDRUG PARACETAMOL 500 MG 10 S"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "MEDLINE UNKNOWN ITEM", supplier_code="MEDLINE")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)
        self.assertIsNone(
            result["proposed_product_code"],
            "must not arbitrarily pick one of two equally-unsupported Medline products",
        )

    def test_generic_manufacturer_token_alone_does_not_trigger_trade_name_match(self):
        # Six products share the word "LONGMED" (over the generic-token
        # threshold) and nothing else in the OCR text narrows it down --
        # TRADE_NAME_MATCH must refuse to fire from that alone (it must not
        # arbitrarily prefer product #0). Per the required gate order,
        # fuzzy suggestion is still allowed to offer a low-confidence,
        # human-review-required guess as the last-resort fallback -- that
        # is fuzzy doing its documented job, not the bug being guarded
        # against here.
        products = [_product(f"IC-LM{i:03d}", f"LONGMED PRODUCT{i} VARIANT {i} MG 10 S") for i in range(6)]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "LONGMED SOMETHING VAGUE")
        self.assertNotEqual(result["tier"], "TRADE_NAME_MATCH")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_genuine_tie_does_not_auto_pick_first_candidate(self):
        # Two candidates with the same distinctive token and identical
        # attribute agreement -- no principled basis to prefer one over the
        # other, so neither is proposed, but both remain visible for a
        # human to pick from.
        products = [
            _product("TESTTIE-001", "UNIQUEDRUGNAME 100 MG 10 S"),
            _product("TESTTIE-002", "UNIQUEDRUGNAME 100 MG 20 S"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "UNIQUEDRUGNAME 100 MG")
        self.assertIsNone(result["proposed_product_code"])
        candidate_codes = {c["product_code"] for c in result["candidate_set"]}
        self.assertEqual(candidate_codes, {"TESTTIE-001", "TESTTIE-002"})


class SupplierIdentifierFieldContractTests(TmpCacheTestCase):
    """Slice 1 -- field-contract separation (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
    section 16): internal product code, supplier SKU, and barcode are three
    different kinds of identifier and must never be conflated, even when one
    coincidentally has the shape of another. Every test below builds a
    catalog and OCR text deliberately unrelated to each other by every
    OTHER signal (name, trade-name tokens, fuzzy similarity) so a false
    positive can only happen through the specific conflation being guarded
    against here -- not through some other tier picking up the slack."""

    def test_supplier_sku_shaped_like_ic_code_is_never_read_as_internal_code(self):
        products = [_product("IC-000648", "UNRELATED CATALOG ENTRY NEVERMATCH QQQZZZ")]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "COMPLETELY DIFFERENT INVOICE TEXT ZYXWVUT", supplier_sku="IC-000648")
        self.assertNotEqual(result["tier"], "EXACT_CODE")
        self.assertNotEqual(result["proposed_product_code"], "IC-000648")

    def test_supplier_sku_shaped_like_630_code_is_never_read_as_internal_code(self):
        products = [_product("630010124", "UNRELATED CATALOG ENTRY NEVERMATCH QQQZZZ")]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "COMPLETELY DIFFERENT INVOICE TEXT ZYXWVUT", supplier_sku="630010124")
        self.assertNotEqual(result["tier"], "EXACT_CODE")
        self.assertNotEqual(result["proposed_product_code"], "630010124")

    def test_supplier_sku_echoed_in_free_ocr_text_does_not_shadow_active_alias(self):
        # Codex adjudication finding 1 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
        # section 17): real OCR text routinely echoes the printed supplier
        # SKU inline as part of the description/raw text -- excluding the
        # supplier_sku FIELD from the scan (Slice 1's first pass) is not
        # enough if that same digit run also appears in the free text and
        # happens to be a real, unrelated internal product code. A correct,
        # human-approved (supplier_code, SKU) alias must still win.
        products = [
            _product("630010124", "UNRELATED COINCIDENTAL PRODUCT NEVERMATCH"),
            _product("IC-RIGHT", "THE ACTUAL CORRECT PRODUCT NEVERMATCH"),
        ]
        alias_repo = _StaticAliasRepository(
            [{"supplier_code": "ACME", "status": "ACTIVE", "normalized_supplier_text": "630010124", "ada_product_code": "IC-RIGHT"}]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=alias_repo)
        # The OCR text on this line literally contains the printed SKU
        # ("630010124 SOME ITEM TEXT"), exactly like a real invoice row.
        result = _predict(matcher, "630010124 SOME ITEM TEXT", supplier_sku="630010124", supplier_code="ACME")
        self.assertEqual(result["tier"], "ACTIVE_ALIAS")
        self.assertEqual(result["proposed_product_code"], "IC-RIGHT")
        self.assertNotEqual(result["proposed_product_code"], "630010124")

    def test_explicit_internal_code_evidence_still_resolves(self):
        # The explicit-provenance path (evidence_json["internal_code_candidates"])
        # must still work and take priority over free-text scanning.
        products = [_product("IC-000648", "SOME PRODUCT NEVERMATCH")]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "COMPLETELY UNRELATED TEXT", internal_code_candidates=["IC-000648"])
        self.assertEqual(result["tier"], "EXACT_CODE")
        self.assertEqual(result["proposed_product_code"], "IC-000648")

    def test_supplier_sku_is_never_auto_treated_as_barcode(self):
        products = [_product("IC-BC001", "UNRELATED BARCODE CATALOG ENTRY QQQZZZ", barcode="8851234567890")]
        matcher = _build_matcher(self.tmp_root, products)
        # supplier_sku happens to equal the product's real barcode, but no
        # evidence_json barcode evidence is given -- must not resolve.
        result = _predict(matcher, "COMPLETELY DIFFERENT INVOICE TEXT ZYXWVUT", supplier_sku="8851234567890")
        self.assertNotEqual(result["tier"], "EXACT_BARCODE")
        self.assertNotEqual(result["proposed_product_code"], "IC-BC001")

    def test_supplier_sku_active_alias_selects_the_confirmed_product(self):
        products = [
            _product("IC-AAA", "PRODUCT A UNRELATED NAME"),
            _product("IC-ZZZ", "PRODUCT Z ANOTHER UNRELATED NAME"),
        ]
        alias_repo = _StaticAliasRepository(
            [{"supplier_code": "ACME", "status": "ACTIVE", "normalized_supplier_text": "SKU777", "ada_product_code": "IC-AAA"}]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=alias_repo)
        # Description text is deliberately generic/unrelated to either
        # product's name -- only the (supplier_code, SKU) alias resolves it.
        result = _predict(matcher, "GENERIC INVOICE LINE TEXT", supplier_sku="SKU777", supplier_code="ACME")
        self.assertEqual(result["tier"], "ACTIVE_ALIAS")
        self.assertEqual(result["proposed_product_code"], "IC-AAA")
        self.assertEqual(result["candidate_set"][0]["product_code"], "IC-AAA")

    def test_same_sku_from_different_suppliers_can_point_to_different_products(self):
        products = [
            _product("IC-AAA", "PRODUCT A UNRELATED NAME"),
            _product("IC-BBB", "PRODUCT B UNRELATED NAME"),
        ]
        alias_repo = _StaticAliasRepository(
            [
                {"supplier_code": "ACME", "status": "ACTIVE", "normalized_supplier_text": "SKU777", "ada_product_code": "IC-AAA"},
                {"supplier_code": "ZENITH", "status": "ACTIVE", "normalized_supplier_text": "SKU777", "ada_product_code": "IC-BBB"},
            ]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=alias_repo)
        result_acme = _predict(matcher, "GENERIC INVOICE LINE TEXT", supplier_sku="SKU777", supplier_code="ACME")
        result_zenith = _predict(matcher, "GENERIC INVOICE LINE TEXT", supplier_sku="SKU777", supplier_code="ZENITH")
        self.assertEqual(result_acme["proposed_product_code"], "IC-AAA")
        self.assertEqual(result_zenith["proposed_product_code"], "IC-BBB")


class InternalCodeTextMatchTests(TmpCacheTestCase):
    """Slice 1 remediation round 2 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section
    18, Codex's second Slice-1 re-adjudication): EXACT_CODE auto-confirms
    ONLY from explicit-provenance evidence_json["internal_code_candidates"].
    A digit run found by scanning free OCR text -- even when supplier_sku is
    missing/unparsed, which is exactly the residual gap Codex's first probe
    demonstrated -- is downgraded to the new INTERNAL_CODE_TEXT_MATCH tier:
    it may still be proposed, but it is never auto-confirmable and always
    requires human confirmation. Explicit internal-code evidence that
    resolves to more than one real product must quarantine, exactly like
    conflicting barcode evidence."""

    def test_missing_supplier_sku_free_text_code_hit_is_never_auto_confirmed(self):
        # This is the exact residual gap from Codex's first probe: the
        # earlier "reject if it equals supplier_sku" guard only protects a
        # line where supplier_sku was actually parsed. Here supplier_sku is
        # None (unparsed/missing) -- the digit run must STILL not
        # auto-confirm.
        products = [_product("630010124", "UNRELATED COINCIDENTAL PRODUCT")]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "630010124 SOME ITEM DESCRIPTION TEXT", supplier_sku=None)
        self.assertNotEqual(result["tier"], "EXACT_CODE")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)
        self.assertEqual(result["tier"], "INTERNAL_CODE_TEXT_MATCH")
        self.assertEqual(result["proposed_product_code"], "630010124")
        self.assertTrue(result["provenance"]["human_confirmation_required"])

    def test_active_alias_still_outranks_a_downgraded_free_text_code_hit(self):
        products = [
            _product("630010124", "UNRELATED COINCIDENTAL PRODUCT"),
            _product("IC-RIGHT", "THE ACTUAL CORRECT PRODUCT"),
        ]
        alias_repo = _StaticAliasRepository(
            [{"supplier_code": "ACME", "status": "ACTIVE", "normalized_supplier_text": "630010124", "ada_product_code": "IC-RIGHT"}]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=alias_repo)
        result = _predict(matcher, "630010124 SOME ITEM TEXT", supplier_sku=None, supplier_code="ACME")
        self.assertEqual(result["tier"], "ACTIVE_ALIAS")
        self.assertEqual(result["proposed_product_code"], "IC-RIGHT")

    def test_explicit_internal_code_conflict_quarantines_the_line(self):
        products = [
            _product("IC-000001", "CONFLICT PRODUCT ONE"),
            _product("IC-000002", "CONFLICT PRODUCT TWO"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "UNRELATED TEXT", internal_code_candidates=["IC-000001", "IC-000002"])
        self.assertEqual(result["tier"], "UNRESOLVED")
        self.assertIsNone(result["proposed_product_code"])
        self.assertIn("INTERNAL_CODE_CONFLICT_MULTIPLE_PRODUCTS", result["reason_codes"])
        candidate_codes = {c["product_code"] for c in result["candidate_set"]}
        self.assertEqual(candidate_codes, {"IC-000001", "IC-000002"})

    def test_explicit_internal_code_conflict_is_not_overridden_by_a_matching_name(self):
        products = [
            _product("IC-000001", "ZYNTREX FORTE 50 MG"),
            _product("IC-000002", "SOME OTHER PRODUCT"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "ZYNTREX FORTE 50 MG", internal_code_candidates=["IC-000001", "IC-000002"])
        self.assertEqual(result["tier"], "UNRESOLVED")
        self.assertIsNone(result["proposed_product_code"])


class InputHashAuditContractTests(TmpCacheTestCase):
    """Slice 1 remediation round 3 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
    section 19, Codex's fourth Slice-1 re-adjudication): `input_hash` must
    change whenever any input that could change the outcome changes. Codex's
    exact probe -- "no evidence" (UNRESOLVED) vs "explicit internal-code
    evidence" (EXACT_CODE) on the same OCR text produced the IDENTICAL
    hash -- is reproduced here directly, plus the same shape for barcode
    evidence, plus a positive control proving identical inputs still
    produce identical hashes (this must not become a hash that changes on
    every call for irrelevant reasons)."""

    def test_identical_evidence_produces_identical_hash(self):
        products = [_product("IC-STABLE", "STABLE HASH TEST PRODUCT")]
        matcher = _build_matcher(self.tmp_root, products)
        first = _predict(matcher, "SOME INVOICE LINE TEXT", supplier_sku="SKU-1", supplier_code="ACME")
        second = _predict(matcher, "SOME INVOICE LINE TEXT", supplier_sku="SKU-1", supplier_code="ACME")
        self.assertEqual(first["input_hash"], second["input_hash"])

    def test_no_evidence_vs_explicit_internal_code_evidence_changes_hash(self):
        # This is Codex's exact reported probe: same base text, only the
        # presence of explicit internal-code evidence differs, and the tier
        # differs (UNRESOLVED vs EXACT_CODE) -- input_hash must differ too.
        products = [_product("IC-000648", "SOME PRODUCT NEVERMATCH")]
        matcher = _build_matcher(self.tmp_root, products)
        without_evidence = _predict(matcher, "COMPLETELY UNRELATED TEXT")
        with_evidence = _predict(matcher, "COMPLETELY UNRELATED TEXT", internal_code_candidates=["IC-000648"])
        self.assertEqual(without_evidence["tier"], "UNRESOLVED")
        self.assertEqual(with_evidence["tier"], "EXACT_CODE")
        self.assertNotEqual(without_evidence["input_hash"], with_evidence["input_hash"])

    def test_no_evidence_vs_explicit_barcode_evidence_changes_hash(self):
        products = [_product("IC-BC777", "SOME PRODUCT NEVERMATCH", barcode="8850000000777")]
        matcher = _build_matcher(self.tmp_root, products)
        without_evidence = _predict(matcher, "COMPLETELY UNRELATED TEXT")
        with_evidence = _predict(matcher, "COMPLETELY UNRELATED TEXT", barcode_candidates=["8850000000777"])
        self.assertEqual(without_evidence["tier"], "UNRESOLVED")
        self.assertEqual(with_evidence["tier"], "EXACT_BARCODE")
        self.assertNotEqual(without_evidence["input_hash"], with_evidence["input_hash"])

    def test_different_supplier_sku_changes_hash_even_with_identical_text(self):
        products = [_product("IC-SKU1", "SOME PRODUCT NEVERMATCH")]
        matcher = _build_matcher(self.tmp_root, products)
        first = _predict(matcher, "SAME TEXT EVERY TIME", supplier_sku="SKU-AAA")
        second = _predict(matcher, "SAME TEXT EVERY TIME", supplier_sku="SKU-BBB")
        self.assertNotEqual(first["input_hash"], second["input_hash"])

    def test_unit_final_change_alone_changes_hash_and_proposed_unit(self):
        # Slice 1 remediation round 4 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
        # section 20, Codex's fifth Slice-1 re-adjudication): Codex's exact
        # reported probe -- unit_final "BOX" -> "EACH" changes
        # proposed_unit_code but input_hash did not change. Everything else
        # held fixed (explicit internal-code evidence guarantees a
        # deterministic EXACT_CODE selection regardless of description text).
        products = [
            _product(
                "IC-UNIT",
                "UNIT TEST PRODUCT",
                units=[
                    {"unit_code": "BOX", "factor": "1", "active": True},
                    {"unit_code": "EACH", "factor": "1", "active": True},
                ],
            )
        ]
        matcher = _build_matcher(self.tmp_root, products)
        as_box = _predict(matcher, "UNIT TEST TEXT", internal_code_candidates=["IC-UNIT"], unit_final="BOX")
        as_each = _predict(matcher, "UNIT TEST TEXT", internal_code_candidates=["IC-UNIT"], unit_final="EACH")
        self.assertEqual(as_box["proposed_unit_code"], "BOX")
        self.assertEqual(as_each["proposed_unit_code"], "EACH")
        self.assertNotEqual(as_box["input_hash"], as_each["input_hash"])

    def test_description_final_change_alone_changes_hash(self):
        # Field-boundary regression: description_final and raw_ocr_text are
        # hashed separately now -- changing ONLY description_final (with
        # raw_ocr_text held fixed) must still change the hash.
        products = [_product("IC-FIELD1", "FIELD BOUNDARY TEST PRODUCT ONE")]
        matcher = _build_matcher(self.tmp_root, products)
        first = _predict(matcher, "DESCRIPTION VARIANT ONE", raw_ocr_text="SHARED RAW OCR TEXT")
        second = _predict(matcher, "DESCRIPTION VARIANT TWO", raw_ocr_text="SHARED RAW OCR TEXT")
        self.assertNotEqual(first["input_hash"], second["input_hash"])

    def test_description_final_and_raw_ocr_text_boundary_shift_does_not_collide(self):
        # A stronger, targeted version of the two tests above: these two
        # scenarios have DIFFERENT (description_final, raw_ocr_text) pairs
        # that, if the two fields were still joined into one blended string
        # before hashing (the pre-remediation approach), would normalize to
        # the IDENTICAL joined text -- "FOO BAR" + "BAZ" and "FOO" +
        # "BAR BAZ" both join/normalize to "FOO BAR BAZ". Hashing the two
        # fields independently must NOT collide here, proving the split is
        # real field-identity separation and not just "the same characters,
        # differently spaced."
        products = [_product("IC-FIELD3", "FIELD BOUNDARY COLLISION TEST PRODUCT")]
        matcher = _build_matcher(self.tmp_root, products)
        split_a = _predict(matcher, "FOO BAR", raw_ocr_text="BAZ")
        split_b = _predict(matcher, "FOO", raw_ocr_text="BAR BAZ")
        self.assertNotEqual(split_a["input_hash"], split_b["input_hash"])

    def test_raw_ocr_text_change_alone_changes_hash(self):
        # The mirror case: changing ONLY raw_ocr_text (description_final
        # held fixed) must also change the hash -- proves the two fields are
        # genuinely independent inputs to the hash, not just one of them
        # driving it while the other is silently ignored.
        products = [_product("IC-FIELD2", "FIELD BOUNDARY TEST PRODUCT TWO")]
        matcher = _build_matcher(self.tmp_root, products)
        first = _predict(matcher, "SHARED DESCRIPTION TEXT", raw_ocr_text="RAW OCR VARIANT ONE")
        second = _predict(matcher, "SHARED DESCRIPTION TEXT", raw_ocr_text="RAW OCR VARIANT TWO")
        self.assertNotEqual(first["input_hash"], second["input_hash"])

    def test_evidence_json_as_dict_or_persisted_json_string_produce_the_same_hash(self):
        # decode_line_evidence() already proved dict and JSON-string inputs
        # produce the same MATCHING result (Slice 1 remediation round 1) --
        # this proves they also produce the same input_hash, since the hash
        # is built from the decoded/normalized evidence, never from the raw
        # evidence_json value itself.
        products = [_product("IC-BC900", "EVIDENCE SHAPE TEST PRODUCT", barcode="8859990000009")]
        matcher = _build_matcher(self.tmp_root, products)
        as_dict = _predict(matcher, "UNRELATED TEXT", evidence_json={"barcode_candidates": ["8859990000009"]})
        as_json_string = _predict(matcher, "UNRELATED TEXT", evidence_json=canonical_json({"barcode_candidates": ["8859990000009"]}))
        self.assertEqual(as_dict["tier"], "EXACT_BARCODE")
        self.assertEqual(as_json_string["tier"], "EXACT_BARCODE")
        self.assertEqual(as_dict["input_hash"], as_json_string["input_hash"])

    def test_evidence_list_order_does_not_change_hash(self):
        # Evidence CONTENT, not array order, is what the hash must reflect --
        # the same conflicting-barcode evidence in a different array order
        # must produce the identical hash (and the identical quarantine
        # outcome).
        products = [
            _product("IC-ORD-A", "ORDER TEST PRODUCT A", barcode="1111111111199"),
            _product("IC-ORD-B", "ORDER TEST PRODUCT B", barcode="2222222222299"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        forward = _predict(matcher, "UNRELATED TEXT", barcode_candidates=["1111111111199", "2222222222299"])
        reversed_order = _predict(matcher, "UNRELATED TEXT", barcode_candidates=["2222222222299", "1111111111199"])
        self.assertEqual(forward["tier"], "UNRESOLVED")
        self.assertEqual(reversed_order["tier"], "UNRESOLVED")
        self.assertEqual(forward["input_hash"], reversed_order["input_hash"])


class BarcodeEvidenceTests(TmpCacheTestCase):
    """Slice 1 -- explicit barcode evidence (evidence_json["barcode_candidates"]
    only, never supplier_sku or free text). Covers real-barcode resolution,
    unknown/new-barcode non-guessing, and multi-product conflict quarantine."""

    def test_explicit_barcode_evidence_still_resolves_a_real_barcode(self):
        products = [_product("IC-BC001", "REAL BARCODE PRODUCT NEVERMATCH", barcode="8851234567890")]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "COMPLETELY UNRELATED TEXT ZYXWVUT", barcode_candidates=["8851234567890"])
        self.assertEqual(result["tier"], "EXACT_BARCODE")
        self.assertEqual(result["proposed_product_code"], "IC-BC001")
        self.assertEqual(result["candidate_set"][0]["product_code"], "IC-BC001")

    def test_barcode_evidence_resolves_when_evidence_json_is_a_persisted_json_string(self):
        # Codex adjudication finding 2 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md
        # section 17): `document_lines.evidence_json` is a TEXT column --
        # Repository.list_lines() returns it as the raw JSON STRING written
        # by canonical_json() at import time, never a Python dict. Every
        # other test in this file builds `line["evidence_json"]` as an
        # already-decoded dict directly, which skips that boundary entirely
        # and gives a false-green result. This test goes through the exact
        # shape the real persistence layer produces.
        products = [_product("IC-BC003", "PERSISTED EVIDENCE PRODUCT NEVERMATCH", barcode="8859999999999")]
        matcher = _build_matcher(self.tmp_root, products)
        document = {"id": "doc-1", "supplier_code": "UNKNOWN"}
        line = {
            "id": "line-1",
            "supplier_sku": None,
            "description_final": "COMPLETELY UNRELATED TEXT ZYXWVUT",
            "raw_ocr_text": "COMPLETELY UNRELATED TEXT ZYXWVUT",
            "unit_final": "",
            "evidence_json": canonical_json({"barcode_candidates": ["8859999999999"]}),
        }
        result = matcher._predict(document, line, {"source": "test"})
        self.assertEqual(result["tier"], "EXACT_BARCODE")
        self.assertEqual(result["proposed_product_code"], "IC-BC003")

    def test_unknown_barcode_does_not_get_guessed(self):
        products = [_product("IC-BC002", "SOME OTHER PRODUCT NEVERMATCH", barcode="8850000000000")]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "COMPLETELY UNRELATED TEXT ZYXWVUT", barcode_candidates=["9999999999999"])
        self.assertNotEqual(result["tier"], "EXACT_BARCODE")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)

    def test_conflicting_barcode_candidates_quarantine_the_line(self):
        products = [
            _product("IC-CONF-A", "CONFLICT PRODUCT A", barcode="1111111111111"),
            _product("IC-CONF-B", "CONFLICT PRODUCT B", barcode="2222222222222"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "UNRELATED TEXT", barcode_candidates=["1111111111111", "2222222222222"])
        self.assertEqual(result["tier"], "UNRESOLVED")
        self.assertIsNone(result["proposed_product_code"])
        self.assertIn("BARCODE_CONFLICT_MULTIPLE_PRODUCTS", result["reason_codes"])
        candidate_codes = {c["product_code"] for c in result["candidate_set"]}
        self.assertEqual(candidate_codes, {"IC-CONF-A", "IC-CONF-B"})

    def test_conflicting_barcode_quarantine_is_not_overridden_by_a_matching_name(self):
        # Even when the description text WOULD otherwise resolve cleanly via
        # EXACT_NAME/TRADE_NAME_MATCH, an active barcode contradiction must
        # still win -- no weaker tier is allowed to paper over it.
        products = [
            _product("IC-CONF-A", "ZYNTREX FORTE 50 MG", barcode="1111111111111"),
            _product("IC-CONF-B", "SOME OTHER PRODUCT", barcode="2222222222222"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "ZYNTREX FORTE 50 MG", barcode_candidates=["1111111111111", "2222222222222"])
        self.assertEqual(result["tier"], "UNRESOLVED")
        self.assertIsNone(result["proposed_product_code"])


class BilingualNameMatchingTests(TmpCacheTestCase):
    """Slice 2 (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22): Thai,
    English, and mixed-script trade-name retrieval, plus the new
    SPELLING_ALIAS and SPELLING_SUGGESTION ("คุณหมายถึง...หรือไม่") tiers.
    Covers the 11 minimum acceptance scenarios from the Slice 2 kickoff,
    numbered in comments to match."""

    def test_slice2_uses_a_new_ruleset_version(self):
        self.assertEqual(ProductMatcher.RULESET_VERSION, "layer-f-v6")

    def test_1_minidiab_english_and_thai_find_same_product(self):
        products = [
            _product(
                "IC-000648",
                "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
                name_eng="PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
                name_thai="ไฟเซอร์ มินิเดียบ ไกลพิไซด์ 5 มก 30 เม็ด",
            )
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result_eng = _predict(matcher, "MINIDIAB 5mg 2x15's")
        result_thai = _predict(matcher, "มินิเดียบ 5 มก")
        self.assertEqual(result_eng["proposed_product_code"], "IC-000648")
        self.assertEqual(result_thai["proposed_product_code"], "IC-000648")

    def test_2_lesflam_english_and_thai_find_same_product(self):
        products = [
            _product(
                "IC-002137",
                "MEDLINE LESFLAM DICLOFENAC POTASSIUM 50 MG 10 S",
                name_eng="MEDLINE LESFLAM DICLOFENAC POTASSIUM 50 MG 10 S",
                name_thai="เมดไลน์ เลสแฟลม ไดโคลฟีแนค โพแทสเซียม 50 มก 10 เม็ด",
            )
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result_eng = _predict(matcher, "LESFLAM 50 MG.TAB.10X10'S (Diclofenac Potassium 50 mg)")
        result_thai = _predict(matcher, "เลสแฟลม 50 มก")
        self.assertEqual(result_eng["proposed_product_code"], "IC-002137")
        self.assertEqual(result_thai["proposed_product_code"], "IC-002137")

    def test_3_thai_and_english_mixed_in_one_line_finds_same_product(self):
        products = [
            _product(
                "IC-000648",
                "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
                name_eng="PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
                name_thai="ไฟเซอร์ มินิเดียบ ไกลพิไซด์ 5 มก 30 เม็ด",
            )
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "มินิเดียบ MINIDIAB 5mg")
        self.assertEqual(result["proposed_product_code"], "IC-000648")

    def test_4_single_typo_suggests_did_you_mean_without_auto_confirm(self):
        products = [
            _product(
                "IC-000648",
                "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
                name_eng="PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
            )
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "MINIDIAP 5mg")
        self.assertEqual(result["tier"], "SPELLING_SUGGESTION")
        self.assertEqual(result["proposed_product_code"], "IC-000648")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)
        self.assertTrue(result["provenance"]["human_confirmation_required"])
        self.assertTrue(any(reason.startswith("DID_YOU_MEAN:") for reason in result["reason_codes"]))

    def test_5_presolin_150_never_selects_300(self):
        products = [
            _product("IC-002001", "MEDLINE PRESOLIN IRBESARTAN 150 MG 10 S", name_eng="MEDLINE PRESOLIN IRBESARTAN 150 MG 10 S"),
            _product("IC-002002", "MEDLINE PRESOLIN IRBESARTAN 300 MG 10 S", name_eng="MEDLINE PRESOLIN IRBESARTAN 300 MG 10 S"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "PRESOLIN 150 MG.TAB.10X10'S (Irbesartan 150 mg)")
        self.assertEqual(result["proposed_product_code"], "IC-002001")
        self.assertNotEqual(result["proposed_product_code"], "IC-002002")

    def test_6_tablet_never_selects_syrup_cream_or_drop_thai_or_english(self):
        products = [
            _product("TESTDF-T01", "ZANTIX TABLET 150 MG 10 S", name_eng="ZANTIX TABLET 150 MG 10 S", name_thai="แซนทิกซ์ เม็ด 150 มก"),
            _product("TESTDF-T02", "ZANTIX SYRUP 150 MG 60 ML", name_eng="ZANTIX SYRUP 150 MG 60 ML", name_thai="แซนทิกซ์ น้ำเชื่อม 150 มก"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result_eng = _predict(matcher, "ZANTIX TABLET 150 MG")
        result_thai = _predict(matcher, "แซนทิกซ์ เม็ด 150 มก")
        self.assertEqual(result_eng["proposed_product_code"], "TESTDF-T01")
        self.assertEqual(result_thai["proposed_product_code"], "TESTDF-T01")

    def test_7_supplier_name_alone_never_selects_a_product(self):
        products = [
            _product("IC-002137", "MEDLINE LESFLAM DICLOFENAC POTASSIUM 50 MG 10 S", name_eng="MEDLINE LESFLAM DICLOFENAC POTASSIUM 50 MG 10 S"),
            _product("IC-000316", "MEDLINE OTHERDRUG PARACETAMOL 500 MG 10 S", name_eng="MEDLINE OTHERDRUG PARACETAMOL 500 MG 10 S"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "MEDLINE UNKNOWN ITEM", supplier_code="MEDLINE")
        self.assertNotIn(result["tier"], AUTO_CONFIRMABLE_TIERS)
        self.assertIsNone(result["proposed_product_code"])

    def test_8_thai_name_differing_only_by_spacing_still_found(self):
        products = [
            _product(
                "IC-000648",
                "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
                name_eng="PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S",
                name_thai="ไฟเซอร์  มินิเดียบ   ไกลพิไซด์ 5 มก 30 เม็ด",
            )
        ]
        matcher = _build_matcher(self.tmp_root, products)
        # Query text has different (single-space) spacing from the master
        # name's irregular double/triple spacing above -- normalize_product_text
        # collapses both to the same token stream either way.
        result = _predict(matcher, "มินิเดียบ 5 มก")
        self.assertEqual(result["proposed_product_code"], "IC-000648")

    def test_9_similar_name_multiple_products_is_unresolved_with_top_candidates(self):
        # Two products genuinely tied on the only distinctive shared token
        # ("MATRACOL"; "SUSPENSION" is a dosage-form stopword, excluded from
        # retrieval on both sides) -- there is no principled basis to prefer
        # either, so the line must come back UNRESOLVED, not a guess, while
        # BOTH still appear in candidate_set for a human to pick from.
        products = [
            _product("TESTMX-001", "MATRACOL SUSPENSION 200 ML", name_eng="MATRACOL SUSPENSION 200 ML"),
            _product("TESTMX-002", "MATRACOL FORTE SUSPENSION 200 ML", name_eng="MATRACOL FORTE SUSPENSION 200 ML"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        # "BATCH99" keeps this from exactly matching either full master name
        # (which would resolve via EXACT_NAME before trade-name retrieval
        # even runs) without affecting the tie -- it contains a digit, so
        # extract_trade_name_tokens excludes it from retrieval entirely.
        result = _predict(matcher, "MATRACOL SUSPENSION 200 ML BATCH99")
        self.assertEqual(result["tier"], "UNRESOLVED")
        self.assertIsNone(result["proposed_product_code"])
        candidate_codes = {c["product_code"] for c in result["candidate_set"]}
        self.assertEqual(candidate_codes, {"TESTMX-001", "TESTMX-002"})

    def test_10_raw_master_name_is_never_modified(self):
        raw_name_eng = "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S"
        raw_name_thai = "ไฟเซอร์ มินิเดียบ ไกลพิไซด์ 5 มก 30 เม็ด"
        products = [_product("IC-000648", raw_name_eng, name_eng=raw_name_eng, name_thai=raw_name_thai)]
        matcher = _build_matcher(self.tmp_root, products)
        _predict(matcher, "มินิเดียบ MINIDIAB 5mg")  # exercise both retrieval paths
        stored = matcher.cache.get_product("IC-000648")
        self.assertEqual(stored["name_eng"], raw_name_eng)
        self.assertEqual(stored["name_thai"], raw_name_thai)

    def test_11_slice1_active_alias_still_outranks_spelling_alias(self):
        products = [
            _product("IC-AAA", "PRODUCT A UNRELATED NAME", name_eng="PRODUCT A UNRELATED NAME"),
            _product("IC-ZZZ", "PRODUCT Z ANOTHER UNRELATED NAME", name_eng="PRODUCT Z ANOTHER UNRELATED NAME"),
        ]
        repo = _StaticAliasRepository(
            [{"supplier_code": "ACME", "status": "ACTIVE", "normalized_supplier_text": "SKU777", "ada_product_code": "IC-AAA"}],
            name_aliases=[{"normalized_text": "MINIDIAB", "ada_product_code": "IC-ZZZ", "status": "ACTIVE"}],
        )
        matcher = _build_matcher(self.tmp_root, products, repository=repo)
        result = _predict(matcher, "GENERIC INVOICE LINE TEXT", supplier_sku="SKU777", supplier_code="ACME")
        self.assertEqual(result["tier"], "ACTIVE_ALIAS")
        self.assertEqual(result["proposed_product_code"], "IC-AAA")

    def test_spelling_alias_auto_confirms_and_outranks_did_you_mean(self):
        products = [
            _product("IC-000648", "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S", name_eng="PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S"),
        ]
        repo = _StaticAliasRepository(
            [],
            name_aliases=[{"normalized_text": "มินิเดียบ", "ada_product_code": "IC-000648", "status": "ACTIVE"}],
        )
        matcher = _build_matcher(self.tmp_root, products, repository=repo)
        result = _predict(matcher, "มินิเดียบ 5 มก")
        self.assertEqual(result["tier"], "SPELLING_ALIAS")
        self.assertEqual(result["proposed_product_code"], "IC-000648")
        self.assertIn(result["tier"], AUTO_CONFIRMABLE_TIERS)
        self.assertFalse(result["provenance"]["human_confirmation_required"])

    def test_spelling_alias_requires_a_whole_normalized_phrase(self):
        products = [_product("IC-PARA", "PARA PRODUCT", name_eng="PARA PRODUCT")]
        repo = _StaticAliasRepository(
            [], name_aliases=[{"normalized_text": "PARA", "ada_product_code": "IC-PARA", "status": "ACTIVE"}]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=repo)
        result = _predict(matcher, "XPARAX UNKNOWN")
        self.assertNotEqual(result["tier"], "SPELLING_ALIAS")
        self.assertTrue(result["provenance"]["human_confirmation_required"])

    def test_spelling_alias_strength_conflict_blocks_auto_confirm_and_weaker_tiers(self):
        products = [
            _product("IC-MINI-5", "MINIDIAB 5 MG TABLET", name_eng="MINIDIAB 5 MG TABLET"),
            _product("IC-MINI-10", "MINIDIAB 10 MG TABLET", name_eng="MINIDIAB 10 MG TABLET"),
        ]
        repo = _StaticAliasRepository(
            [], name_aliases=[{"normalized_text": "MINIDIAB", "ada_product_code": "IC-MINI-5", "status": "ACTIVE"}]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=repo)
        result = _predict(matcher, "MINIDIAB 10 MG TABLET BATCH99")
        self.assertEqual(result["tier"], "UNRESOLVED")
        self.assertIsNone(result["proposed_product_code"])
        self.assertIn("SPELLING_ALIAS_ATTRIBUTE_CONFLICT", result["reason_codes"])
        self.assertEqual(result["candidate_set"][0]["product_code"], "IC-MINI-5")

    def test_valid_spelling_alias_outranks_trade_name_heuristic(self):
        products = [
            _product("IC-HUMAN", "HUMAN APPROVED PRODUCT 10 MG TABLET", name_eng="HUMAN APPROVED PRODUCT 10 MG TABLET"),
            _product("IC-HEUR", "MINIDIAB 10 MG TABLET", name_eng="MINIDIAB 10 MG TABLET"),
        ]
        repo = _StaticAliasRepository(
            [], name_aliases=[{"normalized_text": "TYPOALIAS", "ada_product_code": "IC-HUMAN", "status": "ACTIVE"}]
        )
        matcher = _build_matcher(self.tmp_root, products, repository=repo)
        result = _predict(matcher, "MINIDIAB 10 MG TABLET TYPOALIAS")
        self.assertEqual(result["tier"], "SPELLING_ALIAS")
        self.assertEqual(result["proposed_product_code"], "IC-HUMAN")

    def test_candidate_set_always_agrees_with_proposed_product_code_bilingual(self):
        # Slice 1's consistency guarantee must keep holding for every new
        # Slice 2 tier too.
        products = [
            _product("IC-000648", "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S", name_eng="PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        result = _predict(matcher, "MINIDIAP 5mg")  # SPELLING_SUGGESTION path
        self.assertEqual(result["candidate_set"][0]["product_code"], result["proposed_product_code"])

    def test_whole_catalog_fuzzy_fallback_never_proposes_a_pack_dimension_contradiction(self):
        # Found via the real ~6,665-product Phase E rerun (Slice 2, see
        # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22): the whole-catalog
        # SequenceMatcher fuzzy fallback never ran the attribute-contradiction
        # guard at all (only trade-name retrieval did), so it proposed a
        # 3x3-INCH wound dressing for a line that explicitly stated
        # "10x20cm" -- a real, stated pack-size contradiction that should
        # have blocked the candidate in ANY tier, not just trade-name
        # retrieval.
        products = [
            _product("IC-RIGHT-SIZE", "GAUZE PAD WOUND DRESSING 10X20 CM", name_eng="GAUZE PAD WOUND DRESSING 10X20 CM"),
            _product("IC-WRONG-SIZE", "GAUZE PAD WOUND DRESSING 3X3 INC", name_eng="GAUZE PAD WOUND DRESSING 3X3 INC"),
        ]
        matcher = _build_matcher(self.tmp_root, products)
        # "DRSNG" is the only word long/specific enough to be extracted as a
        # trade-name token, but it doesn't appear in EITHER candidate's
        # name, so trade-name retrieval finds nothing and the line falls
        # all the way through to the whole-catalog fuzzy sweep -- the exact
        # code path the real invoice line took. "10X20" makes this line's
        # own stated pack dimension explicit (and, pre-fix, high enough
        # character-level similarity to the WRONG 3X3 product to have been
        # proposed by the unguarded fuzzy fallback).
        result = _predict(matcher, "GAZ PAD DRSNG 10X20 CM SET")
        candidate_codes = {c["product_code"] for c in result["candidate_set"]}
        self.assertNotIn("IC-WRONG-SIZE", candidate_codes)
        self.assertNotEqual(result["proposed_product_code"], "IC-WRONG-SIZE")


if __name__ == "__main__":
    unittest.main()
