"""Where the player met harmful materials: the recorded grid around the hit box, sample by sample
(for N4 `first_contact_physics` in `physics.py`; no metric of its own).

A kind (lava, acid, toxic sludge) is *met* at a sample when a cell of it lies within `REACH` cells
of the hit box: one wrong step or a short fall would touch it. Reach is counted in 8-neighbour
steps that cross no brick or metal (statics the starting digger cannot remove: the player can
neither dig nor walk through them); a thinner wall of rock or ground is no shield (the hit box
overlaps thin walls, and they are dug in a moment). The kind is *touched* at a sample when the hit
box itself holds at least `contact.min_cells` cells of it (`content/entities.json`, the engine's
own threshold for contact). A meeting lasts while the kind stays in reach, with gaps under
`MEET_GAP` frames, for at most `MEET_CAP` frames.

Only recorded grids count (`frames.bin`, read through `FrameReader.window`); the world PNG is the
first frame only and says nothing about where liquids flowed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache

import numpy as np

from ..geometry import Sample
from ..recording import RunData
from ..worldinfo import CONTENT, material_keys, undiggable_indices

REACH = 3  # cells from the hit box: a hazard this close is met
MEET_GAP = 60  # frames out of reach that still belong to the same meeting
MEET_CAP = 1800  # frames: a meeting is judged over at most 30 seconds
MAX_MEET_CHECKS = 12_000  # samples scanned (about 40 minutes of play); past it: not known
HAZARDS = {"lava": ("lava",), "acid": ("acid",), "toxic": ("toxic_sludge",)}


@dataclass
class Meeting:
    """The first meeting of one kind: `start`/`end` the first and last sample in reach, `touch`
    the first sample at which the hit box held the kind (None: never touched it)."""

    start: int
    end: int
    touch: int | None = None


@cache
def _min_cells() -> int:
    data = json.loads((CONTENT / "entities.json").read_text(encoding="utf-8"))
    return int(data["contact"]["min_cells"])


@cache
def _cells() -> dict[str, np.ndarray]:
    keys = material_keys()
    return {
        kind: np.array([i for i, k in enumerate(keys) if k in names], dtype=np.uint8)
        for kind, names in HAZARDS.items()
    }


@cache
def _walls() -> np.ndarray:
    return np.array(sorted(undiggable_indices()), dtype=np.uint8)


def _in_reach(window: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """The cells of `window` within `REACH` 8-neighbour steps of the hit box `box` (x0, y0, x1, y1
    in window cells), never crossing brick or metal."""
    open_cells = ~np.isin(window, _walls())
    mask = np.zeros(window.shape, dtype=bool)
    x0, y0, x1, y1 = box
    mask[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = True
    mask &= open_cells
    for _ in range(REACH):
        grown = mask.copy()
        grown[1:] |= mask[:-1]
        grown[:-1] |= mask[1:]
        wide = grown.copy()
        wide[:, 1:] |= grown[:, :-1]
        wide[:, :-1] |= grown[:, 1:]
        mask = wide & open_cells
    return mask


def kinds_at(run: RunData, sample: Sample) -> tuple[set[str], set[str]] | None:
    """(the kinds within reach, the kinds touched) at `sample`; None if no grid was recorded."""
    x0, y0 = int(sample.x) - REACH, int(sample.y) - REACH
    x1, y1 = int(sample.x + sample.w) + REACH, int(sample.y + sample.h) + REACH
    window = run.frames.window(sample.frame, x0, y0, x1, y1)
    if window is None or window.size == 0:
        return None
    ox, oy = max(0, x0), max(0, y0)
    box = (int(sample.x) - ox, int(sample.y) - oy, int(sample.x + sample.w) - ox,
           int(sample.y + sample.h) - oy)  # fmt: skip
    reach = _in_reach(window, box)
    inside = window[max(0, box[1]) : max(0, box[3]), max(0, box[0]) : max(0, box[2])]
    near, touched = set(), set()
    for kind, idx in _cells().items():
        if bool((np.isin(window, idx) & reach).any()):
            near.add(kind)
            if int(np.isin(inside, idx).sum()) >= _min_cells():
                touched.add(kind)
    return near, touched


class Scan:
    """The first meeting of each kind (`met`), how far the scan saw (`upto`: the last frame with
    a recorded grid looked at, None if none) and why it saw no further (`cut`, None if it saw the
    whole run)."""

    def __init__(self, run: RunData) -> None:
        self.met: dict[str, Meeting] = {}
        self.upto: int | None = None
        self.cut: str | None = None
        if not run.frames.records:
            self.cut = "no recorded grid (frames.bin): meetings cannot be seen"
            return
        self._scan(run)
        if self.upto is None:
            self.cut = "no recorded grid at the player's samples"

    def _scan(self, run: RunData) -> None:
        going: dict[str, Meeting] = {}
        for k, sample in enumerate(run.track.samples):
            if len(self.met) == len(HAZARDS):
                break
            if k >= MAX_MEET_CHECKS:
                self.cut = f"the scan stopped at {MAX_MEET_CHECKS} samples (frame {sample.frame})"
                break
            seen = kinds_at(run, sample)
            if seen is None:
                continue
            self.upto = sample.frame
            for kind in HAZARDS:
                if kind not in self.met:
                    self._step(kind, sample.frame, seen, going)
        for kind, meeting in going.items():
            self.met.setdefault(kind, meeting)

    def _step(
        self, kind: str, frame: int, seen: tuple[set[str], set[str]], going: dict[str, Meeting]
    ) -> None:
        near, touched = seen
        m = going.get(kind)
        if m is not None and (frame - m.end > MEET_GAP or frame - m.start > MEET_CAP):
            self.met[kind] = Meeting(m.start, min(m.end, m.start + MEET_CAP), m.touch)
        elif kind in near:
            m = going.setdefault(kind, Meeting(frame, frame))
            m.end = frame
            if kind in touched and m.touch is None:
                m.touch = frame
