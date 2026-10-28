"""Reader for `cogbench-rec/0`, written from `.trellis/spec/backend/contracts.md` section 5 only
(independent of the Rust writer, so tests check what the web viewer will actually see)."""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

HEADER = struct.Struct("<IHHHHBI")  # frame, x0, y0, w, h, codec, nbytes


@dataclass(frozen=True)
class FrameRecord:
    frame: int
    x0: int
    y0: int
    w: int
    h: int
    pixels: bytes


def read_meta(run: Path) -> dict:
    return json.loads((run / "meta.json").read_text())


def read_frames(run: Path) -> list[FrameRecord]:
    data = (run / "frames.bin").read_bytes()
    frames, pos = [], 0
    while pos < len(data):
        frame, x0, y0, w, h, codec, n = HEADER.unpack_from(data, pos)
        payload = data[pos + HEADER.size : pos + HEADER.size + n]
        if codec == 0:
            pixels = payload
        elif codec == 1:
            pixels = zlib.decompress(payload)
        else:
            raise ValueError(f"unknown codec {codec}")
        if len(pixels) != w * h:
            raise ValueError(f"frame {frame}: payload has {len(pixels)} bytes, want {w * h}")
        frames.append(FrameRecord(frame, x0, y0, w, h, pixels))
        pos += HEADER.size + n
    return frames


def read_events(run: Path) -> list[dict]:
    path = run / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]
