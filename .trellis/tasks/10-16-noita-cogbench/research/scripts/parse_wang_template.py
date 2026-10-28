#!/usr/bin/env python3
"""Measure a Noita/stb-herringbone wang template PNG: tile short side, tile counts, and the edge-color
alphabet. Replicates TheHorscht/NoitaWangTiler dist/index.js parseImageData(). Needs a 32-bit BMP
(convert with: sips -s format bmp in.png --out out.bmp). Pure python + struct."""
import struct, sys, collections
def load_bmp(path):
    b = open(path, "rb").read()
    off = struct.unpack_from("<I", b, 10)[0]
    w, h = struct.unpack_from("<ii", b, 18)
    bpp = struct.unpack_from("<H", b, 28)[0]
    assert bpp in (24, 32), bpp
    bypp = bpp // 8
    row_bytes = ((w * bypp + 3) // 4) * 4
    topdown = h < 0
    h = abs(h)
    def px(x, y):
        ry = y if topdown else (h - 1 - y)
        i = off + ry * row_bytes + x * bypp
        bl, g, r = b[i], b[i + 1], b[i + 2]
        return (r, g, bl)
    return w, h, px
def hexc(c): return "%02x%02x%02x" % c
def parse(path):
    w, h, px = load_bmp(path)
    WHITE = "ffffff"
    # tile size: walk down column 0 from y=2 until white
    ts = -2; y = 2
    while y < h and hexc(px(0, y)) != WHITE:
        ts += 1; y += 1
    # count horizontal tile rows (white gaps) until double white
    y = 2; prev = ""; count_h_y = 0
    while y < h:
        c = hexc(px(0, y))
        if c == WHITE:
            if prev == WHITE:
                y += 2; break
            count_h_y += 1
        prev = c; y += 1
    count_v_y = 0
    while y < h:
        if hexc(px(0, y)) == WHITE: count_v_y += 1
        y += 1
    x = 0; prev = ""; count_h_x = 0
    while x < w:
        c = hexc(px(x, 2))
        if c == WHITE:
            if prev == WHITE: break
            count_h_x += 1
        prev = c; x += 1
    x = 0; prev = ""; count_v_x = 0
    vy = (ts + 3) * count_h_y + 4
    while x < w:
        c = hexc(px(x, vy))
        if c == WHITE:
            if prev == WHITE: break
            count_v_x += 1
        prev = c; x += 1
    # edge colors
    def tile_pos(tx, ty, horiz):
        if horiz: return tx * ts * 2 + 3 * tx, ty * ts + 3 * ty + 2
        return tx * ts + 3 * tx, ty * ts * 2 + 3 * ty + (count_h_y * (ts + 3) + 4)
    edge_colors = collections.Counter()
    h_edges = {"topLeft": (ts // 2, 0), "topRight": (ts * 3 // 2, 0), "left": (0, ts // 2), "right": (2 * ts + 1, ts // 2),
               "bottomLeft": (ts // 2, ts + 1), "bottomRight": (ts * 3 // 2, ts + 1)}
    v_edges = {"topLeft": (0, ts // 2), "top": (ts // 2, 0), "topRight": (ts + 1, ts // 2), "bottomLeft": (0, ts * 3 // 2),
               "bottom": (ts // 2, 2 * ts + 1), "bottomRight": (ts + 1, ts * 3 // 2)}
    for ty in range(count_h_y):
        for tx in range(count_h_x):
            ox, oy = tile_pos(tx, ty, True)
            for k, (dx, dy) in h_edges.items(): edge_colors[hexc(px(ox + dx, oy + dy))] += 1
    for ty in range(count_v_y):
        for tx in range(count_v_x):
            ox, oy = tile_pos(tx, ty, False)
            for k, (dx, dy) in v_edges.items(): edge_colors[hexc(px(ox + dx, oy + dy))] += 1
    # material color census inside tiles (first horizontal tile row only to keep it cheap)
    mats = collections.Counter()
    for ty in range(count_h_y):
        for tx in range(count_h_x):
            ox, oy = tile_pos(tx, ty, True)
            for yy in range(1, ts + 1):
                for xx in range(1, 2 * ts + 1):
                    mats[hexc(px(ox + xx, oy + yy))] += 1
    for ty in range(count_v_y):
        for tx in range(count_v_x):
            ox, oy = tile_pos(tx, ty, False)
            for yy in range(1, 2 * ts + 1):
                for xx in range(1, ts + 1):
                    mats[hexc(px(ox + xx, oy + yy))] += 1
    return dict(image_w=w, image_h=h, tile_short_side=ts, h_tiles=(count_h_x, count_h_y), v_tiles=(count_v_x, count_v_y),
                n_h=count_h_x * count_h_y, n_v=count_v_x * count_v_y, edge_colors=dict(edge_colors), material_colors=mats)
if __name__ == "__main__":
    import json
    out = {}
    for p in sys.argv[1:]:
        r = parse(p)
        name = p.split("/")[-1].replace(".bmp", "")
        total = sum(r["material_colors"].values())
        top = r["material_colors"].most_common(14)
        out[name] = {k: v for k, v in r.items() if k != "material_colors"}
        out[name]["material_colors_top"] = [(c, n, round(100 * n / total, 2)) for c, n in top]
        print(f"{name}: {r['image_w']}x{r['image_h']} tile_short_side={r['tile_short_side']} h_tiles(cols x rows)={r['h_tiles']} v_tiles={r['v_tiles']} => {r['n_h']} horizontal + {r['n_v']} vertical; edge colors={r['edge_colors']}")
        print("   top material colors (hex, px, %):", out[name]["material_colors_top"])
    json.dump(out, open("wang_template_stats.json", "w"), indent=1)
