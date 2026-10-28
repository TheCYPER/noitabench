#!/usr/bin/env python3
"""Build research/materials.json from the parsed materials.xml, the wiki Cargo
export, texture palettes and the wiki player-damage table.

Usage:
    python3 build_materials_json.py <research_dir> <palette_json>

Inputs (under <research_dir>/raw):
    materials_xml_parsed.json   (from parse_materials_xml.py)
    cargo_Materials.json        (wiki Cargo export, English names/effects/biomes)
Palette json: output of scripts/png_palette.py over data/materials_gfx/*.png
"""
import html
import json
import re
import sys
from collections import OrderedDict

SOURCE_XML = ("data/materials.xml as mirrored at "
              "https://github.com/NathanSnail/noitadata/blob/e469a926/data/materials.xml "
              "(commit 2024-04-23; file carries a Nolla comment dated 23.4.2024)")
SOURCE_WIKI = "https://noita.wiki.gg Cargo table 'Materials' (exported 2026-10-07)"

# Player material contact damage (display units) from https://noita.wiki.gg/wiki/Materials#Player_damage
# "Per frame, per pixel" displayed value; raw DamageModelComponent value = display / 25 (GUI_HP_MULTIPLIER).
PLAYER_DAMAGE_PER_FRAME_PER_PIXEL = {
    "acid": 0.125, "rock_static_cursed": 0.125, "magic_gas_hp_regeneration": -0.125,
    "rock_static_cursed_green": 0.100, "lava": 0.075, "poison": 0.025,
    "radioactive_gas": 0.025, "radioactive_gas_static": 0.025, "rock_static_radioactive": 0.025,
    "rock_static_poison": 0.025, "ice_radioactive_static": 0.025, "ice_radioactive_glass": 0.025,
    "ice_acid_static": 0.025, "ice_acid_glass": 0.025, "blood_cold": 0.0225,
    "blood_cold_vapour": 0.015, "cursed_liquid": 0.0125, "gold_radioactive": 0.005,
    "gold_static_radioactive": 0.005, "poo_gas": 0.00025,
}

# Stain-driven damage (not per-pixel contact damage). From Status Effects / Alchemy / Fire wiki pages.
STAIN_DAMAGE_NOTES = {
    "lava": "also applies On Fire! (2% max HP/s) on contact; Internal Fire if ingested",
    "radioactive_liquid": "Toxic stain: 2% max HP per second, never reduces below 2% HP",
    "radioactive_liquid_yellow": "Toxic stain: 2% max HP per second, never reduces below 2% HP",
    "radioactive_liquid_fading": "Toxic stain: 2% max HP per second, never reduces below 2% HP",
    "fire": "On Fire! status: 2% max HP per second, +15% move speed; extinguished by most liquids",
    "fire_blue": "On Fire! status: 2% max HP per second",
    "flame": "On Fire! status: 2% max HP per second",
    "liquid_fire": "always burning; ignites entities; Oiled stain",
}

# Curated behaviour notes from the wiki material pages (see materials.md Sources).
NOTES = {
    "air": "The empty cell. Reactions with 'air' are how materials decay/evaporate/grow.",
    "fire": "The fire cell. temperature_of_fire=100 is compared against neighbours' autoignition_temperature. Only material strictly required by the engine.",
    "flame": "Short-lived (lifetime 5) fire variant emitted by explosion smoke trails.",
    "fire_blue": "Blue fire produced by slime + Acceleratium/Levitatium/Hastium (with explosions).",
    "water": "Density 4. Extinguishes burning entities, turns lava to rock (+steam), purifies toxic sludge (13%), freezes to ice_static, boils to steam. Wet stain prevents ignition.",
    "water_ice": "Chilly Water (density 3.5): made from snow+water; freezes into ice_static much faster than water.",
    "water_salt": "Brine: fire + 2 brine -> salt + steam.",
    "water_swamp": "Swamp water: product of swamp/mud purifying toxic sludge; forms peat on air contact (6%).",
    "oil": "Density 1, floats on everything. burnable, fire_hp=500, autoignition 10 (ignites almost immediately), temperature_of_fire 95. Not electrically conductive. Oiled stain = slippery + very flammable. Submerging in oil extinguishes you because fire requires air.",
    "alcohol": "Whiskey (density 3.5). Burns 'almost instantly': fire/lava turns it into alcohol_gas (60%), which is burnable_fast. Reacts with slime -> smoke; with frog meat -> Berserkium.",
    "alcohol_gas": "Whiskey fumes; burnable_fast gas.",
    "lava": "Density 6 liquid, liquid_gravity 0.2, viscosity 10 (slow, viscous). Does NOT have burnable, but always_ignites_damagemodel=1 and temperature_of_fire=90, so it ignites burnable neighbours. Contact damage 0.075/frame/pixel (4.5 DPS/pixel). Reactions solidify it: water->rock_static, blood->lavarock_static, mud->sand_static, blood_cold->rock_hard, radioactive->rock_static_radioactive+radioactive_gas, poison->rock_static_poison+poison_gas. Melts [meltable] metals and eats [meltable_to_lava] rock (3%).",
    "acid": "Density 2.9. [acid] + [corrodible] -> acid + acid_gas at 50% (fast_reaction, blob 2): dissolves almost everything except glass/dense rock. Evaporates slowly on air (10%). Contact damage 0.125/frame/pixel (7.5 DPS per pixel, ~637 DPS submerged).",
    "acid_gas": "Flammable Gas: burnable_fast, fire_hp 1000, autoignition 1 (explosive deflagration). Lifetime 450 frames.",
    "blood": "Density 4.1 (sinks under water). Bloody stain prevents ignition. Lava+blood -> lavarock_static (volcanic rock). blood+poison -> slime+smoke. Freezes to ice_blood_static.",
    "blood_fading": "Player blood: evaporable_fast (45% on air contact), density 3.",
    "blood_cold": "Freezing Liquid: freezes [freezable] liquids into ice_static (90%, blob 3), evaporates into Freezing Vapour on air (20%). Contact damage 0.0225/frame/pixel.",
    "blood_cold_vapour": "Freezing Vapour: gas, lifetime 250, contact damage 0.015/frame/pixel.",
    "radioactive_liquid": "Toxic Sludge, density 3. Toxic stain (2% max HP/s). Purified by water (13%), swamp, mud, brine. Lava -> toxic rock + toxic gas.",
    "radioactive_gas": "Toxic Gas, lifetime 450, contact damage 0.025/frame/pixel.",
    "poison": "Child of radioactive_liquid; evaporates to poison_gas (15%, fast). Lava -> poisonous rock. Contact damage 0.025/frame/pixel.",
    "sand": "Powder (liquid_sand=1), density 6, hp 800, durability 4 (any digging spell removes it). liquid_gravity 0.9. meltable_to_lava_fast.",
    "sand_static": "Ground: static sand (liquid_sand=1, liquid_static=1). hp 19000, durability 10. Lava + mud -> sand_static.",
    "soil": "Powder, density 6, hp 2000, durability 10, viscosity 75, grows_grass. water+soil -> mud (5%).",
    "mud": "Powder, density 6. Purifies toxic sludge into swamp water; lava+mud -> ground.",
    "rock_static": "Standard terrain: hp 100000, durability 10, density 10, meltable_to_lava (lava eats it at 3%). Grows moss on air (1%).",
    "rock_hard": "Dense Rock: durability 12, not corrodible, not melted by lava. Produced by freezing liquid + lava.",
    "rock_static_grey": "Grey Rock (Coal Pits terrain).",
    "lavarock_static": "Volcanic Rock: blood + lava; immune to lava.",
    "coal": "Powder, density 6, hp 1000, durability 8. burnable with fire_hp 1000 (slowest common fuel), autoignition 94 (only ~6% ignition chance per check), temperature_of_fire 95. coal+fire -> fire+air (20%).",
    "coal_static": "Coal Vein: static, not burnable, hp 25000, durability 10.",
    "wood_static": "Static wood: hp 2000, durability 10, burnable, fire_hp 600, autoignition 85, temperature_of_fire 90.",
    "wood": "Box2D prop wood (crates, wheels): burnable, fire_hp 600, hp 3000, durability 9.",
    "wood_player": "Unused static wood; reacts with cement -> concrete.",
    "wood_burns_forever": "fire_hp 99999999 variant.",
    "wood_tree": "Giant Tree wood: hp 200000, durability 12, not burnable, not corrodible.",
    "gunpowder_explosive": "Explosive gunpowder (natural piles): burnable, autoignition 1, requires_oxygen 0, ExplosionConfig ray_energy 400000, cell_explosion_power 40, radius_min 8, explodes after 20 fire damage. Density 7, hp 1000.",
    "gunpowder": "Inert gunpowder (Gunpowder Trail spell): burns, no explosion.",
    "gunpowder_tnt": "TNT powder: fire_hp 200, explodes after 10 fire damage, ray_energy 400000.",
    "gunpowder_unstable": "Firecrackers: on_fire=1 (starts burning), fire_hp 300, autoignition 0, explodes after 10 fire damage, radius_min 8 (was 5 before Oct 23 2019).",
    "gunpowder_unstable_big": "Liquid Detonation product: cell_explosion_power 100, radius_min 20, ray_energy 800000, damage 0.6.",
    "burning_powder": "Child of salt: burnable, fire_hp 100, autoignition 0, requires_oxygen 0; burning_powder + [water] -> burning_powder + fire (20%).",
    "sodium": "Child of salt; sodium + [water] -> sodium + steam (50%) with an ExplosionConfig (ray_energy 50000): many small explosions.",
    "salt": "Powder; salt + water -> brine (5%).",
    "steam": "Gas, lifetime 1000 frames, density 1. Condenses back to water on [static] contact (3%).",
    "smoke": "Gas, lifetime 350 frames. Produced by burning (on_fire_smoke_material default) and many reactions.",
    "snow": "Powder, density 8, hp 1000, warmth_melts_to_material water; fire+snow -> steam (20%) or water (80%).",
    "snow_static": "Packed Snow: static, density 8.",
    "ice_static": "Ice: static, hp 30000, slippery, convert_to_box2d_material ice_glass (breaks into rigid shards), meltable_to_water, melts slowly on air (1%).",
    "ice": "Ice powder (Pakkasukko corpse), hp 5000.",
    "ice_glass": "Broken ice (Box2D rigid body), hp 10000, melts to water.",
    "steel_static": "Steel: static, hp 130000, durability 12, conductive, rusts on [water] contact (1% -> rust_static), melts with lava (meltable_metal_generic -> metal_sand_molten) or Concentrated Mana (-> steam, 25%).",
    "steel": "Box2D steel prop: hp 100000, meltable_metal -> steel_molten.",
    "steel_sand": "Steel powder (metal dust), density 8, hp 8000, does not melt.",
    "steel_molten": "Molten Metal: on_fire, always ignites, fire_hp 90000, density 2; resolidifies on [cold]/[water]/[frozen] (50%).",
    "gold": "Gold powder: density 9, hp 8000, durability 12, gfx_glow 127, conductive, meltable_metal -> gold_molten; Chaotic Polymorphine -> silver.",
    "gold_molten": "Molten Gold, density 5, always burning.",
    "glass": "Box2D solid (cell_type solid), hp 200, crackability 100 (shatters), solid_static_type 2, not corrodible.",
    "glass_static": "Static glass: convert_to_box2d_material glass_brittle on damage.",
    "brass": "Metal powder, density 8, hp 8000; brass+diamond -> purifying powder; copper+teleportatium -> brass+smoke; brass+[fire_strong] -> shock_powder.",
    "silver": "Metal powder, density 8, hp 8000, gfx_glow 127; silver+polymorphine -> copper+smoke; silver+copper+blood -> diamond+2 smoke (100%).",
    "copper": "Metal powder; copper+brass+water -> silver + smoke + smoke.",
    "diamond": "Powder, hp 200000, density 8; diamond+honey -> Ambrosia + poison (50%); diamond + chaotic polymorphine -> silver.",
    "fungi": "Fungus (powder, plant): burnable, fire_hp 60, autoignition 65, generates_smoke 20, gfx_glow 255. Grows into air (8% up, 30% down).",
    "fungi_creeping": "Mystery/creeping fungus: spreads into sand (50%) and toxic sludge.",
    "grass": "Powder plant; grows from [grows_grass] materials (2% into air).",
    "honey": "Static-ish powder (liquid_sand=1, density 10, liquid_gravity 0.2, viscosity 15, stickyness 1.0). meltable_by_fire: fire -> lava + smoke (100%). honey+diamond -> Ambrosia + poison.",
    "slime": "Density 5, liquid_slime=1, liquid_gravity 0.1 (flows slowly, bunches up), requires_oxygen 0. Extinguishes fire far better than water. Slimy stain slows 15-40%. slime + [magic_faster] -> fire_blue + steam with explosions (ray_energy 50000). unstable teleportatium + slime -> teleportatium.",
    "magic_liquid_polymorph": "Polymorphine: density 4.14, water-tagged, gfx_glow 150; only a few pixels needed for a Polymorph stain. + toxic sludge -> chaotic polymorphine (15%).",
    "magic_liquid_random_polymorph": "Chaotic Polymorphine: density 4.15.",
    "magic_liquid_unstable_polymorph": "Unstable Polymorphine: made from flummoxium + blood + oil (35%, blob 15).",
    "magic_liquid_teleportation": "Teleportatium: density 4.21, burnable (autoignition 10, temperature_of_fire 95, generates_smoke 250 -> burns into Freezing Vapour via evaporable_custom); + whiskey -> unstable teleportatium (21%); + concentrated mana -> fire (10%).",
    "magic_liquid_unstable_teleportation": "Unstable Teleportatium: density 4.43; + slime -> teleportatium (20%); + flummoxium -> orb_powder (Guiding Powder) + fire (100%).",
    "material_confusion": "Flummoxium: density 1.2; + berserkium -> pheromone (25%); + [sand_metal] -> levitatium (45%).",
    "magic_liquid_mana_regeneration": "Concentrated Mana: density 4.921; + water -> more mana (25%); + [meltable_metal]/[meltable_metal_generic]/gold props -> steam (25%) (melts steel safely).",
    "magic_liquid_berserk": "Berserkium: density 2.412; whiskey + frog meat -> berserkium (10%).",
    "magic_liquid_movement_faster": "Acceleratium: density 1.1, tag magic_faster; + levitatium -> hastium (15%).",
    "magic_liquid_faster_levitation": "Levitatium: density 1.11, tag magic_faster.",
    "magic_liquid_faster_levitation_and_movement": "Hastium: density 1.091, tag magic_faster.",
    "magic_liquid_protection_all": "Ambrosia: density 5.12; stain blocks all damage.",
    "magic_liquid_hp_regeneration": "Healthium: density 5.53, tag regenerative; + purifying powder or lava -> unstable gunpowder/healium.",
    "magic_liquid_hp_regeneration_unstable": "Lively Concoction: per-seed random 3-ingredient recipe; evaporates quickly.",
    "midas_precursor": "Alchemic Precursor: per-seed random recipe; + [meat] -> Draught of Midas (100%, fast); + lava -> Gas of Midas (80%).",
    "midas": "Draught of Midas: midas + [alchemy] -> midas + gold (100%, fast, blob 3).",
    "purifying_powder": "purifying_powder + [impure] -> water (80%, blob 2); + lava/[regenerative] -> gunpowder_unstable.",
    "cement": "Sets to concrete_static on air (90%, req_lifetime 300) or water (100%); fire + 2 cement -> concrete.",
    "concrete_static": "Concrete: durability 8 (wiki), set from cement.",
    "templebrick_static": "Holy Mountain brickwork: durability 14 (hardest common terrain), hp very high; corroding it angers the gods.",
    "meat": "Corpse meat (box2d/static variants); cooks via meat -> meat_warm -> meat_hot -> meat_done -> meat_burned when next to fire/lava + oil.",
    "meat_static": "Static meat: durability 9.",
    "fungisoil": "Fungal soil (Fungal Caverns ground). water + fungisoil -> swamp + soil (10%).",
    "moss": "Grows on rock_static top faces (1%).",
    "vine": "Grows into air: 60% up, 30% left/right.",
    "root": "Root: same growth rule as vine.",
    "plastic": "Plastic (box2d).",
    "liquid_fire": "Liquid Fire (cocktail): child of oil, on_fire=1, fire_hp 1,000,000, temperature_of_fire 150, tag fire_strong (melts metals at 30%), liquid_gravity 0.2, viscosity 9, flow_speed 0.3.",
    "liquid_fire_weak": "Weak liquid fire: fire_hp 2300.",
    "void_liquid": "Void Liquid: density 14.5 (densest); consumes toxic sludge and fungus into more void liquid (100%).",
    "cursed_liquid": "Greed-Cursed Liquid: contact damage 0.0125/frame/pixel; lava -> greed-cursed rock + steam.",
    "rock_static_cursed": "Cursed Rock: durability 14, contact damage 0.125/frame/pixel.",
    "rock_static_cursed_green": "Greed-Cursed Rock: contact damage 0.1/frame/pixel.",
    "spore": "Fungal spore powder: vanishes on [sand_ground] (90%) or air (2%).",
    "peat": "Peat: flammable powder formed from swamp water on air (6%); lava -> smoke.",
    "swamp": "Swamp: density 3.5; purifies toxic sludge into water_swamp (15%).",
    "urine": "Density 3; lava + urine -> Fool's Gold (templebrick_golden_static) + steam (70%).",
    "vomit": "Density 1; + any bone -> Diminution; lava + vomit -> acid (50%).",
    "milk": "Milk (2024): density 3.5; beer + milk -> molut (100%).",
    "beer": "Beer (2024): density 3.5.",
    "sima": "Sima (2024): lava + sima -> rock_static + fire (80%).",
    "juhannussima": "Juhannussima (2024): lava + juhannussima -> rock_static + fire (80%).",
    "pea_soup": "Pea Soup: density 5; lava + pea_soup -> liquid_fire (80%).",
    "cheese_static": "Cheese: durability 5.",
    "glue": "Glue: fire -> poison_gas (60%, fast).",
    "mimic_liquid": "Mimicium: mimics [any_liquid] it touches (engine tag).",
    "magic_gas_hp_regeneration": "Healium: gas that heals 0.125 HP/frame/pixel (negative damage).",
    "poo_gas": "Nauseating Gas: 0.00025/frame/pixel.",
    "wax": "Wax: meltable -> wax_molten with lava/fire; resolidifies on cold/water.",
    "wax_molten": "Molten wax: density 2, burning, fire_hp 90000.",
    "shock_powder": "Shock Powder: consumed on air contact (100%) spawning 7-frame electric charge entities.",
    "orb_powder": "Guiding Powder: on_fire, fire_hp 1000, tiny explosions (ray_energy 0, power 2, radius 4).",
    "metal_sand_molten": "Molten metal dust: product of lava/[fire_strong] + [meltable_metal_generic] (30%); -> metal_sand on [cold]/[water]/[frozen] (50%).",
    "rust_static": "Rusted Metal: durability 10 (diggable), product of steel + [water] (1%).",
    "steel_rusted_no_holes": "Rusted Steel: durability 11.",
    "steel_static_strong": "Extremely Dense Rock/Dense Steel class: durability 12-13.",
    "meteorite": "Meteorite (box2d): on_fire, fire_hp -1 (burns forever), solid_on_collision_explode with ray_energy 50000.",
    "cloud_slime": "Slime Mist: lifetime ~10 frames (very short).",
    "cloud_blood": "Blood Mist: lifetime 10 frames.",
    "aluminium": "Aluminium (robot bodies): meltable metal.",
    "endslime": "Hell Slime: density 5; lava + slime -> endslime (70%).",
}


def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        return float(s)
    except ValueError:
        return s


def argb_to_rgb(hexstr):
    """'AARRGGBB' (Noita wang/graphics colours) -> ([r,g,b], alpha)."""
    if not hexstr:
        return None, None
    h = hexstr.strip().lstrip("#").lower()
    if h in ("0", ""):
        return None, None
    if len(h) == 6:
        h = "ff" + h
    if len(h) != 8:
        return None, None
    try:
        a, r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
    except ValueError:
        return None, None
    return [r, g, b], a


def clean_effect(s):
    if not s:
        return None
    s = html.unescape(html.unescape(s))
    names = re.findall(r"\[\[Status Effects#[^|\]]*\|([^\]]+)\]\]", s)
    durs = re.findall(r"\((\d+s)\)", s)
    out = []
    for i, n in enumerate(names):
        out.append(n + (f" ({durs[i]})" if i < len(durs) else ""))
    if not out:
        txt = re.sub(r"<[^>]+>", "", s).strip()
        return txt or None
    return "; ".join(out)


def kind_of(r):
    ct = r.get("cell_type", "liquid")
    if ct == "fire":
        return "fire"
    if ct == "gas":
        return "gas"
    if ct == "solid":
        return "solid"
    if r.get("liquid_static") == "1":
        return "static"
    if r.get("liquid_sand") == "1":
        return "powder"
    return "liquid"


def main(research_dir, palette_json):
    raw = f"{research_dir}/raw"
    ms = json.load(open(f"{raw}/materials_xml_parsed.json"))
    cargo = json.load(open(f"{raw}/cargo_Materials.json"))
    palettes = json.load(open(palette_json))
    cargo_by_id = {}
    for row in cargo:
        if row.get("id"):
            cargo_by_id.setdefault(row["id"], row)

    out = []
    seen = set()
    for m in ms:
        name = m["name"]
        if name in seen:
            continue  # the XML defines 2 names twice; the first definition is used by the engine
        seen.add(name)
        r = m["resolved"]
        c = cargo_by_id.get(name, {})
        g = m["children"].get("Graphics", [{}])[0] if m["children"].get("Graphics") else {}
        kind = kind_of(r)
        ct = r.get("cell_type", "liquid")
        color_rgb, alpha = argb_to_rgb(g.get("color"))
        wang_rgb, wang_a = argb_to_rgb(r.get("wang_color"))
        tex = g.get("texture_file")
        pal = palettes.get(tex.split("/")[-1]) if tex else None
        palette = []
        if pal and "top" in pal:
            palette = [p["hex"] for p in pal["top"]]
        elif color_rgb:
            palette = ["#%02x%02x%02x" % tuple(color_rgb)]
        base_rgb = color_rgb
        if base_rgb is None and pal and "avg_hex" in pal:
            h = pal["avg_hex"].lstrip("#")
            base_rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
        if base_rgb is None and wang_rgb is not None:
            base_rgb = wang_rgb  # engine falls back to wang_color at full opacity

        cond = r.get("electrical_conductivity")
        if cond is None:
            cond_eff = 1 if (ct == "liquid" and r.get("liquid_sand", "0") == "0") else 0
        else:
            cond_eff = num(cond)

        burnable = r.get("burnable") == "1"
        fire_hp = num(r.get("fire_hp"))
        burns_into = r.get("on_fire_convert_to_material") or None
        if burnable or r.get("on_fire") == "1":
            if fire_hp == -1:
                burns_into_eff = "never consumed (fire_hp=-1)"
            else:
                burns_into_eff = burns_into or "air (engine default: cell removed when fire_hp is spent)"
        else:
            burns_into_eff = None

        dmg = PLAYER_DAMAGE_PER_FRAME_PER_PIXEL.get(name)
        damage = None
        if dmg is not None:
            damage = OrderedDict(
                per_frame_per_pixel_display=dmg,
                dps_per_pixel=round(dmg * 60, 4),
                dps_submerged_85px=round(dmg * 60 * 85, 2),
                raw_damagemodel_value=round(dmg / 25, 6),
                source="https://noita.wiki.gg/wiki/Materials#Player_damage",
            )
        if name in STAIN_DAMAGE_NOTES:
            damage = damage or OrderedDict()
            damage["status_effect"] = STAIN_DAMAGE_NOTES[name]

        exp = None
        if m["children"].get("ExplosionConfig"):
            e = m["children"]["ExplosionConfig"][0]
            exp = OrderedDict((k, num(v)) for k, v in e.items() if not k.startswith("_"))

        rec = OrderedDict()
        rec["id"] = name
        rec["name"] = c.get("name") or r.get("ui_name") or name
        rec["kind"] = kind
        rec["cell_type"] = ct
        rec["wiki_type"] = c.get("type")
        rec["parent"] = m["parent_chain"][0] if m["parent_chain"] else None
        rec["inherits_reactions"] = num(m.get("inherit_reactions"))
        rec["tags"] = m["tags"]
        rec["density"] = num(r.get("density", "1"))
        rec["durability"] = num(r.get("durability")) if r.get("durability") is not None else (num(c.get("durability")) if c.get("durability") not in (None, "") else 0)
        rec["hp"] = num(r.get("hp", "100"))
        rec["flammable"] = burnable
        rec["fire_hp"] = (fire_hp if fire_hp is not None else 0) if (burnable or r.get("on_fire") == "1") else fire_hp
        rec["fire_hp_is_engine_default"] = (burnable or r.get("on_fire") == "1") and fire_hp is None
        rec["starts_on_fire"] = r.get("on_fire") == "1"
        rec["burns_into"] = burns_into_eff
        rec["on_fire_convert_to_material_raw"] = burns_into
        rec["autoignition"] = num(r.get("autoignition_temperature", "100"))
        rec["temperature_of_fire"] = num(r.get("temperature_of_fire", "10"))
        rec["requires_oxygen"] = r.get("requires_oxygen", "1") == "1"
        rec["generates_smoke"] = num(r.get("generates_smoke", "0"))
        rec["generates_flames"] = num(r.get("generates_flames", "30"))
        rec["always_ignites_entities"] = r.get("always_ignites_damagemodel") == "1"
        rec["on_fire_flame_material"] = r.get("on_fire_flame_material") or None
        rec["on_fire_smoke_material"] = r.get("on_fire_smoke_material") or None
        rec["gravity"] = OrderedDict(
            liquid_gravity=num(r.get("liquid_gravity", "0.5")) if ct in ("liquid", "fire", "gas") else None,
            solid_gravity_scale=num(r.get("solid_gravity_scale", "1")) if ct == "solid" else None,
            gas_speed=num(r.get("gas_speed", "50")) if ct == "gas" else None,
            gas_upwards_speed=num(r.get("gas_upwards_speed", "100")) if ct == "gas" else None,
            gas_horizontal_speed=num(r.get("gas_horizontal_speed", "100")) if ct == "gas" else None,
            gas_downwards_speed=num(r.get("gas_downwards_speed", "90")) if ct == "gas" else None,
        )
        rec["dispersion"] = OrderedDict(
            liquid_viscosity=num(r.get("liquid_viscosity", "50")),
            liquid_flow_speed=num(r.get("liquid_flow_speed", "0.9")),
            liquid_damping=num(r.get("liquid_damping", "0.8")),
            liquid_slime=r.get("liquid_slime") == "1",
            liquid_sticks_to_ceiling=num(r.get("liquid_sticks_to_ceiling", "0")),
            stickyness=num(r.get("stickyness", "0")),
        ) if ct == "liquid" else None
        rec["lifetime_frames"] = num(r.get("lifetime", "0"))
        rec["color_rgb"] = base_rgb
        rec["color_alpha"] = alpha if alpha is not None else (255 if base_rgb else None)
        rec["graphics_color_argb"] = g.get("color")
        rec["texture_file"] = tex
        rec["palette"] = palette
        rec["palette_avg"] = pal.get("avg_hex") if pal else None
        rec["wang_color_argb"] = r.get("wang_color")
        rec["gfx_glow"] = num(r.get("gfx_glow", "0"))
        rec["gfx_glow_color"] = r.get("gfx_glow_color") or None
        rec["electrical_conductivity"] = cond_eff
        rec["slippery"] = r.get("slippery") == "1"
        rec["platform_type"] = num(r.get("platform_type", "-1"))
        rec["stainable"] = r.get("stainable", "1") == "1"
        rec["liquid_stains"] = num(r.get("liquid_stains", "0"))
        rec["solid"] = OrderedDict(
            solid_static_type=num(r.get("solid_static_type", "0")),
            crackability=num(r.get("crackability", "0")),
            solid_friction=num(r.get("solid_friction", "0.3")),
            solid_restitution=num(r.get("solid_restitution", "0.2")),
            solid_on_collision_explode=r.get("solid_on_collision_explode") == "1",
            solid_on_collision_convert=r.get("solid_on_collision_convert") == "1",
            solid_on_collision_material=r.get("solid_on_collision_material") or None,
            solid_break_to_type=r.get("solid_break_to_type") or None,
            solid_on_break_explode=r.get("solid_on_break_explode") == "1",
            solid_go_through_sand=r.get("solid_go_through_sand") == "1",
        ) if ct == "solid" else None
        rec["freezes_to"] = r.get("cold_freezes_to_material") or c.get("freezes") or None
        rec["cold_freezes_chance_rev"] = num(r.get("cold_freezes_chance_rev"))
        rec["melts_to"] = r.get("warmth_melts_to_material") or c.get("melts") or None
        rec["warmth_melts_chance_rev"] = num(r.get("warmth_melts_chance_rev"))
        rec["convert_to_box2d_material"] = r.get("convert_to_box2d_material") or None
        rec["break_into"] = c.get("breakInto") or None
        rec["explosion_config"] = exp
        rec["damage_to_entities"] = damage
        rec["stain_effect"] = clean_effect(c.get("stainEffect"))
        rec["submerge_effect"] = clean_effect(c.get("submergeEffect"))
        rec["ingest_effect"] = clean_effect(c.get("ingestEffect"))
        rec["danger"] = OrderedDict(
            fire=r.get("danger_fire") == "1", water=r.get("danger_water") == "1",
            poison=r.get("danger_poison") == "1", radioactive=r.get("danger_radioactive") == "1",
        )
        rec["biomes"] = [b for b in (c.get("biomes") or []) if b]
        rec["wiki_page"] = c.get("_pageName")
        rec["notes"] = NOTES.get(name)
        rec["xml_order"] = m["order"]
        rec["xml_element"] = m["xml_element"]
        rec["source"] = "materials.xml + wiki Cargo" if c else "materials.xml only (no wiki row)"
        out.append(rec)

    with open(f"{research_dir}/materials.json", "w") as f:
        json.dump(out, f, indent=1)
    from collections import Counter
    print(f"wrote {len(out)} materials; kinds: {Counter(o['kind'] for o in out)}")
    print(f"with curated notes: {sum(1 for o in out if o['notes'])}; with texture palette: {sum(1 for o in out if o['texture_file'])}")
    print(f"without wiki row: {[o['id'] for o in out if 'only' in o['source']]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
