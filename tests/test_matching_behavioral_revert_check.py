"""Standalone behavioral revert-check for the Layer F trade-name matcher.

Deliberately imports ONLY symbols that exist in both the pre-fix and
post-fix `matching.py` (`ProductMatcher`, `normalize_product_text`) plus
generic infrastructure (`AppProfile`, `AdaReferenceCache`) that never
changed. This file must import cleanly against EITHER version of
matching.py -- the whole point is that running it against the original,
unfixed matcher fails via real assertion mismatches (wrong/no product
selected), not via ImportError on a helper function that doesn't exist yet.

Codex's adjudication (docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 11, finding
5) correctly identified that `tests/test_matching.py`'s revert-check was
weak for exactly this reason: that file imports `attributes_conflict`,
`extract_attributes`, and `extract_trade_name_tokens` at module level, so
reverting matching.py to the original makes the whole module fail to
import -- proving file-shape dependency, not behavior. This file is the
fix: run it against the original matching.py and it fails on real
assertions (wrong product selected, or no candidate at all); run it against
the fixed matching.py and it passes.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ocr_inbound.config import AppProfile
from ocr_inbound.ada_read import AdaReferenceCache
from ocr_inbound.matching import ProductMatcher, normalize_product_text


class _NoAliasRepository:
    def list_aliases(self, supplier_code):
        return []


def _product(code, name, *, barcode=None, ingredient="", strength="", size="", units=None):
    return {
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


_REAL_MASTER_PRODUCTS = [
    _product("IC-000648", "PFIZER MINIDIAB GLIPIZIDE 5 MG 30 S"),
    _product("IC-002268", "BERLIN ISOTRATE ISOSORBIDE DINITRATE 10 MG 10 S"),
    _product("IC-002001", "MEDLINE PRESOLIN IRBESARTAN 150 MG 10 S"),
    _product("IC-002002", "MEDLINE PRESOLIN IRBESARTAN 300 MG 10 S"),
    _product("IC-001609", "APROVEL 150 MG. (IRBESARTAN) 28 S"),
    _product("IC-004874", "ABBVIE RELESTAT OLOPATADINE 0.05% 5 ML"),
    _product("IC-002137", "MEDLINE LESFLAM DICLOFENAC POTASSIUM 50 MG 10 S"),
    _product("IC-001962", "CHUMCHON CODIPHEN DIPHENHYDRAMINE 50 MG 10 S"),
    # Real decoy/competitor products that actually won on the live
    # ~6,700-product master under the pre-fix whole-string fuzzy ranking
    # (see SONNET_TRADE_NAME_MATCHER_RESULTS.json / FULL_MASTER_LAYER_F_
    # RESULTS.json). Without these, a small clean fixture lets the old
    # matcher "accidentally" pass several of the scenarios below just
    # because nothing plausible-looking competes -- that would understate
    # how broken whole-string fuzzy ranking actually is at real scale.
    _product("IC-001754", "ACNOTIN ISOTRETINOIN 10 MG 10 S."),
    _product("IC-000205", "GPO AMITRIPTYLINE 10 MG 10 S"),
    _product("IC-001593", "APROVEL 300 MG. (IRBESARTAN) 28 S"),
    _product("IC-002993", "BEDSIDE TABLE ABS 1 S"),
    _product("630030164", "CLINDA M 15 ML"),
    _product("IC-003658", "MEGA DOFLAM DICLOFENAC POTASSIUM 50 MG 10 S"),
    _product("IC-000103", "สามัญคาลาไมน์ตราเสือดาว 60 มล"),
]


def _build_matcher(tmp_root: Path) -> ProductMatcher:
    profile = AppProfile(
        environment="staging",
        root=tmp_root,
        app_db=tmp_root / "unused_app.db",
        ada_cache_db=tmp_root / "ada_cache.db",
        artifacts=tmp_root / "artifacts",
        logs=tmp_root / "logs",
        backups=tmp_root / "backups",
        badge="STAGING - NOT PRODUCTION AUTH",
        mutex_name="Global\\OCRInbound.ADA.behavioral-revert-check",
        target_allowlist=("STAGING_TEST",),
    )
    profile.ensure_directories()
    cache = AdaReferenceCache(profile)
    cache.refresh_from_fixture({"products": _REAL_MASTER_PRODUCTS, "suppliers": [], "purchase_history": []})
    return ProductMatcher(_NoAliasRepository(), cache)


def _predict(matcher: ProductMatcher, description: str, *, supplier_sku=None, supplier_code="UNKNOWN") -> dict:
    document = {"id": "doc-1", "supplier_code": supplier_code}
    line = {
        "id": "line-1",
        "supplier_sku": supplier_sku,
        "description_final": description,
        "raw_ocr_text": description,
        "unit_final": "",
        "evidence_json": None,
    }
    return matcher._predict(document, line, {"source": "behavioral-revert-check"})


class BehavioralAcceptanceMatrix(unittest.TestCase):
    """Six independent scenarios, each checking that the matcher's actual
    top answer (proposed_product_code) is the correct real product code --
    not merely that the right code appears somewhere in a five-item
    candidate list, which a small fixture can satisfy by coincidence even
    under broken ranking. Against the original matcher, run with the real
    decoy/competitor products that actually won on the live ~6,700-product
    master (see the comment above _REAL_MASTER_PRODUCTS), most of these
    fail on a real assertion -- the old matcher's TOP pick is a decoy, not
    the right product. See revert-check evidence in
    CANDIDATE_REPORT_TRADE_NAME_MATCHER.md."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="behavioral-revert-check-")
        self.matcher = _build_matcher(Path(self._tmpdir.name))

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_minidiab(self):
        result = _predict(self.matcher, "MINIDIAB 5mg 2x15's", supplier_sku="844")
        self.assertEqual(result["proposed_product_code"], "IC-000648")

    def test_isotrate(self):
        result = _predict(self.matcher, "ISOTRATE 10 MG. (W) 50X10'S")
        self.assertEqual(result["proposed_product_code"], "IC-002268")

    def test_presolin_150_not_300(self):
        result = _predict(self.matcher, "PRESOLIN 150 MG.TAB.10X10'S (Irbesartan 150 mg)", supplier_sku="1000000513")
        self.assertEqual(result["proposed_product_code"], "IC-002001")

    def test_relestat_with_english_hint(self):
        result = _predict(
            self.matcher,
            "รีเลสตาต 0.05% 5ML (คาดว่าคือ Relestat - อยู่ในแผนก ABBVIE-EYE CARE ตามหัวบิล)",
            supplier_sku="100754916",
        )
        self.assertEqual(result["proposed_product_code"], "IC-004874")

    def test_lesflam(self):
        result = _predict(self.matcher, "LESFLAM 50 MG.TAB.10X10'S (Diclofenac Potassium 50 mg)", supplier_sku="1000000316")
        self.assertEqual(result["proposed_product_code"], "IC-002137")

    def test_codiphen(self):
        result = _predict(self.matcher, "CODIPHEN TABLET (1X10's)", supplier_sku="32132")
        self.assertEqual(result["proposed_product_code"], "IC-001962")


if __name__ == "__main__":
    unittest.main()
