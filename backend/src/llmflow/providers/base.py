"""Provider abstraction. The router and service depend only on this protocol, so
non-OpenAI wire formats can be added as separate adapters without touching routing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from llmflow.catalog import ModelSpec
from llmflow.schemas import Usage


@dataclass(frozen=True, slots=True)
class Completion:
    body: dict[str, Any]
    usage: Usage
    latency_ms: float


class Provider(Protocol):
    async def chat(self, spec: ModelSpec, payload: dict[str, Any]) -> Completion: ...

    def stream(self, spec: ModelSpec, payload: dict[str, Any]) -> AsyncIterator[str]:
        """Yield SSE ``data:`` payload strings. Must raise ``ProviderError`` before the
        first yield on upstream failure so the caller can still fall back."""
        ...
