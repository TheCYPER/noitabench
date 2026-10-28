"""The key of the seal: which spells open the brick plug of the sealed deep, and in which wand.

Brick has durability 14. No single spell of the content removes it: ``BOMB``'s explosion removes up
to 11, and the modifier ``EXPLOSIVE_PROJECTILE`` raises the max durability of the explosion of the
projectile it modifies by 3 (``shot.explosion_durability`` in ``content/spells.json``; the largest
bonus among the modifiers counts, copies do not stack). So the key is two spells the world hands
out in two places (``role: "breaker"`` markers of the encounter scenes E02 and E12) and the order
the player puts them in the starter spark wand: the modifier first, the projectile after it.

``best_combo`` answers, for the spells the world hands out, how hard an explosion the starter wand
can be made to cast; the ``seal_breakable`` predicate compares that with the plug.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from .config import load_materials
from .contentio import CONTENT_DIR, read_json

PROJECTILE_TYPES = ("projectile", "static_projectile")


@dataclass(frozen=True)
class Combo:
    """Spells that fit the starter wand, in wand order (the modifier first)."""

    spells: tuple[str, ...]
    durability: int  # the hardest durability the explosion removes
    mana: float  # what one cast costs
    radius: int = 0  # the radius of the explosion in cells


@lru_cache(maxsize=1)
def spell_table() -> dict[str, dict]:
    """``content/spells.json`` by spell key."""
    doc = read_json(CONTENT_DIR / "spells.json")
    return {s["key"]: s for s in doc["spells"]}


@lru_cache(maxsize=1)
def starter_spark_wand() -> tuple[int, float]:
    """``(capacity, mana_max)`` of the spark wand the player starts with (``entities.json``)."""
    wand = read_json(CONTENT_DIR / "entities.json")["starter"]["wands"][0]
    return int(wand["stats"]["capacity"]), float(wand["stats"]["mana_max"])


def plug_durability() -> int:
    """The durability of the seal's plug (brick)."""
    mats = load_materials()
    return int(mats.durability[mats["brick"]])


def own_durability(spell: dict) -> int | None:
    """The max durability of the explosion a projectile spell has by itself, else None."""
    explosion = (spell.get("projectile") or {}).get("explosion")
    return None if not explosion else int(explosion["max_durability"])


def own_radius(spell: dict) -> int:
    """The radius of the explosion a projectile spell has by itself (0 if it has none)."""
    explosion = (spell.get("projectile") or {}).get("explosion")
    return 0 if not explosion else int(explosion["radius"])


def best_combo(spells: Iterable[str]) -> Combo | None:
    """The explosion of the highest durability that ``spells`` can make in the starter wand.

    A projectile with an explosion, alone or after one modifier that raises the durability of
    the explosion (a second one adds nothing: the largest bonus counts). The cards must fit the
    wand's capacity, one cast must be paid by its mana, and every card needs a use left.
    """
    table = spell_table()
    capacity, mana_max = starter_spark_wand()
    held = [table[k] for k in dict.fromkeys(spells) if k in table]
    projectiles = [
        s for s in held if s["type"] in PROJECTILE_TYPES and own_durability(s) is not None
    ]
    helpers = [s for s in held if s["type"] == "modifier" and s["shot"]["explosion_durability"]]
    best: Combo | None = None
    for p in projectiles:
        for m in [None, *helpers]:
            cards = [p] if m is None else [m, p]
            mana = sum(float(c["mana"]) for c in cards)
            usable = all(c["max_uses"] is None or c["max_uses"] >= 1 for c in cards)
            if len(cards) > capacity or mana > mana_max or not usable:
                continue
            bonus = 0 if m is None else int(m["shot"]["explosion_durability"])
            durability = (own_durability(p) or 0) + bonus
            radius = own_radius(p) + (0 if m is None else int(m["shot"]["explosion_radius"]))
            combo = Combo(tuple(c["key"] for c in cards), durability, mana, radius)
            if best is None or (combo.durability, -combo.mana) > (best.durability, -best.mana):
                best = combo
    return best


def blast_radius(spells: Iterable[str]) -> int:
    """The radius of the biggest-durability explosion ``spells`` can make (0 if they make none).

    With the content as it is, this is the radius of the blast that opens the plug. The radius is
    that of the same combination ``best_combo`` picks, whether or not it reaches the plug.
    """
    combo = best_combo(spells)
    return 0 if combo is None else combo.radius
