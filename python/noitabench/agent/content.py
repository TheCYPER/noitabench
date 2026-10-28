"""What the agent layer reads from `content/`: materials (names, kinds, colours), spells (the
numbers a wand editor shows) and a few player and bottle numbers from `entities.json`.

Nothing here is hard-coded about a material: a material added to `materials.json` shows up in the
legend, the map and the screenshot without a code change.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
CONTENT = REPO / "content"

KIND_ORDER = ("air", "gas", "fire", "liquid", "powder", "static")


@dataclass(frozen=True)
class Content:
    material_keys: tuple[str, ...]
    material_kinds: tuple[str, ...]
    material_colors: tuple[tuple[int, int, int], ...]
    spells: Mapping[str, Mapping[str, Any]]
    spell_order: tuple[str, ...]
    player_w: int
    player_h: int
    hand: tuple[int, int]
    accel_ground: float
    accel_air: float
    pickup_radius: float
    bottle_capacity: int
    drink_rate: int
    pour_rate: int
    fill_rate: int

    @classmethod
    def load(cls, directory: Path | str | None = None) -> Content:
        base = Path(directory) if directory is not None else CONTENT
        materials = _read(base / "materials.json")["materials"]
        spells = _read(base / "spells.json")["spells"]
        ent = _read(base / "entities.json")
        player, bottle = ent["player"], ent["items"]["bottle"]
        return cls(
            material_keys=tuple(m["key"] for m in materials),
            material_kinds=tuple(m["kind"] for m in materials),
            material_colors=tuple(_rgb(m["color"]) for m in materials),
            spells={s["key"]: s for s in spells},
            spell_order=tuple(s["key"] for s in spells),
            player_w=int(player["collision"]["w"]),
            player_h=int(player["collision"]["h"]),
            hand=(int(player["hand"]["dx"]), int(player["hand"]["dy"])),
            accel_ground=float(player["accel_ground"]),
            accel_air=float(player["accel_air"]),
            pickup_radius=float(player["pickup_radius"]),
            bottle_capacity=int(bottle["capacity"]),
            drink_rate=int(bottle["drink_cells_per_frame"]),
            pour_rate=int(bottle["pour_cells_per_frame"]),
            fill_rate=int(bottle["fill_cells_per_frame"]),
        )

    def material_index(self, key: str) -> int:
        return self.material_keys.index(key)

    def spell_cost(self, key: str) -> float:
        """Mana a spell takes (negative: it adds mana); 0 for a key the content does not know."""
        row = self.spells.get(key)
        return float(row["mana"]) if row else 0.0


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError) as err:
        raise ValueError(f"{path}: cannot read content file ({err})") from err


def _rgb(text: str) -> tuple[int, int, int]:
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
