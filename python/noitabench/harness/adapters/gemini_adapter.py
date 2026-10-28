"""Gemini through the official `google-genai` SDK.

The history is a list of `Content` objects; the model's own `Content` goes back unchanged (it
carries the thought signatures Gemini needs). Function calls and their responses are matched in
order; a call that came without an id gets one made up here, and its response then goes back
without an id. No sampling parameters are sent. Thought summaries are requested when `thinking`
is `adaptive` (the default): models without thinking need `--thinking default`.

The key comes from `GOOGLE_API_KEY` / `GEMINI_API_KEY` (read by the SDK) or from the variable
named by `api_key_env`; with a custom base URL only the latter, so that a Google key is not sent
to another host.

Not exercised against the live service by the test suite (no call is made without a go-ahead);
the request and response shapes are checked against the SDK's types with a mocked transport.
"""

from __future__ import annotations

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

PUBLIC_URL = "https://generativelanguage.googleapis.com/"
SYNTHETIC_ID = "gemini-call-"
STAND_IN = "(my answer was cut off)"
EMPTY_REPLY = "(no reply)"
NO_OUTPUT = "(no output)"
REFUSED = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "IMAGE_SAFETY"}
LEVELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "HIGH", "max": "HIGH"}
_DROPPED_KEYS = ("additionalProperties", "exclusiveMinimum", "exclusiveMaximum", "$schema")


def _sdk() -> tuple[Any, Any]:
    try:
        from google import genai
        from google.genai import types
    except ImportError as err:  # pragma: no cover - depends on the environment
        raise ConfigError(
            "the `google-genai` package is missing; install it with: "
            "pip install 'noitabench[harness]'"
        ) from err
    return genai, types


def gemini_schema(schema: Any) -> Any:
    """A JSON schema in the subset Gemini accepts: no `additionalProperties`, no exclusive
    bounds, `const` written as a one-value `enum`."""
    if isinstance(schema, list):
        return [gemini_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _DROPPED_KEYS:
            continue
        if key == "const":
            out["enum"] = [value]
            continue
        out[key] = gemini_schema(value)
    return out


class GeminiAdapter(ModelAdapter):
    provider = "gemini"

    def __init__(self, config: ModelConfig, client: Any | None = None) -> None:
        if config.effort is not None and config.effort not in LEVELS:
            raise ConfigError(f"effort must be one of {', '.join(LEVELS)}, got {config.effort!r}")
        self.config = config
        self.model = config.model
        self.client = client if client is not None else self._make_client(config)

    @staticmethod
    def _make_client(config: ModelConfig) -> Any:
        genai, types = _sdk()
        options = types.HttpOptions(
            base_url=config.base_url or PUBLIC_URL,
            timeout=int(config.request_timeout * 1000),
            retry_options=types.HttpRetryOptions(attempts=config.max_retries + 1),
        )
        # the Gemini API, never Vertex AI, whatever the environment says
        kwargs: dict[str, Any] = {"http_options": options, "vertexai": False}
        if config.api_key_env:
            key = os.environ.get(config.api_key_env)
            if not key:
                raise ConfigError(f"the environment variable {config.api_key_env} is not set")
            kwargs["api_key"] = key
        elif config.base_url:
            raise ConfigError(
                "a custom base URL needs --api-key-env: GOOGLE_API_KEY is not sent to a host "
                "other than Google's"
            )
        try:
            return genai.Client(**kwargs)
        except ValueError as err:  # no key anywhere
            raise ConfigError(
                f"no credentials for the Gemini SDK ({err}); set GOOGLE_API_KEY or use --api-key-env"
            ) from err

    def new_conversation(self, system: str, tools: Sequence[ToolSpec]) -> GeminiConversation:
        return GeminiConversation(self, system, tools)


class GeminiConversation(Conversation):
    def __init__(self, adapter: GeminiAdapter, system: str, tools: Sequence[ToolSpec]) -> None:
        _, types = _sdk()
        self._types = types
        self._adapter = adapter
        cfg = adapter.config
        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "max_output_tokens": cfg.max_output_tokens,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters_json_schema=gemini_schema(t.schema),
                )
                for t in tools
            ]
            kwargs["tools"] = [types.Tool(function_declarations=declarations)]
            kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            )
        thinking: dict[str, Any] = {}
        if cfg.thinking == "adaptive":
            thinking["include_thoughts"] = True
        if cfg.effort:
            thinking["thinking_level"] = LEVELS[cfg.effort]
        if thinking:
            kwargs["thinking_config"] = types.ThinkingConfig(**thinking)
        self._config = types.GenerateContentConfig(**kwargs)
        self.contents: list[Any] = []
        self.last_prompt_tokens = 0

    def user_content(self, items: Sequence[Item]) -> Any:
        types = self._types
        parts: list[Any] = []
        for item in items:
            if isinstance(item, ToolResult):
                text = item.content if item.content.strip() else NO_OUTPUT
                key = "error" if item.is_error else "output"
                response = types.FunctionResponse(
                    id=None if item.call_id.startswith(SYNTHETIC_ID) else item.call_id,
                    name=item.name,
                    response={key: text},
                )
                parts.append(types.Part(function_response=response))
                parts.extend(
                    types.Part.from_bytes(data=p, mime_type="image/png") for p in item.images
                )
        for item in items:
            if isinstance(item, UserText):
                if not item.text.strip():
                    raise ValueError("a text item must not be empty")
                parts.append(types.Part.from_text(text=item.text))
                parts.extend(
                    types.Part.from_bytes(data=p, mime_type="image/png") for p in item.images
                )
        return types.Content(role="user", parts=parts)

    def send(self, items: Sequence[Item]) -> ModelTurn:
        if not items:
            raise ValueError("nothing to send")
        types = self._types
        user = self.user_content(items)
        started = time.monotonic()
        response = self._generate([*self.contents, user])
        latency = time.monotonic() - started
        turn, model_content = self._parse(response, latency)
        if turn.stop == REFUSAL:
            return turn
        self.contents.append(user)
        if turn.stop == MAX_TOKENS or model_content is None:
            text = STAND_IN if turn.stop == MAX_TOKENS else EMPTY_REPLY
            model_content = types.Content(role="model", parts=[types.Part.from_text(text=text)])
        self.contents.append(model_content)
        self.last_prompt_tokens = turn.usage.prompt_tokens
        return turn

    def _generate(self, contents: list[Any]) -> Any:
        cfg = self._adapter.config
        try:
            return self._adapter.client.models.generate_content(
                model=cfg.model, contents=contents, config=self._config
            )
        except Exception as exc:
            mapped = map_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    def _parse(self, response: Any, latency: float) -> tuple[ModelTurn, Any | None]:
        candidates = getattr(response, "candidates", None) or []
        usage = usage_of(response)
        base = {
            "usage": usage,
            "latency_s": latency,
            "request_id": getattr(response, "response_id", None),
            "model": getattr(response, "model_version", None) or self._adapter.model,
        }
        if not candidates:
            blocked = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
            stop = REFUSAL if blocked else END_TURN
            raw = f"blocked: {blocked}" if blocked else None
            return ModelTurn("", "", (), stop, raw_stop=raw, **base), None
        cand = candidates[0]
        raw_finish = getattr(cand.finish_reason, "name", cand.finish_reason)
        raw_finish = str(raw_finish) if raw_finish is not None else None
        content = cand.content
        texts, thoughts, calls = [], [], []
        for part in (content.parts or []) if content is not None else []:
            if part.function_call is not None:
                fc = part.function_call
                call_id = fc.id or f"{SYNTHETIC_ID}{len(calls) + 1}"
                calls.append(ToolCall(call_id, fc.name, dict(fc.args or {})))
            elif part.text:
                (thoughts if part.thought else texts).append(part.text)
        stop = END_TURN
        if raw_finish == "MAX_TOKENS":
            stop = MAX_TOKENS
        elif raw_finish in REFUSED:
            stop = REFUSAL
        elif calls:
            stop = TOOL_USE
        if stop in (MAX_TOKENS, REFUSAL):
            calls = []
        turn = ModelTurn(
            "\n".join(texts), "\n".join(thoughts), tuple(calls), stop, raw_stop=raw_finish, **base
        )
        has_parts = content is not None and bool(content.parts)
        return turn, content if has_parts else None


def usage_of(response: Any) -> Usage:
    um = getattr(response, "usage_metadata", None)
    if um is None:
        return Usage()
    prompt = um.prompt_token_count or 0
    cached = um.cached_content_token_count or 0
    answer = getattr(um, "response_token_count", None)
    if answer is None:
        answer = getattr(um, "candidates_token_count", None) or 0
    thoughts = um.thoughts_token_count or 0
    return Usage(
        input_tokens=max(prompt - cached, 0),
        cache_read_tokens=cached,
        output_tokens=answer + thoughts,
        thinking_tokens=thoughts or None,
    )


def map_error(exc: Exception) -> ModelError | None:
    _sdk()  # a clear error when the package is missing
    from google.genai import errors

    if isinstance(exc, errors.APIError):
        status = int(exc.code) if exc.code else None
        message = scrub(exc.message or str(exc))

        def err(kind: str, retryable: bool = False) -> ModelError:
            return ModelError(kind, message, status=status, retryable=retryable)

        if status == 401:
            return err("auth")
        if status == 403:
            return err("permission")
        if status == 404:
            return err("not_found")
        if status == 429:
            return err("rate_limit", True)
        if status == 400:
            lowered = message.lower()
            return err("auth" if "api key" in lowered else "bad_request")
        if status in (503, 529):
            return err("overloaded", True)
        if status is not None and status >= 500:
            return err("server", True)
        return err("api")
    name = type(exc).__name__
    if "Timeout" in name:
        return ModelError("timeout", scrub(str(exc)), retryable=True)
    if any(word in name for word in ("Connect", "Network", "Read", "Remote")):
        return ModelError("connection", scrub(str(exc)), retryable=True)
    return None
