from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from ocr_inbound.ada_read import SELECT_EXISTING_INVOICE, SELECT_PRODUCT, SELECT_SUPPLIER
from ocr_inbound.config import build_profile


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = {
    "openai_key": re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "password_literal": re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"\s]{4,}['\"]"),
    "sqlserver_connection_string": re.compile(r"(?i)server\s*=.+;\s*(?:database|initial catalog)\s*="),
}
MUTATION = re.compile(r"\b(?:INSERT|UPDATE|DELETE|MERGE|EXEC|EXECUTE|CALL|TRUNCATE|DROP|ALTER|CREATE)\b", re.IGNORECASE)

# Tracked source-like trees the secret scan must cover (relative to the repo
# root). Everything else -- .git, .venv/venv, output/, environments/,
# generated OCR artifacts, caches, binaries/images/PDFs -- is excluded, both
# by never being a scan root and (in the filesystem-walk fallback) by the
# explicit prune list below.
SCAN_ROOTS = ("src", "scripts", "tests", "docs", "resources")
# Root-level source/config files are scanned too, but ONLY these suffixes:
# a stray root-level *.md is deliberately not scanned (it is not code and the
# repo root intentionally accumulates untracked work-summary handoffs).
ROOT_FILE_SUFFIXES = {".py", ".ps1", ".js", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".html", ".css", ".sql", ".txt"}
TREE_FILE_SUFFIXES = ROOT_FILE_SUFFIXES | {".md"}
EXCLUDED_DIR_NAMES = {".git", ".venv", "venv", "node_modules", "__pycache__", "output", "dist", "environments", ".playwright-cli", ".pytest_cache", ".mypy_cache", "ruff_cache", "ocr_runs_staging", "ocr_runs_final"}


def _has_suffix(path: Path, suffixes: set[str]) -> bool:
    return path.suffix.lower() in suffixes


def _git_tracked_files(repo_root: Path) -> list[str] | None:
    """Tracked file list, or None when git is unavailable (tests build plain
    temp trees). Tracking makes the scan deterministic: exactly what a clean
    CI checkout sees, never a developer's untracked local files."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "-c", "core.quotepath=off", "ls-files", "-z"],
            capture_output=True,
            timeout=30,
            check=True,
        )
    except Exception:
        return None
    return [entry for entry in completed.stdout.decode("utf-8", "replace").split("\0") if entry]


def _walk_fallback(repo_root: Path) -> list[Path]:
    """Filesystem walk used only when git is unavailable: same roots and
    suffixes, with excluded directories pruned during traversal."""
    files: list[Path] = []
    import os

    for name in SCAN_ROOTS:
        root = repo_root / name
        if not root.is_dir():
            continue
        for current, directories, filenames in os.walk(root):
            directories[:] = [d for d in directories if d not in EXCLUDED_DIR_NAMES]
            for filename in filenames:
                path = Path(current) / filename
                if _has_suffix(path, TREE_FILE_SUFFIXES):
                    files.append(path)
    for path in repo_root.iterdir():
        if path.is_file() and _has_suffix(path, ROOT_FILE_SUFFIXES):
            files.append(path)
    return files


def _candidate_files(repo_root: Path) -> list[Path]:
    tracked = _git_tracked_files(repo_root)
    if tracked is None:
        return _walk_fallback(repo_root)
    files: list[Path] = []
    for relative in tracked:
        top = relative.split("/", 1)[0]
        path = repo_root / relative
        if top in SCAN_ROOTS and _has_suffix(path, TREE_FILE_SUFFIXES):
            files.append(path)
        elif "/" not in relative and _has_suffix(path, ROOT_FILE_SUFFIXES):
            files.append(path)
    return files


def run_scan(repo_root: Path) -> dict:
    findings: list[dict] = []
    files = _candidate_files(repo_root)
    for path in files:
        relative = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in SECRET_PATTERNS.items():
            # finditer, not search: two fake passwords in one file are two
            # findings (each with its own line), not one.
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append({"kind": name, "path": relative, "line": line})
    queries = {"product": SELECT_PRODUCT, "supplier": SELECT_SUPPLIER, "existing_invoice": SELECT_EXISTING_INVOICE}
    query_failures = [name for name, query in queries.items() if not query.lstrip().upper().startswith("SELECT ") or MUTATION.search(query)]
    with tempfile.TemporaryDirectory(prefix="ocr-inbound-safety-") as temp:
        profile = build_profile("staging", Path(temp))
        flags_safe = not profile.live_ada_enabled and not profile.live_adacc_enabled and not profile.production_save_enabled
    return {
        "secret_scan": "pass" if not findings else "fail",
        "findings": findings,
        "files_scanned": len(files),
        "ada_query_catalog": "pass" if not query_failures else "fail",
        "query_failures": query_failures,
        "live_flags_default_off": flags_safe,
    }


def main() -> int:
    result = run_scan(ROOT)
    print(json.dumps(result, indent=2))
    return 0 if result["secret_scan"] == "pass" and not result["query_failures"] and result["live_flags_default_off"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
