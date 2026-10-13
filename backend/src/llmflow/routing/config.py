"""Loading of calibrated router parameters from a small, versioned JSON file."""

from __future__ import annotations

import json
from pathlib import Path

from llmflow.routing.policy import DEFAULT_PARAMS, RouterParams


class RoutingConfigError(ValueError):
    pass


def _unit(value: object, name: str, lo: float = 0.0, hi: float = 1.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not lo <= float(value) <= hi
    ):
        raise RoutingConfigError(f"routing config: {name} must be a number in [{lo}, {hi}]")
    return float(value)


def parse_router_params(raw: dict[str, object]) -> RouterParams:
    params = raw.get("params")
    if not isinstance(params, dict):
        raise RoutingConfigError("routing config: missing 'params' object")
    base = params.get("base")
    if not isinstance(base, dict):
        raise RoutingConfigError("routing config: params.base must be an object")
    low, bal, high = (_unit(base.get(k), f"base.{k}") for k in ("low", "balanced", "high"))
    if not low <= bal <= high:
        raise RoutingConfigError("routing config: base values must satisfy low <= balanced <= high")
    version = raw.get("version")
    if not isinstance(version, str) or not version or len(version) > 64:
        raise RoutingConfigError("routing config: version must be a short string")
    return RouterParams(low, bal, high, _unit(params.get("span"), "span", 0.0, 2.0), version)


def load_router_params(path: Path) -> RouterParams:
    """Defaults when the file is absent; a malformed file is an error (never silently ignored)."""
    if not path.exists():
        return DEFAULT_PARAMS
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RoutingConfigError(f"{path}: not valid JSON") from exc
    if not isinstance(raw, dict):
        raise RoutingConfigError(f"{path}: expected a JSON object")
    return parse_router_params(raw)
