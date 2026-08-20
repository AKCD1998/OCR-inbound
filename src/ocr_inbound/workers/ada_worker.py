from __future__ import annotations

import argparse
import base64
import json
import sys
import time

from ocr_inbound.ada_automation import AdaSafetyStop, FakeAdaDriver, PROTOCOL_VERSION, ReplayAdaDriver


def emit(kind: str, **payload) -> None:
    print(json.dumps({"protocol_version": PROTOCOL_VERSION, "kind": kind, **payload}, sort_keys=True), flush=True)


def main() -> int:
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument("--driver",choices=("FAKE","REPLAY"));parser.add_argument("--fault");parser.add_argument("--crash-after-row",type=int,default=1);parser.add_argument("--replay-json");args=parser.parse_args()
    driver=None
    if args.driver=="FAKE":driver=FakeAdaDriver(fault=args.fault,crash_after_row=args.crash_after_row)
    elif args.driver=="REPLAY":
        if not args.replay_json:emit("PROTOCOL_ERROR",code="REPLAY_REQUIRED");return 2
        driver=ReplayAdaDriver.from_payload(json.loads(base64.urlsafe_b64decode(args.replay_json.encode("ascii")).decode("utf-8")))
    emit("WORKER_READY",driver=args.driver)
    for raw in sys.stdin:
        message = json.loads(raw)
        if message.get("protocol_version") != PROTOCOL_VERSION:
            emit("PROTOCOL_ERROR", code="VERSION_UNSUPPORTED")
            continue
        kind = message.get("kind")
        if kind == "HEARTBEAT":
            emit("HEARTBEAT", message_id=message.get("message_id"), occurred_monotonic=time.monotonic())
        elif kind == "CANCEL":
            emit("SAFE_DISCONNECT", input_stopped=True, save_clicked=False)
            return 0
        elif kind == "DRIVER_COMMAND" and driver is not None:
            action=message.get("action");payload=message.get("payload",{});message_id=message.get("message_id")
            try:
                if action=="preflight":result=driver.preflight(payload)
                elif action=="start_blank_receipt":result=driver.start_blank_receipt(payload)
                elif action=="enter_line":result=driver.enter_line(payload["line"],payload["command_id"])
                elif action=="readback_draft":result=driver.readback_draft()
                elif action=="duplicate_before_save":result={"duplicate":driver.duplicate_before_save()}
                elif action=="save":result=driver.save(payload)
                elif action=="verify_saved":result=driver.verify_saved()
                elif action=="stop_safely":result=driver.stop_safely()
                else:emit("DRIVER_FAULT",message_id=message_id,code="ADA_ACTION_UNSUPPORTED",message="Unsupported worker action",state="FAILED",observed={"action":action});continue
                emit("DRIVER_RESULT",message_id=message_id,result=result)
            except AdaSafetyStop as exc:
                if exc.code=="ADA_WORKER_DISCONNECTED":return 70
                emit("DRIVER_FAULT",message_id=message_id,code=exc.code,message=exc.message,state=exc.state,observed=exc.observed)
        else:
            emit("COMMAND_REJECTED", code="DRIVER_REQUIRED", message_id=message.get("message_id"))
    emit("SAFE_DISCONNECT", input_stopped=True, save_clicked=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
