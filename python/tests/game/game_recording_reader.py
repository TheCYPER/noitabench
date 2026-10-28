"""Just enough of a `cogbench-rec/0` reader for the game tests (contract section 5): the meta
file, the frame numbers of `frames.bin` and the event lines."""

from __future__ import annotations

import json
import struct
from pathlib import Path

HEADER = struct.Struct("<IHHHHBI")  # frame, x0, y0, w, h, codec, nbytes


def read_meta(run: Path) -> dict:
    return json.loads((run / "meta.json").read_text())


def frame_numbers(run: Path) -> list[int]:
    data = (run / "frames.bin").read_bytes()
    frames, pos = [], 0
    while pos < len(data):
        frame, *_rest, nbytes = HEADER.unpack_from(data, pos)
        frames.append(frame)
        pos += HEADER.size + nbytes
    return frames


def read_events(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
