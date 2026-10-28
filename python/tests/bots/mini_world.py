"""A small hand-built world for the bot tests, with every feature the bot handles: a ground
wall to dig, a step too high to hop, a pit with lava, a long shaft and a brick seal over a sealed
room. It is written as a world file pair like the generator's."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from noitabench.bots.descend import WorldFiles
from noitabench.bots.terrain import CONTENT, Materials
from PIL import Image

W, H = 170, 280
SEAL_X, SEAL_TOP, SEAL_W, SEAL_THICK = 122, 240, 16, 10
ROOM = {"x": 100, "y": 250, "w": 60, "h": 22}
SPAWN = (20, 69)


def build_mini_grid(mats: Materials) -> np.ndarray:
    idx = {k: mats.index(k) for k in ("air", "rock", "ground", "lava", "brick", "potion_heal")}
    grid = np.full((H, W), idx["rock"], dtype=np.uint8)

    def carve(x: int, y: int, w: int, h: int, material: str = "air") -> None:
        grid[y : y + h, x : x + w] = idx[material]

    carve(10, 30, 91, 40)  # corridor A: floor at y = 70
    carve(55, 30, 9, 40, "ground")  # a wall of ground across it: dig
    carve(100, 16, 40, 30)  # corridor B: floor at y = 46, a step of 24 up from A
    carve(108, 46, 16, 6)  # a pit in B's floor ...
    carve(108, 48, 16, 4, "lava")  # ... with lava at the bottom
    carve(128, 46, 12, 154)  # the shaft down from B
    carve(100, 200, 60, 40)  # the hall above the seal: floor at y = 240
    carve(104, 240, 12, 4, "potion_heal")  # a healing pool sunk into its floor
    carve(SEAL_X, SEAL_TOP, SEAL_W, SEAL_THICK, "brick")  # the plug
    carve(ROOM["x"], ROOM["y"], ROOM["w"], ROOM["h"])  # the sealed room
    return grid


def write_world(
    out: Path,
    mats: Materials,
    *,
    key_item: dict[str, Any] | None = None,
    enemies: list[dict[str, Any]] | None = None,
    items: list[dict[str, Any]] | None = None,
    edit: Callable[[np.ndarray, dict[str, int]], None] | None = None,
) -> WorldFiles:
    """The mini world as a file pair. `key_item` and `items` are extra item markers, `edit`
    changes the grid (given the material indices by key) before it is written."""
    grid = build_mini_grid(mats)
    if edit is not None:
        edit(grid, {k: mats.index(k) for k in mats.keys})
    out.mkdir(parents=True, exist_ok=True)
    rows = json.loads((CONTENT / "materials.json").read_text())["materials"]
    palette: list[int] = []
    for r in rows:
        palette += [int(r["color"][i : i + 2], 16) for i in (1, 3, 5)]
    palette += [0] * (768 - len(palette))
    img = Image.frombytes("P", (W, H), grid.tobytes())
    img.putpalette(palette)
    png = out / "mini.png"
    img.save(png)
    markers: list[dict[str, Any]] = [
        {"type": "spawn_player", "x": SPAWN[0], "y": SPAWN[1]},
        {
            "type": "seal",
            "x": SEAL_X,
            "y": SEAL_TOP + 1,
            "w": SEAL_W,
            "h": 22,
            "room": dict(ROOM),
        },
        {"type": "rest_area", "x": 100, "y": 200, "w": 60, "h": 46, "index": 1},  # (with the pool)
    ]
    if key_item is not None:
        markers.append(key_item)
    markers += items or []
    markers += enemies or []
    doc = {
        "format": "cogbench-world/0",
        "seed": 5,
        "rule_seed": 0,
        "width": W,
        "height": H,
        "biome_cell_size": 128,
        "biome_map": [["mine"]],
        "markers": markers,
        "meta": {"main_path": [[20, 66], [95, 66], [120, 42], [134, 100], [130, 236]]},
    }
    js = out / "mini.json"
    js.write_text(json.dumps(doc), encoding="utf-8")
    return WorldFiles(png, js)


# -- a river of lava in a low passage (the shape of encounter E02) --------------------------------

RIVER = (28, 44)  # x range of the lava, in the floor row of corridor A (y = 70)
ROOF = (24, 48)  # x range of the rock roof over it, down to row 61: the passage is 8 rows high
BREAKER = {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker", "x": 47, "y": 69}


def solvent(contents: str, x: int) -> dict[str, Any]:
    return {
        "type": "item",
        "item": "bottle",
        "contents": contents,
        "role": "solvent",
        "x": x,
        "y": 69,
    }


def river_items(solvents: str = "blood", decoy: str = "oil") -> list[dict[str, Any]]:
    """Two solvent bottles and a decoy at the start of the passage, the bomb on the far bank."""
    return [
        solvent(solvents, 13),
        solvent(solvents, 15),
        {"type": "item", "item": "bottle", "contents": decoy, "x": 17, "y": 69},
        BREAKER,
    ]


def dig_river(grid: np.ndarray, idx: dict[str, int], *, sealed: bool = False) -> None:
    """A lava trench in the floor row of corridor A under a roof 8 rows above it: a player that
    flies over it keeps the hit box in the lava (the box is 7 tall, the hit box reaches 2 below).
    With `sealed` the passage is walled in with brick, which the digging bolt cannot remove: the
    river is the only way on."""
    grid[30:62, ROOF[0] : ROOF[1]] = idx["rock"]
    grid[70, RIVER[0] : RIVER[1]] = idx["lava"]
    if sealed:
        grid[0:62, ROOF[0] - 3 : ROOF[1] + 3] = idx["brick"]
        grid[71:, ROOF[0] - 3 : ROOF[1] + 3] = idx["brick"]  # all the way down: no tunnel under it


def patched_spells(tmp_path: Path, bonus: int | None) -> Path:
    """A copy of the content's spells where EXPLOSIVE_PROJECTILE adds `bonus` to the durability
    of the explosion it modifies (`None`: no spell has the field, as before the content had it)."""
    data = json.loads((CONTENT / "spells.json").read_text())
    for spell in data["spells"]:
        spell["shot"].pop("explosion_durability", None)
        if bonus is not None and spell["key"] == "EXPLOSIVE_PROJECTILE":
            spell["shot"]["explosion_durability"] = bonus
    path = tmp_path / f"spells_{bonus}.json"
    path.write_text(json.dumps(data))
    return path
