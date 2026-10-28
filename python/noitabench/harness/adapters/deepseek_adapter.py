"""DeepSeek's official API, through the OpenAI adapter (it speaks Chat Completions).

What differs from `openai_adapter.py`, and nothing else does:

- The endpoint is `https://api.deepseek.com`; the key is `DEEPSEEK_API_KEY` or the variable named
  in `api_key_env`. The default variable is read only for that endpoint, over https: for any
  other `base_url` (another host, a look-alike, plain http, a port, user info in the URL) only
  `api_key_env` is read, or no key is sent at all. See `_is_deepseek_endpoint`.
- The token limit is `max_tokens`, and reasoning tokens count against it (`model.py` gives a
  DeepSeek model a larger default limit and a longer timeout than the other providers).
- Thinking is on by default. `thinking="off"` sends `thinking: {"type": "disabled"}` (as
  `extra_body`, the SDK has no field for it). `effort` becomes `reasoning_effort` (low, high or
  max) and is not sent when thinking is off, since a reasoning effort would switch it on again.
- **The history keeps `reasoning_content`.** With thinking on, a request that carries tools must
  send back the `reasoning_content` of every earlier assistant message, tool-call or not, or the
  API answers 400. The assistant message is therefore stored with the one the model returned (an
  empty one if the answer had none; none at all with thinking off, which sends no such field).
  Its `content` is the empty string, not null, when the model said nothing besides its tool
  calls: that is the form the API's own sample sends back. A cut-off answer keeps the reasoning
  it had (a stand-in replaces the text and the tool calls only). Nothing in the harness rewrites
  a history: it only ever appends (`model.py`), a failed call appends nothing, a fork copies the
  list with its entries, and compaction starts a new conversation that holds no assistant message.
- `usage.prompt_tokens` is cache hits plus misses; the hit count is read from
  `prompt_tokens_details.cached_tokens` or, when that is absent, `prompt_cache_hit_tokens`. There
  is no cache write.
- `finish_reason` `insufficient_system_resource` and `aborted` mean the server gave up: a
  retryable `server` error, not the end of a turn.
- HTTP 402 (no balance left) is the `balance` error: not retried, and it ends a family of games.
- `deepseek-v4-pro` cannot read pictures.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from ..errors import ConfigError, ModelError, scrub
from ..model import ModelConfig, ModelTurn, ToolSpec
from ..usage import Usage
from .openai_adapter import OpenAIAdapter, OpenAIConversation, _sdk, map_error

API_URL = "https://api.deepseek.com"
API_HOST = "api.deepseek.com"
DEFAULT_KEY_ENV = "DEEPSEEK_API_KEY"
THINKING_MODES = ("adaptive", "off", "default")
# what `reasoning_effort` DeepSeek knows (low, high, max) for each effort the harness knows
EFFORT_MAP = {"low": "low", "medium": "high", "high": "high", "xhigh": "high", "max": "max"}
TEXT_ONLY_MODELS = frozenset({"deepseek-v4-pro"})
SERVER_GAVE_UP = frozenset({"insufficient_system_resource", "aborted"})


def _is_deepseek_endpoint(config: ModelConfig) -> bool:
    """Is this DeepSeek's own endpoint (named or not)? The URL must be https and its authority
    exactly `api.deepseek.com`: no user info, no port, no trailing dot, nothing that two URL
    parsers could read differently. Any path counts (`/beta`). Only then may the key of
    `DEEPSEEK_API_KEY` be sent."""
    url = config.base_url
    if url is None:
        return True
    if not all(33 <= ord(c) < 127 and c != "\\" for c in url):  # no spaces, controls, backslashes
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.netloc.lower() == API_HOST


def refuse_screenshot(config: ModelConfig) -> None:
    """Raise `ConfigError` when `config` is a DeepSeek model that cannot read pictures."""
    if config.provider == "deepseek" and config.model in TEXT_ONLY_MODELS:
        raise ConfigError(
            f"{config.model} cannot read pictures: drop --screenshot, or use deepseek-flash"
        )


class DeepSeekAdapter(OpenAIAdapter):
    provider = "deepseek"

    def __init__(self, config: ModelConfig, client: Any | None = None) -> None:
        if config.thinking not in THINKING_MODES:
            raise ConfigError(f"thinking must be {', '.join(THINKING_MODES)}")
        super().__init__(config, client)
        self.official = False  # not OpenAI's endpoint: the limit is `max_tokens`
        self.thinking_on = config.thinking != "off"
        # with thinking off, an effort would switch thinking on again: it is not sent
        self.reasoning_effort = (
            EFFORT_MAP[config.effort] if config.effort and self.thinking_on else None
        )

    @staticmethod
    def _make_client(config: ModelConfig) -> Any:
        openai = _sdk()
        env = config.api_key_env or (DEFAULT_KEY_ENV if _is_deepseek_endpoint(config) else None)
        kwargs: dict[str, Any] = {
            "base_url": config.base_url or API_URL,
            "max_retries": config.max_retries,
            "timeout": config.request_timeout,
            "api_key": "EMPTY",  # a host of our own that needs no key; DeepSeek's key stays home
        }
        if env:
            key = os.environ.get(env)
            if not key:
                hint = (
                    " (or name another variable with --api-key-env)"
                    if not config.api_key_env
                    else ""
                )
                raise ConfigError(f"the environment variable {env} is not set{hint}")
            kwargs["api_key"] = key
        try:
            return openai.OpenAI(**kwargs)
        except Exception as err:  # noqa: BLE001 - the SDK refuses a base URL it cannot read
            # `from None`: a URL that carries a key is in the SDK's own message and its chain
            raise ConfigError(
                f"the OpenAI SDK could not be set up for DeepSeek ({scrub(str(err))})"
            ) from None

    def new_conversation(self, system: str, tools: Sequence[ToolSpec]) -> DeepSeekConversation:
        return DeepSeekConversation(self, system, tools)


class DeepSeekConversation(OpenAIConversation):
    def __init__(self, adapter: DeepSeekAdapter, system: str, tools: Sequence[ToolSpec]) -> None:
        super().__init__(adapter, system, tools)
        self._deepseek = adapter

    def request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        req = super().request(messages)  # `max_tokens`: the adapter is not OpenAI's
        req.pop("reasoning_effort", None)  # the OpenAI spelling of the efforts is not DeepSeek's
        if self._deepseek.reasoning_effort:
            req["reasoning_effort"] = self._deepseek.reasoning_effort
        if not self._deepseek.thinking_on:
            req["extra_body"] = {"thinking": {"type": "disabled"}}
        return req

    def _create(self, request: dict[str, Any]) -> Any:
        try:
            return self._adapter.client.chat.completions.create(**request)
        except Exception as exc:
            mapped = map_deepseek_error(exc)
            if mapped is None:
                raise
            raise mapped from exc

    def _parse(
        self, response: Any, choice: Any, message: Any, latency: float
    ) -> tuple[ModelTurn, dict[str, Any]]:
        raw_stop = getattr(choice, "finish_reason", None)
        if raw_stop in SERVER_GAVE_UP:
            raise ModelError(
                "server",
                f"DeepSeek ended the reply early (finish_reason {raw_stop}): its servers were "
                "short of resources; the call can be repeated",
                retryable=True,
                request_id=getattr(response, "_request_id", None),
            )
        turn, assistant = super()._parse(response, choice, message, latency)
        turn = replace(turn, usage=usage_of(response))
        # sent back with every later request that carries tools, or the API answers 400: with
        # thinking on, the field is there even when the answer carried none
        reasoning = getattr(message, "reasoning_content", None)
        if isinstance(reasoning, str):
            assistant["reasoning_content"] = reasoning
        elif self._deepseek.thinking_on:
            assistant["reasoning_content"] = ""
        if assistant["content"] is None:  # only tool calls: the API's sample sends back ''
            assistant["content"] = ""
        return turn, assistant


def usage_of(response: Any) -> Usage:
    """Tokens of a call. `prompt_tokens` counts cache hits and misses together; there is no
    cache write on DeepSeek."""
    u = getattr(response, "usage", None)
    if u is None:
        return Usage()
    details = getattr(u, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None) if details else None
    if cached is None:
        cached = getattr(u, "prompt_cache_hit_tokens", None)
    cached = cached or 0
    out_details = getattr(u, "completion_tokens_details", None)
    thinking = getattr(out_details, "reasoning_tokens", None) if out_details else None
    return Usage(
        input_tokens=max((u.prompt_tokens or 0) - cached, 0),
        cache_read_tokens=cached,
        output_tokens=u.completion_tokens or 0,
        thinking_tokens=thinking,
    )


def map_deepseek_error(exc: Exception) -> ModelError | None:
    """`map_error` (429 and 5xx retryable, 400, 401 and 422 not), with the one status that is
    DeepSeek's own: 402, no balance left, which ends the run and is never retried."""
    mapped = map_error(exc)
    if mapped is not None and mapped.status == 402:
        return ModelError(
            "balance",
            f"DeepSeek says the account has no balance left (HTTP 402): top it up and run again. "
            f"The provider said: {mapped}",
            status=402,
            request_id=mapped.request_id,
        )
    return mapped
