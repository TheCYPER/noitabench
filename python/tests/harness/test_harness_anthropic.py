"""The Anthropic adapter, against the real SDK with a mocked transport (no network)."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import replace
from typing import Any

import anthropic
import httpx2
import pytest
from noitabench.harness import ConfigError, ModelConfig, ModelError, ToolResult, ToolSpec, UserText
from noitabench.harness.adapters.anthropic_adapter import (
    COMPACT_BETA,
    PUBLIC_URL,
    AnthropicAdapter,
)
from noitabench.harness.model import END_TURN, MAX_TOKENS, REFUSAL, TOOL_USE
from noitabench.harness.prices import PRICES
from noitabench.harness.usage import Usage

MODEL = "claude-haiku-5-5"
TOOLS = (
    ToolSpec(
        "wait", "Stand still.", {"type": "object", "properties": {"ticks": {"type": "integer"}}}
    ),
    ToolSpec("kick", "Kick.", {"type": "object", "properties": {}}),
)
SIGNED = {"type": "thinking", "thinking": "the way is clear", "signature": "sig-abc"}
CALL = {"type": "tool_use", "id": "toolu_01", "name": "wait", "input": {"ticks": 2}}


def message(
    content: list[dict[str, Any]],
    stop: str = "tool_use",
    *,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": usage
        or {
            "input_tokens": 30,
            "output_tokens": 12,
            "cache_creation_input_tokens": 1000,
            "cache_read_input_tokens": 0,
        },
    }


class Wire:
    """A mocked transport: records requests, answers from a list of JSON bodies or errors."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx2.Response):
            return answer
        return httpx2.Response(200, json=answer, headers={"request-id": "req_test"})

    def body(self, i: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def adapter_for(wire: Wire, **config: Any) -> AnthropicAdapter:
    cfg = ModelConfig("anthropic", MODEL, max_retries=0, **config)
    client = anthropic.Anthropic(
        api_key="test-key",
        base_url=PUBLIC_URL,
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(wire)),
    )
    return AnthropicAdapter(cfg, client)


def conversation(wire: Wire, **config: Any):
    return adapter_for(wire, **config).new_conversation("You play a game.", TOOLS)


# -- the request ----------------------------------------------------------------------------------


def test_request_shape() -> None:
    wire = Wire(message([SIGNED, CALL]))
    conv = conversation(wire)
    conv.send([UserText("Decision 1 ...")])
    request, body = wire.requests[0], wire.body()
    assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
    assert body["model"] == MODEL and body["max_tokens"] == 8192
    assert body["system"] == [
        {"type": "text", "text": "You play a game.", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["cache_control"] == {"type": "ephemeral"}  # automatic caching of the tail
    assert [t["name"] for t in body["tools"]] == ["wait", "kick"]
    assert body["tools"][0]["input_schema"]["properties"]["ticks"] == {"type": "integer"}
    assert body["tool_choice"] == {"type": "auto"}
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "medium"}
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Decision 1 ..."}]}
    ]
    for banned in ("temperature", "top_p", "top_k", "stream", "betas", "context_management"):
        assert banned not in body
    assert "anthropic-beta" not in request.headers


def test_options_change_only_what_they_name() -> None:
    wire = Wire(message([CALL]))
    conv = conversation(wire, effort="high", thinking="off", max_output_tokens=2048)
    conv.send([UserText("go")])
    body = wire.body()
    assert body["output_config"] == {"effort": "high"} and body["max_tokens"] == 2048
    assert body["thinking"] == {"type": "disabled"}
    wire = Wire(message([CALL]))
    conversation(wire, thinking="default").send([UserText("go")])
    assert "thinking" not in wire.body()
    with pytest.raises(ConfigError):
        adapter_for(Wire(), effort="extreme")
    with pytest.raises(ConfigError):
        adapter_for(Wire(), thinking="loud")


def test_without_tools_no_tool_fields_are_sent() -> None:
    wire = Wire(message([{"type": "text", "text": "walk_to(x=3)"}], "end_turn"))
    adapter_for(wire).new_conversation("sys", []).send([UserText("go")])
    body = wire.body()
    assert "tools" not in body and "tool_choice" not in body


def test_the_environment_base_url_is_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://desktop-proxy.invalid:9999")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-for-the-test")
    adapter = AnthropicAdapter(ModelConfig("anthropic", MODEL, max_retries=3, request_timeout=42))
    assert str(adapter.client.base_url).rstrip("/") == "https://api.anthropic.com"
    assert adapter.client.max_retries == 3 and adapter.client.timeout == 42
    monkeypatch.setenv("GATEWAY_KEY_FOR_THE_TEST", "key-for-the-gateway-0004")
    own = AnthropicAdapter(
        ModelConfig(
            "anthropic",
            MODEL,
            base_url="http://gateway.test:8080",
            api_key_env="GATEWAY_KEY_FOR_THE_TEST",
        )
    )
    assert str(own.client.base_url).startswith("http://gateway.test:8080")


def test_the_key_is_read_here_and_a_gateways_credentials_are_never_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The desktop app sets a token, custom headers and a base URL for its own gateway. The SDK
    would read the first two and send them to whatever endpoint it is given."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-from-the-user-0001")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token-0002")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "X-Gateway: gateway-secret-0003")
    monkeypatch.setenv("ANTHROPIC_PROFILE", "some-profile")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://desktop-proxy.invalid:9999")
    client = AnthropicAdapter(ModelConfig("anthropic", MODEL)).client
    assert client.auth_headers == {"Authorization": "Bearer key-from-the-user-0001"}
    assert client.auth_token is None
    sent = " ".join(f"{k}: {v}" for k, v in client.default_headers.items())
    assert "gateway" not in sent.lower()
    assert str(client.base_url).rstrip("/") == "https://api.anthropic.com"
    # the environment is as it was
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "gateway-token-0002"
    assert os.environ["ANTHROPIC_CUSTOM_HEADERS"] == "X-Gateway: gateway-secret-0003"


def test_a_gateway_token_alone_is_not_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "gateway-token-0002")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        AnthropicAdapter(ModelConfig("anthropic", MODEL))


def test_a_custom_base_url_needs_its_own_named_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-from-the-user-0001")
    monkeypatch.setenv("MY_GATEWAY_KEY", "key-for-the-gateway-0004")
    with pytest.raises(ConfigError, match="--api-key-env"):
        AnthropicAdapter(ModelConfig("anthropic", MODEL, base_url="http://gateway.test:8080"))
    own = AnthropicAdapter(
        ModelConfig(
            "anthropic", MODEL, base_url="http://gateway.test:8080", api_key_env="MY_GATEWAY_KEY"
        )
    )
    assert own.client.auth_headers == {"Authorization": "Bearer key-for-the-gateway-0004"}


@pytest.mark.parametrize(
    ("model", "effort", "ok"),
    [
        (MODEL, None, True),
        (MODEL, "high", True),
        (MODEL, "xhigh", False),  # the API answers 400: thinking off above `high`
        (MODEL, "max", False),
        ("claude-sonnet-5-5", None, False),  # 400 on Sonnet 5.5 and Opus 5.5: always thinking
        ("claude-opus-5-5", "low", False),
    ],
)
def test_thinking_off_is_refused_where_the_api_would_refuse_it(
    model: str, effort: str | None, ok: bool
) -> None:
    cfg = ModelConfig("anthropic", model, effort=effort, thinking="off", max_retries=0)
    client = anthropic.Anthropic(api_key="test-key", base_url=PUBLIC_URL, max_retries=0)
    if ok:
        AnthropicAdapter(cfg, client)
    else:
        with pytest.raises(ConfigError, match="thinking"):
            AnthropicAdapter(cfg, client)
    # adaptive thinking is fine on every model and at every effort
    AnthropicAdapter(replace(cfg, thinking="adaptive", effort="max"), client)


def test_a_key_variable_that_is_not_set_is_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_SUCH_KEY_VARIABLE", raising=False)
    with pytest.raises(ConfigError, match="NO_SUCH_KEY_VARIABLE"):
        AnthropicAdapter(ModelConfig("anthropic", MODEL, api_key_env="NO_SUCH_KEY_VARIABLE"))


# -- the answer -----------------------------------------------------------------------------------


def test_the_answer_is_read_by_block_type() -> None:
    usage = {
        "input_tokens": 30,
        "output_tokens": 120,
        "cache_creation_input_tokens": 1000,
        "cache_read_input_tokens": 40_000,
        "output_tokens_details": {"thinking_tokens": 90},
    }
    wire = Wire(
        message(
            [SIGNED, {"type": "text", "text": "Waiting."}, CALL],
            usage=usage,
        )
    )
    turn = conversation(wire).send([UserText("go")])
    assert turn.stop == TOOL_USE and turn.raw_stop == "tool_use"
    assert turn.text == "Waiting." and turn.thinking == "the way is clear"
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [
        ("toolu_01", "wait", {"ticks": 2})
    ]
    assert turn.usage == Usage(30, 40_000, 1000, 120, 90)
    assert turn.usage.prompt_tokens == 41_030
    assert turn.request_id == "req_test" and turn.model == MODEL
    cost = PRICES[MODEL].cost(turn.usage)
    assert cost == pytest.approx((30 * 0.10 + 40_000 * 0.01 + 1000 * 0.125 + 120 * 0.50) / 1e6)


def test_text_only_answers_end_the_turn() -> None:
    wire = Wire(message([{"type": "text", "text": "Hello"}], "end_turn"))
    turn = conversation(wire).send([UserText("go")])
    assert turn.stop == END_TURN and turn.tool_calls == ()


# -- the history ----------------------------------------------------------------------------------


def test_history_is_append_only_and_thinking_goes_back_unchanged() -> None:
    first = message([SIGNED, {"type": "text", "text": "Waiting."}, CALL])
    second = message([{"type": "text", "text": "Done."}], "end_turn")
    wire = Wire(first, second)
    conv = conversation(wire)
    conv.send([UserText("Decision 1")])
    conv.send([ToolResult("toolu_01", "wait", "Decision 2 ...")])
    one, two = wire.body(0), wire.body(1)
    assert two["messages"][:1] == one["messages"]  # what was sent before is sent again, as it was
    assistant = two["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0] == SIGNED  # the signed thinking block, byte for byte
    assert [b["type"] for b in assistant["content"]] == ["thinking", "text", "tool_use"]
    assert two["messages"][2] == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_01", "content": "Decision 2 ..."}
        ],
    }
    # the prefix that caching depends on is the same in both requests
    for key in ("model", "system", "tools", "tool_choice", "thinking", "output_config"):
        assert json.dumps(one[key], sort_keys=True) == json.dumps(two[key], sort_keys=True)


def test_all_results_of_a_turn_are_one_user_message_errors_flagged_text_after() -> None:
    two_calls = message(
        [
            {"type": "tool_use", "id": "a", "name": "wait", "input": {}},
            {"type": "tool_use", "id": "b", "name": "kick", "input": {}},
        ]
    )
    wire = Wire(two_calls, message([CALL]))
    conv = conversation(wire)
    turn = conv.send([UserText("go")])
    assert [c.id for c in turn.tool_calls] == ["a", "b"]
    conv.send(
        [UserText("a nudge"), ToolResult("a", "wait", "ok"), ToolResult("b", "kick", "no", True)]
    )
    last = wire.body(1)["messages"][-1]
    assert last["role"] == "user"
    assert last["content"] == [  # tool results first, then the text
        {"type": "tool_result", "tool_use_id": "a", "content": "ok"},
        {"type": "tool_result", "tool_use_id": "b", "content": "no", "is_error": True},
        {"type": "text", "text": "a nudge"},
    ]


def test_images_go_inside_the_tool_result() -> None:
    wire = Wire(message([CALL]), message([CALL]))
    conv = conversation(wire)
    conv.send([UserText("go")])
    conv.send([ToolResult("toolu_01", "wait", "view", images=(b"\x89PNGdata",))])
    block = wire.body(1)["messages"][-1]["content"][0]
    assert block["content"][0] == {"type": "text", "text": "view"}
    assert block["content"][1]["source"]["media_type"] == "image/png"
    assert base64.b64decode(block["content"][1]["source"]["data"]) == b"\x89PNGdata"


def test_empty_results_and_texts() -> None:
    wire = Wire(message([CALL]), message([CALL]))
    conv = conversation(wire)
    with pytest.raises(ValueError):
        conv.send([UserText("  ")])
    with pytest.raises(ValueError):
        conv.send([])
    conv.send([UserText("go")])
    conv.send([ToolResult("toolu_01", "wait", "")])
    assert wire.body(1)["messages"][-1]["content"][0]["content"] == "(no output)"


def test_a_cut_off_answer_leaves_a_stand_in_not_half_a_tool_call() -> None:
    cut = message([SIGNED, {"type": "text", "text": "I will"}, CALL], "max_tokens")
    wire = Wire(cut, message([CALL]))
    conv = conversation(wire)
    turn = conv.send([UserText("go")])
    assert turn.stop == MAX_TOKENS and turn.tool_calls == ()
    conv.send([UserText("shorter, please")])
    sent = wire.body(1)["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[1]["content"] == [{"type": "text", "text": "(my answer was cut off)"}]


def test_a_refusal_is_reported_and_not_appended() -> None:
    wire = Wire(message([], "refusal"), message([CALL]))
    conv = conversation(wire)
    turn = conv.send([UserText("go")])
    assert turn.stop == REFUSAL and turn.tool_calls == ()
    assert conv.messages == []
    conv.send([UserText("go")])  # the same step again
    assert [m["role"] for m in wire.body(1)["messages"]] == ["user"]
    assert len(conv.messages) == 2


def test_blank_text_blocks_are_not_sent_back_and_a_thinking_only_answer_gets_a_line() -> None:
    blank = {"type": "text", "text": ""}
    spaces = {"type": "text", "text": " \n"}
    wire = Wire(
        message([SIGNED, blank, CALL, spaces]),
        message([SIGNED], "end_turn"),  # the answer was all in the thinking
        message([CALL]),
    )
    conv = conversation(wire)
    first = conv.send([UserText("go")])
    assert [c.name for c in first.tool_calls] == ["wait"]
    second = conv.send([ToolResult("toolu_01", "wait", "ok")])
    assert second.stop == END_TURN and second.text == ""
    conv.send([UserText("again")])
    sent = wire.body(2)["messages"]
    assert [b["type"] for b in sent[1]["content"]] == ["thinking", "tool_use"]  # no blank text
    assert sent[1]["content"][0] == SIGNED  # the signed block itself is untouched
    assert [b["type"] for b in sent[3]["content"]] == ["thinking", "text"]
    assert sent[3]["content"][1]["text"] == "(no reply)"


def test_a_refusal_names_its_category_when_the_api_gives_one() -> None:
    refused = message([], "refusal")
    refused["stop_details"] = {"type": "refusal", "category": "cyber", "explanation": None}
    turn = conversation(Wire(refused, message([], "refusal"))).send([UserText("go")])
    assert turn.stop == REFUSAL and turn.raw_stop == "refusal (cyber)"
    plain = conversation(Wire(message([], "refusal"))).send([UserText("go")])
    assert plain.raw_stop == "refusal"


def test_an_empty_answer_gets_a_stand_in() -> None:
    wire = Wire(message([], "end_turn"), message([CALL]))
    conv = conversation(wire)
    conv.send([UserText("go")])
    conv.send([UserText("again")])
    assert wire.body(1)["messages"][1]["content"] == [{"type": "text", "text": "(no reply)"}]


# -- errors ---------------------------------------------------------------------------------------


def status(code: int, kind: str = "api_error", text: str = "nope") -> httpx2.Response:
    return httpx2.Response(
        code,
        json={"type": "error", "error": {"type": kind, "message": text}},
        headers={"request-id": "req_err"},
    )


@pytest.mark.parametrize(
    ("answer", "kind", "retryable", "code"),
    [
        (status(401, "authentication_error", "invalid x-api-key"), "auth", False, 401),
        (status(403, "permission_error"), "permission", False, 403),
        (status(404, "not_found_error"), "not_found", False, 404),
        (status(400, "invalid_request_error", "thinking: bad"), "bad_request", False, 400),
        (status(429, "rate_limit_error"), "rate_limit", True, 429),
        (status(500), "server", True, 500),
        (status(503), "server", True, 503),
        (status(529, "overloaded_error"), "overloaded", True, 529),
        (httpx2.ReadTimeout("slow"), "timeout", True, None),
        (httpx2.ConnectError("down"), "connection", True, None),
    ],
)
def test_errors_are_mapped_and_leave_the_conversation_alone(
    answer: Any, kind: str, retryable: bool, code: int | None
) -> None:
    wire = Wire(answer, message([CALL]))
    conv = conversation(wire)
    with pytest.raises(ModelError) as err:
        conv.send([UserText("go")])
    assert (err.value.kind, err.value.retryable, err.value.status) == (kind, retryable, code)
    assert conv.messages == []  # nothing was appended: the same items can be sent again
    conv.send([UserText("go")])
    assert len(conv.messages) == 2


def test_sdk_errors_that_are_not_about_credentials_are_not_called_auth() -> None:
    from noitabench.harness.adapters.anthropic_adapter import map_error

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    odd = anthropic.APIResponseValidationError(
        response=httpx2.Response(200, request=request), body=None
    )
    mapped = map_error(odd)
    assert mapped is not None and mapped.kind == "unknown" and not mapped.retryable
    creds = map_error(anthropic.CredentialsError("no profile"))
    assert creds is not None and creds.kind == "auth"
    assert map_error(ValueError("not the SDK's")) is None


def test_error_text_carries_the_request_id_and_hides_keys() -> None:
    wire = Wire(status(401, "authentication_error", "bad key sk-ant-api03-ABCDEFGHIJKLMNOP given"))
    with pytest.raises(ModelError) as err:
        conversation(wire).send([UserText("go")])
    assert err.value.request_id == "req_err"
    assert "ABCDEFGHIJKLMNOP" not in str(err.value) and "[redacted]" in str(err.value)


# -- server-side compaction -----------------------------------------------------------------------


def test_server_compaction_uses_the_beta_and_counts_the_compaction_call() -> None:
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1_000,
        "iterations": [
            {
                "type": "compaction",
                "input_tokens": 60_000,
                "output_tokens": 700,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            {
                "type": "message",
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1_000,
            },
        ],
    }
    wire = Wire(
        message(
            [{"type": "compaction", "content": "summary", "encrypted_content": None}, CALL],
            usage=usage,
        )
    )
    conv = conversation(wire, server_compaction=80_000)
    turn = conv.send([UserText("go")])
    request, body = wire.requests[0], wire.body()
    assert request.headers["anthropic-beta"] == COMPACT_BETA
    edit = body["context_management"]["edits"][0]
    assert edit["type"] == "compact_20260112" and edit["trigger"] == {
        "type": "input_tokens",
        "value": 80_000,
    }
    assert "briefing" in edit["instructions"]
    # the call itself plus the compaction step, which the top-level usage leaves out
    assert turn.usage == Usage(60_100, 1_000, 0, 750, None)
    assert conv.last_prompt_tokens == 1_100
    assert turn.tool_calls[0].name == "wait"
    # the compaction block goes back with the rest of the answer
    assert conv.messages[-1]["content"][0].type == "compaction"


# -- through the loop -----------------------------------------------------------------------------


def test_a_whole_game_through_the_sdk(make_game, run_config) -> None:
    from noitabench.harness import run_family

    answers = [
        message(
            [
                SIGNED,
                {"type": "tool_use", "id": f"toolu_{i}", "name": "wait", "input": {"ticks": 1}},
            ],
            usage={
                "input_tokens": 50,
                "output_tokens": 40,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 1_000 * i,
            },
        )
        for i in range(1, 8)
    ]
    wire = Wire(*answers)
    cfg = run_config(model=ModelConfig("anthropic", MODEL, max_retries=0), max_decisions=3)
    summary = run_family(cfg, adapter=adapter_for(wire), game_factory=make_game)[0]
    r = summary["result"]
    assert r["over"] == "decision_limit" and r["model_calls"] == 3
    expected = sum(PRICES[MODEL].cost(Usage(50, 1_000 * i, 200, 40)) for i in range(1, 4))
    assert r["cost_usd"] == pytest.approx(expected)
    # the second request carries the first answer's signed thinking block unchanged
    assert wire.body(1)["messages"][1]["content"][0] == SIGNED
    assert wire.body(2)["messages"][1]["content"][0] == SIGNED
    assert wire.body(2)["messages"][3]["content"][0] == SIGNED
    # every request has the same prefix
    assert wire.body(0)["tools"] == wire.body(2)["tools"]
    # tool results of the game go back as tool_result blocks of the right call
    result_block = wire.body(1)["messages"][2]["content"][0]
    assert result_block["type"] == "tool_result" and result_block["tool_use_id"] == "toolu_1"
    assert result_block["content"].startswith("Decision 2")


def test_the_loop_survives_a_flaky_connection(make_game, run_config) -> None:
    from noitabench.harness import run_family

    good = message([{"type": "tool_use", "id": "t", "name": "wait", "input": {"ticks": 1}}])
    wire = Wire(httpx2.ConnectError("blip"), good, good)
    cfg = run_config(model=ModelConfig("anthropic", MODEL, max_retries=0), max_decisions=2)
    summary = run_family(
        cfg, adapter=adapter_for(wire), game_factory=make_game, sleep=lambda _s: None
    )[0]
    assert summary["result"]["over"] == "decision_limit"


def test_missing_credentials_are_an_auth_error_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    wire = Wire(message([CALL]))
    client = anthropic.Anthropic(
        base_url=PUBLIC_URL,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(wire)),
    )
    adapter = AnthropicAdapter(ModelConfig("anthropic", MODEL), client)
    with pytest.raises(ModelError, match="ANTHROPIC_API_KEY") as err:
        adapter.new_conversation("sys", TOOLS).send([UserText("go")])
    assert err.value.kind == "auth" and not err.value.retryable
    assert wire.requests == []  # nothing was sent
