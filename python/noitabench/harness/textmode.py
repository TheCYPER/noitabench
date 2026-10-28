"""Plain-text mode: finding the commands in a model's message.

A model without tools answers in prose and ends with its commands in the grammar of the agent
layer (`walk_to(x=180); fire(until=target_dead)`). `extract_decision` picks them out: the last
fenced block, else the last run of lines that are commands. A statement counts as a command only
if it has the shape the game itself reads, a bare name or `name(...)` with a known name (the
check is the game's own, `ast` without evaluating anything), so a sentence that merely starts
with a command word ("wait for the enemy to come closer") is prose and is never sent to the game.
"""

from __future__ import annotations

import ast
import re

from noitabench.agent.grammar import split_statements
from noitabench.agent.spec import COMMANDS

from .prompt import TEXT_MODE_BUDGET_WORD

_FENCE = re.compile(r"```[A-Za-z]*\n(.*?)```", re.DOTALL)
_PARSE_FAILURES = (SyntaxError, ValueError, MemoryError, RecursionError)


def _is_command(statement: str) -> bool:
    """Is `statement` exactly `name` or `name(...)` for a command (or the budget word)?"""
    try:
        node = ast.parse(statement, mode="eval").body
    except _PARSE_FAILURES:
        return False
    if isinstance(node, ast.Call):
        node = node.func
    return isinstance(node, ast.Name) and (node.id in COMMANDS or node.id == TEXT_MODE_BUDGET_WORD)


def _is_command_line(line: str) -> bool:
    statements = split_statements(line)
    return bool(statements) and all(_is_command(statement) for statement in statements)


def extract_decision(text: str) -> str | None:
    """The decision text in `text`, or None if there is none."""
    for block in reversed(_FENCE.findall(text)):
        block = block.strip()
        if block and all(_is_command_line(line) for line in block.splitlines() if line.strip()):
            return block
    lines = [ln.strip().strip("`").strip() for ln in text.splitlines() if ln.strip()]
    found: list[str] = []
    for line in reversed(lines):
        if _is_command_line(line):
            found.append(line)
        elif found:
            break
    if not found:
        return None
    return "; ".join(reversed(found))


def is_budget_request(decision: str) -> bool:
    parts = split_statements(decision)
    return (
        len(parts) == 1
        and re.fullmatch(rf"{TEXT_MODE_BUDGET_WORD}\s*(\(\s*\))?", parts[0]) is not None
    )
