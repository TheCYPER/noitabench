"""Read the material grid back from `frames.bin` (`cogbench-rec/0`, contracts section 5).

The evaluator rarely needs the grid (which hazard hurt the player at the moment of a damage
event), so this reader only indexes the 17-byte record headers and decompresses the few frames it
is asked for: the nearest full-world record at or before the frame, then the partial rectangles
after it. If the file is missing the world's first grid (the PNG) answers instead.
"""

from __future__ import annotations

import struct
import zlib
from bisect import bisect_right
from pathlib import Path
from typing import NamedTuple

import numpy as np

HEADER = struct.Struct("<IHHHHBI")  # frame, x0, y0, w, h, codec, nbytes


class Record(NamedTuple):
    frame: int
    x0: int
    y0: int
    w: int
    h: int
    codec: int
    offset: int
    nbytes: int


class FrameReader:
    """`grid_at(frame)`: the world's material indices at (the record at or before) `frame`;
    `window(frame, x0, y0, x1, y1)`: a piece of a recorded grid, cheaper to read."""

    def __init__(
        self, path: Path, base: np.ndarray | None, size: tuple[int, int] | None = None
    ) -> None:
        """`size` is (width, height) of the world; it defaults to the shape of `base`."""
        self.path = path
        self.base = base
        self.size = size if size is not None else (None if base is None else base.shape[::-1])
        self.records: list[Record] = _index(path) if path.exists() else []
        self._frames = [r.frame for r in self.records]
        self._cache: tuple[int, np.ndarray] | None = None

    @property
    def available(self) -> bool:
        return bool(self.records) or self.base is not None

    def grid_at(self, frame: int) -> np.ndarray | None:
        """A (height, width) uint8 array, or None if nothing is known about the grid.

        A record that cannot be read (a damaged file) is not an error: the first grid answers."""
        try:
            return self._grid_at(frame)
        except (zlib.error, ValueError, OSError):
            return self.base

    def window(self, frame: int, x0: int, y0: int, x1: int, y1: int) -> np.ndarray | None:
        """The recorded cells `[y0:y1, x0:x1]` (clipped to the world) at (the record at or before)
        `frame`; None if no record is at or before it or it cannot be read (the first grid, the
        PNG, never answers: a window is only what was recorded). Of a full-world compressed
        record only the rows down to `y1` are decompressed."""
        last = bisect_right(self._frames, frame) - 1
        if last < 0:
            return None
        r = self.records[last]
        x0, y0 = max(0, x0), max(0, y0)
        cached = self._cache is not None and self._cache[0] == r.frame
        if cached or not self._is_full(r) or r.codec != 1:
            grid = self.grid_at(frame)
            return None if grid is None or grid is self.base else grid[y0:y1, x0:x1]
        rows = max(0, min(r.h, y1))
        try:
            with self.path.open("rb") as handle:
                handle.seek(r.offset)
                head = zlib.decompressobj().decompress(handle.read(r.nbytes), rows * r.w)
        except (zlib.error, OSError):
            return None
        if len(head) < rows * r.w:
            return None
        return np.frombuffer(head, dtype=np.uint8).reshape(rows, r.w)[y0:y1, x0:x1]

    def _is_full(self, r: Record) -> bool:
        return self.size is not None and (r.x0, r.y0, r.w, r.h) == (0, 0, *self.size)

    def _grid_at(self, frame: int) -> np.ndarray | None:
        last = bisect_right(self._frames, frame) - 1
        if last < 0:
            return self.base
        target = self.records[last].frame
        if self._cache is not None and self._cache[0] == target:
            return self._cache[1]
        full = self._full_world_index(last)
        if full is None:
            grid = None if self.base is None else self.base.copy()
            first = 0
        else:
            grid = self._read(self.records[full])
            first = full + 1
        if grid is None:
            return None
        with self.path.open("rb") as handle:
            for r in self.records[first : last + 1]:
                if r.frame > target:
                    break
                part = _payload(handle, r)
                grid[r.y0 : r.y0 + r.h, r.x0 : r.x0 + r.w] = part
        self._cache = (target, grid)
        return grid

    def _full_world_index(self, upto: int) -> int | None:
        for i in range(upto, -1, -1):
            if self._is_full(self.records[i]):
                return i
        return None

    def _read(self, record: Record) -> np.ndarray:
        with self.path.open("rb") as handle:
            return _payload(handle, record).copy()


def _payload(handle, record: Record) -> np.ndarray:
    handle.seek(record.offset)
    raw = handle.read(record.nbytes)
    if record.codec == 1:
        raw = zlib.decompress(raw)
    return np.frombuffer(raw, dtype=np.uint8).reshape(record.h, record.w)


def _index(path: Path) -> list[Record]:
    """The records of the file; a cut-off last record (or garbage after the last good one) ends
    the list."""
    out: list[Record] = []
    size = path.stat().st_size
    with path.open("rb") as handle:
        pos = 0
        while pos + HEADER.size <= size:
            head = handle.read(HEADER.size)
            if len(head) < HEADER.size:
                break
            frame, x0, y0, w, h, codec, nbytes = HEADER.unpack(head)
            end = pos + HEADER.size + nbytes
            if end > size or codec > 1 or (out and frame < out[-1].frame):
                break  # cut off, not a record, or out of order
            out.append(Record(frame, x0, y0, w, h, codec, pos + HEADER.size, nbytes))
            pos = end
            handle.seek(pos)
    return out
