"""Boxes and the player's track: where the hit box was, and when it touched a region.

The recording samples the player every `frame_stride` frames (12 in the runs so far), and a
falling player moves about 6 cells per frame, so two samples can lie 70 cells apart. `Track`
therefore interpolates linearly between samples when it asks whether the box touched a region;
a trigger is never skipped by a fast fall.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, NamedTuple

MERGE_GAP = 120  # frames: two stays in a region closer than this are one stay


@dataclass(frozen=True)
class Rect:
    """An axis-aligned box in cells, top-left corner and size (contracts section 4)."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def grow(self, n: int) -> Rect:
        return Rect(self.x - n, self.y - n, self.w + 2 * n, self.h + 2 * n)

    def overlaps(self, other: Rect) -> bool:
        return (
            self.x < other.right
            and other.x < self.right
            and self.y < other.bottom
            and other.y < self.bottom
        )

    def has_point(self, px: float, py: float) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    @staticmethod
    def parse(value: Any) -> Rect:
        """From `{x, y, w, h}` or a list `[x, y, w, h]`."""
        if isinstance(value, dict):
            return Rect(int(value["x"]), int(value["y"]), int(value["w"]), int(value["h"]))
        x, y, w, h = value
        return Rect(int(x), int(y), int(w), int(h))


class Sample(NamedTuple):
    """The player's hit box (top-left corner, size) and health at one recorded frame."""

    frame: int
    x: float
    y: float
    w: float
    h: float
    hp: float
    hp_max: float

    def box(self) -> Rect:
        return Rect(int(self.x), int(self.y), int(self.w), int(self.h))

    @property
    def feet(self) -> float:
        return self.y + self.h


def _lerp(a: Sample, b: Sample | None, frame: int) -> Sample:
    """The box at `frame` between samples `a` and `b` (health of `a`)."""
    if b is None or b.frame <= a.frame:
        return a
    t = (frame - a.frame) / (b.frame - a.frame)
    return Sample(frame, a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.w, a.h, a.hp, a.hp_max)


class Track:
    """The samples of the player, in frame order, with interpolation between them."""

    def __init__(self, samples: list[Sample]) -> None:
        self.samples = samples
        self._frames = [s.frame for s in samples]

    def __len__(self) -> int:
        return len(self.samples)

    @property
    def first_frame(self) -> int:
        return self.samples[0].frame if self.samples else 0

    @property
    def last_frame(self) -> int:
        return self.samples[-1].frame if self.samples else 0

    def at(self, frame: int) -> Sample | None:
        """The player's box at `frame` (positions interpolated, health of the sample before)."""
        if not self.samples:
            return None
        i = bisect_right(self._frames, frame) - 1
        if i < 0:
            return self.samples[0]
        a = self.samples[i]
        if i + 1 >= len(self.samples) or a.frame == frame:
            return a
        return _lerp(a, self.samples[i + 1], frame)

    def between(self, f0: int, f1: int) -> list[Sample]:
        """The recorded samples with `f0 <= frame <= f1`."""
        lo = bisect_right(self._frames, f0 - 1)
        hi = bisect_right(self._frames, f1)
        return self.samples[lo:hi]

    def touch_frames(self, region: Rect) -> list[int]:
        """Every frame at which the (interpolated) hit box touched `region`, in order."""
        out: list[int] = []
        samples = self.samples
        for i, a in enumerate(samples):
            b = samples[i + 1] if i + 1 < len(samples) else None
            lo_x, hi_x = (a.x, a.x) if b is None else (min(a.x, b.x), max(a.x, b.x))
            lo_y, hi_y = (a.y, a.y) if b is None else (min(a.y, b.y), max(a.y, b.y))
            if not (
                lo_x < region.right
                and region.x < hi_x + a.w
                and lo_y < region.bottom
                and region.y < hi_y + a.h
            ):
                continue
            end = a.frame + 1 if b is None else max(b.frame, a.frame + 1)
            for f in range(a.frame, end):
                s = _lerp(a, b, f)
                if Rect(int(s.x), int(s.y), int(s.w), int(s.h)).overlaps(region):
                    out.append(f)
        return out

    def stays(self, region: Rect, *, gap: int = MERGE_GAP) -> list[tuple[int, int]]:
        """`(enter, exit)` frames of the stays of the hit box in `region`, nearby stays merged.

        `exit` is the last frame the box touched the region."""
        spans: list[list[int]] = []
        for f in self.touch_frames(region):
            if spans and f - spans[-1][1] <= max(gap, 1):
                spans[-1][1] = f
            else:
                spans.append([f, f])
        return [(lo, hi) for lo, hi in spans]

    def touched(self, region: Rect, f0: int, f1: int) -> bool:
        """True if the box touched `region` at some frame in `[f0, f1]`."""
        return any(lo <= f1 and hi >= f0 for lo, hi in self.stays(region, gap=0))

    def first_touch(self, region: Rect, f0: int, f1: int) -> int | None:
        """The first frame in `[f0, f1]` at which the box touched `region`."""
        best = None
        for lo, hi in self.stays(region, gap=0):
            if lo <= f1 and hi >= f0:
                best = max(lo, f0) if best is None else min(best, max(lo, f0))
        return best

    def deepest_feet(self) -> float:
        return max((s.feet for s in self.samples), default=0.0)

    def path_length(self, f0: int | None = None, f1: int | None = None) -> float:
        """Length in cells of the polyline through the samples of `[f0, f1]`."""
        pts = self.samples if f0 is None else self.between(f0, f1 if f1 is not None else 10**12)
        total = 0.0
        for a, b in pairwise(pts):
            total += ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
        return total
