#!/usr/bin/env python3
"""Rasterize noitamap biome_boundries_py.json SVG outlines into per-cell biome occupancy.
Outputs: an ASCII biome map (70 cols x 48 rows, 1 char = one 512x512 chunk) and a JSON of
cells per biome filename, in chunk coords (cx = col-35, cy = row-14) and world px (*512)."""
import json, re, sys
src, out_json, out_txt = sys.argv[1:4]
d = json.load(open(src))
W, H = 70, 48
CX0, CY0, CHUNK = 35, 14, 512

def pip(px, py, poly):  # even-odd point in polygon
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            xint = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xint:
                inside = not inside
    return inside

grid = [[None] * W for _ in range(H)]
cells = {}
# Paths may contain several closed subpaths (M ... Z M ... Z); handle each.
for b in d["biomes"]:
    fn = (b["filename"] or b["name"] or "unnamed") + "|" + b["biome_color"]
    subpaths = re.split(r"[Zz]", b["svg_map_path"])
    polys = []
    for sp in subpaths:
        pts = [(int(x), int(y)) for _, x, y in re.findall(r"([ML])\s*(-?\d+)\s+(-?\d+)", sp)]
        if len(pts) >= 3:
            polys.append(pts)
    occupied = []
    for row in range(H):
        for col in range(W):
            cxp, cyp = col + 0.5, row + 0.5
            cnt = sum(1 for p in polys if pip(cxp, cyp, p))
            if cnt % 2 == 1:
                occupied.append((col, row))
    cells[fn] = {"biome_color": b["biome_color"], "name": b["name"], "n_cells": len(occupied),
                 "cells_chunk": [[c - CX0, r - CY0] for c, r in occupied]}
    for c, r in occupied:
        grid[r][c] = fn  # later (smaller, inner) entries overwrite; noitamap lists outer walls first

# legend
names = sorted({v for row in grid for v in row if v})
legend = {}
alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
for i, n in enumerate(names):
    legend[n] = alphabet[i // len(alphabet)] + alphabet[i % len(alphabet)]
lines = []
lines.append("Noita biome_map (derived from noitamap biome_boundries_py.json). 1 char = 1 chunk (512x512 px).")
lines.append("Columns: map px 0..69 => chunk x = col-35 (world x = chunk*512). Rows: map px 0..47 => chunk y = row-14.")
lines.append("Row label = chunk y and world y (top edge). Each cell is a 2-char code (see legend); '..' = no biome entry.")
lines.append("Note: noitamap lists big outer regions first and small rooms later; later entries overwrite earlier ones here.")
lines.append("")
hdr = "".join((f"{c - CX0:+d}").rjust(3)[-3:] if (c - CX0) % 5 == 0 else "   " for c in range(W))
lines.append("chunk x ->    " + hdr)
for r in range(H):
    cy = r - CY0
    lines.append(f"cy={cy:3d} {cy*CHUNK:6d} " + " ".join(legend[grid[r][c]] if grid[r][c] else ".." for c in range(W)))
lines.append("")
lines.append("Legend:")
for n in names:
    lines.append(f"  {legend[n]} = {n} ({cells[n]['biome_color']}, {cells[n]['n_cells']} cells)")
open(out_txt, "w").write("\n".join(lines) + "\n")
# per-biome y-rows summary for main path
summary = {}
for fn, v in cells.items():
    if not v["cells_chunk"]:
        continue
    ys = sorted({cy for _, cy in v["cells_chunk"]}); xs = sorted({cx for cx, _ in v["cells_chunk"]})
    summary[fn] = {"chunk_rows": ys, "chunk_cols_min_max": [xs[0], xs[-1]],
                   "world_y_px": [ys[0] * CHUNK, (ys[-1] + 1) * CHUNK],
                   "world_x_px": [xs[0] * CHUNK, (xs[-1] + 1) * CHUNK], "n_cells": v["n_cells"]}
json.dump({"cells": cells, "summary": summary}, open(out_json, "w"), indent=1)
print("\n".join(lines))
