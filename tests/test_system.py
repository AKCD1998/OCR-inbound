from __future__ import annotations

import base64
import json
import socket
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from ocr_inbound.ada_automation import FakeAdaDriver
from ocr_inbound.ada_read import SELECT_EXISTING_INVOICE, SELECT_PRODUCT, SELECT_SUPPLIER
from ocr_inbound.config import repository_root
from ocr_inbound.structured_log import StructuredLogger, redact
from ocr_inbound.web import make_handler

from .support import AppTestCase


class ReliabilityTests(AppTestCase):
    def test_startup_recovery_fails_ocr_closed_and_pauses_automation(self):
        document_id=self.prepare_ready()
        run=self.app.automation.start_draft(document_id,self.app.actor,FakeAdaDriver())
        self.app.automation._release(run["id"])
        fixture=repository_root()/"tests/fixtures/ocr_top3/berlin"
        processing=self.app.import_artifact(fixture/"invoice.svg",fixture/"artifact.json")["document"]["id"]
        self.app.repository.update_document_status(processing,"PROCESSING")
        recovered=type(self.app).bootstrap(data_root=self.root,reviewer_id="test-reviewer")
        self.assertEqual(recovered.repository.get_automation_run(run["id"])["state"],"PAUSED")
        self.assertEqual(recovered.repository.get_automation_run(run["id"])["failure_code"],"HOST_RESTARTED")
        self.assertEqual(recovered.repository.get_document(processing)["status"],"FAILED")
        self.assertIn(run["id"],recovered.startup_recovery["automation_runs_paused"])

    def test_backup_restore_drill_and_integrity(self):
        document_id=self.prepare_ready()
        backup=self.app.repository.backup("restore-drill")
        self.app.repository.update_document_status(document_id,"CANCELLED")
        self.assertEqual(self.app.repository.get_document(document_id)["status"],"CANCELLED")
        self.app.repository.restore(backup)
        self.assertEqual(self.app.repository.integrity_check(),"ok")
        self.assertEqual(self.app.repository.get_document(document_id)["status"],"READY_FOR_ADA")

    def test_structured_log_redacts_secrets_and_uses_allowlist(self):
        path=self.root/"logs/test.ndjson";logger=StructuredLogger(path)
        logger.emit(event="TEST",severity="INFO",correlation_id="c",detail={"password":"p@ss","text":"token=abc connection_string=server"},unexpected="drop")
        payload=json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["detail"]["password"],"[REDACTED]")
        self.assertNotIn("abc",json.dumps(payload));self.assertNotIn("unexpected",payload)

    def test_live_sql_catalog_is_select_only_and_live_flags_off(self):
        for query in (SELECT_PRODUCT,SELECT_SUPPLIER,SELECT_EXISTING_INVOICE):
            self.assertTrue(query.lstrip().upper().startswith("SELECT "))
            self.assertNotRegex(query.upper(),r"\b(INSERT|UPDATE|DELETE|MERGE|EXEC|CALL)\b")
        health=self.app.system_health()
        self.assertFalse(health["live_ada_enabled"]);self.assertFalse(health["live_adacc_enabled"]);self.assertFalse(health["production_save_enabled"])

    def test_system_health_contains_actor_cache_db_and_metrics(self):
        health=self.app.system_health()
        self.assertEqual(health["status"],"ok");self.assertEqual(health["db_integrity"],"ok");self.assertEqual(health["ada_cache"]["integrity"],"ok")
        self.assertEqual(health["actor_id"],"test-reviewer");self.assertIn("NOT PRODUCTION",health["authentication"])


class UiContractTests(AppTestCase):
    def test_ui_keyboard_thai_dpi_and_safety_contract(self):
        root=repository_root()/"src/ocr_inbound/web_static"
        html=(root/"index.html").read_text(encoding="utf-8");js=(root/"app.js").read_text(encoding="utf-8");css=(root/"app.css").read_text(encoding="utf-8")
        for text in ("หลักฐานต้นฉบับ","Exception Resolver","Human authorize save","Simulated save"):
            self.assertIn(text,html)
        for key in ("ArrowDown","ArrowUp","F8","ctrlKey","shiftKey","altKey"):
            self.assertIn(key,js)
        self.assertIn("performance.now",js)
        self.assertIn("min-resolution:1.25dppx",css);self.assertIn("min-resolution:1.5dppx",css)
        self.assertNotIn("UPDATE ",js.upper());self.assertNotIn("INSERT ",js.upper())

    def test_loopback_web_health_and_static_smoke(self):
        server=HTTPServer(("127.0.0.1",0),make_handler(self.app));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base+"/api/health",timeout=5) as response:health=json.load(response)
            with urllib.request.urlopen(base+"/",timeout=5) as response:html=response.read().decode("utf-8")
            self.assertEqual(health["environment"],"staging");self.assertIn("OCR Inbound Review",html)
            fixture=repository_root()/"tests/fixtures/ocr_top3/woothi"
            payload=json.dumps({"source_name":"invoice.svg","source_base64":base64.b64encode((fixture/"invoice.svg").read_bytes()).decode("ascii"),"artifact":json.loads((fixture/"artifact.json").read_text(encoding="utf-8"))}).encode("utf-8")
            request=urllib.request.Request(base+"/api/import",data=payload,headers={"Content-Type":"application/json"},method="POST")
            with urllib.request.urlopen(request,timeout=5) as response:imported=json.load(response)
            self.assertEqual(len(self.app.workspace(imported["document_id"])["predictions"]),3)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_spike_uses_120_row_shared_fixture(self):
        fixture=json.loads((repository_root()/"spikes/ui_comparison/shared_fixture.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(fixture["line_count"],100)
        self.assertTrue((repository_root()/"spikes/ui_comparison"/fixture["evidence_image"]).exists())


class TopThreeEndToEndTests(AppTestCase):
    def test_top3_import_review_match_correct_validate_ready_fake_receipts(self):
        results=[self.app.run_golden(name,driver_kind="FAKE") for name in ("woothi","charoon","berlin")]
        self.assertEqual([result["fixture"] for result in results],["woothi","charoon","berlin"])
        self.assertTrue(all(result["receipt"]["reconciliation"]["passed"] for result in results))
        self.assertTrue(all(result["receipt"]["simulated"] for result in results))
        metrics=self.app.repository.metrics();self.assertEqual(metrics["completed"],3);self.assertEqual(metrics["documents"],3)
        self.assertEqual(metrics["review_decisions"],24)

    def test_representative_fixture_through_replay(self):
        result=self.app.run_golden("berlin",driver_kind="REPLAY")
        self.assertEqual(result["driver"],"REPLAY");self.assertTrue(result["receipt"]["reconciliation"]["passed"])
