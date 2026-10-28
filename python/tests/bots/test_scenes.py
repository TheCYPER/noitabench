"""The must-pass scenes of a world file, the no-tunnel mask over them and the log of the bot
going through them."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from noitabench.bots.scenes import (
    Scene,
    SceneTracker,
    dig_zones,
    door_of,
    exit_spot,
    no_dig_mask,
    read_scenes,
)
from noitabench.bots.seal import Rect
from noitabench.bots.terrain import Body, Materials, analyse

BODY = Body.load()


def marker(eid: str, x: int, y: int, **extra: object) -> dict:
    base = {
        "type": "encounter",
        "encounter_id": eid,
        "x": x + 10,
        "y": y + 10,
        "placeholder": False,
        "must_pass": True,
        "layer": 1,
        "variant": 0,
        "mirror": False,
        "footprint": {"x": x, "y": y, "w": 40, "h": 30},
        "regions": {"pool": {"x": x + 5, "y": y + 20, "w": 10, "h": 5}},
    }
    return base | extra


def scene(eid: str = "E16", x: int = 20, y: int = 40, dig: bool = False) -> Scene:
    return Scene(
        eid=eid,
        layer=1,
        variant=0,
        mirror=False,
        footprint=Rect(x, y, 40, 30),
        regions={},
        must_pass=True,
        dig_zone=dig,
    )


def test_the_definitions_say_which_scenes_are_dig_zones() -> None:
    found = dig_zones()
    assert {"E08", "E12"} <= found
    assert not found & {"E02", "E07", "E16", "E22", "E23", "E06"}


def test_read_scenes_keeps_the_placed_must_pass_scenes_shallowest_first() -> None:
    markers = [
        marker("E02", 100, 300),
        marker("E16", 20, 40),
        marker("E09", 5, 5, placeholder=True),  # no scene: a bare chamber
        marker("E07", 60, 100, must_pass=False),  # optional
        {"type": "rest_area", "x": 0, "y": 0, "w": 1, "h": 1},
    ]
    scenes = read_scenes(markers)
    assert [s.eid for s in scenes] == ["E16", "E02"]
    assert scenes[0].footprint == Rect(20, 40, 40, 30)
    assert scenes[0].regions["pool"] == Rect(25, 60, 10, 5)
    assert [s.eid for s in read_scenes(markers, must_pass=False)] == ["E16", "E07", "E02"]
    assert read_scenes(markers, digging={"E16"})[0].dig_zone is True


def test_the_mask_covers_boxes_that_touch_a_footprint_of_a_scene_without_digging() -> None:
    mask = no_dig_mask((100, 100), [scene("E16"), scene("E12", 20, 40, dig=True)], (4, 7))
    # the footprint is x 20..59, y 40..69; a box overlaps it from x = 17 and y = 34
    assert mask[34, 17] and mask[69, 59] and not mask[33, 17] and not mask[70, 59]
    assert not mask[34, 16] and not mask[69, 60]
    only_dig = no_dig_mask((100, 100), [scene("E12", dig=True)], (4, 7))
    assert not only_dig.any()  # a dig zone is dug through


def test_the_tracker_follows_a_player_from_the_top_to_below_the_footprint() -> None:
    s = scene()
    t = SceneTracker([s])
    player = {"x": 38, "y": 30, "w": 4, "h": 7, "hp": 100.0, "dead": False}
    t.update(1, player)  # above the scene
    assert t.visits[0].entered is None and t.missed() == ["E16"]
    player |= {"y": 45, "hp": 90.0}
    t.update(5, player)
    t.note_dig(player)
    player |= {"y": 60, "hp": 80.0}
    t.update(9, player)
    assert t.visits[0].entered == 5 and t.visits[0].passed is None
    player |= {"y": 75}  # the centre is below the footprint
    t.update(12, player)
    v = t.visits[0]
    assert v.passed == 12 and v.hp_in == 90.0 and v.hp_min == 80.0 and v.dig_frames == 1
    assert t.passed == [v] and t.missed() == [] and not v.died
    t.update(20, player | {"hp": 1.0})  # nothing changes after the scene is passed
    assert v.hp_min == 80.0


def test_a_player_who_comes_in_from_the_side_or_below_has_not_passed_the_scene() -> None:
    """Passing means in from above and out below: a side door or a tunnel from under the
    footprint is a way round, however the player leaves."""
    box = {"w": 4, "h": 7, "hp": 100.0, "dead": False}
    side = SceneTracker([scene()])  # the footprint is x 20..59, y 40..69
    for frame, (x, y) in enumerate([(10, 50), (14, 50), (18, 50), (30, 50), (30, 66), (30, 72)]):
        side.update(frame, {"x": x, "y": y, **box})
    v = side.visits[0]
    assert v.entered == 2 and not v.from_above and v.passed is None and side.missed() == ["E16"]
    below = SceneTracker([scene()])
    for frame, y in enumerate([90, 80, 66, 50, 75]):  # up from under it, then back out below
        below.update(frame, {"x": 38, "y": y, **box})
    assert not below.visits[0].from_above and below.missed() == ["E16"]
    above = SceneTracker([scene()])
    for frame, y in enumerate([30, 34, 50, 66, 75]):
        above.update(frame, {"x": 38, "y": y, **box})
    assert above.visits[0].from_above and above.missed() == []


def test_a_player_who_only_skirts_a_scene_has_not_passed_it() -> None:
    t = SceneTracker([scene()])
    for frame, x in enumerate((5, 10, 15)):  # beside the footprint, going down
        for y in range(30, 90, 10):
            t.update(frame * 10 + y, {"x": x, "y": y, "w": 4, "h": 7, "hp": 100.0, "dead": False})
    assert t.missed() == ["E16"]


@pytest.fixture
def grid(mats: Materials) -> np.ndarray:
    """Rock with a footprint at x 20..59, y 40..69 whose top door is at x 30..35 and bottom door
    at x 44..49, a shaft under the bottom door and a floor 12 rows below it."""
    g = np.full((120, 80), mats.index("rock"), dtype=np.uint8)
    air = mats.index("air")
    g[40:70, 30:36] = air
    g[60:70, 30:50] = air
    g[70:82, 44:50] = air
    g[82, 40:55] = mats.index("ground")
    g[70:82, 44:50] = air
    return g


def test_the_doors_are_the_open_runs_in_the_top_and_bottom_row(
    grid: np.ndarray, mats: Materials
) -> None:
    s = scene()
    assert door_of(grid, mats, s, top=True) == (30, 36)
    assert door_of(grid, mats, s, top=False) == (30, 50)  # the bottom row is open across 20 cells
    grid[69, 30:44] = mats.index("rock")
    assert door_of(grid, mats, s, top=False) == (44, 50)
    grid[69, :] = mats.index("rock")
    assert door_of(grid, mats, s, top=False) is None


def test_the_exit_is_a_standing_place_under_the_bottom_door(
    grid: np.ndarray, mats: Materials
) -> None:
    grid[69, 30:44] = mats.index("rock")
    terrain = analyse(grid, mats, BODY, dig_max_durability=10)
    spot = exit_spot(grid, mats, terrain, scene())
    assert spot is not None
    x, y = spot
    assert 44 <= x <= 46 and y + BODY.h == 82  # on the ground under the shaft
    assert terrain.free[y, x] and terrain.grounded[y, x]
    assert exit_spot(grid, mats, terrain, scene(y=90)) is None


def test_scene_markers_of_a_real_world_file_read_back(tmp_path: Path) -> None:
    doc = {"markers": [marker("E08", 0, 0)]}
    path = tmp_path / "w.json"
    path.write_text(json.dumps(doc))
    (s,) = read_scenes(json.loads(path.read_text())["markers"])
    assert s.dig_zone and s.contains(10, 10) and not s.contains(50, 10)
