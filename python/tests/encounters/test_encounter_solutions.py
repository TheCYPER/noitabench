"""Reference solutions of the encounters: every scene is solved by a short script under several
rule seeds (enemies on). The reaction table is the original one for every rule seed, so the rule
seeds only vary the variants and the recipes the engine is seeded with."""

from __future__ import annotations

import pytest
import solutions
from driver import start
from noitabench.worldgen.encounter_defs import load_encounters

RULE_SEEDS = (0, 1, 2, 3, 4, 5)
CASES = [
    (seed, variant) for i, seed in enumerate(RULE_SEEDS) for variant in (i % 2, (i + 1) % 2 + 2)
]


def _checker(eid: str):
    return getattr(solutions, f"check_{eid}")


@pytest.mark.parametrize("rule_seed,variant", CASES)
@pytest.mark.parametrize(
    "eid",
    [
        "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10", "E12", "E14", "E16",
        "E18", "E21", "E22", "E23", "E24",
    ],
)  # fmt: skip
def test_the_reference_solution_works(eid, rule_seed, variant):
    variant %= load_encounters()[eid].variants  # a definition may have fewer variants
    r = start(eid, variant, rule_seed)
    solutions.SOLVERS[eid](r, rule_seed)
    assert _checker(eid)(r) == []


@pytest.mark.parametrize("variant", [0, 1])
def test_the_short_way_of_e22_works_when_the_barrel_is_shot(variant):
    r = start("E22", variant, 0)
    solutions.solve_E22_short(r)
    assert solutions.check_E22(r) == []
    assert r.hp > 30, f"{r.hp:.0f} HP left"


def _blasts(r) -> list[int]:
    return [e["radius"] for e in r.g.events() if e["type"] == "explosion"]


@pytest.mark.parametrize("variant", [0, 1])
def test_the_key_of_the_seal_blasts_with_radius_75_and_breaks_the_plug(variant):
    r = start("E06", variant, 0)
    assert solutions.plug_bricks(r) == 96
    gap = solutions.play_key(r, solutions.KEY)
    assert _blasts(r) == [75], "[EXPLOSIVE_PROJECTILE, BOMB]: the bomb's 60 plus the modifier's 15"
    assert gap > solutions.BLAST_REACH and not r.dead
    assert solutions.plug_bricks(r) < 96


@pytest.mark.parametrize("variant", [0, 1])
@pytest.mark.parametrize("spells", [["BOMB"], ["BOMB", "EXPLOSIVE_PROJECTILE"]])
def test_the_bomb_alone_or_before_the_modifier_leaves_the_plug_intact(variant, spells):
    """Durability 11 against brick 14: the bomb goes off (radius 60) and the plug stays whole.

    With the modifier behind the bomb the first cast is the bomb alone (one spell per cast). The
    cards come round again on the next cast, which deals the modifier ahead of the bomb (the
    wand wraps, `explosion_durability.rs` pins that down), so this is a first throw only."""
    r = start("E06", variant, 0)
    solutions.play_key(r, spells)
    assert _blasts(r) == [60]
    assert solutions.plug_bricks(r) == 96
    assert not r.dead
