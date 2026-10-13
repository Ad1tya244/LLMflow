"""Benchmark suite loading (JSONL, one item per line)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    category: str
    difficulty: str
    prompt: str
    check: dict[str, Any]


def load_suite(path: Path) -> list[Item]:
    items: list[Item] = []
    seen: set[str] = set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        item = Item(raw["id"], raw["category"], raw["difficulty"], raw["prompt"], raw["check"])
        if item.id in seen:
            raise ValueError(f"{path}:{n}: duplicate id {item.id!r}")
        seen.add(item.id)
        items.append(item)
    if not items:
        raise ValueError(f"{path}: suite is empty")
    return items
