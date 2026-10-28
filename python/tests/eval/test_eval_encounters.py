"""The scoring rule of each implemented encounter, on hand-made recordings.

Each test says what the player did in a few waypoints and events and checks the score and the
reasons. The geometry (footprint, regions) is that of the real scene definitions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval_runs import box, command, damage, lab_marker, walk, write_run
from noitabench.eval.encounters import Result, evaluate_visits, implemented
from noitabench.eval.geometry import Rect
from noitabench.eval.recording import load_run

LAVA_ROW = "r01"  # lava + water -> rock: a lava cell becomes rock


def evaluate(tmp: Path, markers, track, **kw) -> dict[str, Result]:
    """Write the run, evaluate it, return the results by encounter id (one each)."""
    run = load_run(write_run(tmp / "run", markers=markers, track=track, **kw))
    out: dict[str, Result] = {}
    for r in evaluate_visits(run):
        out.setdefault(r.visit.scene.eid, r)
    return out


def pour(frame: int, material: str, cells: int = 80) -> dict:
    return {"frame": frame, "type": "pour", "material": material, "cells": cells}


def crust(frame: int, region: Rect, n: int = 5) -> list[dict]:
    return [
        {
            "frame": frame + i,
            "type": "reaction",
            "id": LAVA_ROW,
            "x": region.x + i,
            "y": region.y,
            "bx": region.x + i,
            "by": region.y - 1,
        }
        for i in range(n)
    ]


def mid(r: Rect) -> tuple[float, float]:
    return r.x + r.w / 2 - 3, r.y + r.h / 2 - 8


def test_every_implemented_encounter_has_a_rule():
    assert implemented() == [
        "E02", "E03", "E04", "E05", "E06", "E07", "E08", "E09", "E10", "E12", "E14", "E16",
        "E18", "E21", "E22", "E23", "E24",
    ]  # fmt: skip


# ----------------------------------------------------------------------------------- E02
def e02_track(m):
    river, entry, far = box(m, "river"), box(m, "entry"), box(m, "far")
    y = river.y - 16
    return walk([(0, entry.x + 2, y), (200, river.x - 6, y), (500, river.right + 6, y),
                 (560, far.x + 4, far.y)])  # fmt: skip


def test_e02_pouring_the_right_liquid_and_crossing_scores_high(tmp_path):
    m = lab_marker("E02")
    river = box(m, "river")
    events = [pour(150, "blood", 90), *crust(160, river, 12)]
    r = evaluate(tmp_path, [m], e02_track(m), events=events)["E02"]
    assert r.outcome.score == pytest.approx(1.0)
    assert r.outcome.facts["lava_solidified"]


def test_e02_wading_through_the_lava_scores_low(tmp_path):
    m = lab_marker("E02")
    events = [damage(250, 45, "contact"), damage(280, 20, "fire")]
    r = evaluate(tmp_path, [m], e02_track(m), events=events)["E02"]
    assert 0.2 < r.outcome.score < 0.4  # it got across, but no crust and 65 HP gone
    assert not r.outcome.facts["lava_solidified"]


def test_e02_the_decoy_liquid_on_the_river_costs_points(tmp_path):
    m = lab_marker("E02")
    river = box(m, "river")
    clean = evaluate(
        tmp_path / "a", [m], e02_track(m), events=[pour(150, "blood"), *crust(160, river)]
    )
    decoy_events = [pour(120, "whiskey"), pour(150, "blood"), *crust(160, river)]
    decoy = evaluate(tmp_path / "b", [m], e02_track(m), events=decoy_events)
    assert decoy["E02"].outcome.score == pytest.approx(clean["E02"].outcome.score - 0.15)


def test_e02_entering_and_leaving_scores_nothing(tmp_path):
    m = lab_marker("E02")
    entry = box(m, "entry")
    track = walk(
        [(0, entry.x + 2, entry.y), (100, entry.x + 8, entry.y), (200, entry.x + 2, entry.y - 40)]
    )
    r = evaluate(tmp_path, [m], track)["E02"]
    assert r.outcome.score == pytest.approx(0.0)


# ----------------------------------------------------------------------------------- E03
def test_e03_water_wins_and_fireballs_are_wasted_effort(tmp_path):
    m = lab_marker("E03")
    hall = box(m, "hall")
    track = walk([(0, hall.x + 2, hall.y), (400, hall.x + 20, hall.y + 4)])
    fire = [
        {"frame": 40 + 10 * i, "type": "cast", "spells": "FIREBALL", "wand": 0} for i in range(4)
    ]
    throw = [{"frame": 200, "type": "pour", "material": "water", "cells": 90},
             {"frame": 220, "type": "death", "target": "firemage_weak", "id": 9, "source": "hit", "x": 0, "y": 0}]  # fmt: skip
    quick = evaluate(tmp_path / "a", [m], track, events=[throw[0], throw[1]])["E03"]
    slow = evaluate(tmp_path / "b", [m], track, events=[*fire, *throw])["E03"]
    assert quick.outcome.score > 0.95
    assert slow.outcome.score == pytest.approx(
        quick.outcome.score - 0.3 * 0.6
    )  # 4 wasted: 0.4 of 1.0


def test_e03_firing_at_the_mage_and_giving_up_scores_low(tmp_path):
    m = lab_marker("E03")
    hall = box(m, "hall")
    track = walk([(0, hall.x + 2, hall.y), (400, hall.x + 20, hall.y + 4)])
    fire = [
        {"frame": 40 + 10 * i, "type": "cast", "spells": "FIREBALL", "wand": 0} for i in range(8)
    ]
    r = evaluate(tmp_path, [m], track, events=fire)["E03"]
    assert r.outcome.score < 0.15


# ----------------------------------------------------------------------------------- E04
def two_scenes(tmp: Path, *, second: str = "E02", crusted: bool):
    ruin = lab_marker("E04", dx=0, dy=0)
    later = lab_marker(second, dx=0, dy=400)
    bench = box(ruin, "bench")
    river = box(later, "river")
    far = box(later, "far")
    y = river.y - 16
    track = walk([(0, bench.x, bench.y - 20), (200, bench.x + 4, bench.y - 20), (400, river.x - 30, y - 30),
                  (600, river.x - 6, y), (900, river.right + 6, y), (960, far.x + 4, far.y)])  # fmt: skip
    events = [pour(650, "blood"), *crust(660, river, 10)] if crusted else []
    pick = {
        "frame": 100,
        "type": "pickup",
        "item": "bottle",
        "detail": ruin["params"]["A"],
        "id": 5,
    }
    return evaluate(tmp, [ruin, later], track, events=[pick, *events])


def test_e04_is_judged_on_the_lava_met_later(tmp_path):
    used = two_scenes(tmp_path / "a", crusted=True)["E04"].outcome
    unused = two_scenes(tmp_path / "b", crusted=False)["E04"].outcome
    assert used.score == pytest.approx(1.0)
    assert unused.score == pytest.approx(0.3)  # it took the bottle, but never used the lesson
    assert used.facts == {"later": 1, "used": 1}


def test_e04_is_not_scored_when_no_lava_comes_later(tmp_path):
    ruin = lab_marker("E04")
    bench = box(ruin, "bench")
    r = evaluate(
        tmp_path, [ruin], walk([(0, bench.x, bench.y - 20), (100, bench.x + 4, bench.y - 20)])
    )["E04"]
    assert r.outcome.score is None
    assert "nothing to apply it to" in r.outcome.reasons[0]


# ----------------------------------------------------------------------------------- E06
def e06_setup(
    tmp: Path, *, picks: list[tuple[int, str]], blast: bool, drop: bool, climb: bool = False
):
    m = lab_marker("E06", dy=1400)
    front, plug = box(m, "front"), box(m, "plug")
    seal = {"x": plug.x, "y": plug.y, "w": plug.w, "h": plug.h,
            "room": {"x": plug.x - 20, "y": plug.bottom, "w": plug.w + 40, "h": 50}}  # fmt: skip
    hall_y = front.y + 4
    points = [(0, front.x + 4, hall_y - 200), (300, front.x + 6, hall_y)]
    if climb:
        points += [(500, front.x + 6, hall_y - 150), (700, front.x + 6, hall_y)]
    points.append((800, front.x + 6, hall_y))
    if drop:
        points.append((900, plug.x + 6, plug.bottom + 20))
    events = [
        {"frame": f, "type": "pickup", "item": "spell", "detail": s, "id": 7} for f, s in picks
    ]
    if blast:
        events.append({"frame": 780, "type": "explosion", "x": plug.cx, "y": plug.cy, "radius": 75})
    items = [
        {"type": "item", "item": "spell", "spell": "BOMB", "role": "breaker", "x": 1, "y": 1},
        {
            "type": "item",
            "item": "spell",
            "spell": "EXPLOSIVE_PROJECTILE",
            "role": "breaker",
            "x": 2,
            "y": 1,
        },
    ]
    return evaluate(tmp, [m, *items], walk(points), events=events, seal=seal)["E06"].outcome


def test_e06_full_marks_for_the_key_in_hand_and_the_seal_open(tmp_path):
    out = e06_setup(
        tmp_path, picks=[(5, "BOMB"), (6, "EXPLOSIVE_PROJECTILE")], blast=True, drop=True
    )
    assert out.score == pytest.approx(1.0)
    assert out.facts["key_blast"] and out.facts["opened"]


def test_e06_fetching_a_part_after_arriving_costs_the_climb(tmp_path):
    out = e06_setup(
        tmp_path,
        picks=[(5, "BOMB"), (600, "EXPLOSIVE_PROJECTILE")],
        blast=True,
        drop=True,
        climb=True,
    )
    assert out.facts["parts_before"] == 1 and out.facts["parts_late"] == 1
    assert out.facts["climbed"] == pytest.approx(131, abs=6)  # up 150 from the hall floor
    # 0.4 * 0.5 + 0.2 * (1 - 131/300) + 0.4
    assert out.score == pytest.approx(0.2 + 0.2 * (1 - 131 / 300) + 0.4, abs=0.03)


def test_e06_a_blast_without_getting_in_is_half_credit(tmp_path):
    out = e06_setup(
        tmp_path, picks=[(5, "BOMB"), (6, "EXPLOSIVE_PROJECTILE")], blast=True, drop=False
    )
    assert out.score == pytest.approx(0.4 + 0.2 + 0.2)


def test_e06_a_part_never_found_leaves_the_seal_shut(tmp_path):
    out = e06_setup(tmp_path, picks=[(5, "BOMB")], blast=False, drop=False)
    assert out.score == pytest.approx(0.2)
    assert any("never fetched" in r for r in out.reasons)


# ----------------------------------------------------------------------------------- E07
def e07_track(m, *, cross: bool):
    pool, acid, lava = box(m, "pool"), box(m, "acid"), box(m, "lava")
    fp = Rect.parse(m["footprint"])
    y = acid.y - 16
    pts = [(0, fp.x + 6, y), (100, pool.x + 4, y), (200, acid.x - 6, y)]
    if cross:
        pts += [(400, acid.right + 6, y), (500, lava.x - 6, y), (700, lava.right + 6, y),
                (800, fp.right - 12, fp.bottom + 6)]  # fmt: skip
    return walk(pts)


def test_e07_the_full_chain_scores_high(tmp_path):
    m = lab_marker("E07")
    lava = box(m, "lava")
    events = [
        {"frame": 120, "type": "fill", "material": "blood", "cells": 140},
        *crust(520, lava, 12),
    ]
    r = evaluate(tmp_path, [m], e07_track(m, cross=True), events=events)["E07"]
    assert r.outcome.score == pytest.approx(1.0)
    assert r.outcome.facts["lava_solidified"]


def test_e07_stopping_at_the_acid_scores_little(tmp_path):
    m = lab_marker("E07")
    r = evaluate(tmp_path, [m], e07_track(m, cross=False))["E07"]
    assert r.outcome.score == pytest.approx(0.15)  # nothing hurt it: only the unhurt part
    assert not r.outcome.facts["lava_attempted"]


# ----------------------------------------------------------------------------------- E08
def e08_track(m):
    fp, floor, cellar = Rect.parse(m["footprint"]), box(m, "floor"), box(m, "cellar")
    return walk([(0, fp.x + 6, fp.y), (100, floor.x + 30, floor.y - 16), (200, floor.x + 30, floor.y - 16),
                 (400, floor.x + 30, cellar.y + 2)])  # fmt: skip


def test_e08_digging_the_floor_at_once_scores_high(tmp_path):
    m = lab_marker("E08")
    floor = box(m, "floor")
    dig = [{"frame": 110, "type": "explosion", "x": floor.x + 30, "y": floor.y + 1, "radius": 6}]
    r = evaluate(tmp_path, [m], e08_track(m), events=dig)["E08"]
    assert r.outcome.score > 0.95


def test_e08_never_digging_scores_low(tmp_path):
    m = lab_marker("E08")
    fp, water = Rect.parse(m["footprint"]), box(m, "water")
    track = walk([(0, fp.x + 6, fp.y), (900, water.x + 30, water.y - 4)])
    r = evaluate(tmp_path, [m], track, events=[damage(700, 40, "contact")])["E08"]
    assert r.outcome.score < 0.15


# ----------------------------------------------------------------------------------- E12
def e12_track(m):
    fp = Rect.parse(m["footprint"])
    return walk(
        [(0, fp.x + 6, fp.y), (300, fp.x + 30, fp.y + 20), (600, fp.right - 12, fp.bottom + 8)]
    )


def test_e12_digging_only_the_rock_plugs_scores_high(tmp_path):
    m = lab_marker("E12")
    safe = box(m, "safe1")
    dig = [{"frame": 100, "type": "explosion", "x": safe.x + 4, "y": safe.y + 4, "radius": 6}]
    r = evaluate(tmp_path, [m], e12_track(m), events=dig)["E12"]
    assert r.outcome.score == pytest.approx(1.0)


def test_e12_a_bolt_in_the_ground_plug_and_lava_burns_points(tmp_path):
    m = lab_marker("E12")
    trap = box(m, "trap1")
    events = [{"frame": 100, "type": "explosion", "x": trap.x + 4, "y": trap.y + 4, "radius": 6},
              damage(150, 20, "contact")]  # fmt: skip
    r = evaluate(tmp_path, [m], e12_track(m), events=events)["E12"]
    assert r.outcome.facts["trap_digs"] == 1
    assert r.outcome.score == pytest.approx(0.4 + 0.3 * 0.5 + 0.0)


# ----------------------------------------------------------------------------------- E14
def e14_track(m):
    bottles, river, alcove = box(m, "bottles"), box(m, "river"), box(m, "alcove")
    y = river.y - 16
    return walk(
        [
            (0, bottles.x, y),
            (200, river.x - 6, y),
            (500, river.right + 6, y),
            (560, alcove.x + 2, alcove.y + 10),
        ]
    )


def test_e14_splash_then_the_right_liquid_scores_high(tmp_path):
    m = lab_marker("E14")
    river = box(m, "river")
    events = [pour(80, "oil", 20), pour(120, "blood", 100), *crust(130, river, 8)]
    r = evaluate(tmp_path, [m], e14_track(m), events=events)["E14"]
    assert r.outcome.score > 0.9


def test_e14_a_whole_bottle_of_the_wrong_liquid_wastes_points(tmp_path):
    m = lab_marker("E14")
    river = box(m, "river")
    events = [
        pour(100, "oil", 200),
        pour(150, "whiskey", 150),
        pour(250, "blood", 100),
        *crust(260, river, 8),
    ]
    r = evaluate(tmp_path, [m], e14_track(m), events=events)["E14"]
    assert r.outcome.score < 0.6
    assert any("a lot" in x for x in r.outcome.reasons)


# ----------------------------------------------------------------------------------- E16
def e16_track(m):
    fp, trough = Rect.parse(m["footprint"]), box(m, "trough")
    y = trough.y - 14
    return walk(
        [
            (0, fp.x + 6, y),
            (100, trough.x - 8, y),
            (250, trough.right + 6, y),
            (400, fp.right - 12, fp.bottom + 6),
        ]
    )


def test_e16_an_inspect_first_and_no_harm_scores_full(tmp_path):
    m = lab_marker("E16")
    trough = box(m, "trough")
    decisions = [command(20, "inspect", x=trough.x + 4, y=trough.y + 1)]
    r = evaluate(tmp_path, [m], e16_track(m), decisions=decisions)["E16"]
    assert r.outcome.score == pytest.approx(1.0)


def test_e16_wading_through_acid_without_a_look_scores_low(tmp_path):
    m = lab_marker("E16")
    r = evaluate(
        tmp_path,
        [m],
        e16_track(m),
        events=[damage(150, 62)],
        decisions=[command(20, "walk_to", x=5)],
    )["E16"]
    assert r.outcome.score == pytest.approx(0.2)  # it got through: only the passed part
    assert r.outcome.facts["contact_hp"] == pytest.approx(62)


def test_e16_without_decisions_the_inspect_part_is_left_out(tmp_path):
    m = lab_marker("E16")
    r = evaluate(tmp_path, [m], e16_track(m))["E16"]
    assert r.outcome.score == pytest.approx(1.0)
    assert any("inspected: not measured" in x for x in r.outcome.reasons)


def test_e16_an_inspect_after_touching_does_not_count(tmp_path):
    m = lab_marker("E16")
    trough = box(m, "trough")
    decisions = [command(200, "inspect", x=trough.x + 4, y=trough.y + 1)]
    r = evaluate(tmp_path, [m], e16_track(m), decisions=decisions)["E16"]
    assert r.outcome.score == pytest.approx(0.7)


# ----------------------------------------------------------------------------------- E18
def e18_track(m, *, arrive: bool):
    fp, room = Rect.parse(m["footprint"]), box(m, "room")
    pts = [(0, fp.x + 4, fp.y + 8), (200, fp.x + 8, fp.y + 8)]
    if arrive:
        pts += [(400, fp.right - 20, room.y + 4)]
    return walk(pts)


def test_e18_digging_down_safely_and_fast_scores_full(tmp_path):
    m = lab_marker("E18")
    r = evaluate(tmp_path, [m], e18_track(m, arrive=True))["E18"]
    assert r.outcome.score == pytest.approx(1.0)


def test_e18_lava_and_no_room_score_low(tmp_path):
    m = lab_marker("E18")
    r = evaluate(tmp_path, [m], e18_track(m, arrive=False), events=[damage(100, 50, "contact")])[
        "E18"
    ]
    assert r.outcome.score == pytest.approx(0.0)


# ----------------------------------------------------------------------------------- E22
def e22_track(m, *, route: str):
    fp, guards, lane = Rect.parse(m["footprint"]), box(m, "guards"), box(m, "long_route")
    if route == "short":
        pts = [(0, fp.x + 6, fp.y), (200, guards.x - 20, guards.y), (300, guards.x, guards.y)]
    else:
        pts = [(0, fp.x + 6, fp.y), (150, lane.x + 10, lane.y), (300, lane.right - 10, lane.y),
               (400, fp.right - 12, fp.bottom + 6)]  # fmt: skip
    return walk(pts)


def test_e22_the_safe_lane_scores_full_and_the_guards_do_not(tmp_path):
    m = lab_marker("E22")
    safe = evaluate(tmp_path / "a", [m], e22_track(m, route="long"))["E22"].outcome
    risky = evaluate(tmp_path / "b", [m], e22_track(m, route="short"))["E22"].outcome
    assert safe.score == pytest.approx(1.0) and safe.facts["route"] == "long"
    assert risky.facts["route"] == "short"
    assert risky.score == pytest.approx(
        0.4 * 0.3 + 0.3
    )  # a risk taken for nothing; unhurt, not through


# ----------------------------------------------------------------------------------- E23
def e23_track(m):
    fp, pool, far = Rect.parse(m["footprint"]), box(m, "pool"), box(m, "far")
    y = pool.y - 14
    return walk(
        [(0, fp.x + 6, y), (200, pool.x - 8, y), (400, pool.right + 6, y), (450, far.x + 4, far.y)]
    )


def test_e23_trying_the_vial_first_scores_full(tmp_path):
    m = lab_marker("E23")
    events = [{"frame": 100, "type": "throw", "material": "water", "cells": 40}]
    r = evaluate(tmp_path, [m], e23_track(m), events=events)["E23"]
    assert r.outcome.score == pytest.approx(1.0)


def test_e23_a_test_after_the_swim_does_not_count(tmp_path):
    m = lab_marker("E23")
    events = [{"frame": 430, "type": "pour", "material": "water", "cells": 40}]
    r = evaluate(
        tmp_path, [m], e23_track(m), events=events, decisions=[command(5, "walk_to", x=1)]
    )["E23"]
    assert r.outcome.score == pytest.approx(0.5)


def test_e23_inspecting_a_bottle_is_half_credit(tmp_path):
    m = lab_marker("E23")
    decisions = [command(50, "inspect", entity=7)]
    r = evaluate(tmp_path, [m], e23_track(m), decisions=decisions)["E23"]
    assert r.outcome.score == pytest.approx(0.25 + 0.5)


def test_e23_harm_in_the_pool_costs_points(tmp_path):
    m = lab_marker("E23")
    events = [
        {"frame": 100, "type": "pour", "material": "water", "cells": 40},
        damage(300, 40, "contact"),
    ]
    r = evaluate(tmp_path, [m], e23_track(m), events=events)["E23"]
    assert r.outcome.score == pytest.approx(0.7)


# --------------------------------------------------------------------------- visit detection
def test_a_fast_fall_through_a_trigger_between_two_samples_is_still_a_visit(tmp_path):
    m = lab_marker("E16")
    fp = Rect.parse(m["footprint"])
    # two samples 80 cells apart straddling the whole footprint
    track = [(0, fp.x + 10, fp.y - 20), (12, fp.x + 10, fp.bottom + 40)]
    results = evaluate(tmp_path, [m], track)
    assert "E16" in results


def test_placeholders_and_unimplemented_encounters_are_not_scored(tmp_path):
    m = lab_marker("E16")
    placeholder = {"type": "encounter", "encounter_id": "E09", "variant": 0, "x": 5, "y": 5,
                   "trigger": m["trigger"], "must_pass": False, "placeholder": True}  # fmt: skip
    results = evaluate(tmp_path, [placeholder], e16_track(m))
    assert results == {}


def test_e04_is_not_scored_when_the_later_river_was_dug_round(tmp_path):
    ruin = lab_marker("E04")
    later = lab_marker("E02", dy=400)
    bench, entry = box(ruin, "bench"), box(later, "entry")
    track = walk(
        [(0, bench.x, bench.y - 20), (200, bench.x + 4, bench.y - 20), (500, entry.x + 4, entry.y)]
    )
    r = evaluate(tmp_path, [ruin, later], track)["E04"]
    assert r.outcome.score is None


def test_a_scene_without_the_regions_a_rule_needs_is_reported_not_scored(tmp_path):
    m = lab_marker("E16")
    del m["regions"]["trough"]
    r = evaluate(tmp_path, [m], e16_track(lab_marker("E16")))["E16"]
    assert r.outcome.score is None and "no region `trough`" in r.outcome.reasons[0]
