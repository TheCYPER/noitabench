"""The JSON Lines protocol: one request per line in, one answer per line out.

    -> {"id": 1, "commands": [{"name": "walk_to", "args": {"x": 180}}]}
    -> {"id": 2, "text": "aim(target=4); fire(until=target_dead)"}
    -> {"id": 3, "command": "inspect", "args": {"x": 10, "y": 20}}
    -> aim(target=4); fire(until=target_dead)          (a line that is not JSON is text)
    -> {"id": 4, "op": "observe"}                       (the current answer again; no decision)
    -> {"id": 5, "op": "close"}
    <- {"id": 1, "ok": true, "decision": 2, "frame": 60, "stop": {...}, "results": [...],
        "events": [...], "observation": {...}, "text": "..."}

The first line the server writes is `{"op": "hello", ...}` with the protocol constants, the tool
schemas and the first answer (decision 1, stop reason "start"). `ok` is false when a command
was invalid (the answer says which and why) or the request could not be read. Invalid commands
count as a decision; unreadable lines do not.
"""

from __future__ import annotations

import json
import reprlib
from collections.abc import Iterable
from typing import Any, TextIO

from .render import render_text
from .session import AgentSession
from .tools import tool_schemas
from .vocab import MAX_COMMAND_FRAMES, MAX_COMMANDS, PROTOCOL, TICK_FRAMES

DECISION_KEYS = ("commands", "text", "command", "name", "tool")


def _dump(obj: dict[str, Any]) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def hello(session: AgentSession) -> dict[str, Any]:
    first = session.observe()
    return {
        "op": "hello",
        "protocol": PROTOCOL,
        "tick_frames": TICK_FRAMES,
        "max_command_frames": MAX_COMMAND_FRAMES,
        "max_commands_per_decision": MAX_COMMANDS,
        "max_decisions": session.config.max_decisions,
        "tools": tool_schemas(),
        **with_text(first),
    }


def with_text(answer: dict[str, Any]) -> dict[str, Any]:
    """The answer with a `text` field (what a model reads) and `ok`."""
    ok = all(r["ok"] for r in answer["results"])
    return {"ok": ok, **answer, "text": render_text(answer)}


def _bad_request(rid: Any, message: str) -> dict[str, Any]:
    return {"id": rid, "ok": False, "error": {"code": "bad_request", "message": message}}


def handle_line(session: AgentSession, line: str) -> dict[str, Any] | None:
    """The answer to one request line (`None` for a blank line)."""
    line = line.strip()
    if not line:
        return None
    if not line.startswith("{"):
        return with_text(session.decide(line))
    try:
        request = json.loads(line)
    except json.JSONDecodeError as err:
        return _bad_request(None, f"the line is not valid JSON ({err.msg})")
    except RecursionError:
        return _bad_request(None, "the line is nested too deeply to read")
    if not isinstance(request, dict):
        return _bad_request(None, "a request must be a JSON object")
    rid = request.pop("id", None)
    op = request.pop("op", "decide")
    if op == "observe":
        answer = with_text(session.observe())
    elif op == "hello":
        answer = hello(session)
    elif op == "tools":
        answer = {"ok": True, "op": "tools", "tools": tool_schemas()}
    elif op == "close":
        answer = {"ok": True, "op": "closed", "summary": session.close()}
    elif op == "decide":
        if not any(k in request for k in DECISION_KEYS):
            return _bad_request(rid, f"a decision needs one of: {', '.join(DECISION_KEYS)}")
        answer = with_text(session.decide(request))
    else:
        return _bad_request(
            rid, f"unknown op {reprlib.repr(op)}; use decide, observe, hello, tools or close"
        )
    return {"id": rid, **answer}


def serve(session: AgentSession, lines: Iterable[str], out: TextIO) -> dict[str, Any]:
    """Read requests from `lines`, write answers to `out`, until `close` or the end of input.
    Returns the session summary."""
    try:
        out.write(_dump(hello(session)) + "\n")
        out.flush()
        for line in lines:
            answer = handle_line(session, line)
            if answer is None:
                continue
            out.write(_dump(answer) + "\n")
            out.flush()
            if answer.get("op") == "closed":
                return dict(answer["summary"])
    except BaseException:
        session.close()  # finish the recording and the decision log, then let the error go on
        raise
    return session.close()
