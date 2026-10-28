"""Material table of ``content/materials.json`` (contracts section 2): u8 cell values."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from .contentio import CONTENT_DIR, need, read_json

KIND_CODES = {"air": 0, "gas": 1, "fire": 2, "liquid": 3, "powder": 4, "static": 5}


@dataclass(frozen=True)
class Materials:
    """Material table of ``content/materials.json`` (u8 cell values)."""

    keys: tuple[str, ...]
    kinds: tuple[str, ...]
    colors: tuple[str, ...]
    durability: tuple[float, ...]
    hp: tuple[float, ...]
    index: dict[str, int]
    kind_code: np.ndarray = field(compare=False, repr=False)
    density: np.ndarray = field(compare=False, repr=False)  # float32 per material
    tags: tuple[frozenset[str], ...] = ()  # the ``tags`` of every material (contracts section 2)

    def __getitem__(self, key: str) -> int:
        try:
            return self.index[key]
        except KeyError as err:
            raise ValueError(f"unknown material key '{key}'") from err

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def air(self) -> int:
        return self.index["air"]

    def with_tag(self, tag: str) -> tuple[str, ...]:
        """Keys of the materials that carry ``tag`` (``ingredient``, ``secret_potion``, ...)."""
        return tuple(k for k, t in zip(self.keys, self.tags) if tag in t)

    def kind_mask(self, grid: np.ndarray, kind: str) -> np.ndarray:
        """Boolean mask of the cells of ``grid`` whose material has this kind."""
        return self.kind_code[grid] == KIND_CODES[kind]

    def kind_at_least(self, grid: np.ndarray, kind: str) -> np.ndarray:
        """Cells whose kind code is ``kind`` or later in ``KIND_CODES`` (powder, static ...)."""
        return self.kind_code[grid] >= KIND_CODES[kind]

    def palette(self) -> list[int]:
        """Flat 768-entry PNG palette: materials colours, black elsewhere."""
        flat: list[int] = []
        for c in self.colors:
            flat += [int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)]
        flat += [0] * (768 - len(flat))
        return flat


@lru_cache(maxsize=4)
def load_materials(path: Path | None = None) -> Materials:
    path = path or CONTENT_DIR / "materials.json"
    data = read_json(path)
    rows = data.get("materials")
    need(isinstance(rows, list) and bool(rows), path, "materials", "must be a non-empty list")
    need(len(rows) <= 256, path, "materials", "has more than 256 entries (cells are u8)")
    keys, kinds, colors, dur, hp, dens, tags = [], [], [], [], [], [], []
    for i, row in enumerate(rows):
        need(row.get("index") == i, path, f"materials[{i}].index", "must equal its position")
        need(row.get("kind") in KIND_CODES, path, f"materials[{i}].kind", "unknown kind")
        col = row.get("color", "")
        ok = isinstance(col, str) and len(col) == 7 and col[0] == "#"
        if ok:
            try:
                int(col[1:], 16)
            except ValueError:
                ok = False
        need(ok, path, f"materials[{i}].color", "must be #RRGGBB")
        need(isinstance(row.get("key"), str), path, f"materials[{i}].key", "must be a string")
        keys.append(row["key"])
        kinds.append(row["kind"])
        colors.append(col)
        dur.append(float(row.get("durability") or 0))
        hp.append(float(row.get("hp") or 0))
        dens.append(float(row.get("density") or 0))
        tags.append(frozenset(row.get("tags") or ()))
    need(keys[0] == "air", path, "materials[0].key", "index 0 must be air")
    need(len(set(keys)) == len(keys), path, "materials", "has a duplicate key")
    code = np.array([KIND_CODES[k] for k in kinds], dtype=np.uint8)
    index = {k: i for i, k in enumerate(keys)}
    density = np.array(dens, dtype=np.float32)
    return Materials(
        tuple(keys),
        tuple(kinds),
        tuple(colors),
        tuple(dur),
        tuple(hp),
        index,
        code,
        density,
        tuple(tags),
    )
