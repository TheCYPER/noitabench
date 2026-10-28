#!/usr/bin/env python3
"""Extract Noita biome spawn tables (g_small_enemies, g_big_enemies, g_items, g_props, g_pixel_scene_01/02, ...) from
data/scripts/biomes/<biome>.lua into JSON. Regex-based: handles { prob=, min_count=, max_count=, entity=/entities={...},
material_file=, visual_file=, background_file=, is_unique=, ngpluslevel=, spawn_check= }. Also captures CHEST_LEVEL and
RegisterSpawnFunction colors."""
import re, json, sys, os
def parse_table(body):
    entries = []
    depth = 0; cur = ""; items = []
    # split top-level {...} blocks inside the table body
    for ch in body:
        if ch == "{":
            depth += 1
            if depth == 1: cur = ""
            else: cur += ch
        elif ch == "}":
            depth -= 1
            if depth == 0: items.append(cur)
            else: cur += ch
        elif depth >= 1: cur += ch
    for it in items:
        e = {}
        m = re.search(r"\bprob\s*=\s*([0-9.]+)", it); e["prob"] = float(m.group(1)) if m else None
        m = re.search(r"\bmin_count\s*=\s*(\d+)", it); e["min_count"] = int(m.group(1)) if m else None
        m = re.search(r"\bmax_count\s*=\s*(\d+)", it); e["max_count"] = int(m.group(1)) if m else None
        m = re.search(r'\bentity\s*=\s*"([^"]*)"', it); e["entity"] = m.group(1) if m else None
        ents = re.search(r"\bentities\s*=\s*\{(.*?)\}", it, re.S)
        if ents: e["entities"] = re.findall(r'"([^"]+)"', ents.group(1))
        for k in ["material_file", "visual_file", "background_file", "color_material"]:
            m = re.search(r'\b%s\s*=\s*"([^"]*)"' % k, it)
            if m: e[k] = m.group(1)
        for k in ["is_unique", "ngpluslevel", "spawn_check_level"]:
            m = re.search(r"\b%s\s*=\s*([0-9.]+)" % k, it)
            if m: e[k] = float(m.group(1))
        if "spawn_check" in it: e["has_spawn_check"] = True
        if e["entity"] is None and "entities" not in e and "material_file" not in e: e["entity"] = ""
        entries.append(e)
    return entries
def parse_file(path):
    t = open(path, encoding="utf-8", errors="replace").read()
    t = re.sub(r"--\[\[.*?\]\]", "", t, flags=re.S); t = re.sub(r"--[^\n]*", "", t)
    out = {"file": path, "tables": {}}
    m = re.search(r"CHEST_LEVEL\s*=\s*(\d+)", t); out["CHEST_LEVEL"] = int(m.group(1)) if m else None
    out["spawn_functions"] = {c.lower(): fn for c, fn in re.findall(r'RegisterSpawnFunction\(\s*0x([0-9a-fA-F]{8})\s*,\s*"(\w+)"', t)}
    for m in re.finditer(r"^(g_\w+)\s*=\s*\{", t, re.M):
        name = m.group(1); i = m.end(); depth = 1; j = i
        while j < len(t) and depth:
            if t[j] == "{": depth += 1
            elif t[j] == "}": depth -= 1
            j += 1
        body = t[i:j - 1]
        entries = parse_table(body)
        total = sum(e["prob"] or 0 for e in entries)
        for e in entries: e["pct"] = round(100 * (e["prob"] or 0) / total, 2) if total else None
        out["tables"][name] = {"total_prob": total, "entries": entries}
    return out
if __name__ == "__main__":
    src_dir, out = sys.argv[1], sys.argv[2]
    res = {}
    for name in sys.argv[3:]:
        p = os.path.join(src_dir, name + ".lua")
        if os.path.exists(p) and os.path.getsize(p) > 200:
            res[name] = parse_file(p)
    json.dump(res, open(out, "w"), indent=1)
    for name, r in res.items():
        print(f"\n=== {name}: CHEST_LEVEL={r['CHEST_LEVEL']} tables={list(r['tables'])}")
        for tn in ["g_small_enemies", "g_big_enemies", "g_items", "g_props", "g_pixel_scene_01", "g_pixel_scene_02", "g_lamp", "g_unique_enemy", "g_unique_enemy2", "g_unique_enemy3", "g_props2", "g_props3", "g_potions", "g_candles"]:
            tb = r["tables"].get(tn)
            if not tb: continue
            print(f"  {tn} (total_prob={tb['total_prob']:.3f})")
            for e in tb["entries"]:
                what = e.get("material_file") or e.get("entity") or ("+".join(os.path.basename(x) for x in e.get("entities", [])))
                print(f"     p={e['prob']:<6} ({e['pct']:>5}%) n={e['min_count']}-{e['max_count']} {os.path.basename(what) if what else '(nothing)'}{' [unique]' if e.get('is_unique') else ''}{' [spawn_check]' if e.get('has_spawn_check') else ''}")
