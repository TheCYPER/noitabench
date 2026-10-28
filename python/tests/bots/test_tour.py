"""The shape of a run: the stops on the way down, the scenes that are not tunnelled through, and
the key items that belong to one scene."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from mini_world import BREAKER, solvent, write_world
from noitabench.bots.descend import Descent
from noitabench.bots.seal import find_seal_keys
from noitabench.bots.terrain import Materials
from noitabench.bots.wands import DIGGER, SPARK, wand_with


def scene_marker(eid: str, x: int, y: int, w: int, h: int, **extra: object) -> dict:
    return {
        "type": "encounter",
        "encounter_id": eid,
        "x": x,
        "y": y,
        "placeholder": False,
        "must_pass": True,
        "layer": 1,
        "variant": 0,
        "mirror": False,
        "footprint": {"x": x, "y": y, "w": w, "h": h},
        "regions": {},
    } | extra


def boxed_in(grid: np.ndarray, idx: dict[str, int]) -> None:
    """Brick over and under the corridor from x 40 to 80, down to the bottom of the world:
    the only way from the west half to the east half leads through x 48..71."""
    grid[0:30, 40:80] = idx["brick"]
    grid[70:, 40:80] = idx["brick"]


def test_the_planner_does_not_tunnel_inside_a_scene_that_is_not_a_dig_zone(
    tmp_path: Path, mats: Materials
) -> None:
    plain = Descent(write_world(tmp_path / "p", mats), enemies=False).terrain_now()
    assert plain.diggable[40, 56]  # the wall of ground can be dug
    scene = Descent(
        write_world(tmp_path / "a", mats, items=[scene_marker("E16", 48, 30, 24, 40)]),
        enemies=False,
    )
    masked = scene.terrain_now()
    assert not masked.diggable[40, 56]  # the wall is in the footprint
    assert (masked.diggable[24:70, 45:72] == masked.free[24:70, 45:72]).all()  # nowhere to dig
    assert masked.diggable[10, 30]  # rock outside it is still dug
    assert masked.free[40, 30] and masked.free[40, 80]  # and the air is as free as before
    dig_zone = Descent(
        write_world(tmp_path / "b", mats, items=[scene_marker("E12", 48, 30, 24, 40)]),
        enemies=False,
    )
    assert dig_zone.terrain_now().diggable[40, 56]  # a dig zone is dug through


def test_the_wall_inside_a_scene_blocks_a_bot_that_may_not_dig(
    tmp_path: Path, mats: Materials
) -> None:
    items = [scene_marker("E16", 48, 30, 24, 40)]
    bot = Descent(write_world(tmp_path / "a", mats, items=items, edit=boxed_in), enemies=False)
    s = bot.run()
    assert not s.reached_seal and s.digs == 0
    assert s.stop_reason == "could not reach the seal" and s.scenes_passed == 0
    # the same scene as a dig zone is dug through
    zone = [scene_marker("E12", 48, 30, 24, 40)]
    bot = Descent(write_world(tmp_path / "b", mats, items=zone, edit=boxed_in), enemies=False)
    s = bot.run()
    assert s.reached_bottom and s.digs >= 1
    # (this corridor is crossed from west to east: entered sideways, so it does not count as
    # passed; the generated worlds' footprints are entered from above, see test_generated_worlds)
    assert s.scenes[0]["entered"] is not None and not s.scenes[0]["from_above"]
    assert s.scenes[0]["dig_frames"] >= 1


def test_dig_frames_count_every_cast_of_the_digging_wand_inside_a_scene(
    tmp_path: Path, mats: Materials
) -> None:
    """The count does not depend on who asks for the cast (the pilot or anything else): a frame
    with the cast key down and the digging bolt in hand is a dig frame, a spark bolt is not."""
    items = [scene_marker("E16", 10, 30, 40, 40)]  # around the spawn
    bot = Descent(write_world(tmp_path, mats, items=items), enemies=False)
    assert bot.pilot is None
    for _ in range(5):
        bot.step({"select_wand": wand_with(bot._p, DIGGER), "fire": True})
    visit = bot.tracker.visits[0]
    assert visit.entered is not None and visit.dig_frames == 5
    bot.step({"select_wand": wand_with(bot._p, SPARK), "fire": True})
    bot.step({"select_wand": wand_with(bot._p, DIGGER)})  # the key is up
    assert visit.dig_frames == 5


def test_the_tour_is_ordered_by_depth(tmp_path: Path, mats: Materials) -> None:
    items = [
        scene_marker("E07", 10, 100, 40, 30),
        BREAKER | {"y": 150},
        BREAKER | {"spell": "EXPLOSIVE_PROJECTILE", "y": 60},
    ]
    bot = Descent(write_world(tmp_path, mats, items=items), enemies=False)
    stops = bot.tour(bot.find_keys())
    labels = [s.label for s in stops]
    assert labels == ["key_EXPLOSIVE_PROJECTILE", "chain", "key_BOMB", "rest_1"]
    assert [s.y for s in stops] == sorted(s.y for s in stops)


def test_the_solvents_of_a_key_are_the_ones_in_its_own_scene(
    tmp_path: Path, mats: Materials
) -> None:
    """Two E02 in a world (an optional one in a side biome): the bottles of the other one are
    not this one's."""
    here = scene_marker("E02", 10, 30, 60, 50)
    other = scene_marker("E02", 10, 120, 60, 50, must_pass=False)
    items = [
        here,
        other,
        BREAKER | {"encounter_id": "E02", "x": 47, "y": 69},
        solvent("blood", 13) | {"encounter_id": "E02", "y": 69},
        solvent("blood", 15) | {"encounter_id": "E02", "y": 69},
        solvent("blood", 40) | {"encounter_id": "E02", "y": 150},  # the other scene's
    ]
    bot = Descent(write_world(tmp_path, mats, items=items), enemies=False)
    (key,) = find_seal_keys(bot.doc["markers"], bot.game.entities())
    found = bot.solvent_items(key)
    assert [m["x"] for m, _ in found] == [13, 15]
