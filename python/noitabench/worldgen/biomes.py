"""Biome definitions (``content/biomes/<key>.json``): parsing and validation.

Every file is validated up front; errors are ``ValueError`` and name the file and the
field (error-handling spec).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .contentio import need, parse_section
from .encounters import ENCOUNTER_NODE
from .materials import Materials

FORMAT = "cogbench-biome/0"
SLOT_NAMES = ("left", "mid", "right")
ENEMY_KEYS = frozenset({"longleg", "shotgunner", "firemage_weak"})  # contracts section 4
ITEM_KEYS = frozenset(
    {
        "potion_heal",
        "potion_mana",
        "potion_haste",
        "spell",
        "wand",
        "bottle",
        "barrel_gunpowder",
        "barrel_acid",
        "barrel_oil",
    }
)
LAYOUTS = ("tiles", "rooms")
# structures and hazards the generator knows how to place (structures.py, hazards.py)
DECOR_NAMES = frozenset(
    {
        "timber",
        "frames",
        "platforms",
        "mushrooms",
        "seams",
        "pillars",
        "broken_walls",
        "breaches",
        "collapses",
        "rubble",
        "pipes",
        "channels",
        "catwalks",
        "barrel_rows",
    }
)
HAZARD_NAMES = frozenset({"lava_crust", "sand_pocket", "sand_pit"})
# structures that work on the rooms of the 'rooms' layout
ROOM_DECOR = frozenset(
    {
        "pillars",
        "broken_walls",
        "breaches",
        "rubble",
        "pipes",
        "channels",
        "catwalks",
        "barrel_rows",
    }
)
MIN_PLAYER_TUNNEL = 8  # the player (4 x 7 cells) must fit through every opening
MIN_SLOT_SIZE = 20  # smallest encounter slot (cells), see test_worldgen_generate


@dataclass(frozen=True)
class TileStyle:
    short_side: int
    band: int
    margin: int
    variants: int
    weights_tb: tuple[float, ...]
    weights_lr: tuple[float, ...]
    tunnel_min: int
    tunnel_max: int
    shape: str
    wobble: float
    chamber_prob: float
    chamber_min: int
    chamber_max: int
    chamber_aspect: float
    cavern_prob: float
    nook_prob: float
    isolated_prob: float
    roughness: float
    smooth_iters: int
    smooth_sigma: float
    smooth_noise: float


@dataclass(frozen=True)
class FillEntry:
    material: str
    weight: float
    buried: int = 0


@dataclass(frozen=True)
class VeinStyle:
    """Thin elongated mineral veins (``per_10k`` per 10,000 cells of solid rock)."""

    material: str
    per_10k: float
    length: tuple[int, int]
    thickness: tuple[float, float]
    buried: int


@dataclass(frozen=True)
class FillStyle:
    """Strata: ``materials`` are the layers (weights = shares, the first is the topmost
    tendency), ``stretch`` makes the layers wide, ``depth_bias`` orders them vertically."""

    scale: float
    speckle: float
    materials: tuple[FillEntry, ...]
    edge_material: str
    edge_depth: int
    edge_prob: float
    stretch: float = 1.0
    depth_bias: float = 0.0
    veins: tuple[VeinStyle, ...] = ()


@dataclass(frozen=True)
class Weighted:
    key: str
    weight: float
    extra: str = ""


@dataclass(frozen=True)
class FeatureStyle:
    """One of pools / piles / gas pockets / supports (``options`` is empty for supports)."""

    attempts_per_10k: float
    depth_min: int = 0
    depth_max: int = 0
    max_area: int = 0
    radius_min: int = 0
    radius_max: int = 0
    options: tuple[Weighted, ...] = ()
    lining_material: str = ""  # pools only: rock lining around the liquid
    lining_depth: int = 0


@dataclass(frozen=True)
class MarkerStyle:
    enemy_per_10k: float
    enemies: tuple[Weighted, ...]
    item_per_10k: float
    items: tuple[Weighted, ...]


@dataclass(frozen=True)
class EncounterStyle:
    slots: int
    pool: tuple[str, ...]
    w_min: int
    w_max: int
    h_min: int
    h_max: int


@dataclass(frozen=True)
class Rate:
    """``per_10k`` attempts per 10,000 cells of region, with two size ranges ``a`` and ``b``."""

    per_10k: float = 0.0
    a: tuple[int, int] = (0, 0)
    b: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class ShapeStyle:
    """Cave shape variety added to the tiled caves (shapes.py).

    ``widen_max``: tunnels swell by up to this many cells where a slow noise is high.
    halls: ``a`` = width, ``b`` = height. shafts / passages: ``a`` = width, ``b`` = length.
    alcoves: ``a`` = height, ``b`` = depth. ledges: ``a`` = length, ``b`` = thickness.
    cracks: ``b`` = length (two cells wide: not passable).
    """

    widen_max: int = 0
    widen_scale: float = 36.0
    halls: Rate = Rate()
    shafts: Rate = Rate()
    passages: Rate = Rate()
    alcoves: Rate = Rate()
    ledges: Rate = Rate()
    cracks: Rate = Rate()


@dataclass(frozen=True)
class RoomsStyle:
    """Built-structure layout (binary space partition into rooms joined by doors)."""

    min_w: int
    min_h: int
    margin: tuple[int, int]  # half wall thickness between rooms
    door_w: int
    door_h: int
    loops: float  # probability of an extra door between neighbouring rooms
    ragged: int = 0  # walls crumble by up to this many cells (ruins)


@dataclass(frozen=True)
class DepositSpec:
    """A heap of powder or a pool of liquid the biome must hold (``supply.deposits``).

    ``count`` deposits of at least ``min_cells`` cells each are built where the player can stand
    beside them; ``size`` is the radius of a pile or the depth of a pool. An ``optional`` deposit
    is tried but a failure does not fail the world.
    """

    material: str
    form: str  # "pile" | "pool"
    count: int
    min_cells: int
    size: tuple[int, int]
    max_area: int = 0  # pools only
    optional: bool = False


@dataclass(frozen=True)
class BottleSpec:
    """``count`` bottles of ``contents`` (a material key; empty = an empty bottle)."""

    contents: str
    count: int = 1


@dataclass(frozen=True)
class SupplyStyle:
    """What the biome guarantees for alchemy (worldgen/alchemy.py): deposits, bottles, bowls."""

    deposits: tuple[DepositSpec, ...] = ()
    bottles: tuple[BottleSpec, ...] = ()
    bowls: int = 0


@dataclass(frozen=True)
class Biome:
    key: str
    name_zh: str
    name_en: str
    layer: int
    slot: str
    tile: TileStyle | None
    fill: FillStyle
    pools: FeatureStyle
    piles: FeatureStyle
    gas: FeatureStyle
    markers: MarkerStyle
    encounters: EncounterStyle
    layout: str = "tiles"
    shape: ShapeStyle = ShapeStyle()
    rooms: RoomsStyle | None = None
    decor: dict = field(default_factory=dict)  # name -> parameters (DECOR_NAMES)
    hazards: dict = field(default_factory=dict)  # name -> parameters (HAZARD_NAMES)
    supply: SupplyStyle = SupplyStyle()


def _pair(v, path: Path, name: str) -> tuple[int, int]:
    need(
        isinstance(v, list) and len(v) == 2 and v[0] <= v[1],
        path,
        name,
        "must be [min, max]",
    )
    return int(v[0]), int(v[1])


def _parse_tile(d: dict, path: Path) -> TileStyle:
    s = int(d["short_side"])
    band, margin = int(d["band"]), int(d["margin"])
    need(s >= 16 and s % 2 == 0, path, "tile.short_side", "must be an even number >= 16")
    need(margin > band >= 1, path, "tile.margin", "must be larger than tile.band")
    need(int(d["variants"]) >= 1, path, "tile.variants", "must be at least 1")
    tmin, tmax = _pair(d["tunnel_width"], path, "tile.tunnel_width")
    need(
        tmin >= MIN_PLAYER_TUNNEL,
        path,
        "tile.tunnel_width",
        f"must be >= {MIN_PLAYER_TUNNEL} so that the player fits",
    )
    need(tmax <= s - 2 * margin, path, "tile.tunnel_width", "must fit in the opening")
    cmin, cmax = _pair(d["chamber_radius"], path, "tile.chamber_radius")
    wtb, wlr = d["edge_weights"]["tb"], d["edge_weights"]["lr"]
    need(
        len(wtb) == 5 and len(wlr) == 5 and min(wtb + wlr) >= 0 and sum(wtb) > 0 and sum(wlr) > 0,
        path,
        "tile.edge_weights",
        "needs 5 non-negative weights with a positive sum for 'tb' and 'lr'",
    )
    need(d["shape"] in ("organic", "rect"), path, "tile.shape", "must be organic or rect")
    return TileStyle(
        s,
        band,
        margin,
        int(d["variants"]),
        tuple(float(x) for x in wtb),
        tuple(float(x) for x in wlr),
        tmin,
        tmax,
        d["shape"],
        float(d["wobble"]),
        float(d["chamber_prob"]),
        cmin,
        cmax,
        float(d["chamber_aspect"]),
        float(d["cavern_prob"]),
        float(d["nook_prob"]),
        float(d["isolated_prob"]),
        float(d["roughness"]),
        int(d["smooth_iters"]),
        float(d["smooth_sigma"]),
        float(d["smooth_noise"]),
    )


def _weighted(
    lst: list[dict], key: str, path: Path, name: str, allowed: frozenset[str] | None = None
) -> tuple[Weighted, ...]:
    need(isinstance(lst, list) and bool(lst), path, name, "must be a non-empty list")
    out = []
    for e in lst:
        need(e["weight"] > 0, path, name, "weights must be positive")
        if allowed is not None:
            need(e[key] in allowed, path, name, f"'{e[key]}' is not one of {sorted(allowed)}")
        out.append(Weighted(e[key], float(e["weight"]), e.get("contents", "")))
    return tuple(out)


def _parse_fill(f: dict, path: Path, mats: Materials) -> FillStyle:
    entries = tuple(
        FillEntry(e["material"], float(e["weight"]), int(e.get("buried", 0)))
        for e in f["materials"]
    )
    for e in entries:
        mats[e.material]  # unknown key -> ValueError naming the key
        need(e.weight > 0, path, "fill.materials", "weights must be positive")
    mats[f["edge_material"]]
    need(any(e.buried == 0 for e in entries), path, "fill.materials", "needs a non-buried entry")
    need(float(f["scale"]) > 0, path, "fill.scale", "must be positive")
    stretch, bias = float(f.get("stretch", 1.0)), float(f.get("depth_bias", 0.0))
    need(stretch >= 1.0, path, "fill.stretch", "must be at least 1")
    need(0.0 <= bias <= 1.0, path, "fill.depth_bias", "must be in [0, 1]")
    return FillStyle(
        float(f["scale"]),
        float(f["speckle"]),
        entries,
        f["edge_material"],
        int(f["edge_depth"]),
        float(f["edge_prob"]),
        stretch,
        bias,
        tuple(_parse_vein(v, path, mats) for v in f.get("veins", [])),
    )


def _parse_vein(v: dict, path: Path, mats: Materials) -> VeinStyle:
    mats[v["material"]]
    need(float(v["per_10k"]) >= 0, path, "fill.veins", "rate must be >= 0")
    lmin, lmax = _pair(v["length"], path, "fill.veins.length")
    tmin, tmax = _pair(v["thickness"], path, "fill.veins.thickness")
    need(lmin >= 4 and tmin > 0, path, "fill.veins", "length must be >= 4 and thickness > 0")
    return VeinStyle(
        v["material"],
        float(v["per_10k"]),
        (int(lmin), int(lmax)),
        (tmin, tmax),
        int(v.get("buried", 0)),
    )


def _parse_feature(
    ft: dict, path: Path, mats: Materials, name: str, opt_key: str | None
) -> FeatureStyle:
    e = ft[name]
    need(float(e["attempts_per_10k"]) >= 0, path, f"features.{name}", "rate must be >= 0")
    opts = ()
    if opt_key:
        opts = _weighted(e[opt_key], "material", path, f"features.{name}.{opt_key}")
        for o in opts:
            mats[o.key]
            need(
                not (name == "pools" and o.key == "acid"),
                path,
                f"features.{name}.{opt_key}",
                "must not contain acid: acid only comes from barrels",
            )
    dmin, dmax = _pair(e["depth"], path, f"features.{name}.depth") if "depth" in e else (0, 0)
    rmin, rmax = _pair(e["radius"], path, f"features.{name}.radius") if "radius" in e else (0, 0)
    lining = e.get("lining") or {}
    if lining:
        mats[lining["material"]]
        need(int(lining["depth"]) >= 1, path, f"features.{name}.lining", "depth must be >= 1")
    return FeatureStyle(
        float(e["attempts_per_10k"]),
        dmin,
        dmax,
        int(e.get("max_area", 0)),
        rmin,
        rmax,
        opts,
        lining.get("material", ""),
        int(lining.get("depth", 0)),
    )


def _parse_markers(m: dict, path: Path, mats: Materials) -> MarkerStyle:
    items = _weighted(m["items"], "item", path, "markers.items", ITEM_KEYS)
    for it in items:
        need(
            (it.key == "bottle") == bool(it.extra),
            path,
            "markers.items",
            "'bottle' needs 'contents' (a material key) and no other item may have it",
        )
        if it.extra:
            mats[it.extra]
            need(
                it.extra != "acid",
                path,
                "markers.items",
                "must not lie around a bottle of acid: acid only comes from barrels",
            )
    return MarkerStyle(
        float(m["enemy_per_10k"]),
        _weighted(m["enemies"], "enemy", path, "markers.enemies", ENEMY_KEYS),
        float(m["item_per_10k"]),
        items,
    )


def _parse_encounters(e: dict, path: Path) -> EncounterStyle:
    pool = tuple(e["pool"])
    unknown = [i for i in pool if i not in ENCOUNTER_NODE]
    need(not unknown, path, "encounters.pool", f"has unknown encounter ids {unknown}")
    need(int(e["slots"]) >= 0, path, "encounters.slots", "must be >= 0")
    wmin, wmax = _pair(e["size"]["w"], path, "encounters.size.w")
    hmin, hmax = _pair(e["size"]["h"], path, "encounters.size.h")
    need(
        min(wmin, hmin) >= MIN_SLOT_SIZE,
        path,
        "encounters.size",
        f"must be at least {MIN_SLOT_SIZE} in both directions",
    )
    return EncounterStyle(int(e["slots"]), pool, wmin, wmax, hmin, hmax)


def _rate(d: dict, path: Path, name: str, a: str | None, b: str | None) -> Rate:
    """One entry of ``shape``: ``per_10k`` plus the size ranges named by ``a`` and ``b``."""
    need(float(d["per_10k"]) >= 0, path, f"shape.{name}", "rate must be >= 0")
    ra = _pair(d[a], path, f"shape.{name}.{a}") if a else (0, 0)
    rb = _pair(d[b], path, f"shape.{name}.{b}") if b else (0, 0)
    return Rate(float(d["per_10k"]), (int(ra[0]), int(ra[1])), (int(rb[0]), int(rb[1])))


def _parse_shape(d: dict, path: Path) -> ShapeStyle:
    spec = {
        "halls": ("w", "h"),
        "shafts": ("w", "len"),
        "passages": ("w", "len"),
        "alcoves": ("h", "depth"),
        "ledges": ("len", "thick"),
        "cracks": (None, "len"),
    }
    rates = {n: _rate(d[n], path, n, *keys) if n in d else Rate() for n, keys in spec.items()}
    wd = d.get("widen", {})
    need(int(wd.get("max", 0)) >= 0, path, "shape.widen.max", "must be >= 0")
    for name in ("halls", "shafts", "passages"):
        r = rates[name]
        need(
            r.per_10k == 0 or min(r.a) >= MIN_PLAYER_TUNNEL,
            path,
            f"shape.{name}",
            f"openings must be at least {MIN_PLAYER_TUNNEL} cells wide",
        )
    return ShapeStyle(int(wd.get("max", 0)), float(wd.get("scale", 36.0)), **rates)


def _parse_rooms(d: dict, path: Path) -> RoomsStyle:
    mmin, mmax = _pair(d["margin"], path, "rooms.margin")
    need(int(d["min_w"]) >= 40 and int(d["min_h"]) >= 30, path, "rooms", "rooms are too small")
    need(
        int(d["door_h"]) >= MIN_PLAYER_TUNNEL and int(d["door_w"]) >= MIN_PLAYER_TUNNEL,
        path,
        "rooms.door_w",
        f"doors must be at least {MIN_PLAYER_TUNNEL} cells so that the player fits",
    )
    need(mmin >= 3, path, "rooms.margin", "walls need at least 3 cells per side")
    return RoomsStyle(
        int(d["min_w"]),
        int(d["min_h"]),
        (int(mmin), int(mmax)),
        int(d["door_w"]),
        int(d["door_h"]),
        float(d.get("loops", 0.3)),
        int(d.get("ragged", 0)),
    )


def _parse_params(
    d: dict, path: Path, section: str, names: frozenset[str], mats: Materials, layout: str
) -> dict:
    """``decor`` / ``hazards``: known names, each a dict of numbers, [min, max] pairs or keys."""
    for name, params in d.items():
        where = f"{section}.{name}"
        need(name in names, path, where, f"is unknown (use one of {sorted(names)})")
        need(isinstance(params, dict), path, where, "must be an object")
        need(float(params.get("per_10k", 0)) >= 0, path, where, "rate must be >= 0")
        need(
            name not in ROOM_DECOR or layout == "rooms",
            path,
            where,
            "works on rooms: use it with the 'rooms' layout only",
        )
        for k, v in params.items():
            if k in ("material", "liquid", "crust_material"):
                mats[v]
            elif k == "weights":
                need(
                    isinstance(v, dict) and bool(v) and all(w > 0 for w in v.values()),
                    path,
                    f"{where}.weights",
                    "must map item keys to positive weights",
                )
                bad = [i for i in v if i not in ITEM_KEYS]
                need(not bad, path, f"{where}.weights", f"has unknown item keys {bad}")
            elif isinstance(v, list):
                _pair(v, path, f"{where}.{k}")
    return dict(d)


def _parse_supply(d: dict, path: Path, mats: Materials) -> SupplyStyle:
    """``supply``: deposits and bottles of recipe ingredients, and bowls (alchemy.py)."""
    ingredients = set(mats.with_tag("ingredient"))
    deposits = []
    for i, e in enumerate(d.get("deposits", [])):
        where = f"supply.deposits[{i}]"
        need(e["material"] in ingredients, path, where, "must name an ingredient material")
        form = e["form"]
        need(form in ("pile", "pool"), path, where, "form must be 'pile' or 'pool'")
        kind = mats.kinds[mats[e["material"]]]
        need(
            kind == ("powder" if form == "pile" else "liquid"),
            path,
            where,
            f"a {form} needs a {'powder' if form == 'pile' else 'liquid'}, not {kind}",
        )
        size = _pair(e["radius" if form == "pile" else "depth"], path, f"{where}.size")
        need(size[0] >= 2, path, f"{where}.size", "must be at least 2")
        need(int(e["count"]) >= 1, path, f"{where}.count", "must be at least 1")
        need(int(e["min_cells"]) >= 20, path, f"{where}.min_cells", "must be at least 20")
        deposits.append(
            DepositSpec(
                e["material"],
                form,
                int(e["count"]),
                int(e["min_cells"]),
                size,
                int(e.get("max_area", 0)),
                bool(e.get("optional", False)),
            )
        )
    bottles = []
    for i, e in enumerate(d.get("bottles", [])):
        contents = e.get("contents", "")
        need(
            contents == "" or contents in ingredients,
            path,
            f"supply.bottles[{i}].contents",
            "must be empty or an ingredient material",
        )
        need(int(e.get("count", 1)) >= 1, path, f"supply.bottles[{i}].count", "must be >= 1")
        bottles.append(BottleSpec(contents, int(e.get("count", 1))))
    need(int(d.get("bowls", 0)) >= 0, path, "supply.bowls", "must be >= 0")
    return SupplyStyle(tuple(deposits), tuple(bottles), int(d.get("bowls", 0)))


def _parse_biome(d: dict, path: Path, mats: Materials) -> Biome:
    need(d["format"] == FORMAT, path, "format", f"must be {FORMAT}")
    need(d["key"] == path.stem, path, "key", f"must equal the file name '{path.stem}'")
    need(d["slot"] in SLOT_NAMES, path, "slot", f"must be one of {SLOT_NAMES}")
    layout = d.get("layout", "tiles")
    need(layout in LAYOUTS, path, "layout", f"must be one of {LAYOUTS}")
    ft = d["features"]
    need(
        ("tile" in d) == (layout == "tiles"),
        path,
        "tile",
        "is required for the 'tiles' layout and not allowed for 'rooms'",
    )
    need(("rooms" in d) == (layout == "rooms"), path, "rooms", "belongs to the 'rooms' layout only")
    return Biome(
        d["key"],
        d["name_zh"],
        d["name_en"],
        int(d["layer"]),
        d["slot"],
        _parse_tile(d["tile"], path) if layout == "tiles" else None,
        _parse_fill(d["fill"], path, mats),
        _parse_feature(ft, path, mats, "pools", "liquids"),
        _parse_feature(ft, path, mats, "piles", "powders"),
        _parse_feature(ft, path, mats, "gas", "gases"),
        _parse_markers(d["markers"], path, mats),
        _parse_encounters(d["encounters"], path),
        layout,
        _parse_shape(d.get("shape", {}), path),
        _parse_rooms(d["rooms"], path) if layout == "rooms" else None,
        _parse_params(d.get("decor", {}), path, "decor", DECOR_NAMES, mats, layout),
        _parse_params(d.get("hazards", {}), path, "hazards", HAZARD_NAMES, mats, layout),
        _parse_supply(d.get("supply", {}), path, mats),
    )


def parse_biome(d: dict, path: Path, mats: Materials) -> Biome:
    """Parse and validate one biome file's content (``path`` is only used in messages)."""
    return parse_section(_parse_biome, d, path, mats)
