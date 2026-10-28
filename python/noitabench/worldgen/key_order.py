"""Post-generation check: the last part of the seal key lies in the last must-pass scene.

The key of the seal is two spells (``role: "breaker"``): the BOMB of E02 and the
EXPLOSIVE_PROJECTILE modifier of E12. Together they blast brick, so a player who holds both could
blast through the brick walls or the brick seam of a must-pass scene and skip it. The key must
therefore be complete only when nothing but the seal is left: ``biome_map.json`` names a ``last``
scene for a layer (E12 for layer 3), and this check asks, for every such layer, that

* the layer holds exactly one must-pass band scene with that id,
* every other must-pass band scene of the layer lies entirely above it (the bands are stacked
  down the main path, so "above" is "before" along it), and
* the breaker item the scene hands out lies inside its footprint, and no breaker item of the
  world lies below the scene's top edge except that one.

Marker data only: the grid is not looked at.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import BiomeMap
from .encounter_defs import load_encounters
from .world import World

if TYPE_CHECKING:  # checks.py imports this module
    from .checks import CheckReport


def _box(m: dict) -> dict:
    return m.get("footprint") or m["trigger"]


def _inside(it: dict, fp: dict) -> bool:
    return fp["x"] <= it["x"] < fp["x"] + fp["w"] and fp["y"] <= it["y"] < fp["y"] + fp["h"]


def check_key_order(world: World, bm: BiomeMap, rep: CheckReport) -> None:
    """Add a failure to ``rep`` for every layer whose ``last`` scene is not its deepest one.

    Statistic ``key_last``: ``{layer: encounter id}`` of the layers that were checked.
    """
    defs = load_encounters()
    bands = [
        m
        for m in world.markers
        if m["type"] == "encounter" and m["must_pass"] and m.get("biome") != "seal"
    ]
    breakers = [m for m in world.markers if m["type"] == "item" and m.get("role") == "breaker"]
    checked: dict[str, str] = {}
    for lay in bm.layers:
        if lay.last is None:
            continue
        checked[str(lay.layer)] = lay.last
        mine = [m for m in bands if m.get("layer") == lay.layer]
        last = [m for m in mine if m["encounter_id"] == lay.last]
        if len(last) != 1:
            rep.failures.append(
                f"layer {lay.layer}: {len(last)} must-pass scenes {lay.last}, exactly one is "
                "needed (it is the last of the layer)"
            )
            continue
        fp = _box(last[0])
        for m in mine:
            if m is not last[0] and _box(m)["y"] + _box(m)["h"] > fp["y"]:
                rep.failures.append(
                    f"layer {lay.layer}: must-pass scene {m['encounter_id']} (y "
                    f"{_box(m)['y']}..{_box(m)['y'] + _box(m)['h']}) is not above {lay.last} "
                    f"(y {fp['y']}): the seal key would be complete before it"
                )
        _check_breakers(rep, lay.layer, lay.last, fp, breakers, defs)
    rep.stats["key_last"] = checked


def _check_breakers(
    rep: CheckReport, layer: int, eid: str, fp: dict, breakers: list[dict], defs: dict
) -> None:
    """The scene's own breaker is in it, and no other breaker lies as deep."""
    own = {
        str(t["spell"])
        for t in defs[eid].markers.values()
        if t.get("role") == "breaker" and t.get("spell")
    }
    if not own:  # the scene hands out no part of the key: nothing to order
        return
    for it in breakers:
        if str(it.get("spell")) in own and not _inside(it, fp):
            rep.failures.append(
                f"layer {layer}: the {it.get('spell')} item at ({it['x']}, {it['y']}) is not "
                f"inside {eid}, the last scene of the layer"
            )
        elif str(it.get("spell")) not in own and it["y"] >= fp["y"]:
            rep.failures.append(
                f"layer {layer}: the {it.get('spell')} item at ({it['x']}, {it['y']}) lies at "
                f"or below the top of {eid} (y {fp['y']}): the key would be complete earlier"
            )
    if not any(str(it.get("spell")) in own for it in breakers):
        rep.failures.append(f"layer {layer}: no breaker item of {sorted(own)} in the world")
