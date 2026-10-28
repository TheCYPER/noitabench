"""The bot edits its wands only where a player may: in a rest area or at an edit station."""

from __future__ import annotations

from pathlib import Path

import pytest
from mini_world import write_world
from noitabench.agent.content import Content
from noitabench.agent.engine import Engine
from noitabench.bots.descend import Descent
from noitabench.bots.editing import EditNotAllowed, ZonedGame, edit_zones, zone_at
from noitabench.bots.terrain import Materials

MARKERS = [
    {"type": "rest_area", "x": 100, "y": 200, "w": 60, "h": 46, "index": 1},
    {"type": "edit_station", "x": 400, "y": 1500, "w": 70, "h": 20},
    {"type": "seal", "x": 0, "y": 0, "w": 1, "h": 1},
    {"type": "spawn_player", "x": 1, "y": 1},
]
BOX = {"w": 4, "h": 7}


def test_the_zones_are_the_rest_areas_and_edit_stations_of_the_world_file() -> None:
    assert edit_zones(MARKERS) == [
        ("rest_area", 100, 200, 60, 46),
        ("edit_station", 400, 1500, 70, 20),
    ]


def test_the_centre_of_the_collision_box_decides() -> None:
    zones = edit_zones(MARKERS)
    inside = {"x": 98, "y": 200, **BOX}  # centre x = 100: on the edge, inside
    assert zone_at(zones, inside) is not None and zone_at(zones, inside)[0] == "rest_area"
    assert zone_at(zones, {"x": 97, "y": 200, **BOX}) is None  # centre x = 99
    assert zone_at(zones, {"x": 100, "y": 242, **BOX}) is not None  # centre y = 245.5 < 246
    assert zone_at(zones, {"x": 100, "y": 243, **BOX}) is None  # centre y = 246.5
    assert zone_at(zones, {"x": 430, "y": 1505, **BOX})[0] == "edit_station"


def test_a_game_without_zones_edits_anywhere_and_one_with_zones_refuses_elsewhere(
    tmp_path: Path, mats: Materials
) -> None:
    files = write_world(tmp_path, mats)
    free = ZonedGame.from_world(files.png, files.json)
    free.edit_wand({"op": "swap", "wand": 0, "a": 0, "b": 1})  # no zones set: no rule
    game = ZonedGame.from_world(files.png, files.json)
    game.zones = edit_zones(MARKERS)
    game.step(70, None)
    with pytest.raises(EditNotAllowed, match="not in a rest area"):
        game.edit_wand({"op": "swap", "wand": 0, "a": 0, "b": 1})
    assert game.edits() == []


def test_the_bot_arms_itself_in_the_first_rest_hall_not_at_the_start(
    tmp_path: Path, mats: Materials
) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=True, max_frames=6000)
    assert not bot.armed and bot.game.edits() == []  # nothing happened at the start
    assert bot.rest(1)
    assert bot.armed and any(e["event"] == "armed" for e in bot.log)
    edits = bot.game.edits()
    assert edits and {zone for _, zone, _ in edits} == {"rest_area"}


def test_a_run_without_enemies_does_not_touch_the_wands_until_the_key(
    tmp_path: Path, mats: Materials
) -> None:
    bot = Descent(write_world(tmp_path, mats), enemies=False, max_frames=6000, seal_fallback=False)
    s = bot.run()
    assert not bot.armed
    assert s.wand_edits == {} or set(s.wand_edits) <= {"rest_area", "edit_station"}


def test_the_bots_rule_is_the_rule_of_the_agent_layer(tmp_path: Path, mats: Materials) -> None:
    """The same boxes and the same test, edge for edge: `ZonedGame` holds the bot to what
    `agent/engine.py` holds an agent to (the centre of the collision box, `x, y` top-left,
    the right and bottom edges outside)."""
    station = {"type": "edit_station", "x": 14, "y": 62, "w": 9, "h": 5}
    files = write_world(tmp_path, mats, items=[station])
    game = ZonedGame.from_world(files.png, files.json)
    engine = Engine(game, Content.load())
    zones = edit_zones(game.markers())
    assert sorted(z[0] for z in zones) == ["edit_station", "rest_area"]
    inside = 0
    for x in range(8, 170):
        for y in range(56, 250):
            p = {"x": x, "y": y, "w": 4, "h": 7}
            agent, bot = engine.edit_zone_at(p), zone_at(zones, p)
            assert agent == (None if bot is None else bot[0]), (x, y)
            inside += bot is not None
    assert inside > 1000  # (the boxes were hit, not just missed alike)
