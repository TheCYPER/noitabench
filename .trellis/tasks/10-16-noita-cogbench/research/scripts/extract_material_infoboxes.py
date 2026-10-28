#!/usr/bin/env python3
"""Extract {{Infobox material}} parameters from saved wikitext into JSON (handles tabbed variants: name2, type2...)."""
import re, json, sys, glob, os
src_dir, out = sys.argv[1], sys.argv[2]
rows = []
for path in sorted(glob.glob(os.path.join(src_dir, "*.wikitext"))):
    txt = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"\{\{Infobox material(.*?)\n\}\}", txt, re.S)
    if not m:
        continue
    body = m.group(1)
    params = {}
    for line in body.split("\n|"):
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        params[k.strip()] = re.sub(r"\s+", " ", v.strip())
    # group by suffix index
    variants = {}
    for k, v in params.items():
        mm = re.match(r"([a-zA-Z_]+?)(\d*)$", k)
        if not mm:
            continue
        base, idx = mm.group(1), mm.group(2) or "1"
        variants.setdefault(idx, {})[base] = v
    for idx, p in sorted(variants.items()):
        if "id" not in p and "name" not in p:
            continue
        rows.append({"page": os.path.basename(path).replace(".wikitext", ""), "variant": idx,
                     **{k: p.get(k) for k in ["name", "id", "type", "tags", "density", "hardness", "durability",
                                              "burnable", "biomes", "parent", "notes", "tab"]}})
json.dump(rows, open(out, "w"), indent=1)
for r in rows:
    print(f'{r["page"]:<22} {str(r["name"]):<24} id={str(r["id"]):<26} type={str(r["type"]):<8} dens={str(r["density"]):<4} hard={str(r["hardness"]):<8} dura={str(r["durability"]):<4} burn={str(r["burnable"]):<4} biomes={str(r["biomes"])[:70]}')
