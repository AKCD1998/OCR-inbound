from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import DomainError


ENVIRONMENTS = ("staging", "production")


@dataclass(frozen=True)
class AppProfile:
    environment: str
    root: Path
    app_db: Path
    ada_cache_db: Path
    artifacts: Path
    logs: Path
    backups: Path
    badge: str
    mutex_name: str
    target_allowlist: tuple[str, ...]
    live_ada_enabled: bool = False
    live_adacc_enabled: bool = False
    production_save_enabled: bool = False

    def ensure_directories(self) -> None:
        for path in (self.root, self.artifacts, self.logs, self.backups):
            path.mkdir(parents=True, exist_ok=True)

    def assert_within_root(self, path: Path, purpose: str) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError as exc:
            raise DomainError("ENV_PATH_ESCAPE", f"{purpose} must stay inside {self.environment} root") from exc
        return resolved


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_profile(environment: str = "staging", data_root: Path | None = None) -> AppProfile:
    env = environment.strip().lower()
    if env not in ENVIRONMENTS:
        raise DomainError("ENV_UNSUPPORTED", f"Unsupported environment: {environment}")
    configured = os.environ.get(f"OCR_INBOUND_{env.upper()}_ROOT")
    root = (data_root or (Path(configured) if configured else repository_root() / "environments" / env / "ocr_inbound_app")).resolve()
    profile = AppProfile(
        environment=env,
        root=root,
        app_db=root / "app.db",
        ada_cache_db=root / "ada_cache.db",
        artifacts=root / "artifacts",
        logs=root / "logs",
        backups=root / "backups",
        badge="STAGING — NOT PRODUCTION AUTH" if env == "staging" else "PRODUCTION — AUTOMATION DISABLED",
        mutex_name=f"Global\\OCRInbound.ADA.default.{env}",
        target_allowlist=("STAGING_TEST",) if env == "staging" else (),
    )
    profile.ensure_directories()
    return profile


def assert_physical_isolation(staging: AppProfile, production: AppProfile) -> None:
    paths = {staging.app_db, staging.ada_cache_db, staging.artifacts, production.app_db, production.ada_cache_db, production.artifacts}
    if len({p.resolve() for p in paths}) != len(paths):
        raise DomainError("ENV_NOT_ISOLATED", "Staging and production paths overlap")
    if staging.mutex_name == production.mutex_name:
        raise DomainError("ENV_MUTEX_COLLISION", "Staging and production mutex names collide")
