from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from llmflow.catalog import Catalog, Limits, ModelSpec, ProviderSpec, Tier
from llmflow.core.errors import ProviderError
from llmflow.providers.base import Completion
from llmflow.schemas import Usage


def model(
    mid: str, tier: Tier, quality: float, price: float, provider: str = "p1", **limits: int
) -> ModelSpec:
    return ModelSpec(
        id=mid,
        provider=provider,
        upstream_model=f"up-{mid}",
        tier=tier,
        quality=quality,
        context_window=8000,
        price_in=price,
        price_out=price,
        limits=Limits(**limits),
    )


@pytest.fixture
def small() -> ModelSpec:
    return model("small", Tier.SMALL, 0.35, 0.05)


@pytest.fixture
def medium() -> ModelSpec:
    return model("medium", Tier.MEDIUM, 0.6, 0.3)


@pytest.fixture
def large() -> ModelSpec:
    return model("large", Tier.LARGE, 0.85, 1.0, provider="p2")


@pytest.fixture
def catalog(small: ModelSpec, medium: ModelSpec, large: ModelSpec) -> Catalog:
    return Catalog(
        providers={
            "p1": ProviderSpec(id="p1", base_url="http://p1", api_key_env="K1"),
            "p2": ProviderSpec(
                id="p2", base_url="http://p2", api_key_env="K2", trains_on_data=True
            ),
        },
        models={m.id: m for m in (small, medium, large)},
    )


class FakeProvider:
    """Scripted provider: each call pops the next outcome (Exception or Completion)."""

    def __init__(self, outcomes: list[Any] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def chat(self, spec: ModelSpec, payload: dict[str, Any]) -> Completion:
        self.calls.append((spec.id, payload))
        outcome = self.outcomes.pop(0) if self.outcomes else ok_completion()
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, Completion)
        return outcome

    async def stream(self, spec: ModelSpec, payload: dict[str, Any]) -> AsyncIterator[str]:
        self.calls.append((spec.id, payload))
        outcome = self.outcomes.pop(0) if self.outcomes else ["{}", "[DONE]"]
        if isinstance(outcome, ProviderError):
            raise outcome
        for item in outcome:
            yield item


def ok_completion(prompt: int = 10, completion: int = 5) -> Completion:
    return Completion(
        body={
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
        },
        usage=Usage(prompt_tokens=prompt, completion_tokens=completion),
        latency_ms=12.0,
    )
