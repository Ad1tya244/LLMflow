"""Adapter for any provider that speaks the OpenAI chat-completions wire format."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from llmflow.catalog import ModelSpec, ProviderSpec
from llmflow.core.errors import ProviderError, ProviderErrorKind
from llmflow.providers.base import Completion
from llmflow.schemas import Usage

_ERROR_BODY_LIMIT = 300


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _classify(status: int) -> ProviderErrorKind:
    if status == 429:
        return ProviderErrorKind.RATE_LIMITED
    if status in (401, 403):
        return ProviderErrorKind.AUTH
    if status == 404:
        return ProviderErrorKind.NOT_FOUND
    if status == 408:
        return ProviderErrorKind.TIMEOUT
    if status >= 500:
        return ProviderErrorKind.SERVER
    return ProviderErrorKind.BAD_REQUEST


def _upstream_message(body: bytes) -> str | None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    err = parsed.get("error") if isinstance(parsed, dict) else None
    msg = err.get("message") if isinstance(err, dict) else None
    if not isinstance(msg, str):
        return None
    return "".join(ch for ch in msg if ch.isprintable())[:_ERROR_BODY_LIMIT]


def _to_error(response: httpx.Response, body: bytes) -> ProviderError:
    snippet = body[:_ERROR_BODY_LIMIT].decode("utf-8", errors="replace")
    return ProviderError(
        _classify(response.status_code),
        f"upstream {response.status_code}: {snippet}",
        status=response.status_code,
        retry_after=_retry_after(response),
        client_message=_upstream_message(body),
    )


def _usage_from(body: dict[str, Any]) -> Usage:
    raw = body.get("usage") or {}
    return Usage(
        prompt_tokens=int(raw.get("prompt_tokens") or 0),
        completion_tokens=int(raw.get("completion_tokens") or 0),
    )


class OpenAICompatibleProvider:
    def __init__(self, spec: ProviderSpec, api_key: str, client: httpx.AsyncClient) -> None:
        self._spec = spec
        self._client = client
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._url = f"{spec.base_url.rstrip('/')}/chat/completions"

    async def chat(self, spec: ModelSpec, payload: dict[str, Any]) -> Completion:
        started = time.perf_counter()
        try:
            response = await self._client.post(self._url, json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "upstream timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorKind.SERVER, f"transport error: {exc}") from exc
        if response.status_code >= 400:
            raise _to_error(response, response.content)
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(ProviderErrorKind.SERVER, "upstream returned invalid JSON") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        return Completion(body=body, usage=_usage_from(body), latency_ms=latency_ms)

    async def stream(self, spec: ModelSpec, payload: dict[str, Any]) -> AsyncIterator[str]:
        body = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        try:
            async with self._client.stream(
                "POST", self._url, json=body, headers=self._headers
            ) as response:
                if response.status_code >= 400:
                    raise _to_error(response, await response.aread())
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        yield line[5:].strip()
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderErrorKind.TIMEOUT, "upstream timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorKind.SERVER, f"transport error: {exc}") from exc
