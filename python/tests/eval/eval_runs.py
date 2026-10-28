"""Hand-made run folders for the evaluation tests.

`write_run` writes a recording folder (`meta.json`, `entities.jsonl`, `events.jsonl`, optional
`decisions.jsonl`, `transcript.jsonl`, `summary.json`) and a world file pair next to it, so a
rule can be tested on a few lines of "the player went here, this happened". Encounter geometry
comes from the real scene definitions (`worldgen.scene_world`), so regions are the real ones.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Iterable, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from noitabench.eval.frames import HEADER
from noitabench.eval.geometry import Rect
from noitabench.worldgen.config import load_materials
from noitabench.worldgen.scene_world import scene_world
from PIL import Image

WIDTH, HEIGHT = 768, 1664
BIOME_MAP = (
    [["start"] * 6]
    + [["coal_pit", "coal_pit", "mine", "mine", "sand_cave", "sand_cave"]] * 3
    + [["rest_1"] * 6]
    + [["fungal", "fungal", "swamp", "swamp", "oil_cave", "oil_cave"]] * 3
    + [["rest_2"] * 6]
    + [["workshop", "workshop", "lava_deeps", "lava_deeps", "brick_ruins", "brick_ruins"]] * 3
    + [["seal"] * 6]
)
PLAYER = (6, 16)
STRIDE = 12

_MATS = None


def lab_marker(eid: str, variant: int = 0, *, dx: int = 0, dy: int = 0) -> dict[str, Any]:
    """The encounter marker of the lab world of `eid` (real regions), shifted by `(dx, dy)`."""
    global _MATS
    _MATS = _MATS or load_materials()
    world = scene_world(eid, variant, 0, 1, _MATS)
    marker = next(m for m in world.markers if m["type"] == "encounter")
    out = json.loads(json.dumps(marker))

    def shift(box: dict[str, int]) -> dict[str, int]:
        return {**box, "x": box["x"] + dx, "y": box["y"] + dy}

    out["x"] += dx
    out["y"] += dy
    for key in ("trigger", "footprint"):
        out[key] = shift(out[key])
    out["regions"] = {k: shift(v) for k, v in out["regions"].items()}
    return out


def box(marker: dict[str, Any], region: str) -> Rect:
    return Rect.parse(marker["regions"][region])


def walk(
    points: Sequence[tuple[int, float, float]], stride: int = STRIDE
) -> list[tuple[int, float, float]]:
    """Straight-line samples every `stride` frames through `(frame, x, y)` waypoints."""
    out: list[tuple[int, float, float]] = []
    for (f0, x0, y0), (f1, x1, y1) in pairwise(points):
        for f in range(f0, f1, stride):
            t = (f - f0) / max(1, f1 - f0)
            out.append((f, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    f, x, y = points[-1]
    out.append((f, x, y))
    return out


def write_run(
    root: Path,
    *,
    markers: Iterable[dict[str, Any]] = (),
    track: Sequence[tuple[int, float, float]] = (),
    hp: dict[int, float] | None = None,
    events: Iterable[dict[str, Any]] = (),
    decisions: Iterable[dict[str, Any]] | None = None,
    transcript: Iterable[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    creatures: dict[int, list[dict[str, Any]]] | None = None,
    main_path: Sequence[Sequence[float]] = (),
    seal: dict[str, Any] | None = None,
    patches: Sequence[tuple[int, int, int, int, int]] = (),
    recorded: bool = False,
    notes: str = "synthetic test run",
) -> Path:
    """Write the folder `root` and return it. `hp` maps a frame to the health from there on.

    `patches` are `(x, y, w, h, material index)` rectangles painted into the world PNG (the grid
    at frame 0); without any, no PNG is written. `recorded` also writes `frames.bin` with that
    grid recorded at every sample of the track (a world whose cells never move)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "world").mkdir(exist_ok=True)
    all_markers = [{"type": "spawn_player", "x": 150, "y": 77}, *markers]
    if seal is not None:
        all_markers.append({"type": "seal", **seal})
    world = {
        "format": "cogbench-world/0",
        "seed": 1,
        "rule_seed": 0,
        "width": WIDTH,
        "height": HEIGHT,
        "biome_cell_size": 128,
        "biome_map": BIOME_MAP,
        "markers": all_markers,
        "meta": {"main_path": [list(p) for p in main_path]},
    }
    (root / "world" / "world.json").write_text(json.dumps(world), encoding="utf-8")
    if patches:
        grid = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
        for x, y, w, h, index in patches:
            grid[y : y + h, x : x + w] = index
        Image.fromarray(grid).save(root / "world" / "world.png")
        if recorded:
            write_frames(root, grid, [f for f, _x, _y in track])
    meta = {
        "format": "cogbench-rec/0",
        "run_id": root.name,
        "seed": 1,
        "rule_seed": 0,
        "world": {"width": WIDTH, "height": HEIGHT},
        "frame_stride": STRIDE,
        "notes": notes,
        "last_frame": track[-1][0] if track else 0,
    }
    (root / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    steps = sorted((hp or {0: 100.0}).items())
    lines = []
    for frame, x, y in track:
        health = [h for f, h in steps if f <= frame][-1] if steps else 100.0
        player = {"id": 1, "kind": "player", "x": x, "y": y, "w": PLAYER[0], "h": PLAYER[1]}
        player.update(hp=health, hp_max=100.0)
        crowd = (creatures or {}).get(frame, [])
        lines.append(json.dumps({"frame": frame, "entities": [player, *crowd]}))
    (root / "entities.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ev = sorted(events, key=lambda e: e["frame"])
    (root / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8"
    )
    if decisions is not None:
        rows = [{"index": i + 1, "ok": True, **d} for i, d in enumerate(decisions)]
        (root / "decisions.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )
    if transcript is not None:
        (root / "transcript.jsonl").write_text(
            "\n".join(json.dumps({"seq": i + 1, **t}) for i, t in enumerate(transcript)) + "\n",
            encoding="utf-8",
        )
    if summary is not None:
        (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return root


def write_frames(root: Path, grid: np.ndarray, frames: Iterable[int]) -> None:
    """`frames.bin` holding `grid` as a full-world zlib record at each of `frames`."""
    blob = zlib.compress(np.ascontiguousarray(grid, dtype=np.uint8).tobytes())
    head = (0, 0, grid.shape[1], grid.shape[0], 1, len(blob))
    with (root / "frames.bin").open("wb") as out:
        for frame in sorted(set(frames)):
            out.write(HEADER.pack(frame, *head) + blob)


def damage(frame: int, amount: float, source: str = "contact", hp: float = 50.0) -> dict[str, Any]:
    return {
        "frame": frame,
        "type": "damage",
        "target": "player",
        "id": 1,
        "amount": amount,
        "source": source,
        "hp": hp,
        "x": 0,
        "y": 0,
    }


def command(frame: int, name: str, **args: Any) -> dict[str, Any]:
    """A one-command decision asked at `frame`."""
    return {"frame": frame, "stop_reason": "completed", "command": [{"name": name, "args": args}]}
