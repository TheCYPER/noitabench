#!/usr/bin/env python3
"""Exact wang-template census: tile geometry (per NoitaWangTiler parse rules) + per-template color census mapped to
Noita material names (materials.xml wang_color) / spawn markers (wang_scripts.csv + RegisterSpawnFunction in biome lua)."""
import sys, json, re, collections, os
sys.path.insert(0, os.path.dirname(__file__))
from png_min import read_png
root = sys.argv[1]; out = sys.argv[2]
mats = json.load(open(os.path.join(root, "materials_from_data_xml.json")))
wc = {}
for m in mats:
    if m["wang_color"]:
        wc.setdefault(m["wang_color"][-6:].lower(), m["name"])
markers = {}
for line in open(os.path.join(root, "raw/noitadata/data/scripts/wang_scripts.csv")):
    if line.startswith("#") or not line.strip(): continue
    c, fn = line.strip().split(",")[:2]; markers[c[-6:].lower()] = fn
def biome_markers(lua):
    d = {}
    if os.path.exists(lua):
        for c, fn in re.findall(r'RegisterSpawnFunction\(\s*0x([0-9a-fA-F]{8})\s*,\s*"(\w+)"', open(lua).read()):
            d[c[-6:].lower()] = fn
    return d
def measure(path):
    w, h, px = read_png(path)
    hx = lambda x, y: "%02x%02x%02x" % px(x, y)[:3]
    WHITE = "ffffff"; ts = -2; y = 2
    while y < h and hx(0, y) != WHITE: ts += 1; y += 1
    y = 2; prev = ""; chy = 0
    while y < h:
        c = hx(0, y)
        if c == WHITE:
            if prev == WHITE: y += 2; break
            chy += 1
        prev = c; y += 1
    cvy = 0
    while y < h:
        if hx(0, y) == WHITE: cvy += 1
        y += 1
    x = 0; prev = ""; chx = 0
    while x < w:
        c = hx(x, 2)
        if c == WHITE:
            if prev == WHITE: break
            chx += 1
        prev = c; x += 1
    x = 0; prev = ""; cvx = 0; vy = (ts + 3) * chy + 4
    while x < w:
        c = hx(x, vy)
        if c == WHITE:
            if prev == WHITE: break
            cvx += 1
        prev = c; x += 1
    def tpos(tx, ty, horiz):
        if horiz: return tx * ts * 2 + 3 * tx, ty * ts + 3 * ty + 2
        return tx * ts + 3 * tx, ty * ts * 2 + 3 * ty + (chy * (ts + 3) + 4)
    census = collections.Counter(); edges = collections.Counter()
    hE = [(ts // 2, 0), (ts * 3 // 2, 0), (0, ts // 2), (2 * ts + 1, ts // 2), (ts // 2, ts + 1), (ts * 3 // 2, ts + 1)]
    vE = [(0, ts // 2), (ts // 2, 0), (ts + 1, ts // 2), (0, ts * 3 // 2), (ts // 2, 2 * ts + 1), (ts + 1, ts * 3 // 2)]
    for ty in range(chy):
        for tx in range(chx):
            ox, oy = tpos(tx, ty, True)
            for dx, dy in hE: edges[hx(ox + dx, oy + dy)] += 1
            for yy in range(1, ts + 1):
                for xx in range(1, 2 * ts + 1): census[hx(ox + xx, oy + yy)] += 1
    for ty in range(cvy):
        for tx in range(cvx):
            ox, oy = tpos(tx, ty, False)
            for dx, dy in vE: edges[hx(ox + dx, oy + dy)] += 1
            for yy in range(1, 2 * ts + 1):
                for xx in range(1, ts + 1): census[hx(ox + xx, oy + yy)] += 1
    return dict(image=(w, h), tile_short_side=ts, h_tiles=(chx, chy), v_tiles=(cvx, cvy), edge_colors=sorted(edges), census=census)
result = {}
for name in ["coalmine", "coalmine_alt", "excavationsite", "snowcave", "snowcastle", "rainforest", "rainforest_open", "rainforest_dark", "vault", "crypt", "fungicave", "liquidcave"]:
    p = os.path.join(root, "raw/noitadata/data/wang_tiles", name + ".png")
    r = measure(p)
    bm = biome_markers(os.path.join(root, "raw/noitadata/data/scripts/biomes", name + ".lua"))
    total = sum(r["census"].values())
    rows = []
    for c, n in r["census"].most_common():
        label = "AIR" if c == "000000" else "BIOME_FILL(white->Materials)" if c == "ffffff" else wc.get(c) or bm.get(c) or markers.get(c) or ("GREY_FILL" if c[0:2] == c[2:4] == c[4:6] else "?")
        rows.append([c, label, n, round(100 * n / total, 3)])
    result[name] = {k: v for k, v in r.items() if k != "census"}
    result[name]["n_edge_colors"] = len(r["edge_colors"])
    result[name]["colors"] = rows
    print(f"\n== {name}: image={r['image']} tile_short_side={r['tile_short_side']} h_tiles={r['h_tiles']} v_tiles={r['v_tiles']} edge_colors={len(r['edge_colors'])}")
    for c, label, n, pct in rows[:22]:
        print(f"   {c} {label:<32} {n:>7} {pct:6.2f}%")
json.dump(result, open(out, "w"), indent=1)
