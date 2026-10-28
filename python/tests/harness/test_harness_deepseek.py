"""The DeepSeek adapter, against the real `openai` SDK with a mocked transport (no network, no key)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx2
import openai
import pytest
from noitabench.agent import ViewConfig
from noitabench.harness import (
    ConfigError,
    ModelConfig,
    ModelError,
    RunConfig,
    ToolResult,
    ToolSpec,
    Usage,
    UserText,
    run_family,
)
from noitabench.harness.adapters import PROVIDERS, make_adapter
from noitabench.harness.adapters.deepseek_adapter import (
    API_URL,
    DeepSeekAdapter,
    DeepSeekConversation,
)
from noitabench.harness.cli import _model_config, _parser
from noitabench.harness.cli import main as harness_main
from noitabench.harness.model import END_TURN, MAX_TOKENS, TOOL_USE
from noitabench.harness.prices import PRICES, default_context_limit, resolve_price
from noitabench.harness.prompt import SUMMARY_REQUEST
from noitabench.harness.subagent_fork import fork_conversation
from test_harness_openai import Wire

MODEL = "deepseek-flash"
SERVED = "deepseek-v4.1-flash-1017"  # what the answers say the alias is, today
TOOLS = (
    ToolSpec(
        "wait", "Stand still.", {"type": "object", "properties": {"ticks": {"type": "integer"}}}
    ),
    ToolSpec("kick", "Kick.", {"type": "object", "properties": {}}),
)
THOUGHT = "The user wants me to wait; I will call wait."


def call_json(n: int = 1, name: str = "wait", args: str = '{"ticks":2}') -> dict[str, Any]:
    return {"id": f"call_{n}", "type": "function", "function": {"name": name, "arguments": args}}


def reply(
    message: dict[str, Any] | None = None,
    finish: str = "tool_calls",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thinking = {"role": "assistant", "content": "", "reasoning_content": THOUGHT}
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": SERVED,
        "choices": [
            {
                "index": 0,
                "message": message or {**thinking, "tool_calls": [call_json()]},
                "finish_reason": finish,
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "total_tokens": 1050,
            "prompt_tokens_details": {"cached_tokens": 800},
            "prompt_cache_hit_tokens": 800,
            "prompt_cache_miss_tokens": 200,
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
    }


def client_for(wire: Any, base_url: str = API_URL) -> openai.OpenAI:
    return openai.OpenAI(
        api_key="test-key",
        base_url=base_url,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(wire)),
    )


def adapter_for(wire: Any, **config: Any) -> DeepSeekAdapter:
    cfg = ModelConfig("deepseek", MODEL, max_retries=0, **config)
    return DeepSeekAdapter(cfg, client_for(wire))


def conversation(wire: Wire, **config: Any) -> DeepSeekConversation:
    return adapter_for(wire, **config).new_conversation("You play a game.", TOOLS)


# -- the request ----------------------------------------------------------------------------------


def test_the_provider_is_registered_and_builds_the_deepseek_adapter() -> None:
    assert "deepseek" in PROVIDERS
    adapter = make_adapter(ModelConfig("deepseek", MODEL), client=client_for(Wire()))
    assert isinstance(adapter, DeepSeekAdapter) and adapter.provider == "deepseek"


def test_request_shape() -> None:
    wire = Wire(reply())
    conversation(wire).send([UserText("Decision 1")])
    request, body = wire.requests[0], wire.body()
    assert request.url.host == "api.deepseek.com" and request.url.path == "/chat/completions"
    assert body["model"] == MODEL and body["max_tokens"] == 32768  # thinking counts against it
    assert "max_completion_tokens" not in body
    assert body["messages"] == [
        {"role": "system", "content": "You play a game."},
        {"role": "user", "content": "Decision 1"},
    ]
    assert body["tools"][1]["function"]["name"] == "kick" and body["tool_choice"] == "auto"
    # thinking is DeepSeek's default: nothing is sent about it, nor about an effort not given
    for absent in ("thinking", "reasoning_effort", "temperature", "top_p", "stream"):
        assert absent not in body


@pytest.mark.parametrize("thinking", ["adaptive", "default"])
def test_adaptive_and_default_leave_thinking_on(thinking: str) -> None:
    wire = Wire(reply())
    conversation(wire, thinking=thinking).send([UserText("go")])
    assert "thinking" not in wire.body()


def test_thinking_off_is_sent_as_a_body_field() -> None:
    wire = Wire(reply({"role": "assistant", "content": "ok"}, "stop"))
    conversation(wire, thinking="off").send([UserText("go")])
    body = wire.body()
    assert body["thinking"] == {"type": "disabled"} and "reasoning_effort" not in body


def test_an_effort_would_switch_thinking_on_again_so_it_is_not_sent_when_off() -> None:
    wire = Wire(reply({"role": "assistant", "content": "ok"}, "stop"))
    conversation(wire, thinking="off", effort="high").send([UserText("go")])
    body = wire.body()
    assert body["thinking"] == {"type": "disabled"} and "reasoning_effort" not in body


@pytest.mark.parametrize(
    ("effort", "sent"),
    [("low", "low"), ("medium", "high"), ("high", "high"), ("xhigh", "high"), ("max", "max")],
)
def test_effort_becomes_deepseeks_reasoning_effort(effort: str, sent: str) -> None:
    wire = Wire(reply())
    conversation(wire, effort=effort).send([UserText("go")])
    assert wire.body()["reasoning_effort"] == sent


def test_bad_settings_are_config_errors() -> None:
    with pytest.raises(ConfigError, match="effort"):
        adapter_for(Wire(), effort="extreme")
    with pytest.raises(ConfigError, match="thinking"):
        adapter_for(Wire(), thinking="sometimes")


# -- the key and the host -------------------------------------------------------------------------


def test_the_key_comes_from_deepseek_api_key_or_the_named_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-openai-key-0123456789")
    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        DeepSeekAdapter(ModelConfig("deepseek", MODEL))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-default-key")
    default = DeepSeekAdapter(ModelConfig("deepseek", MODEL))
    assert default.client.api_key == "ds-default-key"
    assert str(default.client.base_url).rstrip("/") == API_URL
    monkeypatch.setenv("MY_DS_KEY", "ds-named-key")
    named = DeepSeekAdapter(ModelConfig("deepseek", MODEL, api_key_env="MY_DS_KEY"))
    assert named.client.api_key == "ds-named-key"
    with pytest.raises(ConfigError, match="NOT_SET_ANYWHERE_123"):
        DeepSeekAdapter(ModelConfig("deepseek", MODEL, api_key_env="NOT_SET_ANYWHERE_123"))


def test_the_deepseek_key_is_never_sent_to_another_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-default-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-openai-key-0123456789")
    elsewhere = DeepSeekAdapter(
        ModelConfig("deepseek", "local", base_url="http://localhost:8000/v1")
    )
    assert elsewhere.client.api_key == "EMPTY"  # neither key leaves home
    monkeypatch.setenv("MY_SERVER_KEY", "local-secret")
    keyed = DeepSeekAdapter(
        ModelConfig(
            "deepseek", "local", base_url="http://localhost:8000/v1", api_key_env="MY_SERVER_KEY"
        )
    )
    assert keyed.client.api_key == "local-secret"


@pytest.mark.parametrize(
    "url",
    [
        None,
        API_URL,
        API_URL + "/",
        API_URL + "/beta",
        "https://API.DeepSeek.com/v1",  # host names have no case
    ],
)
def test_only_the_https_endpoint_of_deepseek_gets_the_default_key(
    url: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-default-key")
    adapter = DeepSeekAdapter(ModelConfig("deepseek", MODEL, base_url=url))
    assert adapter.client.api_key == "ds-default-key"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.deepseek.com.evil.io",  # a look-alike host
        "https://evilapi.deepseek.com",
        "https://api.deepseek.com@evil.io",  # user info: the host is evil.io
        "https://evil.io@api.deepseek.com",  # the right host, but user info rides along
        "https://api.deepseek.com:evil@evil.io",
        "https://api.deepseek.com:8443/v1",  # not the API's port
        "https://api.deepseek.com:443",
        "https://api.deepseek.com./v1",  # trailing dot
        "http://api.deepseek.com",  # the key would travel in clear
        "ftp://api.deepseek.com",
        "//api.deepseek.com",
        "api.deepseek.com",
        "https://evil.io\\@api.deepseek.com",  # parsers disagree about backslashes
        "https://api.deepseek.com\\.evil.io",
        "https://api.deepseek.com .evil.io",
        "https://api.deepseek.com\t.evil.io",
        "https://api.deepseek.com\n@evil.io",
        " https://api.deepseek.com",
        "https://[api.deepseek.com",
        "",
    ],
)
def test_no_other_url_gets_the_default_key(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-default-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-openai-key-0123456789")
    try:
        adapter = DeepSeekAdapter(ModelConfig("deepseek", MODEL, base_url=url))
    except ConfigError:
        return  # refused outright is as good
    assert adapter.client.api_key == "EMPTY"


def test_an_explicit_key_variable_goes_with_any_url_and_only_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-default-key")
    monkeypatch.setenv("MY_DS_KEY", "ds-named-key")
    for url in ("http://api.deepseek.com", "https://api.deepseek.com.evil.io", API_URL):
        named = DeepSeekAdapter(
            ModelConfig("deepseek", MODEL, base_url=url, api_key_env="MY_DS_KEY")
        )
        assert named.client.api_key == "ds-named-key"


def test_a_key_never_shows_in_an_error_or_in_the_logged_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("NOITABENCH_DEEPSEEK_KEY", secret)
    cfg = ModelConfig(
        "deepseek", MODEL, api_key_env="NOITABENCH_DEEPSEEK_KEY",
        base_url=f"https://user:{secret}@api.deepseek.com.evil.io/v1",
    )  # fmt: skip
    assert secret not in json.dumps(cfg.as_log())
    for code in (401, 402, 500):
        response = httpx2.Response(code, json={"error": {"message": f"bad key {secret}"}})
        with pytest.raises(ModelError) as err:
            conversation(Wire(response)).send([UserText("go")])
        assert secret not in str(err.value) and secret not in json.dumps(err.value.as_dict())


# -- the history keeps reasoning_content ----------------------------------------------------------


def test_reasoning_content_is_stored_and_sent_back_with_the_tool_calls() -> None:
    wire = Wire(
        reply(), reply({"role": "assistant", "content": "done", "reasoning_content": "ok"}, "stop")
    )
    conv = conversation(wire)
    turn = conv.send([UserText("Decision 1")])
    assert turn.thinking == THOUGHT and turn.stop == TOOL_USE
    conv.send([ToolResult("call_1", "wait", "Decision 2 ...")])
    sent = wire.body(1)["messages"]
    assert sent[2] == {
        "role": "assistant",
        "content": "",  # not null: the form the API's own sample sends back
        "tool_calls": [call_json()],
        "reasoning_content": THOUGHT,
    }
    assert sent[3] == {"role": "tool", "tool_call_id": "call_1", "content": "Decision 2 ..."}


def test_every_earlier_assistant_message_keeps_its_reasoning_even_without_tool_calls() -> None:
    wire = Wire(
        reply(
            {"role": "assistant", "content": "thinking out loud", "reasoning_content": "r1"}, "stop"
        ),
        reply(),
        reply({"role": "assistant", "content": "end", "reasoning_content": "r3"}, "stop"),
    )
    conv = conversation(wire)
    conv.send([UserText("one")])
    conv.send([UserText("two")])
    conv.send([ToolResult("call_1", "wait", "result")])
    assistants = [m for m in wire.body(2)["messages"] if m["role"] == "assistant"]
    assert [m["reasoning_content"] for m in assistants] == ["r1", THOUGHT]
    assert assistants[0]["content"] == "thinking out loud" and "tool_calls" not in assistants[0]


def test_a_cut_off_answer_keeps_what_it_had_thought() -> None:
    cut = reply({"role": "assistant", "content": "", "reasoning_content": "half a tho"}, "length")
    wire = Wire(cut, reply())
    conv = conversation(wire)
    turn = conv.send([UserText("go")])
    assert turn.stop == MAX_TOKENS
    assert conv.messages[-1] == {
        "role": "assistant",
        "content": "(my answer was cut off)",
        "reasoning_content": "half a tho",
    }


def test_without_thinking_no_reasoning_content_is_invented() -> None:
    wire = Wire(reply({"role": "assistant", "content": "hi"}, "stop"), reply())
    conv = conversation(wire, thinking="off")
    conv.send([UserText("one")])
    conv.send([UserText("two")])
    assert "reasoning_content" not in wire.body(1)["messages"][2]


def test_with_thinking_on_an_answer_without_reasoning_still_carries_the_field() -> None:
    """An answer that names no reasoning must not make the next request fail with 400."""
    bare = {"role": "assistant", "content": "", "tool_calls": [call_json()]}
    null = {"role": "assistant", "content": "ok", "reasoning_content": None}
    wire = Wire(reply(bare), reply(null, "stop"), reply())
    conv = conversation(wire)
    conv.send([UserText("one")])
    conv.send([ToolResult("call_1", "wait", "result")])
    conv.send([UserText("two")])
    assistants = [m for m in wire.body(2)["messages"] if m["role"] == "assistant"]
    assert [m["reasoning_content"] for m in assistants] == ["", ""]


def test_a_refused_answer_leaves_the_history_alone() -> None:
    refused = reply(
        {"role": "assistant", "content": "", "reasoning_content": "r"}, "content_filter"
    )
    wire = Wire(refused, reply())
    conv = conversation(wire)
    assert conv.send([UserText("go")]).stop == "refusal" and conv.messages == []
    conv.send([UserText("go")])
    assert [m["role"] for m in wire.body(1)["messages"]] == ["system", "user"]


def test_a_fork_copies_the_history_with_its_reasoning() -> None:
    wire = Wire(
        reply(), reply({"role": "assistant", "content": "helper", "reasoning_content": "h"}, "stop")
    )
    adapter = adapter_for(wire)
    parent = adapter.new_conversation("You play a game.", TOOLS)
    parent.send([UserText("Decision 1")])
    child = fork_conversation(adapter, parent, "You play a game.", TOOLS)
    child.send([ToolResult("call_1", "wait", "not run"), UserText("You are a helper now.")])
    sent = wire.body(1)["messages"]
    assert sent[2]["role"] == "assistant" and sent[2]["reasoning_content"] == THOUGHT
    assert len(parent.messages) == 2  # the parent was not written to


def test_a_new_conversation_holds_no_assistant_message() -> None:
    """After a briefing the loop opens a new conversation: it has nothing to send back."""
    wire = Wire(reply())
    adapter = adapter_for(wire)
    old = adapter.new_conversation("s", TOOLS)
    old.send([UserText("one")])
    fresh = adapter.new_conversation("s", TOOLS)
    assert fresh.messages == [] and old.messages != []


def test_pictures_go_as_png_data_urls_in_a_user_message() -> None:
    wire = Wire(reply(), reply())
    conv = conversation(wire)
    conv.send([UserText("go")])
    conv.send([ToolResult("call_1", "wait", "view", images=(b"\x89PNGdata",))])
    picture = wire.body(1)["messages"][-1]["content"][1]["image_url"]["url"]
    assert picture == "data:image/png;base64," + base64.b64encode(b"\x89PNGdata").decode()


# -- usage and the served model -------------------------------------------------------------------


def test_usage_from_the_openai_style_cache_field_and_the_thinking_tokens() -> None:
    turn = conversation(Wire(reply())).send([UserText("go")])
    assert turn.usage == Usage(200, 800, 0, 50, 20)
    assert turn.model == SERVED  # the model the answer names, not the alias that was asked for


def test_usage_falls_back_to_the_deepseek_hit_field() -> None:
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "total_tokens": 1050,
        "prompt_cache_hit_tokens": 900,
        "prompt_cache_miss_tokens": 100,
    }
    turn = conversation(Wire(reply(usage=usage))).send([UserText("go")])
    assert turn.usage == Usage(100, 900, 0, 50, None) and turn.usage.prompt_tokens == 1000


def test_usage_without_any_cache_field_is_all_fresh_input() -> None:
    usage = {"prompt_tokens": 700, "completion_tokens": 5, "total_tokens": 705}
    turn = conversation(Wire(reply(usage=usage))).send([UserText("go")])
    assert turn.usage == Usage(700, 0, 0, 5, None)


# -- errors and finish reasons --------------------------------------------------------------------


@pytest.mark.parametrize("finish", ["insufficient_system_resource", "aborted"])
def test_a_server_that_gives_up_is_a_retryable_error_and_nothing_is_appended(finish: str) -> None:
    wire = Wire(
        reply({"role": "assistant", "content": "par", "reasoning_content": "t"}, finish), reply()
    )
    conv = conversation(wire)
    with pytest.raises(ModelError) as err:
        conv.send([UserText("go")])
    assert (err.value.kind, err.value.retryable) == ("server", True)
    assert finish in str(err.value) and conv.messages == []
    assert conv.send([UserText("go")]).stop == TOOL_USE  # the same items work the second time


@pytest.mark.parametrize(
    ("code", "kind", "retryable"),
    [
        (400, "bad_request", False),
        (401, "auth", False),
        (402, "balance", False),
        (422, "api", False),
        (429, "rate_limit", True),
        (500, "server", True),
        (503, "server", True),
    ],
)
def test_status_errors(code: int, kind: str, retryable: bool) -> None:
    response = httpx2.Response(code, json={"error": {"message": "nope", "type": "x", "code": None}})
    wire = Wire(response, reply())
    conv = conversation(wire)
    with pytest.raises(ModelError) as err:
        conv.send([UserText("go")])
    assert (err.value.kind, err.value.retryable, err.value.status) == (kind, retryable, code)
    assert conv.messages == []
    if code == 402:
        assert "balance" in str(err.value) and "nope" in str(err.value)


def test_an_unusual_answer_is_not_mistaken_for_an_error() -> None:
    plain = reply({"role": "assistant", "content": "just text", "reasoning_content": "r"}, "stop")
    turn = conversation(Wire(plain)).send([UserText("go")])
    assert turn.stop == END_TURN and turn.text == "just text"


# -- the loop -------------------------------------------------------------------------------------


class Server:
    """A DeepSeek that answers every call with a `wait` tool call (with thoughts), and a briefing
    when asked for one. `prompt_tokens` grows with the calls so that the loop compacts."""

    def __init__(self, fail_with: int | None = None, resource_once: bool = False) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.fail_with = fail_with
        self.resource_once = resource_once

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.fail_with:
            return httpx2.Response(
                self.fail_with, json={"error": {"message": "Insufficient Balance"}}
            )
        n = len(self.bodies)
        if self.resource_once and n == 1:
            return httpx2.Response(200, json=reply(finish="insufficient_system_resource"))
        last = body["messages"][-1]
        asked_for_briefing = isinstance(last["content"], str) and SUMMARY_REQUEST in last["content"]
        usage = {"prompt_tokens": 2000 * n, "completion_tokens": 30, "total_tokens": 2000 * n + 30}
        if asked_for_briefing:
            message = {
                "role": "assistant",
                "content": "Briefing: stay put.",
                "reasoning_content": f"b{n}",
            }
            return httpx2.Response(200, json=reply(message, "stop", usage))
        message = {
            "role": "assistant",
            "content": "",
            "reasoning_content": f"thought {n}",
            "tool_calls": [call_json(n, "wait", '{"ticks":1}')],
        }
        return httpx2.Response(200, json=reply(message, "tool_calls", usage))


def test_a_whole_game_with_compaction_never_breaks_the_reasoning_rule(
    run_config, make_game, tmp_path: Path
) -> None:
    server = Server()
    cfg = run_config(
        model=ModelConfig("deepseek", MODEL, max_retries=0),
        context_limit=5_000,
        max_decisions=8,
    )
    adapter = adapter_for(server)
    summary = run_family(cfg, adapter=adapter, game_factory=make_game, sleep=lambda _s: None)[0]
    result = summary["result"]
    assert result["over"] == "decision_limit" and result["summaries"] >= 1
    # the rule: a request that carries tools sends back the reasoning of every assistant message
    with_assistants = 0
    for body in server.bodies:
        assert "tools" in body
        for message in body["messages"]:
            if message["role"] == "assistant":
                with_assistants += 1
                assert message["reasoning_content"], message
    assert with_assistants > 0
    # after a briefing the conversation starts again: no assistant message in its first request
    opened = [b for b in server.bodies if all(m["role"] != "assistant" for m in b["messages"])]
    assert len(opened) >= 2
    # the run records the model the answers named, in both logs
    assert result["models_seen"] == [SERVED] and summary["model"]["model"] == MODEL
    rows = [json.loads(x) for x in (cfg.out / "harness.jsonl").read_text().splitlines()]
    assert {r["model"] for r in rows if "model" in r} == {SERVED}
    assert all(r["provider"] == "deepseek" for r in rows)
    price = summary["price"]
    assert price["cache_write_factor"] == 1.0 and "peak" in price["source"]


def test_a_server_that_gives_up_once_is_retried_by_the_loop(run_config, make_game) -> None:
    server = Server(resource_once=True)
    cfg = run_config(model=ModelConfig("deepseek", MODEL, max_retries=0), max_decisions=2)
    summary = run_family(
        cfg, adapter=adapter_for(server), game_factory=make_game, sleep=lambda _s: None
    )[0]
    assert summary["result"]["over"] == "decision_limit"
    log = [json.loads(x) for x in (cfg.out / "harness.jsonl").read_text().splitlines()]
    assert log[0]["error"]["kind"] == "server" and log[0]["error"]["retryable"] is True
    assert log[1].get("attempt") is None and "error" not in log[1]


def test_no_balance_stops_the_game_with_a_clear_message_and_no_retry(
    run_config, make_game, tmp_path: Path
) -> None:
    server = Server(fail_with=402)
    cfg = run_config(
        model=ModelConfig("deepseek", MODEL, max_retries=0),
        max_decisions=3,
        runs=3,
        out=tmp_path / "fam",
    )
    summaries = run_family(
        cfg, adapter=adapter_for(server), game_factory=make_game, sleep=lambda _s: None
    )
    assert len(server.bodies) == 1  # not retried, and the other games were not even started
    assert len(summaries) == 1
    result = summaries[0]["result"]
    assert result["over"] == "model_error" and result["detail"].startswith("balance:")
    assert "balance" in result["detail"] and "top it up" in result["detail"]


def test_the_dollar_budget_stops_a_game_at_deepseeks_prices(run_config, make_game) -> None:
    server = Server()
    cfg = run_config(
        model=ModelConfig("deepseek", MODEL, max_retries=0), max_decisions=50, budget_usd=0.002
    )
    summary = run_family(
        cfg, adapter=adapter_for(server), game_factory=make_game, sleep=lambda _s: None
    )[0]
    result = summary["result"]
    assert result["over"] == "budget_usd" and 0 < result["cost_usd"] <= 0.002
    # the Server answers call n with a prompt of 2000 n tokens, none of them cached
    expected = sum((2000 * n * 0.30 + 30 * 1.20) / 1e6 for n in range(1, result["model_calls"] + 1))
    assert result["cost_usd"] == pytest.approx(expected, rel=1e-3)


# -- limits that depend on the provider ----------------------------------------------------------


def test_deepseek_gets_a_larger_output_limit_and_a_longer_timeout_by_default() -> None:
    deepseek = ModelConfig("deepseek", MODEL)
    assert (deepseek.max_output_tokens, deepseek.request_timeout) == (32768, 600.0)
    for provider in ("anthropic", "openai", "gemini", "fake"):
        other = ModelConfig(provider, "m")
        assert (other.max_output_tokens, other.request_timeout) == (8192, 180.0)
    given = ModelConfig("deepseek", MODEL, max_output_tokens=4096, request_timeout=30)
    assert (given.max_output_tokens, given.request_timeout) == (4096, 30)
    logged = deepseek.as_log()
    assert (logged["max_output_tokens"], logged["request_timeout"]) == (32768, 600.0)


def test_the_cli_leaves_the_limits_to_the_provider_unless_they_are_given() -> None:
    base = ["run", "--model", "m", "--world-seed", "1", "--out", "x", "--provider"]
    for provider, tokens, seconds in (("deepseek", 32768, 600.0), ("anthropic", 8192, 180.0)):
        config = _model_config(_parser().parse_args([*base, provider]))
        assert (config.max_output_tokens, config.request_timeout) == (tokens, seconds)
    given = _parser().parse_args(
        [*base, "deepseek", "--max-output-tokens", "16000", "--request-timeout", "90"]
    )
    config = _model_config(given)
    assert (config.max_output_tokens, config.request_timeout) == (16000, 90.0)


def test_the_notes_extractor_reads_without_thinking_on_deepseek_too() -> None:
    from noitabench.eval.knowledge.claims_cli import model_config

    config = model_config("deepseek", MODEL, "MY_DS_KEY")
    assert config.thinking == "off" and config.api_key_env == "MY_DS_KEY"
    assert config.max_output_tokens == 4096  # no thinking to pay for out of it


def test_the_client_and_the_request_use_the_deepseek_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-default-key")
    adapter = DeepSeekAdapter(ModelConfig("deepseek", MODEL))
    assert adapter.client.timeout == 600.0
    wire = Wire(reply())
    DeepSeekAdapter(ModelConfig("deepseek", MODEL), client_for(wire)).new_conversation(
        "s", TOOLS
    ).send([UserText("go")])
    assert wire.body()["max_tokens"] == 32768


# -- prices, screenshots and the commands ---------------------------------------------------------


def test_the_prices_are_deepseeks_peak_rates() -> None:
    flash, pro = PRICES["deepseek-flash"], PRICES["deepseek-v4-pro"]
    usage = Usage(input_tokens=200, cache_read_tokens=800, output_tokens=50)
    assert flash.cost(usage) == pytest.approx((200 * 0.30 + 800 * 0.006 + 50 * 1.20) / 1e6)
    assert pro.cost(usage) == pytest.approx((200 * 1.32 + 800 * 0.044 + 50 * 3.96) / 1e6)
    for price in (flash, pro):
        assert price.cache_write_factor == 1.0 and len(price.tiers) == 1
        assert "peak" in price.source and "2026-10-28" in price.source
    assert resolve_price("deepseek-v4-pro") is pro
    # 1M context windows: the harness's general compaction limit is kept
    assert default_context_limit(flash) == default_context_limit(pro) == 120_000


def test_pictures_are_refused_for_the_model_that_cannot_read_them(tmp_path: Path) -> None:
    view = ViewConfig(screenshot=True)
    RunConfig(ModelConfig("deepseek", "deepseek-flash"), out=tmp_path / "a", view=view)
    with pytest.raises(ConfigError, match="cannot read pictures"):
        RunConfig(ModelConfig("deepseek", "deepseek-v4-pro"), out=tmp_path / "b", view=view)
    # without the picture channel it is fine
    RunConfig(ModelConfig("deepseek", "deepseek-v4-pro"), out=tmp_path / "c")


def test_the_cli_refuses_a_screenshot_with_v4_pro_before_starting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = harness_main(
        ["run", "--provider", "deepseek", "--model", "deepseek-v4-pro", "--screenshot",
         "--world-seed", "1", "--out", str(tmp_path / "x")]
    )  # fmt: skip
    assert code == 2 and "cannot read pictures" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-pro"])
def test_estimate_works_for_deepseek(model: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = harness_main(
        ["estimate", "--provider", "deepseek", "--model", model, "--max-decisions", "200",
         "--runs", "3"]
    )  # fmt: skip
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["typical_usd"] > 0 and data["runs"] == 3
    assert data["low_usd"] < data["typical_usd"] < data["high_usd"]
    assert data["without_cache_usd"] > data["typical_usd"]
    assert data["context_limit_tokens"] == 120_000


def test_estimate_of_flash_is_cheaper_than_pro(capsys: pytest.CaptureFixture[str]) -> None:
    costs = {}
    for model in ("deepseek-flash", "deepseek-v4-pro"):
        harness_main(["estimate", "--provider", "deepseek", "--model", model])
        costs[model] = json.loads(capsys.readouterr().out)["typical_usd"]
    assert costs["deepseek-flash"] < costs["deepseek-v4-pro"]
