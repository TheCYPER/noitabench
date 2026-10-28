"""Alchemy supplies (alchemy.py, alchemy_checks.py, reach.py): ingredients, bottles, bowls.

CP2 (2026-10-27): only the recipes of the secret potions change from seed to seed, so every
generated world has to hand out the twelve ingredients, the bottles to carry them and a bowl to
try them in. The last tests load generated worlds into the game and make a potion in a bowl.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import shutil

import noitabench_core
import numpy as np
import pytest
from noitabench.game import Game
from noitabench.worldgen import alchemy
from noitabench.worldgen.canvas import Canvas, GenerationFailure
from noitabench.worldgen.checks import run_checks
from noitabench.worldgen.config import (
    CONTENT_DIR,
    BottleSpec,
    DepositSpec,
    SupplyStyle,
    load_biome_map,
)
from noitabench.worldgen.reach import dig_zone_cells, grow, reach_mask, walk_area
from noitabench.worldgen.rest import mobile_cells
from noitabench.worldgen.settle import settle
from noitabench.worldgen.table import get_rules

W, H, FLOOR = 200, 140, 100
RECT = (0, 0, W, H)
PILE = DepositSpec("gold_dust", "pile", 1, 70, (11, 14))
POOL = DepositSpec("water", "pool", 1, 60, (3, 6), 500)


def _cave(mats, x0=10, x1=190, y0=20, floor=FLOOR) -> Canvas:
    c = Canvas(W, H, mats)
    c.grid[:] = mats["ground"]
    c.carve_rect((x0, y0, x1, floor), force=True)
    return c


def _near(c: Canvas) -> np.ndarray:
    return np.ones(c.grid.shape, dtype=bool)


def _biome(bm, **supply) -> object:
    return dataclasses.replace(bm.biomes["mine"], supply=SupplyStyle(**supply))


def _deposits(c, bm, specs, form, seed=1):
    biome = _biome(bm, deposits=tuple(specs))
    return alchemy.place_deposits(c, biome, RECT, np.random.default_rng(seed), _near(c), form)


# ------------------------------------------------------------------------ biome files


def _edit_supply(tmp_path, edit):
    dst = tmp_path / "content"
    shutil.copytree(CONTENT_DIR, dst)
    path = dst / "biomes" / "mine.json"
    data = json.loads(path.read_text())
    edit(data["supply"])
    path.write_text(json.dumps(data))
    return dst


def test_every_ingredient_has_a_source_in_the_biome_files(bm, mats):
    ingredients = set(mats.with_tag("ingredient"))
    assert len(ingredients) == 12 and not ingredients & set(mats.with_tag("secret_potion"))
    required = {d.material for b in bm.biomes.values() for d in b.supply.deposits if not d.optional}
    bottled = {s.contents for b in bm.biomes.values() for s in b.supply.bottles if s.contents}
    assert bottled == ingredients  # a full bottle of each (the only way to carry a powder)
    assert required == ingredients  # a deposit of each, guaranteed (the optional ones are extra)
    for layer in bm.layers[:2]:  # the first two layers hold bowls and bottles
        assert sum(bm.biomes[k].supply.bowls for k in (layer.left, layer.mid, layer.right)) >= 1


@pytest.mark.parametrize(
    "edit, field",
    [
        (lambda s: s["deposits"][0].update(material="rock"), r"supply\.deposits\[0\]"),
        (lambda s: s["deposits"][0].update(material="water"), "a pile needs a powder"),
        (lambda s: s["deposits"][0].update(form="mound"), "form must be"),
        (lambda s: s["deposits"][0].update(count=0), r"count"),
        (lambda s: s["deposits"][0].update(min_cells=3), r"min_cells"),
        (lambda s: s["bottles"][0].update(contents="acid"), r"bottles\[0\]\.contents"),
        (lambda s: s["bottles"][0].update(contents="potion_crit"), r"bottles\[0\]\.contents"),
        (lambda s: s["bottles"][0].update(count=0), r"bottles\[0\]\.count"),
        (lambda s: s.update(bowls=-1), r"supply\.bowls"),
    ],
)
def test_a_bad_supply_names_its_field(tmp_path, edit, field):
    with pytest.raises(ValueError, match=field):
        load_biome_map(_edit_supply(tmp_path, edit))


def test_materials_know_their_tags(mats):
    assert "water" in mats.with_tag("ingredient") and "metal" not in mats.with_tag("ingredient")
    assert mats.with_tag("secret_potion")[0].startswith("potion_")
    assert mats.with_tag("no_such_tag") == ()


# ---------------------------------------------------------------------------- deposits


def test_a_pile_is_heaped_on_the_floor_with_at_least_its_cells(mats, bm):
    c = _cave(mats)
    [dep] = _deposits(c, bm, [PILE], "pile")
    assert dep["shape"] == "heap" and dep["biome"] == "mine" and dep["material"] == "gold_dust"
    assert dep["cells"] >= PILE.min_cells
    assert int((c.grid == mats["gold_dust"]).sum()) == dep["cells"]
    ys, xs = np.nonzero(c.grid == mats["gold_dust"])
    assert abs(int(xs.mean()) - dep["x"]) <= 14 and ys.max() == FLOOR - 1  # lying on the floor
    settle(c)  # a heap comes to rest without losing most of itself
    assert not len(mobile_cells(c.grid, mats, "powder")[0])
    assert int((c.grid == mats["gold_dust"]).sum()) >= PILE.min_cells // 2


def test_a_pool_with_no_basin_to_fill_is_dug_as_a_pit_level_with_the_floor(mats, bm):
    c = _cave(mats)
    [dep] = _deposits(c, bm, [POOL], "pool")
    assert dep["shape"] == "pit" and dep["cells"] >= POOL.min_cells
    water = c.grid == mats["water"]
    ys, xs = np.nonzero(water)
    assert len(xs) == dep["cells"]
    assert ys.min() == FLOOR  # the surface is the floor row ...
    assert (c.grid[FLOOR - 3 : FLOOR, xs.min() : xs.max() + 1] == mats.air).all()  # ... open
    box = water[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    assert box.all()  # a rectangle of liquid
    x0, x1, y1 = xs.min(), xs.max() + 1, ys.max() + 1
    wall = mats["ground"]
    assert (c.grid[FLOOR : y1 + 1, x0 - 1] == wall).all() and (
        c.grid[FLOOR : y1 + 1, x1] == wall
    ).all()
    assert (c.grid[y1, x0 - 1 : x1 + 1] == wall).all()  # walled in on three sides
    assert not len(mobile_cells(c.grid, mats, "liquid")[0])  # at rest as it stands


def test_a_pool_fills_a_closed_basin_when_there_is_one(mats, bm):
    c = _cave(mats)
    c.carve_rect((80, FLOOR, 110, FLOOR + 8), force=True)  # a basin in the floor
    [dep] = _deposits(c, bm, [dataclasses.replace(POOL, size=(3, 4))], "pool")
    assert dep["shape"] == "basin" and 60 <= dep["cells"] <= 500
    xs = np.nonzero((c.grid == mats["water"]).any(axis=0))[0]
    assert xs.min() >= 79 and xs.max() <= 110  # it stays inside the basin
    assert not len(mobile_cells(c.grid, mats, "liquid")[0])


def test_the_pools_of_a_supply_come_before_its_heaps(mats, bm):
    c = _cave(mats)
    biome = _biome(bm, deposits=(PILE, POOL))
    rng = np.random.default_rng(3)
    pools = alchemy.place_deposits(c, biome, RECT, rng, _near(c), "pool")
    piles = alchemy.place_deposits(c, biome, RECT, rng, _near(c), "pile")
    assert [d["form"] for d in pools] == ["pool"] and [d["form"] for d in piles] == ["pile"]
    # a heap keeps away from liquids (it would sink into them) and a pool from other ingredients
    wet = c.grid == mats["water"]
    dust = np.nonzero(c.grid == mats["gold_dust"])
    px, py = int(dust[1].mean()), int(dust[0].mean())
    wy, wx = np.nonzero(wet)
    assert np.min(np.hypot(wx - px, wy - py)) > 5


def test_a_deposit_keeps_ten_cells_from_another_ingredient(mats, bm):
    # 24 wide: no heap (23 and more) and no pit (at least 12 wide and as far from the standing
    # points as its walls reach) can keep ten cells away from a cell in the middle
    c = _cave(mats, x0=88, x1=112)
    c.grid[FLOOR - 1, 100] = mats["blood"]  # a loose cell of another ingredient mid-cave
    assert not any(_deposits(c, bm, [dataclasses.replace(PILE, optional=True)], "pile"))
    c.grid[FLOOR - 1, 100] = mats["coal"]  # a coal vein is not a deposit: it does not count
    assert _deposits(c, bm, [PILE], "pile")


def test_a_required_deposit_without_a_place_fails_the_world_and_an_optional_one_does_not(mats, bm):
    c = _cave(mats)
    biome = _biome(bm, deposits=(PILE,))
    none = np.zeros(c.grid.shape, dtype=bool)  # nowhere the player can stand
    with pytest.raises(GenerationFailure, match="mine: no place for a deposit of gold_dust"):
        alchemy.place_deposits(c, biome, RECT, np.random.default_rng(1), none, "pile")
    optional = _biome(bm, deposits=(dataclasses.replace(PILE, optional=True),))
    assert alchemy.place_deposits(c, optional, RECT, np.random.default_rng(1), none, "pile") == []
    assert alchemy.place_deposits(c, biome, RECT, np.random.default_rng(1), none, "pool") == []


# ----------------------------------------------------------------------------- bottles


def test_bottles_are_full_of_their_ingredient_or_empty_and_keep_their_distance(mats, bm):
    c = _cave(mats)
    biome = _biome(bm, bottles=(BottleSpec("gold_dust"), BottleSpec("water"), BottleSpec("", 2)))
    taken = [(30, FLOOR - 1)]
    home = {"material": "gold_dust", "x": 120, "y": FLOOR - 1}
    out = alchemy.place_bottles(c, biome, RECT, np.random.default_rng(2), _near(c), [home], taken)
    assert [m.get("contents", "") for m in out] == ["gold_dust", "water", "", ""]
    assert all(m["type"] == "item" and m["item"] == "bottle" for m in out)
    assert all("contents" not in m for m in out[2:])  # an empty bottle has no contents key
    spots = [(m["x"], m["y"]) for m in out]
    assert len(taken) == 5 and taken[1:] == spots  # the list of taken spots grows
    pts = [(30, FLOOR - 1), *spots]
    assert all(
        np.hypot(a[0] - b[0], a[1] - b[1]) >= 14 for i, a in enumerate(pts) for b in pts[i + 1 :]
    )
    lo, hi = alchemy.BOTTLE_NEAR
    assert lo <= np.hypot(spots[0][0] - home["x"], spots[0][1] - home["y"]) <= hi
    assert all(c.grid[y, x] == mats.air and c.grid[y + 1, x] == mats["ground"] for x, y in spots)


def test_a_world_without_room_for_a_bottle_fails(mats, bm):
    c = _cave(mats)
    biome = _biome(bm, bottles=(BottleSpec("sand"),))
    none = np.zeros(c.grid.shape, dtype=bool)
    with pytest.raises(GenerationFailure, match="no place for a bottle of sand"):
        alchemy.place_bottles(c, biome, RECT, np.random.default_rng(2), none, [], [])


# ------------------------------------------------------------------------------ reach


def _two_caves(mats, wall: str) -> Canvas:
    c = Canvas(100, 80, mats)
    c.carve_rect((10, 20, 50, 60), force=True)
    c.carve_rect((52, 20, 90, 60), force=True)
    c.fill_rect((50, 20, 52, 60), wall, force=True)
    c.fill_rect((55, 55, 60, 60), "water", force=True)  # a pool in the far cave, behind the wall
    return c


def test_a_pool_behind_a_wall_is_not_within_reach_however_near_it_lies(mats):
    c = _two_caves(mats, "rock")
    walk = walk_area(c.grid, mats, (30, 55))
    assert walk[55, 30] and not walk[55, 70]
    assert grow(walk, 6)[58, 54]  # a plain grown mask crosses the wall ...
    reach = reach_mask(c.grid, mats, walk, 6)
    assert reach[58, 40] and not reach[58, 54] and not reach[58, 57]  # ... the reach does not


def test_a_scene_dug_through_joins_the_walking_area_but_brick_never_does(mats):
    for wall, joined in (("ground", True), ("brick", False)):
        c = _two_caves(mats, wall)
        dug = dig_zone_cells(c.grid, mats, [(50, 20, 2, 40)])
        assert bool(dug.any()) is joined  # ground (durability 10) is diggable, brick (14) is not
        walk = walk_area(c.grid, mats, (30, 55), dug)
        assert bool(walk[55, 70]) is joined
        assert not walk_area(np.full((20, 20), 15, dtype=np.uint8), mats, (5, 5)).any()


# ----------------------------------------------------------------- generated worlds


def test_every_world_hands_out_every_ingredient(world_a, world_b, bm, mats):
    cfg = bm.scenes["alchemy"]
    for w in (world_a, world_b):
        stats = w.meta["checks"]["alchemy"]
        assert set(stats["ingredient_cells"]) == set(mats.with_tag("ingredient"))
        assert min(stats["ingredient_cells"].values()) >= cfg["min_cells"]
        full = {m["contents"] for m in w.markers if m.get("item") == "bottle" and m.get("contents")}
        assert set(mats.with_tag("ingredient")) <= full
        assert stats["empty_bottles"]["early"] >= cfg["early_empty_bottles"]
        assert stats["empty_bottles"]["reachable"] >= cfg["min_empty_bottles"]
        assert stats["bowls"] == {"rest": 2, "cave": 3} and stats["recipes"] == 8


def test_the_deposits_of_the_biome_files_are_all_there(world_a, bm):
    placed: dict[tuple[str, str], list[dict]] = {}
    for d in world_a.meta["deposits"]:
        placed.setdefault((d["biome"], d["material"]), []).append(d)
        assert d["shape"] in ("heap", "basin", "pit") and d["form"] in ("pile", "pool")
    for key, b in bm.biomes.items():
        for spec in b.supply.deposits:
            got = placed.get((key, spec.material), [])
            assert all(d["cells"] >= spec.min_cells for d in got)
            if not spec.optional:
                assert len(got) >= spec.count, f"{key} lacks a deposit of {spec.material}"
    assert world_a.meta["built"]["mine"]["deposits"] >= 3


def test_gold_dust_bone_dust_fungus_powder_and_slime_are_found_in_the_first_two_layers(world_a, bm):
    y_layer_3 = bm.region("rest_2")[3]
    early = {d["material"] for d in world_a.meta["deposits"] if d["y"] < y_layer_3}
    assert {"gold_dust", "bone_dust", "fungus_powder", "slime"} <= early


def test_each_biome_gets_the_cave_bowls_its_file_asks_for(world_a, world_b, bm):
    """The fungal and the oil caverns hold one bowl each (not both in the first of them), the
    mine one: a biome only hands its bowls on to another of its layer when it has no room."""
    for w in (world_a, world_b):
        where: dict[str, int] = {}
        for m in w.markers:
            if m["type"] == "alchemy_bowl" and m["place"] == "cave":
                key = next(
                    k
                    for k in bm.biomes
                    if bm.region(k)[0] <= m["x"] < bm.region(k)[2]
                    and bm.region(k)[1] <= m["y"] < bm.region(k)[3]
                )
                where[key] = where.get(key, 0) + 1
        assert where == {k: b.supply.bowls for k, b in bm.biomes.items() if b.supply.bowls}


def test_no_secret_potion_lies_about(world_a, world_b, mats):
    secret = mats.with_tag("secret_potion")
    for w in (world_a, world_b):
        assert not np.isin(w.grid, [mats[k] for k in secret]).any()
        assert not [m for m in w.markers if m.get("item") in secret or m.get("contents") in secret]


def test_metal_is_only_in_bowls_and_scenes(world_a, bm, mats):
    spec = alchemy.BowlSpec.from_config(bm.scenes["alchemy"]["bowl"])
    metal = world_a.grid == mats["metal"]
    bowls = [m for m in world_a.markers if m["type"] == "alchemy_bowl"]
    assert int(metal.sum()) >= len(bowls) * (spec.outer_w * spec.outer_h - spec.w * spec.h)
    rep = run_checks(world_a, bm, mats)
    assert rep.ok and not [f for f in rep.failures if "metal" in f]


def test_the_terrain_and_the_supplies_do_not_depend_on_the_rule_seed(world_a, bm, mats):
    from noitabench.worldgen import generate_world

    other = generate_world(3, 77)
    assert (other.grid == world_a.grid).all() and other.markers == world_a.markers
    assert other.meta["deposits"] == world_a.meta["deposits"]
    assert run_checks(other, bm, mats).ok and other.rule_seed == 77


def test_every_recipe_of_every_rule_seed_can_be_made_in_the_world(world_a, bm, mats):
    """All twelve ingredients are there, so any three-ingredient recipe is obtainable."""
    for rule_seed in range(40):
        w = dataclasses.replace(world_a, rule_seed=rule_seed)
        rep = run_checks(w, bm, mats, get_rules(rule_seed))
        assert rep.ok, (rule_seed, rep.failures)
        assert rep.stats["alchemy"]["recipes"] == 8


# ---------------------------------------------------------------- the checks bite


def _mutated(world):
    return dataclasses.replace(
        world,
        grid=world.grid.copy(),
        markers=copy.deepcopy(world.markers),
        meta=copy.deepcopy(world.meta),
    )


def _failures(world, bm, mats) -> list[str]:
    return run_checks(world, bm, mats, get_rules(world.rule_seed)).failures


def test_a_missing_bottle_names_the_ingredient_and_the_recipes_that_need_it(world_a, bm, mats):
    w = _mutated(world_a)
    w.markers = [m for m in w.markers if m.get("contents") != "gold_dust"]
    fails = _failures(w, bm, mats)
    assert any("ingredient gold_dust: no full bottle" in f for f in fails)
    needing = [p for p, trio in get_rules(w.rule_seed).recipes() if "gold_dust" in trio]
    assert needing
    for potion in needing:
        assert any(f"recipe {potion} cannot be made" in f and "gold_dust" in f for f in fails)


def test_a_bottle_out_of_reach_does_not_count(world_a, bm, mats):
    w = _mutated(world_a)
    seal = next(m for m in w.markers if m["type"] == "seal")
    inside = (seal["room"]["x"] + seal["room"]["w"] // 2, seal["room"]["y"] + 3)  # the sealed room
    for m in w.markers:
        if m.get("contents") == "slime":
            m["x"], m["y"] = inside
    assert any("ingredient slime: no full bottle" in f for f in _failures(w, bm, mats))


def test_too_few_cells_of_an_ingredient_fail(world_a, bm, mats):
    w = _mutated(world_a)
    w.grid[w.grid == mats["slime"]] = mats["rock"]
    assert any("ingredient slime: only 0 cells" in f for f in _failures(w, bm, mats))


def test_too_few_empty_bottles_fail(world_a, bm, mats):
    w = _mutated(world_a)
    w.markers = [m for m in w.markers if not (m.get("item") == "bottle" and not m.get("contents"))]
    fails = _failures(w, bm, mats)
    assert any("empty bottles the player can walk to up to the first rest area" in f for f in fails)
    assert any("empty bottles the player can walk to (need" in f for f in fails)


def test_a_damaged_or_blocked_bowl_fails(world_a, bm, mats):
    cave = next(m for m in world_a.markers if m["type"] == "alchemy_bowl" and m["place"] == "cave")
    w = _mutated(world_a)
    w.grid[cave["y"] + 4, cave["x"] - 1] = mats["rock"]  # a hole in a wall
    assert any("a wall or the bottom is not metal" in f for f in _failures(w, bm, mats))
    w = _mutated(world_a)
    w.grid[cave["y"] + 9, cave["x"] + 5] = mats["sand"]  # sand in the bowl
    assert any("interior is not empty" in f for f in _failures(w, bm, mats))
    w = _mutated(world_a)
    lid = (cave["x"] - 6, cave["y"] - 9, cave["x"] + 26, cave["y"])
    w.grid[lid[1] : lid[3], lid[0] : lid[2]] = mats["brick"]  # a lid
    w.markers = [  # nothing may stand in the bricks, or the marker check stops the run first
        m
        for m in w.markers
        if not (
            m["type"] in ("item", "spawn_enemy")
            and lid[0] <= m["x"] < lid[2]
            and lid[1] <= m["y"] < lid[3]
        )
    ]
    assert any("cannot stand on its rim" in f for f in _failures(w, bm, mats))


def test_a_hall_needs_exactly_one_bowl_and_caves_the_asked_number(world_a, bm, mats):
    w = _mutated(world_a)
    rest = next(m for m in w.markers if m["type"] == "alchemy_bowl" and m["place"] == "rest")
    w.markers.append(dict(rest))
    assert any("each rest area needs exactly one alchemy bowl" in f for f in _failures(w, bm, mats))
    w = _mutated(world_a)
    cave = [m for m in w.markers if m["type"] == "alchemy_bowl" and m["place"] == "cave"]
    w.markers.remove(cave[0])
    assert any("only 2 alchemy bowls in caves" in f for f in _failures(w, bm, mats))


def test_metal_outside_the_bowls_and_a_potion_in_the_world_fail(world_a, bm, mats):
    w = _mutated(world_a)
    w.grid[400, 5] = mats["metal"]
    assert any("metal cells outside the bowls and the scenes" in f for f in _failures(w, bm, mats))
    w = _mutated(world_a)
    ys, xs = np.nonzero(w.grid == mats["water"])
    w.grid[ys[0], xs[0]] = mats["potion_crit"]
    assert any("secret potions lie about" in f for f in _failures(w, bm, mats))
    w = _mutated(world_a)
    w.markers.append(
        {"type": "item", "x": 10, "y": 10, "item": "bottle", "contents": "potion_crit"}
    )
    assert any("secret potions lie about" in f for f in _failures(w, bm, mats))


# --------------------------------------------------------------------- in the game


def _game(world, mats, tmp_path, rule_seed=None) -> Game:
    """The world in the game, without its own player (the test puts one on a bowl)."""
    bare = dataclasses.replace(
        world, markers=[m for m in world.markers if m["type"] != "spawn_player"]
    )
    png, js = bare.write(tmp_path, "w", mats)
    return Game.from_world(png, js, world.seed, rule_seed=rule_seed)


def test_a_generated_world_rests_when_the_game_starts(world_a, mats, tmp_path):
    game = _game(world_a, mats, tmp_path)
    before = np.frombuffer(game.grid(), dtype=np.uint8).copy()
    game.step(90)
    assert (np.frombuffer(game.grid(), dtype=np.uint8) == before).all()  # no pool ran, no heap slid


@pytest.mark.parametrize("place", ["rest", "cave"])
def test_a_potion_is_made_in_a_bowl_of_the_world(world_a, mats, tmp_path, place):
    """Stand on the rim, pour three ingredients straight down into the bowl: the recipe's potion
    appears inside it (the sunk bowl is what makes ``pour`` land in it)."""
    game = _game(world_a, mats, tmp_path)
    recipe = noitabench_core.recipes(world_a.rule_seed)[0]
    bowl = next(m for m in world_a.markers if m["type"] == "alchemy_bowl" and m["place"] == place)
    rim = bowl["y"]
    game.spawn_player(bowl["x"] - 1, rim - 1)
    game.step(10)
    assert game.player()["on_ground"]
    for material in recipe["inputs"]:
        game.give_bottle(material, 12)  # a small portion mixes best
    for i in range(3):
        game.step(1, {"select_bottle": i})
        game.step(30, {"pour": True, "aim": -90})
        game.step(1, {})
    game.step(300)
    grid = np.frombuffer(game.grid(), dtype=np.uint8).reshape(world_a.grid.shape)
    inside = grid[rim : rim + bowl["h"], bowl["x"] : bowl["x"] + bowl["w"]]
    made = int((inside == mats[recipe["potion"]]).sum())
    assert made >= 6, f"{recipe['potion']}: only {made} cells in the bowl"
    wall = grid[rim : rim + bowl["h"] + 2, bowl["x"] - 2 : bowl["x"]]
    assert (wall == mats["metal"]).all()  # and the bowl is as it was
