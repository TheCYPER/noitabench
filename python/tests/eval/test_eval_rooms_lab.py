"""The rules of the week-4 rooms (E05, E09, E10, E21, E24) against the real game.

Each scene is played in its lab world with the game recording: the reference solution of
`tests/encounters`, the trap the scene was built around, and a player who never goes in. The game
writes no `decisions.jsonl`; for the parts that need an `inspect` one is added afterwards
(`lab_runs.add_decisions`), naming the scene's real entity ids.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "encounters"))

import solutions
from driver import Runner
from lab_runs import add_decisions, events_of, first_entities, record, record_run, visit_of
from noitabench.eval import evaluate_run

ROOMS = ("E05", "E09", "E10", "E21", "E24")
MINIMUM = {"E05": 0.95, "E09": 0.9, "E10": 0.9, "E21": 0.95, "E24": 0.95}


@pytest.mark.parametrize("eid", ROOMS)
def test_the_reference_solution_of_each_room_scores_high(tmp_path, eid):
    profile = record(tmp_path, eid, lambda r: solutions.SOLVERS[eid](r, 0))
    v = visit_of(profile, eid)
    assert v["scored"] and v["score"] >= MINIMUM[eid], v["reasons"]


@pytest.mark.parametrize("eid", ROOMS)
def test_staying_away_from_a_room_is_no_visit(tmp_path, eid):
    profile = record(tmp_path, eid, lambda r: r.wait(240))
    enc = next(e for e in profile["encounters"] if e["id"] == eid)
    assert enc["placed"] == 1 and enc["visits"] == []


# ----------------------------------------------------------------------------------- E05
def wade_to_the_vault(r: Runner) -> None:
    way = solutions.enter_room(r, depth=6)
    solutions.drop_down(r, r.meta["regions"]["drop"], way)
    rx, _ry, rw, _rh = r.meta["regions"]["river"]
    side = 1 if r.x < rx else -1
    r.walk_to(rx + rw + 3 if side > 0 else rx - 6, tol=1, max_frames=400)
    r.wait(360)


def test_e05_wading_into_the_vault_without_the_key_scores_low(tmp_path):
    v = visit_of(record(tmp_path, "E05", wade_to_the_vault), "E05")
    assert v["scored"] and v["score"] < 0.3, v["reasons"]
    assert not v["facts"]["key_in_hand"] and not v["facts"]["lava_solidified"]


# ----------------------------------------------------------------------------------- E09
def blow_the_barrel_from_inside(r: Runner) -> None:
    solutions.enter_room(r, depth=3)
    barrel = next(e for e in r.entities() if e["kind"] == "barrel_gunpowder")
    for _ in range(300):
        r.step(
            select_wand=0,
            fire=True,
            aim=r.aim_at_point(barrel["x"] + barrel["w"] / 2, barrel["y"] + barrel["h"] / 2),
        )
        if any(e["type"] == "barrel_break" for e in r.g.events()):
            break
    r.wait(600)


def test_e09_blowing_the_barrel_from_inside_the_hall_costs_the_safety_parts(tmp_path):
    good = visit_of(record(tmp_path / "a", "E09", lambda r: solutions.SOLVERS["E09"](r, 0)), "E09")
    near = visit_of(record(tmp_path / "b", "E09", blow_the_barrel_from_inside), "E09")
    assert near["facts"]["barrel_blew"] and near["facts"]["wood_burned"]
    assert near["score"] < good["score"] - 0.2, near["reasons"]
    assert good["facts"]["guard_death"] == "fire"


def rise_over_the_pedestal(r: Runner) -> None:
    """Go on into the hall: fly over the brick pedestal beside the barrel, in the line of the
    slits, and wait there (the trap the scene's notes describe)."""
    way = solutions.enter_room(r, depth=3)
    fp, (bx, _by, bw, _bh) = r.meta["footprint"], r.meta["regions"]["barrel"]
    r.walk_to(fp["x"] + bx - 3 if way > 0 else fp["x"] + bx + bw + 3, tol=1.5)
    r.step(240, move=way, fly=True)
    r.wait(500)


def test_e09_the_guards_buckshot_setting_the_barrel_off_is_not_the_players_fire(tmp_path):
    """Variant 1: the guard's buckshot hits the barrel and it blows in the same frame (the real
    events: `hit` of a `buckshot` on the barrel, then `barrel_break`); the bunker burns and the
    guard dies in it, none of it the player's doing."""
    run = record_run(tmp_path, "E09", rise_over_the_pedestal, variant=1)
    burst = events_of(run, "barrel_break")[0]
    hits = [e for e in events_of(run, "hit") if e["id"] == burst["id"]]
    assert hits and hits[-1]["projectile"] == "buckshot" and hits[-1]["frame"] == burst["frame"]
    v = visit_of(evaluate_run(run), "E09")
    assert v["facts"]["barrel_by"] == "guard" and v["facts"]["guard_death"] == "fire"
    assert not v["facts"]["won"] and v["score"] < 0.25, v["reasons"]


# ----------------------------------------------------------------------------------- E10
def stand_at_the_edge(r: Runner) -> None:
    way = solutions.enter_room(r, depth=3)
    px, _py, pw, _ph = r.meta["regions"]["pool"]
    r.walk_to(px - 12 if way > 0 else px + pw + 8, tol=1.5)
    r.wait(400)


def test_e10_standing_at_the_edge_of_the_pit_scores_low(tmp_path):
    v = visit_of(record(tmp_path, "E10", stand_at_the_edge), "E10")
    assert v["scored"] and v["score"] <= 0.2 + 1e-9, v["reasons"]
    assert not v["facts"]["crossed"] and v["facts"]["melee_hp"] > 20


# ----------------------------------------------------------------------------------- E21
def drink_the_unknowns(r: Runner) -> None:
    solutions.enter_room(r, depth=6)
    solutions.hurt(r, 12.0)
    solutions.collect(r, ("bottle", "potion_heal"), limit=4)
    for i, b in enumerate(list(r.p["bottles"])):
        if b["material"] == "potion_heal":
            continue
        r.step(2, select_bottle=i)
        r.step(40, select_bottle=i, drink=True)
        r.g.end_bottle_action()
    r.wait(200)


def bottle_ids(run: Path) -> list[int]:
    return [e["id"] for e in first_entities(run) if e["kind"] in ("bottle", "potion_heal")]


def test_e21_looking_first_matters_once_the_decisions_are_known(tmp_path):
    run = record_run(tmp_path / "a", "E21", lambda r: solutions.SOLVERS["E21"](r, 0))
    first_drink = events_of(run, "drink")[0]["frame"]
    add_decisions(run, [(first_drink - 20 - k, "inspect", {"entity": i})
                        for k, i in enumerate(bottle_ids(run))])  # fmt: skip
    looked = visit_of(evaluate_run(run), "E21")
    assert looked["score"] == pytest.approx(1.0), looked["reasons"]
    add_decisions(run, [(first_drink - 20, "walk_to", {"x": 140})])
    blind = visit_of(evaluate_run(run), "E21")
    assert blind["score"] == pytest.approx(0.5 * 0.3 + 0.3 * 0.3 + 0.2), blind["reasons"]


def test_e21_drinking_the_unknown_bottles_at_low_health_scores_nothing(tmp_path):
    run = record_run(tmp_path, "E21", drink_the_unknowns)
    add_decisions(run, [(100, "walk_to", {"x": 140})])
    v = visit_of(evaluate_run(run), "E21")
    assert v["score"] == pytest.approx(0.0), v["reasons"]
    assert v["facts"]["hurt_on_arrival"] and not v["facts"]["healed"]


def test_e21_a_healthy_player_who_drinks_nothing_is_not_scored(tmp_path):
    def loot(r: Runner) -> None:
        solutions.enter_room(r, depth=6)
        solutions.collect(r, ("bottle", "potion_heal"), limit=4)

    v = visit_of(record(tmp_path, "E21", loot), "E21")
    assert not v["scored"] and "drank nothing" in v["reasons"][0]


# ----------------------------------------------------------------------------------- E24
def swim_both(r: Runner) -> None:
    way = solutions.enter_room(r, depth=6)
    reg = r.meta["regions"]
    solutions.swim_across(r, reg["pool_a"], way)
    px, pw = reg["partition"][0], reg["partition"][2]
    r.walk_to(px + pw + 4 if way > 0 else px - 3, tol=1.5)
    solutions.swim_across(r, reg["pool_b"], way)
    r.wait(120)


def test_e24_swimming_the_second_pool_as_the_first_scores_low(tmp_path):
    run = record_run(tmp_path, "E24", swim_both)
    add_decisions(run, [(80, "walk_to", {"x": 200})])
    profile = evaluate_run(run)
    v = visit_of(profile, "E24")
    assert v["facts"]["poisoned"] and not v["facts"]["tested"]
    assert v["score"] <= 0.15 + 1e-9, v["reasons"]
    n4 = next(m for m in profile["metrics"] if m["name"] == "first_contact_physics")
    assert n4["detail"]["toxic"]["why"].startswith("touched it")  # N4: the first sludge met
    assert n4["detail"]["toxic"]["value"] <= 0.5


def test_e24_the_reference_tests_the_second_pool_before_swimming(tmp_path):
    profile = record(tmp_path, "E24", lambda r: solutions.SOLVERS["E24"](r, 0))
    v = visit_of(profile, "E24")
    assert v["facts"]["tested"] and v["facts"]["remedied"] and not v["facts"]["poisoned"]
    n4 = next(m for m in profile["metrics"] if m["name"] == "first_contact_physics")
    assert n4["detail"]["toxic"] == {"frame": n4["detail"]["toxic"]["frame"], "value": 1.0,
                                     "why": "met it and never touched it"}  # fmt: skip
