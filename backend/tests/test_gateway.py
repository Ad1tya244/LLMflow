from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from llmflow.api.app import create_app
from llmflow.catalog import Catalog
from llmflow.core.config import Settings
from llmflow.core.errors import ProviderError, ProviderErrorKind

from .conftest import FakeProvider, ok_completion

KEY = "test-key"
AUTH = {"Authorization": f"Bearer {KEY}"}
ENV = {"K1": "x", "K2": "y"}


@pytest.fixture
def make_client(catalog: Catalog):  # type: ignore[no-untyped-def]
    clients: list[TestClient] = []

    def build(p1: FakeProvider, p2: FakeProvider | None = None) -> TestClient:
        settings = Settings(
            _env_file=None,
            api_keys=KEY,
            min_key_length=1,
            database_url="sqlite+aiosqlite:///:memory:",
        )
        app = create_app(
            settings,
            catalog=catalog,
            providers={"p1": p1, "p2": p2 or FakeProvider()},
            env=ENV,
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for c in clients:
        c.__exit__(None, None, None)


BODY = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}


def test_requires_auth(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(FakeProvider())
    assert c.post("/v1/chat/completions", json=BODY).status_code == 401
    bad = c.post("/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    assert c.get("/healthz").status_code == 200


def test_refuses_to_start_without_keys(catalog: Catalog) -> None:
    with pytest.raises(RuntimeError):
        create_app(Settings(_env_file=None, api_keys="", auth_disabled=False), catalog=catalog)


def test_auto_routes_easy_prompt_to_cheapest_and_reports_metadata(make_client) -> None:  # type: ignore[no-untyped-def]
    p1 = FakeProvider([ok_completion(10, 5)])
    c = make_client(p1)
    r = c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["x-llmflow-model"] == "small"
    assert float(r.headers["x-llmflow-shadow-cost-usd"]) > 0
    assert p1.calls[0][1]["model"] == "up-small"
    assert "llmflow" not in p1.calls[0][1]  # gateway-only field stripped


def test_falls_back_when_first_model_rate_limited(make_client) -> None:  # type: ignore[no-untyped-def]
    p1 = FakeProvider(
        [
            ProviderError(ProviderErrorKind.RATE_LIMITED, "429", status=429, retry_after=60),
            ok_completion(),
        ]
    )
    c = make_client(p1)
    r = c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["x-llmflow-model"] == "medium"
    assert r.headers["x-llmflow-attempts"] == "2"
    # the rate-limited model is now cooling down and skipped next time
    r2 = c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert r2.headers["x-llmflow-model"] == "medium"
    assert r2.headers["x-llmflow-attempts"] == "1"


def test_bad_request_is_not_retried_elsewhere(make_client) -> None:  # type: ignore[no-untyped-def]
    p1 = FakeProvider([ProviderError(ProviderErrorKind.BAD_REQUEST, "bad", status=400)])
    c = make_client(p1)
    r = c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert r.status_code == 400
    assert len(p1.calls) == 1


def test_all_failing_returns_503(make_client) -> None:  # type: ignore[no-untyped-def]
    boom = ProviderError(ProviderErrorKind.SERVER, "boom", status=500)
    c = make_client(FakeProvider([boom, boom, boom]), FakeProvider([boom]))
    r = c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert r.status_code == 503
    assert r.json()["error"]["type"] == "all_providers_failed"


def test_auth_failure_disables_provider(make_client) -> None:  # type: ignore[no-untyped-def]
    p1 = FakeProvider([ProviderError(ProviderErrorKind.AUTH, "no", status=401)])
    c = make_client(p1)
    first = c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert first.headers["x-llmflow-provider"] == "p2"
    models = c.get("/v1/models", headers=AUTH).json()["data"]
    assert {m["id"] for m in models} >= {"auto", "small", "large"}


def test_pinned_model_and_unknown_model(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(FakeProvider())
    ok = c.post("/v1/chat/completions", json={**BODY, "model": "large"}, headers=AUTH)
    assert ok.headers["x-llmflow-model"] == "large"
    missing = c.post("/v1/chat/completions", json={**BODY, "model": "nope"}, headers=AUTH)
    assert missing.status_code == 404


def test_fallback_can_be_disabled_per_request(make_client) -> None:  # type: ignore[no-untyped-def]
    boom = ProviderError(ProviderErrorKind.SERVER, "boom", status=500)
    p1 = FakeProvider([boom])
    c = make_client(p1)
    r = c.post(
        "/v1/chat/completions",
        json={**BODY, "llmflow": {"fallback": False}},
        headers=AUTH,
    )
    assert r.status_code == 503
    assert len(p1.calls) == 1


def test_streaming_passthrough_and_pre_stream_fallback(make_client) -> None:  # type: ignore[no-untyped-def]
    chunks = [json.dumps({"choices": [{"delta": {"content": "a"}}]}), "[DONE]"]
    p1 = FakeProvider([ProviderError(ProviderErrorKind.SERVER, "boom", status=502), chunks])
    c = make_client(p1)
    with c.stream("POST", "/v1/chat/completions", json={**BODY, "stream": True}, headers=AUTH) as r:
        assert r.status_code == 200
        assert r.headers["x-llmflow-model"] == "medium"
        text = "".join(r.iter_text())
    assert text.count("data: ") == 2 and text.rstrip().endswith("[DONE]")


def test_usage_is_recorded(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(FakeProvider([ok_completion(100, 50)]))
    c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    usage = c.app.state.usage  # type: ignore[attr-defined]
    result = c.portal.call(usage.summary)  # type: ignore[union-attr]
    assert result.requests == 1
    assert result.prompt_tokens == 100 and result.completion_tokens == 50
    assert result.shadow_cost_usd > 0


# --- pinned models are never swapped silently; skips and failures are explained ----------------


def _auth_failure() -> ProviderError:
    return ProviderError(
        ProviderErrorKind.AUTH, "401", status=401, client_message="API key not valid"
    )


def test_pinned_model_does_not_fall_back_and_says_why(make_client) -> None:  # type: ignore[no-untyped-def]
    p2 = FakeProvider([_auth_failure()])  # "large" lives on provider p2
    c = make_client(FakeProvider(), p2)
    pinned = {**BODY, "model": "large"}

    first = c.post("/v1/chat/completions", json=pinned, headers=AUTH)
    assert first.status_code == 503
    msg = first.json()["error"]["message"]
    assert "large failed (auth: API key not valid)" in msg

    # the provider is now disabled; the next call must say so instead of quietly using another
    second = c.post("/v1/chat/completions", json=pinned, headers=AUTH)
    assert second.status_code == 503
    assert "large skipped: its provider rejected the API key" in second.json()["error"]["message"]


def test_pinned_model_may_fall_back_only_when_the_caller_allows_it(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(FakeProvider(), FakeProvider([_auth_failure()]))
    allowed = {**BODY, "model": "large", "llmflow": {"fallback": True}}
    r = c.post("/v1/chat/completions", json=allowed, headers=AUTH)
    assert r.status_code == 200 and r.headers["x-llmflow-model"] != "large"
    assert "pinned to large" in r.headers["x-llmflow-route-reason"]
    assert "large failed (auth: API key not valid)" in r.headers["x-llmflow-route-reason"]

    r2 = c.post("/v1/chat/completions", json=allowed, headers=AUTH)  # now skipped, still explained
    assert r2.status_code == 200
    assert (
        "large skipped: its provider rejected the API key" in r2.headers["x-llmflow-route-reason"]
    )


def test_auto_fallback_is_reflected_in_the_route_reason(make_client) -> None:  # type: ignore[no-untyped-def]
    boom = ProviderError(ProviderErrorKind.SERVER, "boom", status=500, client_message="overloaded")
    c = make_client(FakeProvider([boom]))
    r = c.post("/v1/chat/completions", json=BODY, headers=AUTH)
    assert r.status_code == 200
    reason = r.headers["x-llmflow-route-reason"]
    assert "before that: small failed (server: overloaded)" in reason
    assert r.headers["x-llmflow-attempts"] == "2"


def test_pinned_streaming_reports_the_real_failure(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(FakeProvider(), FakeProvider([_auth_failure()]))
    r = c.post(
        "/v1/chat/completions", json={**BODY, "model": "large", "stream": True}, headers=AUTH
    )
    assert r.status_code == 503
    assert "large failed (auth: API key not valid)" in r.json()["error"]["message"]
