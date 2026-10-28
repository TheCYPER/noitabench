"""Small hand-built worlds for the agent-interface tests, written as world file pairs.

`Arena` is a flat ground (top at `FLOOR`) with: a rest area at the left where the player starts,
an edit station at the right, a tall wall, a deep pit, a ledge, a pool of water and a wall of
rock around. The world file carries the markers a generated world has - with all the tooling
fields (`role`, `params`, `regions`, `encounter_id`, `must_pass`, `footprint`, `trigger`,
`placeholder`, `strength`) - so tests can check that none of them reaches an agent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from noitabench.agent.content import CONTENT
from noitabench.game import Game
from PIL import Image

W, H = 420, 220
FLOOR = 160  # top row of the ground
GROUND = FLOOR - 1  # the row a creature stands in
START_X = 30

WALL_X, WALL_W = 150, 6  # rock from the floor up to y = 100
PIT_X, PIT_W, PIT_DEPTH = 250, 12, 30  # a pit in the ground; its bottom is rock
LEDGE_X, LEDGE_W, LEDGE_H = 300, 12, 3  # a step of three rows
POOL_X, POOL_W, POOL_DEPTH = 340, 24, 12  # a basin of water sunk into the ground
REST = {"x": 10, "y": 120, "w": 70, "h": 40}
STATION = {"x": 380, "y": 120, "w": 30, "h": 40}
SENTINELS = ("E99_SENTINEL", "sentinel_material", "ROOM_SENTINEL")


@dataclass
class Arena:
    png: Path
    json: Path
    extra: dict[str, Any] = field(default_factory=dict)

    def game(self, seed: int = 1) -> Game:
        return Game.from_world(self.png, self.json, seed)


def _palette() -> list[int]:
    rows = json.loads((CONTENT / "materials.json").read_text())["materials"]
    palette: list[int] = []
    for r in rows:
        palette += [int(r["color"][i : i + 2], 16) for i in (1, 3, 5)]
    return palette + [0] * (768 - len(palette))


def _keys() -> dict[str, int]:
    rows = json.loads((CONTENT / "materials.json").read_text())["materials"]
    return {r["key"]: r["index"] for r in rows}


def build_grid() -> np.ndarray:
    idx = _keys()
    grid = np.zeros((H, W), dtype=np.uint8)
    grid[FLOOR:, :] = idx["rock"]
    grid[:, :4] = idx["rock"]
    grid[:, W - 4 :] = idx["rock"]
    grid[100:FLOOR, WALL_X : WALL_X + WALL_W] = idx["rock"]
    grid[FLOOR : FLOOR + PIT_DEPTH, PIT_X : PIT_X + PIT_W] = 0  # the pit (air)
    grid[FLOOR - LEDGE_H : FLOOR, LEDGE_X : LEDGE_X + LEDGE_W] = idx["ground"]
    grid[FLOOR : FLOOR + POOL_DEPTH, POOL_X : POOL_X + POOL_W] = idx["water"]
    return grid


def markers(spawn_x: int = START_X) -> list[dict[str, Any]]:
    return [
        {"type": "spawn_player", "x": spawn_x, "y": GROUND},
        {"type": "rest_area", **REST, "index": 1},
        {"type": "edit_station", **STATION},
        {
            "type": "encounter",
            "encounter_id": "E99_SENTINEL",
            "variant": 3,
            "x": 200,
            "y": GROUND,
            "must_pass": True,
            "placeholder": False,
            "layer": 1,
            "biome": "mine",
            "mirror": False,
            "params": {"A": "sentinel_material"},
            "footprint": {"x": 190, "y": 130, "w": 30, "h": 30},
            "regions": {"plug": {"x": 195, "y": 150, "w": 4, "h": 4}},
            "trigger": {"x": 190, "y": 130, "w": 30, "h": 30},
        },
        {
            "type": "seal",
            "x": 100,
            "y": 190,
            "w": 16,
            "h": 6,
            "room": {"x": 90, "y": 196, "w": 30, "h": 10, "note": "ROOM_SENTINEL"},
        },
        {
            "type": "item",
            "item": "spell",
            "spell": "BOMB",
            "x": 45,
            "y": GROUND,
            "role": "breaker",
            "encounter_id": "E99_SENTINEL",
        },
        {
            "type": "item",
            "item": "bottle",
            "contents": "water",
            "x": 55,
            "y": GROUND,
            "role": "solvent",
            "encounter_id": "E99_SENTINEL",
        },
    ]


def write_arena(
    out: Path,
    *,
    edit: Any = None,
    extra_markers: list[dict[str, Any]] | None = None,
    base_markers: list[dict[str, Any]] | None = None,
    spawn_x: int = START_X,
    name: str = "arena",
) -> Arena:
    """Write the arena (`edit(grid, keys)` may change the grid first); the player starts at
    column `spawn_x`."""
    out.mkdir(parents=True, exist_ok=True)
    grid = build_grid()
    if edit is not None:
        edit(grid, _keys())
    img = Image.frombytes("P", (W, H), grid.tobytes())
    img.putpalette(_palette())
    png = out / f"{name}.png"
    img.save(png)
    doc = {
        "format": "cogbench-world/0",
        "seed": 7,
        "rule_seed": 5,
        "strength": 0,
        "width": W,
        "height": H,
        "biome_cell_size": 128,
        "biome_map": [["mine"]],
        "markers": (markers(spawn_x) if base_markers is None else base_markers)
        + (extra_markers or []),
    }
    js = out / f"{name}.json"
    js.write_text(json.dumps(doc), encoding="utf-8")
    return Arena(png, js)


def settle(game: Game, frames: int = 61) -> None:
    """Let the player land and the opening invincibility end; forget the events so far."""
    game.step(frames)
    game.events()
