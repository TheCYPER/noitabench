"""What the player's bottles hold, read from the player dict.

A bottle is a flask: it can hold a mixture (`contents`, material key -> cells) and always carries
its largest share as `material` with the total `amount`. These helpers read both shapes, so the
bot works with a game that gives only `material` and `amount`.
"""

from __future__ import annotations

from typing import Any


def bottle_parts(bottle: dict[str, Any]) -> dict[str, int]:
    """Material key -> cells in a bottle of the player (empty parts left out)."""
    contents = bottle.get("contents")
    if isinstance(contents, dict):
        return {str(k): int(v) for k, v in contents.items() if int(v) > 0}
    if isinstance(contents, list):
        return {str(c["material"]): int(c["amount"]) for c in contents if int(c["amount"]) > 0}
    amount = int(bottle.get("amount", 0))
    return {str(bottle["material"]): amount} if amount > 0 else {}


def bottle_total(bottle: dict[str, Any]) -> int:
    """Cells in a bottle, all materials together."""
    return sum(bottle_parts(bottle).values())


def holding(player: dict[str, Any], materials: set[str] | frozenset[str]) -> int | None:
    """Index of the first bottle that holds any of the `materials`."""
    for i, b in enumerate(player["bottles"]):
        if any(m in materials for m in bottle_parts(b)):
            return i
    return None


def empty_bottle(player: dict[str, Any]) -> int | None:
    """Index of the first empty bottle."""
    for i, b in enumerate(player["bottles"]):
        if bottle_total(b) == 0:
            return i
    return None
