from __future__ import annotations

import json
import re
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


def main() -> int:
    findings: list[dict] = []
    roots = [ROOT / "src", ROOT / "scripts", ROOT / "resources"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".js", ".html", ".css", ".json", ".sql", ".ps1", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    findings.append({"kind": name, "path": path.relative_to(ROOT).as_posix()})
    queries = {"product": SELECT_PRODUCT, "supplier": SELECT_SUPPLIER, "existing_invoice": SELECT_EXISTING_INVOICE}
    query_failures = [name for name, query in queries.items() if not query.lstrip().upper().startswith("SELECT ") or MUTATION.search(query)]
    with tempfile.TemporaryDirectory(prefix="ocr-inbound-safety-") as temp:
        profile = build_profile("staging", Path(temp))
        flags_safe = not profile.live_ada_enabled and not profile.live_adacc_enabled and not profile.production_save_enabled
    result = {"secret_scan": "pass" if not findings else "fail", "findings": findings, "ada_query_catalog": "pass" if not query_failures else "fail", "query_failures": query_failures, "live_flags_default_off": flags_safe}
    print(json.dumps(result, indent=2))
    return 0 if not findings and not query_failures and flags_safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
