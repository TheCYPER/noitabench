"""A fork over the OpenAI-compatible and Gemini adapters (real SDKs, mocked transports): the
continuation is valid for each wire format."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

openai = pytest.importorskip("openai")
httpx2 = pytest.importorskip("httpx2")
httpx = pytest.importorskip("httpx")
genai = pytest.importorskip("google.genai")

from google.genai import types
from layer_context import make_rig
from noitabench.harness import ModelConfig, ToolResult, ToolSpec, UserText
from noitabench.harness.adapters.gemini_adapter import PUBLIC_URL as GEMINI_URL
from noitabench.harness.adapters.gemini_adapter import GeminiAdapter
from noitabench.harness.adapters.openai_adapter import PUBLIC_URL as OPENAI_URL
from noitabench.harness.adapters.openai_adapter import OpenAIAdapter
from noitabench.harness.subagent_fork import fork_conversation
from noitabench.harness.subagents import register_l4

TOOLS = (
    ToolSpec("wait", "Stand still.", {"type": "object", "properties": {}}),
    ToolSpec("fork_agent", "Fork.", {"type": "object", "properties": {"task": {"type": "string"}}}),
)


class Wire:
    def __init__(self, module: Any, *answers: dict[str, Any]) -> None:
        self.module, self.answers, self.requests = module, list(answers), []

    def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        return self.module.Response(200, json=self.answers.pop(0))

    def body(self, i: int) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def test_a_fork_over_chat_completions() -> None:
    call = {
        "id": "call_f1",
        "type": "function",
        "function": {"name": "fork_agent", "arguments": '{"task":"Plan"}'},
    }

    def completion(message: dict[str, Any], finish: str) -> dict[str, Any]:
        return {
            "id": "c1",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-test",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
        }

    wire = Wire(
        httpx2,
        completion({"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"),
        completion({"role": "assistant", "content": "The plan."}, "stop"),
    )
    client = openai.OpenAI(
        api_key="test-key",
        base_url=OPENAI_URL,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(wire)),
    )
    adapter = OpenAIAdapter(ModelConfig("openai", "gpt-test", max_retries=0), client)
    main = adapter.new_conversation("PLAYER SYSTEM", TOOLS)
    turn = main.send([UserText("Decision 1")])
    child = fork_conversation(adapter, main, "PLAYER SYSTEM", TOOLS)
    child.send([ToolResult(turn.tool_calls[0].id, "fork_agent", "You are the helper. Plan")])
    roles = [m["role"] for m in wire.body(1)["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert wire.body(1)["messages"][3]["tool_call_id"] == "call_f1"
    assert wire.body(1)["messages"][:2] == wire.body(0)["messages"], (
        "the player's part goes out as it was"
    )
    assert len(main.messages) == 2 and len(child.messages) == 4


def test_a_fork_over_gemini() -> None:
    def reply(parts: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "candidates": [
                {"content": {"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}
            ],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 5},
            "modelVersion": "gemini-test",
        }

    wire = Wire(
        httpx,
        reply([{"functionCall": {"name": "fork_agent", "args": {"task": "Plan"}}}]),
        reply([{"text": "The plan."}]),
    )
    client = genai.Client(
        api_key="test-key",
        http_options=types.HttpOptions(
            base_url=GEMINI_URL,
            httpx_client=httpx.Client(transport=httpx.MockTransport(wire)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    adapter = GeminiAdapter(ModelConfig("gemini", "gemini-test", max_retries=0), client)
    main = adapter.new_conversation("PLAYER SYSTEM", TOOLS)
    turn = main.send([UserText("Decision 1")])
    child = fork_conversation(adapter, main, "PLAYER SYSTEM", TOOLS)
    child.send([ToolResult(turn.tool_calls[0].id, "fork_agent", "You are the helper. Plan")])
    roles = [c["role"] for c in wire.body(1)["contents"]]
    assert roles == ["user", "model", "user"], "valid alternation, no two user turns in a row"
    answer = wire.body(1)["contents"][2]["parts"][0]["functionResponse"]
    assert answer["name"] == "fork_agent"
    assert wire.body(1)["contents"][:1] == wire.body(0)["contents"], (
        "the player's part goes out as it was"
    )
    assert len(main.contents) == 2 and len(child.contents) == 4


# -- a turn with several open calls, through the hub ----------------------------------------------


def test_a_fork_answers_all_three_calls_of_the_turn_over_chat_completions(
    tmp_path: Path, make_game
) -> None:
    def call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }

    def completion(message: dict[str, Any], finish: str) -> dict[str, Any]:
        return {
            "id": "c1",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-test",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
        }

    turn_calls = [
        call("call_a", "workspace_list", "{}"),
        call("call_f", "fork_agent", '{"task":"Plan"}'),
        call("call_w", "wait", '{"until":{"ticks":1}}'),
    ]
    wire = Wire(
        httpx2,
        completion({"role": "assistant", "content": None, "tool_calls": turn_calls}, "tool_calls"),
        completion({"role": "assistant", "content": "The plan."}, "stop"),
    )
    client = openai.OpenAI(
        api_key="test-key",
        base_url=OPENAI_URL,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(wire)),
    )
    adapter = OpenAIAdapter(ModelConfig("openai", "gpt-test", max_retries=0), client)
    rig = make_rig(tmp_path, make_game(), adapter=adapter, register=register_l4)
    main = adapter.new_conversation("PLAYER SYSTEM", rig.toolbox.specs())
    turn = main.send([UserText("Decision 1")])
    before = copy.deepcopy(main.messages)
    out = rig.toolbox.execute(turn.tool_calls)
    assert json.loads(out.results[1].content)["answer"] == "The plan."
    assert rig.session.decisions == 1, "the player's own wait ran; the fork cost no step"

    messages = wire.body(1)["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "tool", "tool"]
    assert messages[:3] == wire.body(0)["messages"] + [messages[2]], "the player's part, as it was"
    assert [m["tool_call_id"] for m in messages[3:]] == ["call_a", "call_f", "call_w"]
    assert "Plan" in messages[4]["content"] and "not run" in messages[3]["content"]
    assert "not run" in messages[5]["content"]
    assert [c["id"] for c in messages[2]["tool_calls"]] == ["call_a", "call_f", "call_w"]
    assert main.messages == before, "the player's conversation is untouched"
    assert [m["role"] for m in main.messages] == ["user", "assistant"]
    # the player answers the same calls itself afterwards, in its own conversation
    assert [r.call_id for r in out.results] == ["call_a", "call_f", "call_w"]


def test_a_fork_answers_all_three_calls_of_the_turn_over_gemini(tmp_path: Path, make_game) -> None:
    thought = {"text": "I should ask for a plan", "thought": True, "thoughtSignature": "c2lnbg=="}
    parts = [
        thought,
        {"functionCall": {"name": "workspace_list", "args": {}}},
        {"functionCall": {"name": "fork_agent", "args": {"task": "Plan"}}},
        {"functionCall": {"name": "wait", "args": {"until": {"ticks": 1}}}},
    ]

    def reply(content: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "candidates": [
                {"content": {"role": "model", "parts": content}, "finishReason": "STOP", "index": 0}
            ],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 5},
            "modelVersion": "gemini-test",
        }

    wire = Wire(httpx, reply(parts), reply([{"text": "The plan."}]))
    client = genai.Client(
        api_key="test-key",
        http_options=types.HttpOptions(
            base_url=GEMINI_URL,
            httpx_client=httpx.Client(transport=httpx.MockTransport(wire)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    adapter = GeminiAdapter(ModelConfig("gemini", "gemini-test", max_retries=0), client)
    rig = make_rig(tmp_path, make_game(), adapter=adapter, register=register_l4)
    main = adapter.new_conversation("PLAYER SYSTEM", rig.toolbox.specs())
    turn = main.send([UserText("Decision 1")])
    assert [c.name for c in turn.tool_calls] == ["workspace_list", "fork_agent", "wait"]
    before = list(main.contents)
    before_wire = [c.model_dump(mode="json") for c in main.contents]
    out = rig.toolbox.execute(turn.tool_calls)
    assert json.loads(out.results[1].content)["answer"] == "The plan."

    contents = wire.body(1)["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[0] == wire.body(0)["contents"][0]
    model_part_kinds = [
        next(iter(set(p) - {"thoughtSignature", "thought"})) for p in contents[1]["parts"]
    ]
    assert model_part_kinds == ["text", "functionCall", "functionCall", "functionCall"]
    assert contents[1]["parts"][0]["thoughtSignature"] == "c2lnbg==", "the signature goes back"
    answers = [p["functionResponse"] for p in contents[2]["parts"]]
    assert [a["name"] for a in answers] == ["workspace_list", "fork_agent", "wait"]
    assert "Plan" in json.dumps(answers[1]) and "not run" not in json.dumps(answers[1])
    # the player's other calls are its own to run: in the fork's copy they were not
    assert "not run" in json.dumps(answers[0]) and "not run" in json.dumps(answers[2])
    assert main.contents == before and len(main.contents) == 2
    assert [c.model_dump(mode="json") for c in main.contents] == before_wire
