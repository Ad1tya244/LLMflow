from __future__ import annotations

import httpx
import pytest
import respx

from llmflow.catalog import ProviderSpec, Tier
from llmflow.core.errors import ProviderError, ProviderErrorKind
from llmflow.providers.openai_compat import OpenAICompatibleProvider

from .conftest import model

URL = "https://api.example.com/v1/chat/completions"


@pytest.fixture
async def provider() -> OpenAICompatibleProvider:
    spec = ProviderSpec(id="p1", base_url="https://api.example.com/v1/", api_key_env="K")
    return OpenAICompatibleProvider(spec, "secret", httpx.AsyncClient())


@respx.mock
async def test_chat_success_parses_usage_and_sends_auth(provider: OpenAICompatibleProvider) -> None:
    route = respx.post(URL).respond(
        json={"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}
    )
    done = await provider.chat(model("m", Tier.SMALL, 0.3, 0.1), {"model": "x"})
    assert done.usage.prompt_tokens == 7 and done.usage.completion_tokens == 3
    assert route.calls.last.request.headers["authorization"] == "Bearer secret"


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, ProviderErrorKind.RATE_LIMITED),
        (401, ProviderErrorKind.AUTH),
        (404, ProviderErrorKind.NOT_FOUND),
        (400, ProviderErrorKind.BAD_REQUEST),
        (503, ProviderErrorKind.SERVER),
    ],
)
@respx.mock
async def test_status_codes_map_to_error_kinds(
    provider: OpenAICompatibleProvider, status: int, kind: ProviderErrorKind
) -> None:
    respx.post(URL).respond(status, headers={"retry-after": "7"}, text="nope")
    with pytest.raises(ProviderError) as exc:
        await provider.chat(model("m", Tier.SMALL, 0.3, 0.1), {})
    assert exc.value.kind is kind
    assert exc.value.retry_after == 7.0
    assert exc.value.fallback_eligible is (kind is not ProviderErrorKind.BAD_REQUEST)


@respx.mock
async def test_timeout_maps_to_timeout_kind(provider: OpenAICompatibleProvider) -> None:
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderError) as exc:
        await provider.chat(model("m", Tier.SMALL, 0.3, 0.1), {})
    assert exc.value.kind is ProviderErrorKind.TIMEOUT


@respx.mock
async def test_stream_yields_sse_payloads_and_requests_usage(
    provider: OpenAICompatibleProvider,
) -> None:
    body = 'data: {"a":1}\n\ndata: {"usage":{"prompt_tokens":1}}\n\ndata: [DONE]\n\n'
    route = respx.post(URL).respond(200, text=body)
    out = [p async for p in provider.stream(model("m", Tier.SMALL, 0.3, 0.1), {"model": "x"})]
    assert out == ['{"a":1}', '{"usage":{"prompt_tokens":1}}', "[DONE]"]
    assert b'"include_usage"' in route.calls.last.request.content


@respx.mock
async def test_stream_error_raises_before_first_yield(provider: OpenAICompatibleProvider) -> None:
    respx.post(URL).respond(429, text="slow down")
    stream = provider.stream(model("m", Tier.SMALL, 0.3, 0.1), {})
    with pytest.raises(ProviderError) as exc:
        await anext(stream)
    assert exc.value.kind is ProviderErrorKind.RATE_LIMITED
