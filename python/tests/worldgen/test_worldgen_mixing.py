"""Accidental potions (mixing.py, ``alchemy_checks._check_accidental_mixes``).

The terrain does not depend on the rule seed, so a world in which three ingredients touch would
make a potion at frame 0 for every rule seed whose recipes include that triple. The detector must
see exactly what the simulation's mixing rule sees; the tests compare the two on sealed tubes, and
then check the generated worlds (and the worlds that used to fail) in the game itself.
"""

from __future__ import annotations

import dataclasses
import itertools
from types import SimpleNamespace

import noitabench_core
import numpy as np
import pytest
from noitabench.game import Game
from noitabench.worldgen import generate_world
from noitabench.worldgen.alchemy_checks import _check_accidental_mixes
from noitabench.worldgen.mixing import MIX_REACH, touching_triples
from noitabench.worldgen.table import get_rules

# three powders: a sealed tube of them never moves (nothing lies below, nothing is lighter)
TRIO = ("sand", "gold_dust", "bone_dust")
LETTERS = {"a": TRIO[0], "b": TRIO[1], "c": TRIO[2], "#": "rock", ".": "air"}


@pytest.fixture(scope="module")
def ingredients(mats):
    return mats.with_tag("ingredient")


def _tube(mats, text: str, vertical: bool = False) -> np.ndarray:
    """A rock slab with one tube of ``text`` through it (a=sand, b=gold dust, c=bone dust)."""
    n = len(text)
    grid = np.full((n + 8, 9) if vertical else (9, n + 8), mats["rock"], dtype=np.uint8)
    for i, ch in enumerate(text):
        y, x = (4 + i, 4) if vertical else (4, 4 + i)
        grid[y, x] = mats[LETTERS[ch]]
    return grid


def _meets(mats, ingredients, text: str, vertical: bool = False) -> bool:
    return bool(touching_triples(_tube(mats, text, vertical), mats, ingredients))


CASES = [
    ("abc", True),  # three in a row
    ("cba", True),
    ("aabbcc", True),  # the middle layer sees both ends
    ("a" + "b" * MIX_REACH + "c", True),  # the end is exactly in reach
    ("a" + "b" * (MIX_REACH + 1) + "c", False),  # one cell too far
    ("ab#c", False),  # something that is no ingredient stops the look
    ("abab", False),  # two ingredients only
    ("aabb", False),
    ("a#bc", False),  # only two of the three touch
]


# air in a vertical tube lets the powder fall: only a horizontal tube keeps its cells at rest
HORIZONTAL_ONLY = [("ab.c", False), ("a.bc", False)]


@pytest.mark.parametrize(
    "text, expected, vertical",
    [(t, e, v) for t, e in CASES for v in (False, True)]
    + [(t, e, False) for t, e in HORIZONTAL_ONLY],
)
def test_the_detector_reads_a_tube_the_way_the_mixing_rule_does(
    mats, ingredients, text, expected, vertical
):
    assert _meets(mats, ingredients, text, vertical) is expected


def test_the_detector_names_the_triple_and_where_it_meets(mats, ingredients):
    found = touching_triples(_tube(mats, "abc"), mats, ingredients)
    assert list(found) == [("sand", "gold_dust", "bone_dust")]
    x, y = found[("sand", "gold_dust", "bone_dust")]
    assert y == 4 and 4 <= x <= 6


def test_a_grid_with_no_ingredients_or_one_kind_meets_nothing(mats, ingredients):
    assert (
        touching_triples(np.full((20, 20), mats["rock"], dtype=np.uint8), mats, ingredients) == {}
    )
    grid = np.full((20, 20), mats["sand"], dtype=np.uint8)
    assert touching_triples(grid, mats, ingredients) == {}


def test_the_look_stays_inside_the_grid(mats, ingredients):
    grid = np.full((6, 6), mats["sand"], dtype=np.uint8)
    grid[0, 0], grid[5, 5], grid[2, 2] = mats["gold_dust"], mats["bone_dust"], mats["gold_dust"]
    touching_triples(grid, mats, ingredients)  # reaches past every edge without an index error


def _engine_mixes(mats, text: str, vertical: bool) -> bool:
    """Does the simulation turn the triple of the tube into a potion by itself?"""
    grid = _tube(mats, text, vertical)
    h, w = grid.shape
    game = Game(w, h, 1, recipes=[{"potion": "potion_crit", "inputs": list(TRIO)}])
    game.fill_rect(0, 0, w, h, "rock")
    for y, x in zip(*np.nonzero(grid != mats["rock"])):
        game.fill_rect(int(x), int(y), 1, 1, mats.keys[grid[y, x]])
    game.step(150)
    return any(e["type"] == "mix" for e in game.events())


@pytest.mark.parametrize(
    "text, expected, vertical",
    [(t, e, v) for t, e in CASES for v in (False, True)]
    + [(t, e, False) for t, e in HORIZONTAL_ONLY],
)
def test_the_detector_and_the_simulation_agree_on_every_tube(mats, text, expected, vertical):
    """The point of the module: what it flags is what the engine mixes, and nothing else."""
    assert _engine_mixes(mats, text, vertical) is expected


def test_a_world_where_three_ingredients_touch_fails_whatever_the_rule_seed(mats):
    grid = _tube(mats, "abc")
    for rule_seed in (0, 1, 2, 3):
        failures: list[str] = []
        _check_accidental_mixes(SimpleNamespace(grid=grid), mats, get_rules(rule_seed), failures)
        assert len(failures) == 1 and "sand, gold_dust and bone_dust touch" in failures[0]
        assert "potion at frame 0" in failures[0]


def test_a_pair_that_reacts_is_no_recipe_and_does_not_count(mats):
    """Water and toxic sludge turn into water when they touch: no recipe can hold both."""
    grid = np.full((9, 12), mats["rock"], dtype=np.uint8)
    grid[4, 4:7] = [mats["water"], mats["toxic_sludge"], mats["sand"]]
    failures: list[str] = []
    _check_accidental_mixes(SimpleNamespace(grid=grid), mats, get_rules(0), failures)
    assert failures == []
    grid[4, 4:7] = [mats["water"], mats["oil"], mats["sand"]]  # a possible recipe
    _check_accidental_mixes(SimpleNamespace(grid=grid), mats, get_rules(0), failures)
    assert len(failures) == 1 and "water, oil and sand" in failures[0]


def test_many_triples_are_listed_in_brief(mats, ingredients):
    grid = np.full((12, 40), mats["rock"], dtype=np.uint8)
    for k, trio in enumerate(itertools.combinations(("sand", "coal", "gunpowder", "gold_dust"), 3)):
        grid[2 + 2 * k, 2:5] = [mats[m] for m in trio]
    failures: list[str] = []
    _check_accidental_mixes(SimpleNamespace(grid=grid), mats, get_rules(0), failures)
    assert len(failures) == 4 and "1 more triples" in failures[-1]


# --------------------------------------------------------------------- generated worlds


def test_generated_worlds_have_no_three_ingredients_touching(world_a, world_b, mats, ingredients):
    for w in (world_a, world_b):
        assert touching_triples(w.grid, mats, ingredients) == {}


def _mix_events(world, mats, tmp_path, rule_seed: int, frames: int = 300) -> list[dict]:
    png, js = dataclasses.replace(world, rule_seed=rule_seed).write(tmp_path, f"w{rule_seed}", mats)
    game = Game.from_world(png, js, world.seed, rule_seed=rule_seed)
    events: list[dict] = []
    for _ in range(frames // 60):
        game.step(60)
        events += [e for e in game.events() if e["type"] == "mix"]
    return events


# seeds whose first attempt put coal, gunpowder and bone dust (or water, coal and fungus powder)
# side by side: the new check rebuilds them, and the game must stay quiet for every recipe
@pytest.mark.parametrize("seed, rule_seed", [(109, 3), (19, 0), (10, 7), (47, 5)])
def test_the_game_makes_no_potion_by_itself_in_the_worlds_that_used_to_(
    mats, tmp_path, seed, rule_seed
):
    world = generate_world(seed, rule_seed)
    assert _mix_events(world, mats, tmp_path, rule_seed) == []


def test_a_refused_first_attempt_really_makes_a_potion_in_the_game(mats, bm, ingredients, tmp_path):
    """Positive control on real terrain: the first attempt for seed 20 (the one the check
    refuses: coal, gunpowder and bone dust touch in the coal pit) turns into a potion in the game
    when the rule seed's recipes include that triple (rule seed 14: berserk). If the generator
    changes and that attempt passes, pick another refused seed (``python -m noitabench world
    check`` lists the re-rolled ones; seed 109 until the scenes of batch G1 moved the layouts)."""
    from noitabench.worldgen.encounter_place import SceneContext
    from noitabench.worldgen.generate import _build

    world = _build(20, 20, 14, 0, bm, mats, SceneContext.build(get_rules(14), mats))
    found = touching_triples(world.grid, mats, ingredients)
    assert ("coal", "gunpowder", "bone_dust") in found, found
    recipes = {tuple(sorted(r["inputs"])) for r in noitabench_core.recipes(14)}
    assert tuple(sorted(("coal", "gunpowder", "bone_dust"))) in recipes
    events = _mix_events(world, mats, tmp_path, 14)
    assert events and {e["potion"] for e in events} == {"potion_berserk"}
