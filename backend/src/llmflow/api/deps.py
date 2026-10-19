"""Shared FastAPI dependencies: authentication for apps, people, and operators.

Three separate credentials, deliberately not interchangeable:
  * API keys (``llmf_...``) or operator keys   -> /v1/*   (applications; Bearer)
  * workspace user session (HttpOnly cookie)   -> /account/*, /auth/* (people; + CSRF)
  * operator admin key                         -> /admin/* (ops tooling; Bearer only)
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from llmflow.api.auth import Authenticator
from llmflow.core.errors import GatewayError
from llmflow.core.ratelimit import SlidingWindowLimiter
from llmflow.storage.tenants import Tenant, TenantRepo, User

SESSION_COOKIE = "llmflow_session"
CSRF_HEADER = "x-llmflow-csrf"


@dataclass(frozen=True, slots=True)
class Caller:
    """An authenticated /v1 caller. ``key_id`` keys budgets, rate limits, cache and logs."""

    key_id: str
    tenant: Tenant | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceSession:
    tenant: Tenant
    user: User


def client_ip(request: Request, trust_forwarded: bool) -> str:
    if trust_forwarded:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return hops[-1]  # the hop appended by our own proxy, not client-supplied
    return request.client.host if request.client else "unknown"


def request_ip(request: Request) -> str:
    return client_ip(request, request.app.state.trust_forwarded)


def throttle(request: Request) -> tuple[SlidingWindowLimiter, str]:
    state = request.app.state
    limiter: SlidingWindowLimiter = state.auth_limiter
    ip = client_ip(request, state.trust_forwarded)
    wait = limiter.retry_after(ip)
    if wait is not None:
        raise GatewayError(
            429, "rate_limited", "too many failed attempts; try again later",
            {"Retry-After": str(int(wait) + 1)},
        )  # fmt: skip
    return limiter, ip


def bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def authenticate(request: Request, authorization: str | None, scope: str) -> str:
    """Operator/admin key check with brute-force throttling."""
    limiter, ip = throttle(request)
    auth: Authenticator = request.app.state.auth if scope == "api" else request.app.state.admin_auth
    try:
        return auth.check(authorization)
    except GatewayError as exc:
        if exc.status == 401:
            limiter.hit(ip)
        raise


async def _caller(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Caller:
    state = request.app.state
    limiter, ip = throttle(request)
    operator_id = state.auth.try_check(authorization)
    if operator_id is not None:
        return Caller(operator_id)
    raw = bearer(authorization)
    repo: TenantRepo | None = state.tenants
    if raw and repo is not None:
        found = await repo.tenant_for_api_key(raw)
        if found is not None:
            tenant, _key = found
            if tenant.disabled:
                raise GatewayError(403, "forbidden", "this workspace is disabled")
            return Caller(tenant.id, tenant)
    limiter.hit(ip)
    if raw is None:
        raise GatewayError(401, "authentication_error", "missing bearer token")
    raise GatewayError(401, "authentication_error", "invalid API key")


async def _workspace(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> WorkspaceSession:
    """A signed-in person. API keys deliberately cannot manage a workspace: a leaked key must
    not be able to read secrets metadata, add provider keys, or mint more keys."""
    state = request.app.state
    if authorization is not None:
        raise GatewayError(403, "forbidden", "API keys cannot manage a workspace; sign in instead")
    cookie = request.cookies.get(SESSION_COOKIE)
    session = state.sessions.get(cookie) if cookie else None
    if session is None or session.tenant_id is None or session.user_id is None:
        raise GatewayError(401, "authentication_error", "sign in to continue")
    if not hmac.compare_digest(
        request.headers.get(CSRF_HEADER, "").encode(), session.csrf.encode()
    ):
        raise GatewayError(403, "forbidden", "missing or invalid CSRF token")
    repo: TenantRepo | None = state.tenants
    if repo is None:
        raise GatewayError(503, "byok_not_configured", "workspaces are not enabled")
    tenant = await repo.get_tenant(session.tenant_id)
    user = await repo.get_user(session.user_id)
    if tenant is None or user is None or tenant.disabled:
        raise GatewayError(401, "authentication_error", "workspace no longer available")
    return WorkspaceSession(tenant, user)


def _admin(request: Request, authorization: Annotated[str | None, Header()] = None) -> str:
    """Operator tooling: Bearer admin key only (no cookies, so no CSRF surface)."""
    return authenticate(request, authorization, "admin")


ClientCaller = Annotated[Caller, Depends(_caller)]
Workspace = Annotated[WorkspaceSession, Depends(_workspace)]
AdminPrincipal = Annotated[str, Depends(_admin)]


async def db_ready(request: Request) -> None:
    """Dependency for entry points that need the database (sign-in, sign-up, recovery).

    A suspended hosted database (Neon) takes a few seconds to resume and can refuse the first
    connection; this waits for it, with retries, instead of failing the person's request. It
    adds no public surface: these routes already query the database and are already throttled.
    """
    if not await request.app.state.usage.ensure_awake():
        raise GatewayError(
            503,
            "service_unavailable",
            "the database is starting up; try again in a moment",
            {"Retry-After": "5"},
        )
