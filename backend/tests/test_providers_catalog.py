"""Shipped catalog (Groq, OpenAI, Gemini), pin-only models, and the streaming-usage switch."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

from llmflow.api.app import create_app
from llmflow.catalog import Catalog, ProviderSpec, Tier, load_catalog
from llmflow.core.config import Settings
from llmflow.providers.openai_compat import OpenAICompatibleProvider

from .conftest import FakeProvider, model

CONFIG = Path(__file__).parents[1] / "config" / "catalog.yaml"
AUTH = {"Authorization": "Bearer test-key"}
BODY = {"model": "auto", "messages": [{"role": "user", "content": "hi"}]}


def test_shipped_catalog_has_three_providers_and_a_pin_only_qwen() -> None:
    cat = load_catalog(CONFIG)
    assert {"groq", "openai", "gemini"} <= set(cat.providers)
    gemini = cat.providers["gemini"]
    assert gemini.base_url.startswith("https://generativelanguage.googleapis.com/")
    assert gemini.trains_on_data is True and gemini.stream_usage is False
    assert {m.id for m in cat.models.values() if m.provider == "gemini"} == {
        "gemini-2.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    }
    qwen = cat.models["groq-qwen3.8-27b"]
    assert qwen.enabled and qwen.auto_route is False
    assert (qwen.price_in, qwen.price_out) == (0.80, 4.00)
    # every other shipped model stays eligible for automatic routing
    assert all(m.auto_route for m in cat.models.values() if m.id != qwen.id)


def _app(catalog: Catalog) -> TestClient:
    settings = Settings(
        _env_file=None,
        api_keys="test-key",
        min_key_length=1,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings, catalog=catalog, providers={"p1": FakeProvider()}, env={"K1": "x"})
    client = TestClient(app)
    client.__enter__()
    return client


def test_pin_only_model_is_never_auto_routed_but_can_be_named() -> None:
    cheap_but_pin_only = model("pinonly", Tier.MEDIUM, 0.6, 0.001).model_copy(
        update={"auto_route": False}
    )
    normal = model("normal", Tier.LARGE, 0.9, 1.0)
    cat = Catalog(
        providers={"p1": ProviderSpec(id="p1", base_url="http://p1", api_key_env="K1")},
        models={m.id: m for m in (cheap_but_pin_only, normal)},
    )
    client = _app(cat)
    try:
        auto = client.post("/v1/chat/completions", headers=AUTH, json=BODY)
        assert auto.status_code == 200 and auto.headers["x-llmflow-model"] == "normal"
        listed = [m["id"] for m in client.get("/v1/models", headers=AUTH).json()["data"]]
        assert "pinonly" in listed  # visible, so it can be chosen
        pinned = client.post(
            "/v1/chat/completions", headers=AUTH, json={**BODY, "model": "pinonly"}
        )
        assert pinned.status_code == 200 and pinned.headers["x-llmflow-model"] == "pinonly"
    finally:
        client.__exit__(None, None, None)


URL = "https://api.example.com/v1/chat/completions"


@respx.mock
async def test_stream_usage_option_is_sent_only_when_enabled() -> None:
    for flag in (True, False):
        spec = ProviderSpec(
            id="p", base_url="https://api.example.com/v1", api_key_env="K", stream_usage=flag
        )
        provider = OpenAICompatibleProvider(spec, "secret", httpx.AsyncClient())
        route = respx.post(URL).respond(
            content=b'data: {"choices":[]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )
        _ = [p async for p in provider.stream(model("m", Tier.SMALL, 0.3, 0.1), {"model": "x"})]
        sent = json.loads(route.calls.last.request.content)
        assert sent["stream"] is True
        assert ("stream_options" in sent) is flag
        respx.reset()
