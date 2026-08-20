from __future__ import annotations

import json
import subprocess
import sys

from ocr_inbound.ada_automation import PROTOCOL_VERSION
from ocr_inbound.ocr_adapter import ExistingOcrPipelineAdapter


def emit(kind: str, **payload) -> None:
    print(json.dumps({"protocol_version": PROTOCOL_VERSION, "kind": kind, **payload}, ensure_ascii=False), flush=True)


def main() -> int:
    raw = sys.stdin.readline()
    if not raw:
        emit("PROTOCOL_ERROR", code="COMMAND_REQUIRED")
        return 2
    message = json.loads(raw)
    if message.get("protocol_version") != PROTOCOL_VERSION:
        emit("PROTOCOL_ERROR", code="VERSION_UNSUPPORTED")
        return 2
    adapter = ExistingOcrPipelineAdapter()
    emit("OCR_STARTED", message_id=message.get("message_id"))
    completed = adapter.run_base(message["source"], message["legacy_out_root"])
    emit("OCR_FINISHED", returncode=completed.returncode, stdout=completed.stdout[-2000:], stderr=completed.stderr[-2000:])
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
