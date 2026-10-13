"""Benchmark harness: checkers, statistics, pacing, resume, end-to-end through the gateway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from llmflow.api.app import create_app
from llmflow.bench.checks import check, extract_answer, json_matches, parse_json
from llmflow.bench.report import summarise, to_markdown, wilson
from llmflow.bench.runner import (
    QuotaExhausted,
    RunConfig,
    default_strategies,
    load_done,
    run_benchmark,
    wait_for_quota,
)
from llmflow.bench.suite import load_suite
from llmflow.catalog import Catalog, Tier
from llmflow.core.config import Settings
from llmflow.providers.base import Completion
from llmflow.providers.quota import QuotaTracker
from llmflow.schemas import Usage

from .conftest import model

SUITE = Path(__file__).parents[2] / "benchmarks" / "suite" / "core44.jsonl"


# --- checkers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "text", "ok"),
    [
        ({"type": "numeric", "value": 1890}, "work...\nAnswer: 1,890", True),
        ({"type": "numeric", "value": 1890}, "Answer: ₹1890.00", True),
        ({"type": "numeric", "value": 46}, "so the total is 46", True),  # lenient fallback
        ({"type": "numeric", "value": 46}, "Answer: 45", False),
        ({"type": "choice", "value": "C"}, "Answer: C) O(log n)", True),
        ({"type": "choice", "value": "C"}, "I think it is B.\nAnswer: **B**", False),
        ({"type": "exact", "accept": ["canberra"]}, "Answer: Canberra.", True),
        (
            {"type": "exact", "accept": ["shakespeare", "william shakespeare"]},
            "Answer: William Shakespeare",
            True,
        ),
        ({"type": "exact", "accept": ["pacific"]}, "Answer: Atlantic", False),
        (
            {"type": "json", "expected": {"a": 1, "b": "x"}},
            '```json\n{"a": 1, "b": "X"}\n```',
            True,
        ),
        ({"type": "json", "expected": {"a": 1}}, '{"a": 1, "extra": 2}', False),
        ({"type": "json", "expected": [11, 13]}, "Here: [11, 13]", True),
        (
            {"type": "json", "expected": {"i": ["a", "b"]}, "unordered": True},
            '{"i": ["B", "a"]}',
            True,
        ),
        ({"type": "constraint", "name": "bullets3"}, "- a\n- b\n- c", True),
        ({"type": "constraint", "name": "bullets3"}, "- a\n- b", False),
        ({"type": "constraint", "name": "no_letter_e"}, "A big blue wave rolls on", False),
        (
            {"type": "constraint", "name": "no_letter_e"},
            "A vast salt pool stirs and swirls as gray clouds roll past",
            True,
        ),
        ({"type": "constraint", "name": "repeat_banana"}, "banana banana banana banana", True),
        (
            {"type": "constraint", "name": "eight_words"},
            "Fresh coffee wakes my sleepy brain up today.",
            True,
        ),
        (
            {"type": "constraint", "name": "eight_words"},
            "Coffee, wakes my sleepy brain up today.",
            False,
        ),
    ],
)
def test_checkers(spec: dict[str, Any], text: str, ok: bool) -> None:
    assert check(spec, text)[0] is ok


def test_empty_response_fails_every_check() -> None:
    assert check({"type": "numeric", "value": 1}, "  ")[0] is False


def test_hard_suite_wellformed() -> None:
    hard = load_suite(SUITE.with_name("hard21.jsonl"))
    assert len(hard) == 21 and all(i.difficulty == "hard" for i in hard)


def test_helpers() -> None:
    assert extract_answer("x\nanswer - 42.") == "42"
    assert parse_json("no json here") is None
    assert json_matches(1.0, 1) and not json_matches(True, 1)


def test_shipped_suite_is_wellformed_and_answers_are_right() -> None:
    items = load_suite(SUITE)
    assert len(items) == 44
    by_id = {i.id: i for i in items}
    # independent re-derivation of a few answers so the key itself is sanity-checked
    assert by_id["math-10"].check["value"] == len(
        {n for n in range(1, 100) if n % 3 == 0 or n % 5 == 0}
    )
    assert by_id["math-04"].check["value"] == 2400 * 0.75 * 1.05
    assert by_id["math-13"].check["value"] == 25 + 20 - (40 - 8)
    assert by_id["json-04"].check["expected"] == [
        p for p in range(10, 31) if all(p % d for d in range(2, p))
    ]
    for it in items:
        assert it.check["type"] in {"numeric", "choice", "exact", "json", "constraint"}


# --- statistics -------------------------------------------------------------------------


def test_wilson_interval_properties() -> None:
    lo, hi = wilson(0, 0)
    assert (lo, hi) == (0.0, 0.0)
    lo, hi = wilson(22, 44)
    assert 0.35 < lo < 0.5 < hi < 0.65
    lo, hi = wilson(44, 44)
    assert hi > 0.999 and lo > 0.9


# --- pacing -----------------------------------------------------------------------------


async def test_wait_for_quota_waits_then_succeeds_or_gives_up() -> None:
    t = [0.0]
    q = QuotaTracker(lambda: t[0])
    m = model("m", Tier.SMALL, 0.3, 0.1, rpm=1)
    q.record(m, 10)
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)
        t[0] += 30

    assert await wait_for_quota(q, [m], 0, max_wait_s=300, sleep=fake_sleep)
    assert slept  # had to wait for the minute window to slide

    q.record(m, 10)

    async def stuck(_: float) -> None:
        return None

    assert not await wait_for_quota(q, [m], 0, max_wait_s=4, sleep=stuck, poll_s=2)


# --- end to end through the gateway ---------------------------------------------------


class Oracle:
    """Provider that answers correctly only when the model is 'large', to give strategies
    distinguishable accuracy without any network."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, spec: Any, payload: dict[str, Any]) -> Completion:
        self.calls += 1
        prompt = payload["messages"][0]["content"]
        right = spec.id == "large"
        text = "Answer: 84" if (right and "pencils" in prompt) else "Answer: 0"
        if "capital city of Australia" in prompt:
            text = "Answer: Canberra" if right else "Answer: Sydney"
        return Completion(
            body={"choices": [{"message": {"role": "assistant", "content": text}}],
                  "usage": {"prompt_tokens": 100, "completion_tokens": 20}},
            usage=Usage(prompt_tokens=100, completion_tokens=20),
            latency_ms=5.0,
        )  # fmt: skip

    def stream(self, spec: Any, payload: dict[str, Any]) -> Any:
        raise NotImplementedError


@pytest.fixture
def bench_app(catalog: Catalog, tmp_path: Path):  # type: ignore[no-untyped-def]
    provider = Oracle()
    settings = Settings(
        _env_file=None, api_keys="bench-key-0123456789", admin_api_keys="", min_key_length=1,
        database_url=f"sqlite+aiosqlite:///{tmp_path}/u.db", rate_limit_rpm=10_000, cache_ttl_s=0,
    )  # fmt: skip
    app = create_app(
        settings,
        catalog=catalog,
        providers={"p1": provider, "p2": provider},
        env={"K1": "x", "K2": "y"},
    )
    return app, provider


async def test_end_to_end_run_resume_and_report(bench_app: Any, tmp_path: Path) -> None:
    app, provider = bench_app
    items = [i for i in load_suite(SUITE) if i.id in {"math-01", "fact-01"}]
    out = tmp_path / "r.jsonl"
    async with app.router.lifespan_context(app):
        gw = app.state.gateway
        models = list(gw.enabled_models)
        strategies = [
            s
            for s in default_strategies(models)
            if s.name in {"always-large", "always-cheapest", "routed-balanced"}
        ]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://b",
            headers={"Authorization": "Bearer bench-key-0123456789"},
        ) as client:  # fmt: skip
            cfg = RunConfig(max_tokens=200, retries=0)
            ran = await run_benchmark(
                client, gw.quota, models, strategies, items, out, cfg, progress=lambda _: None
            )
            assert ran == 6
            calls = provider.calls
            # resume: nothing new runs, no extra provider calls
            again = await run_benchmark(
                client, gw.quota, models, strategies, items, out, cfg, progress=lambda _: None
            )
            assert again == 0 and provider.calls == calls
        assert len(load_done(out)) == 6

        rows = [json.loads(line) for line in out.read_text().splitlines()]
        rep = summarise(rows, gw.catalog.models, suite_name="t", strategy_descriptions={})
    s = rep["strategies"]
    assert rep["label"] == "MEASURED"
    assert s["always-large"]["accuracy"] == 1.0
    assert s["always-cheapest"]["accuracy"] == 0.0
    assert s["always-cheapest"]["cost_saving_vs_large_pct"] > 0
    assert s["always-large"]["accuracy_delta_vs_large_pts"] == 0
    md = to_markdown(rep)
    assert "MEASURED" in md and "always-large" in md and "Cost vs large" in md


async def test_quota_exhaustion_stops_cleanly(bench_app: Any, tmp_path: Path) -> None:
    app, _ = bench_app
    items = [i for i in load_suite(SUITE) if i.id == "math-01"]
    async with app.router.lifespan_context(app):
        gw = app.state.gateway
        models = list(gw.enabled_models)
        target = next(m for m in models if m.id == "small")
        gw.quota.cool_down(target.id, 10_000)
        strat = [s for s in default_strategies(models) if s.name == "always-cheapest"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://b",
            headers={"Authorization": "Bearer bench-key-0123456789"},
        ) as client:  # fmt: skip
            with pytest.raises(QuotaExhausted):
                await run_benchmark(
                    client, gw.quota, models, strat, items, tmp_path / "x.jsonl",
                    RunConfig(max_wait_s=0.0, retries=0), progress=lambda _: None,
                )  # fmt: skip


def test_rescore_skips_truncated_responses_and_reports_real_changes() -> None:
    from llmflow.bench.__main__ import _rescore

    full = {"strategy": "s", "item_id": "fact-06", "status": "ok", "passed": False,
            "detail": "", "response": "Answer: Newton (N)"}  # fmt: skip
    cut = {"strategy": "s", "item_id": "choice-10", "status": "ok", "passed": True,
           "detail": "", "response": "x" * 1500}  # fmt: skip
    rows, changes = _rescore([full, cut], SUITE)
    assert rows[0]["passed"] is True and len(changes) == 1
    assert rows[0]["rescored"] == "False -> True"
    assert rows[1]["passed"] is True  # truncated: original verdict kept


# --- suite generation and router evaluation --------------------------------------------------


def test_synthetic_generator_is_deterministic_and_answers_are_correct() -> None:
    import re
    from datetime import date, timedelta

    from llmflow.bench.generate import synthetic_items

    a, b = synthetic_items(32, seed=3), synthetic_items(32, seed=3)
    assert a == b and a != synthetic_items(32, seed=4)
    assert len({i["id"] for i in a}) == 32
    seen_levels = {i["difficulty"] for i in a}
    assert seen_levels == {"easy", "medium", "hard"}
    for it in a:  # recompute each answer independently from the prompt text
        text, chk = it["prompt"].split("\n\n")[0], it["check"]
        if it["category"] == "mult":
            x, y = map(int, re.findall(r"\d+", text))
            assert chk["value"] == x * y
        elif it["category"] == "chain":
            a1, b1, c1, d1, e1 = map(int, re.findall(r"\d+", text))
            assert chk["value"] == (a1 * b1 + c1) - d1 * e1
        elif it["category"] == "letters":
            ch = re.search(r"letter '(.)'", text).group(1)  # type: ignore[union-attr]
            s = re.search(r'string "(.*)"', text).group(1)  # type: ignore[union-attr]
            assert chk["value"] == s.count(ch)
        elif it["category"] == "weekday":
            d0 = date.fromisoformat(re.search(r"\d{4}-\d\d-\d\d", text).group(0))  # type: ignore[union-attr]
            n = int(re.search(r"(\d+) days from today", text).group(1))  # type: ignore[union-attr]
            want = (d0 + timedelta(days=n)).strftime("%A").lower()
            assert chk["accept"] == [want]
        elif it["category"] == "binary":
            n = int(re.search(r"number (\d+)", text).group(1))  # type: ignore[union-attr]
            assert chk["accept"] == [format(n, "b")]
        elif it["category"] == "modpow":
            bb, ee, mm = map(int, re.findall(r"\d+", text))
            assert chk["value"] == pow(bb, ee, mm)


def test_gsm8k_sampling_uses_reference_answers(tmp_path: Path) -> None:
    from llmflow.bench.generate import gsm8k_items

    src = tmp_path / "g.jsonl"
    rows = [{"question": f"Q{i}?", "answer": f"step {i}\n#### {i * 10 + 1:,}"} for i in range(1, 8)]
    src.write_text("\n".join(json.dumps(r) for r in rows))
    items = gsm8k_items(src, 4, seed=1)
    assert len(items) == 4 and all(i["check"]["type"] == "numeric" for i in items)
    assert {i["check"]["value"] for i in items} <= {i * 10 + 1 for i in range(1, 8)}


def _eval_items(small_pass: list[bool], large_pass: list[bool], difficulty: list[str]) -> list[Any]:
    from llmflow.bench.router_eval import EvalItem, Outcome
    from llmflow.routing.analyzer import analyze as _an
    from llmflow.schemas import ChatRequest, Message

    items = []
    for i, (sp, lp, text) in enumerate(zip(small_pass, large_pass, difficulty, strict=True)):
        it = EvalItem(
            f"s:{i}", "s", "x", _an(ChatRequest(messages=[Message(role="user", content=text)]))
        )
        it.outcomes = {"small": Outcome(sp, 1.0), "large": Outcome(lp, 10.0)}
        items.append(it)
    return items


def test_replay_oracle_and_escalation_metrics() -> None:
    from llmflow.bench.router_eval import auc, fixed, oracle, replay
    from llmflow.routing.policy import RouterParams

    easy, hard = "What is 2+2?", "Analyze and compare step by step ```code``` derive the equation"
    items = _eval_items(
        [True, True, False, False], [True, True, True, False], [easy, easy, hard, hard]
    )
    cands = [model("small", Tier.SMALL, 0.5, 0.1), model("large", Tier.LARGE, 0.9, 1.0)]
    assert fixed(items, "large").accuracy == 0.75
    assert oracle(items).accuracy == 0.75 and oracle(items).cost == 1 + 1 + 10 + 1
    # default-like params: easy -> small, hard -> large
    p = RouterParams(0.0, 0.3, 0.5, 0.9, "t")
    r = replay(items, cands, "small", "large", p)
    assert r.share_large == 0.5 and r.escalation_recall == 1.0 and r.escalation_precision == 0.5
    assert auc([0.0, 0.0, 0.9, 0.9], [False, False, True, False]) == pytest.approx(2.5 / 3)
    assert auc([0.1, 0.2], [False, False]) is None


def test_calibration_picks_cheapest_params_meeting_the_tolerance_and_reports_holdout() -> None:
    from llmflow.bench.router_eval import calibrate

    easy, hard = "What is 2+2?", "Analyze and compare step by step ```code``` derive the equation"
    n = 40
    small_pass = [i % 2 == 0 for i in range(n)]  # small fails on every 'hard' item
    texts = [easy if i % 2 == 0 else hard for i in range(n)]
    items = _eval_items(small_pass, [True] * n, texts)
    for i, it in enumerate(items):
        it.key = f"s:{i}"
    cands = [model("small", Tier.SMALL, 0.5, 0.1), model("large", Tier.LARGE, 0.9, 1.0)]
    cal = calibrate(items, cands, "small", "large", tolerance=0.0, stamp="test")
    assert cal.params.version == "calibrated-test"
    assert (
        cal.train.accuracy == 1.0 and cal.holdout.accuracy == 1.0
    )  # escalates exactly the hard ones
    assert 0 < cal.holdout.share_large < 1  # and does not send everything to the large model
    assert len(cal.frontier) == 61


def test_routing_config_loader_validates(tmp_path: Path) -> None:
    from llmflow.routing.config import RoutingConfigError, load_router_params
    from llmflow.routing.policy import DEFAULT_PARAMS

    assert load_router_params(tmp_path / "missing.json") == DEFAULT_PARAMS
    good = tmp_path / "r.json"
    good.write_text(
        json.dumps(
            {
                "version": "v1",
                "params": {"base": {"low": 0.1, "balanced": 0.2, "high": 0.4}, "span": 0.6},
            }
        )
    )
    assert load_router_params(good).base_balanced == 0.2
    for bad in (
        {
            "version": "v",
            "params": {"base": {"low": 0.5, "balanced": 0.2, "high": 0.4}, "span": 0.5},
        },
        {"version": "v", "params": {"base": {"low": 0.1, "balanced": 0.2, "high": 4}, "span": 0.5}},
        {"params": {}},
    ):
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(bad))
        with pytest.raises(RoutingConfigError):
            load_router_params(p)
    p.write_text("not json")
    with pytest.raises(RoutingConfigError):
        load_router_params(p)


def test_lift_table_flags_a_signal_free_policy() -> None:
    from llmflow.bench.router_eval import lift_table

    easy = "What is 2+2?"
    items = _eval_items([True] * 10, [True] * 10, [easy] * 10)  # identical items: no way to rank
    cands = [model("small", Tier.SMALL, 0.5, 0.1), model("large", Tier.LARGE, 0.9, 1.0)]
    assert all(abs(r["lift"]) < 1e-9 for r in lift_table(items, cands, "small", "large"))
