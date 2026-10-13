"""Benchmark suite generation.

* GSM8K: a seeded sample of the public grade-school-math test set (MIT licence,
  https://github.com/openai/grade-school-math), with its own reference answers.
* Synthetic: seeded families of tasks whose answers are computed in Python, so they are correct
  by construction and scale in difficulty (long multiplication, letter counting, date maths...).

No model is run or trained here; this is plain Python.
"""

from __future__ import annotations

import json
import random
import re
import string
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_NUM_SUFFIX = "\n\nThink step by step, then finish with a final line of the form 'Answer: <value>'."
_LEVELS = ("easy", "medium", "hard", "hard")
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _item(family: str, idx: int, level: str, prompt: str, check: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{family}-{idx:02d}",
        "category": family,
        "difficulty": level,
        "prompt": prompt + _NUM_SUFFIX,
        "check": check,
    }


def _num(v: int | float) -> dict[str, Any]:
    return {"type": "numeric", "value": v}


def _exact(*answers: str) -> dict[str, Any]:
    return {"type": "exact", "accept": [a.lower() for a in answers]}


# --- synthetic families ----------------------------------------------------------------------


def _mult(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    digits = {"easy": (2, 2), "medium": (3, 3), "hard": (4, 3), "xhard": (5, 4)}[level]
    a = rng.randint(10 ** (digits[0] - 1), 10 ** digits[0] - 1)
    b = rng.randint(10 ** (digits[1] - 1), 10 ** digits[1] - 1)
    return f"What is {a} multiplied by {b}?", _num(a * b)


def _chain(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    hi = {"easy": 20, "medium": 90, "hard": 400, "xhard": 3000}[level]
    a, b, c, d, e = (rng.randint(3, hi) for _ in range(5))
    value = (a * b + c) - d * e
    return f"Compute ({a} * {b} + {c}) - {d} * {e}.", _num(value)


def _letters(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    length = {"easy": 20, "medium": 40, "hard": 70, "xhard": 150}[level]
    pool = "abcdefghij"
    text = "".join(rng.choice(pool) for _ in range(length))
    target = rng.choice(pool)
    return (
        f"How many times does the letter '{target}' appear in the string \"{text}\"?",
        _num(text.count(target)),
    )


def _kth(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    n = {"easy": 7, "medium": 12, "hard": 18, "xhard": 30}[level]
    nums = rng.sample(range(10, 999), n)
    k = rng.randint(2, max(3, n // 2))
    ordered = sorted(nums, reverse=True)
    listing = ", ".join(str(x) for x in nums)
    return f"Here are {n} distinct numbers: {listing}. What is the {k}th largest of them?", _num(
        ordered[k - 1]
    )


def _weekday(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    days = {
        "easy": rng.randint(5, 20),
        "medium": rng.randint(60, 200),
        "hard": rng.randint(500, 3000),
        "xhard": rng.randint(20000, 200000),
    }[level]
    start = date(2024, 1, 1) + timedelta(days=rng.randint(0, 700))
    answer = _WEEKDAYS[(start + timedelta(days=days)).weekday()]
    return (
        f"Today is {start.isoformat()}. What day of the week will it be {days} days from today? "
        "Answer with the weekday name only.",
        _exact(answer),
    )


def _binary(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    hi = {"easy": 60, "medium": 900, "hard": 60000, "xhard": 900_000_000}[level]
    n = rng.randint(hi // 2, hi)
    return f"Convert the decimal number {n} to binary.", _exact(format(n, "b"))


def _order(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    n = {"easy": 4, "medium": 5, "hard": 7, "xhard": 9}[level]
    names = rng.sample(
        ["Asha", "Bruno", "Chen", "Dara", "Elif", "Farid", "Gita", "Hugo", "Ines"], n
    )
    order = names[:]  # tallest -> shortest
    pairs = [f"{order[i]} is taller than {order[i + 1]}." for i in range(n - 1)]
    rng.shuffle(pairs)
    return (
        "Facts: " + " ".join(pairs) + " Who is the shortest person? Answer with the name only.",
        _exact(order[-1]),
    )


def _modpow(rng: random.Random, level: str) -> tuple[str, dict[str, Any]]:
    base_hi, exp_hi, mod_hi = {
        "easy": (9, 6, 20),
        "medium": (30, 40, 97),
        "hard": (90, 400, 997),
        "xhard": (999, 5000, 99991),
    }[level]
    b, e, m = rng.randint(2, base_hi), rng.randint(3, exp_hi), rng.randint(7, mod_hi)
    return f"What is the remainder when {b}^{e} is divided by {m}?", _num(pow(b, e, m))


FAMILIES: dict[str, Callable[[random.Random, str], tuple[str, dict[str, Any]]]] = {
    "mult": _mult,
    "chain": _chain,
    "letters": _letters,
    "kth": _kth,
    "weekday": _weekday,
    "binary": _binary,
    "order": _order,
    "modpow": _modpow,
}


def synthetic_items(
    n: int, seed: int, levels: tuple[str, ...] = _LEVELS, prefix: str = ""
) -> list[dict[str, Any]]:
    # Seeded, reproducible benchmark data; not security-relevant.
    rng = random.Random(seed)  # nosec B311
    names = list(FAMILIES)
    counts: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for i in range(n):
        family = names[i % len(names)]
        level = levels[(i // len(names)) % len(levels)]
        counts[family] = counts.get(family, 0) + 1
        prompt, check = FAMILIES[family](rng, level)
        out.append(_item(prefix + family, counts[family], level, prompt, check))
    return out


# --- GSM8K -------------------------------------------------------------------------------------


def _gsm_level(solution: str) -> str:
    steps = len([ln for ln in solution.splitlines() if ln.strip() and not ln.startswith("####")])
    return "easy" if steps <= 2 else "medium" if steps <= 4 else "hard"


def gsm8k_items(path: Path, n: int, seed: int) -> list[dict[str, Any]]:
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    # Seeded, reproducible benchmark sampling; not security-relevant.
    rng = random.Random(seed)  # nosec B311
    picked = rng.sample(rows, n)
    items = []
    for i, row in enumerate(picked, 1):
        m = re.search(r"####\s*(-?[\d,\.]+)", row["answer"])
        if m is None:
            continue
        value = float(m.group(1).replace(",", ""))
        value = int(value) if value.is_integer() else value
        items.append(
            _item("gsm8k", i, _gsm_level(row["answer"]), row["question"].strip(), _num(value))
        )
    return items


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8"
    )


def _letters_only(text: str) -> str:  # helper kept for tests
    return "".join(ch for ch in text if ch in string.ascii_lowercase)
