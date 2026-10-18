"""Workspace API for signed-in people: API keys, provider keys, usage, audit, playground.

Requires a dashboard session (cookie + CSRF). Application API keys are refused here on
purpose, so a leaked key cannot read workspace metadata, add provider keys or mint keys.
Provider keys are verified on save and encrypted at rest. Listings show the last 4 only; the
full value comes back only from the re-authenticated ``/reveal`` endpoints.
"""

from __future__ import annotations

import re
import time
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from llmflow.api.admin import _RANGES, Range, build_overview
from llmflow.api.deps import SESSION_COOKIE, Workspace, request_ip
from llmflow.api.reauth import confirm_identity
from llmflow.core.errors import GatewayError
from llmflow.core.ratelimit import SlidingWindowLimiter
from llmflow.schemas import ChatRequest
from llmflow.security.passwords import MIN_LENGTH
from llmflow.security.vault import KeyVault
from llmflow.storage.tenants import TenantRepo, WorkspaceSettings
from llmflow.storage.usage import UsageRepo
from llmflow.tenancy import TenantScopes

router = APIRouter(tags=["account"])
public = APIRouter(tags=["public"])

_KEY_RE = re.compile(r"^[\x21-\x7e]{8,512}$")  # printable ASCII, no whitespace
_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f<>]{1,60}$")
MAX_ACTIVE_API_KEYS = 20


class ProviderKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(min_length=8, max_length=512)
    verify: bool = True


class SettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_mode: Literal["auto", "always", "off"] = "auto"
    default_quality: Literal["low", "balanced", "high"] = "balanced"
    daily_budget_usd: float | None = Field(default=None, gt=0, le=1_000_000)
    daily_token_budget: int | None = Field(default=None, gt=0, le=10_000_000_000)


class RevealBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(max_length=128)
    code: str | None = Field(default=None, max_length=12)


class NewApiKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)


def _state(request: Request) -> tuple[TenantRepo, KeyVault, TenantScopes]:
    st = request.app.state
    if st.tenants is None or st.vault is None or st.tenant_scopes is None:
        raise GatewayError(503, "byok_not_configured", "workspaces are not enabled on this gateway")
    return st.tenants, st.vault, st.tenant_scopes


def _limit(request: Request, tenant_id: str) -> None:
    limiter: SlidingWindowLimiter = request.app.state.key_limiter
    wait = limiter.acquire(f"acct:{tenant_id}")
    if wait is not None:
        raise GatewayError(
            429, "rate_limited", "too many requests", {"Retry-After": str(int(wait) + 1)}
        )


@public.get("/public/info")
async def public_info(request: Request) -> dict[str, Any]:
    st = request.app.state
    byok = st.tenants is not None
    return {
        "byok_enabled": byok,
        "signup_enabled": bool(byok and st.settings.signup_enabled),
        "invite_code_required": bool(st.settings.signup_code),
        "password_min_length": MIN_LENGTH,
    }


@router.get("/account")
async def account(request: Request, ws: Workspace) -> dict[str, Any]:
    repo, _vault, scopes = _state(request)
    _limit(request, ws.tenant.id)
    gw = request.app.state.gateway
    keys = await repo.provider_keys(ws.tenant.id)
    quota = scopes.quota_for(ws.tenant.id)  # no decryption needed to describe the workspace
    spend = gw.budget.spend(ws.tenant.id)
    workspace = await repo.get_settings(ws.tenant.id)
    gw.budget.set_limits(ws.tenant.id, workspace.daily_budget_usd, workspace.daily_token_budget)
    cap_usd, cap_tokens = gw.budget.limits(ws.tenant.id)
    return {
        "workspace": {
            "id": ws.tenant.id,
            "name": ws.tenant.name,
            "created_at": ws.tenant.created_at,
        },
        "user": {
            "email": ws.user.email,
            "last_login_at": ws.user.last_login_at,
            "mfa_enabled": ws.user.mfa_enabled,
        },
        "recovery_codes_left": await repo.unused_recovery_codes(ws.user.id),
        "providers": [
            {
                "id": p.id,
                "configured": p.id in keys,
                "last4": keys[p.id][1] if p.id in keys else None,
                "trains_on_data": p.trains_on_data,
                "auth_failed": bool(p.id in keys and quota.snapshot_provider_disabled(p.id)),
            }
            for p in gw.catalog.providers.values()
        ],
        "models": [
            {
                "id": m.id,
                "provider": m.provider,
                "upstream_model": m.upstream_model,
                "tier": m.tier.name.lower(),
                "enabled": m.provider in keys,
            }
            for m in gw.catalog.models.values()
            if m.enabled
        ],
        "usage_today": {"tokens": spend.tokens, "shadow_cost_usd": round(spend.cost_usd, 8)},
        "limits": {
            "daily_budget_usd": cap_usd,
            "daily_token_budget": cap_tokens,
            "rate_limit_rpm": request.app.state.settings.rate_limit_rpm,
        },
    }


# --- workspace settings ---------------------------------------------------------------


def _settings_json(s: WorkspaceSettings, request: Request) -> dict[str, Any]:
    budget = request.app.state.gateway.budget
    return {
        "cache_mode": s.cache_mode,
        "default_quality": s.default_quality,
        "daily_budget_usd": s.daily_budget_usd,
        "daily_token_budget": s.daily_token_budget,
        "platform_caps": {
            "daily_budget_usd": budget.daily_usd,
            "daily_token_budget": budget.daily_tokens,
        },
    }


@router.get("/account/settings")
async def get_settings(request: Request, ws: Workspace) -> dict[str, Any]:
    repo, _v, _s = _state(request)
    return _settings_json(await repo.get_settings(ws.tenant.id), request)


@router.put("/account/settings")
async def put_settings(request: Request, body: SettingsBody, ws: Workspace) -> dict[str, Any]:
    repo, _v, _s = _state(request)
    _limit(request, ws.tenant.id)
    new = WorkspaceSettings(
        body.cache_mode, body.default_quality, body.daily_budget_usd, body.daily_token_budget
    )
    old = await repo.get_settings(ws.tenant.id)
    await repo.put_settings(ws.tenant.id, new)
    request.app.state.gateway.budget.set_limits(
        ws.tenant.id, new.daily_budget_usd, new.daily_token_budget
    )
    changed = [f for f in new.__slots__ if getattr(new, f) != getattr(old, f)]
    detail = ", ".join(changed) or "no change"
    await repo.audit(ws.tenant.id, ws.user.email, "settings.changed", detail, request_ip(request))
    return _settings_json(new, request)


# --- active sessions ---------------------------------------------------------------------


@router.get("/account/sessions")
async def list_sessions(request: Request, ws: Workspace) -> dict[str, Any]:
    store = request.app.state.sessions
    current = store.session_id(request.cookies.get(SESSION_COOKIE))
    return {
        "sessions": [
            {
                "id": sid,
                "created_at": s.created_at,
                "last_seen_at": s.last_seen_at,
                "ip": s.ip,
                "user_agent": s.user_agent,
                "current": sid == current,
            }
            for sid, s in store.list_for_user(ws.user.id)
        ]
    }


@router.post("/account/sessions/revoke-others")
async def revoke_other_sessions(request: Request, ws: Workspace) -> dict[str, Any]:
    repo, _v, _s = _state(request)
    count = request.app.state.sessions.revoke_others(
        ws.user.id, request.cookies.get(SESSION_COOKIE)
    )
    await repo.audit(ws.tenant.id, ws.user.email, "session.revoked", f"{count} other session(s)",
                     request_ip(request))  # fmt: skip
    return {"revoked": count}


@router.delete("/account/sessions/{session_id}")
async def revoke_session(request: Request, session_id: str, ws: Workspace) -> dict[str, str]:
    repo, _v, _s = _state(request)
    store = request.app.state.sessions
    if session_id == store.session_id(request.cookies.get(SESSION_COOKIE)):
        raise GatewayError(400, "invalid_request_error", "use Sign out to end this session")
    if not store.revoke_by_id(ws.user.id, session_id):
        raise GatewayError(404, "not_found", "no such session")
    await repo.audit(
        ws.tenant.id, ws.user.email, "session.revoked", session_id[:8], request_ip(request)
    )
    return {"status": "revoked"}


# --- application API keys ---------------------------------------------------------------


def _key_json(k: Any) -> dict[str, Any]:
    return {
        "id": k.id,
        "name": k.name,
        "last4": k.last4,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
        "revoked_at": k.revoked_at,
    }


@router.get("/account/api-keys")
async def list_api_keys(request: Request, ws: Workspace) -> dict[str, Any]:
    repo, _v, _s = _state(request)
    revealable = await repo.revealable_key_ids(ws.tenant.id)
    return {
        "keys": [
            {**_key_json(k), "revealable": k.revoked_at is None and k.id in revealable}
            for k in await repo.list_api_keys(ws.tenant.id)
        ]
    }


@router.post("/account/api-keys", status_code=201)
async def create_api_key(request: Request, body: NewApiKey, ws: Workspace) -> dict[str, Any]:
    """Mint an application key. The secret is returned exactly once."""
    repo, vault, _s = _state(request)
    _limit(request, ws.tenant.id)
    name = body.name.strip()
    if not _NAME_RE.match(name):
        raise GatewayError(422, "invalid_request_error", "key name contains invalid characters")
    active = [k for k in await repo.list_api_keys(ws.tenant.id) if k.revoked_at is None]
    if len(active) >= MAX_ACTIVE_API_KEYS:
        raise GatewayError(
            409, "conflict", f"at most {MAX_ACTIVE_API_KEYS} active API keys; revoke one first"
        )
    key, raw = await repo.create_api_key(ws.tenant.id, name)
    await repo.store_api_key_secret(
        ws.tenant.id, key.id, vault.encrypt(ws.tenant.id, f"api_key:{key.id}", raw)
    )
    await repo.audit(ws.tenant.id, ws.user.email, "api_key.created", f"{key.name} (…{key.last4})",
                     request_ip(request))  # fmt: skip
    return {**_key_json(key), "revealable": True, "api_key": raw}


_NO_STORE = {"Cache-Control": "no-store"}


@router.post("/account/api-keys/{key_id}/reveal")
async def reveal_api_key(
    request: Request, key_id: str, body: RevealBody, ws: Workspace
) -> JSONResponse:
    """Show an active application key again. Needs the password (and 2FA code if enabled)."""
    repo, vault, _s = _state(request)
    _limit(request, ws.tenant.id)
    await confirm_identity(request, repo, ws, body.password, body.code)
    token = await repo.api_key_secret(ws.tenant.id, key_id)
    if token is None:
        raise GatewayError(
            404,
            "not_found",
            "this key cannot be shown again (it is revoked, or was created before key viewing "
            "existed); create a new key",
        )
    raw = vault.decrypt(ws.tenant.id, f"api_key:{key_id}", token)
    await repo.audit(ws.tenant.id, ws.user.email, "api_key.revealed", key_id, request_ip(request))
    return JSONResponse({"api_key": raw}, headers=_NO_STORE)


@router.delete("/account/api-keys/{key_id}")
async def revoke_api_key(request: Request, key_id: str, ws: Workspace) -> dict[str, str]:
    repo, _v, _s = _state(request)
    _limit(request, ws.tenant.id)
    if not await repo.revoke_api_key(ws.tenant.id, key_id):
        raise GatewayError(404, "not_found", "no such active API key")
    await repo.audit(ws.tenant.id, ws.user.email, "api_key.revoked", key_id, request_ip(request))
    return {"status": "revoked"}


# --- provider keys (bring your own) ---------------------------------------------------------


@router.post("/account/provider-keys/{provider}/reveal")
async def reveal_provider_key(
    request: Request, provider: str, body: RevealBody, ws: Workspace
) -> JSONResponse:
    """Show a saved provider key again. Needs the password (and 2FA code if enabled)."""
    repo, vault, _scopes = _state(request)
    _limit(request, ws.tenant.id)
    await confirm_identity(request, repo, ws, body.password, body.code)
    stored = (await repo.provider_keys(ws.tenant.id)).get(provider)
    if stored is None:
        raise GatewayError(404, "not_found", "no key saved for that provider")
    secret = vault.decrypt(ws.tenant.id, provider, stored[0])
    await repo.audit(
        ws.tenant.id, ws.user.email, "provider_key.revealed", provider, request_ip(request)
    )
    return JSONResponse({"api_key": secret}, headers=_NO_STORE)


@router.put("/account/provider-keys/{provider}")
async def put_provider_key(
    request: Request, provider: str, body: ProviderKeyBody, ws: Workspace
) -> dict[str, Any]:
    repo, vault, scopes = _state(request)
    _limit(request, ws.tenant.id)
    spec = request.app.state.gateway.catalog.providers.get(provider)
    if spec is None:
        raise GatewayError(404, "not_found", f"unknown provider {provider!r}")
    key = body.api_key.strip()
    if not _KEY_RE.match(key):
        raise GatewayError(422, "invalid_request_error", "that does not look like an API key")

    verified: bool | None = None
    if body.verify:
        client: httpx.AsyncClient = request.app.state.http
        try:
            r = await client.get(
                f"{spec.base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise GatewayError(
                502, "upstream_unreachable", f"could not reach {provider} to verify the key"
            ) from exc
        if r.status_code in (401, 403):
            raise GatewayError(422, "invalid_request_error", f"{provider} rejected this key")
        verified = r.status_code == 200  # other statuses: provider has no /models; save unverified

    await repo.put_provider_key(
        ws.tenant.id, provider, vault.encrypt(ws.tenant.id, provider, key), key[-4:]
    )
    scopes.invalidate(ws.tenant.id)
    await repo.audit(ws.tenant.id, ws.user.email, "provider_key.saved", f"{provider} (…{key[-4:]})",
                     request_ip(request))  # fmt: skip
    return {"provider": provider, "last4": key[-4:], "verified": verified}


@router.delete("/account/provider-keys/{provider}")
async def delete_provider_key(request: Request, provider: str, ws: Workspace) -> dict[str, str]:
    repo, _vault, scopes = _state(request)
    _limit(request, ws.tenant.id)
    if not await repo.delete_provider_key(ws.tenant.id, provider):
        raise GatewayError(404, "not_found", "no key stored for that provider")
    scopes.invalidate(ws.tenant.id)
    await repo.audit(
        ws.tenant.id, ws.user.email, "provider_key.removed", provider, request_ip(request)
    )
    return {"status": "deleted"}


# --- visibility -------------------------------------------------------------------------------


@router.get("/account/audit")
async def audit_log(request: Request, ws: Workspace) -> dict[str, Any]:
    repo, _v, _s = _state(request)
    events = await repo.audit_log(ws.tenant.id, 100)
    return {
        "events": [
            {"ts": e.ts, "actor": e.actor, "action": e.action, "detail": e.detail, "ip": e.ip}
            for e in events
        ]
    }


@router.get("/account/overview")
async def account_overview(
    request: Request, ws: Workspace, range: Annotated[Range, Query()] = "24h"
) -> dict[str, Any]:
    repo, _vault, _scopes = _state(request)
    window_s, bucket_s = _RANGES[range]
    usage: UsageRepo = request.app.state.usage
    now = time.time()
    rows = await usage.since(now - window_s, key_id=ws.tenant.id)
    catalog = request.app.state.gateway.catalog
    keys = await repo.provider_keys(ws.tenant.id)
    enabled = [m for m in catalog.models.values() if m.enabled and m.provider in keys]
    return build_overview(rows, catalog, enabled, now=now, window_s=window_s, bucket_s=bucket_s)


@router.get("/account/requests")
async def account_requests(
    request: Request,
    ws: Workspace,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Literal["ok", "error"] | None = None,
) -> dict[str, Any]:
    usage: UsageRepo = request.app.state.usage
    rows, total = await usage.page(limit, offset, status, key_id=ws.tenant.id)
    return {
        "total": total,
        "items": [
            {
                "id": r.id, "ts": r.ts, "requested_model": r.requested_model, "model": r.model,
                "provider": r.provider, "status": r.status, "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens, "latency_ms": r.latency_ms,
                "shadow_cost_usd": r.shadow_cost_usd, "attempts": r.attempts,
                "route_reason": r.route_reason, "cache_status": r.cache_status,
            }
            for r in rows
        ],
    }  # fmt: skip


@router.post("/account/chat", response_model=None)
async def account_chat(
    request: Request, body: ChatRequest, ws: Workspace
) -> JSONResponse | StreamingResponse:
    """Dashboard playground, routed through this workspace's own provider keys."""
    _repo, _vault, scopes = _state(request)
    scope = await scopes.get(ws.tenant.id)
    result: JSONResponse | StreamingResponse = await request.app.state.run_chat(
        body, request, ws.tenant.id, scope
    )
    return result
