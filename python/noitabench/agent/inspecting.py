"""`inspect`: a closer look at one thing, without letting time pass.

It returns exact facts a player could read off the thing - the material of a cell, what is in a
bottle (each material and its cells), the numbers on a spell card, the stats and spells of a wand
on the ground, the health and conditions of a creature - and nothing about what a material is
*like* (which family it belongs to, what it reacts with). Spell numbers are the ones a wand
editor shows. Damage is shown in HP (internal units times 25). A cell or a thing must be inside
the view (the extent of the ASCII map; a thing also needs a clear line of sight).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .content import Content
from .engine import Engine
from .errors import CommandError
from .vocab import FPS

DAMAGE_SCALE = 25


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Without the entries that say nothing (zero, empty, none)."""
    return {k: v for k, v in d.items() if v not in (0, 0.0, None, "", [], {}, False)}


def spell_info(content: Content, key: str, uses: int | None = None) -> dict[str, Any]:
    """The numbers of a spell card; `uses` is what is left on this card."""
    row: Mapping[str, Any] | None = content.spells.get(key)
    if row is None:
        return {"spell": key}
    shot, proj, trigger = row["shot"], row.get("projectile"), row.get("trigger")
    explosion = (proj or {}).get("explosion") or {}
    info: dict[str, Any] = {
        "spell": key,
        "name": row["name_en"],
        "type": row["type"],
        "cast_delay": row["cast_delay"],
        "recharge": row["recharge"],
        "draws": row["draw"],
        "spread": round(shot["spread"] + (proj or {}).get("innate_spread", 0.0), 2),
        "speed_multiplier": shot["speed_mul"] if shot["speed_mul"] != 1.0 else 0,
        "crit_chance": shot["crit_chance"],
        "bounces": shot["bounces"],
        "effects": list(shot["effects"]),
        "trail": [t["material"] for t in shot["trail"]],
    }
    if proj is not None:
        info.update(
            damage=round(proj["hit_damage"] * DAMAGE_SCALE, 1),
            speed=[proj["speed_min"], proj["speed_max"]],
            lifetime=proj["lifetime"],
            explosion_radius=explosion.get("radius", 0),
            explosion_damage=round(explosion.get("damage", 0.0) * DAMAGE_SCALE, 1),
            emits=(proj["emit"] or {}).get("material"),
        )
    else:  # a modifier or multicast: what it adds
        info.update(
            damage_added=round(shot["damage"] * DAMAGE_SCALE, 1),
            explosion_damage_added=round(shot["explosion_damage"] * DAMAGE_SCALE, 1),
            explosion_radius_added=shot["explosion_radius"],
        )
    if trigger:
        info["payload"] = _clean(
            {
                "when": trigger["kind"],
                "after_frames": trigger.get("timer_frames"),
                "spells": trigger["payload_draws"],
            }
        )
    info = _clean(info)
    info["mana"] = row["mana"]  # kept when 0 or negative
    limit = row["max_uses"]
    if limit is None:
        info["uses"] = "unlimited"
    else:
        info.update(uses_left=limit if uses is None else uses, uses_max=limit)
    return info


def wand_info(
    content: Content, index: int, wand: dict[str, Any], active: bool, *, numbers: bool = True
) -> dict[str, Any]:
    """A wand. With `numbers` every slot carries the numbers of its spell (what `inspect` shows);
    without, only the spell and the uses left (what the state shows)."""
    stats = wand["stats"]
    slots: list[dict[str, Any]] = []
    for i, s in enumerate(wand["slots"]):
        if s is None:
            slots.append({"slot": i, "spell": None})
        elif numbers:
            slots.append({"slot": i, **spell_info(content, s["spell"], s["uses"])})
        else:
            slots.append({"slot": i, "spell": s["spell"], "uses": s["uses"]})
    return {
        "what": "wand",
        "index": index,
        "active": active,
        "mana": round(wand["mana"], 1),
        "mana_max": stats["mana_max"],
        "mana_per_second": stats["mana_charge_speed"],
        "cast_delay": stats["cast_delay"],
        "recharge": stats["recharge"],
        "spells_per_cast": stats["spells_per_cast"],
        "capacity": stats["capacity"],
        "spread": stats["spread"],
        "shuffle": stats["shuffle"],
        "cooldown": wand["cooldown"],
        "always_cast": list(wand["always_cast"]),
        "slots": slots,
    }


def inspect(
    args: Mapping[str, Any],
    engine: Engine,
    content: Content,
    player: dict[str, Any],
    visible: list[dict[str, Any]],
) -> dict[str, Any]:
    """Answer one `inspect` command. Raises `CommandError` for things that are not there."""
    if "x" in args:
        return _inspect_cell(args["x"], args["y"], engine, player)
    if "entity" in args:
        return _inspect_entity(args["entity"], content, visible)
    if "wand" in args:
        return _inspect_wand(args, content, player)
    if "spell" in args:
        carried = player["spells"]
        i = args["spell"]
        if i >= len(carried):
            raise CommandError(
                "no_such_spell", f"inspect: you carry {len(carried)} spell card(s), no card {i}."
            )
        spell = carried[i]
        return {"what": "spell", "index": i, **spell_info(content, spell["spell"], spell["uses"])}
    return _inspect_bottle(args["bottle"], content, player)


def _inspect_cell(x: int, y: int, engine: Engine, player: dict[str, Any]) -> dict[str, Any]:
    if not engine.in_view(player, x, y) or not engine.in_world(x, y):
        raise CommandError("out_of_sight", f"inspect: ({x}, {y}) is not within sight.")
    cell = engine.cell(x, y)
    return {
        "what": "cell",
        "x": x,
        "y": y,
        "material": cell["material"],
        "burning": bool(cell["burning"]),
    }


def _inspect_entity(
    entity_id: int, content: Content, visible: list[dict[str, Any]]
) -> dict[str, Any]:
    e = next((v for v in visible if v["id"] == entity_id), None)
    if e is None:
        raise CommandError(
            "not_in_view", f"inspect: no creature or item with id {entity_id} is in view."
        )
    out: dict[str, Any] = {
        "what": "entity",
        "id": e["id"],
        "kind": e["kind"],
        "x": e["x"],
        "y": e["y"],
        "w": e["w"],
        "h": e["h"],
        "dx": e["dx"],
        "dy": e["dy"],
    }
    if e["hp_max"] > 0:
        out.update(hp=round(e["hp"], 1), hp_max=round(e["hp_max"], 1))
    if e["statuses"]:
        out["statuses"] = {k: round(v / FPS, 1) for k, v in e["statuses"].items()}
    if "contents" in e:  # a bottle: the exact mixture
        out["contents"] = [dict(part) for part in e["contents"]]
        out["amount"] = sum(part["amount"] for part in e["contents"])
    elif "wand" in e:  # a wand on the ground: what a wand editor shows
        wand = wand_info(content, 0, e["wand"], False)
        for name in ("what", "index", "active"):
            wand.pop(name)
        out["wand"] = wand
    elif e["kind"] == "spell":
        out["card"] = spell_info(content, e["detail"])
    elif e["detail"]:
        out["detail"] = e["detail"]
    return out


def _inspect_wand(
    args: Mapping[str, Any], content: Content, player: dict[str, Any]
) -> dict[str, Any]:
    wands, i = player["wands"], args["wand"]
    if i >= len(wands):
        raise CommandError("no_such_wand", f"inspect: you have {len(wands)} wand(s), no wand {i}.")
    info = wand_info(content, i, wands[i], i == player["active_wand"])
    if "slot" in args:
        slots = info["slots"]
        if args["slot"] >= len(slots):
            raise CommandError("no_such_slot", f"inspect: wand {i} has {len(slots)} slot(s).")
        return {"what": "wand_slot", "wand": i, **slots[args["slot"]]}
    return info


def _inspect_bottle(i: int, content: Content, player: dict[str, Any]) -> dict[str, Any]:
    bottles = player["bottles"]
    if i >= len(bottles):
        raise CommandError(
            "no_such_bottle", f"inspect: you carry {len(bottles)} bottle(s), no bottle {i}."
        )
    b = bottles[i]
    return {
        "what": "bottle",
        "index": i,
        "material": b["material"],  # the largest share
        "amount": b["amount"],
        "capacity": content.bottle_capacity,
        "active": i == player["active_bottle"],
        "contents": [dict(part) for part in b["contents"]],
    }
