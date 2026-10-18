"""Per-key daily spend guard (UTC day). Costs are shadow costs at catalog list prices."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from llmflow.core.errors import GatewayError

_DAY = 86_400


@dataclass(slots=True)
class Spend:
    tokens: int = 0
    cost_usd: float = 0.0


def utc_day_start(ts: float) -> float:
    return ts - (ts % _DAY)


class BudgetGuard:
    def __init__(
        self,
        daily_usd: float | None,
        daily_tokens: int | None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.daily_usd = daily_usd
        self.daily_tokens = daily_tokens
        self._clock = clock
        self._day = utc_day_start(clock())
        self._spend: dict[str, Spend] = {}
        self._overrides: dict[str, tuple[float | None, int | None]] = {}

    def _roll(self) -> None:
        today = utc_day_start(self._clock())
        if today != self._day:
            self._day = today
            self._spend.clear()

    def hydrate(self, totals: dict[str, Spend]) -> None:
        """Seed today's counters from persisted usage after a restart."""
        self._roll()
        self._spend = {k: Spend(v.tokens, v.cost_usd) for k, v in totals.items()}

    def set_limits(self, key_id: str, usd: float | None, tokens: int | None) -> None:
        """Per-key (per-workspace) caps. They can only tighten the platform-wide caps."""
        if usd is None and tokens is None:
            self._overrides.pop(key_id, None)
        else:
            self._overrides[key_id] = (usd, tokens)

    def limits(self, key_id: str) -> tuple[float | None, int | None]:
        """Effective ``(usd, tokens)`` caps for a key: the stricter of platform and workspace."""
        own_usd, own_tokens = self._overrides.get(key_id, (None, None))

        def tighter(a: float | None, b: float | None) -> float | None:
            present = [v for v in (a, b) if v is not None]
            return min(present) if present else None

        usd = tighter(self.daily_usd, own_usd)
        tokens = tighter(
            None if self.daily_tokens is None else float(self.daily_tokens),
            None if own_tokens is None else float(own_tokens),
        )
        return usd, None if tokens is None else int(tokens)

    def spend(self, key_id: str) -> Spend:
        self._roll()
        return self._spend.get(key_id, Spend())

    def check(self, key_id: str) -> None:
        s = self.spend(key_id)
        daily_usd, daily_tokens = self.limits(key_id)
        if daily_usd is not None and s.cost_usd >= daily_usd:
            raise GatewayError(
                429, "budget_exceeded", "daily cost budget exhausted; resets 00:00 UTC"
            )
        if daily_tokens is not None and s.tokens >= daily_tokens:
            raise GatewayError(
                429, "budget_exceeded", "daily token budget exhausted; resets 00:00 UTC"
            )

    def record(self, key_id: str, tokens: int, cost_usd: float) -> None:
        self._roll()
        s = self._spend.setdefault(key_id, Spend())
        s.tokens += tokens
        s.cost_usd += cost_usd

    def snapshot(self) -> dict[str, Spend]:
        self._roll()
        return dict(self._spend)
