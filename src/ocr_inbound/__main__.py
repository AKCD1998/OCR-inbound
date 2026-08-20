from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .ada_automation import SubprocessAdaDriver
from .errors import DomainError
from .service import Application
from .web import serve


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="OCR Inbound staging operational companion")
    root.add_argument("--environment", default="staging", choices=["staging", "production"])
    root.add_argument("--data-root", type=Path)
    root.add_argument("--reviewer", default="staging-reviewer")
    root.add_argument("--admin", action="store_true", help="Enable the local admin-only product review queue")
    sub = root.add_subparsers(dest="command")
    serve_parser = sub.add_parser("serve", help="Launch the local staging UI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8876)
    serve_parser.add_argument("--no-browser", action="store_true")
    import_parser = sub.add_parser("import", help="Import a PDF/image with a reviewed versioned OCR artifact")
    import_parser.add_argument("--source", type=Path, required=True)
    import_parser.add_argument("--artifact", type=Path, required=True)
    golden = sub.add_parser("golden", help="Run one complete Top 3 staging fixture")
    golden.add_argument("fixture", choices=["woothi", "charoon", "berlin"])
    golden.add_argument("--driver", choices=["FAKE", "REPLAY"], default="FAKE")
    sub.add_parser("top3", help="Run all Top 3 fixtures through the complete staging flow")
    sub.add_parser("health", help="Print System Health JSON")
    sub.add_parser("backup", help="Create an online SQLite backup")
    restore = sub.add_parser("restore", help="Restore a backup under the selected environment root")
    restore.add_argument("backup_path", type=Path)
    sub.add_parser("self-check", help="Initialize storage and verify safe staging defaults")
    sub.add_parser("worker-smoke", help="Verify packaged Fake driver JSONL worker isolation")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        app = Application.bootstrap(environment=args.environment, data_root=args.data_root, reviewer_id=args.reviewer, is_admin=args.admin)
        command = args.command or "serve"
        if command == "serve":
            serve(app, args.host, args.port, not args.no_browser)
            return 0
        if command == "import":
            result = app.import_artifact(args.source.resolve(), args.artifact.resolve())
            if not result["duplicate"]:
                app.generate_predictions(result["document"]["id"])
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        if command == "golden":
            print(json.dumps(app.run_golden(args.fixture, driver_kind=args.driver), ensure_ascii=False, indent=2))
            return 0
        if command == "top3":
            results = [app.run_golden(name, driver_kind="FAKE") for name in ("woothi", "charoon", "berlin")]
            print(json.dumps({"status": "ok", "fixtures": results, "metrics": app.repository.metrics()}, ensure_ascii=False, indent=2))
            return 0
        if command == "health":
            print(json.dumps(app.system_health(), ensure_ascii=False, indent=2, default=str))
            return 0
        if command == "backup":
            path = app.repository.backup("manual")
            print(json.dumps({"status": "ok", "backup": str(path), "integrity": app.repository.integrity_check()}))
            return 0
        if command == "restore":
            app.repository.restore(args.backup_path)
            print(json.dumps({"status": "ok", "integrity": app.repository.integrity_check()}))
            return 0
        if command == "self-check":
            health = app.system_health()
            required = health["environment"] == "staging" and not health["live_ada_enabled"] and not health["live_adacc_enabled"] and not health["production_save_enabled"] and health["db_integrity"] == "ok"
            print(json.dumps({"self_check": "pass" if required else "fail", "health": health}, ensure_ascii=False, indent=2, default=str))
            return 0 if required else 1
        if command == "worker-smoke":
            driver = SubprocessAdaDriver.fake()
            try:
                expected = {"target_company":"STAGING_TEST","target_branch":"MAIN","supplier_code":"SMOKE","invoice_number":"SMOKE-1","row_count":1,"grand_total_minor":100}
                preflight = driver.preflight(expected)
                driver.start_blank_receipt(expected)
                driver.enter_line({"sequence":1,"product_code":"SMOKE","unit_code":"EA","quantity":"1","line_total_minor":100}, "smoke-row-1")
                observed = driver.readback_draft()
                passed = preflight.get("passed") is True and observed["row_count"] == 1 and observed["grand_total_minor"] == 100
                print(json.dumps({"worker_smoke":"pass" if passed else "fail","driver":driver.kind,"observed":observed},ensure_ascii=False,indent=2))
                return 0 if passed else 1
            finally:
                driver.close()
        return 2
    except DomainError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
