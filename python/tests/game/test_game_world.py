"""A generated world loaded into a game: markers become entities, the world runs."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parents[2]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from noitabench.game import Game
from noitabench.worldgen import generate_world
from noitabench.worldgen.config import load_materials

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def world_files(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, dict]:
    out = tmp_path_factory.mktemp("world")
    world = generate_world(3)
    png, js = world.write(out, "w", load_materials())
    return Path(png), Path(js), json.loads(Path(js).read_text())


def wand_ids(game: Game) -> list[int]:
    return [e["id"] for e in game.entities() if e["kind"] == "wand"]


def test_every_spawn_marker_becomes_an_entity(world_files) -> None:
    png, js, meta = world_files
    game = Game.from_world(png, js)
    markers = Counter(
        m.get("enemy") or m.get("item") or m["type"]
        for m in meta["markers"]
        if m["type"] in ("spawn_enemy", "item", "spawn_player")
    )
    kinds = Counter(e["kind"] for e in game.entities())
    assert kinds["player"] == 1
    for enemy in ("longleg", "shotgunner", "firemage_weak"):
        assert kinds[enemy] == markers[enemy]
    for barrel in ("barrel_gunpowder", "barrel_acid", "barrel_oil"):
        assert kinds[barrel] == markers[barrel]
    assert kinds["wand"] == markers["wand"] and kinds["spell"] == markers["spell"]
    for potion in ("potion_heal", "potion_mana", "potion_haste"):
        assert kinds[potion] == markers[potion]
    assert kinds["bottle"] == markers["bottle"]
    assert game.width == meta["width"] and game.height == meta["height"] and game.seed == 3


def test_the_player_starts_on_the_ground_with_the_starter_loadout(world_files) -> None:
    png, js, meta = world_files
    game = Game.from_world(png, js)
    p = game.player()
    spawn = next(m for m in meta["markers"] if m["type"] == "spawn_player")
    assert p["y"] + p["h"] == spawn["y"] + 1 and abs(p["x"] + 2 - spawn["x"]) <= 1
    assert [w["slots"][0]["spell"] for w in p["wands"]] == ["LIGHT_BULLET", "DIGGER"]
    game.step(120)
    assert game.player()["on_ground"] and game.player()["hp"] == 100.0


def test_encounters_and_rest_areas_are_kept_for_the_evaluator(world_files) -> None:
    png, js, meta = world_files
    game = Game.from_world(png, js)
    kept = Counter(m["type"] for m in game.markers())
    wanted = Counter(
        m["type"] for m in meta["markers"] if m["type"] in ("encounter", "rest_area", "seal")
    )
    assert all(kept[k] == n for k, n in wanted.items())


def test_the_loaded_world_runs_and_replays(world_files) -> None:
    png, js, _ = world_files
    a, b = Game.from_world(png, js), Game.from_world(png, js)
    for game in (a, b):
        game.step(90, {"move": 1})
        game.step(60, {"fire": True, "aim": -90.0, "select_wand": 1})
    assert a.state_hash() == b.state_hash()
    assert a.player()["y"] > 0
    # a different episode seed gives different loot but the same terrain
    c = Game.from_world(png, js, seed=99)
    assert c.grid() == Game.from_world(png, js).grid()
    assert wand_ids(c) == wand_ids(a)


def test_a_reaction_table_can_be_injected(world_files, tmp_path) -> None:
    png, js, _ = world_files
    plain = Game.from_world(png, js)
    # the original table is the table every world runs: injecting it changes nothing
    same = Game.from_world(png, js, reactions_path=REPO / "content" / "reactions.json")
    assert same.content_hash == plain.content_hash
    table = json.loads((REPO / "content" / "reactions.json").read_text(encoding="utf-8"))
    table["reactions"] = table["reactions"][1:]
    custom_path = tmp_path / "reactions.json"
    custom_path.write_text(json.dumps(table), encoding="utf-8")
    custom = Game.from_world(png, js, reactions_path=custom_path)
    assert custom.content_hash != plain.content_hash
    with pytest.raises(ValueError, match="not both"):
        Game.from_world(png, js, reactions_json="{}", reactions_path=REPO / "x")
    with pytest.raises(ValueError):
        Game.from_world(png, js, reactions_json="{}")
    with pytest.raises(FileNotFoundError):
        Game.from_world(png.with_name("nope.png"), js)
