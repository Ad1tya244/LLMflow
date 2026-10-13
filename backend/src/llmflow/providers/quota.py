"""In-process quota and cooldown tracking per model.

Windows are rolling (60 s and 24 h). Provider daily resets are calendar based and
differ per vendor; a rolling 24 h window is deliberately conservative.
State is process-local, which is correct for the single-instance free-tier deployment.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from llmflow.catalog import ModelSpec

_MINUTE = 60.0
_DAY = 86_400.0


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    rpm_used: int
    rpd_used: int
    tpd_used: int
    cooldown_s: float
    provider_disabled: bool
    headroom: float


class QuotaTracker:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._events: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._cooldown_until: dict[str, float] = {}
        self._disabled_providers: set[str] = set()

    def _prune(self, model_id: str, now: float) -> deque[tuple[float, int]]:
        events = self._events[model_id]
        while events and now - events[0][0] >= _DAY:
            events.popleft()
        return events

    def allows(self, spec: ModelSpec, est_tokens: int = 0) -> bool:
        now = self._clock()
        if spec.provider in self._disabled_providers:
            return False
        if self._cooldown_until.get(spec.id, 0.0) > now:
            return False
        events = self._prune(spec.id, now)
        lim = spec.limits
        if lim.rpm is not None and sum(1 for t, _ in events if now - t < _MINUTE) >= lim.rpm:
            return False
        if lim.tpm is not None:
            minute_tokens = sum(n for t, n in events if now - t < _MINUTE)
            if minute_tokens + est_tokens > lim.tpm:
                return False
        if lim.rpd is not None and len(events) >= lim.rpd:
            return False
        return not (lim.tpd is not None and sum(n for _, n in events) + est_tokens > lim.tpd)

    def headroom(self, spec: ModelSpec) -> float:
        """Fraction of the tightest configured limit still available, in [0, 1]."""
        now = self._clock()
        events = self._prune(spec.id, now)
        lim = spec.limits
        ratios = [1.0]
        if lim.rpm:
            used = sum(1 for t, _ in events if now - t < _MINUTE)
            ratios.append(1 - used / lim.rpm)
        if lim.tpm:
            used_tokens = sum(n for t, n in events if now - t < _MINUTE)
            ratios.append(1 - used_tokens / lim.tpm)
        if lim.rpd:
            ratios.append(1 - len(events) / lim.rpd)
        if lim.tpd:
            ratios.append(1 - sum(n for _, n in events) / lim.tpd)
        return max(0.0, min(ratios))

    def record(self, spec: ModelSpec, tokens: int) -> None:
        self._events[spec.id].append((self._clock(), tokens))

    def cool_down(self, model_id: str, seconds: float) -> None:
        self._cooldown_until[model_id] = self._clock() + seconds

    def disable_provider(self, provider_id: str) -> None:
        self._disabled_providers.add(provider_id)

    def snapshot_provider_disabled(self, provider_id: str) -> bool:
        return provider_id in self._disabled_providers

    def is_cooling(self, model_id: str) -> bool:
        return self._cooldown_until.get(model_id, 0.0) > self._clock()

    def snapshot(self, spec: ModelSpec) -> QuotaSnapshot:
        now = self._clock()
        events = self._prune(spec.id, now)
        return QuotaSnapshot(
            rpm_used=sum(1 for t, _ in events if now - t < _MINUTE),
            rpd_used=len(events),
            tpd_used=sum(n for _, n in events),
            cooldown_s=max(0.0, self._cooldown_until.get(spec.id, 0.0) - now),
            provider_disabled=spec.provider in self._disabled_providers,
            headroom=self.headroom(spec),
        )
