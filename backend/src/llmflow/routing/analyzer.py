"""Request complexity analysis: turns a chat request into a difficulty score in [0, 1].

Deliberately transparent: a weighted sum of cheap, inspectable features. Weights are a
starting point to be tuned against benchmark results, not a trained model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from llmflow.schemas import ChatRequest, Message

_CODE_RE = re.compile(
    r"```|\bdef \w+\(|\bclass \w+|#include|\bfunction\b|=>|\bSELECT\b.*\bFROM\b", re.I
)
_MATH_RE = re.compile(
    r"\d\s*[-+*/^=]\s*\d|\b(integral|derivative|equation|prove|theorem|probability)\b", re.I
)
_REASONING_RE = re.compile(
    r"\b(step[- ]by[- ]step|explain why|analy[sz]e|compare|trade-?offs?|design|evaluate|"
    r"reason|derive|optimi[sz]e|debug|refactor|critique)\b",
    re.I,
)
_STRUCTURED_RE = re.compile(r"\b(json|yaml|schema|table|csv)\b", re.I)

_CHARS_PER_TOKEN = 4


def _text(message: Message) -> str:
    content = message.content
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return " ".join(str(part.get("text", "")) for part in content if part.get("type") == "text")


@dataclass(frozen=True, slots=True)
class Analysis:
    difficulty: float
    prompt_tokens_est: int
    needs_tokens: int
    features: dict[str, float]


_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_OPERATOR_RE = re.compile(
    r"(?<=\d)\s*[-+*/^%]\s*(?=\d)|\b(?:times|multiplied|divided|remainder|modulo|mod)\b", re.I
)
_LIST_RE = re.compile(r"(?:[^,\s]+,\s*){9,}[^,\s]+")

DEFAULT_VERSION = "v2"
VERSIONS = ("v1", "v2")

_WEIGHTS_V1 = {
    "length": 0.20, "code": 0.20, "math": 0.20, "reasoning": 0.25,
    "structured": 0.05, "turns": 0.05, "long_output": 0.05,
}  # fmt: skip
# v2 (frozen 2026-10-14, before any xhard results were seen): same intent, plus structural
# signals that do not depend on task type, and a date-safe math pattern.
_WEIGHTS_V2 = {
    "length": 0.15, "code": 0.15, "math": 0.10, "reasoning": 0.20, "structured": 0.05,
    "turns": 0.05, "long_output": 0.05,
    "numeric_load": 0.10, "digit_span": 0.10, "operators": 0.05,
}  # fmt: skip


def analyze(request: ChatRequest, version: str = DEFAULT_VERSION) -> Analysis:
    if version not in VERSIONS:
        raise ValueError(f"unknown analyzer version {version!r}")
    texts = [_text(m) for m in request.messages]
    joined = "\n".join(texts)
    last_user = next((_text(m) for m in reversed(request.messages) if m.role == "user"), "")
    prompt_tokens = max(1, len(joined) // _CHARS_PER_TOKEN)

    # Dates look like subtraction ("2024-03-15"); mask them so they are not read as arithmetic.
    math_text = _DATE_RE.sub(" DATE ", last_user)
    features = {
        "length": min(prompt_tokens / 3000, 1.0),
        "code": 1.0 if _CODE_RE.search(joined) else 0.0,
        "math": 1.0 if _MATH_RE.search(last_user if version == "v1" else math_text) else 0.0,
        "reasoning": min(len(_REASONING_RE.findall(last_user)) / 2, 1.0),
        "structured": 1.0 if _STRUCTURED_RE.search(last_user) else 0.0,
        "turns": min(len(request.messages) / 12, 1.0),
        "long_output": 1.0 if (request.max_tokens or 0) >= 1500 else 0.0,
    }
    if version == "v2":
        numbers = _NUMBER_RE.findall(math_text)
        digits = max((len(n.replace(",", "").split(".")[0]) for n in numbers), default=0)
        features["numeric_load"] = min(len(numbers) / 12, 1.0)
        features["digit_span"] = min(max(digits - 2, 0) / 6, 1.0)  # 3+ digit numbers start to count
        ops = len(_OPERATOR_RE.findall(math_text)) + (1 if _LIST_RE.search(math_text) else 0)
        features["operators"] = min(ops / 4, 1.0)
    weights = _WEIGHTS_V1 if version == "v1" else _WEIGHTS_V2
    difficulty = min(1.0, sum(weights[k] * v for k, v in features.items()))
    needs = prompt_tokens + (request.max_tokens or 512)
    return Analysis(difficulty, prompt_tokens, needs, features)
