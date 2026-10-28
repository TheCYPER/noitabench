#!/usr/bin/env python3
"""Dump <MaterialComponent> (strata/vein fill rules) and <VegetationComponent> from Noita biome XMLs to JSON + table."""
import re, json, sys, os
src_dir, out = sys.argv[1], sys.argv[2]
res = {}
for b in sys.argv[3:]:
    p = os.path.join(src_dir, b + ".xml")
    if not os.path.exists(p): continue
    t = open(p).read()
    topo = re.search(r"<Topology(.*?)>", t, re.S)
    tattrs = dict(re.findall(r'(\w+)="([^"]*)"', topo.group(1))) if topo else {}
    mats = []
    for m in re.finditer(r"<MaterialComponent(.*?)>", t, re.S):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if a.get("_enabled", "1") == "0": continue
        mats.append(a)
    veg = []
    for m in re.finditer(r"<VegetationComponent(.*?)>", t, re.S):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if a.get("_enabled", "1") == "0": continue
        veg.append({k: a.get(k) for k in ["tree_material", "tree_probability", "tree_width", "tree_image_file", "material_on_top_of", "is_grass", "is_ceiling_plant", "is_visual"]})
    res[b] = {"topology": {k: tattrs.get(k) for k in ["type", "wang_template_file", "wang_map_width", "wang_map_height", "noise_biome_edges", "mInsidePerlinScaleX", "mInsidePerlinScaleY", "mGradientStartY", "mGradientEndY", "mGradientAddNoise", "mMultiplierPerlin", "mMultiplierGradient", "mInsideAddValue", "mGradientNoiseScale"] if k in tattrs},
              "material_components": mats, "vegetation": veg}
    print(f"\n=== {b} ===  {res[b]['topology']}")
    print(f'  {"material":<24} {"idx":>3} {"min":>7} {"max":>7} {"rare":>4} {"polka":>5} {"perlin":>6} {"p_prob":>8} {"r_lo":>6} {"r_hi":>6} {"scale_x":>9} {"scale_y":>9} {"req_min":>7} {"req_max":>7} {"lim_y":>5} {"lim_min_y":>9} {"lim_max_y":>9} boxed')
    for a in mats:
        g = lambda k: a.get(k, "")
        print(f'  {g("material_name"):<24} {g("material_index"):>3} {g("material_min"):>7} {g("material_max"):>7} {g("is_rare"):>4} {g("rare_use_polka"):>5} {g("rare_use_perlin"):>6} {g("rare_polka_probability")[:8]:>8} {g("rare_polka_radius_low")[:6]:>6} {g("rare_polka_radius_high")[:6]:>6} {g("rare_scale_x")[:9]:>9} {g("rare_scale_y")[:9]:>9} {g("rare_required_min")[:7]:>7} {g("rare_required_max")[:7]:>7} {g("limit_y"):>5} {g("limit_min_y")[:9]:>9} {g("limit_max_y")[:9]:>9} {g("rare_polka_is_boxed")}')
    for v in veg:
        print(f'  veg: {v}')
json.dump(res, open(out, "w"), indent=1)
