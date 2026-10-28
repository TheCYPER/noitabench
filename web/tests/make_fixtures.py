"""Synthetic fixtures for the web viewer, written strictly per
.trellis/spec/backend/contracts.md sections 4 and 5.

The "physics" below is a toy cellular automaton that exists only to give the
viewer something moving to draw. It is NOT the game's simulation.

Run from anywhere:  .venv/bin/python web/tests/make_fixtures.py
Output (web/tests/fixtures/):
  rec_synthetic/        full-world frames, zlib and raw codecs, all optional files
  rec_synthetic_delta/  one keyframe then dirty-rect deltas, two rects per frame
                        sometimes, no optional files, unknown meta field
  world_synthetic.png/.json   256x192 world pair with markers and encounters
  indexed_4bit.png      16-colour 4-bit indexed PNG (Pillow picks the bit depth)
  expected.json         sha256 of decoded states, used by the node tests

Not produced here: rec_sim/ (a recording written by cogbench-sim; see its HOWTO.md).
"""

import hashlib
import json
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "fixtures"

MATS = json.loads((ROOT / "content" / "materials.json").read_text())["materials"]
IDX = {m["key"]: m["index"] for m in MATS}
AIR, SAND, WATER = IDX["air"], IDX["sand"], IDX["water"]
ROCK, GROUND, WOOD, BRICK = IDX["rock"], IDX["ground"], IDX["wood"], IDX["brick"]


def sha(arr: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(arr, dtype=np.uint8).tobytes()).hexdigest()


# ---------------------------------------------------------------- toy sim


def make_basin(w: int, h: int) -> np.ndarray:
    g = np.full((h, w), AIR, dtype=np.uint8)
    g[0, :] = ROCK
    g[-1, :] = ROCK
    g[:, 0] = ROCK
    g[:, -1] = ROCK
    g[h - 12 : h - 1, 1 : w - 1] = GROUND
    g[h - 24 : h - 12, 56:72] = GROUND  # a hill in the middle
    g[h - 12 - 1, 20:44] = AIR
    g[h - 40 : h - 38, 10:36] = WOOD  # a wooden shelf
    g[h - 40 : h - 38, 90:110] = WOOD
    g[h - 11 : h - 1, 1:6] = BRICK  # a few bricks at the bottom left
    return g


def toy_step(g: np.ndarray, t: int) -> None:
    """One frame of the toy automaton: powder sinks through water, liquid spreads."""
    h, w = g.shape
    moved = np.zeros_like(g, dtype=bool)
    for y in range(h - 2, 0, -1):
        xs = range(1, w - 1) if (t + y) % 2 == 0 else range(w - 2, 0, -1)
        for x in xs:
            c = g[y, x]
            if c not in (SAND, WATER) or moved[y, x]:
                continue

            def can(target: int, mover: int = int(c)) -> bool:
                return target == AIR or (mover == SAND and target == WATER)

            below = g[y + 1, x]
            order = (-1, 1) if (x * 7 + y * 13 + t) % 2 == 0 else (1, -1)
            dest = None
            if can(below):
                dest = (y + 1, x)
            else:
                for dx in order:
                    if can(g[y + 1, x + dx]) and g[y, x + dx] in (AIR, WATER):
                        dest = (y + 1, x + dx)
                        break
                if dest is None and c == WATER:
                    for dx in order:
                        if g[y, x + dx] == AIR:
                            dest = (y, x + dx)
                            break
            if dest is not None:
                dy, dx_ = dest
                g[y, x], g[dy, dx_] = g[dy, dx_], g[y, x]
                moved[dy, dx_] = True


def emit(g: np.ndarray, t: int) -> None:
    if t < 60 and t % 2 == 0:
        g[2, 25] = SAND
        g[2, 26] = SAND
    if t < 80 and t % 3 == 0:
        g[2, 95] = WATER
        g[2, 96] = WATER
        g[3, 95] = WATER


# ---------------------------------------------------------------- writers


def frame_record(frame: int, x0: int, y0: int, w: int, h: int, payload: bytes, codec: int) -> bytes:
    body = zlib.compress(payload, 6) if codec == 1 else payload
    return struct.pack("<IHHHHBI", frame, x0, y0, w, h, codec, len(body)) + body


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
    )


def meta(run_id: str, w: int, h: int, stride: int, notes: str, **extra: Any) -> dict[str, Any]:
    return {
        "format": "cogbench-rec/0",
        "run_id": run_id,
        "created": "2026-10-26T00:00:00Z",
        "world": {"width": w, "height": h},
        "materials_format": "cogbench-materials/0",
        "seed": 42,
        "rule_seed": 7,
        "frame_stride": stride,
        "notes": notes,
        **extra,
    }


# ---------------------------------------------------------------- recording 1: full frames


def rec_full(expected: dict[str, Any]) -> None:
    d = OUT / "rec_synthetic"
    d.mkdir(parents=True)
    w, h, stride, total = 128, 96, 2, 120
    g = make_basin(w, h)
    blob = bytearray()
    checks: dict[str, str] = {}
    entities: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    n = 0
    for t in range(total):
        emit(g, t)
        toy_step(g, t)
        if t % stride:
            continue
        codec = 0 if n % 10 == 0 else 1  # sprinkle in raw records
        blob += frame_record(t, 0, 0, w, h, g.tobytes(), codec)
        checks[str(t)] = sha(g)
        px = 10 + t * 0.8
        entities.append(
            {
                "frame": t,
                "entities": [
                    {
                        "id": 1,
                        "kind": "player",
                        "x": round(px, 2),
                        "y": h - 12 - 9,
                        "w": 4,
                        "h": 9,
                        "hp": max(10, 100 - t // 2),
                        "hp_max": 100,
                        "future_field": "ignored",
                    },
                    {
                        "id": 2,
                        "kind": "enemy_longleg",
                        "x": 100,
                        "y": h - 12 - 6,
                        "w": 6,
                        "h": 6,
                        "hp": 20,
                        "hp_max": 20,
                    },
                ],
            }
        )
        n += 1
    events += [
        {"frame": 8, "type": "reaction", "x": 26, "y": 60, "a": "sand", "b": "water"},
        {
            "frame": 30,
            "type": "damage",
            "x": 50,
            "y": h - 21,
            "amount": 12,
            "target": 1,
        },
        {"frame": 44, "type": "pickup", "x": 70, "y": h - 21, "item": "potion_heal"},
        {"frame": 70, "type": "explosion", "x": 96, "y": h - 25, "radius": 9},
        {"frame": 100, "type": "death", "x": 100, "y": h - 18, "target": 2},
        {
            "frame": 110,
            "type": "some_future_event",
            "note": "no position, must not crash",
        },
    ]
    decisions = [
        {
            "frame": 0,
            "index": 0,
            "stop_reason": "start",
            "command": "walk_to(x=100)",
            "observation_digest": "synthetic",
        },
        {"frame": 40, "index": 1, "stop_reason": "damaged", "command": "wait"},
        {"frame": 90, "index": 2, "stop_reason": "completed", "command": "inspect"},
    ]
    (d / "meta.json").write_text(
        json.dumps(
            meta("synthetic-full", w, h, stride, "synthetic fixture; toy physics"),
            indent=1,
        )
    )
    (d / "frames.bin").write_bytes(bytes(blob))
    write_jsonl(d / "entities.jsonl", entities)
    write_jsonl(d / "events.jsonl", events)
    write_jsonl(d / "decisions.jsonl", decisions)
    expected["rec_synthetic"] = {
        "steps": n,
        "width": w,
        "height": h,
        "checks": checks,
        "frames_bytes": len(blob),
    }


# ---------------------------------------------------------------- recording 2: keyframe + deltas


def bbox_of(diff: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(diff)
    if len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def rec_delta(expected: dict[str, Any]) -> None:
    d = OUT / "rec_synthetic_delta"
    d.mkdir(parents=True)
    w, h, stride, total = 128, 96, 3, 120
    g = make_basin(w, h)
    prev = None
    blob = bytearray()
    checks: dict[str, str] = {}
    steps, multi = 0, 0
    for t in range(total):
        emit(g, t)
        toy_step(g, t)
        if t % stride:
            continue
        if prev is None:
            blob += frame_record(t, 0, 0, w, h, g.tobytes(), 1)
            prev = g.copy()
            checks[str(t)] = sha(g)
            steps += 1
            continue
        rects: list[tuple[int, int, int, int]] = []
        for lo, hi in (
            (0, w // 2),
            (w // 2, w),
        ):  # one rect per half, so a frame can carry two records
            bb = bbox_of(g[:, lo:hi] != prev[:, lo:hi])
            if bb:
                rects.append((bb[0] + lo, bb[1], bb[2] + lo, bb[3]))
        if not rects:
            continue
        for x0, y0, x1, y1 in rects:
            blob += frame_record(t, x0, y0, x1 - x0, y1 - y0, g[y0:y1, x0:x1].tobytes(), 1)
        multi += len(rects) > 1
        prev = g.copy()
        checks[str(t)] = sha(g)
        steps += 1
    (d / "meta.json").write_text(
        json.dumps(
            meta(
                "synthetic-delta",
                w,
                h,
                stride,
                "keyframe then dirty rects",
                unknown_future_field=[1, 2, 3],
            )
        )
    )
    (d / "frames.bin").write_bytes(bytes(blob))
    expected["rec_synthetic_delta"] = {
        "steps": steps,
        "multi_record_steps": multi,
        "width": w,
        "height": h,
        "checks": checks,
    }


# ---------------------------------------------------------------- world pair


def palette_bytes() -> list[int]:
    pal = [0] * 768
    for m in MATS:
        c = m["color"].lstrip("#")
        pal[m["index"] * 3 : m["index"] * 3 + 3] = [int(c[i : i + 2], 16) for i in (0, 2, 4)]
    return pal


def world_pair(expected: dict[str, Any]) -> None:
    w, h, cell = 256, 192, 64
    rng = np.random.default_rng(7)
    g = np.full((h, w), GROUND, dtype=np.uint8)
    noise = rng.random((h, w)) < 0.07
    g[noise] = ROCK
    # carve a winding cave along the middle with a random walk
    x, y = 30, 20
    for _ in range(900):
        g[max(1, y - 6) : y + 6, max(1, x - 6) : x + 6] = AIR
        x = int(np.clip(x + rng.integers(-3, 6), 8, w - 9))
        y = int(np.clip(y + rng.integers(-2, 5), 8, h - 9))
    g[90:104, 150:210] = WATER
    g[104:108, 150:210] = ROCK
    g[40:60, 20:60] = SAND
    g[150:160, 60:120] = IDX["lava"]
    g[h - 6 :, :] = BRICK
    g[0, :] = ROCK
    g[:, 0] = ROCK
    g[:, -1] = ROCK

    img = Image.frombytes("P", (w, h), g.tobytes())
    img.putpalette(palette_bytes())
    img.save(OUT / "world_synthetic.png")

    biome_map = [
        ["coal_pit", "mine", "sand_cave", "sand_cave"],
        ["fungus", "marsh", "oil_cave", "oil_cave"],
        ["acid_lake", "lava_deep", "brick_ruin", "brick_ruin"],
    ]
    markers = [
        {"type": "spawn_player", "x": 30, "y": 20},
        {"type": "spawn_enemy", "enemy": "longleg", "x": 120, "y": 60},
        {"type": "spawn_enemy", "enemy": "shotgunner", "x": 200, "y": 140},
        {"type": "item", "item": "wand_basic", "x": 70, "y": 30},
        {"type": "item", "item": "potion_heal", "x": 180, "y": 80},
        {
            "type": "encounter",
            "encounter_id": "E16",
            "variant": 1,
            "x": 100,
            "y": 40,
            "trigger": {"x": 90, "y": 30, "w": 40, "h": 24},
            "must_pass": True,
        },
        {
            "type": "encounter",
            "encounter_id": "E08",
            "variant": 0,
            "x": 190,
            "y": 100,
            "trigger": {"x": 170, "y": 88, "w": 50, "h": 20},
            "must_pass": False,
        },
        {
            "type": "encounter",
            "encounter_id": "E02",
            "variant": 3,
            "x": 80,
            "y": 150,
            "trigger": {"x": 60, "y": 140, "w": 64, "h": 30},
            "must_pass": True,
        },
        {"type": "rest_area", "x": 120, "y": 120, "w": 30, "h": 20},
        {"type": "seal", "x": 128, "y": 184},
        {
            "type": "future_marker_type",
            "x": 10,
            "y": 10,
            "note": "unknown types must still draw",
        },
    ]
    main_path = [[30, 20], [60, 40], [100, 60], [128, 100], [100, 140], [128, 180]]
    doc = {
        "format": "cogbench-world/0",
        "seed": 12345,
        "rule_seed": 7,
        "width": w,
        "height": h,
        "biome_cell_size": cell,
        "biome_map": biome_map,
        "markers": markers,
        "main_path": main_path,
    }
    (OUT / "world_synthetic.json").write_text(json.dumps(doc, indent=1))
    expected["world_synthetic"] = {"width": w, "height": h, "sha256": sha(g)}

    # a second PNG: 16 colours only, so Pillow writes 4 bits per pixel
    small = np.add.outer(np.arange(37), np.arange(53)).astype(np.uint8) % 16
    simg = Image.frombytes("P", (53, 37), small.tobytes())
    simg.putpalette([v for i in range(16) for v in (i * 16, 255 - i * 16, (i * 37) % 256)])
    simg.save(OUT / "indexed_4bit.png")
    expected["indexed_4bit"] = {"width": 53, "height": 37, "sha256": sha(small)}


def main() -> None:
    """Regenerate the synthetic fixtures from scratch (deterministic).

    Only the files and folders written below are replaced. Anything else in
    fixtures/ (rec_sim/, which comes from the real simulation) is left alone.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("rec_synthetic", "rec_synthetic_delta"):
        shutil.rmtree(OUT / name, ignore_errors=True)
    for name in (
        "world_synthetic.png",
        "world_synthetic.json",
        "indexed_4bit.png",
        "expected.json",
    ):
        (OUT / name).unlink(missing_ok=True)
    expected: dict[str, Any] = {}
    rec_full(expected)
    rec_delta(expected)
    world_pair(expected)
    (OUT / "expected.json").write_text(json.dumps(expected, indent=1))
    print("wrote", OUT)
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(OUT)}  {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
