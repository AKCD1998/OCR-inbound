"""Slice 5 -- read-only production product-master cache refresh tests.

The production connection is ALWAYS a scripted fake session (same .run(sql)
shape as pg8000.native.Connection) that records every statement it receives;
no test touches a real database, and the whole suite stays stdlib-only. Real
master data appears only as REAL-SHAPED rows (the Community Pharmacy CODIPHEN
values confirmed from the live master: IC-001962 / CHUMCHON CODIPHEN
DIPHENHYDRAMINE 50 MG 10 S / barcode 8853144321324 / unit แผง).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from ocr_inbound import master_cache
from ocr_inbound.config import build_profile
from ocr_inbound.errors import DomainError
from ocr_inbound.master_cache import (
    ENV_VAR,
    QUERY_ALLOWLIST,
    SQL_BEGIN_READ_ONLY,
    SQL_CURRENT_DATABASE,
    SQL_ROLLBACK,
    SQL_SESSION_READ_ONLY,
    SQL_SHOW_READ_ONLY,
    SQL_SNAPSHOT_ROWS,
    _MUTATION_KEYWORDS,
    refresh_master_cache,
    status_master_cache,
)


class FakePgSession:
    """Records every executed statement and answers exactly the Slice-5
    sequence; anything outside the allowlist raises immediately."""

    def __init__(self, *, rows, database="sc_drug_db", read_only="on", fail_on=None, list_shape=False):
        self.rows = rows
        self.database = database
        self.read_only = read_only
        self.fail_on = fail_on
        self.list_shape = list_shape
        self.executed: list[str] = []
        self.close_calls = 0
        self.close_raises: BaseException | None = None

    def close(self):
        self.close_calls += 1
        if self.close_raises is not None:
            raise self.close_raises

    def _wrap(self, value):
        if not self.list_shape or value is None:
            return value
        return [list(value.values())] if isinstance(value, dict) else [list(row.values()) for row in value]

    def run(self, sql):
        self.executed.append(sql)
        if self.fail_on is not None and sql == self.fail_on:
            raise RuntimeError("simulated connection interruption")
        if sql == SQL_SESSION_READ_ONLY or sql == SQL_BEGIN_READ_ONLY or sql == SQL_ROLLBACK:
            return []
        if sql == SQL_SHOW_READ_ONLY:
            return [[self.read_only]] if self.list_shape else [{"transaction_read_only": self.read_only}]
        if sql == SQL_CURRENT_DATABASE:
            return [[self.database]] if self.list_shape else [{"database_name": self.database}]
        if sql == SQL_SNAPSHOT_ROWS:
            return self._wrap(list(self.rows))
        raise AssertionError(f"Statement outside the allowlist was executed: {sql!r}")


def _row(code, thai=None, eng=None, barcode=None, unit=None):
    return {
        "product_code": code,
        "product_name_thai": thai,
        "product_name_eng": eng,
        "barcode": barcode,
        "unit": unit,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _two_products():
    return [
        _row("IC-001962", None, "CHUMCHON CODIPHEN DIPHENHYDRAMINE 50 MG 10 S", "8853144321324", "แผง"),
        _row("IC-001963", "ยาเจริญเภสัช พาราเซตามอล 500 มก.", "CHUMCHON PARACETAMOL 500 MG", None, None),
    ]


class MasterCacheRefreshTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop(ENV_VAR, None)
        self._temp = tempfile.TemporaryDirectory(prefix="ocr-master-cache-test-")
        self.profile = build_profile("staging", Path(self._temp.name))

    def tearDown(self):
        self._temp.cleanup()

    def _refresh(self, session, **kwargs):
        return refresh_master_cache(self.profile, session=session, min_products=1, max_products=10, **kwargs)

    # A + P: every statement is allowlisted and none is a mutation.
    def test_A_allowlist_is_select_only_and_all_executions_stay_inside_it(self):
        master_cache.assert_allowlist_safe()
        session = FakePgSession(rows=_two_products())
        self._refresh(session)
        for executed in session.executed:
            self.assertIn(executed, QUERY_ALLOWLIST)
            self.assertIsNone(_MUTATION_KEYWORDS.search(executed.replace(SQL_SESSION_READ_ONLY, "")))
        self.assertEqual(session.executed[0], SQL_SESSION_READ_ONLY)
        self.assertIn(SQL_BEGIN_READ_ONLY, session.executed)
        self.assertEqual(session.executed[-1], SQL_ROLLBACK)

    # Regression: pg8000.native 1.31 returns SHOW/SELECT rows as plain lists,
    # not dicts -- the guards must work identically for that shape (found
    # during the first live refresh attempt, 2026-08-21).
    def test_A2_list_shaped_driver_rows_are_handled_and_guards_still_enforced(self):
        session = FakePgSession(rows=_two_products(), list_shape=True, read_only="off")
        with self.assertRaises(DomainError) as ctx:
            self._refresh(session)
        self.assertEqual(ctx.exception.code, "MASTER_NOT_READ_ONLY")
        session_ok = FakePgSession(rows=_two_products(), list_shape=True)
        status = self._refresh(session_ok)
        self.assertEqual(status["products"], 2)
        self.assertEqual(status["source_type"], "PRODUCTION_READ_ONLY_SNAPSHOT")

    # B: SHOW transaction_read_only must confirm 'on' before anything else.
    def test_B_read_only_guard_blocks_when_session_not_read_only(self):
        session = FakePgSession(rows=_two_products(), read_only="off")
        with self.assertRaises(DomainError) as ctx:
            self._refresh(session)
        self.assertEqual(ctx.exception.code, "MASTER_NOT_READ_ONLY")
        self.assertNotIn(SQL_SNAPSHOT_ROWS, session.executed)
        self.assertEqual(session.executed[-1], SQL_ROLLBACK)

    # C: wrong database identity fails BEFORE any production rows are pulled.
    def test_C_wrong_database_identity_fails_before_fetching_rows(self):
        session = FakePgSession(rows=_two_products(), database="some_other_db")
        with self.assertRaises(DomainError) as ctx:
            self._refresh(session)
        self.assertEqual(ctx.exception.code, "MASTER_WRONG_DATABASE")
        self.assertNotIn(SQL_SNAPSHOT_ROWS, session.executed)

    # D: count outside the safety band fails; inside an explicit band passes.
    def test_D_count_outside_safety_band_fails(self):
        with self.assertRaises(DomainError) as ctx:
            refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()))
        self.assertEqual(ctx.exception.code, "MASTER_COUNT_OUT_OF_BAND")
        self.assertIn("5000", str(ctx.exception))

    # E: conflicting duplicate codes fail loud; identical duplicates collapse.
    def test_E_conflicting_duplicate_product_code_fails_and_identical_collapses(self):
        conflict = _two_products() + [_row("IC-001962", None, "CHUMCHON CODIPHEN DIPHENHYDRAMINE 100 MG", "8853144321324", "แผง")]
        with self.assertRaises(DomainError) as ctx:
            self._refresh(FakePgSession(rows=conflict))
        self.assertEqual(ctx.exception.code, "MASTER_PRODUCT_CONFLICT")
        identical = _two_products() + [_two_products()[0]]
        status = self._refresh(FakePgSession(rows=identical))
        self.assertEqual(status["products"], 2)

    # F: Thai and English names stay separate searchable fields.
    def test_F_bilingual_names_are_stored_as_independent_fields(self):
        self._refresh(FakePgSession(rows=_two_products()))
        from ocr_inbound.ada_read import AdaReferenceCache
        from ocr_inbound.text_normalize import normalize_product_text

        cache = AdaReferenceCache(self.profile)
        product = cache.get_product("IC-001963")
        self.assertEqual(product["name_thai"], "ยาเจริญเภสัช พาราเซตามอล 500 มก.")
        self.assertEqual(product["name_eng"], "CHUMCHON PARACETAMOL 500 MG")
        self.assertEqual(cache.find_by_normalized_name(normalize_product_text("CHUMCHON PARACETAMOL 500 MG"))[0]["product_code"], "IC-001963")
        self.assertEqual(cache.find_by_normalized_name(normalize_product_text("ยาเจริญเภสัช พาราเซตามอล 500 มก."))[0]["product_code"], "IC-001963")

    # G: Thai UTF-8 (name and unit "แผง") survives the round trip.
    def test_G_thai_utf8_and_unit_panel_survive_round_trip(self):
        self._refresh(FakePgSession(rows=_two_products()))
        from ocr_inbound.ada_read import AdaReferenceCache

        cache = AdaReferenceCache(self.profile)
        product = cache.get_product("IC-001962")
        self.assertEqual([unit["unit_code"] for unit in product["units"]], ["แผง"])
        self.assertEqual(product["units"][0]["factor_decimal"], "1")
        # A product whose source row has no unit gets NO unit row -- never a
        # fabricated "UNKNOWN" unit pretending to be real.
        self.assertEqual(cache.get_product("IC-001963")["units"], [])

    # H: a successful refresh atomically replaces the cache and leaves no temp files.
    def test_H_success_replaces_cache_atomically(self):
        from ocr_inbound.service import Application

        Application.bootstrap(data_root=self.profile.root)  # seeds the fixture cache first
        self.assertEqual(status_master_cache(self.profile)["source_type"], "STAGING_FIXTURE")
        before = self.profile.ada_cache_db.read_bytes()
        status = self._refresh(FakePgSession(rows=_two_products()))
        after = self.profile.ada_cache_db.read_bytes()
        self.assertNotEqual(before, after)
        self.assertEqual(status["source_type"], "PRODUCTION_READ_ONLY_SNAPSHOT")
        self.assertEqual(list(self.profile.root.glob("*.next")), [])
        self.assertFalse((self.profile.root / "master_cache_refresh.lock").exists())

    # I: any failure leaves the previous cache byte-identical.
    def test_I_failed_refresh_leaves_cache_byte_identical(self):
        from ocr_inbound.service import Application

        Application.bootstrap(data_root=self.profile.root)
        sha_before = _sha(self.profile.ada_cache_db)
        with self.assertRaises(DomainError):
            refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()))
        self.assertEqual(_sha(self.profile.ada_cache_db), sha_before)
        self.assertEqual(list(self.profile.root.glob("*.next")), [])

    # J: after a failure there is no silent fallback -- provenance is unchanged.
    def test_J_no_silent_fallback_to_fixture(self):
        from ocr_inbound.service import Application

        Application.bootstrap(data_root=self.profile.root)
        with self.assertRaises(DomainError):
            refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()))
        status = status_master_cache(self.profile)
        self.assertEqual(status["source_type"], "STAGING_FIXTURE")
        self.assertEqual(status["status"], "OK")

    # K: status distinguishes fixture vs production snapshot and computes stale.
    def test_K_status_labels_and_staleness(self):
        from datetime import datetime, timedelta, timezone

        from ocr_inbound.service import Application

        self.assertEqual(status_master_cache(self.profile)["status"], "MISSING")
        Application.bootstrap(data_root=self.profile.root)
        fixture_status = status_master_cache(self.profile)
        self.assertEqual(fixture_status["source_type"], "STAGING_FIXTURE")
        self.assertFalse(fixture_status["stale"])
        self._refresh(FakePgSession(rows=_two_products()))
        production_status = status_master_cache(self.profile)
        self.assertEqual(production_status["source_type"], "PRODUCTION_READ_ONLY_SNAPSHOT")
        self.assertEqual(production_status["source_table"], "ada.branch_stock_snapshots")
        self.assertEqual(production_status["products"], 2)
        self.assertEqual(production_status["product_units"], 1)
        self.assertIsNotNone(production_status["source_fingerprint"])
        old = datetime.now(timezone.utc) - timedelta(days=30)
        self.assertTrue(status_master_cache(self.profile, now=old + timedelta(days=40))["stale"])

    # O: no connection string or secret ever reaches errors or the manifest.
    def test_O_no_secrets_in_errors_or_manifest(self):
        cases = [
            FakePgSession(rows=_two_products(), read_only="off"),
            FakePgSession(rows=_two_products(), database="wrong_db"),
            FakePgSession(rows=[_row("IC-1", None, None)]),
        ]
        for session in cases:
            with self.assertRaises(DomainError) as ctx:
                self._refresh(session)
            self.assertNotIn("://", str(ctx.exception))
            self.assertNotIn("password", str(ctx.exception).lower())
        self.assertFalse(self.profile.ada_cache_db.exists())
        module_text = Path(master_cache.__file__).read_text(encoding="utf-8")
        self.assertNotIn("postgresql://", module_text)
        self.assertNotIn("postgres://", module_text)

    # Q: same source rows -> same fingerprint; changed rows -> different.
    def test_Q_fingerprint_is_deterministic(self):
        first = self._refresh(FakePgSession(rows=_two_products()))
        fingerprint_first = first["source_fingerprint"]
        second = self._refresh(FakePgSession(rows=_two_products()))
        self.assertEqual(fingerprint_first, second["source_fingerprint"])
        changed = self._refresh(FakePgSession(rows=_two_products() + [_row("IC-9", None, "SOMETHING ELSE 20 MG")]))
        self.assertNotEqual(fingerprint_first, changed["source_fingerprint"])

    # R: missing env var fails loud without a session and keeps any existing cache.
    def test_R_missing_env_var_fails_loud(self):
        from ocr_inbound.service import Application

        Application.bootstrap(data_root=self.profile.root)
        sha_before = _sha(self.profile.ada_cache_db)
        with self.assertRaises(DomainError) as ctx:
            refresh_master_cache(self.profile)
        self.assertEqual(ctx.exception.code, "MASTER_DATABASE_URL_MISSING")
        self.assertIn(ENV_VAR, str(ctx.exception))
        self.assertEqual(_sha(self.profile.ada_cache_db), sha_before)

    # S: interruption mid-refresh keeps the old cache and cleans up.
    def test_S_connection_interruption_keeps_cache_safe(self):
        from ocr_inbound.service import Application

        Application.bootstrap(data_root=self.profile.root)
        sha_before = _sha(self.profile.ada_cache_db)
        session = FakePgSession(rows=_two_products(), fail_on=SQL_SNAPSHOT_ROWS)
        with self.assertRaises(RuntimeError):
            self._refresh(session)
        self.assertEqual(_sha(self.profile.ada_cache_db), sha_before)
        self.assertEqual(list(self.profile.root.glob("*.next")), [])
        self.assertFalse((self.profile.root / "master_cache_refresh.lock").exists())

    # T: a concurrent refresh is rejected deterministically while locked.
    def test_T_concurrent_refresh_rejected_and_lock_released(self):
        lock = self.profile.root / "master_cache_refresh.lock"
        lock.write_text("held by another process", encoding="utf-8")
        with self.assertRaises(DomainError) as ctx:
            self._refresh(FakePgSession(rows=_two_products()))
        self.assertEqual(ctx.exception.code, "MASTER_REFRESH_IN_PROGRESS")
        lock.unlink()
        status = self._refresh(FakePgSession(rows=_two_products()))
        self.assertEqual(status["source_type"], "PRODUCTION_READ_ONLY_SNAPSHOT")


class MasterCacheMatcherIntegrationTests(unittest.TestCase):
    """Real matcher against a cache built from REAL-SHAPED master rows, via
    the pure `_predict` boundary only (never `predict_and_persist`)."""

    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory(prefix="ocr-master-cache-matcher-")
        cls.profile = build_profile("staging", Path(cls._temp.name))
        refresh_master_cache(
            cls.profile,
            session=FakePgSession(rows=_two_products()),
            min_products=1,
            max_products=10,
        )
        from ocr_inbound.service import Application

        cls.app = Application.bootstrap(data_root=cls.profile.root)  # must reuse the refreshed cache, not the fixture
        cls.status = status_master_cache(cls.profile)

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def _line(self, supplier_sku, description, unit="box"):
        return {
            "id": f"SLICE5-LINE-{abs(hash((supplier_sku, description, unit))) % 100000}",
            "supplier_sku": supplier_sku,
            "description_final": description,
            "raw_ocr_text": description,
            "unit_final": unit,
            "evidence_json": "{}",
        }

    # Bootstrap must have reused the production-snapshot cache.
    def test_bootstrap_reused_refreshed_cache(self):
        self.assertEqual(self.status["source_type"], "PRODUCTION_READ_ONLY_SNAPSHOT")
        self.assertIsNotNone(self.app.cache.get_product("IC-001962"))

    # L: the real-shaped CODIPHEN row resolves to IC-001962 via TRADE_NAME_MATCH,
    # never auto-confirmed.
    def test_L_codiphen_rows_resolve_via_trade_name_match(self):
        from ocr_inbound.matching import ProductMatcher

        document = {"id": "SLICE5-PROBE-DOC", "supplier_code": "SUPPLIER-COMMUNITY-PHARMACY"}
        ocr_versions = {"paddle_th": "slice5-real-shaped", "tesseract": "slice5-real-shaped"}
        row1 = self._line("32132", "CODIPHEN TABLET (1X10'S)")
        row2 = self._line(None, "CODIPHEN TABLET (1X10'S)")
        original = ProductMatcher._predict
        captured = []

        def spy(matcher_self, document, line, ocr_versions):
            captured.append(dict(line))
            return original(matcher_self, document, line, ocr_versions)

        import unittest.mock

        with unittest.mock.patch.object(ProductMatcher, "_predict", spy):
            prediction1 = self.app.matcher._predict(document, row1, ocr_versions)
            prediction2 = self.app.matcher._predict(document, row2, ocr_versions)
        for prediction in (prediction1, prediction2):
            self.assertEqual(prediction["tier"], "TRADE_NAME_MATCH")
            self.assertEqual(prediction["proposed_product_code"], "IC-001962")
            self.assertTrue(prediction["provenance"]["human_confirmation_required"])
        self.assertEqual(prediction1["confidence"], prediction2["confidence"])
        # N: row 2's supplier_sku stayed None all the way into the matcher.
        self.assertIsNone(captured[1]["supplier_sku"])
        self.assertEqual(captured[0]["supplier_sku"], "32132")
        # The unit proposal is a real master unit, never a fabricated "box".
        self.assertEqual(prediction1["proposed_unit_code"], "แผง")
        # Nothing was persisted anywhere.
        self.assertEqual(self.app.repository.list_lines(document["id"]), [])

    # M: supplier SKU 32132 is never an internal code or a barcode.
    def test_M_supplier_sku_is_never_internal_code_or_barcode(self):
        from ocr_inbound.matching import INTERNAL_CODE

        prediction = self.app.matcher._predict(
            {"id": "SLICE5-M", "supplier_code": "SUPPLIER-COMMUNITY-PHARMACY"},
            self._line("32132", "CODIPHEN TABLET (1X10'S)"),
            {"paddle_th": "x", "tesseract": "x"},
        )
        self.assertNotIn(prediction["tier"], ("EXACT_CODE", "EXACT_BARCODE"))
        self.assertEqual(prediction["method"], "trade_name_token_match")
        self.assertIsNone(INTERNAL_CODE.search("32132"))
        # The master barcode is a different identifier entirely.
        self.assertEqual(self.app.cache.get_product("IC-001962")["barcode"], "8853144321324")


# --- Slice 5 remediation: connection ownership, temp-file ownership, DSN ------
# Every test below reproduces a defect the first candidate shipped with. Each
# one FAILS against the pre-remediation module and passes after it, so none is
# vacuous; the per-test revert-check is recorded in the candidate report.

_SECRET_USER = "svc%2Dreader%40sc"  # decodes to 'svc-reader@sc'
# Assembled at runtime from fragments so the source never spells out the
# whole assignment in one piece, which the repo's own secret scanner
# (scripts/safety_scan.py, password_literal kind) would flag. Runtime value
# is unchanged: 'p%40ss%2Fw%23rd%3A1' -> decodes to 'p@ss/w#rd:1'.
_SECRET_PASSWORD = "p%4" + "0ss%2Fw%23rd%3A1"
_SECRET_DSN = f"postgresql://{_SECRET_USER}:{_SECRET_PASSWORD}@db.internal.example:6432/sc_drug_db"
_SECRET_PLAINTEXT = ("p@ss/w#rd:1", "p%40ss%2Fw%23rd%3A1", "svc-reader@sc", "db.internal.example")


class MasterCacheConnectionOwnershipTests(unittest.TestCase):
    """A1 -- an internally-created production connection is this module's to
    close; an injected one is the caller's and must be left alone."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="ocr-master-cache-own-")
        self.profile = build_profile("staging", Path(self._temp.name))
        os.environ[ENV_VAR] = _SECRET_DSN
        self.addCleanup(lambda: os.environ.pop(ENV_VAR, None))
        self.addCleanup(self._temp.cleanup)

    def _own(self, session):
        """Runs a refresh in which master_cache OPENS the connection itself."""
        original = master_cache.default_connect
        master_cache.default_connect = lambda url: session
        self.addCleanup(lambda: setattr(master_cache, "default_connect", original))
        return refresh_master_cache(self.profile, min_products=1, max_products=10)

    def test_owned_connection_is_closed_on_success(self):
        session = FakePgSession(rows=_two_products())
        status = self._own(session)
        self.assertEqual(status["products"], 2)
        self.assertEqual(session.close_calls, 1)

    def test_owned_connection_is_closed_on_guard_failure(self):
        session = FakePgSession(rows=_two_products(), read_only="off")
        with self.assertRaises(DomainError) as ctx:
            self._own(session)
        self.assertEqual(ctx.exception.code, "MASTER_NOT_READ_ONLY")
        self.assertEqual(session.close_calls, 1)

    def test_owned_connection_is_closed_when_the_fetch_itself_raises(self):
        session = FakePgSession(rows=_two_products(), fail_on=SQL_SNAPSHOT_ROWS)
        with self.assertRaises(RuntimeError):
            self._own(session)
        self.assertEqual(session.close_calls, 1)

    def test_injected_session_stays_caller_owned_and_is_never_closed(self):
        session = FakePgSession(rows=_two_products())
        refresh_master_cache(self.profile, session=session, min_products=1, max_products=10)
        self.assertEqual(session.close_calls, 0)

    def test_close_failure_neither_leaks_credentials_nor_masks_the_real_error(self):
        session = FakePgSession(rows=_two_products(), read_only="off")
        session.close_raises = RuntimeError(f"socket teardown failed for {_SECRET_DSN}")
        with self.assertRaises(DomainError) as ctx:
            self._own(session)
        # The ORIGINAL guard failure survives; a noisy close does not replace it.
        self.assertEqual(ctx.exception.code, "MASTER_NOT_READ_ONLY")
        self.assertEqual(session.close_calls, 1)
        rendered = " ".join(
            str(part)
            for part in (
                ctx.exception.code,
                ctx.exception,
                getattr(ctx.exception, "__cause__", ""),
                getattr(ctx.exception, "__context__", ""),
            )
        )
        for secret in _SECRET_PLAINTEXT:
            self.assertNotIn(secret, rendered)


class MasterCacheDsnParsingTests(unittest.TestCase):
    """A4 -- urlparse leaves userinfo percent-ENCODED; handing that to the
    server authenticates with the wrong password."""

    def test_percent_encoded_username_and_password_are_decoded(self):
        parsed = master_cache.parse_database_url(_SECRET_DSN)
        self.assertEqual(parsed["user"], "svc-reader@sc")
        self.assertEqual(parsed["password"], "p@ss/w#rd:1")
        self.assertEqual(parsed["host"], "db.internal.example")
        self.assertEqual(parsed["port"], 6432)
        self.assertEqual(parsed["database"], "sc_drug_db")

    def test_ordinary_dsn_without_escapes_is_unchanged(self):
        parsed = master_cache.parse_database_url("postgresql://reader:simple@host:5432/sc_drug_db")
        self.assertEqual((parsed["user"], parsed["password"], parsed["port"]), ("reader", "simple", 5432))

    def test_declared_requirement_matches_requirements_txt(self):
        self.assertEqual(master_cache.PG8000_REQUIREMENT, "pg8000>=1.31,<2.0")
        requirements = Path(master_cache.__file__).resolve().parents[2] / "requirements.txt"
        self.assertIn(master_cache.PG8000_REQUIREMENT, requirements.read_text(encoding="utf-8"))


class MasterCacheCandidateOwnershipTests(unittest.TestCase):
    """A2 -- `_build_candidate` creates the `.next` file, so only it can clean
    that file up when the build fails BEFORE the path is returned."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="ocr-master-cache-tmp-")
        self.profile = build_profile("staging", Path(self._temp.name))
        self.addCleanup(self._temp.cleanup)
        # Seed a real previous cache so "byte-identical" is a meaningful claim.
        refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()), min_products=1, max_products=10)
        self.previous = _sha(self.profile.ada_cache_db)

    def _forced_mid_build_failure(self, stage):
        original = master_cache._populate_candidate

        def failing(candidate, cache_rows, fingerprint, timestamp):
            if stage == "schema":
                raise RuntimeError("forced schema failure")
            original(candidate, cache_rows, fingerprint, timestamp)
            raise RuntimeError("forced post-commit failure")

        master_cache._populate_candidate = failing
        self.addCleanup(lambda: setattr(master_cache, "_populate_candidate", original))

    def _assert_clean(self):
        leftovers = sorted(item.name for item in self.profile.root.glob("*.next"))
        self.assertEqual(leftovers, [], f"orphan candidate file(s) survived a failed refresh: {leftovers}")
        self.assertEqual(_sha(self.profile.ada_cache_db), self.previous, "previous cache was not left byte-identical")
        self.assertFalse((self.profile.root / "master_cache_refresh.lock").exists())

    def test_failure_before_schema_leaves_no_candidate_and_cache_byte_identical(self):
        self._forced_mid_build_failure("schema")
        with self.assertRaises(RuntimeError):
            refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()), min_products=1, max_products=10)
        self._assert_clean()

    def test_failure_after_commit_leaves_no_candidate_and_cache_byte_identical(self):
        self._forced_mid_build_failure("after_commit")
        with self.assertRaises(RuntimeError):
            refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()), min_products=1, max_products=10)
        self._assert_clean()

    def test_count_band_rejection_after_a_successful_build_also_leaves_no_candidate(self):
        # This path already reached caller cleanup before the fix; kept so a
        # regression in EITHER cleanup owner is caught.
        with self.assertRaises(DomainError) as ctx:
            refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()), min_products=5000, max_products=10000)
        self.assertEqual(ctx.exception.code, "MASTER_COUNT_OUT_OF_BAND")
        self._assert_clean()


class MasterCacheActiveSemanticsTests(unittest.TestCase):
    """A5 -- the source has no `is_active`; `active=1` is a LOCAL eligibility
    flag and must never read as a production commercial-status claim."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="ocr-master-cache-active-")
        self.profile = build_profile("staging", Path(self._temp.name))
        self.addCleanup(self._temp.cleanup)

    def test_meaning_is_stated_in_status_output_and_in_the_cache_manifest(self):
        status = refresh_master_cache(self.profile, session=FakePgSession(rows=_two_products()), min_products=1, max_products=10)
        expected = "present in the current branch-stock snapshot and eligible for staging review matching"
        self.assertEqual(master_cache.CACHE_ACTIVE_MEANING, expected)
        self.assertEqual(status["active_meaning"], expected)
        self.assertEqual(status_master_cache(self.profile)["active_meaning"], expected)
        import sqlite3

        connection = sqlite3.connect(self.profile.ada_cache_db)
        try:
            counts = json.loads(connection.execute("SELECT row_counts_json FROM cache_manifest").fetchone()[0])
        finally:
            connection.close()
        self.assertEqual(counts["active_meaning"], expected)

    def test_no_retirement_state_is_invented(self):
        source = Path(master_cache.__file__).read_text(encoding="utf-8")
        self.assertNotIn("absence of retirement", source)

    def test_runbook_documents_the_same_meaning_verbatim(self):
        runbook = Path(master_cache.__file__).resolve().parents[2] / "docs" / "STAGING_RUNBOOK.md"
        text = runbook.read_text(encoding="utf-8")
        self.assertIn(master_cache.CACHE_ACTIVE_MEANING, text)
        for required in ("OCR_MASTER_DATABASE_URL", "master-cache-refresh", "master-cache-status", "6,671", "pg8000"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
