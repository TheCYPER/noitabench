"""The provider-neutral side of a model: what the loop sends, what comes back.

A `Conversation` owns the history in its provider's own format and only ever *appends* to it:
the assistant's content goes back exactly as it came (thinking blocks included), nothing is
edited, reordered or removed. `send` is all-or-nothing: if the call fails, the conversation is as
it was, so the same items can be sent again. When a conversation grows too long the loop starts a
new one (`ModelAdapter.new_conversation`) and carries a written summary over.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .usage import Usage

# Normalised reasons a model turn ended.
END_TURN = "end_turn"
TOOL_USE = "tool_use"
MAX_TOKENS = "max_tokens"
REFUSAL = "refusal"


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call: name, description and the JSON schema of its input."""

    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """One tool call of the model. `error` is set when its arguments could not be read."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """The answer to one tool call. `images` are PNG bytes shown with the text."""

    call_id: str
    name: str
    content: str
    is_error: bool = False
    images: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class UserText:
    """Plain text from the user side of the conversation."""

    text: str
    images: tuple[bytes, ...] = ()


Item = ToolResult | UserText


@dataclass(frozen=True)
class ModelTurn:
    """What one model call returned."""

    text: str
    thinking: str
    tool_calls: tuple[ToolCall, ...]
    stop: str  # END_TURN, TOOL_USE, MAX_TOKENS or REFUSAL
    usage: Usage
    latency_s: float = 0.0
    request_id: str | None = None
    raw_stop: str | None = None
    model: str = ""


class Conversation(ABC):
    """A conversation with one model: a fixed system prompt and tool set, an append-only history."""

    last_prompt_tokens: int = 0  # prompt size of the latest call, for the loop's compaction check

    @abstractmethod
    def send(self, items: Sequence[Item]) -> ModelTurn:
        """Append `items` as one user message, call the model, append its answer.

        Tool results come first, then text. Raises `ModelError`; then nothing was appended. When
        the answer is a refusal nothing is appended either. When it was cut off (`MAX_TOKENS`)
        the items are kept and a short stand-in for the answer is appended, so that no
        half-finished tool call or thinking block stays in the history."""


class ModelAdapter(ABC):
    """A model of one provider. Builds conversations; holds the client."""

    provider: str
    model: str

    @abstractmethod
    def new_conversation(self, system: str, tools: Sequence[ToolSpec]) -> Conversation: ...


DEFAULT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_REQUEST_TIMEOUT = 180.0  # seconds
# Providers whose models need more: (max output tokens, request timeout in seconds). DeepSeek
# counts its thinking against the output limit (8192 risks cut-off answers) and keeps a waiting
# request open for up to ten minutes.
PROVIDER_LIMITS: dict[str, tuple[int, float]] = {"deepseek": (32768, 600.0)}


@dataclass(frozen=True)
class ModelConfig:
    """How to reach and drive a model. Credentials are never part of it: they come from the
    provider's usual environment variables, or from the variable named in `api_key_env`.

    `max_output_tokens` and `request_timeout` left out (None) take the default of the provider
    (`PROVIDER_LIMITS`, else 8192 and 180 s); they are never None afterwards, and `as_log` writes
    the values in force. This is the one place that resolves them, for the CLI and for code."""

    provider: str  # anthropic, openai, gemini, deepseek or fake
    model: str
    base_url: str | None = None  # None: the provider's public endpoint (never an env override)
    api_key_env: str | None = None
    effort: str | None = None
    max_output_tokens: int | None = None
    request_timeout: float | None = None
    max_retries: int = 4
    thinking: str = "adaptive"  # adaptive, off or default (Anthropic and DeepSeek only)
    server_compaction: int | None = None  # Anthropic only: trigger, in prompt tokens

    def __post_init__(self) -> None:
        tokens, seconds = PROVIDER_LIMITS.get(
            self.provider, (DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_REQUEST_TIMEOUT)
        )
        if self.max_output_tokens is None:
            object.__setattr__(self, "max_output_tokens", tokens)
        if self.request_timeout is None:
            object.__setattr__(self, "request_timeout", seconds)

    def as_log(self) -> dict[str, Any]:
        """The config as it may be written to disk (no credentials; a base URL without
        user info)."""
        from urllib.parse import urlsplit, urlunsplit

        base = self.base_url
        if base:
            parts = urlsplit(base)
            host = parts.hostname or ""
            if parts.port:
                host += f":{parts.port}"
            base = urlunsplit((parts.scheme, host, parts.path, "", ""))
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": base,
            "api_key_env": self.api_key_env,
            "effort": self.effort,
            "max_output_tokens": self.max_output_tokens,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "thinking": self.thinking,
            "server_compaction": self.server_compaction,
        }
