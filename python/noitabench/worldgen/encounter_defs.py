"""Encounter definitions and scene art (``content/encounters/``, format ``cogbench-encounter/0``).

An encounter is a small hand-drawn scene (Noita's "pixel scene") the generator stamps into the
world. Each one is two files:

``E02.json``
    the definition: id, capability nodes, must-pass or optional, where it may go, the variant
    parameters (liquid slots, marker templates), the trap and the cue it leaves, the
    predicates of the reaction table it needs, named regions.
``E02.scene``
    the geometry, one character per cell. Lines starting with ``;`` are comments.

====================  =========================================================================
character             meaning
====================  =========================================================================
``.``                 air
``#`` ``g`` ``b`` ``w``  rock, ground, brick, wood
``m``                 metal (durability 15: never dug, burnt or eaten by acid; the alchemy bowls)
``s`` ``c`` ``p``     sand, coal, gunpowder
``L`` ``W`` ``O`` ``X``  lava, water, oil, acid (acid only where the definition allows it)
``A``-``F``           liquid slot: filled from the variant (a table role)
``0``-``9``           marker: the cell is air and the definition's ``markers`` entry is placed
``^`` ``v`` ``<`` ``>``  door: air on the top, bottom, left or right edge, linked to the cave
====================  =========================================================================

A definition may add characters with ``legend`` (character to material key). Mirroring a
variant flips the art left to right (odd variants are the mirror image of the even one before).

Other fields of the definition: ``slots`` (what fills each liquid letter: a role of the reaction
table or a fixed material, ``pick`` to take another candidate of the role, ``exclude`` to differ
from other slots), ``markers`` (``$A`` in ``contents`` is the material of slot A; ``role``
names what the item is for, ``solvent`` and ``breaker`` are supplies the checks look for; the
breakers of all scenes together are the key of the seal, see ``breaker.py``; a marker may map to
a list of templates instead, one per variant pair: variants ``2k`` and ``2k + 1`` use entry ``k``
modulo its length, so an item can change places with the variant, as E21's healing potion does;
a breaker never changes),
``anchor_y`` (the row that sits on the centre line of the rock band), ``trigger`` (default:
the whole footprint), ``regions`` (named boxes, for the checks and the tests),
``requires`` (``{"predicate": ...}`` the table must satisfy, ``{"supply": role, "min": n,
"own": bool}`` bottles or spells the player can walk to; every requirement is hard),
``dig_zone`` (the way through is dug: natural connectivity may cross it), ``allow_acid`` (brick
vats), ``fixed`` (placed by a global scene), ``once`` (a world holds the scene at most once: the
default is twice, and once for a scene that hands out a breaker), ``lab`` (``carve`` boxes and
the ``goal`` of the lab world used by tests and previews), and the ``trap`` the scene sets with
the ``cue`` it leaves, which are for the designers and never reach an agent.

``gates`` (every must-pass scene that is not a dig zone): the obstacles in series, each a list
of names from ``regions`` (its solution regions; a gate with several offers alternatives). The
art has to make them true gates for a player who digs but cannot break brick or metal: see
``routes.py``, which the loader runs on the art (both the top door and the exit have to be
joined only through the regions, and the outer wall of the footprint has to be closed).
``sealed`` (optional) lists the regions that are horizontal passages over or through a mass the
digger could tunnel in (a river under a roof, a pool in a basin): the row of cells just above and
just below each has to be brick or metal wherever it touches the passage.

``lessons`` and ``lesson_topics`` (optional) say what the scene teaches, for the evaluation's
knowledge base (``eval/knowledge/lessons.py``, contracts section 21). The loader here ignores
them: they never reach the world, the generator or an agent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from .breaker import spell_table
from .config import Materials, load_materials
from .contentio import CONTENT_DIR, need, read_json
from .markers import BARREL_CLEARANCE
from .routes import Box, route_problems
from .table import ROLES, Rules, get_rules

FORMAT = "cogbench-encounter/0"
ENCOUNTER_DIR = CONTENT_DIR / "encounters"

BASE_LEGEND = {
    ".": "air",
    "#": "rock",
    "g": "ground",
    "b": "brick",
    "m": "metal",
    "w": "wood",
    "s": "sand",
    "c": "coal",
    "p": "gunpowder",
    "L": "lava",
    "W": "water",
    "O": "oil",
    "X": "acid",
}
SLOT_CHARS = "ABCDEF"
MARKER_CHARS = "0123456789"
DOOR_CHARS = "^v<>"
MIRROR_DOOR = {"^": "^", "v": "v", "<": ">", ">": "<"}
SIDES = {"^": "top", "v": "bottom", "<": "left", ">": "right"}
MARKER_TYPES = ("item", "spawn_enemy")
PREDICATES = (
    "lava_solidifier",  # some liquid turns lava into rock or ground at 40 % or more
    "extinguisher",  # some plain liquid puts burning cells out
    "acid_dissolves_rock",
    "fire_ignites_gas",
    "seal_breakable",  # the breaker spells of the world make an explosion that removes brick
)


@dataclass(frozen=True)
class SlotSpec:
    """How one liquid slot of the art is filled."""

    name: str
    role: str | None = None  # a role of the reaction table (``table.ROLES``)
    material: str | None = None  # or one fixed material
    pick: int = 0  # offset into the role's candidates, so two slots of one role differ
    exclude: tuple[str, ...] = ()  # slots whose material this one must differ from


@dataclass(frozen=True)
class EncounterDef:
    id: str
    name_zh: str
    name_en: str
    nodes: tuple[str, ...]
    must_pass: bool
    layer: int | None
    biomes: tuple[str, ...]
    rows: tuple[str, ...]  # the art
    legend: dict[str, str]
    slots: dict[str, SlotSpec]
    markers: dict[str, dict]
    trigger: tuple[int, int, int, int]  # x, y, w, h inside the footprint
    anchor_y: int  # the row of the art that sits on the wall's centre line (must-pass)
    variants: int
    dig_zone: bool  # the route through the scene is dug: natural connectivity may cross it
    allow_acid: bool
    fixed: bool  # placed by a global scene (the sealed deep), not by a band or a biome slot
    once: bool  # a world holds the scene at most once
    requires: tuple[dict, ...]
    regions: dict[str, tuple[int, int, int, int]]
    trap: str
    cue: str
    gates: tuple[tuple[str, ...], ...] = ()  # solution regions by gate (routes.py)
    sealed: tuple[str, ...] = ()  # gate regions whose top and bottom must be walled (routes.py)
    lab_carve: tuple[tuple[int, int, int, int], ...] = ()  # air boxes of the lab world only
    lab_goal: tuple[int, int] | None = None  # where the lab world's solution ends (x, y)
    notes: str = ""
    # every template of a marker given as a list (``markers`` holds the first, used by variants
    # 0 and 1); a character missing here has the one template of ``markers``
    marker_options: dict[str, tuple[dict, ...]] = field(default_factory=dict)
    path: Path = field(default=Path("."), compare=False)

    @property
    def w(self) -> int:
        return len(self.rows[0])

    @property
    def h(self) -> int:
        return len(self.rows)

    @property
    def node(self) -> str:
        return self.nodes[0]

    def templates(self, ch: str) -> tuple[dict, ...]:
        """Every template of marker ``ch`` (one, or one per variant pair)."""
        return self.marker_options.get(ch, (self.markers[ch],))

    def template(self, ch: str, variant: int) -> dict:
        """The template of marker ``ch`` in ``variant``."""
        options = self.templates(ch)
        return options[(variant >> 1) % len(options)]

    @property
    def hands_out_breaker(self) -> bool:
        """True if the scene holds the key of the seal (a marker with ``role: breaker``)."""
        return any(m.get("role") == "breaker" for m in self.markers.values())

    def doors(self) -> dict[str, list[tuple[int, int]]]:
        """Door cells by side (``top`` ...), as ``(x, y)`` in art coordinates."""
        out: dict[str, list[tuple[int, int]]] = {}
        for y, row in enumerate(self.rows):
            for x, ch in enumerate(row):
                if ch in DOOR_CHARS:
                    out.setdefault(SIDES[ch], []).append((x, y))
        return out


# ---------------------------------------------------------------------------- loading


def _read_art(path: Path) -> tuple[str, ...]:
    rows = [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8").splitlines()]
    rows = [ln for ln in rows if ln and not ln.startswith(";")]
    need(bool(rows), path, "art", "is empty")
    widths = {len(r) for r in rows}
    need(len(widths) == 1, path, "art", f"rows have different lengths {sorted(widths)}")
    return tuple(rows)


def _int_box(value, path: Path, name: str, w: int, h: int) -> tuple[int, int, int, int]:
    need(
        isinstance(value, list) and len(value) == 4 and all(isinstance(v, int) for v in value),
        path,
        name,
        "must be [x, y, w, h] (integers)",
    )
    x, y, bw, bh = value
    need(0 <= x and 0 <= y and bw > 0 and bh > 0, path, name, "must be a positive box")
    need(x + bw <= w and y + bh <= h, path, name, f"{value} reaches outside the {w}x{h} art")
    return x, y, bw, bh


def _parse_slots(d: dict, path: Path) -> dict[str, SlotSpec]:
    slots: dict[str, SlotSpec] = {}
    for name, spec in d.items():
        need(name in SLOT_CHARS, path, f"slots.{name}", f"must be one of {SLOT_CHARS}")
        role, material = spec.get("role"), spec.get("material")
        need((role is None) != (material is None), path, f"slots.{name}", "needs role or material")
        need(role is None or role in ROLES, path, f"slots.{name}.role", f"unknown role {role}")
        slots[name] = SlotSpec(
            name, role, material, int(spec.get("pick", 0)), tuple(spec.get("exclude", ()))
        )
    return slots


def _check_art(d: EncounterDef, mats: Materials) -> None:
    path = d.path
    legend = {**BASE_LEGEND, **d.legend}
    for ch, key in d.legend.items():
        need(len(ch) == 1 and ch not in DOOR_CHARS + SLOT_CHARS + MARKER_CHARS, path, "legend",
             f"character {ch!r} is reserved")  # fmt: skip
        need(key in mats.index, path, f"legend.{ch}", f"unknown material {key}")
    used = {ch for row in d.rows for ch in row}
    for ch in sorted(used):
        known = ch in legend or ch in SLOT_CHARS or ch in MARKER_CHARS or ch in DOOR_CHARS
        need(known, path, "art", f"character {ch!r} is not in the legend")
        if ch in SLOT_CHARS:
            need(ch in d.slots, path, "slots", f"the art uses slot {ch} but it is not defined")
        if ch in MARKER_CHARS:
            need(
                ch in d.markers, path, "markers", f"the art uses marker {ch} but it is not defined"
            )
        if legend.get(ch) == "acid":
            need(d.allow_acid, path, "allow_acid", "must be true for an art with acid cells")
    for ch in d.markers:
        options = d.templates(ch)
        need(len(options) <= d.variants // 2, path, f"markers.{ch}",
             f"{len(options)} templates but only {d.variants // 2} variant pairs")  # fmt: skip
        for tpl in options:
            need(tpl.get("type") in MARKER_TYPES, path, f"markers.{ch}.type", "unknown marker type")
            if tpl.get("role") != "breaker":
                continue
            need(
                len(options) == 1, path, f"markers.{ch}", "a breaker cannot change with the variant"
            )
            is_spell = tpl.get("type") == "item" and tpl.get("item") == "spell"
            need(is_spell and tpl.get("spell") in spell_table(), path, f"markers.{ch}",
                 "a breaker is a spell item whose spell is in content/spells.json")  # fmt: skip
    _check_doors(d)
    _check_marker_room(d, mats)


def _enemy_heights() -> dict[str, int]:
    """Collision box height of every enemy kind (``content/entities.json``)."""
    data = read_json(CONTENT_DIR / "entities.json")["enemies"]
    return {k: int(v["collision"]["h"]) for k, v in data.items()}


def _check_marker_room(d: EncounterDef, mats: Materials) -> None:
    """Every enemy and barrel marker stands on a floor with room above it for the entity.

    An enemy needs its collision box free above its cell (``content/entities.json``), a barrel
    needs ``BARREL_CLEARANCE`` free cells (contracts section 4), a bottle or a spell a floor.
    """
    legend = {**BASE_LEGEND, **d.legend}
    heights = _enemy_heights()

    def free(x: int, y: int) -> bool:
        ch = d.rows[y][x]
        return ch in MARKER_CHARS or ch in DOOR_CHARS or legend.get(ch) == "air"

    def solid(x: int, y: int) -> bool:
        key = legend.get(d.rows[y][x])
        return key is not None and mats.kinds[mats.index[key]] in ("static", "powder")

    for y, row in enumerate(d.rows):
        for x, ch in enumerate(row):
            if ch not in MARKER_CHARS or ch not in d.markers:
                continue
            where = f"marker {ch} at ({x}, {y})"
            need(y + 1 < d.h and solid(x, y + 1), d.path, "art", f"{where} has no floor under it")
            for tpl in d.templates(ch):  # every variant's template must fit the cell
                if tpl["type"] == "spawn_enemy":
                    high = heights.get(tpl.get("enemy", ""))
                    need(high is not None, d.path, f"markers.{ch}.enemy", "unknown enemy")
                    room, what = high, f"a {tpl['enemy']} needs {high} free cells above its feet"
                elif str(tpl.get("item", "")).startswith("barrel_"):
                    room = BARREL_CLEARANCE + 1  # its own cell and the clearance above
                    what = f"a barrel needs {BARREL_CLEARANCE} free cells above it"
                else:
                    continue
                cells = range(y - room + 1, y + 1)
                ok = y - room + 1 >= 0 and all(free(x, k) for k in cells)
                need(ok, d.path, "art", f"{where}: {what}")


def _check_doors(d: EncounterDef) -> None:
    doors = d.doors()
    edge = {
        "top": lambda x, y: y == 0,
        "bottom": lambda x, y: y == d.h - 1,
        "left": lambda x, y: x == 0,
        "right": lambda x, y: x == d.w - 1,
    }
    for side, cells in doors.items():
        bad = [c for c in cells if not edge[side](*c)]
        need(not bad, d.path, "art", f"{side} door cells {bad} are not on that edge")
    if d.fixed:
        return
    if d.must_pass:
        need("top" in doors and "bottom" in doors, d.path, "art", "a must-pass scene needs a top and a bottom door")  # fmt: skip
    else:
        need(len(doors) >= 1, d.path, "art", "a scene needs at least one door")


def _parse(data: dict, path: Path, mats: Materials) -> EncounterDef:
    need(data.get("format") == FORMAT, path, "format", f"must be {FORMAT}")
    art_path = path.with_name(data["art"])
    rows = _read_art(art_path)
    w, h = len(rows[0]), len(rows)
    trig = data.get("trigger")
    trigger = _int_box(trig, path, "trigger", w, h) if trig else (0, 0, w, h)
    regions = {
        k: _int_box(v, path, f"regions.{k}", w, h) for k, v in data.get("regions", {}).items()
    }
    requires = tuple(data.get("requires", ()))
    for req in requires:
        ok = isinstance(req, dict) and (req.get("predicate") in PREDICATES or "supply" in req)
        need(ok, path, "requires", f"entry {req!r} needs a known predicate or a supply")
        need("soft" not in req, path, "requires", f"entry {req!r}: requirements are all hard")
    gates = _parse_gates(data.get("gates", ()), regions, path)
    markers = _parse_markers(data.get("markers", {}), path)
    sealed = _parse_sealed(data.get("sealed", ()), gates, path)
    anchor_y = int(data.get("anchor_y", h // 2))
    need(0 <= anchor_y < h, path, "anchor_y", "must lie inside the art")
    layer = data.get("layer")
    d = EncounterDef(
        id=data["id"],
        name_zh=data["name_zh"],
        name_en=data["name_en"],
        nodes=tuple(data["nodes"]),
        must_pass=bool(data["must_pass"]),
        layer=None if layer is None else int(layer),
        biomes=tuple(data.get("biomes", ())),
        rows=rows,
        legend=dict(data.get("legend", {})),
        slots=_parse_slots(data.get("slots", {}), path),
        markers={k: v[0] for k, v in markers.items()},
        trigger=trigger,
        anchor_y=anchor_y,
        variants=int(data.get("variants", 8)),
        dig_zone=bool(data.get("dig_zone", False)),
        allow_acid=bool(data.get("allow_acid", False)),
        fixed=bool(data.get("fixed", False)),
        once=bool(data.get("once", False)),
        requires=requires,
        regions=regions,
        trap=data["trap"],
        cue=data["cue"],
        gates=gates,
        sealed=sealed,
        lab_carve=tuple(tuple(b) for b in data.get("lab", {}).get("carve", ())),
        lab_goal=tuple(data["lab"]["goal"]) if "goal" in data.get("lab", {}) else None,
        notes=data.get("notes", ""),
        marker_options={k: v for k, v in markers.items() if len(v) > 1},
        path=path,
    )
    need(path.stem == d.id, path, "id", f"must match the file name ({path.stem})")
    need(d.variants >= 2 and d.variants % 2 == 0, path, "variants", "must be an even number >= 2")
    _check_art(d, mats)
    _check_gates(d, mats)
    return d


def _parse_markers(value: dict, path: Path) -> dict[str, tuple[dict, ...]]:
    """The templates of each marker character: one, or a list with one per variant pair."""
    out: dict[str, tuple[dict, ...]] = {}
    for k, v in value.items():
        options = v if isinstance(v, list) else [v]
        ok = bool(options) and all(isinstance(o, dict) for o in options)
        need(ok, path, f"markers.{k}", "must be a template or a non-empty list of templates")
        out[str(k)] = tuple(dict(o) for o in options)
    return out


def _parse_gates(
    value, regions: dict[str, tuple[int, int, int, int]], path: Path
) -> tuple[tuple[str, ...], ...]:
    ok = isinstance(value, (list, tuple)) and all(
        isinstance(g, (list, tuple)) and g and all(isinstance(n, str) for n in g) for g in value
    )
    need(ok, path, "gates", "must be a list of lists of region names")
    gates = tuple(tuple(g) for g in value)
    names = [n for g in gates for n in g]
    for n in names:
        need(n in regions, path, "gates", f"{n} is not one of the regions")
    need(len(names) == len(set(names)), path, "gates", "a region belongs to one gate only")
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            need(not _overlap(regions[a], regions[b]), path, "gates",
                 f"the solution regions {a} and {b} overlap")  # fmt: skip
    return gates


def _parse_sealed(value, gates: tuple[tuple[str, ...], ...], path: Path) -> tuple[str, ...]:
    ok = isinstance(value, (list, tuple)) and all(isinstance(n, str) for n in value)
    need(ok, path, "sealed", "must be a list of region names")
    names = {n for g in gates for n in g}
    for n in value:
        need(n in names, path, "sealed", f"{n} is not a gate region")
    need(len(set(value)) == len(value), path, "sealed", "a region is listed twice")
    return tuple(value)


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _check_gates(d: EncounterDef, mats: Materials) -> None:
    """A must-pass scene that is not dug through names its gates, and its art makes them gates."""
    if d.must_pass and not d.dig_zone:
        need(bool(d.gates), d.path, "gates", "a must-pass scene needs its solution regions")
    if not d.gates:
        return
    inst = instantiate(d, get_rules(0), 0, mats)  # the mirror image routes the same way
    for name in (n for g in d.gates for n in g):
        for side, cells in inst.doors.items():
            hit = any(_overlap(inst.regions[name], (x, y, 1, 1)) for x, y in cells)
            need(not hit, d.path, "gates", f"the solution region {name} covers a {side} door")
    problems = route_problems(inst.grid, inst.doors, inst.gate_regions(), mats, d.fixed, d.sealed)
    need(not problems, d.path, "gates", "; ".join(problems))


@lru_cache(maxsize=2)
def load_encounters(directory: Path | None = None) -> dict[str, EncounterDef]:
    """All encounter definitions of ``content/encounters/``, by id."""
    root = directory or ENCOUNTER_DIR
    mats = load_materials()
    out: dict[str, EncounterDef] = {}
    for path in sorted(root.glob("E*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            raise ValueError(f"{path}: invalid JSON ({err})") from err
        try:
            d = _parse(data, path, mats)
        except KeyError as err:
            raise ValueError(f"{path.name}: missing field {err}") from err
        out[d.id] = d
    return out


def implemented_ids() -> frozenset[str]:
    return frozenset(load_encounters())


def single_ids() -> frozenset[str]:
    """Scenes a world holds at most once: the ones that hand out a part of the key of the seal
    and the ones whose definition says ``once``."""
    return frozenset(i for i, d in load_encounters().items() if d.hands_out_breaker or d.once)


def breaker_spells() -> frozenset[str]:
    """The spells the scenes hand out as parts of the key of the seal (``role: breaker``).

    A world holds exactly one item of each (a scene that hands one out is placed once).
    """
    return frozenset(
        str(m["spell"])
        for d in load_encounters().values()
        for m in d.markers.values()
        if m.get("role") == "breaker" and m.get("spell")
    )


# ---------------------------------------------------------------------------- instances


@dataclass
class Instance:
    """One encounter ready to stamp: concrete cells, markers and doors in footprint coordinates."""

    defn: EncounterDef
    variant: int
    mirror: bool
    params: dict[str, str]  # slot letter -> material key
    grid: np.ndarray  # (h, w) uint8 material indices
    markers: list[dict]  # templates resolved, with x, y relative to the footprint
    doors: dict[str, list[tuple[int, int]]]
    regions: dict[str, tuple[int, int, int, int]]
    trigger: tuple[int, int, int, int]

    @property
    def w(self) -> int:
        return int(self.grid.shape[1])

    @property
    def h(self) -> int:
        return int(self.grid.shape[0])

    def gate_regions(self) -> list[list[tuple[str, Box]]]:
        """The solution regions of every gate of the definition, in footprint coordinates."""
        return [[(n, self.regions[n]) for n in gate] for gate in self.defn.gates]

    def door_center(self, side: str) -> tuple[int, int]:
        cells = self.doors[side]
        xs = [c[0] for c in cells]
        ys = [c[1] for c in cells]
        return (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2


def resolve_slots(d: EncounterDef, rules: Rules, variant: int) -> dict[str, str]:
    """Fill the liquid slots of ``d`` for ``variant`` under ``rules``.

    The role's candidates are in a fixed order; the variant picks among them, so the same
    ``(variant, rules)`` always gives the same liquids. A slot that excludes others avoids
    their materials when the role offers anything else.
    """
    chosen: dict[str, str] = {}
    for name in sorted(d.slots):
        spec = d.slots[name]
        if spec.material is not None:
            chosen[name] = spec.material
            continue
        cands = rules.candidates(spec.role)
        need(
            bool(cands), d.path, f"slots.{name}", f"role {spec.role} has no material in this world"
        )
        taken = {chosen[e] for e in spec.exclude if e in chosen}
        allowed = [m for m in cands if m not in taken] or cands
        chosen[name] = allowed[((variant >> 1) + spec.pick) % len(allowed)]
    return chosen


def instantiate(d: EncounterDef, rules: Rules, variant: int, mats: Materials) -> Instance:
    """Build the cells, markers and doors of ``d`` as variant ``variant`` (0 <= variant < d.variants)."""
    if not 0 <= variant < d.variants:
        raise ValueError(f"{d.id}: variant must be in [0, {d.variants}), got {variant}")
    mirror = bool(variant & 1)
    params = resolve_slots(d, rules, variant)
    legend = {**BASE_LEGEND, **d.legend}
    rows = [r[::-1].translate(str.maketrans("<>", "><")) if mirror else r for r in d.rows]
    grid = np.zeros((d.h, d.w), dtype=np.uint8)
    markers: list[dict] = []
    doors: dict[str, list[tuple[int, int]]] = {}
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in SLOT_CHARS:
                grid[y, x] = mats[params[ch]]
            elif ch in MARKER_CHARS:
                markers.append(_marker(d, ch, variant, params, x, y))
            elif ch in DOOR_CHARS:
                doors.setdefault(SIDES[ch], []).append((x, y))
            else:
                grid[y, x] = mats[legend[ch]]
    regions = {k: _flip_box(b, d.w) if mirror else b for k, b in d.regions.items()}
    trig = _flip_box(d.trigger, d.w) if mirror else d.trigger
    markers.sort(key=lambda m: (m["y"], m["x"], m.get("item", m.get("enemy", ""))))
    return Instance(d, variant, mirror, params, grid, markers, doors, regions, trig)


def _flip_box(box: tuple[int, int, int, int], width: int) -> tuple[int, int, int, int]:
    x, y, w, h = box
    return width - x - w, y, w, h


def _marker(d: EncounterDef, ch: str, variant: int, params: dict[str, str], x: int, y: int) -> dict:
    """The marker of template ``ch`` (as in ``variant``) at ``(x, y)``; ``$A`` in a value is slot
    A's material."""
    out: dict = {}
    for key, value in d.template(ch, variant).items():
        if isinstance(value, str) and value.startswith("$"):
            slot = value[1:]
            need(slot in params, d.path, f"markers.{ch}.{key}", f"refers to unknown slot {slot}")
            value = params[slot]
        out[key] = value
    out["x"], out["y"] = x, y
    out["encounter_id"] = d.id
    return out
