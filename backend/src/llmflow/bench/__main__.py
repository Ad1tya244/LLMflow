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


def _generate_cmd(args: argparse.Namespace) -> int:
    from llmflow.bench import generate

    out = args.out
    if args.gsm8k:
        items = generate.gsm8k_items(args.gsm8k, args.gsm_n, args.seed)
        generate.write_jsonl(out / f"gsm8k{args.gsm_n}.jsonl", items)
        print(f"wrote {len(items)} GSM8K items -> {out / f'gsm8k{args.gsm_n}.jsonl'}")
    if args.xhard_n:
        items = generate.synthetic_items(args.xhard_n, args.seed + 1, ("xhard",), "x")
        generate.write_jsonl(out / f"synthx{args.xhard_n}.jsonl", items)
        print(
            f"wrote {len(items)} extra-hard synthetic items -> {out / f'synthx{args.xhard_n}.jsonl'}"
        )
        return 0
    items = generate.synthetic_items(args.synth_n, args.seed)
    generate.write_jsonl(out / f"synth{args.synth_n}.jsonl", items)
    print(f"wrote {len(items)} synthetic items -> {out / f'synth{args.synth_n}.jsonl'}")
    return 0


def _parse_pairs(raw: list[str]) -> dict[str, tuple[Path, Path]]:
    out: dict[str, tuple[Path, Path]] = {}
    for item in raw:
        name, _, rest = item.partition("=")
        suite, _, results = rest.partition(":")
        if not (name and suite and results):
            raise SystemExit(f"--pair expects NAME=SUITE.jsonl:RESULTS.jsonl, got {item!r}")
        out[name] = (Path(suite), Path(results))
    return out


def _fmt(r: Any) -> str:
    rec = "-" if r.escalation_recall is None else f"{r.escalation_recall * 100:.0f}%"
    prec = "-" if r.escalation_precision is None else f"{r.escalation_precision * 100:.0f}%"
    return (f"acc {r.accuracy * 100:5.1f}%  cost ${r.cost:.5f}  large {r.share_large * 100:3.0f}%  "
            f"escal. recall {rec:>4}  precision {prec:>4}  (n={r.n})")  # fmt: skip


def _eval_cmd(args: argparse.Namespace) -> int:
    from llmflow.bench import router_eval as re_
    from llmflow.catalog import load_catalog
    from llmflow.routing.config import load_router_params

    pairs = _parse_pairs(args.pair)
    items = re_.load_items(pairs, analyzer=args.analyzer)
    cat = load_catalog(Path("config/catalog.yaml"))
    seen = {m for it in items for m in it.outcomes}
    cands = [m for m in cat.models.values() if m.id in seen]
    if len(cands) < 2:
        raise SystemExit(f"need results for at least two models; found {sorted(seen)}")
    small = min(cands, key=lambda m: m.price_in + m.price_out).id
    large = max(cands, key=lambda m: m.quality).id
    items = re_.complete_items(items, [small, large])
    need = [(not it.outcomes[small].passed) and it.outcomes[large].passed for it in items]
    auc = re_.auc([it.analysis.difficulty for it in items], need)

    lines = [f"analyzer: {args.analyzer}",
             f"items: {len(items)}  small={small}  large={large}",
             f"needs-large items (small fails, large passes): {sum(need)}",
             f"difficulty-score AUC for 'needs large': {auc if auc is None else round(auc, 3)}  (0.5 = no signal)",
             "", f"always-small : {_fmt(re_.fixed(items, small))}",
             f"always-large : {_fmt(re_.fixed(items, large))}",
             f"oracle       : {_fmt(re_.oracle(items))}"]  # fmt: skip
    current = load_router_params(args.params)
    lines.append(
        f"router ({current.version}, balanced): {_fmt(re_.replay(items, cands, small, large, current))}"
    )
    lines.append(
        f"router ({current.version}, high)    : {_fmt(re_.replay(items, cands, small, large, current, 'high'))}"
    )

    if args.lift:
        lines += ["", "lift over random escalation (same share sent to the large model):",
                  "  base  share_large  accuracy  random-mix  lift"]  # fmt: skip
        for row in re_.lift_table(items, cands, small, large):
            lines.append(
                f"  {row['base_balanced']:.2f}  {row['share_large'] * 100:9.0f}%  "
                f"{row['accuracy'] * 100:7.1f}%  {row['random_mix_accuracy'] * 100:9.1f}%  "
                f"{row['lift'] * 100:+5.1f} pts"
            )
    if args.calibrate:
        train = set(args.train_suites.split(",")) if args.train_suites else None
        cal = re_.calibrate(
            items, cands, small, large, tolerance=args.tolerance, train_suites=train
        )
        lines += ["", f"calibration (tolerance {args.tolerance * 100:.0f} pts, split by "
                      f"{'suite ' + str(sorted(train)) if train else 'hash'}):",
                  f"  chosen base_balanced={cal.params.base_balanced:.2f}",
                  f"  train   : {_fmt(cal.train)}", f"  holdout : {_fmt(cal.holdout)}"]  # fmt: skip
        if args.write:
            meta = {"suites": sorted(pairs), "items": len(items), "tolerance": args.tolerance,
                    "holdout_accuracy": cal.holdout.accuracy, "holdout_share_large": cal.holdout.share_large,
                    "generated": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
            args.write.write_text(json.dumps(re_.params_to_json(cal.params, meta), indent=2) + "\n")
            lines.append(f"  wrote {args.write}")
        if args.frontier:
            args.frontier.write_text(json.dumps(cal.frontier, indent=2))
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="llmflow.bench")
    sub = p.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser(
        "eval-router", help="replay routing policies on measured per-model outcomes"
    )
    ev.add_argument("--pair", action="append", required=True, help="NAME=SUITE.jsonl:RESULTS.jsonl")
    ev.add_argument("--params", type=Path, default=Path("config/routing.json"))
    ev.add_argument(
        "--analyzer", default="v2", choices=["v1", "v2"], help="difficulty-score version"
    )
    ev.add_argument("--lift", action="store_true", help="print the lift-over-random table")
    ev.add_argument("--calibrate", action="store_true")
    ev.add_argument(
        "--train-suites", help="comma-separated suite names to calibrate on (rest = holdout)"
    )
    ev.add_argument("--tolerance", type=float, default=0.02)
    ev.add_argument("--write", type=Path, help="write the calibrated params JSON here")
    ev.add_argument("--frontier", type=Path)
    gen = sub.add_parser(
        "generate", help="write GSM8K-sample and synthetic suites (no model is run)"
    )
    gen.add_argument("--gsm8k", type=Path, help="path to GSM8K test.jsonl")
    gen.add_argument("--gsm-n", type=int, default=36)
    gen.add_argument("--synth-n", type=int, default=36)
    gen.add_argument(
        "--xhard-n", type=int, default=0, help="write only an extra-hard synthetic suite"
    )
    gen.add_argument("--seed", type=int, default=7)
    gen.add_argument("--out", type=Path, default=Path("../benchmarks/suite"))
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
    if args.cmd == "eval-router":
        return _eval_cmd(args)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.cmd == "generate":
        return _generate_cmd(args)
    if args.cmd == "run":
        return asyncio.run(_run(args))
    return _report_cmd(args)


if __name__ == "__main__":
    sys.exit(main())
