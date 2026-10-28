"""The content files the knowledge base is built from, read once.

`content/{materials,reactions,entities,spells}.json` and `content/encounters/E*.json` are the only
inputs (with `noitabench_core.recipes` for the seed). Everything is read from `worldinfo.CONTENT`,
the folder the rest of the evaluation uses.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from ..worldinfo import CONTENT


def _load(name: str) -> Any:
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


@cache
def materials() -> tuple[dict[str, Any], ...]:
    """The rows of `content/materials.json`, air included, in index order."""
    return tuple(sorted(_load("materials.json")["materials"], key=lambda m: m["index"]))


@cache
def material_table() -> dict[str, dict[str, Any]]:
    return {m["key"]: m for m in materials()}


@cache
def reactions() -> tuple[dict[str, Any], ...]:
    return tuple(_load("reactions.json")["reactions"])


@cache
def entities() -> dict[str, Any]:
    return _load("entities.json")


@cache
def spells() -> tuple[dict[str, Any], ...]:
    return tuple(_load("spells.json")["spells"])


@cache
def encounters() -> dict[str, dict[str, Any]]:
    """The encounter definitions by id (`content/encounters/E*.json`)."""
    out = {}
    for path in sorted((CONTENT / "encounters").glob("E*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        out[str(doc["id"])] = doc
    return out


@cache
def tag_members() -> dict[str, tuple[str, ...]]:
    """Tag -> the materials that carry it, in index order."""
    out: dict[str, list[str]] = {}
    for m in materials():
        for tag in m.get("tags", ()):
            out.setdefault(tag, []).append(m["key"])
    return {tag: tuple(keys) for tag, keys in out.items()}
