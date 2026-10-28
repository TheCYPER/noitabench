"""A fork over the real Anthropic adapter (mocked transport): the request that goes out is a valid
continuation of the player's conversation, with the player's system prompt and tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from layer_context import make_rig
from noitabench.harness import ModelConfig, UserText
from noitabench.harness.adapters.anthropic_adapter import PUBLIC_URL, AnthropicAdapter
from noitabench.harness.subagents import register_l4

MODEL = "claude-haiku-5-5"
SIGNED = {"type": "thinking", "thinking": "a fork would help", "signature": "sig-abc"}


def reply(content: list[dict[str, Any]], stop: str) -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 30,
            "output_tokens": 12,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 2000,
        },
    }


class Wire:
    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        return httpx2.Response(200, json=self.answers.pop(0), headers={"request-id": "req_test"})

    def body(self, i: int) -> dict[str, Any]:
        return json.loads(self.requests[i].content)


def test_a_fork_continues_the_players_conversation_on_the_wire(tmp_path: Path, make_game) -> None:
    wire = Wire(
        reply(
            [
                SIGNED,
                {"type": "text", "text": "I will ask a fork."},
                {
                    "type": "tool_use",
                    "id": "toolu_f1",
                    "name": "fork_agent",
                    "input": {"task": "Plan"},
                },
                {"type": "tool_use", "id": "toolu_w1", "name": "workspace_list", "input": {}},
            ],
            "tool_use",
        ),
        reply([{"type": "text", "text": "The plan: go left."}], "end_turn"),
    )
    client = anthropic.Anthropic(
        api_key="test-key",
        base_url=PUBLIC_URL,
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(wire)),
    )
    adapter = AnthropicAdapter(ModelConfig("anthropic", MODEL, max_retries=0), client)
    rig = make_rig(tmp_path, make_game(), adapter=adapter, register=register_l4)
    main = adapter.new_conversation("PLAYER SYSTEM", rig.toolbox.specs())
    turn = main.send([UserText("Decision 1: the cave.")])
    assert [c.name for c in turn.tool_calls] == ["fork_agent", "workspace_list"]
    before = list(main.messages)

    def frozen() -> str:
        """The player's history by value (the SDK's blocks as JSON), to see in-place edits."""
        return json.dumps(
            main.messages, default=lambda o: o.model_dump(mode="json"), sort_keys=True
        )

    before_by_value = frozen()
    result = rig.toolbox.execute(turn.tool_calls).results[0]
    assert json.loads(result.content)["answer"] == "The plan: go left."

    parent_request, child_request = wire.body(0), wire.body(1)
    # the same prefix: system, tools, and the player's messages (with the signed thinking block)
    assert child_request["system"] == parent_request["system"]
    assert child_request["tools"] == parent_request["tools"]
    assert child_request["messages"][:1] == parent_request["messages"]
    assert child_request["model"] == parent_request["model"]
    assert child_request.get("cache_control") == parent_request.get("cache_control")
    messages = child_request["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"][0] == SIGNED, "the thinking block goes back unchanged"
    # every tool call of the turn is answered, the fork's by its briefing
    answers = messages[2]["content"]
    assert [(b["type"], b["tool_use_id"]) for b in answers] == [
        ("tool_result", "toolu_f1"),
        ("tool_result", "toolu_w1"),
    ]
    assert "Plan" in answers[0]["content"] and not answers[0].get("is_error")
    assert answers[1]["is_error"] is True and "not run" in answers[1]["content"]
    # the player's conversation is untouched, and the child has its own list
    assert main.messages == before and len(main.messages) == 2
    assert frozen() == before_by_value, "no entry of the player's history was edited"
    child = rig.ctx.extras["subagent_hub"].helpers["a1"].conversation
    assert child is not main and len(child.messages) == 4
    assert child.messages[:2] == main.messages
    assert child.messages is not main.messages
    # priced as the player's model, to the one budget
    assert rig.budget.model_calls == 1, "only the helper's call: the player's was made by hand"
