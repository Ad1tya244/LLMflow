"""Server-side admin sessions.

The admin key is exchanged once for an opaque, random session token delivered in an
``HttpOnly`` cookie, so page JavaScript (and therefore XSS) can never read a credential.
A per-session CSRF token is returned in the JSON body and must be echoed in a header on
every cookie-authenticated request, which also forces a CORS preflight.

State is process-local (single instance); sessions end on restart.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class Session:
    csrf: str
    created: float
    last_seen: float
    role: str = "tenant"
    tenant_id: str | None = None
    user_id: str | None = None
    ip: str = ""
    user_agent: str = ""
    created_at: float = 0.0  # wall clock, for display (the monotonic clock is for expiry)
    last_seen_at: float = 0.0


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessionStore:
    def __init__(
        self,
        idle_s: float,
        max_age_s: float,
        max_sessions: int = 50,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._idle = idle_s
        self._max_age = max_age_s
        self._max = max_sessions
        self._clock = clock
        self._sessions: dict[str, Session] = {}

    @property
    def max_age_s(self) -> float:
        return self._max_age

    def _expired(self, s: Session, now: float) -> bool:
        return now - s.last_seen > self._idle or now - s.created > self._max_age

    def _sweep(self, now: float) -> None:
        for k in [k for k, s in self._sessions.items() if self._expired(s, now)]:
            del self._sessions[k]

    def create(
        self,
        role: str = "tenant",
        tenant_id: str | None = None,
        user_id: str | None = None,
        ip: str = "",
        user_agent: str = "",
    ) -> tuple[str, str]:
        """Return ``(cookie_token, csrf_token)``. The raw cookie token is never stored."""
        now = self._clock()
        self._sweep(now)
        while len(self._sessions) >= self._max:  # evict oldest instead of growing unbounded
            oldest = min(self._sessions, key=lambda k: self._sessions[k].created)
            del self._sessions[oldest]
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        wall = time.time()
        self._sessions[_hash(token)] = Session(
            csrf, now, now, role, tenant_id, user_id, ip[:45], user_agent[:200], wall, wall
        )
        return token, csrf

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        now = self._clock()
        key = _hash(token)
        s = self._sessions.get(key)
        if s is None:
            return None
        if self._expired(s, now):
            del self._sessions[key]
            return None
        s.last_seen = now
        s.last_seen_at = time.time()
        return s

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(_hash(token), None)

    @staticmethod
    def session_id(token: str | None) -> str | None:
        """Public, non-secret handle for a session (a truncated hash of its cookie token)."""
        return _hash(token)[:16] if token else None

    def list_for_user(self, user_id: str) -> list[tuple[str, Session]]:
        now = self._clock()
        self._sweep(now)
        rows = [(k[:16], s) for k, s in self._sessions.items() if s.user_id == user_id]
        return sorted(rows, key=lambda r: r[1].created_at, reverse=True)

    def revoke_by_id(self, user_id: str, session_id: str) -> bool:
        for k, s in list(self._sessions.items()):
            if s.user_id == user_id and k[:16] == session_id:
                del self._sessions[k]
                return True
        return False

    def revoke_others(self, user_id: str, keep_token: str | None) -> int:
        keep = _hash(keep_token) if keep_token else None
        doomed = [k for k, s in self._sessions.items() if s.user_id == user_id and k != keep]
        for k in doomed:
            del self._sessions[k]
        return len(doomed)

    def revoke_user(self, user_id: str) -> int:
        """End every session of a user (password change, recovery). Returns how many."""
        doomed = [k for k, s in self._sessions.items() if s.user_id == user_id]
        for k in doomed:
            del self._sessions[k]
        return len(doomed)

    def __len__(self) -> int:
        return len(self._sessions)


@dataclass(slots=True)
class MfaChallenge:
    user_id: str
    expires: float
    attempts: int = 0


class MfaChallengeStore:
    """Short-lived, single-use proof that the password step succeeded.

    The raw token is returned to the client once; only its hash is kept. Each challenge allows a
    handful of code attempts and is destroyed on success or when it runs out of attempts."""

    def __init__(
        self,
        ttl_s: float = 300.0,
        max_attempts: int = 5,
        max_open: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl, self._max_attempts, self._max_open, self._clock = (
            ttl_s,
            max_attempts,
            max_open,
            clock,
        )
        self._items: dict[str, MfaChallenge] = {}

    def create(self, user_id: str) -> str:
        now = self._clock()
        for k in [k for k, c in self._items.items() if c.expires <= now]:
            del self._items[k]
        while len(self._items) >= self._max_open:
            del self._items[next(iter(self._items))]
        token = secrets.token_urlsafe(32)
        self._items[_hash(token)] = MfaChallenge(user_id, now + self._ttl)
        return token

    def peek(self, token: str) -> MfaChallenge | None:
        """Return the live challenge and count an attempt; None if unknown/expired/exhausted."""
        key = _hash(token)
        c = self._items.get(key)
        if c is None or c.expires <= self._clock():
            self._items.pop(key, None)
            return None
        c.attempts += 1
        if c.attempts > self._max_attempts:
            del self._items[key]
            return None
        return c

    def consume(self, token: str) -> None:
        self._items.pop(_hash(token), None)
