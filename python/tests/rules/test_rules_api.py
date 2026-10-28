"""The Python surface of the rules: the original table (`noitabench_core.rules()`), the secret
recipes (`noitabench_core.recipes()`), the absence of the removed perturbation layer, and
recipes in worlds (empty worlds and world files).

Recipes and the rule seed are tooling data: an agent never sees them (contracts sections 10, 11).
"""

from __future__ import annotations

import json
from pathlib import Path

import noitabench_core
import pytest
from noitabench.game import Game
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
REACTIONS = (REPO / "content" / "reactions.json").read_text(encoding="utf-8")
MATERIALS = json.loads((REPO / "content" / "materials.json").read_text(encoding="utf-8"))
BY_KEY = {m["key"]: m for m in MATERIALS["materials"]}
POOL = [m["key"] for m in MATERIALS["materials"] if "ingredient" in m["tags"]]
POTIONS = [m["key"] for m in MATERIALS["materials"] if "secret_potion" in m["tags"]]


# ----- the original table --------------------------------------------------------------------


def test_rules_is_the_original_table() -> None:
    r = noitabench_core.rules()
    assert r.reactions_json == REACTIONS
    assert r.content_hash == noitabench_core.Env(1, 1, 0).content_hash
    assert r.check_invariants() == []
    assert r.transforms("lava", "water") == ("rock", "steam", 0.8)
    assert r.transforms("water", "sand") is None
    assert {s["liquid"] for s in r.lava_solidifiers()} == {"water", "blood", "toxic_sludge"}
    assert r.water_family_extinguishes()
    assert any(e["material"] == "water" for e in r.extinguishers())
    assert r.acid_dissolves("rock") == 0.5 and r.acid_dissolves("metal") is None
    assert r.ignites("fire", "flammable_gas") == 0.4
    row = r.reactions_for("water", "wood", b_burning=True)
    assert len(row) == 1 and row[0]["out_b"] == "@extinguish" and row[0]["b_burning"]
    assert noitabench_core.rules().content_hash == r.content_hash


def test_the_alchemy_ingredients_react_with_nothing() -> None:
    r = noitabench_core.rules()
    for new in ("gold_dust", "bone_dust", "fungus_powder", "slime", "metal"):
        for other in POOL:
            assert r.reactions_for(new, other) == [], (new, other)


# ----- recipes -------------------------------------------------------------------------------


def test_recipes_are_eight_valid_triples() -> None:
    r = noitabench_core.rules()
    for seed in range(200):
        book = noitabench_core.recipes(seed)
        assert [x["potion"] for x in book] == POTIONS
        assert book == r.recipes(seed)
        sets = set()
        uses: dict[str, int] = {}
        for x in book:
            assert set(x) == {"potion", "inputs"} and len(x["inputs"]) == 3
            assert len(set(x["inputs"])) == 3 and set(x["inputs"]) <= set(POOL)
            assert x["inputs"] == sorted(x["inputs"], key=lambda k: BY_KEY[k]["index"])
            for i, a in enumerate(x["inputs"]):
                for b in x["inputs"][i + 1 :]:
                    assert r.reactions_for(a, b) == [], (seed, a, b)
                uses[a] = uses.get(a, 0) + 1
            sets.add(tuple(x["inputs"]))
        assert len(sets) == 8 and max(uses.values()) <= 3


def test_recipes_depend_on_the_rule_seed_alone() -> None:
    assert noitabench_core.recipes(5) == noitabench_core.recipes(5)
    assert noitabench_core.recipes(5) != noitabench_core.recipes(6)
    assert len({json.dumps(noitabench_core.recipes(s)) for s in range(100)}) == 100
    assert noitabench_core.recipes(2**64 - 1)
    for bad in (-1, 2**64):
        with pytest.raises(ValueError, match="rule_seed"):
            noitabench_core.recipes(bad)


def test_the_reaction_file_never_lists_a_recipe() -> None:
    rows = json.loads(REACTIONS)["reactions"]
    assert not any(
        k.startswith("potion_")
        for row in rows
        for k in (row["a"], row["b"], row["out_a"], row["out_b"])
    )


# ----- the removed compatibility layer ---------------------------------------------------------


def test_the_perturbation_compatibility_layer_is_gone() -> None:
    # the table is never perturbed (CP2, 2026-10-27); only `rules()` and `recipes()` remain
    assert not hasattr(noitabench_core, "perturb")
    assert not hasattr(noitabench_core, "Perturbed")


# ----- recipes in worlds ---------------------------------------------------------------------


def stack(game_or_env, recipe: dict) -> None:
    """Three cells of the ingredients in a one-cell shaft."""
    game_or_env.fill_rect(0, 20, 5, 10, "rock")
    game_or_env.fill_rect(2, 0, 1, 20, "air")
    game_or_env.fill_rect(0, 0, 2, 20, "rock")
    game_or_env.fill_rect(3, 0, 2, 20, "rock")
    for i, key in enumerate(recipe["inputs"]):
        game_or_env.fill_rect(2, 15 + i, 1, 1, key)


def potion_cells(game_or_env, potion: str) -> int:
    keys = game_or_env.material_keys()
    return sum(1 for c in game_or_env.grid() if keys[c] == potion)


@pytest.mark.parametrize("make", ["env", "game"])
def test_a_world_with_a_rule_seed_mixes_its_recipes(make: str) -> None:
    from noitabench.env import Env

    cls = Env if make == "env" else Game
    book = noitabench_core.recipes(7)
    for recipe in book:
        world = cls(5, 30, 1, rule_seed=7)
        stack(world, recipe)
        (world.step_frames if make == "env" else world.step)(120)
        assert potion_cells(world, recipe["potion"]) == 3, recipe
    # no rule seed, no recipes: the same stack stays three ingredients
    world = cls(5, 30, 1)
    stack(world, book[0])
    (world.step_frames if make == "env" else world.step)(120)
    assert potion_cells(world, book[0]["potion"]) == 0
    # your own recipes
    own = [{"potion": "potion_crit", "inputs": ["water", "sand", "coal"]}]
    world = cls(5, 30, 1, recipes=own)
    stack(world, own[0])
    (world.step_frames if make == "env" else world.step)(120)
    assert potion_cells(world, "potion_crit") == 3


def test_the_recipes_change_the_content_hash_not_the_table() -> None:
    plain = Game(5, 5, 1)
    a, b = Game(5, 5, 1, rule_seed=1), Game(5, 5, 1, rule_seed=2)
    assert len({plain.content_hash, a.content_hash, b.content_hash}) == 3
    assert Game(5, 5, 1, rule_seed=1).content_hash == a.content_hash
    assert Game(5, 5, 1, recipes=[]).content_hash == plain.content_hash


def test_bad_recipes_are_value_errors() -> None:
    with pytest.raises(ValueError, match="recipes\\[0\\]"):
        Game(5, 5, 1, recipes=[{"potion": "potion_crit", "inputs": ["water", "sand", "mercury"]}])
    with pytest.raises(ValueError, match="exactly three"):
        Game(5, 5, 1, recipes=[{"potion": "potion_crit", "inputs": ["water", "sand"]}])
    with pytest.raises(ValueError, match="needs `potion`"):
        Game(5, 5, 1, recipes=[{"inputs": ["water", "sand", "coal"]}])
    with pytest.raises(ValueError, match="each recipe is a dict"):
        Game(5, 5, 1, recipes=["water"])


def write_world(tmp_path: Path, rule_seed: int) -> tuple[Path, Path]:
    w, h = 60, 40
    keys = [m["key"] for m in MATERIALS["materials"]]
    indices = bytearray(w * h)
    for y in range(30, h):
        for x in range(w):
            indices[y * w + x] = keys.index("rock")
    image = Image.frombytes("P", (w, h), bytes(indices))
    palette: list[int] = []
    for m in MATERIALS["materials"]:
        c = m["color"]
        palette += [int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)]
    image.putpalette(palette + [0] * (768 - len(palette)))
    png, js = tmp_path / "w.png", tmp_path / "w.json"
    image.save(png)
    js.write_text(
        json.dumps(
            {
                "format": "cogbench-world/0",
                "seed": 3,
                "rule_seed": rule_seed,
                "width": w,
                "height": h,
                "biome_cell_size": 128,
                "biome_map": [["start"]],
                "markers": [{"type": "spawn_player", "x": 10, "y": 29}],
            }
        ),
        encoding="utf-8",
    )
    return png, js


def test_a_world_file_gets_the_recipes_of_its_rule_seed(tmp_path: Path) -> None:
    png, js = write_world(tmp_path, 4)
    a = Game.from_world(png, js)
    assert a.rule_seed == 4
    assert a.content_hash == Game(60, 40, 3, rule_seed=4).content_hash
    assert (
        Game.from_world(png, js, rule_seed=5).content_hash
        == Game(1, 1, 3, rule_seed=5).content_hash
    )
    assert Game.from_world(png, js, recipes=[]).content_hash == Game(1, 1, 3).content_hash
    # the original table can be injected without changing anything
    same = Game.from_world(png, js, reactions_json=REACTIONS)
    assert same.content_hash == a.content_hash
    from noitabench.env import Env

    assert Env.from_world(png, js).content_hash == a.content_hash
    assert Env.from_world(png, js, recipes=[]).content_hash == Game(1, 1, 3).content_hash
    # mixing in the loaded world
    recipe = noitabench_core.recipes(4)[0]
    g = Game.from_world(png, js)
    g.fill_rect(20, 10, 1, 20, "air")
    g.fill_rect(19, 10, 1, 20, "rock")
    g.fill_rect(21, 10, 1, 20, "rock")
    for i, key in enumerate(recipe["inputs"]):
        g.fill_rect(20, 25 + i, 1, 1, key)
    g.step(120)
    assert potion_cells(g, recipe["potion"]) == 3
