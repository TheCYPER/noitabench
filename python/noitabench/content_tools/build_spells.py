"""Build `content/spells.json` (`cogbench-spells/0`): the 25 in-scope spells.

Sources (SPELL-R04, SPELL-R10): `spells.json` of the research data for what comes from the spell
Lua (mana, uses, draw counts, shot-state deltas, triggers); the extracted projectile XML files for
what the projectile does (speed, lifetime, damage, explosion), merged with the engine defaults of
SPELL-R05. The game files win over the wiki numbers in the research file; the wiki-derived fields
of the research file are only used as a cross-check, and the build fails when they disagree.

All damage values are *internal* units (player max HP 4.0 = 100 shown); observation code multiplies
by `GUI_HP_MULTIPLIER` = 25. Time is in frames (60 per second), lengths in px, speeds in px/s,
angles in degrees.

    python -m noitabench.content_tools.build_spells            # write content/spells.json
    python -m noitabench.content_tools.build_spells --check    # fail if the file is out of date
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from noitabench.content_tools.noita_xml import Entity, flag, load_entity, number

REPO = Path(__file__).resolve().parents[3]
RESEARCH = REPO / ".trellis" / "tasks" / "10-16-noita-cogbench" / "research"
GAME_FILES = RESEARCH / "raw" / "game"
DEFAULT_OUT = REPO / "content" / "spells.json"

FORMAT = "cogbench-spells/0"
DISPLAY_FACTOR = 25.0  # GUI_HP_MULTIPLIER: only used for the cross-check against the wiki values

# The 25 spells of v1-scope.md section 4, in that order. The order is the spell id: append only.
SPELLS: tuple[tuple[str, str], ...] = (
    ("LIGHT_BULLET", "火花弹"),
    ("BULLET", "魔法箭"),
    ("RUBBER_BALL", "弹跳爆发"),
    ("SLOW_BULLET", "能量球"),
    ("BOMB", "炸弹"),
    ("FIREBALL", "火球"),
    ("DIGGER", "挖掘弹"),
    ("EXPLOSION", "爆炸"),
    ("MATERIAL_WATER", "水"),
    ("MATERIAL_OIL", "油"),
    ("MATERIAL_ACID", "酸"),
    ("LIGHT_BULLET_TRIGGER", "带触发的火花弹"),
    ("LIGHT_BULLET_TIMER", "带计时的火花弹"),
    ("BURST_2", "双重"),
    ("BURST_3", "三重"),
    ("SPEED", "加速"),
    ("DAMAGE", "加伤害"),
    ("HEAVY_SHOT", "重击"),
    ("SPREAD_REDUCE", "减散射"),
    ("BOUNCE", "弹跳"),
    ("EXPLOSIVE_PROJECTILE", "爆炸弹"),
    ("FIRE_TRAIL", "火焰拖尾"),
    ("WATER_TRAIL", "水拖尾"),
    ("RECHARGE", "减充能"),
    ("MANA_REDUCE", "加法力"),
)

# cogbench extension (v1-scope.md section 5, lead decision 2026-10-27): modifiers that raise the max
# durability of the explosion of the projectile they modify (`shot.explosion_durability`; the wand
# applies the largest bonus among the modifiers of a shot, they do not stack). Noita has no such
# field, the numbers are ours: `BOMB` removes up to durability 11 and brickwork is 14, so the seal
# needs `[EXPLOSIVE_PROJECTILE, BOMB]` (11 + 3). Every other spell writes 0.
EXPLOSION_DURABILITY: dict[str, int] = {"EXPLOSIVE_PROJECTILE": 3}

# Status effects a spell can put on what it hits (the effect entity file -> our status key).
EFFECTS = {
    "data/entities/misc/effect_apply_wet.xml": "wet",
    "data/entities/misc/effect_apply_oiled.xml": "oiled",
    "data/entities/misc/effect_apply_on_fire.xml": "on_fire",
}

# Shot-state fields (`c.*` in the spell Lua) that the casting engine models, and the ones that are
# purely cosmetic. Anything else in a spell is a build error: nothing is dropped silently.
MODELLED_C_ADD = {
    "fire_rate_wait",
    "spread_degrees",
    "damage_projectile_add",
    "damage_explosion_add",
    "explosion_radius",
    "damage_critical_chance",
    "bounces",
    "trail_material_amount",
}
COSMETIC_C_ADD = {"screenshake", "gore_particles"}
COSMETIC_C_APPEND = {"extra_entities"}

# SPELL-R05 engine defaults for attributes a projectile XML leaves out.
DEFAULT_SPEED = 60.0
DEFAULT_GRAVITY = 400.0
DEFAULT_AIR_FRICTION = 0.55
DEFAULT_MASS = 0.05
DEFAULT_BOUNCE_ENERGY = 0.5
DEFAULT_LOW_VELOCITY_LIMIT = 50.0
DEFAULT_EXPLOSION_RADIUS = 20.0
DEFAULT_EXPLOSION_DAMAGE = 5.0
DEFAULT_RAY_ENERGY = 20000.0
DEFAULT_MAX_DURABILITY = 10.0
DEFAULT_CELL_PROBABILITY = 5.0


class BuildError(ValueError):
    """The research data does not match what the generator expects."""


def _num(value: float) -> float:
    """Round float noise away (0.12000000000000001) and avoid `-0.0`."""
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _num_or_int(value: float) -> float | int:
    rounded = _num(value)
    return int(rounded) if rounded == int(rounded) else rounded


def _load_research() -> dict[str, dict[str, Any]]:
    records = json.loads((RESEARCH / "spells.json").read_text(encoding="utf-8"))
    return {record["game_id"]: record for record in records}


def _split_list(text: str | None) -> list[str]:
    return [part for part in (text or "").split(",") if part]


def _shot(key: str, rec: dict[str, Any]) -> dict[str, Any]:
    """The deltas a played card applies to its shot state (WAND-R30..R33)."""
    raw = rec["action_effects_raw"]
    c_add, c_mul, c_set, c_append = raw["c_add"], raw["c_mul"], raw["c_set"], raw["c_append"]
    unknown = set(c_add) - MODELLED_C_ADD - COSMETIC_C_ADD
    if unknown:
        raise BuildError(f"{key}: unmodelled c.* additions {sorted(unknown)}")
    if c_set or raw["recharge_mul"] is not None or raw["recoil_set"] is not None:
        raise BuildError(f"{key}: set-mode shot deltas are not supported (WAND-R33)")
    if set(c_mul) - {"speed_multiplier"}:
        raise BuildError(f"{key}: unmodelled c.* multipliers {sorted(c_mul)}")
    if set(c_append) - {"game_effect_entities", "trail_material"} - COSMETIC_C_APPEND:
        raise BuildError(f"{key}: unmodelled c.* appends {sorted(c_append)}")

    effects = []
    for entity in _split_list(c_append.get("game_effect_entities")):
        if entity not in EFFECTS:
            raise BuildError(f"{key}: unknown game effect entity {entity}")
        effects.append(EFFECTS[entity])
    materials = _split_list(c_append.get("trail_material"))
    trail = []
    if materials:
        if len(materials) != 1 or "trail_material_amount" not in c_add:
            raise BuildError(f"{key}: expected exactly one trail material with an amount")
        trail.append({"material": materials[0], "amount": int(c_add["trail_material_amount"])})
    return {
        "spread": _num(c_add.get("spread_degrees", 0.0)),
        "speed_mul": _num(c_mul.get("speed_multiplier", 1.0)),
        "damage": _num(c_add.get("damage_projectile_add", 0.0)),
        "explosion_damage": _num(c_add.get("damage_explosion_add", 0.0)),
        "explosion_radius": _num(c_add.get("explosion_radius", 0.0)),
        "explosion_durability": EXPLOSION_DURABILITY.get(key, 0),
        "crit_chance": _num(c_add.get("damage_critical_chance", 0.0)),
        "bounces": int(c_add.get("bounces", 0)),
        "trail": trail,
        "effects": effects,
    }


def _trigger(key: str, rec: dict[str, Any]) -> dict[str, Any] | None:
    trigger = rec["trigger"]
    if trigger is None:
        return None
    kind = trigger["type"]
    if kind not in ("collision", "timer"):
        raise BuildError(f"{key}: trigger kind {kind!r} is not in scope")
    if trigger["count"] != 1:
        raise BuildError(f"{key}: trigger count {trigger['count']} is not supported")
    return {
        "kind": kind,
        "timer_frames": trigger["timer_frames"] if kind == "timer" else None,
        "payload_draws": int(trigger["draw_count"]),
    }


def _explosion(proj: dict[str, str], parts: dict[str, dict[str, str]]) -> dict[str, Any] | None:
    on_death = flag(proj, "on_death_explode", False)
    on_lifetime_out = flag(proj, "on_lifetime_out_explode", False)
    if not (on_death or on_lifetime_out):
        return None
    config = parts.get("config_explosion", {})
    probability = number(config, "create_cell_probability", DEFAULT_CELL_PROBABILITY)
    material = config.get("create_cell_material", "fire") if probability > 0 else None
    return {
        "radius": int(number(config, "explosion_radius", DEFAULT_EXPLOSION_RADIUS)),
        "damage": _num(number(config, "damage", DEFAULT_EXPLOSION_DAMAGE)),
        "ray_energy": int(number(config, "ray_energy", DEFAULT_RAY_ENERGY)),
        "max_durability": int(number(config, "max_durability_to_destroy", DEFAULT_MAX_DURABILITY)),
        "cell_material": material,
        "cell_percent": int(probability),
        "hole_destroy_liquid": flag(config, "hole_destroy_liquid", False),
        "on_death": on_death,
        "on_lifetime_out": on_lifetime_out,
        "dont_damage_shooter": flag(proj, "explosion_dont_damage_shooter", False),
    }


def _body(spell_type: str, entity: Entity, proj: dict[str, str]) -> str:
    if spell_type == "static_projectile":
        return "static"
    if proj.get("projectile_type") == "MATERIAL_PARTICLE":
        return "material_particle"
    if "PhysicsBodyComponent" in entity:
        return "thrown_body"
    return "projectile"


def _projectile(key: str, rec: dict[str, Any], entity: Entity) -> dict[str, Any]:
    """What a spawned projectile does (SPELL-R05 defaults applied, internal damage units)."""
    parts = entity["ProjectileComponent"]
    proj = parts["@"]
    velocity = entity.get("VelocityComponent", {}).get("@", {})
    body = _body(rec["type"], entity, proj)
    lifetime = number(proj, "lifetime", -1.0)
    if lifetime < 0:
        raise BuildError(f"{key}: projectiles with an infinite lifetime are not supported")
    hit_damage = number(proj, "damage", 1.0) + sum(
        float(value) for value in parts.get("damage_by_type", {}).values()
    )
    low_velocity = None
    if flag(proj, "die_on_low_velocity", False) and body != "static":
        low_velocity = _num_or_int(
            number(proj, "die_on_low_velocity_limit", DEFAULT_LOW_VELOCITY_LIMIT)
        )
    emit = None
    if flag(proj, "on_death_emit_particle", False):
        emit = {
            "material": proj["on_death_emit_particle_type"],
            "count": int(number(proj, "on_death_emit_particle_count", 1)),
        }
    convert = entity.get("MagicConvertMaterialComponent", {}).get("@", {})
    ignite_radius = (
        int(number(convert, "radius", 0)) if number(convert, "ignite_materials", 0) else 0
    )
    hp = entity.get("DamageModelComponent", {}).get("@", {}).get("hp")
    return {
        "body": body,
        "speed_min": _num_or_int(number(proj, "speed_min", DEFAULT_SPEED)),
        "speed_max": _num_or_int(number(proj, "speed_max", DEFAULT_SPEED)),
        "lifetime": int(lifetime),
        "lifetime_jitter": int(number(proj, "lifetime_randomness", 0)),
        "gravity": _num_or_int(number(velocity, "gravity_y", DEFAULT_GRAVITY)),
        "air_friction": _num_or_int(number(velocity, "air_friction", DEFAULT_AIR_FRICTION)),
        "mass": _num_or_int(number(velocity, "mass", DEFAULT_MASS)),
        "innate_spread": _num(math.degrees(number(proj, "direction_random_rad", 0.0))),
        "bounces": int(number(proj, "bounces_left", 0)),
        "bounce_energy": _num_or_int(number(proj, "bounce_energy", DEFAULT_BOUNCE_ENERGY)),
        "bounce_always": flag(proj, "bounce_always", False),
        # A thrown body (the bomb) is a physics body: touching terrain bounces it, only its fuse or
        # a hit on its hit points sets it off, whatever the engine default of the component says.
        "on_collision_die": False
        if body == "thrown_body"
        else flag(proj, "on_collision_die", True),
        "die_on_low_velocity": low_velocity,
        "die_on_liquid": flag(proj, "die_on_liquid_collision", False),
        "hit_damage": _num(hit_damage),
        "damage_scaled_by_speed": flag(proj, "damage_scaled_by_speed", False),
        "knockback": _num(number(proj, "knockback_force", 0.0)),
        "hp": None if hp is None else _num(float(hp)),
        "ignite_radius": ignite_radius,
        "emit": emit,
        "explosion": _explosion(proj, parts),
    }


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-3 * max(1.0, abs(a), abs(b))


def _cross_check(key: str, rec: dict[str, Any], spell: dict[str, Any]) -> None:
    """Compare with the wiki-derived fields of the research file (the game files win)."""
    shot, problems = spell["shot"], []

    def expect(label: str, ours: float, theirs: float | None) -> None:
        if not _close(ours, theirs or 0.0):
            problems.append(f"{label}: built {ours}, research {theirs}")

    delay = rec["cast_delay_modifier"]
    expect("cast_delay", spell["cast_delay"], delay["frames"] if delay else 0)
    recharge = rec["recharge_time_modifier"]
    expect("recharge", spell["recharge"], recharge["frames"] if recharge else 0)
    expect("recoil", spell["recoil"], rec["recoil"])
    expect("spread", shot["spread"], rec["spread_modifier"])
    expect("speed_mul", shot["speed_mul"], rec["speed_multiplier"] or 1.0)
    expect("bounces", shot["bounces"], rec["bounces_modifier"])
    expect("crit_chance", shot["crit_chance"], rec["crit_chance"])
    expect("explosion_radius", shot["explosion_radius"], rec["explosion_radius_modifier"])
    expect("damage", shot["damage"] * DISPLAY_FACTOR, rec["damage_modifier"].get("projectile"))
    expect(
        "explosion_damage",
        shot["explosion_damage"] * DISPLAY_FACTOR,
        rec["damage_modifier"].get("explosion"),
    )
    if sorted(e["material"] for e in shot["trail"]) != sorted(rec["trail_material"]):
        problems.append(f"trail: built {shot['trail']}, research {rec['trail_material']}")
    if len(shot["effects"]) != len(rec["game_effect_entities"]):
        problems.append(f"effects: built {shot['effects']}, research {rec['game_effect_entities']}")
    projectile = spell["projectile"]
    if projectile:
        wiki = rec["damage"]
        shown = sum(v for t, v in wiki.items() if t != "explosion")
        expect("hit_damage", projectile["hit_damage"] * DISPLAY_FACTOR, shown)
        explosion = projectile["explosion"]
        if explosion:
            expect("explosion.damage", explosion["damage"] * DISPLAY_FACTOR, wiki.get("explosion"))
            expect("explosion.radius", explosion["radius"], rec["explosion_radius"])
        speed = rec["projectile_speed"]
        if speed:
            expect("speed_min", projectile["speed_min"], speed["min"])
            expect("speed_max", projectile["speed_max"], speed["max"])
        if rec["lifetime"]:
            expect("lifetime", projectile["lifetime"], rec["lifetime"]["frames"])
    if problems:
        raise BuildError(f"{key}: disagrees with the research data: " + "; ".join(problems))


def _spell(key: str, name_zh: str, rec: dict[str, Any]) -> dict[str, Any]:
    spell_type = rec["type"]
    if spell_type not in ("projectile", "static_projectile", "modifier", "multicast", "material"):
        raise BuildError(f"{key}: spell type {spell_type!r} is not in scope")
    if EXPLOSION_DURABILITY.get(key, 0) and spell_type != "modifier":
        raise BuildError(f"{key}: only modifiers can raise the explosion durability")
    raw = rec["action_effects_raw"]
    draw = raw["draw"] or 0
    if draw != (rec["draw_count"] if rec["draw_scope"] == "same_cast" else 0):
        raise BuildError(f"{key}: draw count {draw} disagrees with the research data")
    has_projectile = spell_type in ("projectile", "static_projectile", "material")
    entity = load_entity(GAME_FILES, rec["projectile_xml"]["path"]) if has_projectile else None
    spell = {
        "key": key,
        "name_en": rec["name"],
        "name_zh": name_zh,
        "type": spell_type,
        "mana": int(rec["mana_drain"]),
        "max_uses": rec["max_uses"],
        "draw": int(draw),
        "trigger": _trigger(key, rec),
        "cast_delay": int(raw["c_add"].get("fire_rate_wait", 0)),
        "recharge": int(raw["recharge_add"] or 0),
        "recoil": _num(raw["recoil_add"] or 0.0),
        "shot": _shot(key, rec),
        "projectile": _projectile(key, rec, entity) if entity else None,
    }
    _cross_check(key, rec, spell)
    return spell


def build() -> dict[str, Any]:
    """The whole `content/spells.json` document."""
    research = _load_research()
    unknown = set(EXPLOSION_DURABILITY) - {key for key, _ in SPELLS}
    if unknown:
        raise BuildError(f"explosion durability bonus for spells not built: {sorted(unknown)}")
    spells = [_spell(key, name_zh, research[key]) for key, name_zh in SPELLS]
    return {
        "format": FORMAT,
        "source": "Noita game data via .trellis/tasks/10-16-noita-cogbench/research (SPELL-R04, R10)",
        "units": {
            "time": "frames (60 per second)",
            "length": "px",
            "speed": "px/s",
            "angle": "degrees",
            "damage": "internal units: player max HP 4.0 is shown as 100 (multiply by 25)",
            "mana": "mana points; negative cost adds mana",
        },
        "spells": spells,
    }


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m noitabench.content_tools.build_spells")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output file")
    parser.add_argument("--check", action="store_true", help="only compare with the existing file")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is out of date; re-run without --check", file=sys.stderr)
            return 1
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(SPELLS)} spells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
