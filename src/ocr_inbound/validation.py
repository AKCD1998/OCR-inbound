from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .ada_read import AdaReferenceCache
from .db import Repository, canonical_json
from .money import line_total_minor, parse_decimal


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    target_type: str
    target_id: str
    field_name: str | None
    expected: Any
    observed: Any
    blocking: bool
    safe_next_action: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]
    snapshot_hash: str
    canonical_snapshot: dict

    @property
    def ready(self) -> bool:
        return not any(issue.blocking for issue in self.issues)

    def as_dict(self) -> dict:
        return {"ready": self.ready, "issues": [asdict(issue) for issue in self.issues], "snapshot_hash": self.snapshot_hash, "canonical_snapshot": self.canonical_snapshot}


class InvoiceValidationService:
    RULE_VERSION = "invoice-validation-v1"

    def __init__(self, repository: Repository, cache: AdaReferenceCache) -> None:
        self.repository = repository
        self.cache = cache

    def validate(self, document_id: str) -> ValidationResult:
        document = self.repository.get_document(document_id)
        fields = self.repository.list_fields(document_id)
        lines = self.repository.list_lines(document_id)
        issues: list[ValidationIssue] = []
        for field in fields:
            final = json.loads(field["final_value_json"])
            if field["required"] and (final is None or str(final).strip() == ""):
                issues.append(self._issue("REQUIRED_FIELD_MISSING", "HEADER", field["id"], field["field_name"], "non-empty", final, "Review the highlighted header field"))
            if field["required"] and field["review_status"] not in {"CONFIRMED", "CORRECTED"}:
                issues.append(self._issue("FIELD_UNREVIEWED", "HEADER", field["id"], field["field_name"], "confirmed/corrected", field["review_status"], "Confirm or correct the field"))
        if self.cache.get_supplier(document["supplier_code"] or "") is None:
            issues.append(self._issue("SUPPLIER_UNRESOLVED", "DOCUMENT", document_id, "supplier_code", "active cache supplier", document["supplier_code"], "Select a valid supplier"))

        sum_minor = 0
        for line in lines:
            if line["review_status"] not in {"CONFIRMED", "CORRECTED"}:
                issues.append(self._issue("LINE_UNREVIEWED", "LINE", line["id"], None, "confirmed/corrected", line["review_status"], "Confirm or correct the line"))
            product = self.cache.get_product(line["ada_product_code"] or "")
            if product is None:
                issues.append(self._issue("PRODUCT_NOT_FOUND", "LINE", line["id"], "ada_product_code", "active master product", line["ada_product_code"], "Select a product from the ADA cache"))
            elif line["ada_unit_code"] not in {unit["unit_code"] for unit in product["units"]}:
                issues.append(self._issue("UNIT_INVALID", "LINE", line["id"], "ada_unit_code", [unit["unit_code"] for unit in product["units"]], line["ada_unit_code"], "Select an active unit"))
            try:
                quantity = parse_decimal(line["quantity_decimal"] or "")
                if quantity <= 0:
                    raise ValueError
            except Exception:
                issues.append(self._issue("QUANTITY_FORMAT_INVALID", "LINE", line["id"], "quantity", "positive decimal", line["quantity_decimal"], "Correct quantity"))
                continue
            expected_line = line_total_minor(line["quantity_decimal"], int(line["unit_price_minor"] or 0), int(line["discount_minor"] or 0))
            observed_line = line["line_total_minor"]
            if expected_line != observed_line:
                issues.append(self._issue("LINE_TOTAL_MISMATCH", "LINE", line["id"], "line_total_minor", expected_line, observed_line, "Correct quantity, price, discount, or line total"))
            if observed_line is not None:
                sum_minor += int(observed_line)

        if sum_minor != document["grand_total_minor"]:
            issues.append(self._issue("INVOICE_TOTAL_MISMATCH", "DOCUMENT", document_id, "grand_total_minor", sum_minor, document["grand_total_minor"], "Resolve line/header total difference"))
        duplicates = self.repository.find_business_duplicates(document_id, document["duplicate_key"] or "")
        if duplicates:
            issues.append(self._issue("DUPLICATE_EXACT", "DOCUMENT", document_id, "duplicate_key", "unique active invoice", [row["id"] for row in duplicates], "Open the existing document; do not send again"))

        snapshot = {
            "document_id": document_id, "revision": document["revision"], "supplier_code": document["supplier_code"],
            "invoice_number": document["invoice_number_normalized"], "invoice_date": document["invoice_date"],
            "grand_total_minor": document["grand_total_minor"], "row_count": len(lines),
            "fields": [{"name": item["field_name"], "value": json.loads(item["final_value_json"]), "status": item["review_status"]} for item in fields],
            "lines": [{"id": line["id"], "sequence": line["sequence"], "product_code": line["ada_product_code"], "unit_code": line["ada_unit_code"], "quantity": line["quantity_decimal"], "unit_price_minor": line["unit_price_minor"], "discount_minor": line["discount_minor"], "line_total_minor": line["line_total_minor"], "status": line["review_status"]} for line in lines],
            "rule_version": self.RULE_VERSION,
        }
        snapshot_hash = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
        return ValidationResult(tuple(issues), snapshot_hash, snapshot)

    @staticmethod
    def _issue(code: str, target_type: str, target_id: str, field_name: str | None, expected: Any, observed: Any, safe_next_action: str) -> ValidationIssue:
        return ValidationIssue(code, "RED", target_type, target_id, field_name, expected, observed, True, safe_next_action)


class ReconciliationService:
    def reconcile(self, expected: dict, observed: dict) -> dict:
        comparisons = {}
        for key in ("target_company", "target_branch", "supplier_code", "invoice_number", "row_count", "grand_total_minor"):
            exp = expected.get(key)
            obs = observed.get(key, "UNKNOWN")
            comparisons[key] = {"expected": exp, "observed": obs, "match": obs != "UNKNOWN" and obs == exp}
        passed = all(item["match"] for item in comparisons.values())
        return {"passed": passed, "comparisons": comparisons, "unknown_is_failure": True}
