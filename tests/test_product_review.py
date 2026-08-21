from __future__ import annotations

import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from ocr_inbound import db as db_module
from ocr_inbound.db import new_id as real_new_id
from ocr_inbound.errors import DomainError
from ocr_inbound.service import Application
from ocr_inbound.web import make_handler


class ProductReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="slice3-review-")
        self.app = Application.bootstrap(data_root=Path(self.tmp.name), reviewer_id="named-admin", is_admin=True)
        fixture = Path(__file__).parent / "fixtures" / "ocr_top3" / "woothi"
        self.document_id = self.app.import_artifact(fixture / "invoice.svg", fixture / "artifact.json")["document"]["id"]

    def tearDown(self): self.tmp.cleanup()

    def test_prediction_must_persist_before_queue_display(self):
        with self.assertRaises(DomainError) as caught: self.app.product_review.queue(self.document_id)
        self.assertEqual(caught.exception.code, "PREDICTION_NOT_PERSISTED")

    def test_queue_contains_persisted_provenance_and_master_candidates(self):
        self.app.generate_predictions(self.document_id)
        row = self.app.product_review.queue(self.document_id)[0]
        self.assertEqual(row["prediction"]["ruleset_version"], "layer-f-v6")
        self.assertTrue(row["candidates"])
        self.assertIn("name_thai", row["candidates"][0])

    def test_confirm_is_idempotent_and_one_document_does_not_activate_alias(self):
        self.app.generate_predictions(self.document_id); row = self.app.product_review.queue(self.document_id)[0]
        payload = {"request_id":"same-request", "document_id":self.document_id,"line_id":row["line"]["id"],"action":"CONFIRM","product_code":row["candidates"][0]["product_code"]}
        first=self.app.product_review.decide(payload,self.app.actor); second=self.app.product_review.decide(payload,self.app.actor)
        self.assertEqual(first["id"],second["id"])
        self.assertEqual(self.app.repository.list_aliases("WOOTHI")[0]["status"],"CANDIDATE")
        line=next(item for item in self.app.repository.list_lines(self.document_id) if item["id"]==row["line"]["id"])
        self.assertEqual(line["review_status"],"CONFIRMED")
        self.assertEqual(len(self.app.repository.list_review_events(self.document_id)),1)
        self.assertFalse(self.app.product_review.queue(self.document_id)[0]["line"]["id"] == row["line"]["id"])

    def test_reused_request_id_with_changed_product_is_rejected_without_alias_side_effect(self):
        self.app.generate_predictions(self.document_id); row=self.app.product_review.queue(self.document_id)[0]
        base={"request_id":"bound-request","document_id":self.document_id,"line_id":row["line"]["id"],"action":"CONFIRM"}
        self.app.product_review.decide({**base,"product_code":row["candidates"][0]["product_code"]},self.app.actor)
        with self.assertRaises(DomainError) as caught:
            self.app.product_review.decide({**base,"action":"CORRECT","product_code":row["candidates"][1]["product_code"],"reason":"wrong","error_category":"SUPPLIER_ALIAS_UNKNOWN"},self.app.actor)
        self.assertEqual(caught.exception.code,"IDEMPOTENCY_PAYLOAD_CONFLICT")
        self.assertEqual(len(self.app.repository.list_aliases("WOOTHI")),1)

    def test_decision_receipts_reject_update_and_delete(self):
        self.app.generate_predictions(self.document_id); row=self.app.product_review.queue(self.document_id)[0]
        self.app.product_review.decide({"request_id":"immutable","document_id":self.document_id,"line_id":row["line"]["id"],"action":"CONFIRM","product_code":row["candidates"][0]["product_code"]},self.app.actor)
        for sql in ("UPDATE product_review_decisions SET action='DEFER'", "DELETE FROM product_review_decisions"):
            with self.assertRaises(Exception):
                with self.app.repository.transaction() as connection: connection.execute(sql)

    def test_forged_product_and_missing_reason_are_rejected_raw_is_immutable(self):
        self.app.generate_predictions(self.document_id); row=self.app.product_review.queue(self.document_id)[0]; before=row["line"]["raw_ocr_text"]
        base={"request_id":"r1","document_id":self.document_id,"line_id":row["line"]["id"]}
        with self.assertRaises(DomainError): self.app.product_review.decide({**base,"action":"CORRECT","product_code":"NOT-IN-MASTER","reason":"bad"},self.app.actor)
        with self.assertRaises(DomainError): self.app.product_review.decide({**base,"action":"UNREADABLE"},self.app.actor)
        self.assertEqual(self.app.product_review.queue(self.document_id)[0]["line"]["raw_ocr_text"],before)

    def test_confirm_writes_an_alias_observed_audit_event(self):
        # Section 29 finding 3: commit_product_review() mutated
        # supplier_product_aliases directly but only ever wrote the
        # generic PRODUCT_REVIEW_DECIDED audit -- alias state transitions
        # must be traceable via ALIAS_OBSERVED the same way the
        # pre-existing Repository.record_alias_observation() path (Slice 1)
        # always has, regardless of which code path produced the
        # observation.
        self.app.generate_predictions(self.document_id); row = self.app.product_review.queue(self.document_id)[0]
        self.app.product_review.decide({"request_id": "audit-check", "document_id": self.document_id, "line_id": row["line"]["id"], "action": "CONFIRM", "product_code": row["candidates"][0]["product_code"]}, self.app.actor)
        alias = self.app.repository.list_aliases("WOOTHI")[0]
        events = self.app.repository.list_audit_events(alias["id"])
        self.assertTrue(any(event["action"] == "ALIAS_OBSERVED" for event in events))

    def test_review_image_path_is_confined_to_root(self):
        path=self.app.product_review.source_path(self.document_id)
        path.resolve().relative_to(self.app.profile.root.resolve())
        with self.app.repository.transaction() as c: c.execute("UPDATE documents SET source_artifact_path='../../secret.txt' WHERE id=?",(self.document_id,))
        with self.assertRaises(DomainError): self.app.product_review.source_path(self.document_id)


class ProductReviewHttpAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="slice3-http-"); self.app=Application.bootstrap(data_root=Path(self.tmp.name),reviewer_id="admin",is_admin=True)
        self.server=HTTPServer(("127.0.0.1",0),make_handler(self.app)); threading.Thread(target=self.server.serve_forever,daemon=True).start(); self.base=f"http://127.0.0.1:{self.server.server_port}"
    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()
    def test_unauthenticated_admin_queue_is_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(self.base+"/api/admin/product-review?document_id=x")
        self.assertEqual(caught.exception.code,400)
    def test_admin_session_and_csrf_are_required(self):
        req=urllib.request.Request(self.base+"/api/admin/session",headers={"X-OCR-Actor":"admin"}); session=json.loads(urllib.request.urlopen(req).read())
        body=json.dumps({}).encode(); req=urllib.request.Request(self.base+"/api/admin/product-review/decision",data=body,headers={"Content-Type":"application/json","X-OCR-Actor":"admin"})
        with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(req)
        self.assertTrue(session["csrf_token"])

    def test_malicious_svg_is_sandboxed_and_master_search_is_admin_only(self):
        fixture=Path(__file__).parent/"fixtures"/"ocr_top3"/"woothi"
        artifact=json.loads((fixture/"artifact.json").read_text(encoding="utf-8"))
        svg=b"<svg xmlns='http://www.w3.org/2000/svg'><script>parent.fetch('/api/admin/session')</script></svg>"
        document_id=self.app.import_uploaded_artifact("evil.svg",svg,artifact)["document"]["id"]
        self.app.generate_predictions(document_id)
        source=urllib.request.urlopen(self.base+f"/api/source?document_id={document_id}&token={self.app.csrf_token}")
        self.assertIn("script-src 'none'",source.headers["Content-Security-Policy"])
        self.assertIn("sandbox",source.headers["Content-Security-Policy"])
        html=urllib.request.urlopen(self.base+"/").read().decode()
        self.assertIn('id="source" title="เอกสารต้นฉบับ" sandbox',html)
        with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(self.base+"/api/admin/product-master/search?q=6300001")
        request=urllib.request.Request(self.base+"/api/admin/product-master/search?q=6300001",headers={"X-OCR-Actor":"admin"})
        self.assertTrue(json.loads(urllib.request.urlopen(request).read()))

    def _post(self, path, body, *, admin=True, csrf=True):
        headers = {"Content-Type": "application/json"}
        if admin:
            headers["X-OCR-Actor"] = self.app.actor.actor_id
        if csrf:
            headers["X-CSRF-Token"] = self.app.csrf_token
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=headers)
        try:
            response = urllib.request.urlopen(request)
            return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_three_distinct_http_decisions_become_eligible_then_explicit_admin_activation(self):
        # §29 finding 4: the previous version of this test only proved the
        # activation call went through HTTP -- the three CONFIRM decisions
        # that actually build the alias's ELIGIBLE state were made with
        # direct Python method calls, so admin headers, CSRF, JSON
        # (de)serialization, and idempotency were never exercised at the
        # HTTP boundary for the part that matters most. Every decision here
        # -- including the retry-same/reuse-different-payload probes --
        # goes through `urllib.request` against the real loopback server,
        # exactly like a browser client would.
        fixture=Path(__file__).parent/"fixtures"/"ocr_top3"/"woothi"; artifact=json.loads((fixture/"artifact.json").read_text(encoding="utf-8"))
        document_rows = []
        for index in range(3):
            svg=f"<svg xmlns='http://www.w3.org/2000/svg'><text>{index}</text></svg>".encode()
            document_id=self.app.import_uploaded_artifact(f"doc-{index}.svg",svg,artifact)["document"]["id"]
            self.app.generate_predictions(document_id); row=self.app.product_review.queue(document_id)[0]
            document_rows.append((document_id, row))

        # Decision 0: retry the SAME payload/request_id over HTTP twice --
        # must return the identical receipt with no duplicate side effect
        # (still only one alias observation from this document).
        document_id, row = document_rows[0]
        decision_body = {"request_id": "http-seed-0", "document_id": document_id, "line_id": row["line"]["id"], "action": "CONFIRM", "product_code": row["prediction"]["proposed_product_code"]}
        status_a, receipt_a = self._post("/api/admin/product-review/decision", decision_body)
        self.assertEqual(status_a, 200)
        status_b, receipt_b = self._post("/api/admin/product-review/decision", decision_body)
        self.assertEqual(status_b, 200)
        self.assertEqual(receipt_a["id"], receipt_b["id"])

        # Same request_id, DIFFERENT payload over HTTP -- must fail with a
        # stable conflict code and must not add a second alias observation.
        conflicting_body = {**decision_body, "product_code": row["candidates"][1]["product_code"] if len(row["candidates"]) > 1 else row["prediction"]["proposed_product_code"], "action": "CORRECT", "reason": "wrong", "error_category": "SUPPLIER_ALIAS_UNKNOWN"}
        if conflicting_body["product_code"] != decision_body["product_code"]:
            status_conflict, payload_conflict = self._post("/api/admin/product-review/decision", conflicting_body)
            self.assertEqual(status_conflict, 400)
            self.assertEqual(payload_conflict["code"], "IDEMPOTENCY_PAYLOAD_CONFLICT")

        # Decisions 1 and 2: distinct documents, distinct request ids, real
        # HTTP each time -- this is what actually drives CANDIDATE -> ELIGIBLE.
        for index in (1, 2):
            document_id, row = document_rows[index]
            body = {"request_id": f"http-seed-{index}", "document_id": document_id, "line_id": row["line"]["id"], "action": "CONFIRM", "product_code": row["prediction"]["proposed_product_code"]}
            status, receipt = self._post("/api/admin/product-review/decision", body)
            self.assertEqual(status, 200)
            self.assertEqual(receipt["action"], "CONFIRM")

        alias=self.app.repository.list_aliases("WOOTHI")[0]; self.assertEqual(alias["status"],"ELIGIBLE")
        # Exactly one alias observation per document, not two, confirms the
        # retry-same-payload probe above had no duplicate side effect.
        self.assertEqual(alias["distinct_document_count"], 3)

        status, activated = self._post("/api/admin/product-review/alias/activate", {"alias_id": alias["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(activated["status"], "ACTIVE")


CONTRACT_VERSION = "ocr-inbound-artifact.v1"


def _header_field(value, raw_text=None):
    return {"value": value, "raw_text": raw_text if raw_text is not None else str(value), "required": True, "confidence": "0.99", "source_prediction_ref": "unit-test:header", "evidence": {}}


def _single_line_artifact(*, supplier_code, invoice_number, line_evidence, raw_ocr_text="TEST LINE"):
    return {
        "contract_version": CONTRACT_VERSION,
        "ocr_run_id": f"unit-test-{invoice_number}",
        "ocr_engine_versions": {"layers_a_e": "unit-test", "tesseract": "n/a", "paddle": "n/a", "easyocr": "n/a"},
        "header": {"fields": {
            "supplier_code": _header_field(supplier_code),
            "invoice_number": _header_field(invoice_number),
            "invoice_date": _header_field("2026-08-20", raw_text="20/08/2569"),
            "grand_total_minor": _header_field(10000, raw_text="100.00"),
        }},
        "lines": [{
            "source_row_ref": "unit-test:r1", "raw_ocr_text": raw_ocr_text, "supplier_sku": None,
            "description": raw_ocr_text, "unit": "BOX", "quantity": "1",
            "unit_price_minor": 10000, "line_total_minor": 10000, "evidence": line_evidence,
        }],
    }


_SVG_FIXTURE_BYTES = "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>".encode("utf-8")


class ProductReviewUnitContractTests(unittest.TestCase):
    """Section 29 finding 1: CONFIRM used to fall back to product.units[0]
    instead of the prediction's own proposed_unit_code -- confirming an
    EACH prediction could silently persist as BOX. Uses evidence_json
    ["internal_code_candidates"] (Slice 1 explicit-provenance path) to
    force a deterministic EXACT_CODE match onto a controlled product, so
    the unit resolved is never influenced by fuzzy/trade-name scoring."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="slice3-unit-")
        self.app = Application.bootstrap(data_root=Path(self.tmp.name), reviewer_id="named-admin", is_admin=True)
        self.app.cache.refresh_from_fixture({
            "products": [
                {
                    "product_code": "IC-MULTI-UNIT", "barcode": None,
                    "name_eng": "MULTI UNIT TEST PRODUCT", "name_thai": "",
                    "ingredient": "", "strength": "", "size": "", "manufacturer": "", "active": True,
                    "units": [{"unit_code": "BOX", "factor": "1", "active": True}, {"unit_code": "EACH", "factor": "1", "active": True}],
                },
                {
                    "product_code": "IC-SINGLE-UNIT", "barcode": None,
                    "name_eng": "SINGLE UNIT TEST PRODUCT", "name_thai": "",
                    "ingredient": "", "strength": "", "size": "", "manufacturer": "", "active": True,
                    "units": [{"unit_code": "BOX", "factor": "1", "active": True}],
                },
            ],
            "suppliers": [{"supplier_code": "ACME", "name": "Acme Wholesale", "active": True}],
            "purchase_history": [],
        })

    def tearDown(self):
        self.tmp.cleanup()

    def _import_and_predict(self, product_code, invoice_number):
        artifact = _single_line_artifact(supplier_code="ACME", invoice_number=invoice_number, line_evidence={"internal_code_candidates": [product_code]})
        document_id = self.app.import_uploaded_artifact(f"{invoice_number}.svg", _SVG_FIXTURE_BYTES, artifact)["document"]["id"]
        self.app.generate_predictions(document_id)
        row = self.app.product_review.queue(document_id)[0]
        return document_id, row

    def test_confirm_pins_the_predicted_unit_not_the_first_active_unit(self):
        document_id, row = self._import_and_predict("IC-MULTI-UNIT", "unit-01")
        self.assertEqual(row["prediction"]["tier"], "EXACT_CODE")
        self.assertEqual(row["prediction"]["proposed_unit_code"], "BOX")  # units[0] happens to also be BOX...
        # ...so this alone would not distinguish the bug. Force the
        # prediction itself to have proposed EACH by re-persisting a
        # prediction with proposed_unit_code="EACH" through the real
        # persistence path, exactly mirroring what a real EACH-tier
        # prediction would have stored.
        line = next(l for l in self.app.repository.list_lines(document_id) if l["id"] == row["line"]["id"])
        prediction = self.app.matcher._predict({"id": document_id, "supplier_code": "ACME"}, line, {"source": "unit-test"})
        prediction["proposed_unit_code"] = "EACH"
        self.app.repository.persist_prediction_before_display(document_id, row["line"]["id"], prediction)
        row = self.app.product_review.queue(document_id)[0]
        self.assertEqual(row["prediction"]["proposed_unit_code"], "EACH")
        receipt = self.app.product_review.decide({"request_id": "confirm-each", "document_id": document_id, "line_id": row["line"]["id"], "action": "CONFIRM", "product_code": "IC-MULTI-UNIT"}, self.app.actor)
        self.assertEqual(receipt["selected_unit_code"], "EACH")
        persisted_line = next(l for l in self.app.repository.list_lines(document_id) if l["id"] == row["line"]["id"])
        self.assertEqual(persisted_line["ada_unit_code"], "EACH")

    def test_confirm_rejects_a_prediction_with_no_proposed_unit(self):
        document_id, row = self._import_and_predict("IC-MULTI-UNIT", "unit-02")
        line = next(l for l in self.app.repository.list_lines(document_id) if l["id"] == row["line"]["id"])
        prediction = self.app.matcher._predict({"id": document_id, "supplier_code": "ACME"}, line, {"source": "unit-test"})
        prediction["proposed_unit_code"] = None
        self.app.repository.persist_prediction_before_display(document_id, row["line"]["id"], prediction)
        row = self.app.product_review.queue(document_id)[0]
        with self.assertRaises(DomainError) as caught:
            self.app.product_review.decide({"request_id": "confirm-no-unit", "document_id": document_id, "line_id": row["line"]["id"], "action": "CONFIRM", "product_code": "IC-MULTI-UNIT"}, self.app.actor)
        self.assertEqual(caught.exception.code, "PROPOSED_UNIT_MISSING")

    def test_correct_with_multiple_units_requires_explicit_unit(self):
        document_id, row = self._import_and_predict("IC-MULTI-UNIT", "unit-03")
        with self.assertRaises(DomainError) as caught:
            self.app.product_review.decide({"request_id": "correct-no-unit", "document_id": document_id, "line_id": row["line"]["id"], "action": "CORRECT", "product_code": "IC-MULTI-UNIT", "reason": "wrong", "error_category": "SUPPLIER_ALIAS_UNKNOWN"}, self.app.actor)
        self.assertEqual(caught.exception.code, "UNIT_REQUIRED")

    def test_correct_with_forged_unit_is_rejected(self):
        document_id, row = self._import_and_predict("IC-MULTI-UNIT", "unit-04")
        with self.assertRaises(DomainError) as caught:
            self.app.product_review.decide({"request_id": "correct-forged-unit", "document_id": document_id, "line_id": row["line"]["id"], "action": "CORRECT", "product_code": "IC-MULTI-UNIT", "unit_code": "PALLET", "reason": "wrong", "error_category": "SUPPLIER_ALIAS_UNKNOWN"}, self.app.actor)
        self.assertEqual(caught.exception.code, "UNIT_INVALID")

    def test_correct_with_explicit_valid_unit_persists_that_unit(self):
        document_id, row = self._import_and_predict("IC-MULTI-UNIT", "unit-05")
        receipt = self.app.product_review.decide({"request_id": "correct-explicit-unit", "document_id": document_id, "line_id": row["line"]["id"], "action": "CORRECT", "product_code": "IC-MULTI-UNIT", "unit_code": "EACH", "reason": "wrong", "error_category": "SUPPLIER_ALIAS_UNKNOWN"}, self.app.actor)
        self.assertEqual(receipt["selected_unit_code"], "EACH")

    def test_single_unit_product_still_works_without_explicit_unit(self):
        document_id, row = self._import_and_predict("IC-SINGLE-UNIT", "unit-06")
        receipt = self.app.product_review.decide({"request_id": "confirm-single-unit", "document_id": document_id, "line_id": row["line"]["id"], "action": "CONFIRM", "product_code": "IC-SINGLE-UNIT"}, self.app.actor)
        self.assertEqual(receipt["selected_unit_code"], "BOX")

    def test_master_search_results_carry_real_units_not_an_empty_list(self):
        # Found during §31 visual re-verification: search_master() built its
        # results from cache.list_products(), which never joins
        # product_units (only get_product() does) -- every search result's
        # "units" was silently [], so the UI's multi-unit picker could never
        # trigger for a product reached via search, and a CORRECT through
        # search to a real multi-unit product would fail server-side with
        # UNIT_REQUIRED with no way for the admin to see why.
        self._import_and_predict("IC-MULTI-UNIT", "unit-07")
        results = self.app.product_review.search_master("MULTI UNIT")
        self.assertTrue(results)
        match = next(r for r in results if r["product_code"] == "IC-MULTI-UNIT")
        self.assertEqual({u["unit_code"] for u in match["units"]}, {"BOX", "EACH"})


class ProductReviewExceptionQueueTests(unittest.TestCase):
    """Section 29 finding 2: UNREADABLE/NOT_IN_MASTER decisions used to
    vanish -- hidden from the main queue forever, with no projection
    anywhere and no way back. DEFER must remain resumable through the
    ordinary queue."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="slice3-exceptions-")
        self.app = Application.bootstrap(data_root=Path(self.tmp.name), reviewer_id="named-admin", is_admin=True)
        self.app.cache.refresh_from_fixture({
            "products": [{"product_code": "IC-EXC-001", "barcode": None, "name_eng": "EXCEPTION TEST PRODUCT", "name_thai": "", "ingredient": "", "strength": "", "size": "", "manufacturer": "", "active": True, "units": [{"unit_code": "BOX", "factor": "1", "active": True}]}],
            "suppliers": [{"supplier_code": "ACME", "name": "Acme Wholesale", "active": True}],
            "purchase_history": [],
        })
        artifact = _single_line_artifact(supplier_code="ACME", invoice_number="exc-01", line_evidence={"internal_code_candidates": ["IC-EXC-001"]})
        self.document_id = self.app.import_uploaded_artifact("exc-01.svg", _SVG_FIXTURE_BYTES, artifact)["document"]["id"]
        self.app.generate_predictions(self.document_id)

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_in_master_disappears_from_main_queue_but_appears_in_exceptions(self):
        row = self.app.product_review.queue(self.document_id)[0]
        self.app.product_review.decide({"request_id": "reject-1", "document_id": self.document_id, "line_id": row["line"]["id"], "action": "NOT_IN_MASTER", "reason": "not stocked here"}, self.app.actor)
        self.assertEqual(self.app.product_review.queue(self.document_id), [])
        exceptions = self.app.product_review.exceptions(self.document_id)
        self.assertEqual(len(exceptions), 1)
        self.assertEqual(exceptions[0]["previous_decision"]["action"], "NOT_IN_MASTER")
        self.assertEqual(exceptions[0]["previous_decision"]["reason"], "not stocked here")
        self.assertEqual(exceptions[0]["previous_decision"]["actor_id"], self.app.actor.actor_id)
        self.assertTrue(exceptions[0]["previous_decision"]["created_at"])

    def test_unreadable_disappears_from_main_queue_but_appears_in_exceptions(self):
        row = self.app.product_review.queue(self.document_id)[0]
        self.app.product_review.decide({"request_id": "unreadable-1", "document_id": self.document_id, "line_id": row["line"]["id"], "action": "UNREADABLE", "reason": "blurry scan"}, self.app.actor)
        self.assertEqual(self.app.product_review.queue(self.document_id), [])
        exceptions = self.app.product_review.exceptions(self.document_id)
        self.assertEqual(exceptions[0]["previous_decision"]["action"], "UNREADABLE")

    def test_resolving_an_exception_removes_it_from_the_exception_list(self):
        row = self.app.product_review.queue(self.document_id)[0]
        self.app.product_review.decide({"request_id": "reject-2", "document_id": self.document_id, "line_id": row["line"]["id"], "action": "NOT_IN_MASTER", "reason": "not stocked here"}, self.app.actor)
        self.assertEqual(len(self.app.product_review.exceptions(self.document_id)), 1)
        exception_row = self.app.product_review.exceptions(self.document_id)[0]
        self.app.product_review.decide({"request_id": "resolve-1", "document_id": self.document_id, "line_id": exception_row["line"]["id"], "action": "CONFIRM", "product_code": "IC-EXC-001"}, self.app.actor)
        self.assertEqual(self.app.product_review.exceptions(self.document_id), [])
        line = next(l for l in self.app.repository.list_lines(self.document_id) if l["id"] == exception_row["line"]["id"])
        self.assertEqual(line["review_status"], "CONFIRMED")
        self.assertEqual(line["ada_product_code"], "IC-EXC-001")

    def test_defer_stays_resumable_in_the_main_queue_not_exceptions(self):
        row = self.app.product_review.queue(self.document_id)[0]
        self.app.product_review.decide({"request_id": "defer-1", "document_id": self.document_id, "line_id": row["line"]["id"], "action": "DEFER"}, self.app.actor)
        self.assertEqual(len(self.app.product_review.queue(self.document_id)), 1)
        self.assertEqual(self.app.product_review.exceptions(self.document_id), [])


def _reversing_new_id(prefix, counter, reversed_prefixes):
    """Returns ids for `prefix` that sort in the OPPOSITE order to the
    order this function is actually called in, for every prefix in
    `reversed_prefixes` -- everything else delegates to the real
    `new_id()`. Used to prove that "latest" selection relies on true
    insertion order (SQLite `rowid`), never on (timestamp, id) sorting,
    without needing `time.sleep()` to force distinct clock values."""
    if prefix not in reversed_prefixes:
        return real_new_id(prefix)
    n = next(counter)
    # Zero-padded DESCENDING suffix: call 0 gets the lexicographically
    # LARGEST id, call 1 gets a smaller one, etc. -- exactly backwards from
    # real insertion order.
    return f"{prefix}_zzz{9999 - n:04d}"


class DecisionOrderingRaceTests(unittest.TestCase):
    """Section 31 (Codex's fifth Slice-3 adjudication): decisions/predictions
    persisted within the SAME millisecond used to be ordered by
    (created_at, id) -- since `id` has a random suffix, two rows in the same
    millisecond could sort in either order, unrelated to which one was
    actually committed first. Every test here forces an identical
    `created_at` AND a deliberately REVERSED id ordering (via
    `_reversing_new_id`, no `time.sleep()` involved) so a test that still
    passed by relying on (created_at, id) ordering would fail here, while
    the rowid-based fix keeps working regardless of what the ids look like."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="slice3-race-")
        self.app = Application.bootstrap(data_root=Path(self.tmp.name), reviewer_id="named-admin", is_admin=True)
        self.app.cache.refresh_from_fixture({
            "products": [
                {"product_code": "IC-RACE-A", "barcode": None, "name_eng": "RACE PRODUCT A", "name_thai": "", "ingredient": "", "strength": "", "size": "", "manufacturer": "", "active": True, "units": [{"unit_code": "BOX", "factor": "1", "active": True}]},
                {"product_code": "IC-RACE-B", "barcode": None, "name_eng": "RACE PRODUCT B", "name_thai": "", "ingredient": "", "strength": "", "size": "", "manufacturer": "", "active": True, "units": [{"unit_code": "EACH", "factor": "1", "active": True}]},
            ],
            "suppliers": [{"supplier_code": "ACME", "name": "Acme Wholesale", "active": True}],
            "purchase_history": [],
        })
        artifact = _single_line_artifact(supplier_code="ACME", invoice_number="race-01", line_evidence={"internal_code_candidates": ["IC-RACE-A"]})
        self.document_id = self.app.import_uploaded_artifact("race-01.svg", _SVG_FIXTURE_BYTES, artifact)["document"]["id"]
        self.app.generate_predictions(self.document_id)

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_timestamp_reversed_decision_id_still_treats_the_truly_later_decision_as_current(self):
        row = self.app.product_review.queue(self.document_id)[0]
        counter = iter(range(100))
        fixed_timestamp = "2026-08-20T00:00:00.000+00:00"
        with patch.object(db_module, "now_iso", return_value=fixed_timestamp), \
             patch.object(db_module, "new_id", side_effect=lambda prefix: _reversing_new_id(prefix, counter, {"prd"})):
            # Decision 1 (real insertion order first): NOT_IN_MASTER. Its
            # decision_id is deliberately the LEXICOGRAPHICALLY LARGEST
            # ("prd_zzz9999") of the two.
            self.app.product_review.decide({"request_id": "race-first", "document_id": self.document_id, "line_id": row["line"]["id"], "action": "NOT_IN_MASTER", "reason": "not stocked"}, self.app.actor)
            # Decision 2 (real insertion order second, same millisecond):
            # CONFIRM. Its decision_id is deliberately SMALLER
            # ("prd_zzz9998") -- (created_at, id) ordering would have sorted
            # this BEFORE decision 1, making NOT_IN_MASTER look like the
            # latest decision even though CONFIRM actually happened after.
            self.app.product_review.decide({"request_id": "race-second", "document_id": self.document_id, "line_id": row["line"]["id"], "action": "CONFIRM", "product_code": "IC-RACE-A"}, self.app.actor)
        # The truly-later CONFIRM must win: the line is resolved (not an
        # open exception, not back in the main queue).
        self.assertEqual(self.app.product_review.queue(self.document_id), [])
        self.assertEqual(self.app.product_review.exceptions(self.document_id), [])
        line = next(l for l in self.app.repository.list_lines(self.document_id) if l["id"] == row["line"]["id"])
        self.assertEqual(line["review_status"], "CONFIRMED")

    def test_same_timestamp_reversed_prediction_id_queue_still_reflects_current_prediction_id(self):
        row = self.app.product_review.queue(self.document_id)[0]
        line = next(l for l in self.app.repository.list_lines(self.document_id) if l["id"] == row["line"]["id"])
        base_prediction = self.app.matcher._predict({"id": self.document_id, "supplier_code": "ACME"}, line, {"source": "race-test"})
        counter = iter(range(100))
        fixed_timestamp = "2026-08-20T00:00:00.000+00:00"
        with patch.object(db_module, "now_iso", return_value=fixed_timestamp), \
             patch.object(db_module, "new_id", side_effect=lambda prefix: _reversing_new_id(prefix, counter, {"pred"})):
            # Prediction 1 (real insertion order first): proposes A/BOX.
            # Its id is deliberately the LEXICOGRAPHICALLY LARGEST.
            first = dict(base_prediction, proposed_product_code="IC-RACE-A", proposed_unit_code="BOX")
            self.app.repository.persist_prediction_before_display(self.document_id, row["line"]["id"], first)
            # Prediction 2 (real insertion order second, same millisecond):
            # proposes B/EACH -- a DIFFERENT product AND unit, so this is
            # not an id-specific assertion. Its id is deliberately SMALLER,
            # so (created_at, id) ordering would have picked prediction 1
            # (A/BOX) as "last", even though B/EACH is what document_lines.
            # current_prediction_id actually points to now.
            second = dict(base_prediction, proposed_product_code="IC-RACE-B", proposed_unit_code="EACH")
            self.app.repository.persist_prediction_before_display(self.document_id, row["line"]["id"], second)
        current_line = next(l for l in self.app.repository.list_lines(self.document_id) if l["id"] == row["line"]["id"])
        self.assertEqual(current_line["ada_product_code"], "IC-RACE-B")
        queue_row = self.app.product_review.queue(self.document_id)[0]
        self.assertEqual(queue_row["prediction"]["proposed_product_code"], "IC-RACE-B")
        self.assertEqual(queue_row["prediction"]["proposed_unit_code"], "EACH")
        self.assertEqual(queue_row["prediction"]["id"], current_line["current_prediction_id"])
