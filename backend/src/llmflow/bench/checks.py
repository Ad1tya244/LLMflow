"""Deterministic answer checkers. No LLM judge: every item has a programmatic pass/fail."""

from __future__ import annotations

import json
import re
import string
from typing import Any

_ANSWER_RE = re.compile(r"answer\s*[:\-]\s*(.+)", re.IGNORECASE)
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_answer(text: str) -> str | None:
    """Text after the last ``Answer:`` marker, stripped of markdown emphasis."""
    matches: list[str] = _ANSWER_RE.findall(text)
    if not matches:
        return None
    return str(matches[-1]).strip().strip("*_`").strip().rstrip(".").strip()


def parse_number(text: str) -> float | None:
    cleaned = text.replace(",", "")
    found = _NUM_RE.findall(cleaned)
    return float(found[0]) if found else None


def _normalise(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text)  # "Newton (N)" -> "Newton"
    text = text.lower().translate(str.maketrans("", "", string.punctuation))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(the|a|an) ", "", text)


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.strip().splitlines() if ln.strip()]


def _json_candidates(text: str) -> list[str]:
    out = [text.strip()]
    out += [m.strip() for m in _FENCE_RE.findall(text)]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = text.find(open_c), text.rfind(close_c)
        if 0 <= a < b:
            out.append(text[a : b + 1])
    return out


def parse_json(text: str) -> Any | None:
    for cand in _json_candidates(text):
        try:
            return json.loads(cand)
        except ValueError:
            continue
    return None


def _folded(xs: list[Any]) -> list[str]:
    return sorted(str(x).casefold() for x in xs)


def json_matches(actual: Any, expected: Any, *, unordered: bool = False) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return False
        return all(json_matches(actual[k], v, unordered=unordered) for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        if unordered:
            return _folded(actual) == _folded(expected)
        return all(
            json_matches(a, e, unordered=unordered) for a, e in zip(actual, expected, strict=True)
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, int | float):
        return isinstance(actual, int | float) and float(actual) == float(expected)
    if isinstance(expected, str):
        return isinstance(actual, str) and actual.strip().casefold() == expected.casefold()
    return bool(actual == expected)


def _bullets3(text: str) -> bool:
    lines = _lines(text)
    return len(lines) == 3 and all(ln.startswith(("- ", "• ", "* ")) for ln in lines)


def _no_letter_e(text: str) -> bool:
    t = text.strip()
    return len(t.split()) >= 3 and "e" not in t.lower()


def _weekdays_reverse(text: str) -> bool:
    days = [d.strip() for d in text.lower().strip().rstrip(".").split(",")]
    return days == ["sunday", "saturday", "friday", "thursday", "wednesday", "tuesday", "monday"]


def _repeat_banana(text: str) -> bool:
    return text.strip().strip(".").lower().split() == ["banana"] * 4


def _three_lines(text: str) -> bool:
    return len(_lines(text)) == 3


def _eight_words(text: str) -> bool:
    t = text.strip()
    if not t.endswith(".") or t.count(".") != 1:
        return False
    body = t[:-1]
    if any(ch in string.punctuation.replace("'", "") for ch in body):
        return False
    return len(body.split()) == 8


def _ten_s_words(text: str) -> bool:
    words = re.findall(r"[A-Za-z']+", text)
    return len(words) == 10 and all(w[0].lower() == "s" for w in words)


_NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


def _numbers_alpha(text: str) -> bool:
    got = [w.strip() for w in text.lower().strip().rstrip(".").split(",")]
    return got == sorted(_NUMBER_WORDS)


CONSTRAINTS = {
    "ten_s_words": _ten_s_words,
    "numbers_alpha": _numbers_alpha,
    "bullets3": _bullets3,
    "no_letter_e": _no_letter_e,
    "weekdays_reverse": _weekdays_reverse,
    "repeat_banana": _repeat_banana,
    "three_lines": _three_lines,
    "eight_words": _eight_words,
}


def check(spec: dict[str, Any], text: str) -> tuple[bool, str]:
    """Return ``(passed, detail)`` for a model response against an item's check spec."""
    kind = spec["type"]
    if not text.strip():
        return False, "empty response"
    if kind == "numeric":
        ans = extract_answer(text)
        got = parse_number(ans) if ans is not None else None
        if got is None:  # lenient fallback: last number in the response
            nums = _NUM_RE.findall(text.replace(",", ""))
            got = float(nums[-1]) if nums else None
        if got is None:
            return False, "no number found"
        ok = abs(got - float(spec["value"])) < 1e-6
        return ok, f"got {got:g}, want {spec['value']}"
    if kind == "choice":
        ans = extract_answer(text)
        letter = None
        if ans:
            m = re.search(r"\b([A-D])\b", ans.upper())
            letter = m.group(1) if m else None
        if letter is None:
            tail = _lines(text)[-1].upper()
            m = re.search(r"\b([A-D])\b", tail)
            letter = m.group(1) if m else None
        return letter == spec["value"], f"got {letter}, want {spec['value']}"
    if kind == "exact":
        ans = extract_answer(text)
        if ans is None:
            ans = _lines(text)[-1]
        accepted = {_normalise(a) for a in spec["accept"]}
        return _normalise(ans) in accepted, f"got {ans!r}"
    if kind == "json":
        parsed = parse_json(text)
        if parsed is None:
            return False, "no valid JSON"
        return json_matches(
            parsed, spec["expected"], unordered=bool(spec.get("unordered"))
        ), "json compared"
    if kind == "constraint":
        fn = CONSTRAINTS[spec["name"]]
        return fn(text), spec["name"]
    raise ValueError(f"unknown check type {kind!r}")
