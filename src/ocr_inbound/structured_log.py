from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .db import now_iso


SECRET_PATTERN = re.compile(r"(?i)(password|passwd|pwd|token|secret|authorization|connection[_ -]?string)\s*[:=]\s*[^\s,;]+")
ALLOWED_KEYS = {"event", "severity", "correlation_id", "document_id", "run_id", "actor_id", "code", "detail", "occurred_at"}


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return SECRET_PATTERN.sub(lambda match: match.group(1) + "=[REDACTED]", value)
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if re.search(r"(?i)password|token|secret|authorization|connection", key) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class StructuredLogger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def emit(self, **event: Any) -> None:
        payload = {key: redact(value) for key, value in event.items() if key in ALLOWED_KEYS}
        payload.setdefault("occurred_at", now_iso())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
