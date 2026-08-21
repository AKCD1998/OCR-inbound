from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Iterable, Protocol

from .config import AppProfile
from .db import ClosingConnection, now_iso
from .errors import DomainError
from .text_normalize import detect_script, normalize_product_text


def _split_bilingual_name(product: dict) -> tuple[str, str]:
    """Returns (name_thai, name_eng) for one fixture product row. Prefers
    explicit `name_thai`/`name_eng` fixture keys (the real bilingual shape,
    see `refresh_from_fixture`); falls back to auto-detecting the script of
    a legacy single `name` field so pre-Slice-2 fixtures (every Slice 0/1
    test, and the packaged default fixture) keep behaving exactly as
    before -- a pure-English legacy name populates only `name_eng`, a
    pure-Thai legacy name populates only `name_thai`. A legacy name that
    itself mixes both scripts is stored in BOTH slots rather than dropped
    from either, so no existing search capability is lost."""
    explicit_thai = (product.get("name_thai") or "").strip()
    explicit_eng = (product.get("name_eng") or "").strip()
    if explicit_thai or explicit_eng:
        return explicit_thai, explicit_eng
    legacy = (product.get("name") or "").strip()
    if not legacy:
        return "", ""
    script = detect_script(legacy)
    if script == "THAI":
        return legacy, ""
    if script == "LATIN":
        return "", legacy
    # MIXED or NEITHER (digits/symbols only, e.g. a placeholder code used as
    # a name in a synthetic test fixture): keep it available under both
    # slots rather than silently discarding it from one language's search.
    return legacy, legacy


SELECT_PRODUCT = "SELECT product_code,barcode,name,ingredient,strength,size,manufacturer,active FROM products WHERE product_code=:product_code AND active=1"
SELECT_SUPPLIER = "SELECT supplier_code,name,active FROM suppliers WHERE supplier_code=:supplier_code AND active=1"
SELECT_EXISTING_INVOICE = "SELECT supplier_code,invoice_number,invoice_date,grand_total_minor FROM approved_receipts WHERE supplier_code=:supplier_code AND invoice_number=:invoice_number"


class AdaReadGateway(Protocol):
    def get_product(self, product_code: str) -> dict | None: ...
    def get_supplier(self, supplier_code: str) -> dict | None: ...
    def find_existing_invoice(self, supplier_code: str, invoice_number: str) -> dict | None: ...


class DisabledLiveAdaReadGateway:
    def __getattr__(self, name: str):
        raise DomainError("LIVE_ADACC_DISABLED", "Live AdaAcc read capability is disabled pending schema/permission proof")


class AdaReferenceCache:
    def __init__(self, profile: AppProfile) -> None:
        self.profile = profile
        self.path = profile.ada_cache_db

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE products(product_code TEXT PRIMARY KEY,barcode TEXT,name TEXT NOT NULL,normalized_name TEXT NOT NULL,name_thai TEXT,name_eng TEXT,normalized_name_thai TEXT,normalized_name_eng TEXT,ingredient TEXT,strength TEXT,size TEXT,manufacturer TEXT,active INTEGER NOT NULL,snapshot_at TEXT NOT NULL);
            CREATE TABLE product_units(product_code TEXT NOT NULL,unit_code TEXT NOT NULL,factor_decimal TEXT NOT NULL,active INTEGER NOT NULL,PRIMARY KEY(product_code,unit_code));
            CREATE TABLE suppliers(supplier_code TEXT PRIMARY KEY,name TEXT NOT NULL,active INTEGER NOT NULL);
            CREATE TABLE purchase_history(supplier_code TEXT NOT NULL,product_code TEXT NOT NULL,last_price_minor INTEGER,purchase_count INTEGER NOT NULL,last_purchase_date TEXT,PRIMARY KEY(supplier_code,product_code));
            CREATE TABLE cache_manifest(id INTEGER PRIMARY KEY CHECK(id=1),source_instance TEXT NOT NULL,schema_fingerprint TEXT NOT NULL,refreshed_at TEXT NOT NULL,row_counts_json TEXT NOT NULL);
            """
        )

    def refresh_from_fixture(self, fixture: dict) -> None:
        # --- Bilingual name contract (Slice 2, see
        # docs/DEV_LAPTOP_SETUP_LEDGER_TH.md section 22) ---------------------
        # The real product master carries `product_name_thai` and
        # `product_name_eng` as two INDEPENDENT fields -- COALESCE-collapsing
        # them into one search field (the pre-Slice-2 harness did exactly
        # this: `COALESCE(NULLIF(eng,''), NULLIF(thai,''))`) silently throws
        # away whichever language a reviewer didn't happen to pick, and any
        # OCR text in the discarded language can never match again. Fixture
        # products may now supply `name_thai`/`name_eng` directly (both
        # independently optional, at least one non-empty); this cache never
        # merges them into a single search value. The legacy single-`name`
        # fixture shape (every Slice 0/1 test, and the packaged default
        # fixture) is still accepted for backward compatibility, with the
        # language auto-detected from the script actually used so old
        # single-language fixtures behave identically to before.
        self.profile.root.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="ada_cache.", suffix=".next", dir=self.profile.root)
        os.close(fd)
        temp = Path(temp_name)
        connection = sqlite3.connect(temp)
        try:
            self._schema(connection)
            timestamp = now_iso()
            for product in fixture["products"]:
                name_thai, name_eng = _split_bilingual_name(product)
                normalized_name_thai = normalize_product_text(name_thai) if name_thai else None
                normalized_name_eng = normalize_product_text(name_eng) if name_eng else None
                legacy_name = product.get("name") or name_eng or name_thai or ""
                legacy_normalized = product.get("normalized_name") or normalize_product_text(legacy_name)
                connection.execute(
                    "INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        product["product_code"], product.get("barcode"), legacy_name, legacy_normalized,
                        name_thai or None, name_eng or None, normalized_name_thai, normalized_name_eng,
                        product.get("ingredient"), product.get("strength"), product.get("size"),
                        product.get("manufacturer"), 1 if product.get("active", True) else 0, timestamp,
                    ),
                )
                for unit in product.get("units", []):
                    connection.execute("INSERT INTO product_units VALUES(?,?,?,?)", (product["product_code"], unit["unit_code"], str(unit.get("factor", "1")), 1 if unit.get("active", True) else 0))
            for supplier in fixture["suppliers"]:
                connection.execute("INSERT INTO suppliers VALUES(?,?,?)", (supplier["supplier_code"], supplier["name"], 1 if supplier.get("active", True) else 0))
            for history in fixture.get("purchase_history", []):
                connection.execute("INSERT INTO purchase_history VALUES(?,?,?,?,?)", (history["supplier_code"], history["product_code"], history.get("last_price_minor"), history.get("purchase_count", 0), history.get("last_purchase_date")))
            counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("products","product_units","suppliers","purchase_history")}
            connection.execute("INSERT INTO cache_manifest VALUES(1,?,?,?,?)", ("STAGING_FIXTURE", "ada-cache-v1", timestamp, json.dumps(counts, sort_keys=True)))
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or counts["products"] == 0:
                raise DomainError("ADA_CACHE_INVALID", "Reference cache validation failed")
        finally:
            connection.close()
        os.replace(temp, self.path)

    def connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise DomainError("ADA_CACHE_MISSING", "ADA reference cache has not been initialized")
        connection = sqlite3.connect(
            f"file:{self.path.as_posix()}?mode=ro",
            uri=True,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def get_product(self, product_code: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM products WHERE product_code=? AND active=1", (product_code,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["units"] = [dict(unit) for unit in connection.execute("SELECT * FROM product_units WHERE product_code=? AND active=1 ORDER BY unit_code", (product_code,))]
            return result

    def get_supplier(self, supplier_code: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM suppliers WHERE supplier_code=? AND active=1", (supplier_code,)).fetchone()
            return dict(row) if row else None

    def list_products(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM products WHERE active=1 ORDER BY product_code")]

    def find_by_barcode(self, barcode: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM products WHERE barcode=? AND active=1", (barcode,)).fetchone()
            return dict(row) if row else None

    def find_by_normalized_name(self, name: str) -> list[dict]:
        # Bilingual OR-match (Slice 2): a query normalized string is an
        # exact match if it equals EITHER the Thai OR the English normalized
        # name -- never a COALESCE-collapsed single field. `name` (the
        # legacy fallback column) is intentionally NOT part of this
        # condition; for a genuinely bilingual product it can equal neither
        # the Thai nor the English half exactly (it is just "whichever one
        # happened to be picked" for display), so matching against it here
        # would reintroduce exactly the single-language bias this rework
        # removes.
        with self.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM products WHERE active=1 AND (normalized_name_thai=? OR normalized_name_eng=?) ORDER BY product_code",
                    (name, name),
                )
            ]

    def purchase_history(self, supplier_code: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM purchase_history WHERE supplier_code=? ORDER BY purchase_count DESC,product_code", (supplier_code,))]

    def manifest(self) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM cache_manifest WHERE id=1").fetchone()
            return dict(row) if row else {}

    def health(self) -> dict:
        with self.connect() as connection:
            return {"integrity": connection.execute("PRAGMA integrity_check").fetchone()[0], "manifest": self.manifest()}
