"""Password hashing and policy (argon2id)."""

from __future__ import annotations

import hashlib
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128
_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters
# A real hash of a random value: verifying against it costs the same as a real check, so
# "unknown email" and "wrong password" take indistinguishable time.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(24))

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}$")
_COMMON = frozenset(
    [
        "password123456",
        "123456789012",
        "qwertyuiop12",
        "letmein12345",
        "iloveyou1234",
        "administrator",
        "welcome12345",
        "passwordpassword",
        "changeme1234",
    ]
)


class PasswordPolicyError(ValueError):
    pass


def normalise_email(email: str) -> str:
    cleaned = email.strip().lower()
    if len(cleaned) > 254 or not _EMAIL_RE.match(cleaned):
        raise ValueError("enter a valid email address")
    return cleaned


def check_policy(password: str, email: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"password must be at most {MAX_LENGTH} characters")
    lowered = password.lower()
    if len(set(password)) < 5 or lowered in _COMMON:
        raise PasswordPolicyError("password is too easy to guess")
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in lowered:
        raise PasswordPolicyError("password must not contain your email name")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Constant-work check; ``stored_hash=None`` (unknown user) still burns a full hash."""
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def new_recovery_codes(n: int = 10) -> list[str]:
    """Human-typable one-time codes, e.g. ``7K3Q-9XPM-4TDW`` (60 bits each)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return [
        "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        for _ in range(n)
    ]


def hash_recovery_code(code: str) -> str:
    normalised = re.sub(r"[^A-Z0-9]", "", code.upper())
    return hashlib.sha256(normalised.encode()).hexdigest()
