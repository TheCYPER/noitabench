#!/usr/bin/env python3
"""
extract_spells.py - build research/spells.json from three sources:

  1. raw/game/gun_actions.lua          (canonical game data: ids, mana, uses, tiers,
                                         price, and the Lua `action` body that mutates
                                         the shot state `c`)
  2. raw/cargo_Spells_export_v2.json   (noita.wiki.gg Cargo table `Spells`, derived
                                         by the wiki from projectile XMLs: damage by
                                         type, speed, lifetime, radius, bounces ...)
  3. raw/all_spell_pages.json          (raw wikitext of every spell page; the
                                         {{Infobox spell}} carries params that are NOT
                                         stored in Cargo: knockback, bounceEnergy,
                                         homingCoeff, onCollisionDie, hitbox ...)
  4. raw/game/entities/**              (projectile XMLs, parsed with <Base> inheritance,
                                         to give exact raw values for the main projectile)
  5. raw/game/translations_en.json     (English names/descriptions for every $action_*)

Usage:  python3 scripts/extract_spells.py            (run from research/ dir)
Outputs: spells.json, spell_actions_lua.json, validation_report.json
"""
import json
import os
import re
import sys
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.abspath(os.path.join(HERE, ".."))
RAW = os.path.join(RESEARCH, "raw")
GAME = os.path.join(RAW, "game")
ENT = os.path.join(GAME, "entities")

DISPLAY_DAMAGE_MULTIPLIER = 25  # in-game UI shows XML damage * 25 (0.12 -> 3)

TYPE_MAP = {
    "ACTION_TYPE_PROJECTILE": "projectile",
    "ACTION_TYPE_STATIC_PROJECTILE": "static_projectile",
    "ACTION_TYPE_MODIFIER": "modifier",
    "ACTION_TYPE_DRAW_MANY": "multicast",
    "ACTION_TYPE_MATERIAL": "material",
    "ACTION_TYPE_OTHER": "other",
    "ACTION_TYPE_UTILITY": "utility",
    "ACTION_TYPE_PASSIVE": "passive",
}
WIKI_TYPE_MAP = {
    "Projectile": "projectile",
    "Static projectile": "static_projectile",
    "Projectile modifier": "modifier",
    "Multicast": "multicast",
    "Material": "material",
    "Other": "other",
    "Utility": "utility",
    "Passive": "passive",
}

# ----------------------------------------------------------------------------
# 1. gun_actions.lua
# ----------------------------------------------------------------------------

def strip_block_comments(src: str) -> str:
    src = re.sub(r"--\[\[.*?\]\]--", "", src, flags=re.S)
    src = re.sub(r"--\[\[.*?\]\]", "", src, flags=re.S)
    return src


def strip_line_comments(body: str) -> str:
    out = []
    for line in body.split("\n"):
        # remove "-- comment" unless inside a string (crude but fine for this file)
        if "--" in line:
            q = line.count('"')
            idx = line.find("--")
            if q % 2 == 0 and line[:idx].count('"') % 2 == 0:
                line = line[:idx]
        out.append(line)
    return "\n".join(out)


def parse_lua_value(v: str):
    v = v.strip().rstrip(",").strip()
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    if v.startswith("{") and v.endswith("}"):
        return [parse_lua_value(x) for x in re.findall(r'"[^"]*"|[-\d.]+', v)]
    if v.startswith("ACTION_TYPE_"):
        return v
    try:
        if re.fullmatch(r"-?\d+", v):
            return int(v)
        return float(v)
    except ValueError:
        return v


def parse_gun_actions(path):
    src = strip_block_comments(open(path, encoding="utf-8").read())
    entries = []
    # top-level entries: a line that is exactly "\t{" (optionally trailing ws) ... "\t},"
    for m in re.finditer(r"^\t\{[ \t]*\n(.*?)^\t\},[ \t]*$", src, flags=re.S | re.M):
        block = m.group(1)
        am0 = re.search(r"^\t\taction\s*=\s*function", block, flags=re.M)
        head = block[: am0.start()] if am0 else block
        meta = {}
        for line in head.split("\n"):
            line_nc = line.strip()
            if not line_nc or line_nc.startswith("--"):
                continue
            mm = re.match(r"([a-z_]+)\s*=\s*(.+?)\s*(?:--.*)?$", line_nc)
            if mm:
                k, v = mm.group(1), mm.group(2)
                meta[k] = parse_lua_value(v)
        am = re.search(r"action\s*=\s*function\s*\(([^)]*)\)(.*)\bend\s*,?\s*$", block, flags=re.S)
        body = am.group(2) if am else ""
        meta["_action_args"] = am.group(1).strip() if am else ""
        meta["_action_body"] = body.strip("\n")
        if "id" in meta:
            entries.append(meta)
    return entries


# ----------------------------------------------------------------------------
# 2. action body -> structured effects
# ----------------------------------------------------------------------------

BOILERPLATE = [
    # speed multiplier clamp
    re.compile(r"if\s*\(\s*c\.speed_multiplier\s*>=\s*20\s*\)\s*then\s*c\.speed_multiplier\s*=\s*math\.min\(\s*c\.speed_multiplier\s*,\s*20\s*\)\s*elseif\s*\(\s*c\.speed_multiplier\s*<\s*0\s*\)\s*then\s*c\.speed_multiplier\s*=\s*0\s*end", re.S),
    re.compile(r"if\s*\(?\s*c\.explosion_radius\s*<\s*0\s*\)?\s*then\s*c\.explosion_radius\s*=\s*0\s*end", re.S),
]
COMPLEX_MARKERS = re.compile(r"\b(if|for|while|deck\[|#deck|#hand|#discarded|Random\(|EntityGet|GameGet|math\.|local |return |SetRandomSeed|table\.)\b")


def num(s):
    s = s.strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else float(s)


def parse_action_body(body: str):
    b = strip_line_comments(body)
    for bp in BOILERPLATE:
        b = bp.sub("", b)
    fx = {
        "c_add": collections.OrderedDict(),
        "c_mul": collections.OrderedDict(),
        "c_set": collections.OrderedDict(),
        "c_append": collections.OrderedDict(),
        "recharge_add": None,
        "recharge_mul": None,
        "recoil_add": None,
        "recoil_set": None,
        "draw": None,
        "projectiles": [],
        "triggers": [],
    }
    for line in b.split("\n"):
        s = line.strip()
        if not s:
            continue
        m = re.match(r"c\.(\w+)\s*=\s*c\.(\w+)\s*([+\-*])\s*(-?[\d.]+)\s*$", s)
        if m and m.group(1) == m.group(2):
            k, op, v = m.group(1), m.group(3), num(m.group(4))
            if op == "+":
                fx["c_add"][k] = fx["c_add"].get(k, 0) + v
            elif op == "-":
                fx["c_add"][k] = fx["c_add"].get(k, 0) - v
            else:
                fx["c_mul"][k] = fx["c_mul"].get(k, 1) * v
            continue
        m = re.match(r"c\.(\w+)\s*=\s*c\.(\w+)\s*\.\.\s*\"([^\"]*)\"\s*$", s)
        if m and m.group(1) == m.group(2):
            fx["c_append"][m.group(1)] = fx["c_append"].get(m.group(1), "") + m.group(3)
            continue
        m = re.match(r"c\.(\w+)\s*=\s*(-?[\d.]+)\s*$", s)
        if m:
            fx["c_set"][m.group(1)] = num(m.group(2))
            continue
        m = re.match(r"c\.(\w+)\s*=\s*(true|false)\s*$", s)
        if m:
            fx["c_set"][m.group(1)] = m.group(2) == "true"
            continue
        m = re.match(r"c\.(\w+)\s*=\s*\"([^\"]*)\"\s*$", s)
        if m:
            fx["c_set"][m.group(1)] = m.group(2)
            continue
        m = re.match(r"current_reload_time\s*=\s*current_reload_time\s*(.+)$", s)
        if m:
            expr = m.group(1).replace("ACTION_DRAW_RELOAD_TIME_INCREASE", "0")
            if re.fullmatch(r"[\s\d.+\-]+", expr):
                fx["recharge_add"] = (fx["recharge_add"] or 0) + eval("0" + expr)
            elif re.fullmatch(r"\s*\*\s*[\d.]+\s*", expr):
                fx["recharge_mul"] = (fx["recharge_mul"] or 1) * num(expr.replace("*", ""))
            continue
        m = re.match(r"shot_effects\.recoil_knockback\s*=\s*shot_effects\.recoil_knockback\s*([+\-])\s*([\d.]+)\s*$", s)
        if m:
            v = num(m.group(2)) * (1 if m.group(1) == "+" else -1)
            fx["recoil_add"] = (fx["recoil_add"] or 0) + v
            continue
        m = re.match(r"shot_effects\.recoil_knockback\s*=\s*([\d.]+)\s*$", s)
        if m:
            fx["recoil_set"] = num(m.group(1))
            continue
        m = re.match(r"draw_actions\(\s*(\d+|#deck)\s*,", s)
        if m:
            fx["draw"] = "all_remaining" if m.group(1) == "#deck" else int(m.group(1))
            continue
        m = re.match(r"add_projectile\(\s*\"([^\"]+)\"", s)
        if m:
            fx["projectiles"].append(m.group(1))
            continue
        m = re.match(r"add_projectile_trigger_hit_world\(\s*(\"([^\"]+)\"|\w+)\s*,\s*(\d+)", s)
        if m:
            fx["triggers"].append({"type": "collision", "projectile": m.group(2) or "<next projectile in deck>", "timer_frames": None, "draw_count": int(m.group(3))})
            continue
        m = re.match(r"add_projectile_trigger_timer\(\s*(\"([^\"]+)\"|\w+)\s*,\s*(\d+)\s*,\s*(\d+)", s)
        if m:
            fx["triggers"].append({"type": "timer", "projectile": m.group(2) or "<next projectile in deck>", "timer_frames": int(m.group(3)), "draw_count": int(m.group(4))})
            continue
        m = re.match(r"add_projectile_trigger_death\(\s*(\"([^\"]+)\"|\w+)\s*,\s*(\d+)", s)
        if m:
            fx["triggers"].append({"type": "death", "projectile": m.group(2) or "<next projectile in deck>", "timer_frames": None, "draw_count": int(m.group(3))})
            continue
    fx["complex_logic"] = bool(COMPLEX_MARKERS.search(b))
    return fx


# ----------------------------------------------------------------------------
# 3. wiki infobox parsing
# ----------------------------------------------------------------------------

def parse_infobox(txt):
    start = txt.find("{{Infobox spell")
    if start < 0:
        return None
    j = start + 2
    depth = 1
    while j < len(txt) and depth > 0:
        if txt.startswith("{{", j):
            depth += 1
            j += 2
            continue
        if txt.startswith("}}", j):
            depth -= 1
            j += 2
            continue
        j += 1
    inner = txt[start + len("{{Infobox spell"): j - 2]
    parts, depth, cur, k = [], 0, "", 0
    while k < len(inner):
        if inner.startswith("{{", k) or inner.startswith("[[", k):
            depth += 1
            cur += inner[k:k + 2]
            k += 2
            continue
        if inner.startswith("}}", k) or inner.startswith("]]", k):
            depth -= 1
            cur += inner[k:k + 2]
            k += 2
            continue
        if inner[k] == "|" and depth == 0:
            parts.append(cur)
            cur = ""
            k += 1
            continue
        cur += inner[k]
        k += 1
    parts.append(cur)
    params = {}
    for p in parts[1:]:
        if "=" in p:
            key, val = p.split("=", 1)
            params[key.strip()] = val.strip()
    return params


def split_variants(params):
    """{{Infobox spell}} holds up to 8 variants: name, name2, name3 ... -> list of dicts."""
    variants = {}
    for k, v in params.items():
        m = re.fullmatch(r"([A-Za-z ]+?)(\d*)", k)
        if not m:
            continue
        base, n = m.group(1), m.group(2) or "1"
        variants.setdefault(n, {})[base] = v
    common = variants.get("1", {})
    out = []
    for n, d in sorted(variants.items(), key=lambda x: int(x[0])):
        if "id" not in d:
            continue
        rec = dict(d)
        for ck in ("type", "baseName", "commonTags", "sortKey"):
            if ck in common and ck not in rec:
                rec[ck] = common[ck]
        out.append(rec)
    return out


def wikitext_to_plain(s):
    if s is None:
        return None
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#039;", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


# ----------------------------------------------------------------------------
# 4. projectile XML parsing with <Base file=...> inheritance
# ----------------------------------------------------------------------------

_xml_cache = {}


def load_xml_components(game_path):
    """Return ordered list of (component_name, attrs, children_attrs) for an entity file,
    resolving <Base file=...> inheritance (base first, then overrides, then own)."""
    if game_path in _xml_cache:
        return _xml_cache[game_path]
    local = os.path.join(ENT, game_path.replace("data/entities/", ""))
    if not os.path.isfile(local):
        _xml_cache[game_path] = None
        return None
    s = open(local, encoding="utf-8", errors="replace").read()
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    comps = []
    # Base blocks
    for bm in re.finditer(r"<Base\s+file=\"([^\"]+)\"\s*>(.*?)</Base>", s, flags=re.S):
        base = load_xml_components(bm.group(1)) or []
        over = _components_from_text(bm.group(2))
        merged = [dict(c) for c in base]
        for o in over:
            hit = next((c for c in merged if c["name"] == o["name"]), None)
            if hit:
                hit["attrs"] = {**hit["attrs"], **o["attrs"]}
                hit["children"] = {**hit["children"], **o["children"]}
            else:
                merged.append(o)
        comps.extend(merged)
    s_nobase = re.sub(r"<Base\s+file=\"[^\"]+\"\s*>.*?</Base>", "", s, flags=re.S)
    s_nobase = re.sub(r"<Base\s+file=\"[^\"]+\"\s*/>", "", s_nobase)
    comps.extend(_components_from_text(s_nobase))
    tags = re.search(r"<Entity[^>]*\btags=\"([^\"]*)\"", s)
    comps.append({"name": "_entity", "attrs": {"tags": tags.group(1) if tags else ""}, "children": {}})
    _xml_cache[game_path] = comps
    return comps


def _components_from_text(txt):
    comps = []
    for m in re.finditer(r"<([A-Z][A-Za-z0-9]*Component)\b([^>]*)>(.*?)</\1>|<([A-Z][A-Za-z0-9]*Component)\b([^>]*)/>", txt, flags=re.S):
        if m.group(1):
            name, attrtxt, inner = m.group(1), m.group(2), m.group(3)
        else:
            name, attrtxt, inner = m.group(4), m.group(5), ""
        attrs = dict(re.findall(r"([\w.]+)=\"([^\"]*)\"", attrtxt))
        children = {}
        for cm in re.finditer(r"<([a-z_]+)\b([^>]*)>", inner):
            children[cm.group(1)] = dict(re.findall(r"([\w.]+)=\"([^\"]*)\"", cm.group(2)))
        comps.append({"name": name, "attrs": attrs, "children": children})
    return comps


def to_num(v):
    if v is None:
        return None
    try:
        return int(v) if re.fullmatch(r"-?\d+", v) else float(v)
    except ValueError:
        return v


def summarize_projectile_xml(game_path):
    comps = load_xml_components(game_path)
    if comps is None:
        return None
    pc = next((c for c in comps if c["name"] == "ProjectileComponent"), None)
    vc = next((c for c in comps if c["name"] == "VelocityComponent"), None)
    ent_tags = []
    for c in comps:
        if c["name"] == "_entity":
            for t in c["attrs"].get("tags", "").split(","):
                if t and t not in ent_tags:
                    ent_tags.append(t)
    out = {"path": game_path, "entity_tags": ",".join(ent_tags) or None,
           "components": sorted(set(c["name"] for c in comps if c["name"] != "_entity"))}
    if pc:
        a = pc["attrs"]
        keys = ["speed_min", "speed_max", "lifetime", "lifetime_randomness", "damage", "damage_every_x_frames",
                "damage_scaled_by_speed", "explosion_dont_damage_shooter", "on_collision_die", "on_death_explode",
                "on_lifetime_out_explode", "penetrate_entities", "penetrate_world", "collide_with_entities",
                "collide_with_world", "friendly_fire", "bounces_left", "bounce_always", "bounce_energy",
                "bounce_at_any_angle", "knockback_force", "direction_random_rad", "lob_min", "lob_max", "friction",
                "ground_penetration_max_durability_to_destroy", "die_on_low_velocity", "die_on_low_velocity_limit",
                "do_moveto_update", "physics_impulse_coeff", "velocity_sets_scale", "velocity_sets_rotation",
                "camera_shake_when_shot", "hit_entities_only_with_tag", "collide_with_shooter_frames",
                "ragdoll_force_multiplier", "projectile_file"]
        out["projectile"] = {k: to_num(a[k]) for k in keys if k in a}
        if "damage_by_type" in pc["children"]:
            out["damage_by_type_raw"] = {k: to_num(v) for k, v in pc["children"]["damage_by_type"].items()}
        if "config_explosion" in pc["children"]:
            e = pc["children"]["config_explosion"]
            ekeys = ["damage", "explosion_radius", "ray_energy", "max_durability_to_destroy", "hole_enabled",
                     "damage_mortals", "create_cell_material", "create_cell_probability", "hole_destroy_liquid",
                     "knockback_force", "physics_explosion_power.min", "physics_explosion_power.max",
                     "explosion_sprite", "hole_image", "light_enabled", "sparks_enabled", "stains_enabled"]
            out["explosion"] = {k: to_num(e[k]) for k in ekeys if k in e}
    if vc:
        a = vc["attrs"]
        out["velocity"] = {k: to_num(a[k]) for k in ["gravity_y", "gravity_x", "air_friction", "mass", "terminal_velocity", "affect_physics_bodies", "apply_terminal_velocity"] if k in a}
    for name in ["HomingComponent", "LightningComponent", "AreaDamageComponent", "LifetimeComponent", "HitEffectComponent",
                 "MagicConvertMaterialComponent", "CellEaterComponent", "MaterialSuckerComponent", "VerletWeaponComponent",
                 "ExplosionComponent", "GameAreaEffectComponent", "LaserEmitterComponent", "DamageModelComponent",
                 "PhysicsImageShapeComponent", "PhysicsBodyComponent", "MaterialAreaCheckerComponent", "LoadEntitiesComponent",
                 "TeleportComponent", "ProjectileComponent"]:
        if name == "ProjectileComponent":
            continue
        for c in comps:
            if c["name"] == name:
                out.setdefault("other_components", []).append({"name": name, "attrs": {k: to_num(v) for k, v in c["attrs"].items() if not k.startswith("_")}})
    luas = [c["attrs"].get("script_source_file") for c in comps if c["name"] == "LuaComponent" and c["attrs"].get("script_source_file")]
    if luas:
        out["lua_scripts"] = luas
    pem = [c["attrs"].get("emitted_material_name") for c in comps if c["name"] == "ParticleEmitterComponent" and c["attrs"].get("create_real_particles") == "1"]
    if pem:
        out["emits_real_materials"] = sorted(set(pem))
    return out


# ----------------------------------------------------------------------------
# 5. merge
# ----------------------------------------------------------------------------

def frames_to_seconds(fr):
    return None if fr is None else round(fr / 60.0, 4)


def build():
    actions = parse_gun_actions(os.path.join(GAME, "gun_actions.lua"))
    tr = json.load(open(os.path.join(GAME, "translations_en.json"), encoding="utf-8"))
    cargo = json.load(open(os.path.join(RAW, "cargo_Spells_export_v2.json"), encoding="utf-8"))
    cargo_by_id = {r["id"]: r for r in cargo}
    pages = json.load(open(os.path.join(RAW, "all_spell_pages.json"), encoding="utf-8"))
    infobox_by_id = {}
    for title, txt in pages.items():
        p = parse_infobox(txt)
        if not p:
            continue
        for v in split_variants(p):
            v["_page"] = title
            infobox_by_id[v["id"].strip()] = v

    spells, lua_bodies, report = [], {}, {"mismatches": [], "not_on_wiki": [], "wiki_only": [], "xml_missing": []}
    game_ids = set()
    for a in actions:
        gid = a["id"]
        game_ids.add(gid)
        fx = parse_action_body(a["_action_body"])
        lua_bodies[gid] = a["_action_body"]
        w = cargo_by_id.get(gid)
        ib = infobox_by_id.get(gid, {})
        if w is None:
            report["not_on_wiki"].append(gid)
        name_key = (a.get("name") or "").lstrip("$").replace("action_", "", 1)
        desc_key = (a.get("description") or "").lstrip("$").replace("actiondesc_", "", 1)
        ingame_name = tr["names"].get(name_key)
        ingame_desc = tr["descs"].get(desc_key)
        mana = a.get("mana", 10)
        if mana is None:
            mana = 10
        max_uses = a.get("max_uses")
        stype = TYPE_MAP.get(a.get("type"), a.get("type"))

        # does this spell put a projectile entity into the shot?  If not, the wiki's
        # damage*/radius columns describe a MODIFIER amount, not a base projectile stat.
        adds_projectile = bool(fx["projectiles"] or fx["triggers"] or (isinstance(a.get("related_projectiles"), list) and a.get("related_projectiles")))
        # --- damage by type (display units) from wiki; omit zero/None
        dmg = {}
        dmg_mod_wiki = {}
        if w:
            for wk, ok in [("damageProjectile", "projectile"), ("damageExplosion", "explosion"), ("damageFire", "fire"),
                           ("damageElectric", "electricity"), ("damageIce", "ice"), ("damageSlice", "slice"),
                           ("damageDrill", "drill"), ("damageMelee", "melee"), ("damageHoly", "holy"),
                           ("damageHealing", "healing")]:
                v = w.get(wk)
                if v in (None, 0, "0", "=0"):
                    continue
                (dmg if adds_projectile else dmg_mod_wiki)[ok] = v
        # --- damage modifiers from action (display units)
        dmg_mod = {}
        for ck, ok in [("damage_projectile_add", "projectile"), ("damage_explosion_add", "explosion"), ("damage_fire_add", "fire"),
                       ("damage_electricity_add", "electricity"), ("damage_ice_add", "ice"), ("damage_slice_add", "slice"),
                       ("damage_drill_add", "drill"), ("damage_melee_add", "melee"), ("damage_healing_add", "healing"),
                       ("damage_curse_add", "curse")]:
            if ck in fx["c_add"]:
                dmg_mod[ok] = round(fx["c_add"][ck] * DISPLAY_DAMAGE_MULTIPLIER, 4)
        if "damage_null_all" in fx["c_set"] or "damage_null_all" in fx["c_add"]:
            dmg_mod["null_all"] = fx["c_set"].get("damage_null_all", fx["c_add"].get("damage_null_all"))
        for k, v in dmg_mod_wiki.items():
            if k not in dmg_mod:
                dmg_mod[k] = v  # wiki-only (e.g. values applied through scripts / lightning_count)
        # explosion radius: base (projectile) vs modifier (no projectile)
        wiki_radius = w.get("radius") if w else None
        base_radius = wiki_radius if adds_projectile else None
        radius_mod = fx["c_add"].get("explosion_radius")
        if radius_mod is None and not adds_projectile and wiki_radius not in (None, 0):
            radius_mod = wiki_radius

        # --- cast delay (frames)
        cd_frames = None
        cd_mode = None
        if "fire_rate_wait" in fx["c_set"]:
            cd_frames, cd_mode = fx["c_set"]["fire_rate_wait"], "set"
        elif "fire_rate_wait" in fx["c_add"]:
            cd_frames, cd_mode = fx["c_add"]["fire_rate_wait"], "add"
        # --- recharge (frames)
        rc_frames = fx["recharge_add"]
        # --- spread
        spread_mod = fx["c_add"].get("spread_degrees")
        if "spread_degrees" in fx["c_set"]:
            spread_mod = {"set": fx["c_set"]["spread_degrees"]}
        # --- speed multiplier
        speed_mul = fx["c_mul"].get("speed_multiplier")
        # --- trigger
        trig = None
        if fx["triggers"]:
            t = fx["triggers"][0]
            trig = {"type": t["type"], "timer_frames": t["timer_frames"], "draw_count": t["draw_count"],
                    "count": len(fx["triggers"])}
        # --- projectile stats from wiki
        pspeed = None
        if w and (w.get("speedMin") is not None or w.get("speedMax") is not None):
            pspeed = {"min": w.get("speedMin"), "max": w.get("speedMax")}
        life = None
        if w and w.get("lifetime") is not None:
            life = {"frames": w["lifetime"], "random_plus_minus": w.get("lifetimeRandom") or 0}
            if w.get("lifetimeRandom"):
                life["min"] = w["lifetime"] - w["lifetimeRandom"]
                life["max"] = w["lifetime"] + w["lifetimeRandom"]
            if w.get("altLifetimeMin") is not None or w.get("altLifetimeMax") is not None:
                life["alt_component_lifetime"] = {"min": w.get("altLifetimeMin"), "max": w.get("altLifetimeMax")}
        # --- tiers
        tiers = [int(x) for x in str(a.get("spawn_level", "")).split(",") if x.strip() != ""]
        probs = [float(x) for x in str(a.get("spawn_probability", "")).split(",") if x.strip() != ""]
        # --- xml
        main_proj = None
        rp = a.get("related_projectiles")
        xml_path = None
        if isinstance(rp, list) and rp and isinstance(rp[0], str):
            xml_path = rp[0]
        elif fx["projectiles"]:
            xml_path = fx["projectiles"][0]
        elif fx["triggers"] and fx["triggers"][0]["projectile"].startswith("data/"):
            xml_path = fx["triggers"][0]["projectile"]
        if xml_path:
            main_proj = summarize_projectile_xml(xml_path)
            if main_proj is None:
                report["xml_missing"].append({"id": gid, "path": xml_path})

        # --- wiki extras from infobox (not in cargo)
        extras = {}
        for k in ["knockback", "bounceAlways", "bounceEnergy", "destroyLiquid", "health", "hitbox", "holeEnabled",
                  "homingCoeff", "homingMultiplier", "onCollisionDie", "onDeathExplode", "onLifeOutExplode",
                  "physicsImpulse", "safeExplosion", "terminalVelocity", "damageMortals", "hitEffect",
                  "aoeDmg", "aoeDmgType", "aoeDmgEveryX", "aoeTickRate", "aoeMinXYMaxXY", "aoeEntitiesWTag", "aoeDmgProjectile",
                  "air friction", "speed"]:
            if k in ib and ib[k] != "":
                extras[k.replace(" ", "_")] = to_num(ib[k]) if isinstance(ib[k], str) else ib[k]

        notes = []
        if cd_mode == "set":
            notes.append(f"cast delay is SET to {cd_frames} frames (overrides accumulated cast delay) rather than added")
        if "spread_degrees" in fx["c_set"]:
            notes.append(f"spread is SET to {fx['c_set']['spread_degrees']} degrees")
        if a.get("never_unlimited"):
            notes.append("never_unlimited: Unlimited Spells perk does not remove the use limit")
        if a.get("is_dangerous_blast"):
            notes.append("is_dangerous_blast: AI/wand-ghost treats this as a close-range blast")
        if a.get("recursive"):
            notes.append("recursive: subject to recursion_limit=2 when copied by Divide/Greek spells")
        if a.get("spawn_requires_flag"):
            notes.append(f"spawn requires progress flag '{a['spawn_requires_flag']}'")
        if fx["complex_logic"]:
            notes.append("action body contains conditional/loop logic; see spell_actions_lua.json for exact behaviour")
        if fx["draw"] == "all_remaining":
            notes.append("draws every remaining spell in the deck (#deck)")
        if len(fx["projectiles"]) > 1:
            notes.append(f"adds {len(fx['projectiles'])} projectile entities per cast: {fx['projectiles']}")
        if w and w.get("projectileCount"):
            notes.append(f"wiki projectileCount={w['projectileCount']} (number of projectiles spawned per cast)")
        if w and w.get("effect"):
            notes.append("wiki effect: " + (wikitext_to_plain(w["effect"]) or ""))
        if w and w.get("unlockCondition"):
            notes.append("unlock: " + (wikitext_to_plain(w["unlockCondition"]) or ""))

        rec = collections.OrderedDict()
        rec["id"] = gid.lower()
        rec["game_id"] = gid
        rec["name"] = (w["name"] if w else None) or ingame_name or gid
        rec["name_ingame"] = ingame_name
        rec["type"] = stype
        rec["description"] = ingame_desc or (w["description"] if w else None)
        rec["mana_drain"] = mana
        rec["max_uses"] = max_uses
        rec["never_unlimited"] = bool(a.get("never_unlimited", False))
        rec["damage"] = dmg
        rec["damage_modifier"] = dmg_mod
        rec["explosion_radius"] = base_radius
        rec["explosion_radius_modifier"] = radius_mod
        rec["projectile_speed"] = pspeed
        rec["lifetime"] = life
        rec["lifetime_modifier"] = fx["c_add"].get("lifetime_add")
        rec["spread_degrees"] = (w.get("spread") if w else None)
        rec["spread_modifier"] = spread_mod
        rec["cast_delay_modifier"] = {"frames": cd_frames, "seconds": frames_to_seconds(cd_frames), "mode": cd_mode} if cd_frames is not None else None
        rec["recharge_time_modifier"] = {"frames": rc_frames, "seconds": frames_to_seconds(rc_frames)} if rc_frames is not None else None
        rec["speed_multiplier"] = speed_mul
        rec["child_speed_multiplier"] = fx["c_mul"].get("child_speed_multiplier")
        rec["crit_chance"] = fx["c_add"].get("damage_critical_chance")
        rec["bounces"] = (w.get("bounces") if w else None)
        rec["bounces_modifier"] = fx["c_add"].get("bounces")
        rec["knockback"] = extras.get("knockback", (main_proj or {}).get("projectile", {}).get("knockback_force") if main_proj else None)
        rec["knockback_modifier"] = fx["c_add"].get("knockback_force")
        rec["recoil"] = fx["recoil_set"] if fx["recoil_set"] is not None else fx["recoil_add"]
        rec["trigger"] = trig
        if fx["draw"] is not None:
            rec["draw_count"] = fx["draw"]
            rec["draw_scope"] = "same_cast"
        elif trig:
            rec["draw_count"] = trig["draw_count"]
            rec["draw_scope"] = "trigger_payload"
        else:
            rec["draw_count"] = 0
            rec["draw_scope"] = None
        rec["adds_projectile"] = adds_projectile
        rec["pattern_degrees"] = fx["c_set"].get("pattern_degrees")
        rec["dampening"] = fx["c_mul"].get("dampening", fx["c_set"].get("dampening"))
        rec["gravity_modifier"] = fx["c_add"].get("gravity", fx["c_set"].get("gravity"))
        rec["friendly_fire"] = fx["c_set"].get("friendly_fire")
        rec["lightning_count"] = fx["c_add"].get("lightning_count")
        rec["screenshake"] = fx["c_add"].get("screenshake", fx["c_set"].get("screenshake"))
        rec["gore_particles"] = fx["c_add"].get("gore_particles")
        rec["ragdoll_fx"] = fx["c_set"].get("ragdoll_fx", fx["c_add"].get("ragdoll_fx"))
        rec["material"] = fx["c_set"].get("material")
        rec["material_amount"] = fx["c_add"].get("material_amount")
        rec["trail_material"] = [m for m in fx["c_append"].get("trail_material", "").split(",") if m]
        rec["trail_material_amount"] = fx["c_add"].get("trail_material_amount")
        rec["extra_entities"] = [m for m in fx["c_append"].get("extra_entities", "").split(",") if m]
        rec["game_effect_entities"] = [m for m in fx["c_append"].get("game_effect_entities", "").split(",") if m]
        rec["projectiles_added"] = fx["projectiles"]
        rec["triggers_added"] = fx["triggers"]
        rec["tier"] = {"spawn_levels": tiers, "spawn_probabilities": probs,
                       "spawn_requires_flag": a.get("spawn_requires_flag"),
                       "spawn_manual_unlock": bool(a.get("spawn_manual_unlock", False))}
        rec["price"] = a.get("price")
        rec["tags"] = [t.strip() for t in (w["tags"] if w else []) if t.strip()]
        rec["related_projectiles"] = rp if isinstance(rp, list) else None
        rec["related_extra_entities"] = a.get("related_extra_entities") if isinstance(a.get("related_extra_entities"), list) else None
        rec["custom_xml_file"] = a.get("custom_xml_file")
        rec["sprite"] = a.get("sprite")
        rec["sound_loop_tag"] = a.get("sound_loop_tag")
        rec["ai_never_uses"] = bool(a.get("ai_never_uses", False))
        rec["recursive"] = bool(a.get("recursive", False))
        rec["is_dangerous_blast"] = bool(a.get("is_dangerous_blast", False))
        rec["complex_logic"] = fx["complex_logic"]
        rec["action_effects_raw"] = {"c_add": fx["c_add"], "c_mul": fx["c_mul"], "c_set": fx["c_set"], "c_append": fx["c_append"],
                                     "recharge_add": fx["recharge_add"], "recharge_mul": fx["recharge_mul"],
                                     "recoil_add": fx["recoil_add"], "recoil_set": fx["recoil_set"], "draw": fx["draw"]}
        rec["projectile_xml"] = main_proj
        rec["wiki"] = {
            "page": w["_pageName"] if w else None,
            "variant_name": w["name"] if w else None,
            "type": WIKI_TYPE_MAP.get(w["type"]) if w else None,
            "cast_delay_s": w.get("castDelay") if w else None,
            "recharge_delay_s": w.get("rechargeDelay") if w else None,
            "spread_mod": w.get("spreadMod") if w else None,
            "speed_mod": w.get("speedMod") if w else None,
            "lifetime_mod": w.get("lifetimeMod") if w else None,
            "bounces_mod": w.get("bouncesMod") if w else None,
            "crit_chance": w.get("criticalChance") if w else None,
            "recoil": w.get("recoil") if w else None,
            "timer_lifetime": w.get("timerLifetime") if w else None,
            "draw": w.get("draw") if w else None,
            "pattern_degrees": w.get("pattern") if w else None,
            "speed_die_below": w.get("speedDie") if w else None,
            "dmg_every_x_frames": w.get("dmgEveryXFrames") if w else None,
            "hit_shooter_frames": w.get("hitShooterFrames") if w else None,
            "projectile_count": w.get("projectileCount") if w else None,
            "related_proj_count": w.get("relatedProjCount") if w else None,
            "max_durability_to_destroy": w.get("maxDuraToDestroy") if w else None,
            "ray_energy": w.get("rayEnergy") if w else None,
            "gravity": w.get("gravity") if w else None,
            "air_friction": w.get("airFriction") if w else None,
            "mass": w.get("mass") if w else None,
            "spell_tier": w.get("spellTier") if w else None,
            "spawn_probability": w.get("spawnProbability") if w else None,
            "unlock_condition": wikitext_to_plain(w.get("unlockCondition")) if w else None,
            "effect": wikitext_to_plain(w.get("effect")) if w else None,
            "infobox_extras": extras,
        }
        rec["notes"] = notes
        spells.append(rec)

        # --- cross validation
        if w:
            if w.get("manaDrain") != mana:
                report["mismatches"].append({"id": gid, "field": "mana", "game": mana, "wiki": w.get("manaDrain")})
            if (w.get("uses") or None) != (max_uses or None):
                report["mismatches"].append({"id": gid, "field": "max_uses", "game": max_uses, "wiki": w.get("uses")})
            if w.get("price") != a.get("price"):
                report["mismatches"].append({"id": gid, "field": "price", "game": a.get("price"), "wiki": w.get("price")})
            wt = [int(x) for x in (w.get("spellTier") or []) if str(x).strip() != ""]
            if wt != tiers:
                report["mismatches"].append({"id": gid, "field": "spawn_levels", "game": tiers, "wiki": wt})
            wp = [float(x) for x in (w.get("spawnProbability") or []) if str(x).strip() != ""]
            if wp != probs:
                report["mismatches"].append({"id": gid, "field": "spawn_probabilities", "game": probs, "wiki": wp})
            if WIKI_TYPE_MAP.get(w["type"]) != stype:
                report["mismatches"].append({"id": gid, "field": "type", "game": stype, "wiki": w["type"]})
            # cast delay seconds (wiki) vs frames (game); wiki strings like "=0.33" are "set" semantics
            wcd = w.get("castDelay")
            if cd_frames is not None and wcd not in (None, ""):
                wv = float(str(wcd).lstrip("="))
                if abs(wv - cd_frames / 60.0) > 0.011:
                    report["mismatches"].append({"id": gid, "field": "cast_delay", "game_frames": cd_frames, "wiki_s": wcd})
            elif (cd_frames is None) != (wcd in (None, "")):
                report["mismatches"].append({"id": gid, "field": "cast_delay_presence", "game_frames": cd_frames, "wiki_s": wcd})
            # modifier damage cross-check: wiki column vs action-derived (x25)
            for k, v in dmg_mod_wiki.items():
                av = dmg_mod.get(k)
                if av is not None and abs(float(av) - float(v)) > 0.01:
                    report["mismatches"].append({"id": gid, "field": "damage_modifier_" + k, "game_x25": av, "wiki": v})
            # damage cross-check vs XML
            if main_proj and main_proj.get("projectile", {}).get("damage") is not None and "projectile" in dmg:
                xd = main_proj["projectile"]["damage"] * DISPLAY_DAMAGE_MULTIPLIER
                if abs(xd - float(dmg["projectile"])) > 0.01 and not w.get("projectileCount"):
                    report["mismatches"].append({"id": gid, "field": "damage_projectile", "xml_x25": round(xd, 3), "wiki": dmg["projectile"]})
    report["wiki_only"] = sorted(set(cargo_by_id) - game_ids)

    order = {"projectile": 0, "static_projectile": 1, "modifier": 2, "multicast": 3, "material": 4, "utility": 5, "passive": 6, "other": 7}
    spells.sort(key=lambda r: (order.get(r["type"], 9), r["name"].lower()))
    json.dump(spells, open(os.path.join(RESEARCH, "spells.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(lua_bodies, open(os.path.join(RESEARCH, "spell_actions_lua.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump(report, open(os.path.join(RESEARCH, "validation_report.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    counts = collections.Counter(r["type"] for r in spells)
    print("spells:", len(spells))
    print("by type:", dict(counts))
    print("not on wiki:", report["not_on_wiki"])
    print("wiki only:", report["wiki_only"])
    print("xml missing:", report["xml_missing"])
    print("mismatches:", len(report["mismatches"]))
    for m in report["mismatches"][:60]:
        print("  ", m)
    print("complex_logic:", sum(1 for r in spells if r["complex_logic"]))


if __name__ == "__main__":
    build()
