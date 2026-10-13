"""Aggregate raw benchmark rows into a report (JSON + Markdown)."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llmflow.catalog import ModelSpec


def wilson(passed: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = passed / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))]


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _group_acc(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        groups[r[key]].append(bool(r["passed"]))
    return {k: {"n": len(v), "accuracy": sum(v) / len(v)} for k, v in sorted(groups.items())}


def summarise(
    rows: list[dict[str, Any]],
    models: dict[str, ModelSpec],
    *,
    suite_name: str,
    strategy_descriptions: dict[str, str],
    now: datetime | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_strategy[r["strategy"]].append(r)

    out: dict[str, dict[str, Any]] = {}
    for name, rs in by_strategy.items():
        n = len(rs)
        passed = sum(1 for r in rs if r["passed"])
        lo, hi = wilson(passed, n)
        ok = [r for r in rs if r["status"] == "ok"]
        lat = [r["latency_ms"] for r in ok]
        cost = sum(r["shadow_cost_usd"] for r in ok)
        tiers: dict[str, int] = defaultdict(int)
        used: dict[str, int] = defaultdict(int)
        for r in ok:
            tiers[r["tier"] or "unknown"] += 1
            used[r["model"] or "unknown"] += 1
        out[name] = {
            "description": strategy_descriptions.get(name, name),
            "n": n,
            "passed": passed,
            "accuracy": passed / n if n else 0.0,
            "accuracy_ci95": [lo, hi],
            "failures": n - len(ok),
            "fallbacks": sum(1 for r in ok if r["attempts"] > 1),
            "retries": sum(r["retries"] for r in rs),
            "latency_ms_mean": statistics.fmean(lat) if lat else None,
            "latency_ms_p50": _pct(lat, 50),
            "latency_ms_p95": _pct(lat, 95),
            "prompt_tokens": sum(r["prompt_tokens"] for r in ok),
            "completion_tokens": sum(r["completion_tokens"] for r in ok),
            "shadow_cost_usd": cost,
            "cost_per_correct_usd": cost / passed if passed else None,
            "tier_mix": dict(tiers),
            "models_used": dict(used),
            "by_difficulty": _group_acc(rs, "difficulty"),
            "by_category": _group_acc(rs, "category"),
        }

    base = out.get("always-large")
    if base:
        for s in out.values():
            s["accuracy_delta_vs_large_pts"] = (s["accuracy"] - base["accuracy"]) * 100
            s["cost_saving_vs_large_pct"] = (
                (1 - s["shadow_cost_usd"] / base["shadow_cost_usd"]) * 100
                if base["shadow_cost_usd"]
                else None
            )
            s["latency_p50_delta_vs_large_pct"] = (
                (s["latency_ms_p50"] / base["latency_ms_p50"] - 1) * 100
                if s["latency_ms_p50"] and base["latency_ms_p50"]
                else None
            )

    # Quality priors suggested by fixed-model runs (accuracy of that model on the suite).
    priors: dict[str, dict[str, float]] = {}
    for r in rows:
        if r["status"] == "ok" and r["strategy"].startswith("always-") and r["model"]:
            d = priors.setdefault(r["model"], {"n": 0, "passed": 0})
            d["n"] += 1
            d["passed"] += 1 if r["passed"] else 0
    suggested = {
        m: {
            "n": d["n"],
            "accuracy": d["passed"] / d["n"],
            "current_prior": models[m].quality if m in models else None,
        }
        for m, d in priors.items()
    }

    return {
        "label": "MEASURED",
        "notes": notes or [],
        "generated_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "suite": suite_name,
        "items": max((s["n"] for s in out.values()), default=0),
        "models": {
            m.id: {
                "upstream": m.upstream_model,
                "tier": m.tier.name.lower(),
                "price_in": m.price_in,
                "price_out": m.price_out,
            }
            for m in models.values()
        },
        "strategies": out,
        "suggested_quality_priors": suggested,
    }


def to_markdown(report: dict[str, Any]) -> str:
    s = report["strategies"]
    lines = [
        f"# LLMFlow routing benchmark ({report['label']})",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Suite: `{report['suite']}`, {report['items']} items (hand-written, deterministic checks, no LLM judge)",
        "- Provider: Groq free tier, real API calls through the gateway. temperature=0, cache off.",
        "- **Shadow cost** = tokens x paid list price per catalog; actual spend was 0. Latency includes gateway queueing for quota.",
        "- Small suite: 95% intervals are wide. Differences under ~15 points are within noise.",
        *[f"- Note: {n}" for n in report.get("notes", [])],
        "",
        "## Results",
        "",
        "| Strategy | Accuracy (95% CI) | Failures | p50 latency | Shadow cost | Cost / correct | Cost vs large | Accuracy vs large |",
        "|---|---|---|---|---|---|---|---|",
    ]
    order = sorted(s, key=lambda k: (not k.startswith("always-"), k))
    for name in order:
        v = s[name]
        lo, hi = v["accuracy_ci95"]
        lat = f"{v['latency_ms_p50']:.0f} ms" if v["latency_ms_p50"] is not None else "-"
        cpc = f"${v['cost_per_correct_usd']:.5f}" if v["cost_per_correct_usd"] is not None else "-"
        sav = v.get("cost_saving_vs_large_pct")
        sav_s = f"{-sav:+.0f}%" if sav is not None else "-"
        dlt = v.get("accuracy_delta_vs_large_pts")
        dlt_s = f"{dlt:+.1f} pts" if dlt is not None else "-"
        lines.append(
            f"| {name} | {v['accuracy'] * 100:.0f}% ({lo * 100:.0f}-{hi * 100:.0f}) | {v['failures']} | {lat} "
            f"| ${v['shadow_cost_usd']:.5f} | {cpc} | {sav_s} | {dlt_s} |"
        )
    lines += ["", "## Routed traffic by tier", ""]
    for name in order:
        if name.startswith("routed"):
            mix = ", ".join(f"{k}: {v}" for k, v in sorted(s[name]["tier_mix"].items()))
            lines.append(f"- **{name}**: {mix}")
    lines += [
        "",
        "## Accuracy by difficulty",
        "",
        "| Strategy | easy | medium | hard |",
        "|---|---|---|---|",
    ]
    for name in order:
        d = s[name]["by_difficulty"]
        cells = [
            f"{d[k]['accuracy'] * 100:.0f}% (n={d[k]['n']})" if k in d else "-"
            for k in ("easy", "medium", "hard")
        ]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Suggested quality priors",
        "",
        "Accuracy of each model on this suite (replace the placeholder `quality:` in `catalog.yaml` only after reviewing).",
        "",
    ]
    for m, d in sorted(report["suggested_quality_priors"].items()):
        lines.append(
            f"- `{m}`: {d['accuracy'] * 100:.0f}% over {d['n']} items (current prior {d['current_prior']})"
        )
    lines.append("")
    return "\n".join(lines)
