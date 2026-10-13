from __future__ import annotations

from llmflow.catalog import Tier
from llmflow.providers.quota import QuotaTracker

from .conftest import model


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def test_rpm_window_slides() -> None:
    clock = Clock()
    q = QuotaTracker(clock)
    m = model("m", Tier.SMALL, 0.3, 0.1, rpm=2)
    q.record(m, 1)
    q.record(m, 1)
    assert not q.allows(m)
    clock.t += 61
    assert q.allows(m)


def test_daily_token_limit_counts_estimate() -> None:
    q = QuotaTracker(Clock())
    m = model("m", Tier.SMALL, 0.3, 0.1, tpd=100)
    q.record(m, 90)
    assert q.allows(m, est_tokens=10)
    assert not q.allows(m, est_tokens=11)


def test_cooldown_expires() -> None:
    clock = Clock()
    q = QuotaTracker(clock)
    m = model("m", Tier.SMALL, 0.3, 0.1)
    q.cool_down("m", 30)
    assert not q.allows(m)
    clock.t += 31
    assert q.allows(m)


def test_disabled_provider_blocks_all_its_models() -> None:
    q = QuotaTracker(Clock())
    q.disable_provider("p1")
    assert not q.allows(model("m", Tier.SMALL, 0.3, 0.1, provider="p1"))


def test_headroom_reflects_tightest_limit() -> None:
    q = QuotaTracker(Clock())
    m = model("m", Tier.SMALL, 0.3, 0.1, rpd=10, tpd=1000)
    for _ in range(5):
        q.record(m, 10)
    assert q.headroom(m) == 0.5


def test_tokens_per_minute_window_slides_and_counts_estimate() -> None:
    clock = Clock()
    q = QuotaTracker(clock)
    m = model("m", Tier.SMALL, 0.3, 0.1, tpm=1000)
    q.record(m, 800)
    assert q.allows(m, est_tokens=200)
    assert not q.allows(m, est_tokens=201)
    clock.t += 61
    assert q.allows(m, est_tokens=1000)
