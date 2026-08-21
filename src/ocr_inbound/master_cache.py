"""Slice 5 -- official read-only product-master cache refresh (ADR-005 boundary).

production PostgreSQL (sc_drug_db.ada.branch_stock_snapshots)
  -> SELECT-only named queries inside a READ ONLY session
  -> identity/count/contract validation
  -> atomic replacement of the LOCAL staging ada_cache.db
The matcher then keeps working purely locally; no production write of any
kind exists on this path, and no credential is ever logged, embedded, or
copied into this repository (the connection string arrives only via the
OCR_MASTER_DATABASE_URL environment variable on the operator's machine).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .ada_read import AdaReferenceCache
from .config import AppProfile
from .errors import DomainError

ENV_VAR = "OCR_MASTER_DATABASE_URL"
EXPECTED_DATABASE = "sc_drug_db"
SOURCE_TABLE = "ada.branch_stock_snapshots"
SOURCE_INSTANCE_LABEL = "PRODUCTION_READ_ONLY_SNAPSHOT"
FIXTURE_INSTANCE_LABEL = "STAGING_FIXTURE"
DEFAULT_MIN_PRODUCTS = 5_000
DEFAULT_MAX_PRODUCTS = 10_000
DEFAULT_STALE_AFTER_DAYS = 7
# Declared in requirements.txt and pyproject's [project.optional-dependencies]
# "master-refresh" extra. Only this operator-driven refresh path imports it;
# the packaged app, the matcher, and the whole test suite stay stdlib-only.
PG8000_REQUIREMENT = "pg8000>=1.31,<2.0"

# --- What `products.active = 1` means in the LOCAL cache ---------------------
# The source table has NO `is_active` column (verified against the live
# schema). The cache column is therefore a LOCAL eligibility flag, not a
# commercial-status claim, and its meaning is stated in exactly one place
# so code, status output, report, and runbook cannot drift apart.
CACHE_ACTIVE_MEANING = (
    "present in the current branch-stock snapshot and eligible for staging review matching"
)

# --- Named query catalog: the SELECT-only allowlist --------------------------
# Every statement this module may send to the production connection is one of
# these, and nothing else is ever executed. `assert_allowlist_safe()` (used by
# tests) proves both directions: each entry is read-only, and no statement
# outside this tuple is ever handed to `session.run` (the injected fake session
# in tests records every call). The session is forced read-only FIRST, so even
# a future accidental catalog edit could not mutate production.
SQL_SESSION_READ_ONLY = "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
SQL_BEGIN_READ_ONLY = "BEGIN READ ONLY"
SQL_SHOW_READ_ONLY = "SHOW transaction_read_only"
SQL_CURRENT_DATABASE = "SELECT current_database() AS database_name"
SQL_SNAPSHOT_ROWS = (
    "SELECT product_code, product_name_thai, product_name_eng, barcode, unit "
    f"FROM {SOURCE_TABLE} ORDER BY product_code"
)
SQL_ROLLBACK = "ROLLBACK"
QUERY_ALLOWLIST = (
    SQL_SESSION_READ_ONLY,
    SQL_BEGIN_READ_ONLY,
    SQL_SHOW_READ_ONLY,
    SQL_CURRENT_DATABASE,
    SQL_SNAPSHOT_ROWS,
    SQL_ROLLBACK,
)
_MUTATION_KEYWORDS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|CALL|TRUNCATE|DROP|ALTER|"
    r"CREATE|GRANT|REVOKE|SET\s+ROLE)\b",
    re.IGNORECASE,
)


def assert_allowlist_safe() -> None:
    """Self-check: every catalog entry is a read-only statement. `SET SESSION
    CHARACTERISTICS AS TRANSACTION READ ONLY` is the one deliberate exception
    in shape -- it REDUCES the session's capability, it never grants one."""
    for query in QUERY_ALLOWLIST:
        read_only_shape = query.startswith(("SELECT ", "SHOW ", "ROLLBACK", SQL_SESSION_READ_ONLY, SQL_BEGIN_READ_ONLY))
        if not read_only_shape or _MUTATION_KEYWORDS.search(query.replace(SQL_SESSION_READ_ONLY, "")):
            raise DomainError("MASTER_QUERY_CATALOG_UNSAFE", f"Non-read-only statement in the master cache catalog: {query!r}")


def _require_database_url() -> str:
    url = os.environ.get(ENV_VAR, "").strip()
    if not url:
        raise DomainError("MASTER_DATABASE_URL_MISSING", f"Set {ENV_VAR} to the read-only production connection string before refreshing")
    return url


def parse_database_url(database_url: str) -> dict:
    """Splits the operator's DSN into pg8000 connection keywords.

    `urlparse` returns the userinfo fields still PERCENT-ENCODED, so a
    password that legitimately contains `@`, `/`, `#`, `?` or `:` -- all of
    which MUST be percent-escaped to keep the URL parseable -- would
    otherwise be handed to the server verbatim (`p%40ss` instead of `p@ss`)
    and fail authentication for a reason the operator cannot see. Every
    userinfo field and the database path are therefore explicitly unquoted
    here. The returned dict is credential-bearing: it is never logged,
    printed, or stored, and callers must not put it in an error message."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": unquote((parsed.path or "/").lstrip("/")),
    }


def default_connect(database_url: str):
    """Builds the production session from the environment-supplied URL. The
    pg8000 import is deliberately lazy: only the operator-driven refresh path
    needs a driver -- the packaged app, the matcher, and the whole test suite
    stay stdlib-only (tests inject a fake session instead)."""
    try:
        import pg8000.native
    except ImportError as exc:  # pragma: no cover - depends on operator venv
        raise DomainError("MASTER_REFRESH_DRIVER_MISSING", f"Install pg8000 in the operator venv to refresh from production (pip install '{PG8000_REQUIREMENT}')") from exc
    try:
        return pg8000.native.Connection(**parse_database_url(database_url), ssl_context=True, timeout=30)
    except DomainError:
        raise
    except Exception as exc:
        # The driver's own exception text can quote the DSN/user; re-raise a
        # credential-free error and deliberately drop the original context.
        raise DomainError("MASTER_CONNECT_FAILED", f"Could not open the read-only production session ({type(exc).__name__}); check {ENV_VAR}, network access, and credentials") from None


def _close_quietly(connection) -> None:
    """Closes a connection this module OWNS, on success and on every failure
    path. A failure to close is deliberately swallowed WITHOUT its message:
    driver close/teardown errors routinely echo the DSN (host, user, and in
    some drivers the password), and this module must never let a credential
    reach a log, an exception chain, or an operator's terminal. The
    connection is being discarded either way, so there is nothing to
    recover -- only something to leak."""
    try:
        connection.close()
    except Exception:  # noqa: BLE001 - see docstring: message intentionally dropped
        pass


def _first_value(result, key: str):
    """Reads the first row's single column, tolerating both dict-shaped rows
    (tests, and pg8000 versions that return mappings) and plain sequences
    (pg8000.native 1.31 returns SHOW/SELECT rows as lists)."""
    row = result[0]
    if isinstance(row, dict):
        return row[key]
    return row[0]


def _fetch_snapshot(session) -> list[dict]:
    """Runs the guarded read-only sequence. The identity check happens BEFORE
    any production rows are pulled, and ROLLBACK runs even on failure."""
    assert_allowlist_safe()
    session.run(SQL_SESSION_READ_ONLY)
    session.run(SQL_ROLLBACK)  # close any driver-implicit transaction so the session characteristic applies
    session.run(SQL_BEGIN_READ_ONLY)
    try:
        if str(_first_value(session.run(SQL_SHOW_READ_ONLY), "transaction_read_only")).lower() != "on":
            raise DomainError("MASTER_NOT_READ_ONLY", "Production session did not report transaction_read_only=on; refusing to continue")
        database_name = _first_value(session.run(SQL_CURRENT_DATABASE), "database_name")
        if database_name != EXPECTED_DATABASE:
            raise DomainError("MASTER_WRONG_DATABASE", f"Connected to {database_name!r}; this refresh path only targets {EXPECTED_DATABASE!r}")
        rows = session.run(SQL_SNAPSHOT_ROWS)
        if rows and not isinstance(rows[0], dict):
            columns = ("product_code", "product_name_thai", "product_name_eng", "barcode", "unit")
            rows = [dict(zip(columns, row)) for row in rows]
        return rows
    finally:
        try:
            session.run(SQL_ROLLBACK)
        except Exception:
            pass


def _rows_fingerprint(rows: list[dict]) -> str:
    """Deterministic, credential-free checksum of the source content: same
    rows in the same (query-ordered) order always produce the same value."""
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            "\x1f".join(
                "" if row.get(field) is None else str(row.get(field))
                for field in ("product_code", "product_name_thai", "product_name_eng", "barcode", "unit")
            ).encode("utf-8")
        )
        digest.update(b"\x1e")
    return digest.hexdigest()


def _to_cache_rows(rows: list[dict]) -> list[dict]:
    """Applies the data contract row by row: non-empty unique product_code,
    at least one bilingual name, barcode/unit optional (never fabricated),
    Thai preserved as UTF-8. Duplicate identical rows collapse
    deterministically; duplicate codes with conflicting values fail loud."""
    seen: dict[str, dict] = {}
    for row in rows:
        code = (row.get("product_code") or "").strip()
        if not code:
            raise DomainError("MASTER_INVALID_PRODUCT_CODE", "Source row has an empty product_code")
        thai = (row.get("product_name_thai") or "").strip() or None
        eng = (row.get("product_name_eng") or "").strip() or None
        barcode = (row.get("barcode") or "").strip() or None
        unit = (row.get("unit") or "").strip() or None
        if thai is None and eng is None:
            raise DomainError("MASTER_NAME_MISSING", f"Product {code!r} has neither a Thai nor an English name; refusing to guess")
        cache_row = {"product_code": code, "name_thai": thai, "name_eng": eng, "barcode": barcode, "unit": unit}
        previous = seen.get(code)
        if previous is None:
            seen[code] = cache_row
        elif previous != cache_row:
            raise DomainError("MASTER_PRODUCT_CONFLICT", f"Product {code!r} appears twice with conflicting values; refusing to pick a side")
    return sorted(seen.values(), key=lambda item: item["product_code"])


def _build_candidate(profile: AppProfile, cache_rows: list[dict], fingerprint: str) -> Path:
    """Builds the validated candidate SQLite in the environment root. This is
    a LOCAL staging file; no production connection is used here.

    The `.next` file is created INSIDE this function, so this function -- not
    its caller -- is the only code that can clean it up on a failure that
    happens before the path is returned. The caller's `except` block binds
    `candidate` from this function's RETURN VALUE, so a schema/insert/commit
    failure would never reach caller cleanup and the temporary file would
    survive every failed refresh. Ownership is therefore closed here."""
    from .db import now_iso

    handle, temporary_name = tempfile.mkstemp(prefix="ada_cache.slice5.", suffix=".next", dir=profile.root)
    os.close(handle)
    candidate = Path(temporary_name)
    try:
        _populate_candidate(candidate, cache_rows, fingerprint, now_iso())
    except BaseException:
        # BaseException, not Exception: a KeyboardInterrupt mid-build must not
        # leave an orphan `.next` beside the live cache either.
        candidate.unlink(missing_ok=True)
        raise
    return candidate


def _populate_candidate(candidate: Path, cache_rows: list[dict], fingerprint: str, timestamp: str) -> None:
    import sqlite3

    connection = sqlite3.connect(candidate)
    try:
        AdaReferenceCache._schema(connection)
        unit_count = 0
        for row in cache_rows:
            legacy_name = row["name_eng"] or row["name_thai"] or ""
            from .text_normalize import normalize_product_text

            connection.execute(
                "INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row["product_code"], row["barcode"], legacy_name, normalize_product_text(legacy_name),
                    row["name_thai"], row["name_eng"],
                    normalize_product_text(row["name_thai"]) if row["name_thai"] else None,
                    normalize_product_text(row["name_eng"]) if row["name_eng"] else None,
                    None, None, None, None,  # ingredient/strength/size/manufacturer: absent in source, never guessed
                    # active=1 means EXACTLY `CACHE_ACTIVE_MEANING`: this row was
                    # present in the branch-stock snapshot we just read, so it is
                    # eligible to be matched during staging review. The source has
                    # no `is_active` column, so this is NOT a claim that the product
                    # is commercially active, stocked, orderable, or not retired --
                    # and absence from a later snapshot is NOT evidence of
                    # retirement. No retirement state is inferred or invented here.
                    1, timestamp,
                ),
            )
            if row["unit"]:
                connection.execute("INSERT INTO product_units VALUES(?,?,?,?)", (row["product_code"], row["unit"], "1", 1))
                unit_count += 1
        counts = {
            "products": len(cache_rows),
            "product_units": unit_count,
            "suppliers": 0,
            "purchase_history": 0,
            "source_table": SOURCE_TABLE,
            "source_fingerprint": fingerprint,
            "active_meaning": CACHE_ACTIVE_MEANING,
        }
        connection.execute(
            "INSERT INTO cache_manifest VALUES(1,?,?,?,?)",
            (SOURCE_INSTANCE_LABEL, "ada-cache-v1", timestamp, json.dumps(counts, sort_keys=True, ensure_ascii=False)),
        )
        connection.commit()
    finally:
        connection.close()


def _validate_candidate(candidate: Path, product_count: int, min_products: int, max_products: int) -> None:
    import sqlite3

    if not (min_products <= product_count <= max_products):
        raise DomainError(
            "MASTER_COUNT_OUT_OF_BAND",
            f"Source reported {product_count} products; outside the configured safety band {min_products}-{max_products}",
        )
    connection = sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise DomainError("MASTER_CANDIDATE_INVALID", "Candidate cache failed PRAGMA integrity_check")
        distinct_codes, total_rows = connection.execute("SELECT COUNT(DISTINCT product_code), COUNT(*) FROM products").fetchone()
        bilingual = connection.execute("SELECT COUNT(*) FROM products WHERE name_thai IS NULL AND name_eng IS NULL").fetchone()[0]
        if distinct_codes != total_rows or bilingual != 0:
            raise DomainError("MASTER_CANDIDATE_INVALID", "Candidate cache violates the uniqueness/bilingual contract")
    finally:
        connection.close()


def refresh_master_cache(
    profile: AppProfile,
    *,
    session=None,
    min_products: int = DEFAULT_MIN_PRODUCTS,
    max_products: int = DEFAULT_MAX_PRODUCTS,
) -> dict:
    """Explicit operator action (never called by Application.bootstrap). On any
    failure the previous local cache is left byte-identical and the error is
    loud; there is no silent fallback to the packaged fixture."""
    lock_path = profile.root / "master_cache_refresh.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        # The holder identifies itself in the lock body so an operator can tell a
        # LIVE refresh apart from a lock stranded by a killed process, instead of
        # guessing. Nothing here deletes the lock: this process cannot know
        # whether the recorded PID is still the refresh that created it (PIDs are
        # reused), so recovery stays a deliberate human step -- see
        # docs/STAGING_RUNBOOK.md, "Stale refresh lock".
        raise DomainError(
            "MASTER_REFRESH_IN_PROGRESS",
            f"Another master-cache refresh holds {lock_path.name} ({_describe_lock(lock_path)}). "
            "If no refresh is running, follow the stale-lock recovery in docs/STAGING_RUNBOOK.md; "
            "do not delete the lock while a refresh may still be alive.",
        ) from exc
    candidate: Path | None = None
    # Connection OWNERSHIP: a session passed in by a caller (the test suite)
    # stays caller-owned and is never closed here -- closing someone else's
    # handle is not this function's business, and the caller may still want
    # to assert against it. A session this function opens itself is owned by
    # this function and MUST be closed on success and on every failure path,
    # including the guard failures raised inside `_fetch_snapshot`.
    owned_session = None
    try:
        # Credential-free by construction: PID and UTC start time only.
        try:
            os.write(lock_fd, f"pid={os.getpid()} started_at={datetime.now(timezone.utc).isoformat()}\n".encode("utf-8"))
        finally:
            os.close(lock_fd)  # closed even if the diagnostic write fails, so the fd cannot leak
        if session is not None:
            active_session = session
        else:
            active_session = owned_session = default_connect(_require_database_url())
        try:
            rows = _fetch_snapshot(active_session)
        finally:
            if owned_session is not None:
                _close_quietly(owned_session)
                owned_session = None
        fingerprint = _rows_fingerprint(rows)
        cache_rows = _to_cache_rows(rows)
        candidate = _build_candidate(profile, cache_rows, fingerprint)
        _validate_candidate(candidate, len(cache_rows), min_products, max_products)
        os.replace(candidate, profile.ada_cache_db)  # atomic: only a fully validated cache ever replaces the old one
        candidate = None
        return status_master_cache(profile)
    except BaseException:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        raise
    finally:
        if owned_session is not None:  # default_connect succeeded but _fetch_snapshot never started
            _close_quietly(owned_session)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _describe_lock(lock_path: Path) -> str:
    """Credential-free description of who holds the refresh lock."""
    try:
        body = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "holder unknown: lock body unreadable"
    return body or "holder unknown: lock body empty"


def status_master_cache(profile: AppProfile, *, stale_after_days: int = DEFAULT_STALE_AFTER_DAYS, now: datetime | None = None) -> dict:
    """Reports cache provenance WITHOUT any host/user/credential detail."""
    if not profile.ada_cache_db.exists():
        return {"status": "MISSING", "note": "No local ada_cache.db; Application.bootstrap would seed the packaged fixture"}
    cache = AdaReferenceCache(profile)
    health = cache.health()
    manifest = health.get("manifest", {})
    counts = json.loads(manifest.get("row_counts_json") or "{}")
    refreshed_at = manifest.get("refreshed_at")
    stale = False
    if refreshed_at:
        try:
            refreshed = datetime.fromisoformat(refreshed_at)
            if refreshed.tzinfo is None:
                refreshed = refreshed.replace(tzinfo=timezone.utc)
            reference = now or datetime.now(timezone.utc)
            stale = refreshed + timedelta(days=stale_after_days) < reference
        except ValueError:
            stale = True
    with cache.connect() as connection:
        actual_products = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    expected_products = counts.get("products")
    return {
        "status": "OK" if health.get("integrity") == "ok" and actual_products == expected_products else "DEGRADED",
        "source_type": manifest.get("source_instance"),
        "source_table": counts.get("source_table"),
        "refreshed_at": refreshed_at,
        "products": actual_products,
        "product_units": counts.get("product_units"),
        "source_fingerprint": counts.get("source_fingerprint"),
        "stale": stale,
        "stale_after_days": stale_after_days,
        "integrity": health.get("integrity"),
        # Stated on every status call so an operator reading the CLI output can
        # never mistake the cache's `active` flag for a production claim that the
        # product is commercially active. See CACHE_ACTIVE_MEANING.
        "active_meaning": counts.get("active_meaning") or CACHE_ACTIVE_MEANING,
    }
