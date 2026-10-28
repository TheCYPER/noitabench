"""What the evaluator reads from the world file pair (contracts section 4).

The evaluation is outside the game: it may read the markers an agent never sees (an encounter's
`footprint`, `trigger`, `regions`, `params`, `role`, `must_pass`; `meta.main_path`, the `seal`
and `rest_area` boxes). Nothing here is shown to an agent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from .geometry import Rect

REPO = Path(__file__).resolve().parents[3]
CONTENT = REPO / "content"
WORLD_FORMAT = "cogbench-world/0"
PSEUDO_ROWS = ("start", "rest", "seal")  # biome keys that are not a layer of the descent


class WorldFilesNotFound(FileNotFoundError):
    """No world file pair was found for a run."""


class MissingRegion(LookupError):
    """A scene of the world file lacks a region its scoring rule needs (an older generator)."""


@dataclass(frozen=True)
class Scene:
    """One placed encounter of the world (a placeholder carries no scene and is not scored)."""

    eid: str
    variant: int
    mirror: bool
    must_pass: bool
    layer: int
    biome: str
    params: dict[str, str]
    trigger: Rect
    footprint: Rect
    regions: dict[str, Rect]
    x: int
    y: int

    @property
    def key(self) -> str:
        return f"{self.eid}@{self.x},{self.y}"

    def region(self, name: str) -> Rect:
        if name not in self.regions:
            raise MissingRegion(f"{self.key} has no region `{name}` (has {sorted(self.regions)})")
        return self.regions[name]


@dataclass(frozen=True)
class Span:
    """A band of rows of the biome map: `layer` is 1, 2, 3 for the descent, else 0."""

    name: str
    layer: int
    y0: int
    y1: int


@dataclass
class WorldInfo:
    seed: int
    rule_seed: int
    width: int
    height: int
    scenes: list[Scene]
    spans: list[Span]
    markers: list[dict[str, Any]]
    meta: dict[str, Any]
    png_path: Path | None = None
    json_path: Path | None = None
    _grid: np.ndarray | None = field(default=None, repr=False)

    # -- the grid ----------------------------------------------------------------------------
    @property
    def grid(self) -> np.ndarray | None:
        """The world at frame 0 (a (height, width) uint8 array), or None without the PNG."""
        if self._grid is None and self.png_path is not None and self.png_path.exists():
            from PIL import Image

            self._grid = np.array(Image.open(self.png_path), dtype=np.uint8)
        return self._grid

    # -- markers -----------------------------------------------------------------------------
    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.markers if m.get("type") == kind]

    @property
    def seal(self) -> dict[str, Any] | None:
        found = self.of_type("seal")
        return found[0] if found else None

    @property
    def seal_plug(self) -> Rect | None:
        seal = self.seal
        return None if seal is None else Rect(seal["x"], seal["y"], seal["w"], seal["h"])

    @property
    def seal_room(self) -> Rect | None:
        seal = self.seal
        return None if seal is None or "room" not in seal else Rect.parse(seal["room"])

    @property
    def spawn(self) -> tuple[int, int] | None:
        found = self.of_type("spawn_player")
        return (found[0]["x"], found[0]["y"]) if found else None

    def breaker_spells(self) -> list[str]:
        """Spells of the items marked `role: breaker` (the parts of the seal key)."""
        found = [
            m["spell"]
            for m in self.of_type("item")
            if m.get("role") == "breaker" and m.get("spell")
        ]
        return sorted(set(found))

    @property
    def main_path(self) -> list[tuple[float, float]]:
        return [(float(p[0]), float(p[1])) for p in self.meta.get("main_path", [])]

    # -- scenes ------------------------------------------------------------------------------
    def scenes_of(self, eid: str) -> list[Scene]:
        return [s for s in self.scenes if s.eid == eid]

    def span_at(self, y: float) -> Span | None:
        for span in self.spans:
            if span.y0 <= y < span.y1:
                return span
        return self.spans[-1] if self.spans and y >= self.spans[-1].y1 else None

    def layer_at(self, y: float) -> int:
        span = self.span_at(y)
        return span.layer if span else 0

    def layers(self) -> list[Span]:
        return [s for s in self.spans if s.layer > 0]

    @property
    def bottom(self) -> float:
        """The deepest cell the player can stand on: the floor of the sealed room."""
        room = self.seal_room
        return float(room.bottom) if room else float(self.height)

    def route_length_to(self, y: float) -> float | None:
        """Length of the main path from the start to its point nearest to depth `y`."""
        path = self.main_path
        if len(path) < 2:
            return None
        nearest = min(range(len(path)), key=lambda i: abs(path[i][1] - y))
        total = 0.0
        for a, b in pairwise(path[: nearest + 1]):
            total += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        return total


# ---------------------------------------------------------------------------------- loading
def find_world_files(
    run_dir: Path, explicit: tuple[Path, Path] | None = None, seed: int | None = None
) -> tuple[Path | None, Path]:
    """The `(png, json)` of a run's world.

    Looked for, in order: the explicit pair, `<run>/world/`, `<run>/`, then `world/`,
    `<run>-world/` and `<run>_world/` next to the run folder. Among several candidates the one
    whose `seed` matches the recording's wins.
    """
    if explicit is not None:
        png, js = Path(explicit[0]), Path(explicit[1])
        if not js.exists():
            raise WorldFilesNotFound(f"{js}: no such world file")
        return (png if png.exists() else None), js
    run_dir = Path(run_dir)
    sides = [run_dir / "world", run_dir]
    sides += [run_dir.parent / "world", run_dir.with_name(run_dir.name + "-world")]
    sides += [run_dir.with_name(run_dir.name + "_world")]
    candidates: list[Path] = []
    for folder in sides:
        if folder.is_dir():
            candidates += [p for p in sorted(folder.glob("*.json")) if _is_world(p)]
        if candidates:
            break
    if not candidates:
        raise WorldFilesNotFound(f"{run_dir}: no world file pair (cogbench-world/0) found")
    pick = candidates[0]
    if seed is not None:
        for p in candidates:
            if _world_seed(p) == seed:
                pick = p
                break
    png = pick.with_suffix(".png")
    return (png if png.exists() else None), pick


def _is_world(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as handle:
            head = handle.read(200)
    except OSError:
        return False
    return WORLD_FORMAT in head


def _world_seed(path: Path) -> int | None:
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("seed"))
    except (OSError, ValueError, TypeError):
        return None


def load_world(png: Path | None, js: Path) -> WorldInfo:
    """Read a world file pair; the PNG is optional (only the grid needs it)."""
    try:
        doc = json.loads(Path(js).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ValueError(f"{js}: cannot read the world file ({err})") from err
    if doc.get("format") != WORLD_FORMAT:
        raise ValueError(f"{js}: format must be {WORLD_FORMAT}")
    try:
        markers = [m for m in doc.get("markers", []) if isinstance(m, dict)]
        cell = int(doc.get("biome_cell_size", 128))
        meta = doc.get("meta")
        return WorldInfo(
            seed=int(doc.get("seed", 0)),
            rule_seed=int(doc.get("rule_seed", 0)),
            width=int(doc["width"]),
            height=int(doc["height"]),
            scenes=_scenes(markers),
            spans=_spans(doc.get("biome_map", []), cell),
            markers=markers,
            meta=dict(meta) if isinstance(meta, dict) else {},
            png_path=Path(png) if png is not None else None,
            json_path=Path(js),
        )
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"{js}: not a usable world file ({type(err).__name__}: {err})") from err


def _scenes(markers: list[dict[str, Any]]) -> list[Scene]:
    out: list[Scene] = []
    for m in markers:
        if m.get("type") != "encounter" or m.get("placeholder") or "footprint" not in m:
            continue
        footprint = Rect.parse(m["footprint"])
        out.append(
            Scene(
                eid=str(m["encounter_id"]),
                variant=int(m.get("variant", 0)),
                mirror=bool(m.get("mirror", False)),
                must_pass=bool(m.get("must_pass", False)),
                layer=int(m.get("layer") or 0),
                biome=str(m.get("biome", "")),
                params={str(k): str(v) for k, v in (m.get("params") or {}).items()},
                trigger=Rect.parse(m["trigger"]) if "trigger" in m else footprint,
                footprint=footprint,
                regions={k: Rect.parse(v) for k, v in (m.get("regions") or {}).items()},
                x=int(m["x"]),
                y=int(m["y"]),
            )
        )
    return out


def _spans(biome_map: list[list[str]], cell: int) -> list[Span]:
    """Bands of rows: runs of ordinary biomes are layers 1, 2, 3, the rest are pseudo bands."""
    spans: list[Span] = []
    layer = 0
    previous_ordinary = False
    for row, keys in enumerate(biome_map):
        key = keys[0] if keys else ""
        pseudo = key.split("_")[0] in PSEUDO_ROWS
        if pseudo:
            spans.append(Span(key, 0, row * cell, (row + 1) * cell))
        elif not previous_ordinary:
            layer += 1
            spans.append(Span(f"layer{layer}", layer, row * cell, (row + 1) * cell))
        else:
            last = spans[-1]
            spans[-1] = Span(last.name, last.layer, last.y0, (row + 1) * cell)
        previous_ordinary = not pseudo
    return spans


# ---------------------------------------------------------------------------- content files
@cache
def encounter_nodes(eid: str) -> tuple[str, ...]:
    """The capability nodes of an encounter (`content/encounters/EXX.json` `nodes`): the first
    is the main one, the second (if any) the secondary one (capability graph section 3.2)."""
    path = CONTENT / "encounters" / f"{eid}.json"
    try:
        return tuple(json.loads(path.read_text(encoding="utf-8")).get("nodes", []))
    except (OSError, json.JSONDecodeError):
        return ()


@cache
def material_keys() -> tuple[str, ...]:
    """Material keys by index (`content/materials.json`)."""
    data = json.loads((CONTENT / "materials.json").read_text(encoding="utf-8"))
    keys = [""] * (max(m["index"] for m in data["materials"]) + 1)
    for m in data["materials"]:
        keys[m["index"]] = m["key"]
    return tuple(keys)


@cache
def lava_solidifiers() -> frozenset[str]:
    """Liquids that turn lava into rock under the one reaction table (`content/reactions.json`)."""
    data = json.loads((CONTENT / "reactions.json").read_text(encoding="utf-8"))
    out: set[str] = set()
    for row in data["reactions"]:
        if row["a"] == "lava" and row["out_a"] == "rock" and not row["b"].startswith(("[", "@")):
            out.add(row["b"])
    return frozenset(out)


@cache
def lava_rows() -> frozenset[str]:
    """Ids of the reaction rows in which a lava cell becomes rock (`reaction` events)."""
    data = json.loads((CONTENT / "reactions.json").read_text(encoding="utf-8"))
    return frozenset(
        r["id"] for r in data["reactions"] if r["a"] == "lava" and r["out_a"] == "rock"
    )


@cache
def blocking_indices() -> frozenset[int]:
    """Material indices that stop a line of sight: solid ground, powders, walls."""
    data = json.loads((CONTENT / "materials.json").read_text(encoding="utf-8"))
    return frozenset(m["index"] for m in data["materials"] if m["kind"] in ("static", "powder"))


@cache
def undiggable_indices() -> frozenset[int]:
    """Static materials the starting digger cannot remove (durability above the `DIGGER`
    explosion's `max_durability` in `content/spells.json`): brick and metal."""
    spells = json.loads((CONTENT / "spells.json").read_text(encoding="utf-8"))["spells"]
    digger = next(s for s in spells if s["key"] == "DIGGER")
    limit = float(digger["projectile"]["explosion"]["max_durability"])
    data = json.loads((CONTENT / "materials.json").read_text(encoding="utf-8"))
    return frozenset(
        m["index"]
        for m in data["materials"]
        if m["kind"] == "static" and float(m.get("durability", 0)) > limit
    )


@cache
def drink_effects() -> dict[str, str]:
    """Material key -> what drinking it does (`content/materials.json` `drink_effect`)."""
    data = json.loads((CONTENT / "materials.json").read_text(encoding="utf-8"))
    return {m["key"]: str(m.get("drink_effect") or "none") for m in data["materials"]}


HARMFUL_DRINK_EFFECTS = frozenset({"oiled", "drunk", "damage", "burn", "poisoned"})


def harmful_to_drink(material: str) -> bool:
    """True if drinking `material` does harm (poisons, makes drunk or oiled, hurts, burns)."""
    return drink_effects().get(material, "none") in HARMFUL_DRINK_EFFECTS


@cache
def rows_turning(material: str, into: str) -> frozenset[str]:
    """Ids of the reaction rows in which a cell of `material` becomes `into` (the toxic sludge
    of a pool turned into water by a splash of water)."""
    data = json.loads((CONTENT / "reactions.json").read_text(encoding="utf-8"))
    return frozenset(
        r["id"]
        for r in data["reactions"]
        if (r["a"] == material and r["out_a"] == into)
        or (r["b"] == material and r["out_b"] == into)
    )


@cache
def breathless_liquids() -> frozenset[int]:
    """Indices of the liquids a head cannot breathe in (every liquid but the potions), as the
    game's drowning check reads them."""
    data = json.loads((CONTENT / "materials.json").read_text(encoding="utf-8"))
    return frozenset(
        m["index"]
        for m in data["materials"]
        if m["kind"] == "liquid" and m.get("family") != "potion" and m["key"] != "air"
    )


@cache
def spell_projectiles() -> frozenset[str]:
    """Projectile names of the player's spells (`content/spells.json` keys): a `hit` event naming
    one of them was the player's shot, not an enemy's."""
    data = json.loads((CONTENT / "spells.json").read_text(encoding="utf-8"))
    return frozenset(s["key"] for s in data["spells"])


@cache
def enemy_projectiles() -> frozenset[str]:
    """Projectile names of the enemies' attacks (`content/entities.json` `projectiles`): a `hit`
    event naming one of them was an enemy's shot."""
    data = json.loads((CONTENT / "entities.json").read_text(encoding="utf-8"))
    return frozenset(data.get("projectiles", {}))


@cache
def marker_things(eid: str, role: str) -> frozenset[str]:
    """What the definition's item markers of `role` hold (`content/encounters/EXX.json`): a
    bottle's `contents` (a slot `$A` resolved by the placed scene's params is left as `$A`), or
    the item itself (`potion_heal`). A marker given as a list of templates (one per variant
    pair, E21) counts with every template."""
    path = CONTENT / "encounters" / f"{eid}.json"
    try:
        markers = json.loads(path.read_text(encoding="utf-8")).get("markers", {})
    except (OSError, json.JSONDecodeError):
        return frozenset()
    out = set()
    for entry in markers.values():
        for m in entry if isinstance(entry, list) else [entry]:
            if isinstance(m, dict) and m.get("role") == role:
                out.add(str(m.get("contents") or m.get("item") or ""))
    return frozenset(x for x in out if x)
