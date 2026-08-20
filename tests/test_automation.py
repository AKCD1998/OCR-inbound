from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ocr_inbound.ada_automation import FakeAdaDriver, ReplayAdaDriver, SubprocessAdaDriver
from ocr_inbound.config import repository_root
from ocr_inbound.errors import DomainError

from .support import AppTestCase


class AutomationHappyPathTests(AppTestCase):
    def test_fake_full_draft_reconcile_human_token_simulated_save_receipt(self):
        document_id = self.prepare_ready()
        run = self.app.automation.start_draft(document_id, self.app.actor, FakeAdaDriver())
        self.assertEqual(run["state"], "AWAITING_HUMAN_SAVE")
        authorization = self.app.automation.authorize_save(run["id"], self.app.actor)
        receipt = self.app.automation.save_simulated(authorization, self.app.actor)
        self.assertTrue(receipt["simulated"])
        self.assertEqual(receipt["row_count"], 3)
        self.assertEqual(receipt["grand_total_minor"], 42500)
        self.assertTrue(receipt["reconciliation"]["passed"])
        self.assertEqual(self.app.repository.get_document(document_id)["status"], "COMPLETED")
        self.assertGreaterEqual(receipt["automation_event_count"], 10)
        self.assertTrue(self.app.profile.assert_within_root(self.app.profile.root / self.app.repository.get_automation_run(run["id"])["receipt_artifact_ref"], "receipt").exists())

    def test_replay_full_flow(self):
        document_id = self.prepare_ready("charoon")
        driver = ReplayAdaDriver(repository_root()/"tests/fixtures/ada_replay/happy.json")
        run = self.app.automation.start_draft(document_id, self.app.actor, driver)
        authorization = self.app.automation.authorize_save(run["id"], self.app.actor)
        receipt = self.app.automation.save_simulated(authorization, self.app.actor)
        self.assertTrue(receipt["simulated"])
        self.assertEqual(self.app.repository.get_automation_run(run["id"])["driver_kind"], "REPLAY")

    def test_token_is_one_use(self):
        document_id = self.prepare_ready()
        run = self.app.automation.start_draft(document_id,self.app.actor,FakeAdaDriver())
        authorization = self.app.automation.authorize_save(run["id"],self.app.actor)
        self.app.automation.save_simulated(authorization,self.app.actor)
        with self.assertRaises(DomainError) as caught:
            self.app.automation.save_simulated(authorization,self.app.actor)
        self.assertEqual(caught.exception.code,"SAVE_TOKEN_USED")

    def test_expired_token_and_document_edit_are_blocked(self):
        document_id=self.prepare_ready();run=self.app.automation.start_draft(document_id,self.app.actor,FakeAdaDriver());expired=self.app.automation.authorize_save(run["id"],self.app.actor,ttl_seconds=-1)
        with self.assertRaises(DomainError) as caught:self.app.automation.save_simulated(expired,self.app.actor)
        self.assertEqual(caught.exception.code,"SAVE_TOKEN_EXPIRED")
        self.app.automation._release(run["id"])

        self.tearDown();self.setUp()
        document_id=self.prepare_ready();run=self.app.automation.start_draft(document_id,self.app.actor,FakeAdaDriver());authorization=self.app.automation.authorize_save(run["id"],self.app.actor)
        line=self.app.repository.list_lines(document_id)[0];self.app.review_line_value(document_id,line["id"],"quantity","2",action="CONFIRM")
        with self.assertRaises(DomainError) as caught:self.app.automation.save_simulated(authorization,self.app.actor)
        self.assertEqual(caught.exception.code,"STALE_DOCUMENT_REVISION")


class AutomationFaultTests(AppTestCase):
    def _run_fault(self, fault: str, *, crash_after_row: int = 1):
        document_id=self.prepare_ready()
        run=self.app.automation.start_draft(document_id,self.app.actor,FakeAdaDriver(fault=fault,crash_after_row=crash_after_row))
        events=self.app.repository.list_automation_events(run["id"])
        return document_id,run,events

    def test_popup_focus_input_lookup_timeout_and_crash_stop_safely(self):
        expected={
            "unknown_popup":"ADA_UNKNOWN_POPUP","focus_loss":"ADA_FOCUS_LOST","physical_input":"ADA_PHYSICAL_INPUT",
            "product_lookup_failure":"ADA_PRODUCT_LOOKUP_FAILED","timeout_before_ack":"ADA_ACTION_TIMEOUT",
            "timeout_after_ack":"ADA_ACTION_TIMEOUT","host_crash":"ADA_WORKER_DISCONNECTED",
        }
        for fault,code in expected.items():
            with self.subTest(fault=fault):
                document_id,run,events=self._run_fault(fault,crash_after_row=2)
                self.assertIn(run["state"],{"PAUSED","FAILED"});self.assertEqual(run["failure_code"],code)
                stop=json.loads(events[-1]["observed_json"])["stop"]
                self.assertTrue(stop["input_stopped"]);self.assertFalse(stop["save_clicked"])
                self.tearDown();self.setUp()

    def test_row_count_total_and_unknown_readback_mismatch_pause(self):
        for fault in ("row_count_mismatch","total_mismatch","unreadable_total"):
            with self.subTest(fault=fault):
                _,run,events=self._run_fault(fault)
                self.assertEqual(run["state"],"PAUSED");self.assertEqual(run["failure_code"],"ADA_RECONCILIATION_MISMATCH")
                self.assertTrue(any(event["kind"]=="SAFE_PAUSE" for event in events))
                self.tearDown();self.setUp()

    def test_duplicate_appearing_before_save_consumes_token_and_pauses(self):
        document_id=self.prepare_ready();run=self.app.automation.start_draft(document_id,self.app.actor,FakeAdaDriver(fault="duplicate_before_save"));authorization=self.app.automation.authorize_save(run["id"],self.app.actor);result=self.app.automation.save_simulated(authorization,self.app.actor)
        self.assertEqual(result["state"],"PAUSED");self.assertEqual(result["failure_code"],"DUPLICATE_EXACT");self.assertIsNotNone(result["save_token_consumed_at"])

    def test_post_save_verification_failure_is_not_reported_complete(self):
        document_id=self.prepare_ready();run=self.app.automation.start_draft(document_id,self.app.actor,FakeAdaDriver(fault="post_save_verification_failure"));authorization=self.app.automation.authorize_save(run["id"],self.app.actor);result=self.app.automation.save_simulated(authorization,self.app.actor)
        self.assertEqual(result["state"],"FAILED");self.assertEqual(result["failure_code"],"ADA_POST_SAVE_VERIFY_FAILED")
        self.assertNotEqual(self.app.repository.get_document(document_id)["status"],"COMPLETED")

    def test_replay_fault_fixture_stops_safely(self):
        document_id=self.prepare_ready();driver=ReplayAdaDriver(repository_root()/"tests/fixtures/ada_replay/unknown_popup.json");run=self.app.automation.start_draft(document_id,self.app.actor,driver)
        self.assertEqual(run["state"],"PAUSED");self.assertEqual(run["failure_code"],"ADA_UNKNOWN_POPUP")


class WorkerProtocolTests(AppTestCase):
    def test_worker_crash_after_row_is_audited_safe_failure(self):
        document_id=self.prepare_ready()
        run=self.app.automation.start_draft(document_id,self.app.actor,SubprocessAdaDriver.fake(fault="host_crash",crash_after_row=2))
        self.assertEqual(run["state"],"FAILED")
        self.assertEqual(run["failure_code"],"ADA_WORKER_DISCONNECTED")
        stop=json.loads(self.app.repository.list_automation_events(run["id"])[-1]["observed_json"])["stop"]
        self.assertTrue(stop["input_stopped"]);self.assertFalse(stop["save_clicked"]);self.assertFalse(stop["worker_alive"])

    def test_jsonl_worker_heartbeat_and_safe_disconnect(self):
        payload='{"protocol_version":1,"kind":"HEARTBEAT","message_id":"m1"}\n{"protocol_version":1,"kind":"CANCEL","message_id":"m2"}\n'
        completed=subprocess.run([sys.executable,"-m","ocr_inbound.workers.ada_worker"],input=payload,capture_output=True,text=True,encoding="utf-8",timeout=10)
        messages=[json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(completed.returncode,0)
        self.assertEqual([message["kind"] for message in messages],["WORKER_READY","HEARTBEAT","SAFE_DISCONNECT"])
        self.assertFalse(messages[-1]["save_clicked"])
