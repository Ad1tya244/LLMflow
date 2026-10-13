"""Populate a LOCAL dev database with synthetic request logs for UI development.

The rows are fabricated (seeded RNG) and exist only so the dashboard can be exercised
without provider keys. Never point this at a production database, and never quote
numbers derived from it as measurements.

    PYTHONPATH=src .venv/bin/python scripts/seed_dev_data.py sqlite+aiosqlite:///./dev.db
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import time

from llmflow.catalog import load_catalog
from llmflow.storage.usage import RequestLog, UsageRepo

MIX = {"small": 0.55, "medium": 0.3, "large": 0.15}
LATENCY_MS = {"small": 320, "medium": 780, "large": 1900}


async def main(url: str, count: int = 700, hours: int = 24) -> None:
    if "dev" not in url and ":memory:" not in url:
        raise SystemExit("refusing to seed a database whose URL does not contain 'dev'")
    rng = random.Random(7)
    catalog = load_catalog(__import__("pathlib").Path("config/catalog.yaml"))
    by_tier: dict[str, list[str]] = {"small": [], "medium": [], "large": []}
    # Mirror the gateway: only models whose provider key is present in the environment.
    pool = catalog.enabled_models(dict(os.environ)) or list(catalog.models.values())
    for m in pool:
        by_tier[m.tier.name.lower()].append(m.id)
    for tier, ids in by_tier.items():
        if not ids:  # fall back to the nearest populated tier so every mix weight is usable
            by_tier[tier] = next(v for v in by_tier.values() if v)

    repo = UsageRepo(url)
    await repo.init()
    now = time.time()
    for _ in range(count):
        ts = now - rng.random() * hours * 3600
        tier = rng.choices(list(MIX), weights=list(MIX.values()))[0]
        model_id = rng.choice(by_tier[tier])
        spec = catalog.models[model_id]
        failed = rng.random() < 0.03
        prompt = int(rng.lognormvariate(5.2, 0.8))
        completion = int(rng.lognormvariate(5.0, 0.7))
        usage_ok = not failed
        await repo.record(
            RequestLog(
                ts=ts,
                key_id="devseed1",
                requested_model="auto",
                model=model_id if usage_ok else None,
                provider=spec.provider,
                status="ok" if usage_ok else "error",
                prompt_tokens=prompt if usage_ok else 0,
                completion_tokens=completion if usage_ok else 0,
                latency_ms=LATENCY_MS[tier] * rng.lognormvariate(0, 0.35),
                shadow_cost_usd=spec.shadow_cost(prompt, completion) if usage_ok else 0.0,
                attempts=1 if usage_ok and rng.random() > 0.08 else 2,
                cache_status=rng.choices(["none", "miss", "hit"], weights=[70, 18, 12])[0],
                route_reason=f"[synthetic] routed to {tier} tier",
            )
        )
    await repo.close()
    print(f"seeded {count} synthetic rows into {url}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
