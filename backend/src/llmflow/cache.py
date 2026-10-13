"""Exact-match response cache: bounded LRU with TTL, scoped per client key.

Only deterministic requests are cached by default (``temperature == 0``) or when the
caller opts in. Keys include the client key id so tenants never see each other's answers.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llmflow.schemas import ChatRequest

_MAX_ENTRY_BYTES = 64_000
_KEY_FIELDS = (
    "model", "messages", "temperature", "top_p", "max_tokens", "max_completion_tokens",
    "stop", "seed", "response_format", "tools", "tool_choice", "presence_penalty",
    "frequency_penalty", "n",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class CacheEntry:
    body: dict[str, Any]
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    expires_at: float


def is_cacheable(request: ChatRequest) -> bool:
    if request.stream:
        return False
    mode = request.llmflow.cache
    if mode == "off":
        return False
    if mode == "on":
        return True
    return request.model_extra is not None and request.model_extra.get("temperature") == 0


def cache_key(key_id: str, request: ChatRequest) -> str:
    dumped = request.model_dump()
    payload = {f: dumped.get(f) for f in _KEY_FIELDS}
    payload["_k"] = key_id
    payload["_q"] = [request.llmflow.quality, request.llmflow.privacy]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class ResponseCache:
    def __init__(
        self, ttl_s: int, max_entries: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock
        self._data: OrderedDict[str, CacheEntry] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str) -> CacheEntry | None:
        entry = self._data.get(key)
        if entry is None or entry.expires_at <= self._clock():
            self._data.pop(key, None)
            self.misses += 1
            return None
        self._data.move_to_end(key)
        self.hits += 1
        return entry

    def put(
        self, key: str, body: dict[str, Any], model: str, provider: str, usage: tuple[int, int]
    ) -> None:
        if not self.enabled:
            return
        if len(json.dumps(body, default=str)) > _MAX_ENTRY_BYTES:
            return
        self._data[key] = CacheEntry(
            body, model, provider, usage[0], usage[1], self._clock() + self._ttl
        )
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)
