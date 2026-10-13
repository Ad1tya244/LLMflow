"""OpenAI-compatible request shapes (the subset the gateway inspects).

Unknown fields are accepted but only an allow-list of known chat parameters is ever
forwarded upstream, so a client cannot smuggle arbitrary provider options through.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Parameters forwarded to providers. ``stream``/``stream_options`` are set by the gateway.
UPSTREAM_PARAMS = frozenset(
    {
        "messages", "temperature", "top_p", "max_tokens", "max_completion_tokens", "stop",
        "presence_penalty", "frequency_penalty", "seed", "response_format", "tools",
        "tool_choice", "n", "logit_bias", "user",
    }
)  # fmt: skip


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str = Field(max_length=32)
    content: str | list[dict[str, Any]] | None = None


class LLMFlowOptions(BaseModel):
    """Gateway-specific per-request options, passed as ``llmflow`` in the body."""

    model_config = ConfigDict(extra="forbid")
    quality: Literal["low", "balanced", "high"] = "balanced"
    privacy: Literal["standard", "strict"] = "standard"
    fallback: bool = True
    cache: Literal["auto", "on", "off"] = "auto"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(default="auto", max_length=128)
    messages: list[Message] = Field(min_length=1)
    stream: bool = False
    max_tokens: int | None = Field(default=None, gt=0)
    llmflow: LLMFlowOptions = LLMFlowOptions()

    def upstream_payload(self, upstream_model: str) -> dict[str, Any]:
        """Body to send upstream: allow-listed fields only, with the provider model id."""
        dumped = self.model_dump(exclude_none=True)
        body = {k: v for k, v in dumped.items() if k in UPSTREAM_PARAMS}
        body["model"] = upstream_model
        return body


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
