"""GPT and open-weight models through the official `openai` SDK (Chat Completions).

Chat Completions is the one dialect that GPT models and the servers that host open-weight models
(vLLM, llama.cpp, ...) share, so this adapter serves both: leave `base_url` out for OpenAI, set
it for a server. The history is append-only (the assistant message goes back as it came, tool
calls included). No sampling parameters are sent. The token limit is `max_completion_tokens` for
OpenAI and `max_tokens` for other servers.

The key of OpenAI is never sent to another host: with a custom `base_url` the key comes only from
the variable named in `api_key_env` (or none is sent).
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Sequence
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
from ..usage import Usage

PUBLIC_URL = "https://api.openai.com/v1"
STAND_IN = "(my answer was cut off)"
EMPTY_REPLY = "(no reply)"
NO_OUTPUT = "(no output)"
FINISH_MAP = {
    "stop": END_TURN,
    "tool_calls": TOOL_USE,
    "function_call": TOOL_USE,
    "length": MAX_TOKENS,
    "content_filter": REFUSAL,
}
EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


def _sdk() -> Any:
    try:
        import openai
    except ImportError as err:  # pragma: no cover - depends on the environment
        raise ConfigError(
            "the `openai` package is missing; install it with: pip install 'noitabench[harness]'"
        ) from err
    return openai


def _is_official(config: ModelConfig) -> bool:
    """Is this OpenAI's own endpoint (named or not)?"""
    return config.base_url is None or config.base_url.rstrip("/") == PUBLIC_URL


class OpenAIAdapter(ModelAdapter):
    provider = "openai"

    def __init__(self, config: ModelConfig, client: Any | None = None) -> None:
        if config.effort is not None and config.effort not in EFFORT_MAP:
            raise ConfigError(
                f"effort must be one of {', '.join(EFFORT_MAP)}, got {config.effort!r}"
            )
        self.config = config
        self.model = config.model
        self.official = _is_official(config)
        self.client = client if client is not None else self._make_client(config)

    @staticmethod
    def _make_client(config: ModelConfig) -> Any:
        openai = _sdk()
        kwargs: dict[str, Any] = {
            "base_url": config.base_url or PUBLIC_URL,
            "max_retries": config.max_retries,
            "timeout": config.request_timeout,
        }
        if config.api_key_env:
            key = os.environ.get(config.api_key_env)
            if not key:
                raise ConfigError(f"the environment variable {config.api_key_env} is not set")
            kwargs["api_key"] = key
        elif not _is_official(config):
            kwargs["api_key"] = "EMPTY"  # a server of our own; OPENAI_API_KEY stays at home
        try:
            return openai.OpenAI(**kwargs)
        except openai.OpenAIError as err:  # no key anywhere
            raise ConfigError(
                f"no credentials for the OpenAI SDK ({err}); set OPENAI_API_KEY or use --api-key-env"
            ) from err

    def new_conversation(self, system: str, tools: Sequence[ToolSpec]) -> OpenAIConversation:
        return OpenAIConversation(self, system, tools)


class OpenAIConversation(Conversation):
    def __init__(self, adapter: OpenAIAdapter, system: str, tools: Sequence[ToolSpec]) -> None:
        self._adapter = adapter
        self._system = {"role": "system", "content": system}
        self._tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.schema},
            }
            for t in tools
        ]
        self.messages: list[dict[str, Any]] = []
        self.last_prompt_tokens = 0

    def request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        cfg = self._adapter.config
        limit = "max_completion_tokens" if self._adapter.official else "max_tokens"
        req: dict[str, Any] = {
            "model": cfg.model,
            "messages": [self._system, *messages],
            limit: cfg.max_output_tokens,
        }
        if self._tools:
            req["tools"] = self._tools
            req["tool_choice"] = "auto"
        if cfg.effort:
            req["reasoning_effort"] = EFFORT_MAP[cfg.effort]
        return req

    @staticmethod
    def user_messages(items: Sequence[Item]) -> list[dict[str, Any]]:
        """Tool results as `tool` messages, then the text as a user message. Images cannot be
        part of a tool message, so they follow in a user message of their own."""
        out: list[dict[str, Any]] = []
        pictures: list[bytes] = []
        for item in items:
            if isinstance(item, ToolResult):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.call_id,
                        "content": item.content if item.content.strip() else NO_OUTPUT,
                    }
                )
                pictures.extend(item.images)
        if pictures:
            out.append(_user_with_images("The picture that goes with the last answer.", pictures))
        for item in items:
            if isinstance(item, UserText):
                if not item.text.strip():
                    raise ValueError("a text item must not be empty")
                if item.images:
                    out.append(_user_with_images(item.text, list(item.images)))
                else:
                    out.append({"role": "user", "content": item.text})
        return out

    def send(self, items: Sequence[Item]) -> ModelTurn:
        if not items:
            raise ValueError("nothing to send")
        new = self.user_messages(items)
        request = self.request([*self.messages, *new])
        started = time.monotonic()
        response = self._create(request)
        latency = time.monotonic() - started
        choice = response.choices[0]
        message = choice.message
        turn, assistant = self._parse(response, choice, message, latency)
        if turn.stop == REFUSAL:
            return turn
        self.messages.extend(new)
        self.messages.append(assistant)
        self.last_prompt_tokens = turn.usage.prompt_tokens
        return turn

    def _create(self, request: dict[str, Any]) -> Any:
        try:
            return self._adapter.client.chat.completions.create(**request)
        except Exception as exc:
            mapped = map_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    def _parse(
        self, response: Any, choice: Any, message: Any, latency: float
    ) -> tuple[ModelTurn, dict[str, Any]]:
        raw_stop = getattr(choice, "finish_reason", None)
        stop = FINISH_MAP.get(raw_stop or "", END_TURN)
        if getattr(message, "refusal", None):
            stop = REFUSAL
        text = message.content or ""
        calls: list[ToolCall] = []
        wire_calls: list[dict[str, Any]] = []
        for tc in getattr(message, "tool_calls", None) or []:
            raw = tc.function.arguments or "{}"
            wire_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": raw},
                }
            )
            calls.append(_tool_call(tc.id, tc.function.name, raw))
        if stop in (MAX_TOKENS, REFUSAL):
            calls, wire_calls = [], []
        elif calls:
            stop = TOOL_USE
        elif stop == TOOL_USE:
            stop = END_TURN
        thinking = getattr(message, "reasoning_content", None) or ""
        turn = ModelTurn(
            text=text,
            thinking=thinking if isinstance(thinking, str) else "",
            tool_calls=tuple(calls),
            stop=stop,
            usage=usage_of(response),
            latency_s=latency,
            request_id=getattr(response, "_request_id", None),
            raw_stop=raw_stop,
            model=getattr(response, "model", None) or self._adapter.model,
        )
        assistant: dict[str, Any] = {"role": "assistant", "content": text or None}
        if wire_calls:
            assistant["tool_calls"] = wire_calls
        elif stop == MAX_TOKENS:
            assistant["content"] = STAND_IN
        elif not text:
            assistant["content"] = EMPTY_REPLY
        return turn, assistant


def _tool_call(call_id: str, name: str, raw: str) -> ToolCall:
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as err:
        return ToolCall(call_id, name, {}, f"the arguments were not valid JSON ({err.msg})")
    if not isinstance(args, dict):
        return ToolCall(call_id, name, {}, "the arguments were not a JSON object")
    return ToolCall(call_id, name, args)


def _user_with_images(text: str, pngs: list[bytes]) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for png in pngs:
        data = base64.standard_b64encode(png).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}})
    return {"role": "user", "content": parts}


def usage_of(response: Any) -> Usage:
    u = getattr(response, "usage", None)
    if u is None:
        return Usage()
    details = getattr(u, "prompt_tokens_details", None)
    cached = (getattr(details, "cached_tokens", None) or 0) if details else 0
    written = (getattr(details, "cache_write_tokens", None) or 0) if details else 0
    out_details = getattr(u, "completion_tokens_details", None)
    thinking = getattr(out_details, "reasoning_tokens", None) if out_details else None
    prompt = u.prompt_tokens or 0
    return Usage(
        input_tokens=max(prompt - cached - written, 0),
        cache_read_tokens=cached,
        cache_write_tokens=written,
        output_tokens=u.completion_tokens or 0,
        thinking_tokens=thinking,
    )


def map_error(exc: Exception) -> ModelError | None:
    openai = _sdk()
    request_id = getattr(exc, "request_id", None)
    status = getattr(exc, "status_code", None)
    message = scrub(getattr(exc, "message", None) or str(exc))

    def err(kind: str, retryable: bool = False) -> ModelError:
        return ModelError(kind, message, status=status, retryable=retryable, request_id=request_id)

    if isinstance(exc, openai.AuthenticationError):
        return err("auth")
    if isinstance(exc, openai.PermissionDeniedError):
        return err("permission")
    if isinstance(exc, openai.NotFoundError):
        return err("not_found")
    if isinstance(exc, openai.BadRequestError):
        return err("bad_request")
    if isinstance(exc, openai.RateLimitError):
        return err("rate_limit", True)
    if isinstance(exc, openai.APIStatusError):
        return err("server" if (status or 0) >= 500 else "api", (status or 0) >= 500)
    if isinstance(exc, openai.APITimeoutError):  # a subclass of APIConnectionError: first
        return err("timeout", True)
    if isinstance(exc, openai.APIConnectionError):
        return err("connection", True)
    if isinstance(exc, openai.OpenAIError):
        return err("auth")
    return None
