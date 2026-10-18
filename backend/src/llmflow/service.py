"""Gateway service: plan a route, execute with bounded fallback, record usage."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from llmflow.budget import BudgetGuard
from llmflow.cache import ResponseCache, cache_key, is_cacheable
from llmflow.catalog import Catalog, ModelSpec
from llmflow.core.errors import GatewayError, ProviderError, ProviderErrorKind
from llmflow.providers.base import Provider
from llmflow.providers.quota import QuotaTracker
from llmflow.routing.analyzer import analyze
from llmflow.routing.policy import DEFAULT_PARAMS, RoutePlan, RouterParams, plan_route
from llmflow.schemas import ChatRequest, Usage
from llmflow.storage.usage import RequestLog, UsageRepo

log = logging.getLogger(__name__)

AUTO_MODEL = "auto"
_COOLDOWN_S = {
    ProviderErrorKind.RATE_LIMITED: 30.0,
    ProviderErrorKind.SERVER: 15.0,
    ProviderErrorKind.TIMEOUT: 15.0,
    ProviderErrorKind.NOT_FOUND: 300.0,
}


@dataclass(frozen=True, slots=True)
class RouteMeta:
    model: str
    provider: str
    reason: str
    attempts: int
    shadow_cost_usd: float | None
    cache: str = "none"  # none | miss | hit


@dataclass(frozen=True, slots=True)
class ChatResult:
    body: dict[str, Any]
    meta: RouteMeta


@dataclass(frozen=True, slots=True)
class StreamResult:
    chunks: AsyncIterator[str]
    meta: RouteMeta


@dataclass(slots=True)
class Scope:
    """What one caller may route through: its models, provider clients and quota state.

    The operator's static keys use the gateway's default scope; each tenant gets a scope
    built from that tenant's own (decrypted) provider keys, so nothing is shared."""

    enabled: list[ModelSpec]
    providers: dict[str, Provider]
    quota: QuotaTracker


class Gateway:
    def __init__(
        self,
        catalog: Catalog,
        enabled: list[ModelSpec],
        providers: dict[str, Provider],
        quota: QuotaTracker,
        usage: UsageRepo,
        *,
        budget: BudgetGuard | None = None,
        cache: ResponseCache | None = None,
        max_attempts: int = 3,
        router_params: RouterParams = DEFAULT_PARAMS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._catalog = catalog
        self._enabled = enabled
        self._providers = providers
        self._quota = quota
        self._default = Scope(enabled, providers, quota)
        self._usage = usage
        self._budget = budget if budget is not None else BudgetGuard(None, None)
        self._cache = cache if cache is not None else ResponseCache(0, 1)
        self._max_attempts = max_attempts
        self._params = router_params
        self._clock = clock
        self._untrusted = frozenset(p.id for p in catalog.providers.values() if p.trains_on_data)

    @property
    def default_scope(self) -> Scope:
        return self._default

    @property
    def budget(self) -> BudgetGuard:
        return self._budget

    @property
    def cache(self) -> ResponseCache:
        return self._cache

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    @property
    def quota(self) -> QuotaTracker:
        return self._quota

    @property
    def enabled_models(self) -> list[ModelSpec]:
        return self._enabled

    def _plan(self, request: ChatRequest, scope: Scope) -> RoutePlan:
        if not scope.enabled:
            raise GatewayError(
                503,
                "no_provider_keys",
                "no provider keys are configured for this workspace; add one in the dashboard "
                "(Providers) or with PUT /account/provider-keys/{provider}",
            )
        analysis = analyze(request)
        opts = request.llmflow
        plan = plan_route(
            analysis,
            [m for m in scope.enabled if m.auto_route],  # pin-only models are skipped here
            self._quota,
            quality=opts.quality,
            strict_privacy=opts.privacy == "strict",
            untrusted_providers=self._untrusted,
            max_tokens=request.max_tokens,
            params=self._params,
        )
        if request.model != AUTO_MODEL:
            pinned = next((m for m in scope.enabled if m.id == request.model), None)
            if pinned is None:
                raise GatewayError(
                    404,
                    "model_not_found",
                    f"model {request.model!r} is unknown, or its provider has no key or is paused",
                )
            tail = tuple(m for m in plan.chain if m.id != pinned.id)
            plan = RoutePlan(
                (pinned, *tail), f"pinned to {pinned.id}", plan.required_quality, plan.degraded
            )
        if not plan.chain:
            raise GatewayError(503, "no_available_model", plan.reason)
        # Naming a model means "this one": never swap in another model (possibly at a different
        # provider, with different data terms) unless the caller explicitly allowed fallback.
        pinned_without_fallback = (
            request.model != AUTO_MODEL and "fallback" not in opts.model_fields_set
        )
        if not opts.fallback or pinned_without_fallback:
            plan = RoutePlan(plan.chain[:1], plan.reason, plan.required_quality, plan.degraded)
        return plan

    def _on_failure(self, spec: ModelSpec, err: ProviderError, scope: Scope) -> None:
        if err.kind is ProviderErrorKind.AUTH:
            log.error("provider %s rejected credentials; disabling", spec.provider)
            scope.quota.disable_provider(spec.provider)
        elif err.kind in _COOLDOWN_S:
            seconds = err.retry_after if err.retry_after is not None else _COOLDOWN_S[err.kind]
            scope.quota.cool_down(spec.id, seconds)
        log.warning("model %s failed (%s): %s", spec.id, err.kind.value, err)

    async def _log(
        self,
        request: ChatRequest,
        key_id: str,
        *,
        spec: ModelSpec | None,
        usage: Usage,
        latency_ms: float,
        attempts: int,
        reason: str,
        ok: bool,
        cache_status: str = "none",
        charge: bool = True,
    ) -> float:
        cost = spec.shadow_cost(usage.prompt_tokens, usage.completion_tokens) if spec else 0.0
        if charge and ok:
            self._budget.record(key_id, usage.prompt_tokens + usage.completion_tokens, cost)
        try:
            await self._usage.record(
                RequestLog(
                    ts=self._clock(),
                    key_id=key_id,
                    requested_model=request.model,
                    model=spec.id if spec else None,
                    provider=spec.provider if spec else None,
                    status="ok" if ok else "error",
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    latency_ms=latency_ms,
                    shadow_cost_usd=cost,
                    attempts=attempts,
                    route_reason=reason[:512],
                    cache_status=cache_status,
                )
            )
        except Exception:
            log.exception("failed to record usage")
        return cost

    def _exhausted(self, notes: list[str]) -> GatewayError:
        detail = "; ".join(notes) or "no model could be tried"
        return GatewayError(503, "all_providers_failed", f"no model could answer: {detail}")

    async def complete(
        self, request: ChatRequest, key_id: str, scope: Scope | None = None
    ) -> ChatResult:
        scope = scope or self._default
        self._budget.check(key_id)
        ckey = cache_key(key_id, request) if self._cache.enabled and is_cacheable(request) else None
        if ckey is not None and (hit := self._cache.get(ckey)) is not None:
            spec = self._catalog.models.get(hit.model)
            usage = Usage(prompt_tokens=hit.prompt_tokens, completion_tokens=hit.completion_tokens)
            reason = f"served from cache (originally {hit.model})"
            await self._log(
                request,
                key_id,
                spec=spec,
                usage=usage,
                latency_ms=0.0,
                attempts=0,
                reason=reason,
                ok=True,
                cache_status="hit",
                charge=False,
            )
            meta = RouteMeta(hit.model, hit.provider, reason, 0, 0.0, "hit")
            return ChatResult(hit.body, meta)
        plan = self._plan(request, scope)
        started = time.perf_counter()
        status = "miss" if ckey is not None else "none"
        errors: list[str] = []
        attempts = 0
        for spec in plan.chain:
            if attempts >= self._max_attempts:
                break
            if not scope.quota.allows(spec):
                errors.append(f"{spec.id} skipped: {scope.quota.why_blocked(spec)}")
                continue
            attempts += 1
            try:
                done = await scope.providers[spec.provider].chat(
                    spec, request.upstream_payload(spec.upstream_model)
                )
            except ProviderError as err:
                self._on_failure(spec, err, scope)
                errors.append(_failure_note(spec, err))
                if not err.fallback_eligible:
                    await self._log(
                        request,
                        key_id,
                        spec=spec,
                        usage=Usage(),
                        latency_ms=0,
                        attempts=attempts,
                        reason=plan.reason,
                        ok=False,
                    )
                    raise GatewayError(400, "invalid_request_error", err.client_message) from err
                continue
            usage = done.usage
            scope.quota.record(spec, usage.prompt_tokens + usage.completion_tokens)
            reason = _with_notes(plan.reason, errors)
            cost = await self._log(
                request,
                key_id,
                spec=spec,
                usage=usage,
                latency_ms=done.latency_ms,
                attempts=attempts,
                reason=reason,
                ok=True,
                cache_status=status,
            )
            if ckey is not None:
                self._cache.put(
                    ckey,
                    done.body,
                    spec.id,
                    spec.provider,
                    (usage.prompt_tokens, usage.completion_tokens),
                )
            meta = RouteMeta(spec.id, spec.provider, reason, attempts, cost, status)
            return ChatResult(done.body, meta)
        await self._log(
            request,
            key_id,
            spec=None,
            usage=Usage(),
            latency_ms=(time.perf_counter() - started) * 1000,
            attempts=attempts,
            reason=plan.reason,
            ok=False,
        )
        raise self._exhausted(errors)

    async def stream(
        self, request: ChatRequest, key_id: str, scope: Scope | None = None
    ) -> StreamResult:
        scope = scope or self._default
        self._budget.check(key_id)
        plan = self._plan(request, scope)
        errors: list[str] = []
        attempts = 0
        for spec in plan.chain:
            if attempts >= self._max_attempts:
                break
            if not scope.quota.allows(spec):
                errors.append(f"{spec.id} skipped: {scope.quota.why_blocked(spec)}")
                continue
            attempts += 1
            upstream = scope.providers[spec.provider].stream(
                spec, request.upstream_payload(spec.upstream_model)
            )
            try:
                first = await anext(upstream)
            except StopAsyncIteration:
                await _aclose(upstream)
                errors.append(f"{spec.id} failed (empty stream)")
                scope.quota.cool_down(spec.id, _COOLDOWN_S[ProviderErrorKind.SERVER])
                continue
            except ProviderError as err:
                await _aclose(upstream)
                self._on_failure(spec, err, scope)
                errors.append(_failure_note(spec, err))
                if not err.fallback_eligible:
                    raise GatewayError(400, "invalid_request_error", err.client_message) from err
                continue
            plan = RoutePlan(
                plan.chain, _with_notes(plan.reason, errors), plan.required_quality, plan.degraded
            )
            meta = RouteMeta(spec.id, spec.provider, plan.reason, attempts, None)
            return StreamResult(
                self._relay(request, key_id, spec, plan, attempts, first, upstream, scope), meta
            )
        await self._log(
            request,
            key_id,
            spec=None,
            usage=Usage(),
            latency_ms=0,
            attempts=attempts,
            reason=plan.reason,
            ok=False,
        )
        raise self._exhausted(errors)

    async def _relay(
        self,
        request: ChatRequest,
        key_id: str,
        spec: ModelSpec,
        plan: RoutePlan,
        attempts: int,
        first: str,
        rest: AsyncIterator[str],
        scope: Scope,
    ) -> AsyncIterator[str]:
        started = time.perf_counter()
        usage = Usage()
        ok = True
        try:
            payloads = _chain(first, rest)
            async for payload in payloads:
                if '"usage"' in payload:
                    usage = _usage_from_chunk(payload) or usage
                yield payload
        except ProviderError as err:
            # Mid-stream failure: cannot fall back after bytes were sent; surface in-band.
            ok = False
            self._on_failure(spec, err, scope)
            yield json.dumps({"error": {"type": err.kind.value, "message": err.client_message}})
        finally:
            if usage.prompt_tokens or usage.completion_tokens:
                scope.quota.record(spec, usage.prompt_tokens + usage.completion_tokens)
            await self._log(
                request,
                key_id,
                spec=spec,
                usage=usage,
                latency_ms=(time.perf_counter() - started) * 1000,
                attempts=attempts,
                reason=plan.reason,
                ok=ok,
            )


def _failure_note(spec: ModelSpec, err: ProviderError) -> str:
    return f"{spec.id} failed ({err.kind.value}: {err.client_message[:120]})"


def _with_notes(reason: str, notes: list[str]) -> str:
    """Append what was skipped or failed before the answering model, so the route is honest."""
    return f"{reason}; before that: {'; '.join(notes)}" if notes else reason


async def _aclose(it: AsyncIterator[str]) -> None:
    close = getattr(it, "aclose", None)
    if close is not None:
        await close()


async def _chain(first: str, rest: AsyncIterator[str]) -> AsyncIterator[str]:
    yield first
    async for item in rest:
        yield item


def _usage_from_chunk(payload: str) -> Usage | None:
    try:
        raw = json.loads(payload).get("usage")
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    return Usage(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        completion_tokens=int(raw.get("completion_tokens") or 0),
    )
