#!/usr/bin/env python3
"""Parse Noita data/materials.xml <CellData>/<CellDataChild> into JSON: name, parent, wang_color, cell_type,
durability, hardness, density, burnable, tags, liquid flags. Resolves inherited attributes from _parent."""
import re, json, sys
src, out = sys.argv[1], sys.argv[2]
t = open(src, encoding="utf-8", errors="replace").read()
raw = {}
order = []
for m in re.finditer(r"<(CellData|CellDataChild)\b(.*?)>", t, re.S):
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
    if "name" not in attrs:
        continue
    attrs["_tag"] = m.group(1)
    raw[attrs["name"]] = attrs
    order.append(attrs["name"])
KEYS = ["wang_color", "cell_type", "durability", "hardness", "density", "burnable", "tags", "liquid_static",
        "liquid_sand", "liquid_gravity", "fire_hp", "platform_type", "ui_name", "temperature_of_fire", "generates_smoke",
        "electrical_conductivity", "on_fire", "autoignition_temperature"]
def resolve(name, key, depth=0):
    a = raw.get(name)
    if a is None or depth > 10:
        return None
    if key in a:
        return a[key]
    if a.get("_parent"):
        return resolve(a["_parent"], key, depth + 1)
    return None
rows = []
for n in order:
    r = {"name": n, "parent": raw[n].get("_parent")}
    for k in KEYS:
        r[k] = resolve(n, k)
    rows.append(r)
json.dump(rows, open(out, "w"), indent=1)
print(len(rows), "materials")
want = ["air","soil","sand_static","sand","rock_static","rock_static_wet","rock_loose","coal","gold","copper","silver","brass","sand_static_rainforest","soil_dead","soil_lush","soil_lush_dark","soil_dark","plant_material","wood","wood_static","wood_player","wood_loose","water","water_static","oil","lava","acid","swamp","radioactive_liquid","blood","snow","snow_static","snow_sticky","ice_static","ice_glass","rock_static_radioactive","rock_static_poison","rock_static_cursed","rock_hard","rock_hard_border","rock_static_grey","rock_static_intro","rock_static_box2d","steel","steel_static","steel_rust","steel_rusted_no_holes","metal","metal_rust","metal_pipe","rock_vault","templebrick_static","templebrick_moss_static","templebrick_diamond_static","templebrick_golden_static","templebrick_box2d","templebrick_static_broken","templebrick_static_soft","templebrick_static_ruin","templebrickdark_static","templebrick_thick_static","glass","glass_static","glass_brittle","gunpowder","gunpowder_explosive","magic_liquid_teleportation","magic_liquid_polymorph","magic_liquid_unstable_polymorph","fungi","fungus_loose","grass","grass_dark","moss","vine","ceiling_plant_material","diamond"]
byname = {r["name"]: r for r in rows}
print(f'{"name":<32} {"wang_color":<10} {"cell_type":<8} {"dura":<5} {"hardness":<9} {"dens":<6} {"burn":<4} tags')
for w in want:
    r = byname.get(w)
    if r is None:
        print(f"{w:<32} (not found)"); continue
    print(f'{w:<32} {str(r["wang_color"]):<10} {str(r["cell_type"]):<8} {str(r["durability"]):<5} {str(r["hardness"]):<9} {str(r["density"]):<6} {str(r["burnable"]):<4} {str(r["tags"])[:60]}')
