"""Claude through the official `anthropic` SDK (Messages API).

What the adapter does, and why:

- **Append-only history.** The assistant's `response.content` goes back unchanged, thinking blocks
  included; nothing earlier is ever edited (an edit breaks the signature of the thinking blocks
  after it, and can return a 400).
- **Prompt caching.** Request order is tools, system, messages, all constant between calls. One
  explicit breakpoint sits on the system block (that caches tools and system together), and
  top-level automatic caching follows the growing conversation. Cache reads and writes are read
  from `usage` and priced.
- **Only parameters every model accepts.** No `temperature`, `top_p` or `top_k` (they are
  rejected), no prefill, `tool_choice` auto. Thinking is adaptive with its effort in
  `output_config`; its summaries are requested so that they can be logged.
- **One user message per assistant turn** holds all `tool_result` blocks (failed tools with
  `is_error`), then any text.
- **No silent traffic.** The base URL is explicit (the public endpoint unless the config names
  another): a base URL in the environment, as the desktop app sets one, is never used. The key
  is read here, from `ANTHROPIC_API_KEY` or the variable named by `api_key_env`, and handed to
  the SDK, so that the SDK does not go looking: `ANTHROPIC_AUTH_TOKEN` (a gateway's token),
  profiles on disk and `ANTHROPIC_CUSTOM_HEADERS` never reach the endpoint. With a custom base
  URL the key must be named with `api_key_env`: the Anthropic key is not sent to another host
  by default.
- `stop_reason` is checked before the content is used: a refusal is not appended to the history;
  an answer cut off by `max_tokens` is replaced by a stand-in so that no half-finished tool call
  stays in it.
- Optional server-side compaction (`ModelConfig.server_compaction`, beta) for runs that prefer it
  to the loop's own summary.
"""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from ..errors import ConfigError, ModelError, scrub
from ..model import (
    END_TURN,
    MAX_TOKENS,
    REFUSAL,
    TOOL_USE,
    Conversation,
    Item,
    ModelAdapter,
    ModelConfig,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolSpec,
    UserText,
)
from ..prompt import SERVER_COMPACTION_INSTRUCTIONS
from ..usage import Usage

PUBLIC_URL = "https://api.anthropic.com"
COMPACT_BETA = "compact-2026-01-12"
NO_CREDENTIALS = (
    "No credentials found. Set ANTHROPIC_API_KEY, or name another variable with --api-key-env."
)
STAND_IN = "(my answer was cut off)"
EMPTY_REPLY = "(no reply)"
NO_OUTPUT = "(no output)"
STOP_MAP = {
    "end_turn": END_TURN,
    "stop_sequence": END_TURN,
    "pause_turn": END_TURN,
    "tool_use": TOOL_USE,
    "max_tokens": MAX_TOKENS,
    "model_context_window_exceeded": MAX_TOKENS,
    "refusal": REFUSAL,
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_KEY_VARIABLE = "ANTHROPIC_API_KEY"
# What the SDK reads from the environment besides the key, and must not use here.
MASKED_ENVIRONMENT = (
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_CUSTOM_HEADERS",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "ANTHROPIC_FEDERATION_RULE_ID",
)


def _sdk() -> Any:
    try:
        import anthropic
    except ImportError as err:  # pragma: no cover - depends on the environment
        raise ConfigError(
            "the `anthropic` package is missing; install it with: pip install 'noitabench[harness]'"
        ) from err
    return anthropic


def check_thinking(config: ModelConfig) -> None:
    """Refuse the settings that the API would answer with a 400 (after the first call has been
    paid for): thinking off is only accepted by the Haiku line, and not together with an effort
    of `xhigh` or `max`."""
    if config.thinking not in ("adaptive", "off", "default"):
        raise ConfigError("thinking must be adaptive, off or default")
    if config.thinking != "off":
        return
    if not config.model.startswith("claude-haiku"):
        raise ConfigError(
            f"thinking cannot be switched off for {config.model}; leave it on and lower the "
            "effort instead (--effort low)"
        )
    if config.effort in ("xhigh", "max"):
        raise ConfigError(f"thinking cannot be off at effort {config.effort}; use high or lower")


def _key_variable(config: ModelConfig) -> str:
    """The environment variable the key comes from. With a custom base URL it must be named."""
    if config.api_key_env:
        return config.api_key_env
    if config.base_url:
        raise ConfigError(
            f"a custom base URL needs --api-key-env: {DEFAULT_KEY_VARIABLE} is not sent to a "
            "host other than Anthropic's"
        )
    return DEFAULT_KEY_VARIABLE


@contextmanager
def _without(names: Sequence[str]) -> Iterator[None]:
    """Run a block with some environment variables hidden (the SDK reads them when a client is
    built); they are put back afterwards."""
    held = {n: os.environ.pop(n) for n in names if n in os.environ}
    try:
        yield
    finally:
        os.environ.update(held)


class AnthropicAdapter(ModelAdapter):
    provider = "anthropic"

    def __init__(self, config: ModelConfig, client: Any | None = None) -> None:
        if config.effort is not None and config.effort not in EFFORTS:
            raise ConfigError(f"effort must be one of {', '.join(EFFORTS)}, got {config.effort!r}")
        check_thinking(config)
        self.config = config
        self.model = config.model
        self.client = client if client is not None else self._make_client(config)

    @staticmethod
    def _make_client(config: ModelConfig) -> Any:
        anthropic = _sdk()
        variable = _key_variable(config)
        key = os.environ.get(variable)
        if not key:
            if variable == DEFAULT_KEY_VARIABLE:
                raise ConfigError(NO_CREDENTIALS)
            raise ConfigError(f"the environment variable {variable} is not set")
        with _without(MASKED_ENVIRONMENT):
            return anthropic.Anthropic(
                api_key=key,
                base_url=config.base_url or PUBLIC_URL,
                max_retries=config.max_retries,
                timeout=config.request_timeout,
            )

    def new_conversation(self, system: str, tools: Sequence[ToolSpec]) -> AnthropicConversation:
        return AnthropicConversation(self, system, tools)


class AnthropicConversation(Conversation):
    def __init__(self, adapter: AnthropicAdapter, system: str, tools: Sequence[ToolSpec]) -> None:
        self._adapter = adapter
        self._system: list[dict[str, Any]] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        self._tools: list[dict[str, Any]] = [
            {"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools
        ]
        self.messages: list[dict[str, Any]] = []
        self.last_prompt_tokens = 0

    # -- the request ------------------------------------------------------------------------------

    def request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """The arguments of one `messages.create` call."""
        cfg = self._adapter.config
        req: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": cfg.max_output_tokens,
            "system": self._system,
            "messages": messages,
            "cache_control": {"type": "ephemeral"},
            "output_config": {"effort": cfg.effort or "medium"},
        }
        if self._tools:
            req["tools"] = self._tools
            req["tool_choice"] = {"type": "auto"}
        if cfg.thinking == "adaptive":
            req["thinking"] = {"type": "adaptive", "display": "summarized"}
        elif cfg.thinking == "off":
            req["thinking"] = {"type": "disabled"}
        return req

    @staticmethod
    def user_message(items: Sequence[Item]) -> dict[str, Any]:
        """One user message: the tool results first, then the text."""
        blocks: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, ToolResult):
                blocks.append(_tool_result_block(item))
        for item in items:
            if isinstance(item, UserText):
                if not item.text.strip():
                    raise ValueError("a text item must not be empty")
                blocks.append({"type": "text", "text": item.text})
                blocks.extend(_image_block(png) for png in item.images)
        return {"role": "user", "content": blocks}

    # -- the call ---------------------------------------------------------------------------------

    def send(self, items: Sequence[Item]) -> ModelTurn:
        if not items:
            raise ValueError("nothing to send")
        user = self.user_message(items)
        request = self.request([*self.messages, user])
        started = time.monotonic()
        response = self._create(request)
        turn = self._parse(response, time.monotonic() - started)
        if turn.stop == REFUSAL:
            return turn  # the refused answer is not part of the conversation
        self.messages.append(user)
        self.messages.append(
            {"role": "assistant", "content": history_content(response, turn.stop == MAX_TOKENS)}
        )
        top = response.usage
        self.last_prompt_tokens = (
            (top.input_tokens or 0)
            + (top.cache_read_input_tokens or 0)
            + (top.cache_creation_input_tokens or 0)
        )
        return turn

    def _create(self, request: dict[str, Any]) -> Any:
        client = self._adapter.client
        cfg = self._adapter.config
        try:
            if cfg.server_compaction:
                return client.beta.messages.create(
                    betas=[COMPACT_BETA],
                    context_management={
                        "edits": [
                            {
                                "type": "compact_20260112",
                                "trigger": {"type": "input_tokens", "value": cfg.server_compaction},
                                "instructions": SERVER_COMPACTION_INSTRUCTIONS,
                            }
                        ]
                    },
                    **request,
                )
            return client.messages.create(**request)
        except TypeError as exc:
            if "authentication method" not in str(exc):
                raise
            raise ModelError("auth", NO_CREDENTIALS) from exc  # the SDK's way to say "no key"
        except Exception as exc:
            mapped = map_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    # -- reading the answer -----------------------------------------------------------------------

    def _parse(self, response: Any, latency: float) -> ModelTurn:
        raw_stop = getattr(response, "stop_reason", None)
        stop = STOP_MAP.get(raw_stop or "", END_TURN)
        if stop == REFUSAL:  # say which classifier it was, when the API does
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raw_stop = f"refusal ({category})" if category else "refusal"
        texts: list[str] = []
        thoughts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "thinking":
                thoughts.append(getattr(block, "thinking", "") or "")
            elif kind == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                error = (
                    None if isinstance(block.input, dict) else "the arguments were not an object"
                )
                calls.append(ToolCall(block.id, block.name, args, error))
        if stop in (MAX_TOKENS, REFUSAL):
            calls = []
        elif calls:
            stop = TOOL_USE
        elif stop == TOOL_USE:
            stop = END_TURN
        return ModelTurn(
            text="\n".join(t for t in texts if t),
            thinking="\n".join(t for t in thoughts if t),
            tool_calls=tuple(calls),
            stop=stop,
            usage=usage_of(response),
            latency_s=latency,
            request_id=getattr(response, "_request_id", None),
            raw_stop=raw_stop,
            model=getattr(response, "model", None) or self._adapter.model,
        )


def history_content(response: Any, cut_off: bool) -> list[Any]:
    """The answer as it goes into the history: the blocks as they came (thinking blocks
    unchanged), except that

    - a cut-off answer is replaced by a stand-in, so that no half-finished tool call stays;
    - blocks of blank text are left out: the API refuses to be sent one, and one stray block
      would end the run with a 400 on every later call;
    - an answer with nothing but thinking in it gets a short text after it (an assistant turn
      needs something to say; the model has been seen to answer inside its thinking)."""
    if cut_off:
        return [{"type": "text", "text": STAND_IN}]
    kept = [b for b in response.content if not _blank_text(b)]
    if not kept:
        return [{"type": "text", "text": EMPTY_REPLY}]
    if all(getattr(b, "type", None) in ("thinking", "redacted_thinking") for b in kept):
        kept.append({"type": "text", "text": EMPTY_REPLY})
    return kept


def _blank_text(block: Any) -> bool:
    return getattr(block, "type", None) == "text" and not (getattr(block, "text", "") or "").strip()


def usage_of(response: Any) -> Usage:
    """Tokens of a response, with the compaction iterations that the top-level usage leaves out."""
    u = response.usage
    details = getattr(u, "output_tokens_details", None)
    usage = Usage(
        input_tokens=u.input_tokens or 0,
        cache_read_tokens=u.cache_read_input_tokens or 0,
        cache_write_tokens=u.cache_creation_input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        thinking_tokens=getattr(details, "thinking_tokens", None),
    )
    for step in getattr(u, "iterations", None) or []:
        if getattr(step, "type", None) == "compaction":
            usage += Usage(
                input_tokens=step.input_tokens or 0,
                cache_read_tokens=step.cache_read_input_tokens or 0,
                cache_write_tokens=step.cache_creation_input_tokens or 0,
                output_tokens=step.output_tokens or 0,
            )
    return usage


def _image_block(png: bytes) -> dict[str, Any]:
    data = base64.standard_b64encode(png).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}


def _tool_result_block(result: ToolResult) -> dict[str, Any]:
    text = result.content if result.content.strip() else NO_OUTPUT
    content: Any = text
    if result.images:
        content = [{"type": "text", "text": text}, *(_image_block(p) for p in result.images)]
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": result.call_id,
        "content": content,
    }
    if result.is_error:
        block["is_error"] = True
    return block


def map_error(exc: Exception) -> ModelError | None:
    """The `ModelError` for an SDK exception (most specific class first), None if it is not one
    of the SDK's."""
    anthropic = _sdk()
    request_id = getattr(exc, "request_id", None)
    status = getattr(exc, "status_code", None)
    message = scrub(getattr(exc, "message", None) or str(exc))

    def err(kind: str, retryable: bool = False) -> ModelError:
        return ModelError(kind, message, status=status, retryable=retryable, request_id=request_id)

    if isinstance(exc, anthropic.AuthenticationError):
        return err("auth")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return err("permission")
    if isinstance(exc, anthropic.NotFoundError):
        return err("not_found")
    if isinstance(exc, anthropic.BadRequestError):
        return err("bad_request")
    if isinstance(exc, anthropic.RateLimitError):
        return err("rate_limit", True)
    if isinstance(exc, anthropic.APIStatusError):
        if status == 529:
            return err("overloaded", True)
        return err("server" if (status or 0) >= 500 else "api", (status or 0) >= 500)
    if isinstance(exc, anthropic.APITimeoutError):  # a subclass of APIConnectionError: first
        return err("timeout", True)
    if isinstance(exc, anthropic.APIConnectionError):
        return err("connection", True)
    if isinstance(exc, anthropic.CredentialsError | anthropic.WorkloadIdentityError):
        return err("auth")  # no credentials found, and the like
    if isinstance(exc, anthropic.AnthropicError):
        return err("unknown")  # an answer the SDK could not read, and the like
    return None
