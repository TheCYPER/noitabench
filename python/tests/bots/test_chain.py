"""E07, the chain, on a small world: take the empty bottle, fill it at the pool from the rim,
crust the river of lava with it on the way to the exit."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from mini_world import write_world
from noitabench.bots.bottles import bottle_parts, bottle_total, empty_bottle, holding
from noitabench.bots.chain import fill_spot, pool_liquid
from noitabench.bots.descend import Descent
from noitabench.bots.scenes import Scene
from noitabench.bots.seal import Rect
from noitabench.bots.terrain import Body, Materials, analyse

BODY = Body.load()
POOL = Rect(30, 70, 14, 10)  # a pit in the floor of the corridor, as big as E07's pool
FOOTPRINT = {"x": 10, "y": 30, "w": 76, "h": 63}
SCENE_MARKER = {
    "type": "encounter",
    "encounter_id": "E07",
    "x": 20,
    "y": 60,
    "placeholder": False,
    "must_pass": True,
    "layer": 2,
    "variant": 0,
    "mirror": False,
    "footprint": FOOTPRINT,
    "regions": {"pool": {"x": POOL.x, "y": POOL.y, "w": POOL.w, "h": POOL.h}},
}
RIVER = (60, 72)  # x range of the lava in the floor row of the corridor, as long as E07's
BOTTLE = {"type": "item", "item": "bottle", "role": "container", "x": 22, "y": 69}


def chain_world(tmp_path: Path, mats: Materials, liquid: str = "water", **kw: object) -> Descent:
    """The river of lava of the mini world with a pool before it and a shaft after it."""

    def edit(grid: np.ndarray, idx: dict[str, int]) -> None:
        grid[30:70, 55:64] = idx["air"]  # no wall of ground: the corridor runs on
        grid[30:62, 56:76] = idx["rock"]  # a roof over the river: the passage is 8 rows high
        grid[70, RIVER[0] : RIVER[1]] = idx["lava"]
        grid[POOL.y : POOL.bottom, POOL.x : POOL.x + POOL.w] = idx[liquid]
        grid[70:101, 78:84] = idx["air"]  # the exit: a shaft with a floor at y = 101

    files = write_world(tmp_path, mats, items=[SCENE_MARKER, BOTTLE], edit=edit)
    return Descent(files, enemies=False, max_frames=6000, **kw)  # type: ignore[arg-type]


def events(bot: Descent) -> list[str]:
    return [e["event"] for e in bot.log]


def test_the_bot_fills_the_bottle_at_the_pool_and_crusts_the_lava_with_it(
    tmp_path: Path, mats: Materials
) -> None:
    bot = chain_world(tmp_path, mats)
    (scene,) = bot.scenes
    assert pool_liquid(bot.game.grid_array(), mats, scene) == "water"
    bot.solve_chain(scene)
    order = ["chain_start", "picked_up", "filled", "pour", "crossing_clear", "chain_lava"]
    assert list(dict.fromkeys(e for e in events(bot) if e in order)) == order  # (pours repeat)
    chain = next(e for e in bot.log if e["event"] == "chain_lava")
    assert chain["cleared"] is True
    grid = bot.game.grid_array()
    assert (grid[60:72, 58:74] == mats.index("lava")).sum() <= 2  # (a cell may be left)
    assert bot._p["x"] >= 76 and bot._p["y"] > 70  # beyond the river, down the shaft
    assert bot._p["hp"] >= 90.0 and not bot._p["dead"]  # (the crust leaves a little lava below)


def test_the_fill_is_taken_from_the_rim_with_the_hit_box_out_of_the_liquid(
    tmp_path: Path, mats: Materials
) -> None:
    """A pool of sludge poisons whoever wades in it: the bottle is filled without that."""
    bot = chain_world(tmp_path, mats, liquid="toxic_sludge")
    (scene,) = bot.scenes
    bottle = bot.container_bottle(scene)
    assert bottle is not None and bot.fetch_entity(bottle, label="container") == "fetched"
    seen: set[str] = set()
    step = bot.step

    def watch(controls: dict) -> dict:
        p = step(controls)
        seen.update(p["statuses"])
        return p

    bot.step = watch  # type: ignore[method-assign]
    assert bot.fill_up(scene, "toxic_sludge")
    filled = next(e for e in bot.log if e["event"] == "filled")
    assert filled["rim"] is True and filled["cells"] >= 40 and filled["material"] == "toxic_sludge"
    assert "poisoned" not in seen and bot._p["hp"] == 100.0
    assert bottle_total(bot._p["bottles"][-1]) == filled["cells"]
    assert [e for e in events(bot) if e == "filled"] == ["filled"]  # one fill was enough


def test_the_container_is_the_one_inside_the_footprint(tmp_path: Path, mats: Materials) -> None:
    """The world may hold another E07 (an optional one) with its own container."""
    far = BOTTLE | {"x": 95, "y": 69, "encounter_id": "E07"}  # beyond the footprint
    files = write_world(tmp_path, mats, items=[SCENE_MARKER, far, BOTTLE])
    bot = Descent(files, enemies=False, max_frames=3000)
    found = bot.container_bottle(bot.scenes[0])
    assert found is not None and abs(found["x"] - BOTTLE["x"]) <= 6
    assert found["detail"] in ("", None)


def test_without_a_container_the_chain_is_left_alone(tmp_path: Path, mats: Materials) -> None:
    files = write_world(tmp_path, mats, items=[SCENE_MARKER])
    bot = Descent(files, enemies=False, max_frames=3000)
    bot.solve_chain(bot.scenes[0])
    assert "picked_up" not in events(bot) and "filled" not in events(bot)
    assert bot.frames == 0


# -- where the scoop reaches --------------------------------------------------------------------


def pit(mats: Materials, other: str | None = None) -> tuple[np.ndarray, Scene]:
    """A flat floor at row 30 with a pit of water at x 30..44 (12 deep); `other` puts another
    liquid in a pit at x 52..58."""
    grid = np.full((60, 90), mats.index("rock"), dtype=np.uint8)
    grid[10:30, 4:86] = mats.index("air")
    grid[30:42, 30:45] = mats.index("water")
    if other:
        grid[30:42, 52:59] = mats.index(other)
    pool = Rect(30, 30, 15, 12)
    return grid, Scene("E07", 2, 0, False, Rect(4, 10, 82, 40), {"pool": pool}, True)


def test_the_best_place_is_on_the_rim_out_of_the_water(mats: Materials) -> None:
    grid, scene = pit(mats)
    t = analyse(grid, mats, BODY, dig_max_durability=10)
    x, y = fill_spot(grid, mats, t, scene, "water")  # type: ignore[misc]
    assert y + BODY.h == 30  # on the floor, not in the pit
    assert x + BODY.w <= 30 or x >= 46  # the hit box (x-1 .. x+4) is clear of the pool 30..44
    assert fill_spot(grid, mats, t, scene, "water", dry_only=True) == (x, y)
    wx, _ = fill_spot(grid, mats, t, scene, "water", wading=True)  # type: ignore[misc]
    assert 30 <= wx + BODY.w // 2 <= 44  # wading: where the scoop reaches the most, in the pool


def test_a_place_whose_scoop_reaches_another_liquid_is_not_taken(mats: Materials) -> None:
    grid, scene = pit(mats, other="acid")
    t = analyse(grid, mats, BODY, dig_max_durability=10)
    spot = fill_spot(grid, mats, t, scene, "water")
    assert spot is not None
    x, y = spot
    scoop = grid[y + BODY.h - 6 : y + BODY.h + 6, x + 2 - 7 : x + 2 + 7]
    assert not (scoop == mats.index("acid")).any()


def test_a_pool_too_small_for_the_rim_is_filled_wading(mats: Materials) -> None:
    grid, scene = pit(mats)
    grid[30:42, 30:45] = mats.index("rock")
    grid[30:42, 36:37] = mats.index("water")  # a slot one cell wide
    scene = Scene("E07", 2, 0, False, scene.footprint, {"pool": Rect(36, 30, 1, 12)}, True)
    t = analyse(grid, mats, BODY, dig_max_durability=10)
    assert fill_spot(grid, mats, t, scene, "water", dry_only=True) is None
    assert fill_spot(grid, mats, t, scene, "water") is None  # below the minimum either way


# -- bottles --------------------------------------------------------------------------------------


def test_bottle_parts_read_both_shapes() -> None:
    plain = {"material": "water", "amount": 120}
    mixed = {"material": "water", "amount": 150, "contents": {"water": 120, "blood": 30}}
    listed = {"material": "water", "amount": 5, "contents": [{"material": "oil", "amount": 5}]}
    empty = {"material": "none", "amount": 0}
    assert bottle_parts(plain) == {"water": 120}
    assert bottle_parts(mixed) == {"water": 120, "blood": 30} and bottle_total(mixed) == 150
    assert bottle_parts(listed) == {"oil": 5}
    assert bottle_parts(empty) == {} and bottle_total(empty) == 0
    player = {"bottles": [plain, empty, mixed]}
    assert empty_bottle(player) == 1 and holding(player, frozenset({"blood"})) == 2
    assert holding(player, frozenset({"acid"})) is None
    assert empty_bottle({"bottles": [plain]}) is None


def test_the_chain_needs_a_pool() -> None:
    scene = Scene("E07", 2, 0, False, Rect(0, 0, 10, 10), {}, True)
    assert pool_liquid(np.zeros((10, 10), dtype=np.uint8), Materials.load(), scene) is None
