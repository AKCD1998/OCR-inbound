from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def main() -> int:
    package = Path("dist/ocr-inbound-staging.pyz").resolve()
    if not package.exists():
        print("package missing", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="ocr-inbound-package-smoke-") as temp:
        completed = subprocess.run([sys.executable, str(package), "--data-root", temp, "--reviewer", "package-smoke", "self-check"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        print(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        if completed.returncode:
            return completed.returncode
        if json.loads(completed.stdout)["self_check"] != "pass":
            return 1

        worker = subprocess.run([sys.executable, str(package), "--data-root", temp, "--reviewer", "package-smoke", "worker-smoke"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        print(worker.stdout)
        if worker.stderr:
            print(worker.stderr, file=sys.stderr)
        if worker.returncode or json.loads(worker.stdout)["worker_smoke"] != "pass":
            return worker.returncode or 1

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        server = subprocess.Popen(
            [sys.executable, str(package), "--data-root", temp, "--reviewer", "package-smoke", "serve", "--host", "127.0.0.1", "--port", str(port), "--no-browser"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            health = None
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except OSError:
                    time.sleep(0.1)
            if health is None:
                stdout, stderr = server.communicate(timeout=2) if server.poll() is not None else ("", "")
                print(stdout, file=sys.stderr)
                print(stderr, file=sys.stderr)
                print("packaged server did not become healthy", file=sys.stderr)
                return 1
            passed = health["status"] == "ok" and health["environment"] == "staging" and not health["live_ada_enabled"] and not health["production_save_enabled"]
            print(json.dumps({"launch_smoke": "pass" if passed else "fail", "url": f"http://127.0.0.1:{port}/", "health": health}, ensure_ascii=False, indent=2))
            return 0 if passed else 1
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
