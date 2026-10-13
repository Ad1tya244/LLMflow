"""Router evaluation by counterfactual replay, plus parameter calibration.

Because fixed-model runs at temperature 0 give each item's outcome under *every* model, any
routing policy can be evaluated offline by looking up the outcome of the model it would have
picked: no extra API calls, no model is run or trained. Calibration is a one-parameter search
over the policy's base quality level, chosen by counting.

Replayed numbers are labelled REPLAY: they describe what the policy would have achieved on the
measured outcomes, not a separate live run.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llmflow.bench.suite import load_suite
from llmflow.catalog import ModelSpec
from llmflow.providers.quota import QuotaTracker
from llmflow.routing.analyzer import Analysis, analyze
from llmflow.routing.policy import DEFAULT_PARAMS, Quality, RouterParams, plan_route
from llmflow.schemas import ChatRequest, Message


@dataclass(frozen=True, slots=True)
class Outcome:
    passed: bool
    cost: float


@dataclass(slots=True)
class EvalItem:
    key: str
    suite: str
    label: str
    analysis: Analysis
    outcomes: dict[str, Outcome] = field(default_factory=dict)

    def split(self) -> str:
        """Deterministic 50/50 split that does not depend on dict/file order."""
        return "train" if zlib.crc32(self.key.encode()) % 2 == 0 else "holdout"


def load_items(
    pairs: dict[str, tuple[Path, Path]],
    *,
    feature_max_tokens: int | None = None,
    analyzer: str = "v2",
) -> list[EvalItem]:
    """``pairs``: suite name -> (suite jsonl, results jsonl). Results use ``always-*`` rows."""
    items: dict[str, EvalItem] = {}
    for suite, (suite_path, results_path) in pairs.items():
        by_id: dict[str, str] = {}
        for it in load_suite(suite_path):
            req = ChatRequest(
                messages=[Message(role="user", content=it.prompt)], max_tokens=feature_max_tokens
            )
            key = f"{suite}:{it.id}"
            by_id[it.id] = key
            items[key] = EvalItem(key, suite, it.difficulty, analyze(req, analyzer))
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not row["strategy"].startswith("always-") or row.get("status") != "ok":
                continue
            found = by_id.get(row["item_id"])
            if found and row.get("model"):
                items[found].outcomes[row["model"]] = Outcome(
                    bool(row["passed"]), row["shadow_cost_usd"]
                )
    return list(items.values())


def complete_items(items: list[EvalItem], models: list[str]) -> list[EvalItem]:
    return [i for i in items if all(m in i.outcomes for m in models)]


# --- metrics ------------------------------------------------------------------------------------


@dataclass(slots=True)
class PolicyResult:
    n: int
    accuracy: float
    cost: float
    share_large: float
    escalation_recall: float | None
    escalation_precision: float | None


def auc(scores: list[float], positives: list[bool]) -> float | None:
    """Probability a random positive outranks a random negative (ties count half)."""
    pos = [s for s, p in zip(scores, positives, strict=True) if p]
    neg = [s for s, p in zip(scores, positives, strict=True) if not p]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def replay(
    items: list[EvalItem],
    candidates: list[ModelSpec],
    small_id: str,
    large_id: str,
    params: RouterParams,
    quality: Quality = "balanced",
) -> PolicyResult:
    passed = cost = 0.0
    to_large = hit = needed = 0
    n = 0
    for it in items:
        plan = plan_route(it.analysis, candidates, QuotaTracker(), quality=quality, params=params)
        if not plan.chain:
            continue
        chosen = plan.chain[0].id
        out = it.outcomes.get(chosen)
        if out is None:
            continue
        n += 1
        passed += out.passed
        cost += out.cost
        needs_large = (not it.outcomes[small_id].passed) and it.outcomes[large_id].passed
        needed += needs_large
        if chosen == large_id:
            to_large += 1
            hit += needs_large
    return PolicyResult(
        n=n,
        accuracy=passed / n if n else 0.0,
        cost=cost,
        share_large=to_large / n if n else 0.0,
        escalation_recall=hit / needed if needed else None,
        escalation_precision=hit / to_large if to_large else None,
    )


def fixed(items: list[EvalItem], model_id: str) -> PolicyResult:
    n = len(items)
    return PolicyResult(
        n=n,
        accuracy=sum(i.outcomes[model_id].passed for i in items) / n if n else 0.0,
        cost=sum(i.outcomes[model_id].cost for i in items),
        share_large=0.0,
        escalation_recall=None,
        escalation_precision=None,
    )


def oracle(items: list[EvalItem]) -> PolicyResult:
    """Cheapest passing model per item (cheapest overall when none passes)."""
    passed = cost = 0.0
    for it in items:
        ranked = sorted(it.outcomes.values(), key=lambda o: o.cost)
        winner = next((o for o in ranked if o.passed), ranked[0])
        passed += winner.passed
        cost += winner.cost
    n = len(items)
    return PolicyResult(n, passed / n if n else 0.0, cost, 0.0, None, None)


# --- calibration --------------------------------------------------------------------------------


@dataclass(slots=True)
class Calibration:
    params: RouterParams
    train: PolicyResult
    holdout: PolicyResult
    frontier: list[dict[str, float]]
    tolerance: float


def calibrate(
    items: list[EvalItem],
    candidates: list[ModelSpec],
    small_id: str,
    large_id: str,
    *,
    tolerance: float = 0.02,
    train_suites: set[str] | None = None,
    span: float = DEFAULT_PARAMS.span,
    stamp: str | None = None,
) -> Calibration:
    """Pick the cheapest ``base_balanced`` whose TRAIN accuracy is within ``tolerance`` of
    always-large, then report it on the held-out items.

    Train/holdout is by suite when ``train_suites`` is given (cross-domain check), otherwise a
    deterministic hash split."""
    if train_suites:
        train = [i for i in items if i.suite in train_suites]
        hold = [i for i in items if i.suite not in train_suites]
    else:
        train = [i for i in items if i.split() == "train"]
        hold = [i for i in items if i.split() == "holdout"]
    if not train or not hold:
        raise ValueError("calibration needs non-empty train and holdout sets")
    target = fixed(train, large_id).accuracy - tolerance

    frontier: list[dict[str, float]] = []
    best: tuple[float, float, float] | None = None  # (cost, -accuracy, base)
    for step in range(0, 61):  # base_balanced 0.00 .. 0.60
        base = step / 100
        p = RouterParams(max(0.0, base - 0.1), base, min(1.0, base + 0.2), span, "candidate")
        r = replay(train, candidates, small_id, large_id, p)
        frontier.append({"base_balanced": base, "accuracy": r.accuracy, "cost": r.cost,
                         "share_large": r.share_large})  # fmt: skip
        if r.accuracy >= target:
            cand = (r.cost, -r.accuracy, base)
            if best is None or cand < best:
                best = cand
    base = best[2] if best else 0.6  # nothing met the target: be conservative (always large)
    version = (
        f"calibrated-{stamp or datetime.now(UTC):%Y%m%d}"
        if not isinstance(stamp, str)
        else f"calibrated-{stamp}"
    )
    chosen = RouterParams(max(0.0, base - 0.1), base, min(1.0, base + 0.2), span, version)
    return Calibration(
        chosen,
        replay(train, candidates, small_id, large_id, chosen),
        replay(hold, candidates, small_id, large_id, chosen),
        frontier,
        tolerance,
    )


def lift_table(
    items: list[EvalItem],
    candidates: list[ModelSpec],
    small_id: str,
    large_id: str,
    span: float = DEFAULT_PARAMS.span,
) -> list[dict[str, float]]:
    """Router accuracy minus the accuracy of escalating the same share of items at random.

    Positive lift means the policy chooses *which* items to escalate better than chance; a policy
    with no signal sits on the straight line between always-small and always-large."""
    a_small = fixed(items, small_id).accuracy
    a_large = fixed(items, large_id).accuracy
    out: list[dict[str, float]] = []
    seen: set[tuple[float, float]] = set()
    for step in range(0, 61, 2):
        base = step / 100
        p = RouterParams(max(0.0, base - 0.1), base, min(1.0, base + 0.2), span, "sweep")
        r = replay(items, candidates, small_id, large_id, p)
        key = (round(r.share_large, 3), round(r.accuracy, 3))
        if key in seen:
            continue
        seen.add(key)
        random_mix = a_small + r.share_large * (a_large - a_small)
        out.append({"base_balanced": base, "share_large": r.share_large, "accuracy": r.accuracy,
                    "random_mix_accuracy": random_mix, "lift": r.accuracy - random_mix})  # fmt: skip
    return out


def params_to_json(params: RouterParams, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": params.version,
        "params": {
            "base": {
                "low": params.base_low,
                "balanced": params.base_balanced,
                "high": params.base_high,
            },
            "span": params.span,
        },
        "calibrated_on": meta,
        "note": "Chosen by counting on measured benchmark outcomes (no model training). See benchmarks/README.md.",
    }
