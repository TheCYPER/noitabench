"""Degenerate plays and damaged files.

A score must not be earned by doing nothing (standing at a door, dying at once, wandering back
later) and a damaged recording must not stop the evaluation. The geometry is that of the real
scene definitions.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from eval_runs import box, command, damage, lab_marker, walk, write_run
from noitabench.eval import evaluate_run, write_profile
from noitabench.eval.context import Ctx, find_visits
from noitabench.eval.encounters import evaluate_visits, implemented
from noitabench.eval.recording import load_run

SCORED_ENCOUNTERS = [e for e in implemented() if e != "E04"]  # E04 waits for a lava river
# optional scenes whose question is put only further in (the river of E05, the bench of E21,
# the second room of E24): a touch of their door is not scored at all
POSED_INSIDE = {"E05", "E21", "E24"}


def at_the_door(eid: str, kind: str, must_pass: bool, tmp: Path):
    """The visit results of a player who only touches the top of the scene: `graze` goes in and
    out, `stand` stays 600 frames, `die` is shot dead there."""
    m = lab_marker(eid, 0, dx=300, dy=300)
    m["must_pass"] = must_pass
    fp = m["footprint"]
    x, top = fp["x"] + 10, fp["y"] - 13  # the hit box overlaps the footprint by three rows
    path = {
        "graze": [(0, x, top - 30), (60, x, top), (120, x, top), (200, x, top - 30)],
        "stand": [(0, x, top - 30), (60, x, top), (700, x, top)],
        "die": [(0, x, top - 30), (60, x, top), (120, x, top)],
    }[kind]
    events, hp = [], {0: 100.0}
    if kind == "die":
        events = [damage(70, 100, "melee", 0.0)]
        events.append({"frame": 80, "type": "death", "target": "player", "source": "melee"})
        hp = {0: 100.0, 75: 0.0}
    run = load_run(write_run(tmp, markers=[m], track=walk(path), events=events, hp=hp))
    return evaluate_visits(run)


@pytest.mark.parametrize("kind", ["graze", "stand", "die"])
@pytest.mark.parametrize("must_pass", [True, False])
@pytest.mark.parametrize("eid", SCORED_ENCOUNTERS)
def test_touching_the_door_of_a_scene_scores_nothing(tmp_path, eid, must_pass, kind):
    """No part of a rule may reward the absence of harm to a player who did nothing."""
    (result,) = at_the_door(eid, kind, must_pass, tmp_path / "run")
    if eid in POSED_INSIDE:
        assert result.outcome.score is None, result.outcome.reasons
        assert result.outcome.reasons[0].startswith("not scored: ")
    else:
        assert result.outcome.score == pytest.approx(0.0), result.outcome.reasons


def e16_flight(tmp: Path, *, dip: bool):
    m = lab_marker("E16")
    trough = box(m, "trough")
    y = trough.y - 16 - (0 if not dip else -6)  # feet just above the trough, or 6 cells in
    track = walk([(0, trough.x - 10, y - 20), (100, trough.x - 8, y), (300, trough.right + 8, y)])
    run = load_run(write_run(tmp, markers=[m], track=track))
    return evaluate_visits(run)[0]


def test_flying_over_the_acid_trough_is_going_at_it(tmp_path):
    """Levitating across is one of the solutions: unhurt counts without touching the trough."""
    flown = e16_flight(tmp_path / "a", dip=False)
    assert any("lost 0 HP to contact" in why and "+0.71" in why for why in flown.outcome.reasons)
    assert flown.outcome.score == pytest.approx(0.5 / 0.7)


def e16_with_inspect(tmp: Path, frame: int):
    m = lab_marker("E16")
    trough = box(m, "trough")
    y = trough.y - 16
    track = walk([(0, trough.x - 10, y - 20), (100, trough.x - 8, y), (300, trough.right + 8, y)])
    look = command(frame, "inspect", x=trough.x + 5, y=trough.y + 1)
    run = load_run(write_run(tmp, markers=[m], track=track, decisions=[look]))
    return evaluate_visits(run)[0]


def test_an_inspect_of_the_trough_after_flying_over_it_is_too_late(tmp_path):
    early = e16_with_inspect(tmp_path / "a", frame=50)
    late = e16_with_inspect(tmp_path / "b", frame=250)
    assert early.outcome.score == pytest.approx(0.8)  # inspected 0.3 + unhurt 0.5, not out below
    assert late.outcome.score == pytest.approx(0.5)  # the look came after the flight


def test_health_lost_between_two_visits_is_not_charged_to_the_scene(tmp_path):
    m = lab_marker("E08", 0, dx=300, dy=300)
    fp = m["footprint"]
    x, y = fp["x"] + 10, fp["y"] + 2
    away = (x + 400, fp["y"] - 300)
    track = walk([(0, x, y - 30), (60, x, y), (200, x, y), (300, *away), (900, *away),
                  (1000, x, y - 30), (1060, x, y), (1200, x, y)])  # fmt: skip
    events = [damage(600, 40, "contact"), damage(1100, 10, "contact")]
    run = load_run(write_run(tmp_path / "run", markers=[m], track=track, events=events))
    (visit,) = find_visits(run)
    assert len(visit.segments) == 2
    ctx = Ctx(run, visit)
    assert ctx.hp_lost() == pytest.approx(10.0)  # the 40 were lost somewhere else
    assert ctx.hp_lost(f0=0, f1=run.last_frame) == pytest.approx(50.0)
    assert [e["frame"] for e in ctx.events("damage")] == [1100]


def test_being_deeper_in_the_same_column_later_is_not_passing_the_scene(tmp_path):
    m = lab_marker("E12", 0, dx=300, dy=300)
    m["must_pass"] = False
    fp = m["footprint"]
    x, top = fp["x"] + 10, fp["y"] - 13
    far = x + 500
    track = walk([(0, x, top - 30), (60, x, top), (120, x, top), (200, far, top - 100),
                  (800, far, fp["y"] + fp["h"] + 100), (1400, x, fp["y"] + fp["h"] + 100)])  # fmt: skip
    run = load_run(write_run(tmp_path / "run", markers=[m], track=track))
    (visit,) = find_visits(run)
    assert not Ctx(run, visit).passed_below()


def test_getting_out_through_the_lower_corner_is_passing_the_scene(tmp_path):
    m = lab_marker("E12", 0, dx=300, dy=300)
    fp = m["footprint"]
    left, bottom = fp["x"] - 15, fp["y"] + fp["h"]  # dug out beside the doorway, 15 cells off
    track = walk([(0, fp["x"] + 10, fp["y"] - 20), (100, fp["x"] + 10, fp["y"] + 4),
                  (200, fp["x"] + 10, bottom - 30), (260, left, bottom + 2),
                  (320, left, bottom + 40)])  # fmt: skip
    run = load_run(write_run(tmp_path / "run", markers=[m], track=track))
    (visit,) = find_visits(run)
    assert Ctx(run, visit).passed_below()


# ------------------------------------------------------------------------------- the composite
def test_a_short_perfect_play_is_flagged_as_a_thin_composite(tmp_path):
    """A perfect first scene is discounted by its few opportunities (n / (n + 2)) and the note
    says that the composite rests on few capabilities."""
    from noitabench.eval.scoring import capability_scores, composite

    caps = capability_scores([], [])
    assert composite(caps, {"score": 10.0})["note"].startswith("no capability")
    from noitabench.eval.metrics import Metric

    one = capability_scores([], [Metric("repeat_harm", ("N1",), 1.0, 3)])
    out = composite(one, {"score": 20.0})
    assert out["composite"] == pytest.approx(0.8 * (100 * 3 / 5) / 11 + 0.2 * 20, abs=0.01)
    assert out["note"].startswith("thin: only 1 of 11")
    five = capability_scores(
        [],
        [
            Metric("a", (f"N{i}",), 1.0, 2)
            for i in range(1, 6)  # five covered capabilities
        ],
    )
    assert composite(five, {"score": 0.0})["note"] is None


# ------------------------------------------------------------------------------ damaged files
def damaged_run(tmp: Path) -> Path:
    m = lab_marker("E16")
    trough = box(m, "trough")
    track = walk([(0, trough.x - 10, trough.y - 14), (200, trough.right + 6, trough.y - 14)])
    transcript = [{"kind": "assistant", "text": "go right", "thinking": ""}]
    return write_run(
        tmp, markers=[m], track=track, decisions=[], transcript=transcript, summary={"model": {}}
    )


def cut_frames(folder: Path) -> None:
    from noitabench.eval.frames import HEADER

    payload = b"x" * 40
    record = HEADER.pack(5, 0, 0, 768, 1664, 1, 400) + payload  # promises 400 bytes, has 40
    (folder / "frames.bin").write_bytes(record)


DAMAGE: dict[str, Callable[[Path], None]] = {
    "frames.bin cut inside a record": cut_frames,
    "summary.json is not JSON": lambda d: (d / "summary.json").write_text("{nope"),
    "summary.json is a list": lambda d: (d / "summary.json").write_text("[1, 2]"),
    "summary.json parts are not objects": lambda d: (d / "summary.json").write_text(
        json.dumps({"model": 3, "result": "x"})
    ),
    "decisions with null fields": lambda d: (d / "decisions.jsonl").write_text(
        '{"frame": null, "command": 3, "cost": "x"}\n{"frame": "a"}\n'
    ),
    "transcript with odd rows": lambda d: (d / "transcript.jsonl").write_text(
        '[1]\n{"kind": "assistant", "tool_calls": [1, null, {"arguments": 5}], "text": 5}\n'
    ),
    "events without a frame": lambda d: (d / "events.jsonl").write_text(
        '{"type": "damage"}\n{"frame": null, "type": "damage"}\n{"frame": 5, "type": "damage"}\n'
    ),
    "a damage event without an amount": lambda d: (d / "events.jsonl").write_text(
        '{"frame": 20, "type": "damage", "target": "player", "source": "contact"}\n'
    ),
    "entity rows of the wrong shape": lambda d: (d / "entities.jsonl").write_text(
        (d / "entities.jsonl").read_text()
        + '{"frame": 9999, "entities": [5, {"kind": "player"}]}\n'
    ),
}


@pytest.mark.parametrize("what", sorted(DAMAGE))
def test_a_damaged_file_is_read_as_far_as_it_goes(tmp_path, what):
    folder = damaged_run(tmp_path / "run")
    DAMAGE[what](folder)
    profile = evaluate_run(folder)
    assert profile["format"] == "cogbench-profile/0"
    assert 0 <= profile["composite"] <= 100


def test_a_damaged_meta_names_the_file(tmp_path):
    folder = damaged_run(tmp_path / "run")
    (folder / "meta.json").write_text("{nope")
    with pytest.raises(ValueError, match="meta.json"):
        load_run(folder)


def test_a_world_file_without_sizes_names_the_file(tmp_path):
    folder = damaged_run(tmp_path / "run")
    world = folder / "world" / "world.json"
    doc = json.loads(world.read_text())
    del doc["width"]
    world.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="world.json: not a usable world file"):
        load_run(folder)


def test_a_damaged_event_row_marks_the_visit_unscored_instead_of_stopping(tmp_path):
    folder = damaged_run(tmp_path / "run")
    events = [{"frame": 20, "type": "shatter"}, {"frame": 30, "type": "throw", "material": "water"}]
    (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    profile = evaluate_run(folder)
    e16 = next(e for e in profile["encounters"] if e["id"] == "E16")["visits"][0]
    assert e16["scored"]  # the E16 rule reads no throw: the damaged rows cost it nothing
    assert 0 <= profile["composite"] <= 100


def test_a_rule_that_cannot_read_a_row_reports_the_visit_unscored(tmp_path):
    m = lab_marker("E07")
    lava = box(m, "lava")
    track = walk([(0, lava.x - 20, lava.y - 20), (200, lava.x - 6, lava.y - 16)])
    events = [
        {"frame": 40, "type": "fill", "cells": 50},
        {"frame": 50, "type": "damage", "target": "player", "source": "contact"},
    ]  # the damage has no amount: tolerated
    events.append({"frame": 60, "type": "reaction", "id": "r01"})  # no position: not readable
    run = load_run(write_run(tmp_path / "run", markers=[m], track=track, events=events))
    (result,) = evaluate_visits(run)
    assert result.outcome.score is None
    assert "damaged recording data" in result.outcome.reasons[0]


# ------------------------------------------------------------------------------ determinism
def test_the_same_folder_gives_the_same_bytes_wherever_it_lies(tmp_path):
    folder = damaged_run(tmp_path / "a" / "run")
    other = tmp_path / "elsewhere" / "run"
    shutil.copytree(folder, other)
    first = write_profile(evaluate_run(folder), tmp_path / "p1.json").read_bytes()
    again = write_profile(evaluate_run(folder), tmp_path / "p2.json").read_bytes()
    copy = write_profile(evaluate_run(other), tmp_path / "p3.json").read_bytes()
    assert first == again == copy


def test_a_profile_is_never_written_into_a_workspace_folder(tmp_path):
    profile = evaluate_run(damaged_run(tmp_path / "run"))
    for name in ("workspace", "workspace_start", "workspaces"):
        with pytest.raises(ValueError, match="workspace folder"):
            write_profile(profile, tmp_path / name / "family" / "profile.json")
        assert not (tmp_path / name).exists()
    assert write_profile(profile, tmp_path / "workspace-notes" / "p.json").exists()


def test_a_world_file_of_another_seed_is_named_in_the_notes(tmp_path):
    folder = damaged_run(tmp_path / "run")
    world = folder / "world" / "world.json"
    doc = json.loads(world.read_text())
    doc["seed"] = 99  # the recording says seed 1
    world.write_text(json.dumps(doc))
    notes = evaluate_run(folder)["evaluator"]["notes"]
    assert any("seed 99" in n and "seed 1" in n for n in notes)
    assert not any(
        "seed" in n for n in evaluate_run(damaged_run(tmp_path / "ok"))["evaluator"]["notes"]
    )
