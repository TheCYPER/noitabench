"""A small hand-built world for the play-server tests, written as a world file pair.

A flat ground (top at `FLOOR`), the player at `START_X`, a wall of rock, a plank of wood to set
alight, a rest area with an edit station beside it, and a world file that carries the tooling
fields a generated one has (so the tests can check none of them reaches the page).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from noitabench.agent.content import CONTENT
from noitabench.game import Game
from PIL import Image

W, H = 300, 160
FLOOR = 110  # top row of the ground
GROUND = FLOOR - 1  # the row a creature stands in
START_X = 40
WALL_X = 120  # a tall wall of rock, 6 wide
PLANK_X, PLANK_W = 70, 8  # wood lying on the ground: x 70..77, row GROUND
REST = {"x": 10, "y": 70, "w": 60, "h": 40}
SENTINELS = ("E99_SENTINEL", "sentinel_material", "ROOM_SENTINEL")


@dataclass
class Arena:
    png: Path
    json: Path

    def game(self, seed: int = 1) -> Game:
        return Game.from_world(self.png, self.json, seed)


def _materials() -> list[dict[str, Any]]:
    return json.loads((CONTENT / "materials.json").read_text())["materials"]  # type: ignore[no-any-return]


def build_grid() -> np.ndarray:
    idx = {m["key"]: m["index"] for m in _materials()}
    grid = np.zeros((H, W), dtype=np.uint8)
    grid[FLOOR:, :] = idx["rock"]
    grid[:, :4] = idx["rock"]
    grid[:, W - 4 :] = idx["rock"]
    grid[40:FLOOR, WALL_X : WALL_X + 6] = idx["rock"]
    grid[GROUND, PLANK_X : PLANK_X + PLANK_W] = idx["wood"]
    return grid


def markers() -> list[dict[str, Any]]:
    return [
        {"type": "spawn_player", "x": START_X, "y": GROUND},
        {"type": "rest_area", **REST, "index": 1},
        {
            "type": "encounter",
            "encounter_id": "E99_SENTINEL",
            "variant": 1,
            "x": 200,
            "y": GROUND,
            "must_pass": True,
            "placeholder": False,
            "params": {"A": "sentinel_material"},
            "footprint": {"x": 190, "y": 80, "w": 30, "h": 30},
            "trigger": {"x": 190, "y": 80, "w": 30, "h": 30},
        },
        {
            "type": "item",
            "item": "bottle",
            "contents": "water",
            "x": 55,
            "y": GROUND,
            "role": "solvent",
        },
    ]


def write_arena(out: Path, name: str = "arena") -> Arena:
    out.mkdir(parents=True, exist_ok=True)
    palette: list[int] = []
    for m in _materials():
        palette += [int(m["color"][i : i + 2], 16) for i in (1, 3, 5)]
    img = Image.frombytes("P", (W, H), build_grid().tobytes())
    img.putpalette(palette + [0] * (768 - len(palette)))
    png = out / f"{name}.png"
    img.save(png)
    doc = {
        "format": "cogbench-world/0",
        "seed": 7,
        "rule_seed": 5,
        "width": W,
        "height": H,
        "biome_cell_size": 128,
        "biome_map": [["mine"]],
        "markers": markers(),
    }
    js = out / f"{name}.json"
    js.write_text(json.dumps(doc), encoding="utf-8")
    return Arena(png, js)
