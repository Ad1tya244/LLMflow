"""CLI: ``python -m llmflow.bench run|report`` (run from backend/ with PYTHONPATH=src)."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from llmflow.api.app import create_app
from llmflow.bench.checks import check
from llmflow.bench.report import load_rows, summarise, to_markdown
from llmflow.bench.runner import QuotaExhausted, RunConfig, default_strategies, run_benchmark
from llmflow.bench.suite import load_suite
from llmflow.core.config import Settings

DEFAULT_SUITE = Path("../benchmarks/suite/core44.jsonl")
DEFAULT_OUT = Path("../benchmarks/results")


def _report(results: Path, suite_name: str, descriptions: dict[str, str], models: dict) -> dict:  # type: ignore[type-arg]
    return summarise(
        load_rows(results), models, suite_name=suite_name, strategy_descriptions=descriptions
    )


async def _run(args: argparse.Namespace) -> int:
    items = load_suite(args.suite)
    if args.limit:
        items = items[: args.limit]
    key = f"bench-{secrets.token_hex(12)}"
    db = args.out / ".bench-usage.db"
    settings = Settings(
        api_keys=key,
        admin_api_keys="",
        database_url=f"sqlite+aiosqlite:///{db}",
        rate_limit_rpm=10_000,
        max_tokens_cap=max(args.max_tokens, 8192),
        cache_ttl_s=0,
        daily_budget_usd=None,
        daily_token_budget=None,
        enable_docs=False,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        gw = app.state.gateway
        models = list(gw.enabled_models)
        strategies = default_strategies(models)
        if args.strategies:
            wanted = set(args.strategies.split(","))
            unknown = wanted - {s.name for s in strategies}
            if unknown:
                print(
                    f"unknown strategies: {sorted(unknown)}; available: {[s.name for s in strategies]}"
                )
                return 2
            strategies = [s for s in strategies if s.name in wanted]
        results = args.out / f"{args.name}.jsonl"
        print(
            f"suite={args.suite.name} items={len(items)} strategies={[s.name for s in strategies]}"
        )
        print(f"results -> {results} (resumable; delete the file to start over)")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://bench",
            headers={"Authorization": f"Bearer {key}"},
            timeout=180,
        ) as client:
            try:
                ran = await run_benchmark(
                    client, gw.quota, models, strategies, items, results,
                    RunConfig(max_tokens=args.max_tokens, max_wait_s=args.max_wait),
                )  # fmt: skip
            except QuotaExhausted as exc:
                print(f"\nSTOPPED: {exc}\nPartial results are saved; re-run later to resume.")
                return 3
        print(f"\nran {ran} new item(s)")
    desc = {s.name: s.description for s in default_strategies(models)}
    rep = _report(results, args.suite.name, desc, gw.catalog.models)
    (args.out / f"{args.name}.report.json").write_text(json.dumps(rep, indent=2))
    (args.out / f"{args.name}.report.md").write_text(to_markdown(rep))
    print(f"report -> {args.out / (args.name + '.report.md')}")
    return 0


_LEGACY_TRUNCATION = 1500  # early runs stored only the first 1500 characters


def _rescore(rows: list[dict[str, Any]], suite: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Re-evaluate stored responses with the current checkers (no API calls). Returns the
    rows plus a note for every verdict that changed."""
    specs = {i.id: i.check for i in load_suite(suite)}
    changes: list[str] = []
    for r in rows:
        if r.get("status") != "ok" or r["item_id"] not in specs:
            continue
        if r.get("response_truncated", len(r.get("response", "")) >= _LEGACY_TRUNCATION):
            continue  # the stored text is incomplete; never judge a partial response
        passed, detail = check(specs[r["item_id"]], r.get("response", ""))
        if passed != r["passed"]:
            r["rescored"] = f"{r['passed']} -> {passed}"
            changes.append(f"{r['strategy']}/{r['item_id']}: {r['rescored']}")
            r["passed"], r["detail"] = passed, detail
    return rows, changes


def _report_cmd(args: argparse.Namespace) -> int:
    from llmflow.catalog import load_catalog

    cat = load_catalog(Path("config/catalog.yaml"))
    results = args.out / f"{args.name}.jsonl"
    models = list(cat.models.values())
    desc = {s.name: s.description for s in default_strategies(models)}
    rows = load_rows(results)
    notes: list[str] = []
    if args.rescore:
        rows, changes = _rescore(rows, args.suite)
        if changes:
            results.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    changed = [
        f"{r['strategy']}/{r['item_id']}: {r['rescored']}" for r in rows if r.get("rescored")
    ]
    if changed:
        notes.append(
            "responses re-scored with a corrected checker (no new API calls); verdict changes: "
            + "; ".join(changed)
        )
    rep = summarise(
        rows, cat.models, suite_name=args.suite.name, strategy_descriptions=desc, notes=notes
    )
    (args.out / f"{args.name}.report.json").write_text(json.dumps(rep, indent=2))
    (args.out / f"{args.name}.report.md").write_text(to_markdown(rep))
    print(to_markdown(rep))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="llmflow.bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "report"):
        s = sub.add_parser(name)
        s.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
        s.add_argument("--out", type=Path, default=DEFAULT_OUT)
        s.add_argument("--name", default=f"groq-{datetime.now(UTC):%Y%m%d}")
    sub.choices["report"].add_argument(
        "--rescore", action="store_true", help="re-evaluate stored responses with current checkers"
    )
    run = sub.choices["run"]
    run.add_argument(
        "--strategies", help="comma-separated subset, e.g. always-large,routed-balanced"
    )
    run.add_argument("--limit", type=int, help="only the first N suite items (smoke test)")
    run.add_argument("--max-tokens", type=int, default=1500)
    run.add_argument(
        "--max-wait", type=float, default=900.0, help="seconds to wait for quota headroom"
    )
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.cmd == "run":
        return asyncio.run(_run(args))
    return _report_cmd(args)


if __name__ == "__main__":
    sys.exit(main())
