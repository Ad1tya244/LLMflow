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

_BASE_QUALITY: dict[Quality, float] = {"low": 0.2, "balanced": 0.3, "high": 0.5}
_DIFFICULTY_SPAN = 0.5
_DEFAULT_COMPLETION_TOKENS = 256


@dataclass(frozen=True, slots=True)
class RoutePlan:
    chain: tuple[ModelSpec, ...]
    reason: str
    required_quality: float
    degraded: bool = False


def required_quality(difficulty: float, quality: Quality) -> float:
    return min(1.0, _BASE_QUALITY[quality] + difficulty * _DIFFICULTY_SPAN)


def plan_route(
    analysis: Analysis,
    candidates: list[ModelSpec],
    quota: QuotaTracker,
    *,
    quality: Quality = "balanced",
    strict_privacy: bool = False,
    untrusted_providers: frozenset[str] = frozenset(),
    max_tokens: int | None = None,
) -> RoutePlan:
    needed = required_quality(analysis.difficulty, quality)
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
