#!/usr/bin/env python3
"""Build research/reactions.json and research/tags_index.json.

Usage:
    python3 build_reactions_json.py <research_dir>

reactions.json  : array of every <Reaction>/<ReqReaction> in materials.xml (in
                  file order, which is also engine priority order), normalised to
                  {input_a, input_b, input_c, output_a, output_b, output_c,
                  probability, ...extra attributes..., notes}, followed by a block
                  of engine-level rules (burning, freezing, lifetime, explosions)
                  that are NOT <Reaction> elements but behave like reactions.
tags_index.json : tag -> sorted list of material ids carrying that tag, so that
                  '[tag]' rules can be expanded. Includes the 3 engine tags.
"""
import json
import sys
from collections import OrderedDict, defaultdict

# Curated notes for key reactions (keyed by (in1,in2,in3,out1,out2)).
NOTES = {
    ("[acid]", "[corrodible]", "", "[acid]", "acid_gas"): "Acid eats anything tagged corrodible (most terrain, metals, wood, liquids); the corroded cell becomes Flammable Gas. fast_reaction=1, blob radius 2 on both outputs: each reaction converts a blob of radius 2 so acid tunnels quickly. Glass, rock_hard (Dense Rock) and wood_tree are not corrodible.",
    ("[acid]", "air", "", "acid_gas", "air"): "Acid slowly evaporates when exposed to air.",
    ("[fire]", "water", "", "[fire]", "steam"): "Water next to fire boils (20%). Note: this consumes the WATER, not the fire; large volumes are needed to smother burning fuel.",
    ("[lava]", "water", "", "rock_static", "steam"): "Lava + water -> Rock + Steam. blob_radius1=6 (restricted to lava), blob_radius2=3 (restricted to water): one contact solidifies a lava blob of radius 6 into rock and turns a water blob of radius 3 into steam. The classic 'walk on lava' trick.",
    ("[lava]", "water_ice", "", "rock_static", "steam"): "Chilly water solidifies lava too (blob 4/4).",
    ("[lava]", "mud", "", "sand_static", "steam"): "Lava + Mud -> Ground (static sand).",
    ("[lava]", "blood", "", "lavarock_static", "steam"): "Lava + Blood -> Volcanic Rock (immune to lava).",
    ("[lava]", "[radioactive]", "", "rock_static_radioactive", "radioactive_gas"): "Lava + Toxic Sludge -> Toxic Rock + Toxic Gas (both damage on contact).",
    ("[lava]", "poison", "", "rock_static_poison", "poison_gas"): "Lava + Poison -> Poisonous Rock + Poison Gas.",
    ("blood_cold", "lava", "", "blood_cold_vapour", "rock_hard"): "Freezing Liquid + Lava -> Freezing Vapour + Dense Rock (durability 12).",
    ("[lava]", "[burnable]", "", "[lava]", "fire"): "Lava ignites burnable materials slowly (8%); burnable_fast ones at 80%.",
    ("[lava]", "[meltable_to_lava]", "", "smoke", "fire"): "Lava eats ordinary rock/soil/slime (3%): the lava pixel becomes smoke and the rock pixel becomes fire, so lava pools slowly sink through rock_static.",
    ("[lava]", "[meltable_to_lava_fast]", "", "smoke", "lava"): "Sand/honey melt fast (80%) into more lava.",
    ("[fire_strong]", "[meltable_metal]", "", "[fire_strong]", "[meltable_metal]_molten"): "Liquid Fire (fire_strong) melts metals into their _molten variants at 30%.",
    ("[meltable_metal]", "[lava]", "", "[meltable_metal]_molten", "[lava]"): "Lava melts gold/silver/copper/brass/steel props/glass into <name>_molten (80%). Suffix rule: output material name = input name + '_molten'.",
    ("[meltable]_molten", "water", "", "[meltable]", "steam"): "Molten materials re-solidify in water (20%) producing steam.",
    ("[molten_metal]", "[water]", "", "metal_sand", "steam"): "Generic molten metal quenches into Metal Dust.",
    ("coal", "fire", "", "fire", "air"): "Burning coal is consumed into air (20%) in addition to the fire_hp burn mechanic.",
    ("water", "radioactive_liquid", "", "water", "water"): "Water purifies Toxic Sludge (13%): the sludge pixel becomes water. Works top-down because water (density 4) sinks below sludge (density 3) only when stirred.",
    ("water", "soil", "", "air", "mud"): "Water soaks into soil making mud (5%).",
    ("water", "cement", "", "concrete_static", "air"): "Cement sets instantly in water.",
    ("steam", "[static]", "", "water", "[static]"): "Steam touching static terrain condenses back into water (3%) - 'rain' from ceilings.",
    ("[evaporable]", "air", "", "air", "air"): "Materials tagged evaporable (fading toxic sludge, etc.) vanish on air at 15%; evaporable_fast at 45%.",
    ("[evaporable_by_fire]", "[fire]", "", "air", "[fire]"): "Evaporable-by-fire liquids vanish next to fire at 80%.",
    ("[fire]", "[meltable_by_fire]", "", "lava", "smoke"): "Honey/wax-like meltable_by_fire materials turn into LAVA when burnt (100%).",
    ("[fire]", "[burnable_fast]", "", "[fire]", "fire"): "Flammable Gas / whiskey fumes: fire spreads into them at 40% per check (deflagration).",
    ("[fire]", "[slime]", "", "cloud_slime", "cloud_slime"): "Fire + slime -> short-lived slime mist (70%): slime extinguishes fire extremely well.",
    ("blood", "poison", "", "slime", "smoke"): "Blood + Poison -> Slime + Smoke (10%).",
    ("sodium", "[water]", "", "sodium", "steam"): "Sodium + water -> steam with an ExplosionConfig (ray_energy 50000): many small explosions.",
    ("[slime]", "[magic_faster]", "", "fire_blue", "steam"): "Slime + Acceleratium/Levitatium/Hastium -> blue fire + steam, with explosions (ray_energy 50000, ~50 damage each to entities).",
    ("midas", "[alchemy]", "", "midas", "gold"): "Draught of Midas turns any [alchemy]-tagged material to gold (100%, fast, blob 3).",
    ("purifying_powder", "[impure]", "", "purifying_powder", "water"): "Purifying Powder converts impure liquids to water (80%, blob 2) consuming almost no powder.",
    ("magic_liquid_mana_regeneration", "water", "", "magic_liquid_mana_regeneration", "magic_liquid_mana_regeneration"): "Concentrated Mana duplicates itself from water (25%).",
    ("magic_liquid_mana_regeneration", "[meltable_metal]", "", "magic_liquid_mana_regeneration", "steam"): "Concentrated Mana melts metal (incl. gold nuggets!) into steam (25%) - safe steel digging.",
    ("[rust]", "[water]", "", "rust_static", "[water]"): "Static steel rusts on contact with water-tagged liquids (1%) into Rusted Metal (durability 10).",
    ("rock_static", "air", "", "rock_static", "moss"): "Rock grows moss on its top face (1%, direction=top).",
    ("[grows_grass]", "air", "", "grass", "air"): "Soil-like materials sprout grass into air (2%).",
    ("ice_static", "air", "", "water", "air"): "Ice slowly melts on air (1%).",
    ("water", "ice_static", "", "water", "water_ice"): "Water next to ice becomes Chilly Water (1%), which then freezes into ice_static (35%, blob 4) - ice spreads through water.",
    ("blood_cold", "[freezable]", "", "blood_cold", "ice_static"): "Freezing Liquid freezes water-like liquids (90%, blob 3).",
    ("magic_liquid_unstable_teleportation", "slime", "", "magic_liquid_teleportation", "magic_liquid_teleportation"): "Stabilises Unstable Teleportatium (20%).",
    ("magic_liquid_teleportation", "alcohol", "", "magic_liquid_unstable_teleportation", "alcohol"): "Whiskey destabilises Teleportatium (21%).",
    ("material_confusion", "blood", "oil", "magic_liquid_unstable_polymorph", "magic_liquid_unstable_polymorph"): "Three-input reaction (35%, blob_radius2=15): only the blood is converted, in a radius-15 blob.",
    ("silver", "copper", "blood", "diamond", "smoke"): "Three-input: silver + copper + blood -> diamond + 2 smoke (100%).",
    ("copper", "brass", "water", "silver", "smoke"): "Three-input: copper + brass + water -> silver + 2 smoke.",
    ("diamond", "silver", "blood_worm", "purifying_powder", "smoke"): "Three-input purifying powder recipe.",
    ("honey", "diamond", "", "magic_liquid_protection_all", "poison"): "Ambrosia recipe (50%) - also produces poison.",
    ("brass", "diamond", "", "purifying_powder", "purifying_powder"): "Purifying powder recipe (50%, blob 3).",
    ("alcohol", "meat_frog", "", "magic_liquid_berserk", "meat_frog"): "Berserkium: whiskey + frog meat (10%).",
    ("magic_liquid_faster_levitation", "magic_liquid_movement_faster", "", "magic_liquid_faster_levitation_and_movement", "magic_liquid_faster_levitation_and_movement"): "Hastium = Acceleratium + Levitatium (15%).",
    ("material_confusion", "magic_liquid_berserk", "", "magic_liquid_charm", "magic_liquid_charm"): "Pheromone = Flummoxium + Berserkium (25%).",
    ("midas_precursor", "[meat]", "", "midas", "midas"): "Alchemic Precursor + any meat -> Draught of Midas (100%, fast).",
    ("cement", "air", "", "concrete_static", "air"): "Cement cures to concrete on air after req_lifetime 300 frames (90%).",
    ("burning_powder", "[water]", "", "burning_powder", "fire"): "Burning Powder ignites ON water contact (20%).",
    ("[water]", "liquid_fire", "", "fire", "liquid_fire"): "Water next to Liquid Fire turns into fire (2%): liquid fire cannot be doused with water.",
    ("glue", "[fire]", "", "[fire]", "poison_gas"): "Burning glue releases poison gas.",
    ("poison", "air", "", "poison_gas", "air"): "Poison evaporates into Poison Gas (15%, fast).",
    ("[vapour]", "air", "", "air", "air"): "Vapour-tagged gases (Freezing Vapour, etc.) dissipate on air (30%).",
    ("[lava]", "air", "", "smoke", "air"): "Probability 0: lava does not smoke on air (reaction present but disabled).",
}

ENGINE_RULES = [
    OrderedDict(
        id="engine_burning_ignite",
        source="engine fire system (not a <Reaction>)",
        input_a="fire | burning cell | [lava] | [molten] | any cell with on_fire=1",
        input_b="any cell with burnable=1",
        output_a="(unchanged)",
        output_b="same cell, now burning (is_burning=1, per-cell fire hp = fire_hp)",
        probability=None,
        mechanism=("Each burning cell looks in a random direction each update (GDC 2019: 'when something is on fire it will "
                   "look in a random direction to see if it can ignite that pixel'). A neighbour ignites only if it is burnable "
                   "and the burning cell's temperature_of_fire exceeds the neighbour's autoignition_temperature; the engine "
                   "precomputes hundred_minus_autoignition_temp = 100 - autoignition_temperature per material (reversed CellData), "
                   "consistent with a per-check ignition chance of (100 - autoignition)% - e.g. oil 90%, wood 15%, coal 6%, "
                   "gunpowder 99%, brass/silver/diamond 1% (and they are not burnable anyway). requires_oxygen=1 (default) means "
                   "only cells touching air burn; requires_oxygen=0 (gunpowder, lava, slime, honey) burn throughout."),
        notes="Materials with always_ignites_damagemodel=1 (lava, molten metals) ignite entities on contact regardless of fire cells. UNVERIFIED: exact formula; the (100-autoignition)% reading is inferred from the engine's precomputed field and the default autoignition_temperature=100 making the default material never ignite.",
    ),
    OrderedDict(
        id="engine_burning_consume",
        source="engine fire system (not a <Reaction>)",
        input_a="burning cell (is_burning=1)",
        input_b="air (requires_oxygen) | none",
        output_a="on_fire_convert_to_material if set, else air; plus 'fire' cells (on_fire_flame_material) and 'smoke' (on_fire_smoke_material, amount ~ generates_smoke)",
        output_b="(unchanged)",
        probability=None,
        mechanism=("Each burning cell loses fire hp every update; when the per-cell counter (initialised from fire_hp) reaches 0 the cell "
                   "is converted. fire_hp=-1 burns forever (meteorite, sulphur_box2d, wood_burns_forever uses 99999999). "
                   "fire_hp examples: whiskey ~instant (reaction-based), fungi 60, burning_powder 100, gunpowder_tnt 200, "
                   "gunpowder_unstable 300, oil 500, wood 600, coal 1000, acid_gas 1000, molten metals 90000, liquid_fire 1000000."),
        notes="Every Fire cell itself has lifetime/decay handled by the renderer-side fire particles (RENDER_FIRE_LIFETIME_MIN/MAX 12/30 frames) and the 'flame' material (lifetime 5). generates_flames (default 30) controls how many flame particles a burning cell spawns.",
    ),
    OrderedDict(
        id="engine_cell_explosion",
        source="engine fire/physics system (CellData <ExplosionConfig>)",
        input_a="burning cell of a material with <ExplosionConfig> (gunpowder_explosive, gunpowder_tnt, gunpowder_unstable*, sodium_unstable, tnt, orb_powder)",
        input_b="accumulated fire damage >= cell_explosion_damage_required",
        output_a="explosion at the cell: radius = cell_explosion_radius_min..max scaled by cell_explosion_power; ray_energy and damage per the config",
        output_b="destroyed cells become create_cell_material ('fire') with create_cell_probability 5%",
        probability=None,
        mechanism=("gunpowder_explosive: damage 0.2, ray_energy 400000, cell_explosion_power 40, radius_min 8, damage_required 20. "
                   "gunpowder_tnt: damage_required 10, ray_energy 400000. gunpowder_unstable: on_fire=1 so it detonates as soon as it exists. "
                   "gunpowder_unstable_big: power 100, radius_min 20, ray_energy 800000, damage 0.6. sodium_unstable: ray_energy 50000, power 20, damage_required 0. "
                   "Box2D solids with solid_on_collision_explode=1 (meteorite, meteorite_green, sulphur_box2d, concrete_collapsed) explode on impact when body velocity >= cell_explosion_velocity_min."),
        notes="Chain reaction: each explosion ignites neighbouring gunpowder (create_cell_material fire) which explodes in turn.",
    ),
    OrderedDict(
        id="engine_cold_freeze",
        source="engine (CellData cold_freezes_to_material, used by freezing spells/perks)",
        input_a="liquid with cold_freezes_to_material (water->ice_static, blood->ice_blood_static, slime/vomit/pea_soup->ice_slime_static, acid->ice_acid_static, radioactive_liquid/cursed_liquid->ice_radioactive_static, poison->ice_poison_static, blood_cold->ice_cold_static, lava->lavarock_static)",
        input_b="a 'cold' source: Freeze Field perk, Iceball, Circle of Stillness, Freezing Gaze (ProjectileComponent/MagicConvertMaterial freeze)",
        output_a="cold_freezes_to_material",
        output_b="(unchanged)",
        probability="1 / cold_freezes_chance_rev (default 100)",
        notes="cold_freezes_to_dont_do_reverse_reaction=0 by default, so the same spells can thaw unless flagged. Distinct from Freezing Liquid's explicit <Reaction>.",
    ),
    OrderedDict(
        id="engine_warmth_melt",
        source="engine (CellData warmth_melts_to_material, used by heat sources such as Kiuaskivi / sauna stove)",
        input_a="material with warmth_melts_to_material (snow/snow_static/snow_b2/ice_glass variants -> water; ice_blood_glass -> blood; ice_slime_glass -> slime; water variants -> steam with warmth_melts_chance_rev=500)",
        input_b="a 'warmth' source",
        output_a="warmth_melts_to_material",
        output_b="(unchanged)",
        probability="1 / warmth_melts_chance_rev (default 100; water uses 500 i.e. 0.2%)",
        notes="In Hot biome modifier water evaporates into steam over time via this path (wiki: Water page).",
    ),
    OrderedDict(
        id="engine_lifetime",
        source="engine (CellData lifetime)",
        input_a="cell with lifetime > 0 (frames)",
        input_b="time",
        output_a="air after `lifetime` frames (60 fps)",
        output_b="",
        probability=None,
        notes="steam 1000, acid_gas 450, radioactive_gas 450, smoke 350, blood_cold_vapour 250, smoke_magic/explosion 150, blood_fading_slow 200, flame 5, cloud_blood/cloud_slime 10. Static gas variants (*_static) have lifetime 0 and instead emit normal gas via a Reaction with air.",
    ),
    OrderedDict(
        id="engine_density_swap",
        source="engine falling-sand update (not a <Reaction>)",
        input_a="moving cell (liquid, powder, gas) above/beside a cell of different density",
        input_b="neighbour cell",
        output_a="cells swap positions when the mover is denser (liquids/powders) or lighter (gases) than the neighbour",
        output_b="",
        probability=None,
        notes="See materials.md 'Liquids and powders'. Static cells (liquid_static=1) and Box2D solids never swap.",
    ),
    OrderedDict(
        id="engine_mimic",
        source="engine tag [any_liquid]",
        input_a="mimic_liquid (Mimicium)",
        input_b="[any_liquid] (engine tag: cell_type=liquid and liquid_sand=0)",
        output_a="becomes the touched liquid",
        output_b="(unchanged)",
        probability=None,
        notes="Engine tags: [*] = any material (unused), [any_liquid], [any_powder] (= liquid_sand=1, unused). Documented on 'Documentation: Reaction'.",
    ),
    OrderedDict(
        id="engine_convert_to_box2d",
        source="engine (CellData convert_to_box2d_material)",
        input_a="static material with convert_to_box2d_material (ice_static->ice_glass, glass_static->glass_brittle, rock_static_intro_breakable->rock_static_box2d, ice_*_static->ice_*_glass, tubematerial->tube_physics, ice_meteor_static->meteorite_crackable)",
        input_b="damage to the structure",
        output_a="the whole connected structure becomes a Box2D rigid body of that material (shards fall)",
        output_b="",
        probability=None,
        notes="This is how ice ceilings and glass vats shatter.",
    ),
]


def num(v):
    if v is None:
        return None
    s = str(v).strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def is_tag(s):
    return isinstance(s, str) and "[" in s


def main(research_dir):
    raw = f"{research_dir}/raw"
    rs = json.load(open(f"{raw}/reactions_xml_parsed.json"))
    ms = json.load(open(f"{raw}/materials_xml_parsed.json"))

    tags = defaultdict(set)
    seen = set()
    for m in ms:
        if m["name"] in seen:
            continue
        seen.add(m["name"])
        for t in m["tags"]:
            tags[t].add(m["name"])
        r = m["resolved"]
        if r.get("cell_type", "liquid") == "liquid" and r.get("liquid_sand", "0") == "0":
            tags["any_liquid"].add(m["name"])
        if r.get("cell_type", "liquid") == "liquid" and r.get("liquid_sand", "0") == "1":
            tags["any_powder"].add(m["name"])
        tags["*"].add(m["name"])
    tags_index = OrderedDict((t, sorted(v)) for t, v in sorted(tags.items(), key=lambda kv: kv[0]))
    with open(f"{research_dir}/tags_index.json", "w") as f:
        json.dump(OrderedDict(
            _note="tag -> material ids. '*', 'any_liquid', 'any_powder' are engine tags (Documentation: Reaction). Source: materials.xml (see materials.md Sources).",
            tags=tags_index), f, indent=1)

    out = []
    for i, x in enumerate(rs):
        rec = OrderedDict()
        rec["id"] = f"xml_{i:03d}"
        rec["source"] = f"materials.xml <{x['xml_element']}> #{i} (file order = engine priority)"
        rec["input_a"] = x.get("input_cell1")
        rec["input_b"] = x.get("input_cell2")
        rec["input_c"] = x.get("input_cell3") or None
        rec["output_a"] = x.get("output_cell1")
        rec["output_b"] = x.get("output_cell2")
        rec["output_c"] = x.get("output_cell3") or None
        rec["probability"] = num(x.get("probability", "0"))
        rec["probability_semantics"] = "per-update chance (%) that two adjacent qualifying cells react; stored as int(float*100) in the engine"
        rec["fast_reaction"] = x.get("fast_reaction") == "1"
        rec["req_reaction"] = x["xml_element"] == "ReqReaction"
        rec["convert_all"] = x.get("convert_all") == "1"
        rec["blob_radius_a"] = num(x.get("blob_radius1", "0"))
        rec["blob_radius_b"] = num(x.get("blob_radius2", "0"))
        rec["blob_restrict_a"] = x.get("blob_restrict_to_input_material1", "1") == "1"
        rec["blob_restrict_b"] = x.get("blob_restrict_to_input_material2", "1") == "1"
        rec["direction"] = x.get("direction", "none")
        rec["req_lifetime"] = num(x.get("req_lifetime", "0"))
        rec["destroy_horizontally_lonely_pixels"] = x.get("destroy_horizontally_lonely_pixels") == "1"
        rec["entity"] = x.get("entity") or None
        rec["cosmetic_particle"] = x.get("cosmetic_particle") or None
        rec["audio_fx_volume_1"] = num(x.get("audio_fx_volume_1")) if x.get("audio_fx_volume_1") else None
        ch = x.get("children", {})
        rec["explosion"] = OrderedDict((k, num(v)) for k, v in ch["ExplosionConfig"][0].items()) if ch.get("ExplosionConfig") else None
        tag_inputs = [t for t in (rec["input_a"], rec["input_b"], rec["input_c"]) if is_tag(t)]
        rec["is_tag_rule"] = bool(tag_inputs) or is_tag(rec["output_a"]) or is_tag(rec["output_b"])
        exp = OrderedDict()
        for t in tag_inputs + [o for o in (rec["output_a"], rec["output_b"], rec["output_c"]) if is_tag(o)]:
            base = t.split("[", 1)[1].split("]", 1)[0]
            exp[t] = len(tags_index.get(base, []))
        rec["tag_member_counts"] = exp or None
        key = (rec["input_a"], rec["input_b"], rec["input_c"] or "", rec["output_a"], rec["output_b"])
        rec["notes"] = NOTES.get(key)
        out.append(rec)

    out.extend(ENGINE_RULES)
    with open(f"{research_dir}/reactions.json", "w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {len(out)} entries ({len(rs)} xml reactions + {len(ENGINE_RULES)} engine rules); "
          f"tag rules: {sum(1 for o in out if o.get('is_tag_rule'))}; with notes: {sum(1 for o in out if o.get('notes'))}; "
          f"tags: {len(tags_index)}")


if __name__ == "__main__":
    main(sys.argv[1])
