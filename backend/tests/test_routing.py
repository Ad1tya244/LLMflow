from __future__ import annotations

from llmflow.catalog import ModelSpec, Tier
from llmflow.providers.quota import QuotaTracker
from llmflow.routing.analyzer import analyze
from llmflow.routing.policy import plan_route, required_quality
from llmflow.schemas import ChatRequest, Message

from .conftest import model


def req(text: str, **kw: object) -> ChatRequest:
    return ChatRequest(messages=[Message(role="user", content=text)], **kw)  # type: ignore[arg-type]


def test_easy_prompt_scores_low_and_hard_prompt_scores_high() -> None:
    easy = analyze(req("What is the capital of France?"))
    hard = analyze(
        req(
            "Analyze and compare the trade-offs, derive the equation step by step, "
            "then debug this:\n```python\ndef f(x): return x\n```",
            max_tokens=2000,
        )
    )
    assert easy.difficulty < 0.1
    assert hard.difficulty > 0.6


def test_required_quality_rises_with_difficulty_and_quality_setting() -> None:
    assert required_quality(0.0, "balanced") < required_quality(1.0, "balanced")
    assert required_quality(0.5, "low") < required_quality(0.5, "high")
    assert required_quality(1.0, "high") == 1.0


def test_easy_request_goes_to_cheapest_adequate_model(
    small: ModelSpec, medium: ModelSpec, large: ModelSpec
) -> None:
    plan = plan_route(analyze(req("hi there")), [large, medium, small], QuotaTracker())
    assert plan.chain[0].id == "small"
    assert not plan.degraded


def test_hard_request_skips_models_below_required_quality(
    small: ModelSpec, medium: ModelSpec, large: ModelSpec
) -> None:
    hard = req("Analyze, compare and derive step by step. ```x```", max_tokens=2000)
    plan = plan_route(analyze(hard), [small, medium, large], QuotaTracker(), quality="high")
    assert plan.chain[0].id == "large"
    assert {m.id for m in plan.chain} == {"small", "medium", "large"}  # weaker ones as tail


def test_exhausted_quota_removes_model_and_falls_to_next(
    small: ModelSpec, medium: ModelSpec
) -> None:
    quota = QuotaTracker()
    limited = model("lim", Tier.SMALL, 0.4, 0.01, rpd=1)
    quota.record(limited, 10)
    plan = plan_route(analyze(req("hi")), [limited, small, medium], quota)
    assert "lim" not in [m.id for m in plan.chain]


def test_no_model_meets_quality_degrades_to_best_available(small: ModelSpec) -> None:
    hard = req("Analyze, compare, derive step by step ```x```", max_tokens=2000)
    plan = plan_route(analyze(hard), [small], QuotaTracker(), quality="high")
    assert plan.degraded
    assert plan.chain[0].id == "small"


def test_strict_privacy_excludes_untrusted_providers(small: ModelSpec, large: ModelSpec) -> None:
    plan = plan_route(
        analyze(req("hi")),
        [small, large],
        QuotaTracker(),
        strict_privacy=True,
        untrusted_providers=frozenset({"p2"}),
    )
    assert [m.id for m in plan.chain] == ["small"]


def test_context_window_filters_models(small: ModelSpec) -> None:
    huge = req("x" * 100_000)
    plan = plan_route(analyze(huge), [small], QuotaTracker())
    assert plan.chain == ()
