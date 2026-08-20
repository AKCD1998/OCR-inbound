from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import DomainError


@dataclass(frozen=True)
class Actor:
    actor_id: str
    display_name: str
    authentication_label: str


class IdentityProvider(Protocol):
    def current_actor(self) -> Actor: ...


class StagingIdentityProvider:
    """Explicit named staging identity. This is deliberately not production authentication."""

    def __init__(self, reviewer_id: str, display_name: str | None = None) -> None:
        reviewer_id = reviewer_id.strip()
        if not reviewer_id or reviewer_id.lower() in {"anonymous", "shared", "dao1"}:
            raise DomainError("REVIEWER_ID_REQUIRED", "Use an explicit unique staging reviewer ID; ADA recorder text is not an identity")
        self._actor = Actor(reviewer_id, (display_name or reviewer_id).strip(), "STAGING PROFILE — NOT PRODUCTION AUTHENTICATION")

    def current_actor(self) -> Actor:
        return self._actor


class ProductionIdentityBlocked:
    def current_actor(self) -> Actor:
        raise DomainError("PRODUCTION_IDENTITY_BLOCKED", "Owner/IT must configure production authentication")
