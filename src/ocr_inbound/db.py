from __future__ import annotations

import json
import importlib.resources
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import AppProfile
from .errors import DomainError
from .identity import Actor


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000):013x}{secrets.token_hex(8)}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ClosingConnection(sqlite3.Connection):
    """A sqlite connection whose context manager also releases its file handle.

    sqlite3.Connection normally commits or rolls back in ``__exit__`` but does
    not close.  That behaviour leaves databases locked during Windows cleanup.
    """

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


class Repository:
    """SQLite single-writer adapter. The application host owns this object."""

    def __init__(self, profile: AppProfile) -> None:
        self.profile = profile
        self.db_path = profile.app_db

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        existed = self.db_path.exists() and self.db_path.stat().st_size > 0
        if existed:
            self.backup("pre-migration")
        sql = importlib.resources.files("ocr_inbound").joinpath("migrations/0001_initial.sql").read_text(encoding="utf-8")
        sql_0002 = importlib.resources.files("ocr_inbound").joinpath("migrations/0002_product_name_aliases.sql").read_text(encoding="utf-8")
        sql_0003 = importlib.resources.files("ocr_inbound").joinpath("migrations/0003_product_review.sql").read_text(encoding="utf-8")
        connection = self.connect()
        try:
            # Journal mode is persistent database metadata. Setting it once at
            # migration avoids taking a WAL-mode lock on every short-lived read.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            version = connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            if version < 1:
                connection.executescript(sql)
                version = 1
            if version < 2:
                connection.executescript(sql_0002)
                version = 2
            if version < 3:
                connection.executescript(sql_0003)
            connection.commit()
        finally:
            connection.close()
        if self.integrity_check() != "ok":
            raise DomainError("DB_INTEGRITY_FAILED", "SQLite integrity check failed after migration")

    def backup(self, label: str = "manual") -> Path:
        self.profile.backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.profile.backups / f"app-{stamp}-{label}.db"
        if not self.db_path.exists():
            target.touch()
            return target
        source = self.connect()
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return target

    def restore(self, backup_path: Path) -> None:
        source_path = self.profile.assert_within_root(backup_path, "Backup")
        if not source_path.is_file():
            raise DomainError("BACKUP_NOT_FOUND", "Backup file not found")
        if self.db_path.exists():
            shutil.copy2(self.db_path, self.profile.backups / f"app-before-restore-{int(time.time())}.db")
        source = sqlite3.connect(source_path)
        destination = sqlite3.connect(self.db_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        if self.integrity_check() != "ok":
            raise DomainError("RESTORE_INTEGRITY_FAILED", "Restored database failed integrity check")

    def integrity_check(self) -> str:
        if not self.db_path.exists():
            return "missing"
        connection = self.connect()
        try:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    @staticmethod
    def _insert(connection: sqlite3.Connection, table: str, payload: dict) -> None:
        keys = tuple(payload)
        placeholders = ",".join("?" for _ in keys)
        connection.execute(f"INSERT INTO {table} ({','.join(keys)}) VALUES ({placeholders})", tuple(payload[key] for key in keys))

    def get_document_by_hash(self, source_sha256: str) -> dict | None:
        with self.connect() as connection:
            return self._dict(connection.execute("SELECT * FROM documents WHERE environment=? AND source_sha256=?", (self.profile.environment, source_sha256)).fetchone())

    def create_document(self, *, source_filename: str, source_sha256: str, source_artifact_path: str, actor: Actor, correlation_id: str) -> dict:
        existing = self.get_document_by_hash(source_sha256)
        if existing:
            return existing
        document_id, timestamp = new_id("doc"), now_iso()
        with self.transaction() as connection:
            self._insert(connection, "documents", {
                "id": document_id, "environment": self.profile.environment, "source_filename": source_filename,
                "source_sha256": source_sha256, "source_artifact_path": source_artifact_path, "status": "NEW",
                "last_stable_status": "NEW", "created_by": actor.actor_id, "created_at": timestamp, "updated_at": timestamp,
            })
            self._insert_audit(connection, actor.actor_id, "DOCUMENT_IMPORTED", "document", document_id, correlation_id, {"sha256": source_sha256, "artifact": source_artifact_path})
        return self.get_document(document_id)

    def get_document(self, document_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if row is None:
            raise DomainError("DOCUMENT_NOT_FOUND", f"Document not found: {document_id}")
        return dict(row)

    def list_documents(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM documents ORDER BY created_at DESC")]

    def import_ocr_projection(self, document_id: str, artifact: dict, actor: Actor, correlation_id: str) -> None:
        timestamp = now_iso()
        header = artifact["header"]
        with self.transaction() as connection:
            connection.execute("UPDATE documents SET status='PROCESSING', updated_at=? WHERE id=?", (timestamp, document_id))
            for name, field in header["fields"].items():
                value = field.get("value")
                self._insert(connection, "document_fields", {
                    "id": new_id("fld"), "document_id": document_id, "field_name": name,
                    "required": 1 if field.get("required") else 0, "raw_source_text": field.get("raw_text"),
                    "predicted_value_json": canonical_json(value), "final_value_json": canonical_json(value),
                    "confidence": str(field.get("confidence")) if field.get("confidence") is not None else None,
                    "evidence_json": canonical_json(field.get("evidence", {})), "source_prediction_ref": field["source_prediction_ref"],
                    "review_status": "UNREVIEWED", "created_at": timestamp, "updated_at": timestamp,
                })
            for index, line in enumerate(artifact["lines"], 1):
                self._insert(connection, "document_lines", {
                    "id": new_id("lin"), "document_id": document_id, "sequence": index,
                    "source_row_ref": line["source_row_ref"], "raw_ocr_text": line["raw_ocr_text"],
                    "supplier_sku": line.get("supplier_sku"), "description_final": line.get("description"),
                    "unit_final": line.get("unit"), "quantity_decimal": str(line.get("quantity")),
                    "free_quantity_decimal": str(line.get("free_quantity", "0")), "unit_price_minor": line.get("unit_price_minor"),
                    "discount_minor": line.get("discount_minor", 0), "line_total_minor": line.get("line_total_minor"),
                    "evidence_json": canonical_json(line.get("evidence", {})), "created_at": timestamp, "updated_at": timestamp,
                })
            supplier = header["fields"]["supplier_code"]["value"]
            invoice = header["fields"]["invoice_number"]["value"]
            invoice_date = header["fields"]["invoice_date"]["value"]
            total_minor = int(header["fields"]["grand_total_minor"]["value"])
            duplicate_key = f"{supplier}|{str(invoice).strip().upper()}|{invoice_date}|{total_minor}"
            connection.execute(
                "UPDATE documents SET status='NEEDS_REVIEW',last_stable_status='NEEDS_REVIEW',supplier_code=?,invoice_number_normalized=?,invoice_date=?,grand_total_minor=?,duplicate_key=?,ocr_contract_version=?,ocr_run_id=?,updated_at=? WHERE id=?",
                (supplier, str(invoice).strip().upper(), invoice_date, total_minor, duplicate_key, artifact["contract_version"], artifact["ocr_run_id"], timestamp, document_id),
            )
            self._insert_audit(connection, actor.actor_id, "OCR_ARTIFACT_IMPORTED", "document", document_id, correlation_id, {"contract_version": artifact["contract_version"], "line_count": len(artifact["lines"])})

    def list_fields(self, document_id: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM document_fields WHERE document_id=? ORDER BY field_name", (document_id,))]

    def list_lines(self, document_id: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM document_lines WHERE document_id=? ORDER BY sequence", (document_id,))]

    def persist_prediction_before_display(self, document_id: str, line_id: str, prediction: dict) -> dict:
        prediction_id, timestamp = new_id("pred"), now_iso()
        payload = {
            "id": prediction_id, "document_id": document_id, "document_line_id": line_id,
            "tier": prediction["tier"], "method": prediction["method"], "source_text": prediction["source_text"],
            "normalized_text": prediction["normalized_text"], "input_hash": prediction["input_hash"],
            "proposed_product_code": prediction.get("proposed_product_code"), "proposed_unit_code": prediction.get("proposed_unit_code"),
            "confidence": str(prediction.get("confidence")) if prediction.get("confidence") is not None else None,
            "candidate_set_json": canonical_json(prediction["candidate_set"]), "reason_codes_json": canonical_json(prediction["reason_codes"]),
            "provenance_json": canonical_json(prediction["provenance"]), "evidence_json": canonical_json(prediction["evidence"]),
            "ocr_engine_versions_json": canonical_json(prediction["ocr_engine_versions"]), "ruleset_version": prediction["ruleset_version"],
            "model_version": None, "created_at": timestamp,
        }
        with self.transaction() as connection:
            self._insert(connection, "layer_f_predictions", payload)
            connection.execute(
                "UPDATE document_lines SET current_prediction_id=?,ada_product_code=?,ada_unit_code=?,match_method=?,match_status=?,updated_at=? WHERE id=?",
                (prediction_id, prediction.get("proposed_product_code"), prediction.get("proposed_unit_code"), prediction["method"], "PROPOSED" if prediction.get("proposed_product_code") else "UNRESOLVED", timestamp, line_id),
            )
        return self.get_prediction(prediction_id)

    def get_prediction(self, prediction_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM layer_f_predictions WHERE id=?", (prediction_id,)).fetchone()
        if row is None:
            raise DomainError("PREDICTION_NOT_FOUND", "Prediction was not persisted")
        return dict(row)

    def list_predictions(self, document_id: str) -> list[dict]:
        # §31: `created_at` has only millisecond precision and `id` (new_id())
        # has a random suffix -- two predictions persisted in the same
        # millisecond can sort in EITHER order by (created_at,id), which is
        # not insertion order. SQLite's implicit `rowid` (this table uses a
        # TEXT PRIMARY KEY `id`, so `rowid` is a separate, always-monotonic
        # hidden column, never reused within this append-only table) is the
        # one ordering that is actually guaranteed to match commit order.
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM layer_f_predictions WHERE document_id=? ORDER BY rowid", (document_id,))]

    def commit_product_review(self, payload: dict, actor: Actor) -> dict:
        """Atomically commits receipt, authoritative label, audit, and alias observation."""
        timestamp = now_iso()
        with self.transaction() as connection:
            existing = connection.execute("SELECT * FROM product_review_decisions WHERE request_id=?", (payload["request_id"],)).fetchone()
            if existing:
                if existing["request_fingerprint"] != payload["request_fingerprint"]:
                    raise DomainError("IDEMPOTENCY_PAYLOAD_CONFLICT", "Request id was already used with a different review payload")
                return dict(existing)
            line = connection.execute("SELECT * FROM document_lines WHERE id=? AND document_id=?", (payload["document_line_id"], payload["document_id"])).fetchone()
            if line is None or line["current_prediction_id"] != payload["prediction_id"]:
                raise DomainError("PREDICTION_STALE", "Review requires the current persisted prediction")
            decision_id = new_id("prd")
            self._insert(connection, "product_review_decisions", {"id": decision_id, **payload, "actor_id": actor.actor_id, "created_at": timestamp})
            action = payload["action"]
            if action in {"CONFIRM", "CORRECT"}:
                event_id = new_id("rev")
                final = {"product_code": payload["selected_product_code"], "unit_code": payload["selected_unit_code"]}
                proposed = {"product_code": line["ada_product_code"], "unit_code": line["ada_unit_code"]}
                self._insert(connection, "review_events", {"id":event_id,"interaction_id":new_id("int"),"target_type":"PRODUCT","document_id":payload["document_id"],"document_line_id":line["id"],"prediction_id":payload["prediction_id"],"action":action,"original_value_json":canonical_json(proposed),"proposed_value_json":canonical_json(proposed),"final_value_json":canonical_json(final),"error_category":payload["error_category"],"evidence_json":line["evidence_json"],"versions_json":canonical_json({"ruleset":payload["ruleset_version"]}),"reviewer_id":actor.actor_id,"reviewer_display_name":actor.display_name,"decision_duration_ms":payload["duration_ms"],"occurred_at":timestamp})
                connection.execute("UPDATE document_lines SET ada_product_code=?,ada_unit_code=?,match_status='CONFIRMED',review_status=?,row_revision=row_revision+1,updated_at=? WHERE id=?", (payload["selected_product_code"],payload["selected_unit_code"],"CORRECTED" if action=="CORRECT" else "CONFIRMED",timestamp,line["id"]))
                alias = connection.execute("SELECT * FROM supplier_product_aliases WHERE supplier_code=? AND normalized_supplier_text=? AND ada_product_code=?", (payload["supplier_code"],payload["normalized_alias"],payload["selected_product_code"])).fetchone()
                if alias is None:
                    alias_id=new_id("als"); self._insert(connection,"supplier_product_aliases",{"id":alias_id,"supplier_code":payload["supplier_code"],"normalized_supplier_text":payload["normalized_alias"],"ada_product_code":payload["selected_product_code"],"status":"CANDIDATE","confirmation_count":1,"correction_count":0,"distinct_document_count":1,"observed_document_ids_json":canonical_json([payload["document_id"]]),"created_at":timestamp,"updated_at":timestamp})
                else:
                    alias_id=alias["id"]
                    ids=set(json.loads(alias["observed_document_ids_json"])); ids.add(payload["document_id"]); count=len(ids); status="ELIGIBLE" if count>=3 and alias["status"]=="CANDIDATE" else alias["status"]
                    connection.execute("UPDATE supplier_product_aliases SET confirmation_count=confirmation_count+1,distinct_document_count=?,observed_document_ids_json=?,status=?,updated_at=?,version=version+1 WHERE id=?",(count,canonical_json(sorted(ids)),status,timestamp,alias["id"]))
                conflicts=connection.execute("SELECT COUNT(DISTINCT ada_product_code) FROM supplier_product_aliases WHERE supplier_code=? AND normalized_supplier_text=?",(payload["supplier_code"],payload["normalized_alias"])).fetchone()[0]
                if conflicts>1: connection.execute("UPDATE supplier_product_aliases SET status='QUARANTINED',updated_at=? WHERE supplier_code=? AND normalized_supplier_text=?",(timestamp,payload["supplier_code"],payload["normalized_alias"]))
                # §29 finding 3: this alias-state mutation used to go
                # straight through with no dedicated audit trail (only the
                # generic PRODUCT_REVIEW_DECIDED below) -- the pre-existing
                # Repository.record_alias_observation() path (Slice 1)
                # always wrote an ALIAS_OBSERVED event here; this path must
                # too, so alias learning stays traceable the same way
                # regardless of which code path produced the observation.
                self._insert_audit(connection,actor.actor_id,"ALIAS_OBSERVED","supplier_product_alias",alias_id,new_id("corr"),{"document_id":payload["document_id"],"conflict":conflicts>1})
                self._invalidate_document(connection,payload["document_id"],timestamp)
            self._insert_audit(connection,actor.actor_id,"PRODUCT_REVIEW_DECIDED","document_line",line["id"],new_id("corr"),{"decision_id":decision_id,"action":action})
            return dict(connection.execute("SELECT * FROM product_review_decisions WHERE id=?",(decision_id,)).fetchone())

    def list_product_review_decisions(self, document_id: str) -> list[dict]:
        # §31: same monotonic-ordering fix as list_predictions() above --
        # `rowid` (product_review_decisions also has a TEXT PRIMARY KEY
        # `id`, so `rowid` is a separate always-increasing hidden column)
        # is the only ordering guaranteed to match actual commit order when
        # two decisions land in the same millisecond.
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM product_review_decisions WHERE document_id=? ORDER BY rowid", (document_id,))]

    def review_header(self, document_id: str, field_name: str, final_value: Any, action: str, error_category: str | None, duration_ms: int, actor: Actor, correlation_id: str) -> dict:
        with self.transaction() as connection:
            field = connection.execute("SELECT * FROM document_fields WHERE document_id=? AND field_name=?", (document_id, field_name)).fetchone()
            if field is None:
                raise DomainError("FIELD_NOT_FOUND", f"Header field not found: {field_name}")
            self._require_error_category(action, error_category)
            event_id, timestamp = new_id("rev"), now_iso()
            self._insert(connection, "review_events", {
                "id": event_id, "interaction_id": new_id("int"), "target_type": "HEADER", "document_id": document_id,
                "document_field_id": field["id"], "field_name": field_name, "source_prediction_ref": field["source_prediction_ref"],
                "action": action, "original_value_json": field["predicted_value_json"], "proposed_value_json": field["predicted_value_json"],
                "final_value_json": canonical_json(final_value), "error_category": error_category, "evidence_json": field["evidence_json"],
                "versions_json": canonical_json({"source": field["source_prediction_ref"]}), "reviewer_id": actor.actor_id,
                "reviewer_display_name": actor.display_name, "decision_duration_ms": duration_ms, "occurred_at": timestamp,
            })
            status = "CORRECTED" if action == "CORRECT" else "CONFIRMED"
            connection.execute("UPDATE document_fields SET final_value_json=?,review_status=?,field_revision=field_revision+1,updated_at=? WHERE id=?", (canonical_json(final_value), status, timestamp, field["id"]))
            projection_columns = {"supplier_code": "supplier_code", "invoice_number": "invoice_number_normalized", "invoice_date": "invoice_date", "grand_total_minor": "grand_total_minor"}
            if field_name in projection_columns:
                projected = str(final_value).strip().upper() if field_name == "invoice_number" else final_value
                connection.execute(f"UPDATE documents SET {projection_columns[field_name]}=? WHERE id=?", (projected, document_id))
                current = connection.execute("SELECT supplier_code,invoice_number_normalized,invoice_date,grand_total_minor FROM documents WHERE id=?", (document_id,)).fetchone()
                if all(current[key] is not None for key in current.keys()):
                    duplicate_key = f"{current['supplier_code']}|{current['invoice_number_normalized']}|{current['invoice_date']}|{current['grand_total_minor']}"
                    connection.execute("UPDATE documents SET duplicate_key=? WHERE id=?", (duplicate_key, document_id))
            self._invalidate_document(connection, document_id, timestamp)
            self._insert_audit(connection, actor.actor_id, f"HEADER_{action}", "document_field", field["id"], correlation_id, {"event_id": event_id, "error_category": error_category})
        return self.get_review_event(event_id)

    def review_product(self, document_id: str, line_id: str, product_code: str, unit_code: str, action: str, error_category: str | None, duration_ms: int, actor: Actor, correlation_id: str) -> dict:
        with self.transaction() as connection:
            line = connection.execute("SELECT * FROM document_lines WHERE id=? AND document_id=?", (line_id, document_id)).fetchone()
            if line is None:
                raise DomainError("LINE_NOT_FOUND", "Document line not found")
            prediction_id = line["current_prediction_id"]
            if not prediction_id:
                raise DomainError("PREDICTION_REQUIRED", "Product decision requires a persisted prediction")
            self._require_error_category(action, error_category)
            event_id, timestamp = new_id("rev"), now_iso()
            final = {"product_code": product_code, "unit_code": unit_code}
            proposed = {"product_code": line["ada_product_code"], "unit_code": line["ada_unit_code"]}
            self._insert(connection, "review_events", {
                "id": event_id, "interaction_id": new_id("int"), "target_type": "PRODUCT", "document_id": document_id,
                "document_line_id": line_id, "prediction_id": prediction_id, "action": action,
                "original_value_json": canonical_json(proposed), "proposed_value_json": canonical_json(proposed), "final_value_json": canonical_json(final),
                "error_category": error_category, "evidence_json": line["evidence_json"],
                "versions_json": canonical_json({"ruleset": "layer-f-v1"}), "reviewer_id": actor.actor_id,
                "reviewer_display_name": actor.display_name, "decision_duration_ms": duration_ms, "occurred_at": timestamp,
            })
            connection.execute("UPDATE document_lines SET ada_product_code=?,ada_unit_code=?,match_status='CONFIRMED',review_status=?,row_revision=row_revision+1,updated_at=? WHERE id=?", (product_code, unit_code, "CORRECTED" if action == "CORRECT" else "CONFIRMED", timestamp, line_id))
            self._invalidate_document(connection, document_id, timestamp)
            self._insert_audit(connection, actor.actor_id, f"PRODUCT_{action}", "document_line", line_id, correlation_id, {"event_id": event_id, "prediction_id": prediction_id, "error_category": error_category})
        return self.get_review_event(event_id)

    def review_line_value(self, document_id: str, line_id: str, field_name: str, final_value: Any, action: str, error_category: str | None, duration_ms: int, actor: Actor, correlation_id: str) -> dict:
        columns = {"description": "description_final", "unit": "unit_final", "quantity": "quantity_decimal", "free_quantity": "free_quantity_decimal", "unit_price_minor": "unit_price_minor", "discount_minor": "discount_minor", "line_total_minor": "line_total_minor"}
        column = columns.get(field_name)
        if column is None:
            raise DomainError("LINE_FIELD_UNSUPPORTED", f"Unsupported line field: {field_name}")
        with self.transaction() as connection:
            line = connection.execute("SELECT * FROM document_lines WHERE id=? AND document_id=?", (line_id, document_id)).fetchone()
            if line is None:
                raise DomainError("LINE_NOT_FOUND", "Document line not found")
            self._require_error_category(action, error_category)
            event_id, timestamp = new_id("rev"), now_iso()
            source_ref = f"{line['source_row_ref']}:{field_name}"
            self._insert(connection, "review_events", {
                "id": event_id, "interaction_id": new_id("int"), "target_type": "LINE_VALUE", "document_id": document_id,
                "document_line_id": line_id, "field_name": field_name, "source_prediction_ref": source_ref, "action": action,
                "original_value_json": canonical_json(line[column]), "proposed_value_json": canonical_json(line[column]), "final_value_json": canonical_json(final_value),
                "error_category": error_category, "evidence_json": line["evidence_json"], "versions_json": canonical_json({"source": source_ref}),
                "reviewer_id": actor.actor_id, "reviewer_display_name": actor.display_name, "decision_duration_ms": duration_ms, "occurred_at": timestamp,
            })
            connection.execute(f"UPDATE document_lines SET {column}=?,row_revision=row_revision+1,updated_at=? WHERE id=?", (final_value, timestamp, line_id))
            self._invalidate_document(connection, document_id, timestamp)
            self._insert_audit(connection, actor.actor_id, f"LINE_VALUE_{action}", "document_line", line_id, correlation_id, {"event_id": event_id, "field_name": field_name, "error_category": error_category})
        return self.get_review_event(event_id)

    def bulk_confirm_products(self, document_id: str, line_ids: list[str], duration_ms: int, actor: Actor, correlation_id: str) -> list[dict]:
        if not line_ids:
            return []
        interaction_id, timestamp = new_id("int"), now_iso()
        event_ids: list[str] = []
        with self.transaction() as connection:
            for line_id in line_ids:
                line = connection.execute("SELECT * FROM document_lines WHERE id=? AND document_id=?", (line_id, document_id)).fetchone()
                if line is None or not line["current_prediction_id"] or not line["ada_product_code"] or not line["ada_unit_code"]:
                    raise DomainError("BULK_CONFIRM_INELIGIBLE", "Bulk confirm includes an unresolved or unpredicted line")
                event_id = new_id("rev"); event_ids.append(event_id)
                value = {"product_code": line["ada_product_code"], "unit_code": line["ada_unit_code"]}
                self._insert(connection, "review_events", {
                    "id": event_id, "interaction_id": interaction_id, "target_type": "PRODUCT", "document_id": document_id,
                    "document_line_id": line_id, "prediction_id": line["current_prediction_id"], "action": "CONFIRM",
                    "original_value_json": canonical_json(value), "proposed_value_json": canonical_json(value), "final_value_json": canonical_json(value),
                    "evidence_json": line["evidence_json"], "versions_json": canonical_json({"ruleset": "layer-f-v1"}),
                    "reviewer_id": actor.actor_id, "reviewer_display_name": actor.display_name, "decision_duration_ms": duration_ms,
                    "occurred_at": timestamp,
                })
                connection.execute("UPDATE document_lines SET match_status='CONFIRMED',review_status='CONFIRMED',row_revision=row_revision+1,updated_at=? WHERE id=?", (timestamp, line_id))
            self._invalidate_document(connection, document_id, timestamp)
            self._insert_audit(connection, actor.actor_id, "PRODUCT_BULK_CONFIRM", "document", document_id, correlation_id, {"interaction_id": interaction_id, "target_count": len(line_ids)})
        return [self.get_review_event(event_id) for event_id in event_ids]

    @staticmethod
    def _require_error_category(action: str, error_category: str | None) -> None:
        if action in {"CORRECT", "REJECT", "RETRACT_LABEL"} and not error_category:
            raise DomainError("ERROR_CATEGORY_REQUIRED", f"{action} requires error_category")

    @staticmethod
    def _invalidate_document(connection: sqlite3.Connection, document_id: str, timestamp: str) -> None:
        connection.execute("UPDATE documents SET revision=revision+1,status='NEEDS_REVIEW',last_stable_status='NEEDS_REVIEW',review_snapshot_hash=NULL,updated_at=? WHERE id=?", (timestamp, document_id))
        connection.execute("UPDATE automation_runs SET state='FAILED',failure_code='STALE_DOCUMENT_REVISION',save_token_hash=NULL WHERE document_id=? AND state NOT IN ('COMPLETED','FAILED','STOPPED')", (document_id,))

    def get_review_event(self, event_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM review_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise DomainError("REVIEW_EVENT_NOT_FOUND", "Review event not found")
        return dict(row)

    def list_review_events(self, document_id: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM review_events WHERE document_id=? ORDER BY occurred_at,id", (document_id,))]

    def set_ready(self, document_id: str, snapshot_hash: str, actor: Actor, correlation_id: str) -> None:
        timestamp = now_iso()
        with self.transaction() as connection:
            connection.execute("UPDATE documents SET status='READY_FOR_ADA',last_stable_status='READY_FOR_ADA',review_snapshot_hash=?,updated_at=? WHERE id=?", (snapshot_hash, timestamp, document_id))
            self._insert_audit(connection, actor.actor_id, "DOCUMENT_READY", "document", document_id, correlation_id, {"snapshot_hash": snapshot_hash})

    def update_document_status(self, document_id: str, status: str, *, completed: bool = False) -> None:
        timestamp = now_iso()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE documents SET status=?,last_stable_status=?,updated_at=?,completed_at=? WHERE id=?",
                (status, status, timestamp, timestamp if completed else None, document_id),
            )

    def recover_startup_orphans(self, actor: Actor) -> dict:
        """Fail closed after a host restart; never resume UI automation blindly."""
        timestamp = now_iso()
        recovered_documents: list[str] = []
        recovered_runs: list[str] = []
        active_run_states = ("PREFLIGHT_PASSED", "ENTERING_LINES", "READING_BACK", "AWAITING_HUMAN_SAVE", "SAVING")
        with self.transaction() as connection:
            for document in connection.execute("SELECT id FROM documents WHERE status='PROCESSING'").fetchall():
                recovered_documents.append(document["id"])
                connection.execute(
                    "UPDATE documents SET status='FAILED',last_stable_status='FAILED',updated_at=? WHERE id=?",
                    (timestamp, document["id"]),
                )
                self._insert_audit(connection, actor.actor_id, "STARTUP_OCR_ORPHAN_RECOVERED", "document", document["id"], new_id("corr"), {"safe_state": "FAILED"})
            placeholders = ",".join("?" for _ in active_run_states)
            runs = connection.execute(
                f"SELECT id,document_id,state FROM automation_runs WHERE state IN ({placeholders})",
                active_run_states,
            ).fetchall()
            for run in runs:
                recovered_runs.append(run["id"])
                connection.execute(
                    "UPDATE automation_runs SET state='PAUSED',current_step='STARTUP_RECOVERY',failure_code='HOST_RESTARTED',save_token_hash=NULL,save_token_expires_at=NULL WHERE id=?",
                    (run["id"],),
                )
                connection.execute(
                    "UPDATE documents SET status='ADA_REVIEW_REQUIRED',last_stable_status='ADA_REVIEW_REQUIRED',updated_at=? WHERE id=? AND status<>'COMPLETED'",
                    (timestamp, run["document_id"]),
                )
                self._insert_audit(connection, actor.actor_id, "STARTUP_AUTOMATION_ORPHAN_PAUSED", "automation_run", run["id"], new_id("corr"), {"previous_state": run["state"], "safe_state": "PAUSED"})
        return {"documents_failed": recovered_documents, "automation_runs_paused": recovered_runs}

    def find_business_duplicates(self, document_id: str, duplicate_key: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM documents WHERE environment=? AND duplicate_key=? AND id<>? AND status<>'CANCELLED'", (self.profile.environment, duplicate_key, document_id))]

    def write_erp_fixture(self, row: dict) -> str:
        row_id = new_id("erp")
        with self.transaction() as connection:
            self._insert(connection, "erp_ground_truth", {"id": row_id, **row, "created_at": now_iso()})
        return row_id

    def list_erp_ground_truth(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM erp_ground_truth ORDER BY receipt_number,line_sequence")]

    def write_document_link(self, document_id: str, receipt_number: str, method: str, evidence: dict, actor: Actor) -> str:
        link_id = new_id("dlnk")
        with self.transaction() as connection:
            self._insert(connection, "document_links", {"id": link_id, "document_id": document_id, "receipt_number": receipt_number, "method": method, "evidence_json": canonical_json(evidence), "verified_by": actor.actor_id, "created_at": now_iso()})
        return link_id

    def list_document_links(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM document_links ORDER BY created_at")]

    def write_line_link(self, line_id: str, erp_id: str, method: str, evidence: dict, actor: Actor) -> str:
        link_id = new_id("llnk")
        with self.transaction() as connection:
            self._insert(connection, "line_links", {"id": link_id, "document_line_id": line_id, "erp_ground_truth_id": erp_id, "method": method, "evidence_json": canonical_json(evidence), "verified_by": actor.actor_id, "created_at": now_iso()})
        return link_id

    def list_line_links(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM line_links ORDER BY created_at")]

    def record_alias_observation(self, supplier_code: str, normalized_text: str, product_code: str, document_id: str, actor: Actor) -> dict:
        timestamp = now_iso()
        with self.transaction() as connection:
            existing = connection.execute("SELECT * FROM supplier_product_aliases WHERE supplier_code=? AND normalized_supplier_text=? AND ada_product_code=?", (supplier_code, normalized_text, product_code)).fetchone()
            if existing is None:
                alias_id = new_id("als")
                self._insert(connection, "supplier_product_aliases", {"id": alias_id, "supplier_code": supplier_code, "normalized_supplier_text": normalized_text, "ada_product_code": product_code, "status": "CANDIDATE", "confirmation_count": 1, "correction_count": 0, "distinct_document_count": 1, "observed_document_ids_json": canonical_json([document_id]), "created_at": timestamp, "updated_at": timestamp})
            else:
                alias_id = existing["id"]
                observed_ids = set(json.loads(existing["observed_document_ids_json"]))
                observed_ids.add(document_id)
                count = len(observed_ids)
                status = "ELIGIBLE" if count >= 3 and existing["status"] == "CANDIDATE" else existing["status"]
                connection.execute("UPDATE supplier_product_aliases SET confirmation_count=confirmation_count+1,distinct_document_count=?,observed_document_ids_json=?,status=?,updated_at=?,version=version+1 WHERE id=?", (count, canonical_json(sorted(observed_ids)), status, timestamp, alias_id))
            conflicts = connection.execute("SELECT COUNT(DISTINCT ada_product_code) FROM supplier_product_aliases WHERE supplier_code=? AND normalized_supplier_text=?", (supplier_code, normalized_text)).fetchone()[0]
            if conflicts > 1:
                connection.execute("UPDATE supplier_product_aliases SET status='QUARANTINED',updated_at=? WHERE supplier_code=? AND normalized_supplier_text=?", (timestamp, supplier_code, normalized_text))
            self._insert_audit(connection, actor.actor_id, "ALIAS_OBSERVED", "supplier_product_alias", alias_id, new_id("corr"), {"document_id": document_id, "conflict": conflicts > 1})
        return self.get_alias(alias_id)

    def approve_alias(self, alias_id: str, actor: Actor) -> dict:
        timestamp = now_iso()
        with self.transaction() as connection:
            alias = connection.execute("SELECT * FROM supplier_product_aliases WHERE id=?", (alias_id,)).fetchone()
            if alias is None:
                raise DomainError("ALIAS_NOT_FOUND", "Alias not found")
            if alias["status"] != "ELIGIBLE":
                raise DomainError("ALIAS_NOT_ELIGIBLE", "Alias requires 3 distinct documents and no conflict")
            connection.execute("UPDATE supplier_product_aliases SET status='ACTIVE',approved_by=?,updated_at=?,version=version+1 WHERE id=?", (actor.actor_id, timestamp, alias_id))
            self._insert_audit(connection, actor.actor_id, "ALIAS_APPROVED", "supplier_product_alias", alias_id, new_id("corr"), {"distinct_document_count": alias["distinct_document_count"]})
        return self.get_alias(alias_id)

    def get_alias(self, alias_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM supplier_product_aliases WHERE id=?", (alias_id,)).fetchone()
        if row is None:
            raise DomainError("ALIAS_NOT_FOUND", "Alias not found")
        return dict(row)

    def list_aliases(self, supplier_code: str | None = None) -> list[dict]:
        with self.connect() as connection:
            if supplier_code:
                rows = connection.execute("SELECT * FROM supplier_product_aliases WHERE supplier_code=? ORDER BY normalized_supplier_text", (supplier_code,))
            else:
                rows = connection.execute("SELECT * FROM supplier_product_aliases ORDER BY supplier_code,normalized_supplier_text")
            return [dict(row) for row in rows]

    # --- Slice 2: supplier-agnostic spelling/name aliases (see 0002_product_name_aliases.sql) ---

    def record_name_alias_observation(self, normalized_text: str, product_code: str, document_id: str, actor: Actor) -> dict:
        timestamp = now_iso()
        with self.transaction() as connection:
            existing = connection.execute("SELECT * FROM product_name_aliases WHERE normalized_text=? AND ada_product_code=?", (normalized_text, product_code)).fetchone()
            if existing is None:
                alias_id = new_id("nal")
                self._insert(connection, "product_name_aliases", {"id": alias_id, "normalized_text": normalized_text, "ada_product_code": product_code, "status": "CANDIDATE", "confirmation_count": 1, "correction_count": 0, "distinct_document_count": 1, "observed_document_ids_json": canonical_json([document_id]), "created_at": timestamp, "updated_at": timestamp})
            else:
                alias_id = existing["id"]
                observed_ids = set(json.loads(existing["observed_document_ids_json"]))
                observed_ids.add(document_id)
                count = len(observed_ids)
                status = "ELIGIBLE" if count >= 3 and existing["status"] == "CANDIDATE" else existing["status"]
                connection.execute("UPDATE product_name_aliases SET confirmation_count=confirmation_count+1,distinct_document_count=?,observed_document_ids_json=?,status=?,updated_at=?,version=version+1 WHERE id=?", (count, canonical_json(sorted(observed_ids)), status, timestamp, alias_id))
            conflicts = connection.execute("SELECT COUNT(DISTINCT ada_product_code) FROM product_name_aliases WHERE normalized_text=?", (normalized_text,)).fetchone()[0]
            if conflicts > 1:
                connection.execute("UPDATE product_name_aliases SET status='QUARANTINED',updated_at=? WHERE normalized_text=?", (timestamp, normalized_text))
            self._insert_audit(connection, actor.actor_id, "NAME_ALIAS_OBSERVED", "product_name_alias", alias_id, new_id("corr"), {"document_id": document_id, "conflict": conflicts > 1})
        return self.get_name_alias(alias_id)

    def approve_name_alias(self, alias_id: str, actor: Actor) -> dict:
        timestamp = now_iso()
        with self.transaction() as connection:
            alias = connection.execute("SELECT * FROM product_name_aliases WHERE id=?", (alias_id,)).fetchone()
            if alias is None:
                raise DomainError("NAME_ALIAS_NOT_FOUND", "Name alias not found")
            if alias["status"] != "ELIGIBLE":
                raise DomainError("NAME_ALIAS_NOT_ELIGIBLE", "Name alias requires 3 distinct documents and no conflict")
            connection.execute("UPDATE product_name_aliases SET status='ACTIVE',approved_by=?,updated_at=?,version=version+1 WHERE id=?", (actor.actor_id, timestamp, alias_id))
            self._insert_audit(connection, actor.actor_id, "NAME_ALIAS_APPROVED", "product_name_alias", alias_id, new_id("corr"), {"distinct_document_count": alias["distinct_document_count"]})
        return self.get_name_alias(alias_id)

    def get_name_alias(self, alias_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM product_name_aliases WHERE id=?", (alias_id,)).fetchone()
        if row is None:
            raise DomainError("NAME_ALIAS_NOT_FOUND", "Name alias not found")
        return dict(row)

    def list_name_aliases(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM product_name_aliases ORDER BY normalized_text")]

    def create_automation_run(self, payload: dict) -> dict:
        run_id = new_id("ada")
        with self.transaction() as connection:
            self._insert(connection, "automation_runs", {"id": run_id, **payload, "started_at": now_iso()})
        return self.get_automation_run(run_id)

    def get_automation_run(self, run_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM automation_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainError("AUTOMATION_RUN_NOT_FOUND", "Automation run not found")
        return dict(row)

    def update_automation_run(self, run_id: str, **values: Any) -> None:
        allowed = {"state","current_step","current_line_sequence","reconciliation_json","reconciliation_hash","save_authorized_by","save_token_hash","save_token_expires_at","save_token_consumed_at","finished_at","ada_document_number","failure_code","receipt_artifact_ref"}
        if not values or not set(values).issubset(allowed):
            raise DomainError("AUTOMATION_UPDATE_INVALID", "Invalid automation projection update")
        with self.transaction() as connection:
            connection.execute(f"UPDATE automation_runs SET {','.join(f'{key}=?' for key in values)} WHERE id=?", (*values.values(), run_id))

    def list_automation_runs(self, document_id: str | None = None) -> list[dict]:
        with self.connect() as connection:
            if document_id:
                rows = connection.execute("SELECT * FROM automation_runs WHERE document_id=? ORDER BY started_at", (document_id,))
            else:
                rows = connection.execute("SELECT * FROM automation_runs ORDER BY started_at")
            return [dict(row) for row in rows]

    def set_save_authorization(self, run_id: str, actor_id: str, token_hash: str, expires_at: str) -> None:
        with self.transaction() as connection:
            run = connection.execute("SELECT state FROM automation_runs WHERE id=?", (run_id,)).fetchone()
            if run is None or run["state"] != "AWAITING_HUMAN_SAVE":
                raise DomainError("SAVE_AUTH_STATE_INVALID", "Run is not awaiting human save authorization")
            connection.execute("UPDATE automation_runs SET save_authorized_by=?,save_token_hash=?,save_token_expires_at=? WHERE id=?", (actor_id, token_hash, expires_at, run_id))

    def consume_save_authorization(self, run_id: str, actor_id: str, token_hash: str, now: str) -> dict:
        with self.transaction() as connection:
            run = connection.execute("SELECT * FROM automation_runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                raise DomainError("AUTOMATION_RUN_NOT_FOUND", "Automation run not found")
            if run["save_token_consumed_at"] is not None:
                raise DomainError("SAVE_TOKEN_USED", "Save authorization token has already been used")
            if run["save_authorized_by"] != actor_id or run["save_token_hash"] != token_hash:
                raise DomainError("SAVE_TOKEN_INVALID", "Save authorization token binding is invalid")
            if not run["save_token_expires_at"] or run["save_token_expires_at"] <= now:
                raise DomainError("SAVE_TOKEN_EXPIRED", "Save authorization token has expired")
            connection.execute("UPDATE automation_runs SET save_token_consumed_at=?,state='SAVING',current_step='SAVE' WHERE id=?", (now, run_id))
        return self.get_automation_run(run_id)

    def append_automation_event(self, run_id: str, event: dict) -> dict:
        with self.transaction() as connection:
            sequence = connection.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM automation_events WHERE automation_run_id=?", (run_id,)).fetchone()[0]
            event_id = new_id("aev")
            self._insert(connection, "automation_events", {"id": event_id, "automation_run_id": run_id, "sequence": sequence, "message_id": event["message_id"], "command_id": event["command_id"], "kind": event["kind"], "severity": event.get("severity", "INFO"), "step": event["step"], "line_sequence": event.get("line_sequence"), "expected_json": canonical_json(event.get("expected", {})), "observed_json": canonical_json(event.get("observed", {})), "evidence_ref": event.get("evidence_ref"), "occurred_at": event.get("occurred_at", now_iso())})
        return self.get_automation_event(event_id)

    def get_automation_event(self, event_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM automation_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise DomainError("AUTOMATION_EVENT_NOT_FOUND", "Automation event not found")
        return dict(row)

    def list_automation_events(self, run_id: str) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM automation_events WHERE automation_run_id=? ORDER BY sequence", (run_id,))]

    def append_audit(self, actor_id: str, action: str, entity_type: str, entity_id: str, correlation_id: str, detail: dict) -> str:
        with self.transaction() as connection:
            return self._insert_audit(connection, actor_id, action, entity_type, entity_id, correlation_id, detail)

    @staticmethod
    def _insert_audit(connection: sqlite3.Connection, actor_id: str, action: str, entity_type: str, entity_id: str, correlation_id: str, detail: dict) -> str:
        audit_id = new_id("aud")
        Repository._insert(connection, "audit_events", {"id": audit_id, "actor_id": actor_id, "action": action, "entity_type": entity_type, "entity_id": entity_id, "correlation_id": correlation_id, "detail_json": canonical_json(detail), "occurred_at": now_iso()})
        return audit_id

    def list_audit_events(self, entity_id: str | None = None) -> list[dict]:
        with self.connect() as connection:
            if entity_id:
                rows = connection.execute("SELECT * FROM audit_events WHERE entity_id=? ORDER BY occurred_at,id", (entity_id,))
            else:
                rows = connection.execute("SELECT * FROM audit_events ORDER BY occurred_at,id")
            return [dict(row) for row in rows]

    def metrics(self) -> dict:
        with self.connect() as connection:
            return {
                "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "completed": connection.execute("SELECT COUNT(*) FROM documents WHERE status='COMPLETED'").fetchone()[0],
                "review_decisions": connection.execute("SELECT COUNT(*) FROM review_events").fetchone()[0],
                "review_duration_ms": connection.execute("SELECT COALESCE(SUM(decision_duration_ms),0) FROM (SELECT interaction_id,MAX(decision_duration_ms) decision_duration_ms FROM review_events GROUP BY interaction_id)").fetchone()[0],
                "predictions_by_tier": {row[0]: row[1] for row in connection.execute("SELECT tier,COUNT(*) FROM layer_f_predictions GROUP BY tier")},
                "automation_by_state": {row[0]: row[1] for row in connection.execute("SELECT state,COUNT(*) FROM automation_runs GROUP BY state")},
                "duplicates_caught": connection.execute("SELECT COUNT(*) FROM audit_events WHERE action LIKE 'DUPLICATE_%'").fetchone()[0],
            }
