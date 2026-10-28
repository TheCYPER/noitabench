#!/usr/bin/env python3
"""Generate markdown tables for materials.md from materials.json / reactions.json / tags_index.json.
Usage: python3 gen_md_tables.py <research_dir>  -> writes <research_dir>/raw/generated_tables.md
"""
import json, sys
from collections import defaultdict, Counter

R = sys.argv[1]
ms = json.load(open(f"{R}/materials.json"))
rs = json.load(open(f"{R}/reactions.json"))
tags = json.load(open(f"{R}/tags_index.json"))["tags"]
by = {m["id"]: m for m in ms}
out = []
P = out.append

def hx(rgb):
    return "#%02x%02x%02x" % tuple(rgb) if rgb else "-"

KEY = ["air","fire","water","oil","lava","acid","blood","radioactive_liquid","poison","slime","alcohol","blood_cold","swamp","mud","water_ice","water_salt","honey","urine","vomit","milk","beer","pea_soup",
       "magic_liquid_polymorph","magic_liquid_teleportation","magic_liquid_unstable_teleportation","material_confusion","magic_liquid_mana_regeneration","magic_liquid_berserk","magic_liquid_movement_faster","magic_liquid_faster_levitation","magic_liquid_protection_all","magic_liquid_hp_regeneration","midas","midas_precursor","liquid_fire","void_liquid","cursed_liquid",
       "sand","soil","coal","gunpowder_explosive","gunpowder","gunpowder_unstable","gunpowder_tnt","salt","sodium","burning_powder","snow","ice","gold","silver","copper","brass","diamond","steel_sand","metal_sand","fungi","grass","moss","spore","purifying_powder","bone","cement",
       "sand_static","rock_static","rock_hard","rock_static_grey","lavarock_static","rock_static_radioactive","rock_static_poison","rock_static_cursed","coal_static","wood_static","wood_tree","steel_static","rust_static","ice_static","snow_static","glass_static","templebrick_static","concrete_static","meat_static","fungisoil","soil_lush",
       "glass","wood","steel","ice_glass","meteorite","tnt",
       "steam","smoke","acid_gas","radioactive_gas","poison_gas","blood_cold_vapour","alcohol_gas","magic_gas_hp_regeneration","fungal_gas","poo_gas","cloud_slime",
       "flame","fire_blue","spark","steel_molten","gold_molten","wax_molten"]
KEY = [k for k in KEY if k in by]

P("## T1. Key materials (%d of 466)\n" % len(KEY))
P("| id | name | kind | dens | dur | hp | burn | fire_hp | autoign | T_fire | O2 | grav | visc | life | colour | wang |")
P("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for k in KEY:
    m = by[k]; g = m["gravity"]; d = m["dispersion"] or {}
    grav = g["liquid_gravity"] if g["liquid_gravity"] is not None else (g["solid_gravity_scale"] if g["solid_gravity_scale"] is not None else "-")
    if m["kind"] == "gas": grav = f"up{g['gas_upwards_speed']}/h{g['gas_horizontal_speed']}/d{g['gas_downwards_speed']}"
    P(f"| {k} | {m['name']} | {m['kind']} | {m['density']} | {m['durability']} | {m['hp']} | {'Y' if m['flammable'] else ('ON' if m['starts_on_fire'] else '-')} | {m['fire_hp'] if m['fire_hp'] is not None else '-'} | {m['autoignition']} | {m['temperature_of_fire']} | {'Y' if m['requires_oxygen'] else 'N'} | {grav} | {d.get('liquid_viscosity','-')} | {m['lifetime_frames'] or '-'} | {hx(m['color_rgb'])} a{m['color_alpha']} | {m['wang_color_argb']} |")
P("")
P("Column key: dens=density, dur=durability (0 = none defined), hp=hardness (explosion ray energy cost per cell), burn=burnable (ON = starts on fire), fire_hp=fuel, autoign=autoignition_temperature, T_fire=temperature_of_fire, O2=requires_oxygen, grav=liquid_gravity (or solid_gravity_scale / gas speeds), visc=liquid_viscosity, life=lifetime in frames, colour=Graphics colour RGB + alpha (falls back to wang colour), wang=wang_color ARGB.\n")

P("## T2. Burnable materials sorted by fire_hp (fuel)\n")
P("| id | kind | fire_hp | autoignition | temperature_of_fire | requires_oxygen | generates_smoke | starts_on_fire | burns_into |")
P("|---|---|---|---|---|---|---|---|---|")
burn = [m for m in ms if m["flammable"] or m["starts_on_fire"]]
burn.sort(key=lambda m: (m["fire_hp"] if m["fire_hp"] is not None and m["fire_hp"] >= 0 else 10**12, m["id"]))
for m in burn:
    P(f"| {m['id']} | {m['kind']} | {m['fire_hp']}{' (default)' if m.get('fire_hp_is_engine_default') else ''} | {m['autoignition']} | {m['temperature_of_fire']} | {'Y' if m['requires_oxygen'] else 'N'} | {m['generates_smoke']} | {'Y' if m['starts_on_fire'] else '-'} | {m['on_fire_convert_to_material_raw'] or 'air'} |")
P("")

P("## T3. Durability ladder (materials.xml durability -> ids)\n")
dl = defaultdict(list)
for m in ms: dl[m["durability"]].append(m["id"])
P("| durability | count | material ids |")
P("|---|---|---|")
for d in sorted(dl):
    ids = sorted(dl[d]); P(f"| {d} | {len(ids)} | {', '.join(ids[:40])}{' ...' if len(ids)>40 else ''} |")
P("")

P("## T4. Hardness (hp) distribution for static/powder terrain\n")
P("| hp | example ids |")
P("|---|---|")
hl = defaultdict(list)
for m in ms:
    if m["kind"] in ("static","powder","solid"): hl[m["hp"]].append(m["id"])
for h in sorted(hl):
    P(f"| {h} | {', '.join(sorted(hl[h])[:14])}{' ...' if len(hl[h])>14 else ''} |")
P("")

P("## T5. Density ladder for free-moving liquids (kind=liquid)\n")
liq = sorted([m for m in ms if m["kind"]=="liquid"], key=lambda m:(m["density"], m["id"]))
P("| density | ids |"); P("|---|---|")
dd = defaultdict(list)
for m in liq: dd[m["density"]].append(m["id"])
for d in sorted(dd): P(f"| {d} | {', '.join(dd[d])} |")
P("")
P("## T5b. Density ladder for powders (kind=powder)\n")
dd = defaultdict(list)
for m in ms:
    if m["kind"]=="powder": dd[m["density"]].append(m["id"])
P("| density | ids |"); P("|---|---|")
for d in sorted(dd): P(f"| {d} | {', '.join(sorted(dd[d]))} |")
P("")

P("## T6. Gases: speeds and lifetimes\n")
P("| id | name | density | lifetime (frames) | gas_speed | up | horiz | down | burnable | notes |"); P("|---|---|---|---|---|---|---|---|---|---|")
for m in sorted([m for m in ms if m["kind"]=="gas"], key=lambda m:m["id"]):
    g=m["gravity"]; P(f"| {m['id']} | {m['name']} | {m['density']} | {m['lifetime_frames']} | {g['gas_speed']} | {g['gas_upwards_speed']} | {g['gas_horizontal_speed']} | {g['gas_downwards_speed']} | {'Y' if m['flammable'] else '-'} | {(m['notes'] or '')[:80]} |")
P("")

P("## T7. Materials with lifetime > 0 (non-gas)\n")
P("| id | kind | lifetime frames | seconds @60fps |"); P("|---|---|---|---|")
for m in sorted([m for m in ms if m["lifetime_frames"] and m["kind"]!="gas"], key=lambda m:m["lifetime_frames"]):
    P(f"| {m['id']} | {m['kind']} | {m['lifetime_frames']} | {m['lifetime_frames']/60:.2f} |")
P("")

P("## T8. ASCII palette table (key materials)\n")
P("Base colour = `<Graphics color>` from materials.xml (ARGB; alpha < ff means translucent liquid/gas), falling back to `wang_color` at full alpha when no Graphics colour is set. Palette = most frequent opaque colours in the material's `data/materials_gfx/*.png` texture (share of texels in parentheses).\n")
P("```")
P(f"{'id':34s} {'base RGB':9s} {'A':>3s} {'wang ARGB':9s} {'glow':>4s}  texture palette (top colours, share)")
P("-"*140)
pal_json = json.load(open(f"{R}/raw/texture_palettes.json"))
for k in KEY:
    m = by[k]
    tex = (m["texture_file"] or "").split("/")[-1]
    pal = pal_json.get(tex, {}).get("top", []) if tex else []
    pstr = " ".join(f"{p['hex']}({p['share']:.2f})" for p in pal[:5]) if pal else ("(flat colour)" if m["color_rgb"] else "(none)")
    P(f"{k:34s} {hx(m['color_rgb']):9s} {str(m['color_alpha'] if m['color_alpha'] is not None else '-'):>3s} {str(m['wang_color_argb']):9s} {str(m['gfx_glow']):>4s}  {pstr}")
P("```\n")

P("## T9. Tag index (count, members)\n")
P("| tag | n | members (first 25) |"); P("|---|---|---|")
for t, v in tags.items():
    if t == "*": continue
    P(f"| [{t}] | {len(v)} | {', '.join(v[:25])}{' ...' if len(v)>25 else ''} |")
P("")

P("## T10. Reaction probability histogram\n")
c = Counter(r["probability"] for r in rs if str(r.get("id","")).startswith("xml_"))
P("| probability | count |"); P("|---|---|")
for p in sorted(c, key=lambda x: float(x)): P(f"| {p} | {c[p]} |")
P("")

P("## T11. Player contact damage per material (wiki Materials#Player_damage)\n")
P("| id | per frame per pixel (display) | DPS per pixel | DPS submerged (85 px) | raw DamageModel value |"); P("|---|---|---|---|---|")
for m in sorted([m for m in ms if m["damage_to_entities"] and "per_frame_per_pixel_display" in m["damage_to_entities"]], key=lambda m:-m["damage_to_entities"]["per_frame_per_pixel_display"]):
    d=m["damage_to_entities"]; P(f"| {m['id']} | {d['per_frame_per_pixel_display']} | {d['dps_per_pixel']} | {d['dps_submerged_85px']} | {d['raw_damagemodel_value']} |")
P("")

P("## T12. Materials with <ExplosionConfig> (cell explosions)\n")
P("| id | damage | ray_energy | cell_explosion_power | radius_min | radius_max | damage_required | velocity_min | starts_on_fire | fire_hp |"); P("|---|---|---|---|---|---|---|---|---|---|")
for m in ms:
    e=m["explosion_config"]
    if e: P(f"| {m['id']} | {e.get('damage','-')} | {e.get('ray_energy','-')} | {e.get('cell_explosion_power','-')} | {e.get('cell_explosion_radius_min','-')} | {e.get('cell_explosion_radius_max','-')} | {e.get('cell_explosion_damage_required','-')} | {e.get('cell_explosion_velocity_min','-')} | {'Y' if m['starts_on_fire'] else '-'} | {m['fire_hp']} |")
P("")

P("## T13. Kind / cell_type census\n")
P("| kind | definition | count |"); P("|---|---|---|")
defs={"liquid":"cell_type=liquid, liquid_sand=0, liquid_static=0","powder":"cell_type=liquid, liquid_sand=1, liquid_static=0","static":"cell_type=liquid, liquid_static=1 (terrain)","solid":"cell_type=solid (Box2D rigid body material)","gas":"cell_type=gas","fire":"cell_type=fire"}
for k,n in Counter(m["kind"] for m in ms).most_common(): P(f"| {k} | {defs[k]} | {n} |")
P("")
open(f"{R}/raw/generated_tables.md","w").write("\n".join(out))
print("wrote", f"{R}/raw/generated_tables.md", len(out), "lines")
