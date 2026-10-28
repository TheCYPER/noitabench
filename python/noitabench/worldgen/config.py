"""Content loading and validation for the world generator.

Reads ``content/materials.json`` (``materials.py``), ``content/biome_map.json`` and
``content/biomes/<key>.json`` (``biomes.py``). Everything is validated up front and fails with
a ``ValueError`` that names the file and the field (error-handling spec). This module also
re-exports the content types so the rest of the package imports them from one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .biomes import (
    Biome,
    BottleSpec,
    DepositSpec,
    EncounterStyle,
    FeatureStyle,
    FillEntry,
    FillStyle,
    MarkerStyle,
    Rate,
    RoomsStyle,
    ShapeStyle,
    SupplyStyle,
    TileStyle,
    VeinStyle,
    Weighted,
    parse_biome,
)
from .bowls import BowlSpec, hall_spans, span_room
from .contentio import CONTENT_DIR, REPO_ROOT, need, parse_section, read_json
from .encounters import ENCOUNTER_NODE
from .materials import KIND_CODES, Materials, load_materials

__all__ = [
    "CONTENT_DIR",
    "KIND_CODES",
    "REPO_ROOT",
    "SCENE_KEYS",
    "Biome",
    "BiomeMap",
    "BottleSpec",
    "DepositSpec",
    "EncounterStyle",
    "FeatureStyle",
    "FillEntry",
    "FillStyle",
    "Layer",
    "MarkerStyle",
    "Materials",
    "Rate",
    "RoomsStyle",
    "ShapeStyle",
    "SupplyStyle",
    "TileStyle",
    "VeinStyle",
    "Weighted",
    "load_biome_map",
    "load_materials",
]

FORMAT = "cogbench-biome-map/0"
SCENE_KEYS = ("start", "rest_1", "rest_2", "seal")

# required fields of ``scenes`` in biome_map.json: section -> field names
SCENE_FIELDS: dict[str, tuple[str, ...]] = {
    "start": ("row", "ground_level", "spawn_x", "shaft_x"),
    "rest": ("rows", "hall", "wall", "slots", "gate_x"),
    "seal": ("row", "encounter_id", "gate_x", "top", "room"),
    "bands": ("wall", "wave", "margin", "seam", "chamber_w", "chamber_h"),
    "alchemy": (
        "bowl",
        "reach",
        "min_cells",
        "start_bottles",
        "rest_bottles",
        "early_empty_bottles",
        "min_empty_bottles",
    ),
}
SCENE_SUBFIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("rest", "hall"): ("x", "top", "h", "pool_w"),
    ("seal", "room"): ("w", "h", "wall"),
    ("alchemy", "bowl"): ("w", "h", "wall"),
}


@dataclass(frozen=True)
class Layer:
    layer: int
    row0: int
    row1: int
    left: str
    mid: str
    right: str
    must_pass: tuple[str, ...]
    last: str | None = None  # the must-pass scene that is always the deepest of the layer


@dataclass(frozen=True)
class BiomeMap:
    cell_size: int
    cols: int
    rows: int
    ring: int
    border: int
    cells: tuple[tuple[str, ...], ...]
    layers: tuple[Layer, ...]
    scenes: dict
    biomes: dict[str, Biome]

    @property
    def width(self) -> int:
        return self.cols * self.cell_size

    @property
    def height(self) -> int:
        return self.rows * self.cell_size

    def region(self, key: str) -> tuple[int, int, int, int]:
        """Pixel rectangle ``(x0, y0, x1, y1)`` covered by ``key`` in the map."""
        cs = self.cell_size
        rs = [r for r, row in enumerate(self.cells) if key in row]
        if not rs:
            raise ValueError(f"biome_map.json: field 'cells' never uses '{key}'")
        cols = [c for r in rs for c, k in enumerate(self.cells[r]) if k == key]
        return min(cols) * cs, min(rs) * cs, (max(cols) + 1) * cs, (max(rs) + 1) * cs

    def grid_keys(self) -> list[list[str]]:
        return [list(r) for r in self.cells]


def _parse_layer(d: dict, path: Path) -> Layer:
    rows = d["rows"]
    need(len(rows) == 2 and rows[0] <= rows[1], path, "layers.rows", "must be [first, last]")
    need(len(d["must_pass"]) >= 2, path, "layers.must_pass", "needs at least 2 encounter ids")
    unknown = [i for i in d["must_pass"] if i not in ENCOUNTER_NODE]
    need(not unknown, path, "layers.must_pass", f"has unknown encounter ids {unknown}")
    last = d.get("last")
    need(
        last is None or last in d["must_pass"],
        path,
        "layers.last",
        f"must be one of the layer's must_pass ids {d['must_pass']}, not {last!r}",
    )
    return Layer(
        int(d["layer"]),
        rows[0],
        rows[1],
        d["left"],
        d["mid"],
        d["right"],
        tuple(d["must_pass"]),
        last,
    )


@lru_cache(maxsize=4)
def load_biome_map(content_dir: Path | None = None) -> BiomeMap:
    root = content_dir or CONTENT_DIR
    path = root / "biome_map.json"
    d = read_json(path)
    need(d.get("format") == FORMAT, path, "format", f"must be {FORMAT}")
    bm = parse_section(_parse_map, d, path, root)
    parse_section(_validate_map, bm, path)
    return bm


def _parse_map(d: dict, path: Path, root: Path) -> BiomeMap:
    cols, rows, cs = int(d["cols"]), int(d["rows"]), int(d["cell_size"])
    cells = tuple(tuple(r) for r in d["cells"])
    need(len(cells) == rows and all(len(r) == cols for r in cells), path, "cells", "size mismatch")
    mats = load_materials(root / "materials.json")
    keys = sorted({k for r in cells for k in r} - set(SCENE_KEYS))
    biomes = {}
    for k in keys:
        bpath = root / "biomes" / f"{k}.json"
        biomes[k] = parse_biome(read_json(bpath), bpath, mats)
    layers = tuple(_parse_layer(lay, path) for lay in d["layers"])
    return BiomeMap(
        cs, cols, rows, int(d["ring"]), int(d["border"]), cells, layers, d["scenes"], biomes
    )


def _validate_map(bm: BiomeMap, path: Path) -> None:
    """Regions are rectangles, layers match the cells, scenes are complete and consistent."""
    _validate_regions(bm, path)
    for lay in bm.layers:
        for side, k in (("left", lay.left), ("mid", lay.mid), ("right", lay.right)):
            need(k in bm.biomes, path, "layers", f"unknown biome '{k}'")
            b = bm.biomes[k]
            need(
                (b.slot, b.layer) == (side, lay.layer),
                path,
                "layers",
                f"biome '{k}' says slot={b.slot} layer={b.layer}, the map uses it as "
                f"{side} of layer {lay.layer}",
            )
        for r in range(lay.row0, lay.row1 + 1):
            need(
                bm.cells[r][0] == lay.left
                and bm.cells[r][2] == lay.mid
                and bm.cells[r][4] == lay.right,
                path,
                "layers",
                f"layer {lay.layer} does not match the cells of row {r}",
            )
    _validate_scenes(bm, path)


def _validate_regions(bm: BiomeMap, path: Path) -> None:
    cs = bm.cell_size
    for key in [*bm.biomes, *SCENE_KEYS]:
        x0, y0, x1, y1 = bm.region(key)
        for r in range(y0 // cs, y1 // cs):
            for c in range(x0 // cs, x1 // cs):
                need(bm.cells[r][c] == key, path, "cells", f"region of '{key}' is not a rectangle")
    for key in SCENE_KEYS:
        x0, _, x1, _ = bm.region(key)
        need((x0, x1) == (0, bm.width), path, "cells", f"'{key}' must span the full width")


def _validate_scenes(bm: BiomeMap, path: Path) -> None:
    sc, cs = bm.scenes, bm.cell_size
    for name, fields in SCENE_FIELDS.items():
        need(isinstance(sc.get(name), dict), path, f"scenes.{name}", "is missing")
        for f in fields:
            need(f in sc[name], path, f"scenes.{name}.{f}", "is missing")
    for (name, sub), fields in SCENE_SUBFIELDS.items():
        for f in fields:
            need(f in sc[name][sub], path, f"scenes.{name}.{sub}.{f}", "is missing")
    need(isinstance(sc.get("gate_w"), int), path, "scenes.gate_w", "must be an integer")
    seam, top = sc["bands"]["seam"], min(sc["bands"]["wall"], bm.ring)
    need(
        isinstance(seam, int) and 2 <= seam <= top,
        path,
        "scenes.bands.seam",
        f"must be an integer from 2 to {top} (the band wall and the ring of a region): the "
        "thickness of the brick seams and of the shells of the side biomes",
    )
    rows = {
        "start": sc["start"]["row"],
        "rest_1": sc["rest"]["rows"][0],
        "rest_2": sc["rest"]["rows"][1],
        "seal": sc["seal"]["row"],
    }
    for key, row in rows.items():
        need(
            bm.region(key)[1] == row * cs,
            path,
            f"scenes.{key}.row",
            f"({row}) does not match the rows of '{key}' in cells",
        )
    ranges = {
        "start.shaft_x": sc["start"]["shaft_x"],
        "start.spawn_x": sc["start"]["spawn_x"],
        "rest.gate_x": sc["rest"]["gate_x"],
        "seal.gate_x": sc["seal"]["gate_x"],
    }
    for name, rng in ranges.items():
        ok = len(rng) == 2 and 0 < rng[0] <= rng[1] < bm.width
        need(ok, path, f"scenes.{name}", f"must be [min, max] inside the world width {bm.width}")
    _validate_rest_hall(bm, path)
    _validate_alchemy(bm, path)
    ids = [s["encounter_id"] for s in sc["rest"]["slots"]] + [sc["seal"]["encounter_id"]]
    unknown = [i for i in ids if i not in ENCOUNTER_NODE]
    need(not unknown, path, "scenes", f"has unknown encounter ids {unknown}")


def _validate_rest_hall(bm: BiomeMap, path: Path) -> None:
    """The small rest hall holds both slots, the shafts end in it, and it fits its band."""
    rest = bm.scenes["rest"]
    hall = rest["hall"]
    hx0, hx1 = hall["x"]
    need(0 < hx0 < hx1 < bm.width, path, "scenes.rest.hall.x", "must lie inside the world")
    need(
        hx0 + 6 <= rest["gate_x"][0] and rest["gate_x"][1] <= hx1 - 6,
        path,
        "scenes.rest.hall.x",
        "must contain the whole of rest.gate_x",
    )
    slots = rest["slots"]
    need(
        sum(s["w"] for s in slots) + 40 <= hx1 - hx0 - hall["pool_w"],
        path,
        "scenes.rest.hall",
        "is too narrow for the encounter slots and the pool",
    )
    need(
        hall["h"] >= max(s["h"] for s in slots) + 16,
        path,
        "scenes.rest.hall.h",
        "is too low for the encounter slots",
    )
    need(
        hall["top"] > rest["wall"] + 8
        and hall["top"] + hall["h"] + rest["wall"] + 6 + 8 <= bm.cell_size,
        path,
        "scenes.rest.hall.top",
        "leaves no room for the wall, the pool or the rock around the hall in its band",
    )


def _validate_alchemy(bm: BiomeMap, path: Path) -> None:
    """The bowls fit their rest halls, and the supply thresholds make sense."""
    cfg = bm.scenes["alchemy"]
    spec = BowlSpec.from_config(cfg["bowl"])
    need(
        spec.w >= 12 and spec.h >= 6 and spec.wall >= 2,
        path,
        "scenes.alchemy.bowl",
        "must be at least 12 wide and 6 deep with walls of at least 2 (a bowl holds a bottle)",
    )
    for name in ("reach", "min_cells", "start_bottles", "rest_bottles"):
        need(
            isinstance(cfg[name], int) and cfg[name] >= 1,
            path,
            f"scenes.alchemy.{name}",
            "must be a positive integer",
        )
    need(
        cfg["early_empty_bottles"] <= cfg["min_empty_bottles"],
        path,
        "scenes.alchemy.early_empty_bottles",
        "must not exceed min_empty_bottles (the early ones are among all of them)",
    )
    spans = hall_spans(bm.scenes["rest"])
    for name, (lo, hi) in zip(("left", "right"), spans):
        need(
            hi - lo >= span_room(spec),
            path,
            "scenes.rest.hall.x",
            f"leaves only {hi - lo} free cells on the {name} side of the slots: the bowl, "
            f"its gap to the pillar and its bottles need {span_room(spec)}",
        )
