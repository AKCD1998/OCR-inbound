from __future__ import annotations


class DomainError(RuntimeError):
    """Stable application error; details are safe to present to a staging user."""

    def __init__(self, code: str, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}
