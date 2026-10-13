"""Benchmark execution: paced, resumable, strategy-by-strategy.

Requests go through the real gateway stack (routing, quota tracking, fallback, usage log)
via an in-process ASGI client, so the numbers describe what a user of the gateway gets.
Pacing waits for provider headroom instead of firing into 429s, because rate-limit
failures would measure the free tier, not the routing strategy.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from llmflow.bench.checks import check
from llmflow.bench.suite import Item
from llmflow.catalog import ModelSpec
from llmflow.providers.quota import QuotaTracker
from llmflow.routing.analyzer import analyze
from llmflow.schemas import ChatRequest, Message

_RETRYABLE = {429, 503}
_STORED_RESPONSE_CHARS = 6000


@dataclass(frozen=True, slots=True)
class Strategy:
    name: str
    description: str
    model: str  # catalog id, or "auto"
    quality: str = "balanced"

    @property
    def pinned(self) -> bool:
        return self.model != "auto"


def default_strategies(models: list[ModelSpec]) -> list[Strategy]:
    """Fixed-model baselines derived from the catalog, plus the routed strategies."""
    if not models:
        raise ValueError("no enabled models; set GROQ_API_KEY in backend/.env")
    largest = max(models, key=lambda m: m.quality)
    cheapest = min(models, key=lambda m: m.price_in + m.price_out)
    out = [
        Strategy("always-large", f"always {largest.id}", largest.id),
        Strategy("always-cheapest", f"always {cheapest.id}", cheapest.id),
    ]
    for m in sorted(models, key=lambda m: m.quality):
        if m.id not in {largest.id, cheapest.id}:
            out.append(Strategy(f"always-{m.tier.name.lower()}", f"always {m.id}", m.id))
    out.append(Strategy("routed-balanced", "LLMFlow auto, quality=balanced", "auto", "balanced"))
    out.append(Strategy("routed-high", "LLMFlow auto, quality=high", "auto", "high"))
    return out


def load_done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    done: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            done.add((row["strategy"], row["item_id"]))
    return done


async def wait_for_quota(
    quota: QuotaTracker,
    specs: list[ModelSpec],
    est_tokens: int,
    *,
    max_wait_s: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    poll_s: float = 2.0,
) -> bool:
    """Block until every spec has headroom for ``est_tokens``; False if it never does."""
    waited = 0.0
    while not all(quota.allows(s, est_tokens) for s in specs):
        if waited >= max_wait_s:
            return False
        await sleep(poll_s)
        waited += poll_s
    return True


class QuotaExhausted(RuntimeError):
    """Daily quota ran out; partial results are kept and the run can be resumed later."""


@dataclass(slots=True)
class RunConfig:
    max_tokens: int = 1500
    retries: int = 3
    retry_wait_s: float = 20.0
    max_wait_s: float = 900.0


async def run_item(
    client: httpx.AsyncClient,
    quota: QuotaTracker,
    models: list[ModelSpec],
    strategy: Strategy,
    item: Item,
    cfg: RunConfig,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": strategy.model,
        "messages": [{"role": "user", "content": item.prompt}],
        "temperature": 0,
        "max_tokens": cfg.max_tokens,
        "llmflow": {"quality": strategy.quality, "cache": "off", "fallback": not strategy.pinned},
    }
    est = analyze(
        ChatRequest(messages=[Message(role="user", content=item.prompt)], max_tokens=cfg.max_tokens)
    ).needs_tokens
    specs = [m for m in models if m.id == strategy.model] if strategy.pinned else models

    retries_used = 0
    started = time.perf_counter()
    for attempt in range(cfg.retries + 1):
        if not await wait_for_quota(quota, specs, est, max_wait_s=cfg.max_wait_s, sleep=sleep):
            raise QuotaExhausted(
                f"no quota headroom for {[s.id for s in specs]} after {cfg.max_wait_s}s"
            )
        started = time.perf_counter()
        resp = await client.post("/v1/chat/completions", json=body)
        if resp.status_code in _RETRYABLE and attempt < cfg.retries:
            retries_used += 1
            await sleep(cfg.retry_wait_s)
            continue
        break
    latency_ms = (time.perf_counter() - started) * 1000

    row: dict[str, Any] = {
        "strategy": strategy.name,
        "item_id": item.id,
        "category": item.category,
        "difficulty": item.difficulty,
        "ts": time.time(),
        "latency_ms": round(latency_ms, 1),
        "retries": retries_used,
        "http_status": resp.status_code,
    }
    if resp.status_code != 200:
        err = (
            resp.json().get("error", {})
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        row.update(status="error", passed=False, detail=f"http {resp.status_code}: {err.get('type', '')}",
                   model=None, tier=None, attempts=0, prompt_tokens=0, completion_tokens=0,
                   shadow_cost_usd=0.0, response="")  # fmt: skip
        return row

    data = resp.json()
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    usage = data.get("usage") or {}
    passed, detail = check(item.check, text)
    model_id = resp.headers.get("x-llmflow-model")
    spec = next((m for m in models if m.id == model_id), None)
    row.update(
        status="ok",
        passed=passed,
        detail=detail,
        model=model_id,
        tier=spec.tier.name.lower() if spec else None,
        attempts=int(resp.headers.get("x-llmflow-attempts", "1")),
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        shadow_cost_usd=float(resp.headers.get("x-llmflow-shadow-cost-usd", "0")),
        response=text[:_STORED_RESPONSE_CHARS],
        response_truncated=len(text) > _STORED_RESPONSE_CHARS,
    )
    return row


async def run_strategy(
    client: httpx.AsyncClient,
    quota: QuotaTracker,
    models: list[ModelSpec],
    strategy: Strategy,
    items: list[Item],
    results_path: Path,
    done: set[tuple[str, str]],
    cfg: RunConfig,
    lock: asyncio.Lock,
    progress: Callable[[str], None] = print,
) -> int:
    ran = 0
    for i, item in enumerate(items, 1):
        if (strategy.name, item.id) in done:
            continue
        row = await run_item(client, quota, models, strategy, item, cfg)
        async with lock:
            with results_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        done.add((strategy.name, item.id))
        ran += 1
        mark = "pass" if row["passed"] else "FAIL"
        progress(
            f"[{strategy.name:<16}] {i:>2}/{len(items)} {item.id:<14} {mark} "
            f"{row.get('model') or '-':<20} {row['latency_ms']:>7.0f} ms"
        )
    return ran


async def run_benchmark(
    client: httpx.AsyncClient,
    quota: QuotaTracker,
    models: list[ModelSpec],
    strategies: list[Strategy],
    items: list[Item],
    results_path: Path,
    cfg: RunConfig,
    progress: Callable[[str], None] = print,
) -> int:
    """Pinned strategies run concurrently (each hits its own model's quota); routed ones
    run afterwards one at a time so they do not compete with each other for headroom."""
    results_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(results_path)
    lock = asyncio.Lock()

    async def go(s: Strategy) -> int:
        return await run_strategy(
            client, quota, models, s, items, results_path, done, cfg, lock, progress
        )

    total = 0
    pinned = [s for s in strategies if s.pinned]
    if pinned:
        total += sum(await asyncio.gather(*(go(s) for s in pinned)))
    for s in strategies:
        if not s.pinned:
            total += await go(s)
    return total
