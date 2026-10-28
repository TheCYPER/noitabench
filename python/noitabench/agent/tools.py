"""Commands as tools: JSON schemas, and the one function that runs a tool call.

The JSON Lines protocol (`protocol.py`) and an MCP server (`mcp_adapter.py`) both end in
`call_tool`, so they drive the game the same way: one tool call is one decision with one
command. `coerce_request` is the single place that turns a request - text, a dict, a list - into
checked commands.
"""

from __future__ import annotations

import reprlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from .errors import CommandError
from .grammar import leading_name, parse_decision
from .spec import (
    AMOUNT,
    BOOL,
    COMMANDS,
    ENUM,
    INT,
    NUMBER,
    STR,
    TARGET,
    UNTIL_SPEC,
    Command,
    CommandSpec,
    Param,
)
from .validate import MAX_NAME, validate_command
from .vocab import EVENT_TYPES, MAX_TICKS

if TYPE_CHECKING:
    from .session import AgentSession

NAME_KEYS = ("name", "command", "tool")
MAX_NAME_DEPTH = 8  # how deep into a request that could not be read its first name is looked for


def _item_to_command(item: Any) -> Command:
    if isinstance(item, Command):
        return validate_command(item.name, item.args)
    if isinstance(item, str):
        commands = parse_decision(item)
        if len(commands) != 1:
            raise CommandError("syntax", "a list item must be a single command")
        return commands[0]
    if not isinstance(item, Mapping):
        raise CommandError("syntax", f"cannot read a command from {reprlib.repr(item)}")
    name = next((item[k] for k in NAME_KEYS if k in item), None)
    if name is None:
        raise CommandError("syntax", "a command needs a `name`")
    args = next((item[k] for k in ("args", "arguments") if k in item), None)
    if args is None:  # arguments written beside the name
        args = {k: v for k, v in item.items() if k not in NAME_KEYS}
    return validate_command(name, args)


def coerce_request(request: Any) -> list[Command]:
    """Commands from text (`walk_to(x=180)`), one command dict, a list of them, or
    `{"commands": [...]}` / `{"text": "..."}`. Raises `CommandError`."""
    try:
        return _coerce_request(request)
    except RecursionError as err:  # thousands of nested lists or objects
        raise CommandError("syntax", "the request is nested too deeply to read") from err


def _coerce_request(request: Any) -> list[Command]:
    if isinstance(request, str):
        return parse_decision(request)
    if isinstance(request, Command):
        return [validate_command(request.name, request.args)]
    if isinstance(request, Mapping):
        if "commands" in request:
            return _coerce_request(request["commands"])
        if "text" in request:
            return parse_decision(request["text"])
        return [_listed(request)]
    if isinstance(request, Sequence):
        if not request:
            raise CommandError("syntax", "the decision is empty; give at least one command")
        return [_listed(i) for i in request]
    raise CommandError("syntax", f"cannot read a decision from {reprlib.repr(request)}")


def _listed(item: Any) -> Command:
    """One command of a list; an error names the command, whatever the way it was written."""
    try:
        return _item_to_command(item)
    except CommandError as err:
        if err.command is None:
            err.command = request_name(item)
        raise


# -- schemas -----------------------------------------------------------------------------------------


def _param_schema(p: Param) -> dict[str, Any]:
    if p.kind == INT:
        s: dict[str, Any] = {"type": "integer"}
    elif p.kind == NUMBER:
        s = {"type": "number"}
    elif p.kind == BOOL:
        s = {"type": "boolean"}
    elif p.kind == STR:
        s = {"type": "string"}
    elif p.kind == ENUM:
        s = {"type": "string", "enum": list(p.choices)}
    elif p.kind == AMOUNT:
        s = {"anyOf": [{"type": "integer", "minimum": 1}, {"const": "all"}]}
    elif p.kind == TARGET:
        s = {"type": ["integer", "string"]}
    elif p.kind == UNTIL_SPEC:
        s = {"type": "object", "properties": until_properties(), "additionalProperties": False}
    else:  # pragma: no cover
        raise AssertionError(p.kind)
    if p.minimum is not None:
        s["minimum"] = p.minimum
    s["description"] = p.doc
    return s


def until_properties() -> dict[str, Any]:
    return {
        "ticks": {"type": "integer", "minimum": 1, "maximum": MAX_TICKS},
        "distance": {"type": "number", "exclusiveMinimum": 0},
        "x": {"type": "integer"},
        "blocked": {"type": "boolean"},
        "landed": {"type": "boolean"},
        "hp_below": {"type": "number"},
        "target_dead": {"type": "boolean"},
        "mana_empty": {"type": "boolean"},
        "edge": {"type": "boolean"},
        "event": {
            "anyOf": [
                {"type": "string", "enum": list(EVENT_TYPES)},
                {"type": "array", "items": {"type": "string", "enum": list(EVENT_TYPES)}},
            ]
        },
    }


def tool_schema(spec: CommandSpec) -> dict[str, Any]:
    """A command as an MCP tool: `{name, description, inputSchema}`."""
    props = {p.name: _param_schema(p) for p in spec.params}
    if spec.until_direct:
        for key, schema in until_properties().items():
            props.setdefault(key, schema)
    required = [p.name for p in spec.params if p.required]
    return {
        "name": spec.name,
        "description": spec.summary,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": False,
        },
    }


def tool_schemas() -> list[dict[str, Any]]:
    """Every command as a tool."""
    return [tool_schema(s) for s in COMMANDS.values()]


def call_tool(
    session: AgentSession, name: str, arguments: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Run one tool call as one decision with one command; returns the answer dict."""
    try:
        command = validate_command(name, arguments)
    except CommandError as err:
        return session.decide_invalid(err, {"name": name, "args": dict(arguments or {})})
    except RecursionError:
        err = CommandError("bad_argument", f"{name}: the arguments are nested too deeply to read")
        return session.decide_invalid(err, {"name": name})
    return session.decide([command])


def request_name(request: Any) -> str:
    """The name of the first command of a request, for an answer about a request that could not
    be read (`?` when there is none to find)."""
    for _ in range(MAX_NAME_DEPTH):
        if isinstance(request, Mapping):
            named = next((request[k] for k in NAME_KEYS if isinstance(request.get(k), str)), None)
            if named is not None:
                return str(named)[:MAX_NAME]
            request = request.get("commands", request.get("text", "?"))
        elif isinstance(request, Sequence) and not isinstance(request, str):
            if not request:
                break
            request = request[0]
        else:
            break
    return (leading_name(request) if isinstance(request, str) else None) or "?"
