"""Which wand holds what: the bot picks wands by the spell inside, not by their place.

The starting loadout is a spark wand (`LIGHT_BULLET`, slow) and a digger wand (`DIGGER`, quick).
`arm_for_combat` uses the wand editor, as a player could, to give the quick wand the spark bolt:
the same bolt then flies about three times as often, and digging gets a little slower.
"""

from __future__ import annotations

from typing import Any

from noitabench.game import Game

SPARK = "LIGHT_BULLET"
DIGGER = "DIGGER"


def wand_with(player: dict[str, Any], spell: str, default: int = 0) -> int:
    """Index of the first held wand that has `spell` in a slot (`default` if none)."""
    for i, wand in enumerate(player["wands"]):
        if any(slot and slot["spell"] == spell for slot in wand["slots"]):
            return i
    return default


def active_wand_has(player: dict[str, Any], spell: str) -> bool:
    """Whether the wand in hand has `spell` in a slot."""
    wands = player["wands"]
    index = int(player["active_wand"])
    if not 0 <= index < len(wands):
        return False
    return any(slot and slot["spell"] == spell for slot in wands[index]["slots"])


def arm_for_combat(game: Game) -> bool:
    """Swap the spark bolt and the digging bolt between the two starting wands, so that the wand
    with the shorter cast delay and recharge shoots. False if the loadout is not the starter's."""
    p = game.player()
    if p is None or len(p["wands"]) < 2:
        return False
    spark, digger = wand_with(p, SPARK, -1), wand_with(p, DIGGER, -1)
    if spark < 0 or digger < 0 or spark == digger:
        return False
    if _cycle(p, digger) >= _cycle(p, spark):  # the spark wand is already the quick one
        return False
    game.edit_wand({"op": "take", "wand": spark, "slot": _slot_of(p, spark, SPARK)})
    carried = len(p["spells"])  # the spark bolt is the last card of the inventory now
    game.edit_wand(
        {"op": "place", "wand": digger, "slot": _slot_of(p, digger, DIGGER), "from": carried}
    )
    game.edit_wand({"op": "place", "wand": spark, "slot": 0, "from": carried})  # the digger card
    return True


def _slot_of(player: dict[str, Any], wand: int, spell: str) -> int:
    slots = player["wands"][wand]["slots"]
    return next(i for i, s in enumerate(slots) if s and s["spell"] == spell)


def _cycle(player: dict[str, Any], wand: int) -> int:
    """Frames between two casts of a wand that holds one card: cast delay plus recharge."""
    stats = player["wands"][wand]["stats"]
    return int(stats["cast_delay"] + stats["recharge"])
