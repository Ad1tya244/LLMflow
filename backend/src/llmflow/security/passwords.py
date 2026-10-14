"""Password hashing and policy (argon2id)."""

from __future__ import annotations

import hashlib
import itertools
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
# Substrings that make a password guessable regardless of what surrounds them.
_WEAK_WORDS = (
    "password", "passw0rd", "qwerty", "asdfgh", "zxcvbn", "letmein", "welcome", "iloveyou",
    "admin", "administrator", "changeme", "llmflow", "monkey", "dragon", "football",
    "baseball", "trustno1", "sunshine", "princess", "login",
)  # fmt: skip
_KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890")
_RUN = 4  # length of a sequential or repeated run that is rejected


class PasswordPolicyError(ValueError):
    pass


def _has_sequence(lowered: str) -> bool:
    """True for runs like ``abcd``, ``4321`` or a keyboard row segment such as ``qwer``."""
    for i in range(len(lowered) - _RUN + 1):
        chunk = lowered[i : i + _RUN]
        codes = [ord(c) for c in chunk]
        steps = {b - a for a, b in itertools.pairwise(codes)}
        if steps in ({1}, {-1}) and all(c.isalnum() for c in chunk):
            return True
        for row in _KEYBOARD_ROWS:
            if chunk in row or chunk in row[::-1]:
                return True
    return False


def _has_repeat(password: str) -> bool:
    return any(len(set(password[i : i + _RUN])) == 1 for i in range(len(password) - _RUN + 1))


def normalise_email(email: str) -> str:
    cleaned = email.strip().lower()
    if len(cleaned) > 254 or not _EMAIL_RE.match(cleaned):
        raise ValueError("enter a valid email address")
    return cleaned


def check_policy(password: str, email: str = "") -> None:
    """Complexity policy applied when a password is *set* (sign-up, change, reset).

    Sign-in never applies it, so accounts created under an older policy keep working."""
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"password must be at most {MAX_LENGTH} characters")
    missing = [
        name
        for name, ok in (
            ("an uppercase letter", any(c.isupper() for c in password)),
            ("a lowercase letter", any(c.islower() for c in password)),
            ("a number", any(c.isdigit() for c in password)),
            ("a symbol (such as ! @ # $ % or a space)", any(not c.isalnum() for c in password)),
        )
        if not ok
    ]
    if missing:
        raise PasswordPolicyError("password must include " + ", ".join(missing))
    lowered = password.lower()
    if len(set(lowered)) < 6:
        raise PasswordPolicyError("password uses too few different characters")
    if _has_repeat(lowered):
        raise PasswordPolicyError("password must not repeat the same character 4 times in a row")
    if _has_sequence(lowered):
        raise PasswordPolicyError("password must not contain sequences such as abcd, 1234 or qwer")
    if any(word in lowered for word in _WEAK_WORDS):
        raise PasswordPolicyError("password contains a common word that is easy to guess")
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
