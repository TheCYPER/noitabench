"""Recorded plays of one scene in its lab world, for testing the scoring rules on the real game.

The lab world (`worldgen.scene_world`) holds one scene; the recording is written by the game
itself (`Game.start_recording`), so the events and the track are the real ones. A play reads only
the game state (the reference solutions come from `tests/encounters`). The game writes no
`decisions.jsonl`: `add_decisions` adds one afterwards for the parts that need an `inspect`.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "encounters"))

from driver import SETTLE, Runner, start
from noitabench.eval import evaluate_run

STRIDE = 12


def record_run(tmp: Path, eid: str, play: Callable[[Runner], None], variant: int = 0) -> Path:
    """Play `play` in the lab world of `eid` with the game recording; return the run folder."""
    r = start(eid, variant, 0, tmp=tmp / "world", settle=False)
    run = tmp / "run"
    r.g.start_recording(run, STRIDE, run_id=f"{eid}-lab", notes="lab test")
    r.wait(SETTLE)
    play(r)
    r.wait(30)
    r.g.stop_recording()
    shutil.copytree(tmp / "world", run / "world")
    return run


def record(tmp: Path, eid: str, play: Callable[[Runner], None], variant: int = 0) -> dict:
    """Play `play` in the lab world of `eid` with the game recording; return the profile."""
    return evaluate_run(record_run(tmp, eid, play, variant))


def visit_of(profile: dict, eid: str) -> dict:
    enc = next(e for e in profile["encounters"] if e["id"] == eid)
    assert len(enc["visits"]) == 1, f"{eid}: visits {enc['visits']}"
    return enc["visits"][0]


def events_of(run: Path, *types: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines() if line]
    return [e for e in rows if not types or e["type"] in types]


def first_entities(run: Path) -> list[dict[str, Any]]:
    """The entities of the first recorded frame."""
    first = (run / "entities.jsonl").read_text().splitlines()[0]
    return json.loads(first)["entities"]


def add_decisions(run: Path, commands: Iterable[tuple[int, str, dict[str, Any]]]) -> None:
    """Write `decisions.jsonl` with one one-command decision per `(frame, name, args)` (each costs
    one decision, as a lone command does in the agent layer)."""
    rows = []
    index = 0
    for frame, name, args in commands:
        cost = 1
        index += cost
        rows.append(
            {
                "frame": frame,
                "index": index,
                "cost": cost,
                "stop_reason": "completed",
                "command": [{"name": name, "args": args}],
                "observation_digest": "0" * 16,
                "ok": True,
            }
        )
    (run / "decisions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
