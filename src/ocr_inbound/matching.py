from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

from .ada_read import AdaReferenceCache
from .db import Repository, canonical_json


INTERNAL_CODE = re.compile(r"\b(?:IC-\d{4}|630\d{4})\b", re.IGNORECASE)


def normalize_product_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").upper()
    normalized = re.sub(r"[^0-9A-Zก-๙]+", " ", normalized)
    return " ".join(normalized.split())


class ProductMatcher:
    RULESET_VERSION = "layer-f-v1"

    def __init__(self, repository: Repository, cache: AdaReferenceCache) -> None:
        self.repository = repository
        self.cache = cache

    def predict_and_persist(self, document: dict, line: dict, ocr_versions: dict) -> dict:
        prediction = self._predict(document, line, ocr_versions)
        persisted = self.repository.persist_prediction_before_display(document["id"], line["id"], prediction)
        # The DTO is assembled only after the insert transaction committed and was read back.
        return {"prediction_id": persisted["id"], "tier": persisted["tier"], "method": persisted["method"], "product_code": persisted["proposed_product_code"], "unit_code": persisted["proposed_unit_code"], "candidates": prediction["candidate_set"], "provenance": prediction["provenance"]}

    def _predict(self, document: dict, line: dict, ocr_versions: dict) -> dict:
        source_text = " ".join(filter(None, [line.get("supplier_sku"), line.get("description_final"), line.get("raw_ocr_text")]))
        normalized = normalize_product_text(source_text)
        candidates: list[dict] = []
        selected: dict | None = None
        tier, method, reasons = "UNRESOLVED", "unresolved_human", ["NO_MASTER_CANDIDATE_RESOLVED"]

        codes = INTERNAL_CODE.findall(source_text)
        for code in codes:
            product = self.cache.get_product(code.upper())
            if product:
                selected, tier, method, reasons = product, "EXACT_CODE", "exact_internal_code", ["MASTER_CODE_EXACT"]
                break
        if selected is None and line.get("supplier_sku"):
            product = self.cache.find_by_barcode(str(line["supplier_sku"]).strip())
            if product:
                selected, tier, method, reasons = product, "EXACT_BARCODE", "exact_barcode", ["MASTER_BARCODE_EXACT"]

        aliases = self.repository.list_aliases(document["supplier_code"])
        if selected is None:
            active = [alias for alias in aliases if alias["status"] == "ACTIVE" and alias["normalized_supplier_text"] in normalized]
            if len(active) == 1:
                selected = self.cache.get_product(active[0]["ada_product_code"])
                if selected:
                    tier, method, reasons = "ACTIVE_ALIAS", "supplier_active_alias", ["NAMED_APPROVED_ALIAS"]

        description_normalized = normalize_product_text(line.get("description_final") or "")
        if selected is None:
            exact_names = self.cache.find_by_normalized_name(description_normalized)
            if len(exact_names) == 1:
                selected, tier, method, reasons = exact_names[0], "EXACT_NAME", "exact_normalized_name", ["MASTER_NAME_EXACT"]

        history_codes = {row["product_code"]: row for row in self.cache.purchase_history(document["supplier_code"])}
        products = self.cache.list_products()
        for product in products:
            score = SequenceMatcher(None, description_normalized, product["normalized_name"]).ratio()
            if product["product_code"] in history_codes:
                score = min(1.0, score + 0.05)
            if score >= 0.45:
                candidates.append({"product_code": product["product_code"], "name": product["name"], "score": f"{score:.4f}", "purchase_count": history_codes.get(product["product_code"], {}).get("purchase_count", 0)})
        candidates.sort(key=lambda item: (-float(item["score"]), item["product_code"]))
        candidates = candidates[:5]
        if selected is None and candidates:
            top = self.cache.get_product(candidates[0]["product_code"])
            selected, tier, method, reasons = top, "FUZZY_SUGGESTION", "fuzzy_human_suggestion", ["HUMAN_CONFIRM_REQUIRED"]

        if selected and not self.cache.get_product(selected["product_code"]):
            selected = None
            tier, method, reasons = "UNRESOLVED", "unresolved_human", ["OUT_OF_MASTER_BLOCKED"]
        if selected and not candidates:
            candidates = [{"product_code": selected["product_code"], "name": selected["name"], "score": "1.0000", "purchase_count": history_codes.get(selected["product_code"], {}).get("purchase_count", 0)}]
        unit_code = None
        if selected:
            full = self.cache.get_product(selected["product_code"])
            raw_unit = (line.get("unit_final") or "").upper()
            valid_units = [item["unit_code"] for item in full.get("units", [])]
            unit_code = raw_unit if raw_unit in valid_units else (valid_units[0] if len(valid_units) == 1 else None)

        input_payload = {"supplier": document["supplier_code"], "line_id": line["id"], "text": normalized, "ruleset": self.RULESET_VERSION}
        return {
            "tier": tier, "method": method, "source_text": source_text, "normalized_text": normalized,
            "input_hash": hashlib.sha256(canonical_json(input_payload).encode("utf-8")).hexdigest(),
            "proposed_product_code": selected["product_code"] if selected else None, "proposed_unit_code": unit_code,
            "confidence": candidates[0]["score"] if candidates else None, "candidate_set": candidates, "reason_codes": reasons,
            "provenance": {"tier": tier, "method": method, "master_only": True, "human_confirmation_required": tier not in {"EXACT_CODE","EXACT_BARCODE","ACTIVE_ALIAS"}},
            "evidence": {"line_evidence": line.get("evidence_json"), "supplier_code": document["supplier_code"]},
            "ocr_engine_versions": ocr_versions, "ruleset_version": self.RULESET_VERSION,
        }
