"""The scoring rules against the real game: the reference solutions of the encounters, played in
their lab worlds and recorded, and a few deliberately bad plays.

The lab world (`worldgen.scene_world`) holds one scene; the recording is written by the game
itself (`Game.start_recording`), so the events and the track are the real ones. The reference
solutions come from `tests/encounters` and read only the game state.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "encounters"))

import solutions
from driver import Runner
from lab_runs import record, visit_of

MINIMUM = {  # what the reference solution of each scene must at least score
    "E02": 0.9,
    "E03": 0.9,
    "E07": 0.9,
    "E08": 0.95,
    "E12": 0.95,
    "E14": 0.9,
    "E16": 0.95,
    "E18": 0.65,
    "E22": 0.95,
    "E23": 0.85,
}


@pytest.mark.parametrize("eid", sorted(MINIMUM))
def test_the_reference_solution_scores_high(tmp_path, eid):
    profile = record(tmp_path, eid, lambda r: solutions.SOLVERS[eid](r, 0))
    v = visit_of(profile, eid)
    assert v["scored"] and v["score"] >= MINIMUM[eid], v["reasons"]


def test_the_reference_solution_of_e04_is_not_scored_without_a_lava_river_after_it(tmp_path):
    profile = record(tmp_path, "E04", lambda r: solutions.SOLVERS["E04"](r, 0))
    v = visit_of(profile, "E04")
    assert not v["scored"] and v["score"] is None


def test_the_seal_key_is_assembled_blasted_and_the_plug_opened(tmp_path):
    """E06 in the lab: the spells are handed over (no pickup events), the key is built and thrown."""
    profile = record(tmp_path, "E06", lambda r: solutions.SOLVERS["E06"](r, 0))
    v = visit_of(profile, "E06")
    assert v["facts"]["opened"] and v["facts"]["key_blast"]
    assert v["facts"]["parts_before"] == 0  # given, not picked up: the climb part says so
    key = next(m for m in profile["metrics"] if m["name"] == "key_assembly")
    assert key["status"] == "not_measured"  # the key was never "found" in this recording


def test_wading_through_the_acid_scores_far_below_the_hop(tmp_path):
    def wade(r: Runner) -> None:
        solutions.enter(r)
        tx, _ty, tw, _th = r.meta["regions"]["trough"]
        side = 1 if r.x < tx else -1
        r.walk_to(tx + tw + 4 if side > 0 else tx - 4, tol=2, max_frames=900)
        r.wait(60)

    bad = visit_of(record(tmp_path / "a", "E16", wade), "E16")
    good = visit_of(record(tmp_path / "b", "E16", lambda r: solutions.SOLVERS["E16"](r, 0)), "E16")
    assert bad["score"] < 0.5 < good["score"]
    assert bad["facts"]["contact_hp"] > 20


def test_swimming_the_pool_without_trying_the_vial_scores_half(tmp_path):
    def swim(r: Runner) -> None:
        solutions.enter(r)
        pool = r.meta["regions"]["pool"]
        side = 1 if r.x < pool[0] else -1
        solutions.swim_across(r, pool, side)
        solutions.leave(r)

    v = visit_of(record(tmp_path, "E23", swim), "E23")
    assert not v["facts"]["tested_first"]
    assert v["score"] <= 0.5 + 1e-9, v["reasons"]


def test_walking_into_the_lava_scores_below_the_crust(tmp_path):
    def wade(r: Runner) -> None:
        solutions.enter(r)
        rx, _ry, rw, _rh = r.meta["regions"]["river"]
        side = 1 if r.x < rx else -1
        r.walk_to(rx + rw + 4 if side > 0 else rx - 4, tol=2, max_frames=900)

    bad = visit_of(record(tmp_path, "E02", wade), "E02")
    assert bad["score"] < 0.5, bad["reasons"]
    assert not bad["facts"]["lava_solidified"]


def first_contacts(profile: dict) -> dict:
    return next(m for m in profile["metrics"] if m["name"] == "first_contact_physics")["detail"]


def wade_through(region: str):
    def play(r: Runner) -> None:
        solutions.enter(r)
        x, _y, w, _h = r.meta["regions"][region]
        side = 1 if r.x < x else -1
        r.walk_to(x + w + 4 if side > 0 else x - 4, tol=2, max_frames=900)
        r.wait(60)

    return play


@pytest.mark.parametrize("variant", [0, 1])
def test_walking_into_the_first_lava_or_acid_met_scores_below_keeping_clear(tmp_path, variant):
    """The careless control of N4: a player that walks straight into the first lava river (E02)
    or acid trough (E16) it meets is judged touched (at most 0.5); the reference solutions that
    dig past the lava seams (E12) and hop over the acid (E16) met them and kept clear (1.0)."""
    lava = first_contacts(record(tmp_path / "a", "E02", wade_through("river"), variant))["lava"]
    acid = first_contacts(record(tmp_path / "b", "E16", wade_through("trough"), variant))["acid"]
    assert lava["why"].startswith("touched it") and lava["value"] < 0.4
    assert acid["why"].startswith("touched it") and acid["value"] < 0.4
    seams = record(tmp_path / "c", "E12", lambda r: solutions.SOLVERS["E12"](r, 0), variant)
    hop = record(tmp_path / "d", "E16", lambda r: solutions.SOLVERS["E16"](r, 0), variant)
    assert first_contacts(seams)["lava"]["value"] == 1.0
    assert first_contacts(hop)["acid"]["value"] == 1.0
