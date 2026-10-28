"""Depth: how far down the player got, and when (capability graph section 5).

Depth score = how far down the player got, from the start (0) to the floor of the sealed room
(100), by the lowest point its hit box reached. Below the top of the seal plug only the samples in
which the hit box is inside the sealed room count: a tunnel dug past the vault to the bottom of
the world does not open the seal and is not depth.

`depth_curve` is the same rule sample by sample (the depth of every recorded sample, unrounded);
`deepest` is its maximum, `depth_score` the same plus the fields of the profile, and `reach_frame`
reads off the first moment a given depth was reached. One rule for all three, so the cross-game metrics
(`metrics/growth.py`) and the score cannot disagree about what counts as depth.
"""

from __future__ import annotations

from typing import Any

from .recording import RunData
from .rubric import clamp01

REACH_EPSILON = 1e-9  # depths are compared as floats: a level taken from a curve must reach itself


def _capped_feet(run: RunData) -> list[float]:
    """The lowest point (feet) of every sample that counts as depth: any sample counts at most the
    plug's top edge unless its hit box is inside the sealed room. Without a seal and room in the
    world file nothing is capped."""
    samples = run.track.samples
    room = run.world.seal_room
    plug = run.world.seal_plug
    if room is not None and plug is not None:
        return [
            s.feet if s.feet <= plug.y or s.box().overlaps(room) else float(plug.y) for s in samples
        ]
    return [s.feet for s in samples]


def _span(run: RunData) -> tuple[float, float]:
    """`(start y, span)`: the feet of the first sample, and the way down to the world's floor."""
    start = run.track.samples[0].feet
    return start, max(1.0, run.world.bottom - start)


def depth_curve(run: RunData) -> list[tuple[int, float]]:
    """`(frame, depth)` for every recorded sample of the player, depth 0..100 (unrounded)."""
    start, span = _span(run)
    return [
        (s.frame, 100.0 * clamp01((feet - start) / span))
        for s, feet in zip(run.track.samples, _capped_feet(run), strict=True)
    ]


def deepest(curve: list[tuple[int, float]]) -> float:
    """The depth score of a run read off its `depth_curve`, 0..100, unrounded."""
    return max((d for _f, d in curve), default=0.0)


def reach_frame(curve: list[tuple[int, float]], level: float) -> float | None:
    """The first frame at which the player was at `level` (depth 0..100) or deeper, or None.

    The recording is a sample every few frames and a falling player covers many cells between two
    of them, so the frame is found by interpolating linearly between the last sample above the
    level and the first at or below it (the depth of a stretch between samples is not known)."""
    for i, (frame, depth) in enumerate(curve):
        if depth + REACH_EPSILON < level:
            continue
        if i == 0:
            return float(frame)
        prev_frame, prev_depth = curve[i - 1]
        gap = depth - prev_depth
        t = 1.0 if gap <= 0 else min(1.0, max(0.0, (level - prev_depth) / gap))
        return prev_frame + t * (frame - prev_frame)
    return None


def depth_score(run: RunData) -> dict[str, Any]:
    """How far down the player got, 0 (the start) to 100 (the floor of the sealed room).

    Samples below the top of the seal plug count only while the hit box is inside the sealed
    room; any other sample counts at most the plug's top edge."""
    samples = run.track.samples
    start = samples[0].feet
    raw_deepest = run.track.deepest_feet()
    bottom = run.world.bottom
    room = run.world.seal_room
    deepest = max(_capped_feet(run))
    span = max(1.0, bottom - start)
    fraction = clamp01((deepest - start) / span)
    reached = bool(room and run.track.touched(room, 0, run.last_frame))
    return {
        "score": round(100.0 * fraction, 2),
        "fraction": round(fraction, 4),
        "start_y": round(start, 1),
        "deepest_y": round(deepest, 1),
        "deepest_raw_y": round(raw_deepest, 1),
        "capped_at_seal": deepest < raw_deepest,
        "bottom_y": round(bottom, 1),
        "reached_sealed_room": reached,
    }
