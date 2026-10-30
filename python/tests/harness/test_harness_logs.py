"""The run logs keep the ids of tool calls: they are checked against known secrets only, so that a
call can be told from its result even when a provider makes ids that look like keys."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from noitabench.harness.adapters.scripted import Say, ScriptedAdapter, call
from noitabench.harness.logs import RunLogs
from noitabench.harness.redact import HIDDEN, Redactor
from noitabench.harness.runner import run_family
from test_harness_redact import fake_value

# Ids as three providers make them. The first is the shape that was hidden 238 times in
# runs/ds-flash-pilot/run-01; the others are long enough to look like keys as well.
DEEPSEEK_ID = "call_00_k3LmQ9xZ2vB7nR4tYw8PdS5hJ1cF6gAe0uHoXi"
OPENAI_ID = "call_Qw8Er7Ty6Ui5Op4As3Df2Gh1Jk9Lz0XcVbNm7Rt5Yu3"
ANTHROPIC_ID = "toolu_01Vw8Xc9Zb7Nm6Lk5Jh4Gf3Ds2Aq1Pw0Oe9Ri8Ut7"
PROVIDER_IDS = (DEEPSEEK_ID, OPENAI_ID, ANTHROPIC_ID)


def written(logs_dir: Path) -> list[dict[str, Any]]:
    path = logs_dir / "transcript.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.mark.parametrize("call_id", PROVIDER_IDS)
def test_the_ids_are_the_kind_of_text_the_redactor_hides_elsewhere(call_id: str) -> None:
    assert Redactor().redact(f"id {call_id} end") == f"id {HIDDEN} end"  # the premise
    assert Redactor().redact_id(call_id) == call_id


def test_provider_ids_survive_in_the_transcript(tmp_path: Path) -> None:
    logs = RunLogs(tmp_path, redactor=Redactor())
    logs.transcript(
        "assistant",
        call=1,
        text="Waiting.",
        tool_calls=[{"id": i, "name": "wait", "arguments": {"ticks": 1}} for i in PROVIDER_IDS],
    )
    logs.transcript(
        "results",
        call=1,
        results=[
            {"id": i, "name": "wait", "is_error": False, "content": "ok"} for i in PROVIDER_IDS
        ],
    )
    logs.close()
    assistant, results = written(tmp_path)
    assert [c["id"] for c in assistant["tool_calls"]] == list(PROVIDER_IDS)
    assert [r["id"] for r in results["results"]] == list(PROVIDER_IDS)
    assert list(results["results"][0]) == ["id", "name", "is_error", "content"]  # order kept
    assert HIDDEN not in (tmp_path / "transcript.jsonl").read_text()


def test_helpers_lines_keep_their_ids_too(tmp_path: Path) -> None:
    logs = RunLogs(tmp_path, redactor=Redactor())
    logs.transcript("results", agent="h1", call=2, results=[{"id": DEEPSEEK_ID, "content": "x"}])
    logs.close()
    assert written(tmp_path)[0]["results"][0]["id"] == DEEPSEEK_ID


def test_an_id_that_is_a_known_secret_is_still_hidden(tmp_path: Path) -> None:
    value = fake_value("ident")
    redactor = Redactor()
    redactor.add([value])
    logs = RunLogs(tmp_path, redactor=redactor)
    ids = [value, value[::-1], f"call_00_{value}", value.upper(), "plain_id_7"]
    logs.transcript(
        "assistant", tool_calls=[{"id": i, "name": "wait", "arguments": {}} for i in ids]
    )
    logs.transcript("results", results=[{"id": i, "name": "wait", "content": ""} for i in ids])
    logs.close()
    text = (tmp_path / "transcript.jsonl").read_text()
    for form in (value, value[::-1], value.upper()):
        assert form not in text
    assistant, results = written(tmp_path)
    for record, key in ((assistant, "tool_calls"), (results, "results")):
        assert [c["id"] for c in record[key]] == [HIDDEN] * 4 + ["plain_id_7"]


def test_key_shaped_text_in_other_fields_is_still_hidden(tmp_path: Path) -> None:
    key = "sk-ant-api03-" + "AbCdEfGhIjKlMnOpQrSt" * 2
    blob = "Kd83nQ0xvT2mWc7LbRj5ZpHy9eUa4SfG1oNiX6"  # long and random-looking
    assert Redactor().redact(blob) == HIDDEN
    logs = RunLogs(tmp_path, redactor=Redactor())
    logs.transcript(
        "assistant",
        text=f"my key is {key}",
        thinking=f"also {blob}",
        tool_calls=[
            {"id": DEEPSEEK_ID, "name": "workspace_write", "arguments": {"text": key, "id": key}}
        ],
    )
    logs.transcript(
        "results",
        results=[
            {"id": DEEPSEEK_ID, "name": f"tool-{key}", "is_error": True, "content": f"saw {key}"}
        ],
    )
    logs.transcript("note", text=key, results_list=[key])
    logs.call({"call": 1, "request_id": key, "error": {"message": f"bad {key}"}})
    logs.close()
    raw = (tmp_path / "transcript.jsonl").read_text() + (tmp_path / "harness.jsonl").read_text()
    assert key not in raw and "AbCdEfGhIjKl" not in raw and blob not in raw
    assistant, results, _note = written(tmp_path)
    call_ = assistant["tool_calls"][0]
    assert call_["id"] == DEEPSEEK_ID  # only this one is exempt
    assert call_["arguments"] == {"text": HIDDEN, "id": HIDDEN}  # an `id` argument is not an id
    assert results["results"][0]["id"] == DEEPSEEK_ID
    assert results["results"][0]["content"] == f"saw {HIDDEN}"
    assert assistant["text"] == f"my key is {HIDDEN}"


def test_a_secret_spelled_out_under_a_call_list_name_is_still_hidden(tmp_path: Path) -> None:
    value = fake_value("spelled")
    redactor = Redactor()
    redactor.add([value])
    logs = RunLogs(tmp_path, redactor=redactor)
    # not a list of calls, so the usual redaction sees the whole list (one character per item)
    logs.transcript("note", results=list(value), tool_calls=list(value.encode()))
    logs.transcript("note", results=[{"id": "c1", "content": "ok"}, value])
    logs.close()
    assert value not in (tmp_path / "transcript.jsonl").read_text()
    spelled, mixed = written(tmp_path)
    assert spelled["results"] == HIDDEN and spelled["tool_calls"] == HIDDEN
    assert mixed["results"][1] == HIDDEN


def test_every_record_is_redacted_as_before_except_the_ids(tmp_path: Path) -> None:
    value = fake_value("whole")
    redactor = Redactor()
    redactor.add([value])
    key = "sk-ant-api03-" + "AbCdEfGhIjKlMnOpQrSt" * 2
    record = {
        "kind": "assistant",
        "call": 3,
        "text": f"{key} {value}",
        "thinking": key,
        "tool_calls": [
            {"id": "call_1", "name": "n", "arguments": {"a": [key, {"b": (key, value)}], "id": key}}
        ],
        "results": [{"id": "call_1", "name": f"n-{key}", "is_error": True, "content": [key]}],
        "nested": {"deep": [{"x": {"y": [key, value]}}]},
        key: 1,
    }
    logs = RunLogs(tmp_path, redactor=redactor)
    logs.transcript(**record)
    logs.close()
    (written_record,) = written(tmp_path)
    expected = redactor.redact_value({"seq": 1, **record})
    assert written_record == json.loads(json.dumps(expected))
    assert list(written_record) == list(expected)  # the key order too


def test_a_switched_off_redactor_changes_nothing(tmp_path: Path) -> None:
    logs = RunLogs(tmp_path, redactor=Redactor(enabled=False))
    logs.transcript("results", results=[{"id": DEEPSEEK_ID, "content": "x"}])
    logs.close()
    assert written(tmp_path)[0]["results"][0]["id"] == DEEPSEEK_ID


def test_a_whole_game_keeps_every_call_linked_to_its_result(run_config, make_game) -> None:
    ids = [DEEPSEEK_ID, OPENAI_ID, ANTHROPIC_ID]
    script = [Say.tools(call("wait", call_id=i, ticks=1)) for i in ids] + [
        Say.tools(call("wait", ticks=1)) for _ in range(3)
    ]
    cfg = run_config(max_decisions=3)
    run_family(cfg, adapter=ScriptedAdapter(script), game_factory=make_game, sleep=lambda _s: None)
    rows = written(cfg.out)
    sent = [c["id"] for r in rows if r["kind"] == "assistant" for c in r["tool_calls"]]
    answered = [x["id"] for r in rows if r["kind"] == "results" for x in r["results"]]
    assert sent == answered == ids
    assert HIDDEN not in (cfg.out / "transcript.jsonl").read_text()
