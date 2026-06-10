#!/usr/bin/env python
"""Shared environment config for OCR pipeline and review UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional


ENVIRONMENTS = ("production", "staging")


def workspace_root() -> Path:
    return Path(__file__).resolve().parent


def load_dotenv(dotenv_path: Optional[Path] = None) -> None:
    path = dotenv_path or (workspace_root() / ".env")
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_environment_name(explicit: Optional[str] = None) -> str:
    value = (explicit or os.environ.get("OCR_ENV") or "production").strip().lower()
    if value not in ENVIRONMENTS:
        raise ValueError(f"Unsupported OCR environment: {value}")
    return value


def _env_key(environment: str, key: str) -> str:
    return f"OCR_{environment.upper()}_{key}"


def _path_value(environment: str, key: str, default_relative: str) -> Path:
    value = os.environ.get(_env_key(environment, key))
    path = Path(value) if value else (workspace_root() / default_relative)
    if not path.is_absolute():
        path = workspace_root() / path
    return path.resolve()


def _int_value(environment: str, key: str, default_value: int) -> int:
    raw = os.environ.get(_env_key(environment, key))
    if not raw:
        return default_value
    return int(raw)


def environment_config(environment: str) -> Dict[str, object]:
    env_name = resolve_environment_name(environment)
    default_run_dir = (
        "ocr_runs_final/18-25_3-681-5_a1752ee9b6"
        if env_name == "production"
        else "ocr_runs_staging/18-25_3-681-5_a1752ee9b6"
    )
    defaults = {
        "label": env_name.upper(),
        "inbound_dir": _path_value(env_name, "INBOUND_DIR", f"environments/{env_name}/inbound"),
        "out_dir": _path_value(env_name, "OUT_DIR", "ocr_runs_final" if env_name == "production" else "ocr_runs_staging"),
        "run_dir": _path_value(env_name, "RUN_DIR", default_run_dir),
        "review_port": _int_value(env_name, "REVIEW_PORT", 8765 if env_name == "production" else 8766),
    }
    return defaults


def is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_environment_path(environment: str, path: Path, *, purpose: str) -> None:
    env_name = resolve_environment_name(environment)
    target = path.resolve()
    active = environment_config(env_name)
    other_name = "staging" if env_name == "production" else "production"
    other = environment_config(other_name)
    active_root = Path(active["out_dir"]).resolve()
    other_root = Path(other["out_dir"]).resolve()
    if not is_within_root(target, active_root):
        raise ValueError(
            f"{purpose} must stay under the {env_name} output root: {active_root}. "
            f"Received: {target}"
        )
    if is_within_root(target, other_root):
        raise ValueError(
            f"{purpose} points into the {other_name} output root: {other_root}. "
            f"Received: {target}"
        )
