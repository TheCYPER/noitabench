"""Writes web/tests/fixtures/play_state.json: a real answer of the play server, small.

    .venv/bin/python web/tests/make_play_fixture.py

It generates the world of seed 3, plays one decision through `PlayApp` (the same code the page
talks to), sets a few wood cells alight and an enemy standing in view, and saves the JSON the
server returns for /api/decide, together with `expected`: the values the page must decode,
worked out here straight from the game (not from the encoded view). The window is shrunk to
64 x 144 cells (it hangs over the top of the world, so there are cells outside) so the
file stays small.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

import numpy as np
from noitabench.play.cli import _parser, build_app

OUT = REPO / "web" / "tests" / "fixtures" / "play_state.json"
HEADERS = {"host": "127.0.0.1:8765", "content-type": "application/json"}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        args = _parser().parse_args(
            [
                "serve",
                "--world-seed",
                "3",
                "--no-record",
                "--ascii",  # the legend the view's `legend` must agree with is in the answer
                "--workspace-root",
                str(Path(tmp) / "w"),
            ]
        )
        app = build_app(args, None)
        try:
            app.view_half = (32, 72)
            p = app.session.engine.player()
            px, py = p["x"] + p["w"] // 2, p["y"] + p["h"] - 1
            app.game.fill_rect(px + 6, py, 6, 1, "wood")
            app.game.ignite(px + 7, py)
            app.game.ignite(px + 10, py)
            app.game.spawn_enemy("longleg", px - 14, py)
            app.game.step(2)
            body = json.dumps({"text": f"inspect(x={px + 7}, y={py})"}).encode()
            res = app.handle("POST", "/api/decide", HEADERS, body)
            assert res.status == 200, res.body
            doc = res.json()
            view = doc["view"]
            ox, oy = view["origin"]["x"], view["origin"]["y"]
            w, h = view["width"], view["height"]
            fire = np.frombuffer(app.game.burning_rect(ox, oy, w, h), dtype=np.uint8)
            cells = [[ox + int(i % w), oy + int(i // w)] for i in np.flatnonzero(fire)]
            grid = np.frombuffer(app.game.grid(), dtype=np.uint8).reshape(
                app.game.height, app.game.width
            )
            probes = [[px, py + 2], [px, py - 10], [px + 7, py]]
            rows = json.loads((REPO / "content" / "materials.json").read_text())["materials"]
            ascii_names = set(doc["answer"]["observation"]["map"]["legend"].values())
            expected = {
                # the pairs {index, name} the page may show: the materials the ASCII legend names
                "legend": [
                    {"index": m["index"], "name": m["name_zh"]}
                    for m in rows
                    if m["key"] in ascii_names
                ],
                "burning_cells": cells,
                "probes": [{"x": x, "y": y, "material": int(grid[y, x])} for x, y in probes],
                "outside_cells": int(
                    (
                        np.frombuffer(base64.b64decode(view["materials"]), dtype=np.uint8)
                        == view["outside"]
                    ).sum()
                ),
            }
            OUT.write_text(
                json.dumps({"response": doc, "expected": expected}, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            print(f"wrote {OUT} ({OUT.stat().st_size} bytes), {len(cells)} burning cells")
        finally:
            app.close()


if __name__ == "__main__":
    main()
