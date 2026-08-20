from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import repository_root
from .errors import DomainError


CONTRACT_VERSION = "ocr-inbound-artifact.v1"


@dataclass(frozen=True)
class OcrCommandPlan:
    base_command: tuple[str, ...]
    layer_commands: tuple[tuple[str, ...], ...]


class ExistingOcrPipelineAdapter:
    """Versioned command adapter; the existing Layers A–E implementation remains untouched."""

    def __init__(self, python_executable: Path | None = None) -> None:
        self.python_executable = str(python_executable or Path(sys.executable))
        self.pipeline = repository_root() / "ocr_feasibility.py"

    def command_plan(self, source: Path, legacy_out_root: Path, run_dir: Path | None = None) -> OcrCommandPlan:
        base = (self.python_executable, str(self.pipeline), str(source), "--env", "staging", "--out", str(legacy_out_root), "--cpu-fast")
        if run_dir is None:
            return OcrCommandPlan(base, ())
        layer_flags = ("--table-band-run-dir", "--table-row-run-dir", "--table-column-run-dir", "--table-semantics-run-dir", "--row-classification-run-dir", "--layer-e-extract-run-dir")
        return OcrCommandPlan(base, tuple((self.python_executable, str(self.pipeline), "--env", "staging", flag, str(run_dir)) for flag in layer_flags))

    def run_base(self, source: Path, legacy_out_root: Path, timeout_seconds: int = 3600) -> subprocess.CompletedProcess[str]:
        plan = self.command_plan(source, legacy_out_root)
        return subprocess.run(plan.base_command, cwd=repository_root(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_seconds)


class VersionedOcrArtifactImporter:
    REQUIRED_HEADERS = {"supplier_code", "invoice_number", "invoice_date", "grand_total_minor"}

    def load_fixture_contract(self, path: Path) -> dict:
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.validate(payload)
        return payload

    def validate(self, payload: dict) -> None:
        if payload.get("contract_version") != CONTRACT_VERSION:
            raise DomainError("OCR_CONTRACT_UNSUPPORTED", f"Expected {CONTRACT_VERSION}")
        if not payload.get("ocr_run_id") or not isinstance(payload.get("lines"), list) or not payload["lines"]:
            raise DomainError("OCR_CONTRACT_INVALID", "OCR artifact requires run ID and at least one line")
        fields = payload.get("header", {}).get("fields", {})
        missing = self.REQUIRED_HEADERS - set(fields)
        if missing:
            raise DomainError("OCR_HEADER_MISSING", f"Missing header fields: {sorted(missing)}")
        for name, field in fields.items():
            if not field.get("source_prediction_ref") or "evidence" not in field:
                raise DomainError("OCR_FIELD_EVIDENCE_MISSING", f"Field {name} lacks immutable source/evidence")
        for index, line in enumerate(payload["lines"], 1):
            for key in ("source_row_ref", "raw_ocr_text", "description", "unit", "quantity", "unit_price_minor", "line_total_minor", "evidence"):
                if key not in line:
                    raise DomainError("OCR_LINE_INVALID", f"Line {index} missing {key}")
            if not isinstance(line["unit_price_minor"], int) or not isinstance(line["line_total_minor"], int):
                raise DomainError("OCR_MONEY_NOT_SCALED_INTEGER", f"Line {index} money must use minor-unit integers")

    def from_existing_layer_e(self, run_dir: Path, header_contract: Path) -> dict:
        line_path = run_dir / "tables" / "table_line_items.json"
        review_path = run_dir / "tables" / "table_line_items_review_decisions.json"
        if not line_path.exists() or not review_path.exists():
            raise DomainError("OCR_LAYER_E_INCOMPLETE", "Layer E artifacts and review decision are required")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if review.get("decision") not in {"accept", "accept_with_flags"}:
            raise DomainError("OCR_LAYER_E_NOT_ACCEPTED", "Layer E human review gate has not accepted the artifact")
        header = json.loads(header_contract.read_text(encoding="utf-8"))
        source = json.loads(line_path.read_text(encoding="utf-8"))
        lines = []
        for item in source.get("line_items", []):
            fields = item.get("extracted_fields", {})
            def value(name: str, default=None):
                return fields.get(name, {}).get("extracted_value", default)
            lines.append({
                "source_row_ref": item["row_id"], "raw_ocr_text": value("description", "") or "",
                "supplier_sku": value("supplier_sku"), "description": value("description", "") or "",
                "unit": value("unit", "") or "", "quantity": value("quantity", "0") or "0",
                "unit_price_minor": int(value("unit_price_minor", 0) or 0), "line_total_minor": int(value("line_total_minor", 0) or 0),
                "evidence": {"run_dir": run_dir.name, "row_id": item["row_id"], "fields": fields},
            })
        payload = {"contract_version": CONTRACT_VERSION, "ocr_run_id": run_dir.name, "ocr_engine_versions": header.get("ocr_engine_versions", {}), "header": header["header"], "lines": lines}
        self.validate(payload)
        return payload
