#!/usr/bin/env python3
"""Parse noitamap's biome_boundries_py.json (SVG paths in biome_map.png pixel units,
1 px = one 512x512 chunk) into bounding boxes in biome-map px, chunk coords and world px.

World mapping (noita.wiki.gg Modding: Making a custom environment):
  biome_map.png is 70 px wide; world x=0 is at map column 35; world y=0 is map row 14
  (biome_offset_y = 14). chunk = 512 px.
"""
import json, re, sys, collections
src = sys.argv[1]
out = sys.argv[2]
d = json.load(open(src))
MAP_W_CENTER = 35
BIOME_OFFSET_Y = 14
CHUNK = 512
rows = []
for b in d["biomes"]:
    pts = re.findall(r"([ML])\s*(-?\d+)\s+(-?\d+)", b["svg_map_path"])
    xs = [int(x) for _, x, _ in pts]
    ys = [int(y) for _, _, y in pts]
    if not xs:
        continue
    # svg path outlines cell boundaries, so max is exclusive
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    rows.append({
        "name": b.get("name", ""),
        "filename": b.get("filename", ""),
        "biome_color": b.get("biome_color", ""),
        "map_px": {"x0": x0, "x1_excl": x1, "y0": y0, "y1_excl": y1},
        "chunk": {"x0": x0 - MAP_W_CENTER, "x1_excl": x1 - MAP_W_CENTER,
                  "y0": y0 - BIOME_OFFSET_Y, "y1_excl": y1 - BIOME_OFFSET_Y},
        "world_px": {"x0": (x0 - MAP_W_CENTER) * CHUNK, "x1_excl": (x1 - MAP_W_CENTER) * CHUNK,
                     "y0": (y0 - BIOME_OFFSET_Y) * CHUNK, "y1_excl": (y1 - BIOME_OFFSET_Y) * CHUNK},
        "bbox_w_chunks": x1 - x0, "bbox_h_chunks": y1 - y0,
    })
rows.sort(key=lambda r: (r["chunk"]["y0"], r["chunk"]["x0"]))
json.dump({"note": __doc__.strip(), "map_width_px": 70, "biomes": rows}, open(out, "w"), indent=1)
for r in rows:
    c = r["chunk"]; w = r["world_px"]
    print(f'{r["filename"]:<32} {r["name"]:<26} color={r["biome_color"]:<8} chunks x[{c["x0"]},{c["x1_excl"]}) y[{c["y0"]},{c["y1_excl"]})  world x[{w["x0"]},{w["x1_excl"]}) y[{w["y0"]},{w["y1_excl"]})')
