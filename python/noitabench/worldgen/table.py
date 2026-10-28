"""The rules of a world: the reaction table as the encounters need to see it.

The reaction table is the original one for every seed (CP2 decision, 2026-10-27: only the
potion recipes vary with the rule seed). ``Rules`` wraps the Rust ``cogbench-rules`` crate
(``noitabench_core.rules()``, the queries of the original table) and answers the questions scene
placement and the solvability checks ask: which liquids turn lava to rock, which put burning
cells out, which pairs react at all, and which three ingredients make each secret potion of a
rule seed. ``_load_table`` is the one place that talks to the binding.

**Never let rule-seed text reach an agent.** ``reactions_json`` and the recipes name the seed
(contracts section 10); this module is world-generation and test tooling only.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import noitabench_core

# Liquids a scene may hand out as "some liquid": never acid (barrels and vats only), lava (it
# has its own role) or a potion (the recipe makes those).
PLAIN_LIQUIDS = ("water", "blood", "oil", "whiskey", "toxic_sludge")
FUELS = ("oil", "whiskey")

ROLES = (
    "lava_solidifier",
    "not_lava_solidifier",
    "extinguisher",
    "not_extinguisher",
    "fuel",
    "plain_liquid",
)


@dataclass(frozen=True)
class Rules:
    """The reaction table of a world (the original table; ``rule_seed`` only seeds the recipes)."""

    rule_seed: int
    table: noitabench_core.Rules

    @property
    def reactions_json(self) -> str:
        return self.table.reactions_json

    @property
    def content_hash(self) -> int:
        return self.table.content_hash

    def recipes(self) -> list[tuple[str, tuple[str, str, str]]]:
        """The secret recipes of the rule seed: ``(potion, (ingredient, ingredient, ingredient))``."""
        return [
            (r["potion"], (r["inputs"][0], r["inputs"][1], r["inputs"][2]))
            for r in noitabench_core.recipes(self.rule_seed)
        ]

    # ------------------------------------------------------------------ predicates
    def solidifiers(self) -> list[str]:
        """Liquids that turn lava into rock or ground at 40 % or more, sorted by key."""
        return sorted(s["liquid"] for s in self.table.lava_solidifiers())

    def solidifier_info(self, liquid: str) -> dict | None:
        for s in self.table.lava_solidifiers():
            if s["liquid"] == liquid:
                return s
        return None

    def extinguishers(self) -> list[str]:
        """Liquids that put burning cells out at 30 % or more, sorted by key."""
        return sorted(
            e["material"] for e in self.table.extinguishers() if e["material"] in PLAIN_LIQUIDS
        )

    def transforms(self, a: str, b: str) -> tuple[str, str, float] | None:
        return self.table.transforms(a, b)

    def reacts(self, a: str, b: str) -> bool:
        """True if two plain cells of ``a`` and ``b`` can react when they touch."""
        return bool(self.table.reactions_for(a, b))

    def turns_lava_solid(self, liquid: str) -> bool:
        return liquid in self.solidifiers()

    def ignites(self, source: str, target: str) -> float | None:
        return self.table.ignites(source, target)

    def acid_dissolves(self, target: str) -> float | None:
        return self.table.acid_dissolves(target)

    # ------------------------------------------------------------------ roles
    def candidates(self, role: str) -> list[str]:
        """Materials that fill ``role`` in this world, in a fixed order (see ``ROLES``)."""
        solid = self.solidifiers()
        douse = self.extinguishers()
        if role == "lava_solidifier":
            return solid
        if role == "not_lava_solidifier":
            return [m for m in PLAIN_LIQUIDS if m not in solid]
        if role == "extinguisher":
            return douse
        if role == "not_extinguisher":
            return [m for m in PLAIN_LIQUIDS if m not in douse]
        if role == "fuel":
            return list(FUELS)
        if role == "plain_liquid":
            return list(PLAIN_LIQUIDS)
        raise ValueError(f"unknown liquid role '{role}'; choose one of {', '.join(ROLES)}")


@lru_cache(maxsize=1)
def _load_table() -> noitabench_core.Rules:
    """The engine's query object for the original reaction table (the same for every seed)."""
    return noitabench_core.rules()


@lru_cache(maxsize=256)
def get_rules(rule_seed: int) -> Rules:
    """The rules of ``rule_seed``; cached (the table is shared, only the recipes differ)."""
    return Rules(rule_seed, _load_table())
