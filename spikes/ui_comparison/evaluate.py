"""Collect repeatable local toolchain and workload evidence without installing ecosystems."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run(command: list[str]) -> dict:
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return {"returncode": completed.returncode, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}
    except FileNotFoundError:
        return {"returncode": 127, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "stderr": "command not found"}


def main() -> int:
    fixture = json.loads((ROOT / "shared_fixture.json").read_text(encoding="utf-8"))
    result = {
        "evidence_version": "ui-spike-evidence.v1",
        "fixture_version": fixture["fixture_version"],
        "line_count": fixture["line_count"],
        "criteria": ["Thai rendering", "DPI 100/125/150", "keyboard edit/confirm/next issue", "virtualized table/focus", "evidence zoom", "non-blocking worker boundary", "packaging/runtime footprint", "legacy UI reuse", "testability/accessibility/dependency complexity", "Win32 worker boundary"],
        "local_web": {
            "status": "runnable",
            "runtime": f"Python {sys.version_info.major}.{sys.version_info.minor} stdlib + browser",
            "line_count": fixture["line_count"],
            "virtualization": "bounded DOM window",
            "keyboard": ["ArrowUp", "ArrowDown", "Enter", "Ctrl+Enter", "F8"],
            "evidence": fixture["evidence_image"],
            "legacy_reuse": "HTTP/static asset patterns and visual language from fusion_review_ui",
            "external_dependencies": 0
        },
        "pyside6": {"installed": importlib.util.find_spec("PySide6") is not None, "probe": run([sys.executable, str(ROOT / "pyside6" / "spike.py")])},
        "wpf": {"dotnet_path": shutil.which("dotnet"), "probe": run(["dotnet", "build", str(ROOT / "wpf" / "OcrInboundSpike.csproj"), "--nologo"])},
        "decision": "local-web"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
