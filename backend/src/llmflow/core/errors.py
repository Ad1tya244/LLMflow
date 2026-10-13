"""Domain errors. Each carries the HTTP status and OpenAI-style error type it maps to."""

from __future__ import annotations

from enum import StrEnum


class ProviderErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    TIMEOUT = "timeout"
    SERVER = "server"
    NOT_FOUND = "not_found"
    BAD_REQUEST = "bad_request"


class ProviderError(Exception):
    """A failure from one upstream provider call."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        client_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        # Safe to show callers; ``message`` may contain raw upstream text and is log-only.
        self.client_message = client_message or "the upstream provider rejected the request"

    @property
    def fallback_eligible(self) -> bool:
        """Bad requests are the caller's fault; trying another model will not help."""
        return self.kind is not ProviderErrorKind.BAD_REQUEST


class GatewayError(Exception):
    def __init__(
        self,
        status: int,
        error_type: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.message = message
        self.headers = headers or {}
