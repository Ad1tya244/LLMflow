"""RFC 6238 time-based one-time passwords (SHA-1, 6 digits, 30 s), stdlib only.

Compatible with Google Authenticator, Authy, 1Password, Microsoft Authenticator, etc.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_S = 30
DIGITS = 6


def new_secret() -> str:
    """160-bit secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    pad = "=" * (-len(secret_b32) % 8)
    return base64.b32decode(secret_b32.upper() + pad)


def code_at(secret_b32: str, step: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_key(secret_b32), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_S)


def verify(
    secret_b32: str, code: str, *, last_step: int = 0, now: float | None = None, window: int = 1
) -> int | None:
    """Return the matched time step, or None. ``window`` allows clock drift of +/- N steps.
    A step at or before ``last_step`` is rejected, so a code cannot be replayed."""
    cleaned = code.strip().replace(" ", "")
    if not (cleaned.isdigit() and len(cleaned) == DIGITS):
        return None
    base = current_step(now)
    matched: int | None = None
    for step in range(base - window, base + window + 1):  # no early exit: constant work
        if hmac.compare_digest(code_at(secret_b32, step), cleaned) and step > last_step:
            matched = step
    return matched


def provisioning_uri(secret_b32: str, account: str, issuer: str = "LLMFlow") -> str:
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_S}"
    )
