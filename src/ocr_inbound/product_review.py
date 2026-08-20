from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .db import canonical_json
from .errors import DomainError
from .text_normalize import normalize_product_text


class ProductReviewService:
    ACTIONS = {"CONFIRM", "CORRECT", "UNREADABLE", "NOT_IN_MASTER", "DEFER"}

    def __init__(self, app) -> None:
        self.app = app

    def _latest_decisions_by_line(self, document_id: str) -> dict:
        # list_product_review_decisions() is ordered by (created_at, id)
        # ascending, so iterating in order and overwriting by
        # document_line_id naturally leaves the LATEST decision per line --
        # this is what determines a line's current queue/exception state,
        # not "any decision ever made" (see §29 finding 2: an
        # UNREADABLE/NOT_IN_MASTER decision used to hide a line from the
        # main queue FOREVER with no way back, because "decided" used to
        # mean "has at least one non-DEFER decision in its history" instead
        # of "the most recent decision is a terminal one").
        latest: dict[str, dict] = {}
        for decision in self.app.repository.list_product_review_decisions(document_id):
            latest[decision["document_line_id"]] = decision
        return latest

    def _row(self, document: dict, line: dict, prediction: dict, *, previous_decision: dict | None = None) -> dict:
        candidates = json.loads(prediction["candidate_set_json"])
        expanded = []
        for candidate in candidates[:5]:
            product = self.app.cache.get_product(candidate["product_code"])
            if product:
                expanded.append({**candidate, "name_thai": product.get("name_thai"), "name_eng": product.get("name_eng"), "barcode": product.get("barcode"), "strength": product.get("strength"), "size": product.get("size"), "units": product.get("units", [])})
        row = {
            "document": {"id": document["id"], "supplier_code": document["supplier_code"]},
            "line": {"id": line["id"], "supplier_sku": line["supplier_sku"], "raw_ocr_text": line["raw_ocr_text"], "normalized_text": normalize_product_text(line["raw_ocr_text"]), "evidence": json.loads(line["evidence_json"])},
            "prediction": {"id": prediction["id"], "tier": prediction["tier"], "confidence": prediction["confidence"], "proposed_product_code": prediction["proposed_product_code"], "proposed_unit_code": prediction["proposed_unit_code"], "reasons": json.loads(prediction["reason_codes_json"]), "provenance": json.loads(prediction["provenance_json"]), "ocr_versions": json.loads(prediction["ocr_engine_versions_json"]), "ruleset_version": prediction["ruleset_version"]},
            "candidates": expanded,
        }
        if previous_decision is not None:
            row["previous_decision"] = {
                "id": previous_decision["id"], "action": previous_decision["action"], "reason": previous_decision["reason"],
                "actor_id": previous_decision["actor_id"], "created_at": previous_decision["created_at"],
            }
        return row

    def queue(self, document_id: str) -> list[dict]:
        document = self.app.repository.get_document(document_id)
        # §31: key predictions by their OWN id and dereference each line's
        # authoritative `current_prediction_id` pointer -- never "whichever
        # prediction row happens to be last for this line in list order".
        # layer_f_predictions is append-only; a line re-predicted more than
        # once (e.g. re-run) has multiple rows, and two of them can land in
        # the same millisecond, so "last in list order" is not a reliable
        # way to find the CURRENT one even with the rowid-ordering fix in
        # list_predictions() -- current_prediction_id is the one value that
        # is unambiguous by construction (see decide()'s identical fix).
        predictions_by_id = {row["id"]: row for row in self.app.repository.list_predictions(document_id)}
        latest = self._latest_decisions_by_line(document_id)
        result = []
        for line in self.app.repository.list_lines(document_id):
            decision = latest.get(line["id"])
            if decision is not None and decision["action"] != "DEFER":
                # A terminal decision (CONFIRM/CORRECT/UNREADABLE/NOT_IN_MASTER)
                # already stands for this line -- CONFIRM/CORRECT already
                # moved it into the authoritative current-state projection
                # (see commit_product_review); UNREADABLE/NOT_IN_MASTER are
                # surfaced separately via exceptions(), never silently
                # dropped with no way back.
                continue
            prediction = predictions_by_id.get(line["current_prediction_id"])
            if prediction is None:
                raise DomainError("PREDICTION_NOT_PERSISTED", "Prediction must persist before review display")
            result.append(self._row(document, line, prediction))
        return result

    def exceptions(self, document_id: str) -> list[dict]:
        """Lines whose MOST RECENT decision is a terminal exception
        (UNREADABLE/NOT_IN_MASTER) -- these never update the authoritative
        current-line state or review_events (see commit_product_review),
        so they are invisible everywhere else. This is their one required
        home: every entry carries the original reason/action/actor/time
        (`previous_decision`) plus the full candidate list, so an admin can
        resolve the same line with a fresh CONFIRM/CORRECT/DEFER decision
        through the exact same decide() endpoint -- resolving one moves it
        back out of this list on the next fetch (its latest decision is no
        longer terminal-and-current)."""
        document = self.app.repository.get_document(document_id)
        # §31: same current_prediction_id dereference as queue() above.
        predictions_by_id = {row["id"]: row for row in self.app.repository.list_predictions(document_id)}
        latest = self._latest_decisions_by_line(document_id)
        lines_by_id = {line["id"]: line for line in self.app.repository.list_lines(document_id)}
        result = []
        for line_id, decision in latest.items():
            if decision["action"] not in {"UNREADABLE", "NOT_IN_MASTER"}:
                continue
            line = lines_by_id.get(line_id)
            if line is None:
                continue
            prediction = predictions_by_id.get(line["current_prediction_id"])
            if prediction is None:
                continue
            result.append(self._row(document, line, prediction, previous_decision=decision))
        return result

    def search_master(self, query: str) -> list[dict]:
        needle = normalize_product_text(query)
        if len(needle) < 2:
            return []
        matches = []
        for product in self.app.cache.list_products():
            haystack = normalize_product_text(" ".join(filter(None, [product.get("product_code"), product.get("barcode"), product.get("name_thai"), product.get("name_eng")])))
            if needle in haystack:
                matches.append(product["product_code"])
                if len(matches) >= 20:
                    break
        # §31 visual re-verification caught this: cache.list_products() does
        # NOT join product_units (only get_product() does), so units was
        # always [] here -- a CORRECT via master search could never show
        # the multi-unit picker and would always fail server-side with
        # UNIT_REQUIRED for a multi-unit product, with no way for the admin
        # to see why. Re-fetch each match through get_product() so units is
        # real.
        expanded = []
        for code in matches:
            full = self.app.cache.get_product(code)
            if full:
                expanded.append({"product_code": full["product_code"], "name_thai": full.get("name_thai"), "name_eng": full.get("name_eng"), "barcode": full.get("barcode"), "strength": full.get("strength"), "size": full.get("size"), "units": full.get("units", [])})
        return expanded

    def decide(self, payload: dict, actor) -> dict:
        action = payload.get("action")
        if action not in self.ACTIONS:
            raise DomainError("REVIEW_ACTION_INVALID", "Unsupported review action")
        document_id, line_id = payload["document_id"], payload["line_id"]
        line = next((row for row in self.app.repository.list_lines(document_id) if row["id"] == line_id), None)
        if line is None:
            raise DomainError("LINE_NOT_FOUND", "Review line not found")
        # Look up the CURRENT prediction via the line's authoritative
        # pointer (current_prediction_id), never "the first prediction row
        # that happens to match this line" -- layer_f_predictions is
        # append-only, so a line that has been predicted more than once
        # (e.g. re-run) has multiple rows, and picking by scan order could
        # silently decide against a stale, superseded prediction while
        # commit_product_review()'s own staleness check (which correctly
        # compares against current_prediction_id) would then reject it --
        # or worse, could pick a DIFFERENT stale one that happens to still
        # match by coincidence.
        prediction = next((row for row in self.app.repository.list_predictions(document_id) if row["id"] == line["current_prediction_id"]), None)
        if prediction is None:
            raise DomainError("PREDICTION_NOT_PERSISTED", "Prediction must persist before decision")
        product_code = payload.get("product_code")
        if action in {"CONFIRM", "CORRECT"} and self.app.cache.get_product(product_code or "") is None:
            raise DomainError("PRODUCT_OUTSIDE_MASTER", "Selected product must be active in Product Master")
        if action in {"CORRECT", "UNREADABLE", "NOT_IN_MASTER"} and not payload.get("reason"):
            raise DomainError("REVIEW_REASON_REQUIRED", "A correction/rejection reason is required")
        if action == "CORRECT" and not payload.get("error_category"):
            raise DomainError("ERROR_CATEGORY_REQUIRED", "Corrected product decisions require an error category")
        if action == "CONFIRM" and product_code != prediction["proposed_product_code"]:
            raise DomainError("CONFIRM_MUST_USE_PROPOSED", "Selecting another product requires CORRECT")
        evidence = line["evidence_json"]
        product = self.app.cache.get_product(product_code or "") if product_code else None
        # --- Unit contract (§29 finding 1) -----------------------------------
        # The UI never sends `unit_code` at all (the candidate buttons only
        # send product_code) -- the old fallback `product.units[0]` silently
        # substituted "whichever unit happens to sort first" for whatever
        # unit the PREDICTION actually proposed, so confirming a prediction
        # that said EACH could persist as BOX with no visible change to the
        # admin. CONFIRM must pin the prediction's own proposed unit (the
        # thing the admin actually saw and agreed to), never re-derive it;
        # CORRECT must make the admin choose explicitly whenever the
        # product has more than one active unit, and any explicitly-given
        # unit (from either action) must be validated against the
        # product's real active units -- a forged/inactive unit is rejected
        # exactly like a forged/inactive product code already is.
        valid_units = {item["unit_code"] for item in product.get("units", [])} if product else set()
        if action == "CONFIRM":
            proposed_unit = prediction["proposed_unit_code"]
            if not proposed_unit:
                raise DomainError("PROPOSED_UNIT_MISSING", "Prediction has no proposed unit; use CORRECT with an explicit unit")
            if proposed_unit not in valid_units:
                raise DomainError("PROPOSED_UNIT_INVALID", "Proposed unit is not an active unit for this product")
            unit_code = proposed_unit
        elif action == "CORRECT":
            explicit_unit = payload.get("unit_code")
            if len(valid_units) > 1 and not explicit_unit:
                raise DomainError("UNIT_REQUIRED", "This product has more than one active unit; select one explicitly")
            unit_code = explicit_unit or (next(iter(valid_units)) if len(valid_units) == 1 else None)
            if unit_code is not None and unit_code not in valid_units:
                raise DomainError("UNIT_INVALID", "Selected unit is not an active unit for this product")
        else:
            # UNREADABLE/NOT_IN_MASTER/DEFER never select a product, so no
            # unit applies -- any unit_code sent for these is ignored rather
            # than silently trusted, since there is no product to validate
            # it against.
            unit_code = None
        semantic = {key:payload.get(key) for key in ("document_id","line_id","action","product_code","unit_code","corrected_ocr_text","error_category","reason")}
        fingerprint = hashlib.sha256(canonical_json(semantic).encode()).hexdigest()
        document = self.app.repository.get_document(document_id)
        record = {"request_id": payload["request_id"], "request_fingerprint":fingerprint, "document_id": document_id, "document_line_id": line_id, "prediction_id": prediction["id"], "action": action, "selected_product_code": product_code, "selected_unit_code":unit_code, "supplier_code":document["supplier_code"], "normalized_alias":normalize_product_text(payload.get("corrected_ocr_text") or line["supplier_sku"] or line["raw_ocr_text"]), "ruleset_version":prediction["ruleset_version"], "corrected_ocr_text": payload.get("corrected_ocr_text"), "error_category": payload.get("error_category"), "reason": payload.get("reason"), "raw_ocr_sha256": hashlib.sha256(line["raw_ocr_text"].encode()).hexdigest(), "evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(), "duration_ms": int(payload.get("duration_ms", 0))}
        return self.app.repository.commit_product_review(record, actor)

    def source_path(self, document_id: str) -> Path:
        document = self.app.repository.get_document(document_id)
        return self.app.profile.assert_within_root(self.app.profile.root / document["source_artifact_path"], "Review image")
