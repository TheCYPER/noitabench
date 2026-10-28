"""The one-line text form of a decision: `aim(target=12); fire(until=target_dead)`.

A decision is commands separated by `;` (or by line ends). A command is `name(arguments)`;
arguments are keyword (`x=180`) or positional (the first positional names are listed in the
command table: `walk_to(180)`, `move(right)`). Values are numbers, `true`/`false`, bare words
(`right`, `target_dead`), quoted text, lists and `{...}` objects. Nothing is evaluated: the text
is only parsed with `ast`.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from .errors import CommandError
from .spec import COMMANDS, Command
from .validate import validate_command

MAX_TEXT = 20_000
_WORDS = {"true": True, "false": False, "none": None, "null": None}


def split_statements(text: str) -> list[str]:
    """Split on `;` and line ends that are outside quotes and brackets."""
    parts: list[str] = []
    depth, quote, start = 0, "", 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch in ";\n" and depth <= 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return _WORDS.get(node.id.lower(), node.id)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        inner = _value(node.operand)
        if isinstance(inner, (int, float)) and not isinstance(inner, bool):
            return -inner if isinstance(node.op, ast.USub) else inner
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_value(e) for e in node.elts]
    if isinstance(node, ast.Dict):
        keys = [_value(k) if k is not None else None for k in node.keys]
        if all(isinstance(k, str) for k in keys):
            return {k: _value(v) for k, v in zip(keys, node.values, strict=True)}
    raise CommandError("syntax", "a value must be a number, a word, text, a list or an object")


def _shown(text: str) -> str:
    return text if len(text) <= 60 else text[:57] + "..."


def _statement(text: str) -> tuple[str, dict[str, Any]]:
    """The name and raw arguments of one statement. Whatever `ast` raises for text it cannot
    take (a null byte, thousands of nested brackets or signs) is an unreadable decision."""
    try:
        return _read_statement(text)
    except CommandError:
        raise
    except SyntaxError as err:
        raise CommandError("syntax", f"cannot read `{_shown(text)}`: {err.msg}") from err
    except (ValueError, MemoryError, RecursionError) as err:
        raise CommandError("syntax", f"cannot read `{_shown(text)}`: not a command") from err


def _read_statement(text: str) -> tuple[str, dict[str, Any]]:
    tree = ast.parse(text, mode="eval").body
    if isinstance(tree, ast.Name):  # a bare `kick`
        return tree.id, {}
    if not isinstance(tree, ast.Call) or not isinstance(tree.func, ast.Name):
        raise CommandError("syntax", f"`{_shown(text)}` is not a command like name(argument=value)")
    name = tree.func.id
    spec = COMMANDS.get(name)
    if spec is None:  # let validate_command say which commands exist
        return name, {}
    if len(tree.args) > len(spec.positional):
        raise CommandError(
            "syntax",
            f"{name} takes {len(spec.positional)} positional argument(s), got {len(tree.args)}",
        )
    args: dict[str, Any] = {}
    for arg_name, node in zip(spec.positional, tree.args, strict=False):
        args[arg_name] = _value(node)
    for kw in tree.keywords:
        if kw.arg is None:
            raise CommandError("syntax", f"{name}: `**` is not allowed")
        if kw.arg in args:
            raise CommandError("syntax", f"{name}: `{kw.arg}` is given twice")
        args[kw.arg] = _value(kw.value)
    return name, args


def parse_decision(text: str) -> list[Command]:
    """The checked commands of one line of text. Raises `CommandError` (code `syntax` or
    `bad_argument`...)."""
    if not isinstance(text, str):
        raise CommandError("syntax", "a decision written as text must be a string")
    if len(text) > MAX_TEXT:
        raise CommandError("syntax", f"the decision is longer than {MAX_TEXT} characters")
    statements = split_statements(text)
    if not statements:
        raise CommandError("syntax", "the decision is empty; give at least one command")
    commands: list[Command] = []
    for statement in statements:
        try:
            commands.append(validate_command(*_statement(statement)))
        except CommandError as err:
            if err.command is None:
                err.command = leading_name(statement) or "?"
            raise
    return commands


def leading_name(text: str) -> str | None:
    """The word a statement starts with (the command it means), if it starts with one."""
    match = re.match(r"\s*([A-Za-z_]\w{0,39})", text)
    return match.group(1) if match else None
