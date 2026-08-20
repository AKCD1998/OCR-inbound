from __future__ import annotations

import ctypes
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .artifacts import FilesystemArtifactStore
from .config import AppProfile
from .db import Repository, canonical_json, new_id, now_iso
from .errors import DomainError
from .identity import Actor
from .validation import InvoiceValidationService, ReconciliationService


PROTOCOL_VERSION = 1


class AdaDriver(Protocol):
    kind: str
    def preflight(self, expected: dict) -> dict: ...
    def start_blank_receipt(self, header: dict) -> dict: ...
    def enter_line(self, line: dict, command_id: str) -> dict: ...
    def readback_draft(self) -> dict: ...
    def duplicate_before_save(self) -> bool: ...
    def save(self, authorization: dict) -> dict: ...
    def verify_saved(self) -> dict: ...
    def stop_safely(self) -> dict: ...


class AdaSafetyStop(DomainError):
    def __init__(self, code: str, message: str, *, state: str = "PAUSED", observed: dict | None = None) -> None:
        super().__init__(code, message, detail={"state": state, "observed": observed or {}})
        self.state = state
        self.observed = observed or {}


class FakeAdaDriver:
    kind = "FAKE"

    def __init__(self, *, fault: str | None = None, crash_after_row: int = 1) -> None:
        self.fault = fault
        self.crash_after_row = crash_after_row
        self.expected: dict = {}
        self.lines: list[dict] = []
        self.saved = False
        self.document_number: str | None = None

    def preflight(self, expected: dict) -> dict:
        self.expected = expected
        return {"passed": True, "target_company": expected["target_company"], "target_branch": expected["target_branch"], "supplier_code": expected["supplier_code"], "duplicate": False, "driver": self.kind}

    def start_blank_receipt(self, header: dict) -> dict:
        if self.fault == "unknown_popup":
            raise AdaSafetyStop("ADA_UNKNOWN_POPUP", "Unknown popup observed after header", observed={"popup": "SANITIZED_UNKNOWN"})
        return {"acknowledged": True, "supplier_code": header["supplier_code"], "invoice_number": header["invoice_number"]}

    def enter_line(self, line: dict, command_id: str) -> dict:
        next_row = len(self.lines) + 1
        if self.fault == "focus_loss" and next_row == 1:
            raise AdaSafetyStop("ADA_FOCUS_LOST", "Foreground window changed", observed={"foreground": "OTHER"})
        if self.fault == "physical_input" and next_row == 1:
            raise AdaSafetyStop("ADA_PHYSICAL_INPUT", "Physical keyboard/mouse input observed")
        if self.fault == "product_lookup_failure" and next_row == 1:
            raise AdaSafetyStop("ADA_PRODUCT_LOOKUP_FAILED", "Product lookup did not resolve")
        if self.fault == "timeout_before_ack" and next_row == 1:
            raise AdaSafetyStop("ADA_ACTION_TIMEOUT", "Timeout before acknowledgement", observed={"action_sent": False})
        if self.fault == "timeout_after_ack" and next_row == 1:
            raise AdaSafetyStop("ADA_ACTION_TIMEOUT", "Timeout after action before verification", observed={"action_sent": True, "acknowledged": "UNKNOWN"})
        self.lines.append(dict(line))
        if self.fault == "host_crash" and next_row == self.crash_after_row:
            raise AdaSafetyStop("ADA_WORKER_DISCONNECTED", f"Worker disconnected after row {next_row}", state="FAILED", observed={"last_verified_row": next_row})
        return {"acknowledged": True, "command_id": command_id, "line_sequence": line["sequence"], "product_code": line["product_code"], "quantity": line["quantity"]}

    def readback_draft(self) -> dict:
        row_count = len(self.lines)
        grand_total = sum(int(line["line_total_minor"]) for line in self.lines)
        if self.fault == "row_count_mismatch":
            row_count += 1
        if self.fault == "total_mismatch":
            grand_total += 1
        if self.fault == "unreadable_total":
            grand_total = "UNKNOWN"
        return {"target_company": self.expected["target_company"], "target_branch": self.expected["target_branch"], "supplier_code": self.expected["supplier_code"], "invoice_number": self.expected["invoice_number"], "row_count": row_count, "grand_total_minor": grand_total}

    def duplicate_before_save(self) -> bool:
        return self.fault == "duplicate_before_save"

    def save(self, authorization: dict) -> dict:
        self.saved = True
        self.document_number = f"SIM-{authorization['run_id'][-10:].upper()}"
        return {"saved": True, "document_number": self.document_number, "simulated": True}

    def verify_saved(self) -> dict:
        if self.fault == "post_save_verification_failure":
            raise AdaSafetyStop("ADA_POST_SAVE_VERIFY_FAILED", "Simulated save succeeded but post-save verification failed", state="FAILED", observed={"saved": True, "document_number": self.document_number})
        return {"verified": self.saved, "document_number": self.document_number, "simulated": True}

    def stop_safely(self) -> dict:
        return {"input_stopped": True, "save_clicked": False, "cancel_clicked": False, "last_verified_row": len(self.lines)}


class ReplayAdaDriver(FakeAdaDriver):
    kind = "REPLAY"

    def __init__(self, replay_fixture: Path) -> None:
        self._load(json.loads(replay_fixture.read_text(encoding="utf-8")))

    @classmethod
    def from_payload(cls, payload: dict) -> "ReplayAdaDriver":
        instance = cls.__new__(cls)
        instance._load(payload)
        return instance

    def _load(self, payload: dict) -> None:
        if payload.get("protocol_version") != PROTOCOL_VERSION or payload.get("sanitized") is not True:
            raise DomainError("ADA_REPLAY_INVALID", "Replay fixture must be sanitized protocol v1")
        super().__init__(fault=payload.get("fault"), crash_after_row=int(payload.get("crash_after_row", 1)))
        self.payload = payload


class SubprocessAdaDriver:
    """Host-side JSONL client. The worker owns driver state but never the DB."""

    def __init__(self, kind: str, *, fault: str | None = None, crash_after_row: int = 1, replay_payload: dict | None = None) -> None:
        if kind not in {"FAKE", "REPLAY"}:
            raise DomainError("DRIVER_UNSUPPORTED", "Worker driver must be Fake or Replay")
        self.kind = kind
        command = [sys.executable, "-m", "ocr_inbound.workers.ada_worker", "--driver", kind, "--crash-after-row", str(crash_after_row)]
        if fault:
            command.extend(("--fault", fault))
        if replay_payload is not None:
            encoded = base64.urlsafe_b64encode(canonical_json(replay_payload).encode("utf-8")).decode("ascii")
            command.extend(("--replay-json", encoded))
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(entry for entry in sys.path if entry)
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=environment)
        ready = self._read()
        if ready.get("kind") != "WORKER_READY" or ready.get("driver") != kind:
            self.close()
            raise DomainError("ADA_WORKER_START_FAILED", "ADA worker did not report the selected driver")

    @classmethod
    def fake(cls, *, fault: str | None = None, crash_after_row: int = 1) -> "SubprocessAdaDriver":
        return cls("FAKE", fault=fault, crash_after_row=crash_after_row)

    @classmethod
    def replay(cls, replay_fixture: Path) -> "SubprocessAdaDriver":
        payload = json.loads(replay_fixture.read_text(encoding="utf-8"))
        return cls("REPLAY", replay_payload=payload)

    @classmethod
    def replay_payload(cls, payload: dict) -> "SubprocessAdaDriver":
        return cls("REPLAY", replay_payload=payload)

    def _read(self) -> dict:
        if self.process.stdout is None:
            raise AdaSafetyStop("ADA_WORKER_DISCONNECTED", "ADA worker stdout is unavailable", state="FAILED")
        raw = self.process.stdout.readline()
        if not raw:
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            detail = ""
            if self.process.stderr is not None and self.process.poll() is not None:
                detail = self.process.stderr.read()[-500:]
            raise AdaSafetyStop("ADA_WORKER_DISCONNECTED", "ADA worker disconnected", state="FAILED", observed={"diagnostic": detail})
        message = json.loads(raw)
        if message.get("protocol_version") != PROTOCOL_VERSION:
            raise AdaSafetyStop("ADA_PROTOCOL_MISMATCH", "ADA worker protocol version changed", state="FAILED")
        return message

    def _request(self, action: str, payload: dict) -> dict:
        if self.process.poll() is not None or self.process.stdin is None:
            raise AdaSafetyStop("ADA_WORKER_DISCONNECTED", "ADA worker is not running", state="FAILED")
        message_id = new_id("ipc")
        try:
            self.process.stdin.write(canonical_json({"protocol_version": PROTOCOL_VERSION, "kind": "DRIVER_COMMAND", "message_id": message_id, "action": action, "payload": payload}) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AdaSafetyStop("ADA_WORKER_DISCONNECTED", "ADA worker input pipe closed", state="FAILED") from exc
        response = self._read()
        if response.get("message_id") != message_id:
            raise AdaSafetyStop("ADA_PROTOCOL_MISMATCH", "ADA worker response correlation failed", state="FAILED")
        if response.get("kind") == "DRIVER_FAULT":
            raise AdaSafetyStop(response["code"], response["message"], state=response.get("state", "PAUSED"), observed=response.get("observed", {}))
        if response.get("kind") != "DRIVER_RESULT":
            raise AdaSafetyStop("ADA_PROTOCOL_MISMATCH", "Unexpected ADA worker response", state="FAILED", observed=response)
        return response.get("result", {})

    def preflight(self, expected: dict) -> dict:
        return self._request("preflight", expected)

    def start_blank_receipt(self, header: dict) -> dict:
        return self._request("start_blank_receipt", header)

    def enter_line(self, line: dict, command_id: str) -> dict:
        return self._request("enter_line", {"line": line, "command_id": command_id})

    def readback_draft(self) -> dict:
        return self._request("readback_draft", {})

    def duplicate_before_save(self) -> bool:
        return bool(self._request("duplicate_before_save", {}).get("duplicate"))

    def save(self, authorization: dict) -> dict:
        return self._request("save", authorization)

    def verify_saved(self) -> dict:
        return self._request("verify_saved", {})

    def stop_safely(self) -> dict:
        if self.process.poll() is not None:
            return {"input_stopped": True, "save_clicked": False, "worker_alive": False}
        try:
            return self._request("stop_safely", {})
        except AdaSafetyStop:
            return {"input_stopped": True, "save_clicked": False, "worker_alive": False}

    def close(self) -> None:
        if self.process.poll() is None and self.process.stdin is not None:
            try:
                self.process.stdin.write(canonical_json({"protocol_version": PROTOCOL_VERSION, "kind": "CANCEL", "message_id": new_id("ipc")}) + "\n")
                self.process.stdin.flush()
                self._read()
            except (BrokenPipeError, OSError, DomainError, json.JSONDecodeError):
                pass
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass


class Win32KeyboardAdaDriver:
    kind = "LIVE_DISABLED"

    def __init__(self, profile: AppProfile) -> None:
        if not profile.live_ada_enabled:
            raise DomainError("LIVE_ADA_DISABLED", "Live Win32 ADA driver is feature-flagged off pending Phase 0 proof")
        raise DomainError("LIVE_ADA_UNPROVEN", "Live driver activation is outside this staging goal")


class NamedMutex:
    WAIT_OBJECT_0 = 0
    WAIT_ABANDONED = 0x80
    WAIT_TIMEOUT = 0x102

    def __init__(self, name: str) -> None:
        self.name = name
        self.handle: int | None = None

    def acquire(self) -> None:
        if not hasattr(ctypes, "windll"):
            raise DomainError("MUTEX_PLATFORM_UNSUPPORTED", "Windows named mutex is required")
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.ReleaseMutex.argtypes = (ctypes.c_void_p,)
        kernel32.ReleaseMutex.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise DomainError("ADA_MUTEX_CREATE_FAILED", "Could not create ADA mutex")
        result = kernel32.WaitForSingleObject(handle, 0)
        if result not in {self.WAIT_OBJECT_0, self.WAIT_ABANDONED}:
            kernel32.CloseHandle(handle)
            raise DomainError("ADA_MUTEX_BUSY", "Another automation run owns this ADA instance")
        self.handle = handle

    def release(self) -> None:
        if self.handle and hasattr(ctypes, "windll"):
            ctypes.windll.kernel32.ReleaseMutex(self.handle)
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


@dataclass(frozen=True)
class SaveAuthorization:
    run_id: str
    token: str
    actor_id: str
    expires_at: str


class AdaOrchestrator:
    def __init__(self, profile: AppProfile, repository: Repository, artifacts: FilesystemArtifactStore, validation: InvoiceValidationService) -> None:
        self.profile = profile
        self.repository = repository
        self.artifacts = artifacts
        self.validation = validation
        self.reconciliation = ReconciliationService()
        self._drivers: dict[str, AdaDriver] = {}
        self._mutexes: dict[str, NamedMutex] = {}

    def start_draft(self, document_id: str, actor: Actor, driver: AdaDriver, *, target_company: str = "STAGING_TEST", target_branch: str = "MAIN") -> dict:
        document = self.repository.get_document(document_id)
        if document["status"] != "READY_FOR_ADA":
            raise DomainError("DOCUMENT_NOT_READY", "Document must be READY_FOR_ADA before draft entry")
        if target_company not in self.profile.target_allowlist:
            raise DomainError("ADA_TARGET_NOT_ALLOWED", "Target company is not in the staging allowlist")
        validation = self.validation.validate(document_id)
        if not validation.ready or validation.snapshot_hash != document["review_snapshot_hash"]:
            raise DomainError("STALE_DOCUMENT_REVISION", "Ready snapshot is stale or validation no longer passes")
        expected = {"target_company": target_company, "target_branch": target_branch, "supplier_code": document["supplier_code"], "invoice_number": document["invoice_number_normalized"], "row_count": len(validation.canonical_snapshot["lines"]), "grand_total_minor": document["grand_total_minor"]}
        preflight = driver.preflight(expected)
        if not preflight.get("passed") or preflight.get("duplicate"):
            raise DomainError("ADA_PREFLIGHT_FAILED", "ADA preflight failed", detail=preflight)
        preflight_hash = hashlib.sha256(canonical_json(preflight).encode("utf-8")).hexdigest()
        idempotency_key = hashlib.sha256(f"{document_id}|{document['revision']}|{target_company}|{target_branch}".encode("utf-8")).hexdigest()
        run = self.repository.create_automation_run({
            "document_id": document_id, "document_revision": document["revision"], "review_snapshot_hash": validation.snapshot_hash,
            "driver_kind": driver.kind, "idempotency_key": idempotency_key, "state": "PREFLIGHT_PASSED", "current_step": "PREFLIGHT",
            "target_company": target_company, "target_branch": target_branch, "preflight_json": canonical_json(preflight), "preflight_hash": preflight_hash,
            "started_by": actor.actor_id,
        })
        mutex = NamedMutex(self.profile.mutex_name)
        try:
            mutex.acquire()
        except Exception:
            self.repository.update_automation_run(run["id"], state="FAILED", current_step="MUTEX", failure_code="ADA_MUTEX_BUSY", finished_at=now_iso())
            raise
        self._drivers[run["id"]] = driver
        self._mutexes[run["id"]] = mutex
        self.repository.update_document_status(document_id, "SENDING_TO_ADA")
        self._event(run["id"], "PREFLIGHT_PASSED", "PREFLIGHT", "preflight", expected, preflight)
        self._event(run["id"], "HEARTBEAT", "PREFLIGHT", "heartbeat-0", {}, {"protocol_version": PROTOCOL_VERSION})
        try:
            header = {"supplier_code": expected["supplier_code"], "invoice_number": expected["invoice_number"]}
            observed_header = driver.start_blank_receipt(header)
            self._event(run["id"], "HEADER_ENTERED", "ENTERING_HEADER", "header", header, observed_header)
            for line in validation.canonical_snapshot["lines"]:
                command_id = f"fill-row-{line['sequence']:04d}"
                observed = driver.enter_line(line, command_id)
                self._event(run["id"], "LINE_ENTERED", "ENTERING_LINES", command_id, line, observed, line["sequence"])
                self._event(run["id"], "HEARTBEAT", "ENTERING_LINES", f"heartbeat-{line['sequence']}", {}, {"last_verified_row": line["sequence"]}, line["sequence"])
                self.repository.update_automation_run(run["id"], state="ENTERING_LINES", current_step="ENTERING_LINES", current_line_sequence=line["sequence"])
            observed = driver.readback_draft()
            reconciliation = self.reconciliation.reconcile(expected, observed)
            reconciliation_hash = hashlib.sha256(canonical_json(reconciliation).encode("utf-8")).hexdigest()
            self._event(run["id"], "DRAFT_READBACK", "READING_BACK", "readback", expected, observed)
            if not reconciliation["passed"]:
                self.repository.update_automation_run(run["id"], state="PAUSED", current_step="RECONCILIATION", reconciliation_json=canonical_json(reconciliation), reconciliation_hash=reconciliation_hash, failure_code="ADA_RECONCILIATION_MISMATCH")
                self._event(run["id"], "SAFE_PAUSE", "RECONCILIATION", "pause-mismatch", expected, reconciliation, severity="ERROR")
                self._release(run["id"])
                return self.repository.get_automation_run(run["id"])
            self.repository.update_automation_run(run["id"], state="AWAITING_HUMAN_SAVE", current_step="AWAITING_HUMAN_SAVE", reconciliation_json=canonical_json(reconciliation), reconciliation_hash=reconciliation_hash)
            self.repository.update_document_status(document_id, "ADA_REVIEW_REQUIRED")
            self._event(run["id"], "RECONCILED", "RECONCILIATION", "reconciled", expected, reconciliation)
            return self.repository.get_automation_run(run["id"])
        except AdaSafetyStop as exc:
            stopped = driver.stop_safely()
            self.repository.update_automation_run(run["id"], state=exc.state, current_step="SAFE_STOP", failure_code=exc.code, finished_at=now_iso() if exc.state == "FAILED" else None)
            self._event(run["id"], "SAFE_STOP", "SAFE_STOP", "safe-stop", {}, {"fault": exc.code, "observation": exc.observed, "stop": stopped}, severity="ERROR")
            self._release(run["id"])
            return self.repository.get_automation_run(run["id"])

    def authorize_save(self, run_id: str, actor: Actor, *, ttl_seconds: int = 300) -> SaveAuthorization:
        run = self.repository.get_automation_run(run_id)
        document = self.repository.get_document(run["document_id"])
        if run["state"] != "AWAITING_HUMAN_SAVE" or document["status"] != "ADA_REVIEW_REQUIRED":
            raise DomainError("SAVE_AUTH_STATE_INVALID", "Exact reconciliation must pass before authorization")
        if document["revision"] != run["document_revision"] or document["review_snapshot_hash"] != run["review_snapshot_hash"]:
            raise DomainError("STALE_DOCUMENT_REVISION", "Document changed after preflight")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(timespec="milliseconds")
        self.repository.set_save_authorization(run_id, actor.actor_id, token_hash, expires_at)
        self.repository.append_audit(actor.actor_id, "ADA_SAVE_AUTHORIZED", "automation_run", run_id, new_id("corr"), {"document_revision": run["document_revision"], "preflight_hash": run["preflight_hash"], "reconciliation_hash": run["reconciliation_hash"], "expires_at": expires_at})
        return SaveAuthorization(run_id, token, actor.actor_id, expires_at)

    def save_simulated(self, authorization: SaveAuthorization, actor: Actor) -> dict:
        run = self.repository.get_automation_run(authorization.run_id)
        document = self.repository.get_document(run["document_id"])
        if document["revision"] != run["document_revision"] or document["review_snapshot_hash"] != run["review_snapshot_hash"]:
            raise DomainError("STALE_DOCUMENT_REVISION", "Document changed after authorization")
        token_hash = hashlib.sha256(authorization.token.encode("utf-8")).hexdigest()
        self.repository.consume_save_authorization(run["id"], actor.actor_id, token_hash, now_iso())
        driver = self._drivers.get(run["id"])
        if driver is None:
            raise DomainError("ADA_DRIVER_DISCONNECTED", "Driver is not connected; restart with inspection rather than blind resume")
        if driver.duplicate_before_save():
            self.repository.update_automation_run(run["id"], state="PAUSED", current_step="PRE_SAVE_DUPLICATE", failure_code="DUPLICATE_EXACT")
            self._event(run["id"], "SAFE_PAUSE", "PRE_SAVE_DUPLICATE", "duplicate-check", {"duplicate": False}, {"duplicate": True}, severity="ERROR")
            self._release(run["id"])
            return self.repository.get_automation_run(run["id"])
        try:
            save_result = driver.save({"run_id": run["id"], "actor_id": actor.actor_id, "document_revision": run["document_revision"], "preflight_hash": run["preflight_hash"], "reconciliation_hash": run["reconciliation_hash"], "expires_at": authorization.expires_at})
            self._event(run["id"], "SIMULATED_SAVE", "SAVING", "save", {"authorized": True}, save_result)
            verified = driver.verify_saved()
            self._event(run["id"], "POST_SAVE_VERIFIED", "VERIFYING_SAVE", "verify-save", {"document_number": save_result["document_number"]}, verified)
            events = self.repository.list_automation_events(run["id"])
            receipt = {"receipt_version": "staging-receipt.v1", "simulated": True, "environment": self.profile.environment, "document_id": document["id"], "automation_run_id": run["id"], "ada_document_number": verified["document_number"], "reviewer_id": document["created_by"], "save_authorized_by": actor.actor_id, "row_count": json.loads(run["reconciliation_json"])["comparisons"]["row_count"]["observed"], "grand_total_minor": document["grand_total_minor"], "reconciliation": json.loads(run["reconciliation_json"]), "automation_event_count": len(events), "event_chain_sha256": hashlib.sha256(canonical_json(events).encode("utf-8")).hexdigest(), "completed_at": now_iso()}
            receipt_ref = self.artifacts.write_json_artifact(f"artifacts/documents/{document['id']}/automation/{run['id']}/receipt.json", receipt)
            self.repository.update_automation_run(run["id"], state="COMPLETED", current_step="COMPLETED", finished_at=now_iso(), ada_document_number=verified["document_number"], receipt_artifact_ref=receipt_ref)
            self.repository.update_document_status(document["id"], "COMPLETED", completed=True)
            self.repository.append_audit(actor.actor_id, "SIMULATED_ADA_COMPLETED", "document", document["id"], new_id("corr"), {"run_id": run["id"], "receipt": receipt_ref})
            self._release(run["id"])
            return receipt
        except AdaSafetyStop as exc:
            stopped = driver.stop_safely()
            self.repository.update_automation_run(run["id"], state=exc.state, current_step="POST_SAVE_VERIFY", failure_code=exc.code, finished_at=now_iso())
            self._event(run["id"], "SAFE_STOP", "POST_SAVE_VERIFY", "post-save-failure", {}, {"fault": exc.code, "observed": exc.observed, "stop": stopped}, severity="ERROR")
            self._release(run["id"])
            return self.repository.get_automation_run(run["id"])

    def _event(self, run_id: str, kind: str, step: str, command_id: str, expected: dict, observed: dict, line_sequence: int | None = None, severity: str = "INFO") -> None:
        self.repository.append_automation_event(run_id, {"message_id": new_id("msg"), "command_id": command_id, "kind": kind, "severity": severity, "step": step, "line_sequence": line_sequence, "expected": expected, "observed": observed, "occurred_at": now_iso()})

    def _release(self, run_id: str) -> None:
        mutex = self._mutexes.pop(run_id, None)
        if mutex:
            mutex.release()
        driver = self._drivers.pop(run_id, None)
        if driver and hasattr(driver, "close"):
            driver.close()
