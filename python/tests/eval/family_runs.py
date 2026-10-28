"""Hand-made families of games on disk for the cross-game tests (`write_run` games that walk
straight down, with damage events and decisions as asked)."""

from __future__ import annotations

import json
from pathlib import Path

from eval_runs import damage, walk, write_run
from noitabench.eval.metrics.growth import GROWTH_METRICS

SEAL = {"x": 436, "y": 1574, "w": 16, "h": 6, "room": {"x": 376, "y": 1580, "w": 136, "h": 56}}
START_FEET, FLOOR = 93.0, 1636.0  # the lab world: spawn feet, floor of the sealed room
MODEL = {"provider": "fake", "model": "m"}


def feet_to_top(depth: float) -> float:
    """The y of the hit box's top at `depth` (0 to 100) of the way down."""
    return START_FEET + depth / 100 * (FLOOR - START_FEET) - 16


def make_game(
    root: Path,
    *,
    depth: float,
    frames: int,
    hold: int = 100,
    hurt: tuple[tuple[int, float], ...] = (),
    decisions: tuple[int, ...] | None = None,
    x: float = 150,
    model: dict | None = MODEL,
    rule_seed: int = 0,
    seed: int = 1,
    cleared: bool = False,
    over: str = "dead",
) -> Path:
    """A game that walks straight down to `depth` by frame `frames` and stays `hold` more frames.
    `x` is where it ends (the sealed room lies at x 376 to 512); `hurt` is `(frame, HP)` damage
    events; `decisions` the frames at which one-cost decisions were asked (none: no
    decisions.jsonl)."""
    top = feet_to_top(depth)
    track = walk([(0, 150, 77), (frames, x, top), (frames + hold, x, top)])
    summary = None
    if model is not None:
        summary = {
            "model": model,
            "workspace_cleared_each_game": cleared,
            "result": {"over": over, "cost_usd": 0.01},
        }
    write_run(
        root,
        track=track,
        events=[damage(f, hp) for f, hp in hurt],
        decisions=None
        if decisions is None
        else [{"frame": f, "cost": 1, "stop_reason": "completed"} for f in decisions],
        summary=summary,
        seal=SEAL,
    )
    meta = json.loads((root / "meta.json").read_text())
    meta.update(rule_seed=rule_seed, seed=seed)
    (root / "meta.json").write_text(json.dumps(meta))
    world = json.loads((root / "world" / "world.json").read_text())
    world.update(rule_seed=rule_seed, seed=seed)
    (root / "world" / "world.json").write_text(json.dumps(world))
    return root


def metrics_of(profile: dict) -> dict[str, dict]:
    return {m["name"]: m for m in profile["metrics"] if m["name"] in GROWTH_METRICS}


# game 1 of the design's example: depth 30 at frame 600, 80 HP lost and 200 decisions before that
GAME_1 = {
    "depth": 30.0,
    "frames": 600,
    "hurt": ((100, 20.0), (200, 20.0), (300, 20.0), (400, 20.0), (650, 30.0)),
    "decisions": tuple(3 * i for i in range(200)) + tuple(610 + 3 * i for i in range(10)),
}
# game 3: depth 65 (depth 30 at frame 553.8), 40 HP lost and 120 decisions before depth 30
GAME_3 = {
    "depth": 65.0,
    "frames": 1200,
    "hurt": ((200, 20.0), (500, 20.0), (800, 25.0)),
    "decisions": tuple(4 * i for i in range(120)) + tuple(600 + 3 * i for i in range(80)),
}


def example_family(tmp_path: Path) -> Path:
    fam = tmp_path / "fam"
    make_game(fam / "run-01", **GAME_1)
    make_game(fam / "run-02", **GAME_1)  # a repeat of game 1
    make_game(fam / "run-03", **GAME_3)
    return fam
