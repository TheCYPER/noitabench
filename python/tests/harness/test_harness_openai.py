"""The OpenAI-compatible adapter (GPT and open-weight servers), against the real SDK with a mocked
transport (no network)."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx2
import openai
import pytest
from noitabench.harness import ConfigError, ModelConfig, ModelError, ToolResult, ToolSpec, UserText
from noitabench.harness.adapters.openai_adapter import PUBLIC_URL, OpenAIAdapter
from noitabench.harness.model import END_TURN, MAX_TOKENS, REFUSAL, TOOL_USE
from noitabench.harness.usage import Usage

TOOLS = (
    ToolSpec(
        "wait", "Stand still.", {"type": "object", "properties": {"ticks": {"type": "integer"}}}
    ),
    ToolSpec("kick", "Kick.", {"type": "object", "properties": {}}),
)
CALL = {
    "id": "call_1",
    "type": "function",
    "function": {"name": "wait", "arguments": '{"ticks":2}'},
}


def completion(
    message: dict[str, Any] | None = None,
    finish: str = "tool_calls",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": message or {"role": "assistant", "content": None, "tool_calls": [CALL]},
                "finish_reason": finish,
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "total_tokens": 1050,
            "prompt_tokens_details": {"cached_tokens": 800},
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
    }


class Wire:
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
        return httpx2.Response(200, json=answer, headers={"x-request-id": "req_oa"})

    def body(self, i: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def conversation(wire: Wire, base_url: str | None = None, **config: Any):
    cfg = ModelConfig("openai", "gpt-test", base_url=base_url, max_retries=0, **config)
    client = openai.OpenAI(
        api_key="test-key",
        base_url=base_url or PUBLIC_URL,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(wire)),
    )
    return OpenAIAdapter(cfg, client).new_conversation("You play a game.", TOOLS)


def test_request_shape_for_openai() -> None:
    wire = Wire(completion())
    conversation(wire, effort="high").send([UserText("Decision 1")])
    request, body = wire.requests[0], wire.body()
    assert request.url.host == "api.openai.com" and request.url.path == "/v1/chat/completions"
    assert body["model"] == "gpt-test" and body["max_completion_tokens"] == 8192
    assert body["messages"] == [
        {"role": "system", "content": "You play a game."},
        {"role": "user", "content": "Decision 1"},
    ]
    assert body["tools"][0] == {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Stand still.",
            "parameters": TOOLS[0].schema,
        },
    }
    assert body["tool_choice"] == "auto" and body["reasoning_effort"] == "high"
    for banned in ("temperature", "top_p", "max_tokens", "stream", "parallel_tool_calls"):
        assert banned not in body


def test_a_server_of_ones_own_gets_max_tokens_and_no_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = Wire(completion())
    conversation(wire, base_url="http://localhost:8000/v1").send([UserText("go")])
    body = wire.body()
    assert body["max_tokens"] == 8192 and "max_completion_tokens" not in body
    assert "reasoning_effort" not in body  # only when asked for
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-openai-key-0123456789")
    local = OpenAIAdapter(ModelConfig("openai", "qwen", base_url="http://localhost:8000/v1"))
    assert local.client.api_key == "EMPTY"  # the OpenAI key is not sent to another host
    monkeypatch.setenv("MY_SERVER_KEY", "local-secret")
    keyed = OpenAIAdapter(
        ModelConfig(
            "openai", "qwen", base_url="http://localhost:8000/v1", api_key_env="MY_SERVER_KEY"
        )
    )
    assert keyed.client.api_key == "local-secret"
    official = OpenAIAdapter(ModelConfig("openai", "gpt-test"))
    assert str(official.client.base_url).rstrip("/") == PUBLIC_URL and official.official
    # naming OpenAI's own endpoint is the same thing as leaving it out
    named = OpenAIAdapter(ModelConfig("openai", "gpt-test", base_url=PUBLIC_URL + "/"))
    assert named.official and named.client.api_key == "sk-the-openai-key-0123456789"
    with pytest.raises(ConfigError):
        OpenAIAdapter(ModelConfig("openai", "x", api_key_env="NOT_SET_ANYWHERE_123"))
    with pytest.raises(ConfigError):
        OpenAIAdapter(ModelConfig("openai", "x", effort="extreme"))


def test_the_answer_and_its_usage() -> None:
    wire = Wire(
        completion(
            {"role": "assistant", "content": "Waiting.", "tool_calls": [CALL]},
        )
    )
    turn = conversation(wire).send([UserText("go")])
    assert turn.stop == TOOL_USE and turn.text == "Waiting."
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [
        ("call_1", "wait", {"ticks": 2})
    ]
    # 1000 prompt tokens of which 800 were read from the cache
    assert turn.usage == Usage(200, 800, 0, 50, 20)
    assert turn.request_id == "req_oa"


def test_arguments_that_are_not_json_are_reported_not_raised() -> None:
    bad = {"id": "c", "type": "function", "function": {"name": "wait", "arguments": "{ticks:"}}
    arr = {"id": "d", "type": "function", "function": {"name": "kick", "arguments": "[1]"}}
    wire = Wire(completion({"role": "assistant", "content": None, "tool_calls": [bad, arr]}))
    turn = conversation(wire).send([UserText("go")])
    assert [c.error is not None for c in turn.tool_calls] == [True, True]
    assert "not valid JSON" in (turn.tool_calls[0].error or "")
    assert "JSON object" in (turn.tool_calls[1].error or "")


def test_history_is_append_only_with_tool_messages_in_call_order() -> None:
    two = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            CALL,
            {"id": "call_2", "type": "function", "function": {"name": "kick", "arguments": "{}"}},
        ],
    }
    wire = Wire(completion(two), completion({"role": "assistant", "content": "ok"}, "stop"))
    conv = conversation(wire)
    conv.send([UserText("Decision 1")])
    turn = conv.send(
        [
            ToolResult("call_1", "wait", "Decision 2 ..."),
            ToolResult("call_2", "kick", "failed", True),
            UserText("a nudge"),
        ]
    )
    assert turn.stop == END_TURN
    one, two_body = wire.body(0)["messages"], wire.body(1)["messages"]
    assert two_body[: len(one)] == one
    assert two_body[2] == {"role": "assistant", "content": None, "tool_calls": two["tool_calls"]}
    assert two_body[3:] == [
        {"role": "tool", "tool_call_id": "call_1", "content": "Decision 2 ..."},
        {"role": "tool", "tool_call_id": "call_2", "content": "failed"},
        {"role": "user", "content": "a nudge"},
    ]


def test_images_follow_in_a_user_message() -> None:
    wire = Wire(completion(), completion())
    conv = conversation(wire)
    conv.send([UserText("go")])
    conv.send([ToolResult("call_1", "wait", "view", images=(b"\x89PNGdata",))])
    messages = wire.body(1)["messages"]
    assert messages[-2]["role"] == "tool" and messages[-2]["content"] == "view"
    picture = messages[-1]["content"][1]["image_url"]["url"]
    assert picture == "data:image/png;base64," + base64.b64encode(b"\x89PNGdata").decode()


def test_cut_off_refused_and_empty_answers() -> None:
    cut = completion({"role": "assistant", "content": "I will", "tool_calls": [CALL]}, "length")
    refused = completion({"role": "assistant", "content": None, "refusal": "I cannot"}, "stop")
    empty = completion({"role": "assistant", "content": None}, "stop")
    wire = Wire(cut, refused, completion(), empty, completion())
    conv = conversation(wire)
    turn = conv.send([UserText("go")])
    assert turn.stop == MAX_TOKENS and turn.tool_calls == ()
    assert conv.messages[-1] == {"role": "assistant", "content": "(my answer was cut off)"}
    size = len(conv.messages)
    turn = conv.send([UserText("shorter")])
    assert turn.stop == REFUSAL and len(conv.messages) == size  # not appended
    conv.send([UserText("shorter")])
    conv.send([UserText("and now")])  # an empty answer, then the next call
    assert {"role": "assistant", "content": "(no reply)"} in conv.messages


@pytest.mark.parametrize(
    ("code", "kind", "retryable"),
    [
        (401, "auth", False),
        (403, "permission", False),
        (404, "not_found", False),
        (400, "bad_request", False),
        (429, "rate_limit", True),
        (500, "server", True),
        (503, "server", True),
    ],
)
def test_status_errors(code: int, kind: str, retryable: bool) -> None:
    response = httpx2.Response(
        code,
        json={"error": {"message": "nope", "type": "x", "code": None}},
        headers={"x-request-id": "r1"},
    )
    wire = Wire(response, completion())
    conv = conversation(wire)
    with pytest.raises(ModelError) as err:
        conv.send([UserText("go")])
    assert (err.value.kind, err.value.retryable, err.value.status) == (kind, retryable, code)
    assert conv.messages == []
    conv.send([UserText("go")])


@pytest.mark.parametrize(
    ("raised", "kind"),
    [(httpx2.ReadTimeout("slow"), "timeout"), (httpx2.ConnectError("down"), "connection")],
)
def test_network_errors(raised: Exception, kind: str) -> None:
    with pytest.raises(ModelError) as err:
        conversation(Wire(raised)).send([UserText("go")])
    assert err.value.kind == kind and err.value.retryable


def test_missing_credentials_are_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        OpenAIAdapter(ModelConfig("openai", "gpt-test"))
