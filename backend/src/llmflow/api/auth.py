"""API-key authentication for client and admin scopes."""

from __future__ import annotations

import hashlib
import hmac

from llmflow.core.errors import GatewayError


def _digest(key: str) -> bytes:
    return hashlib.sha256(key.encode()).digest()


class Authenticator:
    """Constant-time check against SHA-256 digests; raw keys are not retained.

    ``keys`` empty means the scope is unconfigured: with ``disabled`` False every request
    is rejected (never an open door).
    """

    def __init__(self, keys: list[str], *, disabled: bool = False, scope: str = "api") -> None:
        self._digests = [_digest(k) for k in keys]
        self._disabled = disabled
        self._scope = scope

    @property
    def configured(self) -> bool:
        return self._disabled or bool(self._digests)

    def check(self, authorization: str | None) -> str:
        if self._disabled:
            return "anonymous"
        if not self._digests:
            raise GatewayError(403, "forbidden", f"{self._scope} access is not configured")
        if not authorization or not authorization.lower().startswith("bearer "):
            raise GatewayError(401, "authentication_error", "missing bearer token")
        presented = _digest(authorization[7:].strip())
        matched = False
        for d in self._digests:  # no early exit: avoid timing differences between keys
            matched |= hmac.compare_digest(d, presented)
        if not matched:
            raise GatewayError(401, "authentication_error", "invalid API key")
        return presented.hex()[:8]

    def try_check(self, authorization: str | None) -> str | None:
        """Like ``check`` but returns None instead of raising when the key does not match."""
        if self._disabled:
            return "anonymous"
        if (
            not self._digests
            or not authorization
            or not authorization.lower().startswith("bearer ")
        ):
            return None
        presented = _digest(authorization[7:].strip())
        matched = False
        for d in self._digests:
            matched |= hmac.compare_digest(d, presented)
        return presented.hex()[:8] if matched else None
