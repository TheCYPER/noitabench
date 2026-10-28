"""Command line: ``python -m noitabench.worldgen <preview|check|generate|tiles|scene> ...``.

The shared ``python -m noitabench world ...`` entry point forwards to ``main`` here.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

from .config import load_biome_map, load_materials
from .generate import generate_world
from .preview import save_crop, save_preview


def _rule_seed(seed: int, fixed: int | None) -> int:
    """The rule seed of a checked world: the given one, else the world seed itself."""
    return seed if fixed is None else fixed


def _digest(seed: int, rule_seed: int) -> str:
    mats = load_materials()
    w = generate_world(seed, rule_seed)
    return hashlib.sha256(w.png_bytes(mats) + w.json_text().encode()).hexdigest()


def _check_one(job: tuple[int, int]) -> tuple[int, bool, float, int, str]:
    seed, rule_seed = job
    t0 = time.perf_counter()
    try:
        w = generate_world(seed, rule_seed)
        return seed, True, time.perf_counter() - t0, int(w.meta.get("attempt", 0)), ""
    except Exception as err:  # noqa: BLE001 - reported per seed and makes the command fail
        return seed, False, time.perf_counter() - t0, -1, f"{type(err).__name__}: {err}"


def cmd_check(args: argparse.Namespace) -> int:
    if args.seeds < 1:
        raise SystemExit(f"--seeds must be at least 1, got {args.seeds}")
    seeds = list(range(args.start, args.start + args.seeds))
    work = [(s, _rule_seed(s, args.rule_seed)) for s in seeds]
    jobs = args.jobs or min(os.cpu_count() or 1, 8)
    t0 = time.perf_counter()
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(_check_one, work, chunksize=4))
    else:
        results = [_check_one(w) for w in work]
    wall = time.perf_counter() - t0
    failed = [r for r in results if not r[1]]
    times = [r[2] for r in results]
    rerolled = [r for r in results if r[1] and r[3] > 0]
    rules = "rule seed = world seed" if args.rule_seed is None else f"rule seed {args.rule_seed}"
    print(
        f"checked {len(seeds)} seeds (start {args.start}, {rules}) "
        f"with {jobs} worker(s) in {wall:.1f}s"
    )
    print(f"  passed {len(results) - len(failed)}  failed {len(failed)}  re-rolled {len(rerolled)}")
    print(f"  per world: mean {statistics.mean(times):.2f}s  max {max(times):.2f}s")
    for seed, _, _, attempt, _ in rerolled[:10]:
        print(f"  seed {seed} needed attempt {attempt}")
    for seed, _, _, _, msg in failed:
        print(f"  FAIL seed {seed}: {msg}")
    if args.determinism:
        n = min(args.determinism, len(seeds))
        # the second digest comes from a fresh interpreter (new hash seed, empty caches)
        here = [_digest(*w) for w in work[:n]]
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            there = list(pool.map(_digest, *zip(*work[:n])))
        bad = [s for s, a, b in zip(seeds, here, there) if a != b]
        print(f"  determinism: {n - len(bad)}/{n} seeds byte-identical in a fresh process")
        if bad:
            print(f"  NOT reproducible: {bad}")
            return 1
    return 1 if failed else 0


def cmd_preview(args: argparse.Namespace) -> int:
    mats = load_materials()
    for seed in args.seed:
        t0 = time.perf_counter()
        world = generate_world(seed, _rule_seed(seed, args.rule_seed))
        gen = time.perf_counter() - t0
        out = Path(args.out)
        png = save_preview(world, out / f"world_seed{seed}.png", args.scale)
        paths = [png]
        if args.plain:
            plain_scale = args.plain_scale or args.scale
            paths.append(
                save_preview(world, out / f"world_seed{seed}_plain.png", plain_scale, overlay=False)
            )
        for i, box in enumerate(args.crop):
            paths.append(
                save_crop(world, out / f"world_seed{seed}_crop{i + 1}.png", box, args.crop_scale)
            )
        if args.write_world:
            paths += list(world.write(out, f"world_seed{seed}", mats))
        print(f"seed {seed}: generated in {gen:.2f}s -> " + ", ".join(str(p) for p in paths))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    mats = load_materials()
    world = generate_world(args.seed, args.rule_seed)
    png, js = world.write(args.out, args.name or f"world_{args.seed}", mats)
    print(f"{png}\n{js}")
    return 0


def cmd_tiles(args: argparse.Namespace) -> int:
    import numpy as np
    from PIL import Image

    from .fill import tileset_for
    from .rng import mix64
    from .tiles import KIND_H, KIND_V, N_COLORS

    biomes = load_biome_map().biomes
    if args.biome not in biomes:
        raise SystemExit(
            f"unknown biome '{args.biome}'; choose one of: {', '.join(sorted(biomes))}"
        )
    biome = biomes[args.biome]
    if biome.tile is None:
        raise SystemExit(f"biome '{args.biome}' has the 'rooms' layout: it has no Wang tiles")
    ts = tileset_for(biome)
    s = biome.tile.short_side
    sheet = np.full((2 * (2 * s + 4) + 4, 12 * (2 * s + 4) + 4), 90, dtype=np.uint8)
    for row, kind in enumerate((KIND_H, KIND_V)):
        for col in range(12):
            edges = tuple(int(mix64(args.seed, kind, col, i) % N_COLORS) for i in range(6))
            t = ts.tile(kind, edges, col % biome.tile.variants)
            y, x = 4 + row * (2 * s + 4), 4 + col * (2 * s + 4)
            sheet[y : y + t.shape[0], x : x + t.shape[1]] = np.where(t, 255, 30)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"tiles_{args.biome}.png"
    Image.fromarray(sheet).resize((sheet.shape[1] * 2, sheet.shape[0] * 2), Image.NEAREST).save(
        path
    )
    print(path)
    return 0


def cmd_scene(args: argparse.Namespace) -> int:
    from .encounter_defs import load_encounters
    from .preview import terrain_image
    from .scene_world import scene_world

    defs = load_encounters()
    if args.id not in defs:
        raise SystemExit(f"unknown encounter '{args.id}'; choose one of: {', '.join(sorted(defs))}")
    mats = load_materials()
    if not 0 <= args.variant < defs[args.id].variants:
        raise SystemExit(
            f"{args.id} has variants 0 to {defs[args.id].variants - 1}, got {args.variant}"
        )
    world = scene_world(args.id, args.variant, args.rule_seed, 1, mats)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"scene_{args.id}_v{args.variant}_r{args.rule_seed}.png"
    terrain_image(world, mats, args.scale, shade=False).save(path, format="PNG")
    paths = [path]
    if args.write_world:
        paths += list(world.write(out, f"scene_{args.id}_v{args.variant}", mats))
    print("\n".join(str(q) for q in paths))
    return 0


def _box(text: str) -> tuple[int, int, int, int]:
    try:
        x0, y0, x1, y1 = (int(v) for v in text.split(","))
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"'{text}' is not X0,Y0,X1,Y1") from err
    if not (0 <= x0 < x1 and 0 <= y0 < y1):
        raise argparse.ArgumentTypeError(f"'{text}' is not a rectangle with X0 < X1 and Y0 < Y1")
    return x0, y0, x1, y1


def _add_rules(parser: argparse.ArgumentParser, seed_help: str, seed_default: int | None) -> None:
    """The ``--rule-seed`` option (it seeds the potion recipes; the reaction table is fixed)."""
    parser.add_argument("--rule-seed", type=int, default=seed_default, help=seed_help)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="noitabench.worldgen", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("preview", help="render preview images of generated worlds")
    pv.add_argument("--seed", type=int, nargs="+", required=True)
    pv.add_argument("--out", default="previews")
    _add_rules(pv, "rule seed of the world (default: 0)", 0)
    pv.add_argument("--scale", type=int, default=2)
    pv.add_argument("--plain", action="store_true", help="also write a plain terrain image")
    pv.add_argument(
        "--plain-scale", type=int, default=0, help="scale of the plain image (default: --scale)"
    )
    pv.add_argument(
        "--crop",
        type=_box,
        action="append",
        default=[],
        metavar="X0,Y0,X1,Y1",
        help="also write a plain close-up of this world rectangle (repeatable)",
    )
    pv.add_argument("--crop-scale", type=int, default=4, help="scale of the close-ups")
    pv.add_argument("--write-world", action="store_true", help="also write the world file pair")
    pv.set_defaults(fn=cmd_preview)

    ck = sub.add_parser("check", help="generate many seeds and run the post-generation checks")
    ck.add_argument("--seeds", type=int, default=200, help="how many seeds to check")
    ck.add_argument("--start", type=int, default=0, help="first seed")
    ck.add_argument("--jobs", type=int, default=0, help="worker processes (default: up to 8)")
    _add_rules(ck, "rule seed of every world (default: the world's own seed)", None)
    ck.add_argument(
        "--determinism", type=int, default=3, help="regenerate this many seeds and compare bytes"
    )
    ck.set_defaults(fn=cmd_check)

    g = sub.add_parser("generate", help="write the world file pair of one seed")
    g.add_argument("--seed", type=int, required=True)
    _add_rules(g, "rule seed of the world (default: 0)", 0)
    g.add_argument("--out", default="worlds")
    g.add_argument("--name", default="")
    g.set_defaults(fn=cmd_generate)

    t = sub.add_parser("tiles", help="write a sheet of sample Wang tiles of a biome")
    t.add_argument("--biome", required=True)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--out", default="previews")
    t.set_defaults(fn=cmd_tiles)

    sc = sub.add_parser("scene", help="render one encounter scene in its lab world")
    sc.add_argument("id", help="encounter id, e.g. E02")
    sc.add_argument("--variant", type=int, default=0)
    _add_rules(sc, "rule seed of the liquids (default: 0)", 0)
    sc.add_argument("--scale", type=int, default=4)
    sc.add_argument("--out", default="previews")
    sc.add_argument("--write-world", action="store_true", help="also write the world file pair")
    sc.set_defaults(fn=cmd_scene)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if os.environ.get("COGBENCH_LOG") else logging.WARNING, stream=sys.stderr
    )
    return int(args.fn(args))
