"""The Gemini adapter, against the real SDK with a mocked transport (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from google import genai
from google.genai import types
from noitabench.harness import ConfigError, ModelConfig, ModelError, ToolResult, ToolSpec, UserText
from noitabench.harness.adapters.gemini_adapter import PUBLIC_URL, GeminiAdapter, gemini_schema
from noitabench.harness.model import END_TURN, MAX_TOKENS, REFUSAL, TOOL_USE
from noitabench.harness.usage import Usage

TOOLS = (
    ToolSpec(
        "wait",
        "Stand still.",
        {
            "type": "object",
            "properties": {"ticks": {"type": "integer", "exclusiveMinimum": 0}},
            "additionalProperties": False,
        },
    ),
    ToolSpec("kick", "Kick.", {"type": "object", "properties": {}}),
)
CALL = {"functionCall": {"name": "wait", "args": {"ticks": 2}}}


def reply(
    parts: list[dict[str, Any]] | None = None,
    finish: str = "STOP",
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts or [CALL]},
                "finishReason": finish,
                "index": 0,
            }
        ],
        "usageMetadata": usage
        or {
            "promptTokenCount": 1000,
            "candidatesTokenCount": 50,
            "thoughtsTokenCount": 20,
            "cachedContentTokenCount": 800,
            "totalTokenCount": 1070,
        },
        "modelVersion": "gemini-test",
        "responseId": "resp-1",
    }


class Wire:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def body(self, i: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def conversation(wire: Wire, **config: Any):
    cfg = ModelConfig("gemini", "gemini-test", max_retries=0, **config)
    client = genai.Client(
        api_key="test-key",
        http_options=types.HttpOptions(
            base_url=PUBLIC_URL,
            httpx_client=httpx.Client(transport=httpx.MockTransport(wire)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    return GeminiAdapter(cfg, client).new_conversation("You play a game.", TOOLS)


def test_request_shape() -> None:
    wire = Wire(reply())
    conversation(wire, effort="low").send([UserText("Decision 1")])
    request, body = wire.requests[0], wire.body()
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.url.path.endswith("/models/gemini-test:generateContent")
    assert body["systemInstruction"]["parts"][0]["text"] == "You play a game."
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Decision 1"}]}]
    declarations = body["tools"][0]["functionDeclarations"]
    assert [d["name"] for d in declarations] == ["wait", "kick"]
    assert declarations[0]["parameters_json_schema"] == {
        "type": "object",
        "properties": {"ticks": {"type": "integer"}},
    }  # the keywords Gemini does not take are left out
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    gen = body["generationConfig"]
    assert gen["maxOutputTokens"] == 8192
    assert gen["thinkingConfig"] == {"include_thoughts": True, "thinking_level": "LOW"}
    for banned in ("temperature", "topP", "topK"):
        assert banned not in gen


def test_the_schema_filter() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "amount": {"anyOf": [{"type": "integer", "minimum": 1}, {"const": "all"}]},
            "n": {"type": "number", "exclusiveMinimum": 0},
        },
    }
    assert gemini_schema(schema) == {
        "type": "object",
        "properties": {
            "amount": {"anyOf": [{"type": "integer", "minimum": 1}, {"enum": ["all"]}]},
            "n": {"type": "number"},
        },
    }


def test_thinking_can_be_left_out() -> None:
    wire = Wire(reply())
    conversation(wire, thinking="default").send([UserText("go")])
    assert "thinkingConfig" not in wire.body().get("generationConfig", {})


def test_the_answer_and_its_usage() -> None:
    wire = Wire(
        reply(
            [
                {"text": "thinking about it", "thought": True},
                {"text": "Waiting."},
                CALL,
                {"functionCall": {"id": "fc-9", "name": "kick", "args": {}}},
            ]
        )
    )
    turn = conversation(wire).send([UserText("go")])
    assert (
        turn.stop == TOOL_USE and turn.text == "Waiting." and turn.thinking == "thinking about it"
    )
    assert [(c.name, c.arguments) for c in turn.tool_calls] == [
        ("wait", {"ticks": 2}),
        ("kick", {}),
    ]
    assert turn.tool_calls[0].id.startswith("gemini-call-") and turn.tool_calls[1].id == "fc-9"
    assert turn.usage == Usage(200, 800, 0, 70, 20)
    assert turn.request_id == "resp-1"


def test_history_is_append_only_and_results_go_back_in_order() -> None:
    wire = Wire(
        reply([CALL, {"functionCall": {"id": "fc-9", "name": "kick", "args": {}}}]),
        reply([{"text": "done"}]),
    )
    conv = conversation(wire)
    first = conv.send([UserText("Decision 1")])
    conv.send(
        [
            ToolResult(first.tool_calls[0].id, "wait", "Decision 2"),
            ToolResult("fc-9", "kick", "bad", True),
            UserText("nudge"),
        ]
    )
    one, two = wire.body(0)["contents"], wire.body(1)["contents"]
    assert two[: len(one)] == one
    assert two[1]["role"] == "model" and len(two[1]["parts"]) == 2
    results = two[2]["parts"]
    assert results[0]["functionResponse"] == {"name": "wait", "response": {"output": "Decision 2"}}
    assert results[1]["functionResponse"] == {
        "id": "fc-9",
        "name": "kick",
        "response": {"error": "bad"},
    }
    assert results[2] == {"text": "nudge"}


def test_images_are_inline_parts() -> None:
    wire = Wire(reply(), reply())
    conv = conversation(wire)
    first = conv.send([UserText("go")])
    conv.send([ToolResult(first.tool_calls[0].id, "wait", "view", images=(b"\x89PNGdata",))])
    parts = wire.body(1)["contents"][-1]["parts"]
    inline = parts[1]["inlineData"]
    assert inline.get("mimeType", inline.get("mime_type")) == "image/png"


def test_cut_off_blocked_and_empty_answers() -> None:
    blocked = {
        "promptFeedback": {"blockReason": "SAFETY"},
        "usageMetadata": {"promptTokenCount": 5},
    }
    wire = Wire(reply([{"text": "I will"}], "MAX_TOKENS"), reply([], "SAFETY"), blocked, reply())
    conv = conversation(wire)
    turn = conv.send([UserText("go")])
    assert turn.stop == MAX_TOKENS and turn.tool_calls == ()
    assert conv.contents[-1].parts[0].text == "(my answer was cut off)"
    size = len(conv.contents)
    assert conv.send([UserText("shorter")]).stop == REFUSAL and len(conv.contents) == size
    assert conv.send([UserText("shorter")]).stop == REFUSAL and len(conv.contents) == size
    assert conv.send([UserText("shorter")]).stop == TOOL_USE


def test_a_reply_without_parts_gets_a_stand_in() -> None:
    wire = Wire({"candidates": [{"finishReason": "STOP"}]}, reply())
    conv = conversation(wire)
    turn = conv.send([UserText("go")])
    assert turn.stop == END_TURN and conv.contents[-1].parts[0].text == "(no reply)"


@pytest.mark.parametrize(
    ("code", "kind", "retryable"),
    [
        (401, "auth", False),
        (403, "permission", False),
        (404, "not_found", False),
        (400, "bad_request", False),
        (429, "rate_limit", True),
        (500, "server", True),
        (503, "overloaded", True),
    ],
)
def test_status_errors(code: int, kind: str, retryable: bool) -> None:
    response = httpx.Response(
        code, json={"error": {"code": code, "message": "nope", "status": "X"}}
    )
    wire = Wire(response, reply())
    conv = conversation(wire)
    with pytest.raises(ModelError) as err:
        conv.send([UserText("go")])
    assert (err.value.kind, err.value.retryable, err.value.status) == (kind, retryable, code)
    assert conv.contents == []
    conv.send([UserText("go")])


def test_a_bad_key_reported_as_a_400_is_still_an_auth_error() -> None:
    response = httpx.Response(
        400,
        json={
            "error": {
                "code": 400,
                "message": "API key not valid. Please pass a valid API key.",
                "status": "INVALID_ARGUMENT",
            }
        },
    )
    with pytest.raises(ModelError) as err:
        conversation(Wire(response)).send([UserText("go")])
    assert err.value.kind == "auth"


def test_network_errors() -> None:
    for raised, kind in (
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("down"), "connection"),
    ):
        with pytest.raises(ModelError) as err:
            conversation(Wire(raised)).send([UserText("go")])
        assert err.value.kind == kind and err.value.retryable


def test_configuration() -> None:
    with pytest.raises(ConfigError):
        GeminiAdapter(ModelConfig("gemini", "x", effort="extreme"))
    with pytest.raises(ConfigError, match="NOT_SET_ANYWHERE_123"):
        GeminiAdapter(ModelConfig("gemini", "x", api_key_env="NOT_SET_ANYWHERE_123"))


def test_missing_credentials_are_a_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigError, match="GOOGLE_API_KEY"):
        GeminiAdapter(ModelConfig("gemini", "gemini-test"))


def test_a_custom_base_url_needs_its_own_named_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key-of-the-user-0001")
    with pytest.raises(ConfigError, match="--api-key-env"):
        GeminiAdapter(ModelConfig("gemini", "gemini-test", base_url="http://gateway.test:8080"))
    monkeypatch.setenv("MY_GATEWAY_KEY", "key-for-the-gateway-0004")
    own = GeminiAdapter(
        ModelConfig(
            "gemini",
            "gemini-test",
            base_url="http://gateway.test:8080",
            api_key_env="MY_GATEWAY_KEY",
        )
    )
    assert own.client._api_client.api_key == "key-for-the-gateway-0004"


def test_the_environment_cannot_switch_the_client_to_vertex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key-of-the-user-0001")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "some-project")
    adapter = GeminiAdapter(ModelConfig("gemini", "gemini-test"))
    assert adapter.client.vertexai is False
    assert str(adapter.client._api_client._http_options.base_url).startswith(
        "https://generativelanguage.googleapis.com"
    )
