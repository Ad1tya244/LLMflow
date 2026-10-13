"""Read-only analytics endpoints that back the dashboard."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request

from llmflow.api.deps import AdminPrincipal as Principal
from llmflow.catalog import Catalog, ModelSpec
from llmflow.core.errors import GatewayError
from llmflow.service import Gateway
from llmflow.storage.tenants import TenantRepo
from llmflow.storage.usage import RequestLog, UsageRepo

router = APIRouter(prefix="/admin", tags=["admin"])

Range = Literal["1h", "24h", "7d", "30d"]
# (window seconds, bucket seconds)
_RANGES: dict[str, tuple[int, int]] = {
    "1h": (3600, 60),
    "24h": (86_400, 1800),
    "7d": (7 * 86_400, 3600 * 4),
    "30d": (30 * 86_400, 86_400),
}


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]


@dataclass
class _Bucket:
    requests: int = 0
    errors: int = 0
    tokens: int = 0
    cost: float = 0.0
    small: int = 0
    medium: int = 0
    large: int = 0
    ref_cost: float = 0.0


def build_overview(
    rows: list[RequestLog],
    catalog: Catalog,
    enabled: list[ModelSpec],
    *,
    now: float,
    window_s: int,
    bucket_s: int,
) -> dict[str, Any]:
    tier_of = {m.id: m.tier.name.lower() for m in catalog.models.values()}
    pool = enabled or list(catalog.models.values())
    reference = max(pool, key=lambda m: m.quality) if pool else None

    start = now - window_s
    n_buckets = window_s // bucket_s
    buckets = [_Bucket() for _ in range(n_buckets)]
    per_model: dict[str, list[RequestLog]] = defaultdict(list)
    latencies: list[float] = []
    ref_cost = 0.0
    total_cost = 0.0
    cache_hits = 0
    cache_lookups = 0

    for row in rows:
        idx = min(n_buckets - 1, max(0, int((row.ts - start) // bucket_s)))
        b = buckets[idx]
        b.requests += 1
        tokens = row.prompt_tokens + row.completion_tokens
        if row.status != "ok":
            b.errors += 1
            continue
        b.tokens += tokens
        if row.cache_status == "hit":
            cache_hits += 1
        if row.cache_status in ("hit", "miss"):
            cache_lookups += 1
        b.cost += row.shadow_cost_usd
        total_cost += row.shadow_cost_usd
        latencies.append(row.latency_ms)
        if row.model:
            per_model[row.model].append(row)
            tier = tier_of.get(row.model)
            if tier in ("small", "medium", "large"):
                setattr(b, tier, getattr(b, tier) + 1)
        if reference:
            rc = reference.shadow_cost(row.prompt_tokens, row.completion_tokens)
            ref_cost += rc
            b.ref_cost += rc

    ok = len(latencies)
    total = len(rows)
    series = [
        {
            "ts": start + i * bucket_s,
            "requests": b.requests,
            "errors": b.errors,
            "tokens": b.tokens,
            "shadow_cost_usd": round(b.cost, 8),
            "reference_cost_usd": round(b.ref_cost, 8),
            "small": b.small,
            "medium": b.medium,
            "large": b.large,
        }
        for i, b in enumerate(buckets)
    ]
    by_model = [
        {
            "model": mid,
            "provider": catalog.models[mid].provider if mid in catalog.models else None,
            "tier": tier_of.get(mid),
            "requests": len(rs),
            "tokens": sum(r.prompt_tokens + r.completion_tokens for r in rs),
            "shadow_cost_usd": round(sum(r.shadow_cost_usd for r in rs), 8),
            "p50_latency_ms": percentile([r.latency_ms for r in rs], 50),
        }
        for mid, rs in sorted(per_model.items(), key=lambda kv: -len(kv[1]))
    ]
    return {
        "range_start": start,
        "bucket_s": bucket_s,
        "totals": {
            "requests": total,
            "errors": total - ok,
            "error_rate": (total - ok) / total if total else 0.0,
            "tokens": sum(b.tokens for b in buckets),
            "shadow_cost_usd": round(total_cost, 8),
            "p50_latency_ms": percentile(latencies, 50),
            "p95_latency_ms": percentile(latencies, 95),
            "cache_hits": cache_hits,
            "cache_lookups": cache_lookups,
            "cache_hit_rate": cache_hits / cache_lookups if cache_lookups else None,
            "reference_model": reference.id if reference else None,
            "reference_cost_usd": round(ref_cost, 8) if reference else None,
            "saved_vs_reference_usd": round(ref_cost - total_cost, 8) if reference else None,
        },
        "series": series,
        "by_model": by_model,
    }


@router.get("/overview")
async def overview(
    request: Request, _: Principal, range: Annotated[Range, Query()] = "24h"
) -> dict[str, Any]:
    window_s, bucket_s = _RANGES[range]
    gw: Gateway = request.app.state.gateway
    usage: UsageRepo = request.app.state.usage
    now = time.time()
    rows = await usage.since(now - window_s)
    return build_overview(
        rows, gw.catalog, gw.enabled_models, now=now, window_s=window_s, bucket_s=bucket_s
    )


@router.get("/requests")
async def requests_log(
    request: Request,
    _: Principal,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[Literal["ok", "error"] | None, Query()] = None,
) -> dict[str, Any]:
    usage: UsageRepo = request.app.state.usage
    rows, total = await usage.page(limit, offset, status)
    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "ts": r.ts,
                "requested_model": r.requested_model,
                "model": r.model,
                "provider": r.provider,
                "status": r.status,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "latency_ms": r.latency_ms,
                "shadow_cost_usd": r.shadow_cost_usd,
                "attempts": r.attempts,
                "route_reason": r.route_reason,
                "cache_status": r.cache_status,
            }
            for r in rows
        ],
    }


@router.get("/providers")
async def providers(request: Request, _: Principal) -> dict[str, Any]:
    gw: Gateway = request.app.state.gateway
    enabled = {m.id for m in gw.enabled_models}
    models = []
    for spec in gw.catalog.models.values():
        snap = gw.quota.snapshot(spec)
        models.append(
            {
                "id": spec.id,
                "provider": spec.provider,
                "upstream_model": spec.upstream_model,
                "tier": spec.tier.name.lower(),
                "quality_prior": spec.quality,
                "context_window": spec.context_window,
                "price_in": spec.price_in,
                "price_out": spec.price_out,
                "limits": spec.limits.model_dump(),
                "enabled": spec.id in enabled,
                "disabled_in_catalog": not spec.enabled,
                "rpm_used": snap.rpm_used,
                "rpd_used": snap.rpd_used,
                "tpd_used": snap.tpd_used,
                "cooldown_s": round(snap.cooldown_s, 1),
                "provider_disabled": snap.provider_disabled,
                "headroom": round(snap.headroom, 4),
            }
        )
    return {
        "providers": [
            {
                "id": p.id,
                "configured": any(m["enabled"] for m in models if m["provider"] == p.id),
                "trains_on_data": p.trains_on_data,
            }
            for p in gw.catalog.providers.values()
        ],
        "models": models,
    }


@router.get("/budgets")
async def budgets(request: Request, _: Principal) -> dict[str, Any]:
    gw: Gateway = request.app.state.gateway
    b = gw.budget
    return {
        "daily_budget_usd": b.daily_usd,
        "daily_token_budget": b.daily_tokens,
        "keys": [
            {"key_id": k, "tokens": s.tokens, "shadow_cost_usd": round(s.cost_usd, 8)}
            for k, s in sorted(b.snapshot().items(), key=lambda kv: -kv[1].cost_usd)
        ],
    }


@router.get("/config")
async def config(request: Request, _: Principal) -> dict[str, Any]:
    """Non-secret runtime configuration for display in the dashboard."""
    st = request.app.state.settings
    gw: Gateway = request.app.state.gateway
    cache = gw.cache
    return {
        "rate_limit_rpm": st.rate_limit_rpm,
        "max_body_bytes": st.max_body_bytes,
        "max_tokens_cap": st.max_tokens_cap,
        "max_attempts": st.max_attempts,
        "cache": {
            "enabled": cache.enabled,
            "ttl_s": st.cache_ttl_s,
            "entries": len(cache),
            "max_entries": st.cache_max_entries,
            "hits": cache.hits,
            "misses": cache.misses,
        },
        "docs_enabled": st.enable_docs,
    }


def read_benchmarks(directory: Path, name: str | None) -> dict[str, Any]:
    files = sorted(directory.glob("*.report.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    available = {f.name.removesuffix(".report.json"): f for f in files}
    selected = name if name in available else (next(iter(available), None))
    report = json.loads(available[selected].read_text()) if selected else None
    return {"available": list(available), "selected": selected, "report": report}


@router.get("/benchmarks")
async def benchmarks(
    request: Request,
    _: Principal,
    name: Annotated[str | None, Query(max_length=100)] = None,
) -> dict[str, Any]:
    """Measured benchmark reports produced by ``python -m llmflow.bench``.

    ``name`` is matched against the files that exist in the reports directory (never joined
    into a path), so it cannot be used to read arbitrary files.
    """
    return read_benchmarks(request.app.state.settings.benchmarks_dir, name)


# --- workspaces (operator tooling: no secrets, no member data beyond the owner email) ----


def _repo(request: Request) -> TenantRepo:
    repo: TenantRepo | None = request.app.state.tenants
    if repo is None:
        raise GatewayError(
            503, "byok_not_configured", "set LLMFLOW_MASTER_KEY to enable workspaces"
        )
    return repo


@router.get("/tenants")
async def list_tenants(request: Request, _: Principal) -> dict[str, Any]:
    repo = _repo(request)
    gw: Gateway = request.app.state.gateway
    spend = gw.budget.snapshot()
    out = []
    for t, owner in await repo.list_workspaces():
        keys = await repo.provider_keys(t.id)
        s = spend.get(t.id)
        out.append(
            {
                "id": t.id,
                "name": t.name,
                "owner_email": owner,
                "created_at": t.created_at,
                "disabled": t.disabled,
                "providers": sorted(keys),
                "tokens_today": s.tokens if s else 0,
                "shadow_cost_today_usd": round(s.cost_usd, 8) if s else 0.0,
            }
        )
    return {"tenants": out}


@router.post("/tenants/{tenant_id}/{action}")
async def set_tenant_state(
    request: Request, tenant_id: str, action: Literal["disable", "enable"], _: Principal
) -> dict[str, str]:
    if not await _repo(request).set_disabled(tenant_id, action == "disable"):
        raise GatewayError(404, "not_found", "unknown workspace")
    scopes = request.app.state.tenant_scopes
    if scopes is not None:
        scopes.invalidate(tenant_id)
    return {"status": f"{action}d"}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(request: Request, tenant_id: str, _: Principal) -> dict[str, str]:
    if not await _repo(request).delete_workspace(tenant_id):
        raise GatewayError(404, "not_found", "unknown workspace")
    scopes = request.app.state.tenant_scopes
    if scopes is not None:
        scopes.invalidate(tenant_id)
    return {"status": "deleted"}
