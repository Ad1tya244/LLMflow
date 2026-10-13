"""Routing policy: pure function from (request analysis, candidates, state) to a plan.

filter (context, quota, privacy) -> cheapest model meeting the required quality ->
ordered fallback chain. Deterministic and side-effect free so it is easy to test and
every decision can be explained via ``RoutePlan.reason``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from llmflow.catalog import ModelSpec
from llmflow.providers.quota import QuotaTracker
from llmflow.routing.analyzer import Analysis

Quality = Literal["low", "balanced", "high"]

_DEFAULT_COMPLETION_TOKENS = 256


@dataclass(frozen=True, slots=True)
class RouterParams:
    """Tunable constants of the routing policy: ``required = base[quality] + span * difficulty``.

    The defaults are hand-set. ``python -m llmflow.bench calibrate`` can produce a versioned
    file (``config/routing.json``) chosen from measured outcomes; see ``load_router_params``.
    """

    base_low: float = 0.2
    base_balanced: float = 0.3
    base_high: float = 0.5
    span: float = 0.5
    version: str = "default"

    def base(self, quality: Quality) -> float:
        return {"low": self.base_low, "balanced": self.base_balanced, "high": self.base_high}[
            quality
        ]


DEFAULT_PARAMS = RouterParams()


@dataclass(frozen=True, slots=True)
class RoutePlan:
    chain: tuple[ModelSpec, ...]
    reason: str
    required_quality: float
    degraded: bool = False


def required_quality(
    difficulty: float, quality: Quality, params: RouterParams = DEFAULT_PARAMS
) -> float:
    return min(1.0, params.base(quality) + difficulty * params.span)


def plan_route(
    analysis: Analysis,
    candidates: list[ModelSpec],
    quota: QuotaTracker,
    *,
    quality: Quality = "balanced",
    strict_privacy: bool = False,
    untrusted_providers: frozenset[str] = frozenset(),
    max_tokens: int | None = None,
    params: RouterParams = DEFAULT_PARAMS,
) -> RoutePlan:
    needed = required_quality(analysis.difficulty, quality, params)
    completion = max_tokens or _DEFAULT_COMPLETION_TOKENS

    eligible = [
        m
        for m in candidates
        if m.context_window >= analysis.needs_tokens
        and quota.allows(m, analysis.needs_tokens)
        and not (strict_privacy and m.provider in untrusted_providers)
    ]
    if not eligible:
        return RoutePlan(
            (), "no eligible model (context, quota, health, or privacy filters)", needed
        )

    def cost(m: ModelSpec) -> float:
        return m.shadow_cost(analysis.prompt_tokens_est, completion)

    good = sorted(
        (m for m in eligible if m.quality >= needed),
        key=lambda m: (cost(m), -quota.headroom(m), -m.quality),
    )
    rest = sorted((m for m in eligible if m.quality < needed), key=lambda m: -m.quality)

    if good:
        top = good[0]
        reason = (
            f"difficulty={analysis.difficulty:.2f} needs quality>={needed:.2f}; "
            f"cheapest eligible is {top.id} (est ${cost(top):.6f})"
        )
        return RoutePlan(tuple(good + rest), reason, needed)
    reason = (
        f"difficulty={analysis.difficulty:.2f} needs quality>={needed:.2f}; "
        f"none available, degraded to best eligible {rest[0].id}"
    )
    return RoutePlan(tuple(rest), reason, needed, degraded=True)
