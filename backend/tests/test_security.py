"""Security-focused behaviour: authz scopes, abuse limits, headers, data hygiene."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmflow.api.app import create_app
from llmflow.budget import BudgetGuard, Spend
from llmflow.cache import ResponseCache
from llmflow.catalog import Catalog
from llmflow.core.config import Settings
from llmflow.core.errors import ProviderError, ProviderErrorKind
from llmflow.core.ratelimit import SlidingWindowLimiter
from llmflow.storage.usage import UsageRepo

from .conftest import FakeProvider, ok_completion

CLIENT = {"Authorization": "Bearer client-key"}
ADMIN = {"Authorization": "Bearer admin-key"}
BODY = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}
ENV = {"K1": "x", "K2": "y"}

Builder = Callable[..., TestClient]


@pytest.fixture
def build(catalog: Catalog):  # type: ignore[no-untyped-def]
    opened: list[TestClient] = []

    def make(p1: FakeProvider | None = None, **overrides: object) -> TestClient:
        base: dict[str, object] = {
            "api_keys": "client-key,other-key",
            "admin_api_keys": "admin-key",
            "database_url": "sqlite+aiosqlite:///:memory:",
            "min_key_length": 1,
        }
        settings = Settings(_env_file=None, **{**base, **overrides})  # type: ignore[arg-type]
        app = create_app(
            settings,
            catalog=catalog,
            providers={"p1": p1 or FakeProvider(), "p2": FakeProvider()},
            env=ENV,
        )
        c = TestClient(app)
        c.__enter__()
        opened.append(c)
        return c

    yield make
    for c in opened:
        c.__exit__(None, None, None)


# --- authorization scopes -------------------------------------------------------


def test_admin_is_disabled_without_admin_keys(build: Builder) -> None:
    c = build(admin_api_keys="")
    r = c.get("/admin/overview", headers=ADMIN)
    assert r.status_code == 403


def test_client_key_cannot_reach_admin_and_admin_key_cannot_chat(build: Builder) -> None:
    c = build()
    assert c.get("/admin/overview", headers=CLIENT).status_code == 401
    assert c.post("/v1/chat/completions", json=BODY, headers=ADMIN).status_code == 401


def test_weak_keys_are_refused() -> None:
    with pytest.raises(RuntimeError, match="at least"):
        create_app(Settings(_env_file=None, api_keys="short"))


def test_admin_and_client_keys_must_differ() -> None:
    with pytest.raises(RuntimeError):
        create_app(
            Settings(_env_file=None, api_keys="same", admin_api_keys="same", min_key_length=1)
        )


def test_failed_auth_attempts_are_throttled_per_ip(build: Builder) -> None:
    c = build(auth_fail_limit_per_min=3)
    bad = {"Authorization": "Bearer wrong"}
    codes = [c.get("/v1/models", headers=bad).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3] == 429
    blocked = c.get("/v1/models", headers=bad)
    assert blocked.headers["retry-after"].isdigit()
    # even a valid key is held back while the IP is throttled (no oracle for guessing)
    assert c.get("/v1/models", headers=CLIENT).status_code == 429


# --- abuse limits ---------------------------------------------------------------


def test_per_key_rate_limit(build: Builder) -> None:
    c = build(rate_limit_rpm=2)
    statuses = [
        c.post("/v1/chat/completions", json=BODY, headers=CLIENT).status_code for _ in range(3)
    ]
    assert statuses == [200, 200, 429]
    # a different key has its own bucket
    other = {"Authorization": "Bearer other-key"}
    assert c.post("/v1/chat/completions", json=BODY, headers=other).status_code == 200


def test_oversized_body_is_rejected(build: Builder) -> None:
    c = build(max_body_bytes=2000)
    big = {"model": "auto", "messages": [{"role": "user", "content": "x" * 5000}]}
    r = c.post("/v1/chat/completions", json=big, headers=CLIENT)
    assert r.status_code == 413


@pytest.mark.parametrize(
    ("patch", "status"),
    [
        ({"messages": [{"role": "user", "content": "a"}] * 6}, 422),
        ({"max_tokens": 99_999}, 422),
        ({"n": 3}, 422),
        ({"messages": [{"role": "user", "content": "z" * 300}]}, 413),
    ],
)
def test_request_limits(build: Builder, patch: dict[str, object], status: int) -> None:
    c = build(max_messages=5, max_prompt_chars=200, max_tokens_cap=1000)
    r = c.post("/v1/chat/completions", json={**BODY, **patch}, headers=CLIENT)
    assert r.status_code == status


def test_validation_errors_do_not_echo_input(build: Builder) -> None:
    c = build()
    secret = "super-secret-prompt-text"
    r = c.post("/v1/chat/completions", json={"messages": secret}, headers=CLIENT)
    assert r.status_code == 422
    assert secret not in r.text


# --- hygiene --------------------------------------------------------------------


def test_security_headers_and_no_store(build: Builder) -> None:
    c = build()
    r = c.get("/v1/models", headers=CLIENT)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert len(r.headers["x-request-id"]) == 32


def test_docs_are_off_by_default(build: Builder) -> None:
    c = build()
    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404
    assert build(enable_docs=True).get("/docs").status_code == 200


def test_only_allowlisted_params_reach_the_provider(build: Builder) -> None:
    p1 = FakeProvider()
    c = build(p1)
    evil = {
        **BODY,
        "temperature": 0.2,
        "base_url": "http://169.254.169.254",
        "stream_options": {"include_usage": False},
        "x_provider_secret": "1",
    }
    assert c.post("/v1/chat/completions", json=evil, headers=CLIENT).status_code == 200
    sent = p1.calls[0][1]
    assert sent["temperature"] == 0.2
    assert not {"base_url", "stream_options", "x_provider_secret", "llmflow", "stream"} & set(sent)


def test_unhandled_errors_are_sanitised(build: Builder) -> None:
    p1 = FakeProvider([RuntimeError("db password is hunter2")])
    app = build(p1).app
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/v1/chat/completions", json=BODY, headers=CLIENT)
    assert r.status_code == 500
    assert "hunter2" not in r.text


def test_upstream_error_text_is_not_leaked(build: Builder) -> None:
    raw = "internal: key sk-live-123 invalid for org-9"
    err = ProviderError(ProviderErrorKind.BAD_REQUEST, raw, status=400, client_message="bad param")
    c = build(FakeProvider([err]))
    r = c.post("/v1/chat/completions", json=BODY, headers=CLIENT)
    assert r.status_code == 400
    assert "sk-live" not in r.text and r.json()["error"]["message"] == "bad param"


# --- cache ----------------------------------------------------------------------


def test_cache_hits_for_deterministic_requests_and_is_tenant_scoped(build: Builder) -> None:
    p1 = FakeProvider([ok_completion(), ok_completion()])
    c = build(p1)
    body = {**BODY, "temperature": 0}
    first = c.post("/v1/chat/completions", json=body, headers=CLIENT)
    second = c.post("/v1/chat/completions", json=body, headers=CLIENT)
    assert first.headers["x-llmflow-cache"] == "miss"
    assert second.headers["x-llmflow-cache"] == "hit"
    assert second.headers["x-llmflow-attempts"] == "0"
    assert len(p1.calls) == 1
    other = c.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer other-key"})
    assert other.headers["x-llmflow-cache"] == "miss"  # no cross-tenant leakage
    assert len(p1.calls) == 2


def test_cache_skipped_by_default_and_when_off(build: Builder) -> None:
    p1 = FakeProvider()
    c = build(p1)
    c.post("/v1/chat/completions", json=BODY, headers=CLIENT)
    c.post("/v1/chat/completions", json=BODY, headers=CLIENT)
    assert len(p1.calls) == 2  # no temperature=0, not cached
    off = {**BODY, "temperature": 0, "llmflow": {"cache": "off"}}
    c.post("/v1/chat/completions", json=off, headers=CLIENT)
    c.post("/v1/chat/completions", json=off, headers=CLIENT)
    assert len(p1.calls) == 4


def test_cache_ttl_zero_disables(build: Builder) -> None:
    p1 = FakeProvider()
    c = build(p1, cache_ttl_s=0)
    body = {**BODY, "temperature": 0}
    c.post("/v1/chat/completions", json=body, headers=CLIENT)
    c.post("/v1/chat/completions", json=body, headers=CLIENT)
    assert len(p1.calls) == 2


# --- budget ---------------------------------------------------------------------


def test_daily_token_budget_blocks_further_requests(build: Builder) -> None:
    p1 = FakeProvider([ok_completion(100, 50)])
    c = build(p1, daily_token_budget=100)
    assert c.post("/v1/chat/completions", json=BODY, headers=CLIENT).status_code == 200
    r = c.post("/v1/chat/completions", json=BODY, headers=CLIENT)
    assert r.status_code == 429 and r.json()["error"]["type"] == "budget_exceeded"
    usage = c.get("/admin/budgets", headers=ADMIN).json()
    assert usage["daily_token_budget"] == 100 and usage["keys"][0]["tokens"] == 150


def test_admin_config_has_no_secrets(build: Builder) -> None:
    c = build()
    text = c.get("/admin/config", headers=ADMIN).text
    for secret in ("client-key", "admin-key", "other-key"):
        assert secret not in text


# --- units ----------------------------------------------------------------------


def test_sliding_window_limiter_expires_hits() -> None:
    t = [0.0]
    lim = SlidingWindowLimiter(2, 60, clock=lambda: t[0])
    assert lim.acquire("a") is None and lim.acquire("a") is None
    assert lim.acquire("a") is not None
    t[0] = 61
    assert lim.acquire("a") is None


def test_budget_rolls_over_at_utc_midnight() -> None:
    t = [86_400.0 * 10 + 100]
    g = BudgetGuard(1.0, None, clock=lambda: t[0])
    g.record("k", 10, 1.5)
    with pytest.raises(Exception, match="budget"):
        g.check("k")
    t[0] += 86_400
    g.check("k")  # new day, counters reset
    g.hydrate({"k": Spend(5, 0.1)})
    assert g.spend("k").tokens == 5


def test_response_cache_lru_and_ttl() -> None:
    t = [0.0]
    cache = ResponseCache(ttl_s=10, max_entries=2, clock=lambda: t[0])
    cache.put("a", {"x": 1}, "m", "p", (1, 1))
    cache.put("b", {"x": 2}, "m", "p", (1, 1))
    cache.get("a")  # refresh a
    cache.put("c", {"x": 3}, "m", "p", (1, 1))  # evicts b
    assert cache.get("b") is None and cache.get("a") is not None
    t[0] = 11
    assert cache.get("a") is None


async def test_schema_migration_adds_missing_column(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE request_log (id INTEGER PRIMARY KEY, ts FLOAT, key_id VARCHAR(32), "
            "requested_model VARCHAR(128), model VARCHAR(128), provider VARCHAR(64), "
            "status VARCHAR(16), prompt_tokens INT, completion_tokens INT, latency_ms FLOAT, "
            "shadow_cost_usd FLOAT, attempts INT, route_reason VARCHAR(512))"
        )
        conn.execute("INSERT INTO request_log (ts, key_id, status) VALUES (1, 'k', 'ok')")
    repo = UsageRepo(f"sqlite+aiosqlite:///{db}")
    await repo.init()
    rows, total = await repo.page(10, 0)
    await repo.close()
    assert total == 1 and rows[0].cache_status == "none"
