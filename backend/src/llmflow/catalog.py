"""Provider/model catalog loaded from YAML. Pure data; no network access."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field


class Tier(IntEnum):
    SMALL = 1
    MEDIUM = 2
    LARGE = 3


_TIER_NAMES = {"small": Tier.SMALL, "medium": Tier.MEDIUM, "large": Tier.LARGE}


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True)
    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None
    tpd: int | None = None


class ProviderSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    base_url: str
    api_key_env: str
    trains_on_data: bool = False
    # Ask for token usage on streamed replies (``stream_options.include_usage``). Turn off for a
    # provider whose OpenAI-compatible layer rejects that option; streamed token counts are then
    # estimated (about 4 characters per token) and the route reason says so.
    stream_usage: bool = True


class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    provider: str
    upstream_model: str
    tier: Tier
    quality: float = Field(ge=0, le=1)
    context_window: int = Field(gt=0)
    price_in: float = Field(ge=0, description="USD per 1M input tokens (shadow)")
    price_out: float = Field(ge=0, description="USD per 1M output tokens (shadow)")
    limits: Limits = Limits()
    enabled: bool = True  # operator switch; a model with enabled=false is never routed to
    # false = never chosen by the router, but still listed and usable when a request names it
    auto_route: bool = True

    def shadow_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.price_in + completion_tokens * self.price_out) / 1_000_000


class Catalog(BaseModel):
    providers: dict[str, ProviderSpec]
    models: dict[str, ModelSpec]

    def enabled_models(self, env: Mapping[str, str]) -> list[ModelSpec]:
        """Models whose provider has an API key present in ``env``."""
        return [
            m
            for m in self.models.values()
            if m.enabled and env.get(self.providers[m.provider].api_key_env, "").strip()
        ]


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def load_catalog(path: Path) -> Catalog:
    """Load ``path`` plus every ``catalog.d/*.yaml`` next to it (added by
    ``python -m llmflow.tools.add_provider``). Ids must be unique across all files."""
    sources = [path, *sorted((path.parent / "catalog.d").glob("*.yaml"))]
    providers: dict[str, ProviderSpec] = {}
    models: dict[str, ModelSpec] = {}
    for src in sources:
        raw = _read_yaml(src)
        for pid, spec in (raw.get("providers") or {}).items():
            if pid in providers:
                raise ValueError(f"{src}: duplicate provider id {pid!r}")
            providers[pid] = ProviderSpec(id=pid, **spec)
        for item in raw.get("models") or []:
            item = dict(item)
            item["tier"] = _TIER_NAMES[item["tier"]]
            model = ModelSpec(**item)
            if model.id in models:
                raise ValueError(f"{src}: duplicate model id {model.id!r}")
            models[model.id] = model
    for m in models.values():
        if m.provider not in providers:
            raise ValueError(f"model {m.id!r} references unknown provider {m.provider!r}")
    return Catalog(providers=providers, models=models)


def environment(dotenv_path: Path = Path(".env")) -> Mapping[str, str]:
    """Process environment overlaid on a local ``.env`` file (real env vars win)."""
    from_file = {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
    return {**from_file, **os.environ}
