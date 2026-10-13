"""HTTP layer: OpenAI-compatible endpoints, auth, error mapping, app wiring."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from llmflow.api.account import public as public_router
from llmflow.api.account import router as account_router
from llmflow.api.admin import router as admin_router
from llmflow.api.auth import Authenticator
from llmflow.api.auth_routes import router as auth_router
from llmflow.api.deps import ClientCaller, client_ip
from llmflow.api.middleware import BodyLimitMiddleware, SecurityHeadersMiddleware
from llmflow.api.sessions import MfaChallengeStore, SessionStore
from llmflow.budget import BudgetGuard, Spend, utc_day_start
from llmflow.cache import ResponseCache
from llmflow.catalog import Catalog, ProviderSpec, environment, load_catalog
from llmflow.core.config import Settings
from llmflow.core.errors import GatewayError
from llmflow.core.ratelimit import SlidingWindowLimiter
from llmflow.providers.base import Provider
from llmflow.providers.openai_compat import OpenAICompatibleProvider
from llmflow.providers.quota import QuotaTracker
from llmflow.schemas import ChatRequest
from llmflow.security.vault import KeyVault, VaultError
from llmflow.service import AUTO_MODEL, Gateway, RouteMeta, Scope
from llmflow.storage.tenants import TenantRepo
from llmflow.storage.usage import UsageRepo
from llmflow.tenancy import TenantScopes

log = logging.getLogger(__name__)

_EXPOSED_HEADERS = [
    "x-llmflow-model",
    "x-llmflow-provider",
    "x-llmflow-attempts",
    "x-llmflow-route-reason",
    "x-llmflow-shadow-cost-usd",
    "x-llmflow-cache",
    "retry-after",
]


def _header_safe(value: str) -> str:
    return "".join(ch if ch.isprintable() and ord(ch) < 127 else "?" for ch in value)[:300]


def _meta_headers(meta: RouteMeta) -> dict[str, str]:
    headers = {
        "x-llmflow-model": _header_safe(meta.model),
        "x-llmflow-provider": _header_safe(meta.provider),
        "x-llmflow-attempts": str(meta.attempts),
        "x-llmflow-route-reason": _header_safe(meta.reason),
        "x-llmflow-cache": meta.cache,
    }
    if meta.shadow_cost_usd is not None:
        headers["x-llmflow-shadow-cost-usd"] = f"{meta.shadow_cost_usd:.8f}"
    return headers


def validate_limits(body: ChatRequest, settings: Settings) -> None:
    """Reject oversized or abusive requests before any provider is contacted."""
    if len(body.messages) > settings.max_messages:
        raise GatewayError(
            422, "invalid_request_error", f"too many messages (max {settings.max_messages})"
        )
    chars = 0
    for m in body.messages:
        if isinstance(m.content, str):
            chars += len(m.content)
        elif isinstance(m.content, list):
            chars += sum(len(str(part.get("text", ""))) for part in m.content)
    if chars > settings.max_prompt_chars:
        raise GatewayError(
            413,
            "request_too_large",
            f"prompt too large (max {settings.max_prompt_chars} characters)",
        )
    extra = body.model_extra or {}
    for name, value in (
        ("max_tokens", body.max_tokens),
        ("max_completion_tokens", extra.get("max_completion_tokens")),
    ):
        if isinstance(value, int) and value > settings.max_tokens_cap:
            raise GatewayError(
                422,
                "invalid_request_error",
                f"{name} exceeds the limit of {settings.max_tokens_cap}",
            )
    n = extra.get("n")
    if isinstance(n, int) and n > 1:
        raise GatewayError(422, "invalid_request_error", "n > 1 is not supported")


def create_app(
    settings: Settings | None = None,
    *,
    catalog: Catalog | None = None,
    providers: dict[str, Provider] | None = None,
    env: dict[str, str] | None = None,
    provider_factory: Callable[[ProviderSpec, str], Provider] | None = None,
) -> FastAPI:
    """Application factory. Injection points exist for tests; production passes nothing."""
    settings = settings or Settings()
    if not settings.auth_disabled and not settings.key_list:
        raise RuntimeError("LLMFLOW_API_KEYS is empty; set it or LLMFLOW_AUTH_DISABLED=true (dev)")
    weak = [
        k
        for k in (*settings.key_list, *settings.admin_key_list)
        if len(k) < settings.min_key_length
    ]
    if weak and not settings.auth_disabled:
        raise RuntimeError(
            f"API keys must be at least {settings.min_key_length} characters; "
            'generate one with: python -c "import secrets;print(secrets.token_urlsafe(32))"'
        )
    vault: KeyVault | None = None
    if settings.master_key_list:
        try:
            vault = KeyVault(settings.master_key_list)
        except VaultError as exc:
            raise RuntimeError(str(exc)) from exc
    overlap = set(settings.key_list) & set(settings.admin_key_list)
    if overlap:
        raise RuntimeError("an admin key must not also be a client API key")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cat = catalog or load_catalog(settings.catalog_path)
        environ = env if env is not None else dict(environment())
        enabled = cat.enabled_models(environ)
        client = httpx.AsyncClient(timeout=settings.request_timeout_s)
        built: dict[str, Provider] = providers or {
            pid: OpenAICompatibleProvider(spec, environ[spec.api_key_env], client)
            for pid, spec in cat.providers.items()
            if environ.get(spec.api_key_env, "").strip()
        }
        usage = UsageRepo(settings.database_url)
        await usage.init()
        app.state.http = client
        app.state.tenants = TenantRepo(usage.sessions) if vault is not None else None
        app.state.vault = vault
        app.state.tenant_scopes = (
            TenantScopes(
                cat,
                app.state.tenants,
                vault,
                provider_factory or (lambda spec, key: OpenAICompatibleProvider(spec, key, client)),
            )
            if vault is not None
            else None
        )
        budget = BudgetGuard(settings.daily_budget_usd, settings.daily_token_budget)
        totals = await usage.daily_totals(utc_day_start(time.time()))
        budget.hydrate({k: Spend(t, c) for k, (t, c) in totals.items()})
        cache = ResponseCache(settings.cache_ttl_s, settings.cache_max_entries)
        app.state.gateway = Gateway(
            cat, enabled, built, QuotaTracker(), usage,
            budget=budget, cache=cache, max_attempts=settings.max_attempts,
        )  # fmt: skip
        app.state.usage = usage
        if not enabled:
            log.warning("no provider API keys configured; every request will return 503")
        try:
            yield
        finally:
            await client.aclose()
            await usage.close()

    app = FastAPI(
        title="LLMFlow",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.settings = settings
    app.state.auth = Authenticator(settings.key_list, disabled=settings.auth_disabled, scope="api")
    app.state.admin_auth = Authenticator(
        settings.admin_key_list, disabled=settings.auth_disabled, scope="admin"
    )
    app.state.auth_limiter = SlidingWindowLimiter(settings.auth_fail_limit_per_min)
    app.state.key_limiter = SlidingWindowLimiter(settings.rate_limit_rpm)
    app.state.trust_forwarded = settings.trust_forwarded_for
    app.state.sessions = SessionStore(settings.session_idle_s, settings.session_max_age_s)
    app.state.mfa_challenges = MfaChallengeStore()
    app.state.signup_limiter = SlidingWindowLimiter(settings.signup_limit_per_hour, 3600.0)
    app.state.tenants = None
    app.state.tenant_scopes = None
    app.state.vault = None

    @app.exception_handler(GatewayError)
    async def _gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"type": exc.error_type, "message": exc.message}},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Report where and why, never echo the submitted values back.
        problems = [{"loc": [str(p) for p in e["loc"]], "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_request_error",
                    "message": "invalid request",
                    "details": problems,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": {"type": "internal_error", "message": "internal server error"}},
        )

    # Added last = outermost: headers wrap everything, body cap runs before parsing.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["authorization", "content-type", "x-llmflow-csrf"],
        allow_credentials=True,
        expose_headers=_EXPOSED_HEADERS,
        max_age=600,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(admin_router)
    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(public_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    async def scope_for(request: Request, caller: ClientCaller) -> Scope | None:
        if caller.tenant is None:
            return None
        scopes: TenantScopes | None = request.app.state.tenant_scopes
        if scopes is None:
            raise GatewayError(503, "byok_not_configured", "workspaces are not enabled")
        return await scopes.get(caller.tenant.id)

    @app.get("/v1/models")
    async def models(request: Request, caller: ClientCaller) -> dict[str, Any]:
        gw: Gateway = request.app.state.gateway
        scope = await scope_for(request, caller) or gw.default_scope
        data = [{"id": AUTO_MODEL, "object": "model", "owned_by": "llmflow"}]
        data += [
            {"id": m.id, "object": "model", "owned_by": m.provider, "tier": m.tier.name.lower()}
            for m in scope.enabled
        ]
        return {"object": "list", "data": data}

    async def run_chat(
        body: ChatRequest, request: Request, key_id: str, scope: Scope | None = None
    ) -> JSONResponse | StreamingResponse:
        gw: Gateway = request.app.state.gateway
        wait = request.app.state.key_limiter.acquire(key_id)
        if wait is not None:
            raise GatewayError(
                429, "rate_limited", "request rate limit exceeded",
                {"Retry-After": str(int(wait) + 1)},
            )  # fmt: skip
        validate_limits(body, settings)
        log.info(
            "chat key=%s ip=%s model=%r stream=%s",
            key_id,
            client_ip(request, settings.trust_forwarded_for),
            body.model,
            body.stream,
        )
        if body.stream:
            result = await gw.stream(body, key_id, scope)

            async def sse() -> AsyncIterator[bytes]:
                async for payload in result.chunks:
                    yield f"data: {payload}\n\n".encode()

            return StreamingResponse(
                sse(), media_type="text/event-stream", headers=_meta_headers(result.meta)
            )
        done = await gw.complete(body, key_id, scope)
        return JSONResponse(done.body, headers=_meta_headers(done.meta))

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(
        body: ChatRequest, request: Request, caller: ClientCaller
    ) -> JSONResponse | StreamingResponse:
        return await run_chat(body, request, caller.key_id, await scope_for(request, caller))

    app.state.run_chat = run_chat
    return app
