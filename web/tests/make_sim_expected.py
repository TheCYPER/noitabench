"""Reference state hashes for fixtures/rec_sim/, decoded without any web code.

rec_sim/ is a real recording written by cogbench-sim (see rec_sim/HOWTO.md). This
script reads its frames.bin with Python's own struct/zlib/numpy, rebuilds the grid
step by step, and writes the sha256 of every state to rec_sim/expected.json. The
Node tests then check that the viewer's decoder reproduces the same bytes.

Run:  .venv/bin/python web/tests/make_sim_expected.py
"""

import hashlib
import json
import struct
import zlib
from pathlib import Path

import numpy as np

DIR = Path(__file__).resolve().parent / "fixtures" / "rec_sim"
HEADER = struct.Struct("<IHHHHBI")  # frame x0 y0 w h codec nbytes: contracts.md section 5


def main() -> None:
    meta = json.loads((DIR / "meta.json").read_text())
    width, height = meta["world"]["width"], meta["world"]["height"]
    buf = (DIR / "frames.bin").read_bytes()
    state = np.zeros((height, width), dtype=np.uint8)
    checks: dict[str, str] = {}
    pos = 0
    while pos < len(buf):
        frame, x0, y0, w, h, codec, nbytes = HEADER.unpack_from(buf, pos)
        pos += HEADER.size
        payload = buf[pos : pos + nbytes]
        pos += nbytes
        data = zlib.decompress(payload) if codec == 1 else payload
        assert len(data) == w * h, (frame, len(data), w, h)
        state[y0 : y0 + h, x0 : x0 + w] = np.frombuffer(data, dtype=np.uint8).reshape(h, w)
        checks[str(frame)] = hashlib.sha256(state.tobytes()).hexdigest()
    events = [line for line in (DIR / "events.jsonl").read_text().splitlines() if line.strip()]
    out = {
        "steps": len(checks),
        "width": width,
        "height": height,
        "events": len(events),
        "seed": str(meta["seed"]),
        "rule_seed": str(meta["rule_seed"]),
        "checks": checks,
    }
    (DIR / "expected.json").write_text(json.dumps(out, indent=1))
    print(f"wrote {DIR / 'expected.json'} ({len(checks)} steps)")


if __name__ == "__main__":
    main()
