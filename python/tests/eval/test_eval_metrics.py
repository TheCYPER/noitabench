"""The global metrics, on hand-made recordings."""

from __future__ import annotations

from pathlib import Path

import pytest
from eval_runs import box, command, damage, lab_marker, walk, write_run
from noitabench.eval.encounters import evaluate_visits
from noitabench.eval.geometry import Rect
from noitabench.eval.metrics import Metric, compute_metrics
from noitabench.eval.recording import RunData, load_run
from noitabench.worldgen.config import load_materials

MATS = load_materials()
LAVA, ACID, SLUDGE, ROCK = MATS["lava"], MATS["acid"], MATS["toxic_sludge"], MATS["rock"]


def metrics(tmp: Path, **kw) -> dict[str, Metric]:
    run = load_run(write_run(tmp / "run", **kw))
    return by_name(run)


def by_name(run: RunData) -> dict[str, Metric]:
    return {m.name: m for m in compute_metrics(run, evaluate_visits(run))}


def down(y0: int, y1: int, frames: int, x: float = 100.0):
    return walk([(0, x, y0), (frames, x, y1)])


# ------------------------------------------------------------------------------ repeat harm
def test_repeat_harm_counts_episodes_of_a_kind_that_already_hurt(tmp_path):
    events = [
        damage(100, 5, "fire"),
        damage(130, 5, "fire"),  # the same episode
        damage(600, 5, "fire"),  # a repeat
        damage(900, 5, "explosion"),  # another kind
    ]
    m = metrics(tmp_path, track=down(100, 300, 1000), events=events)["repeat_harm"]
    assert m.opportunities == 3
    assert m.value == pytest.approx(2 / 3)
    assert m.detail["episodes_by_kind"] == {"fire": 2, "explosion": 1}


def test_repeat_harm_ignores_enemy_attacks_and_is_unmeasured_without_hazards(tmp_path):
    events = [damage(100, 5, "hit"), damage(400, 5, "melee")]
    m = metrics(tmp_path, track=down(100, 300, 600), events=events)["repeat_harm"]
    assert m.value is None and m.opportunities == 0


def test_repeat_harm_names_the_hazard_from_the_grid(tmp_path):
    # the player stands in lava at first, then in acid: two kinds, no repeat
    patches = [(95, 195, 20, 40, LAVA), (95, 395, 20, 40, ACID)]
    track = walk([(0, 100, 200), (300, 100, 200), (600, 100, 400), (900, 100, 400)])
    events = [damage(100, 5, "contact"), damage(800, 5, "contact")]
    m = metrics(tmp_path, track=track, events=events, patches=patches)["repeat_harm"]
    assert m.detail["episodes_by_kind"] == {"lava": 1, "acid": 1}
    assert m.value == pytest.approx(1.0)


def test_repeat_harm_in_the_same_liquid_twice_is_a_repeat(tmp_path):
    patches = [(95, 195, 20, 40, SLUDGE)]
    track = down(200, 210, 1000)
    events = [damage(100, 5, "contact"), damage(700, 5, "contact")]
    m = metrics(tmp_path, track=track, events=events, patches=patches)["repeat_harm"]
    assert m.detail["episodes_by_kind"] == {"toxic_sludge": 2}
    assert m.value == pytest.approx(0.5)


# ------------------------------------------------------------------------- low-health discipline
def test_low_hp_discipline_healing_is_good_and_pressing_on_is_bad(tmp_path):
    hp = {0: 100.0, 300: 30.0, 600: 60.0, 1200: 30.0}
    events = [damage(300, 70, "hit"), damage(1200, 30, "hit"), damage(2000, 10, "hit")]
    m = metrics(tmp_path, track=down(100, 300, 2200), hp=hp, events=events)["low_hp_discipline"]
    assert (m.detail["good"], m.detail["bad"]) == (1, 1)
    assert m.value == pytest.approx(0.5)


def test_low_hp_discipline_poison_from_the_same_blow_is_not_new_harm(tmp_path):
    hp = {0: 100.0, 300: 30.0, 800: 60.0}
    ticks = [damage(300 + 30 * i, 1, "contact") for i in range(1, 12)]
    events = [damage(300, 70, "contact"), *ticks]
    m = metrics(tmp_path, track=down(100, 300, 1200), hp=hp, events=events)["low_hp_discipline"]
    assert m.value == pytest.approx(1.0)


def test_low_hp_discipline_is_unmeasured_when_health_never_falls(tmp_path):
    m = metrics(tmp_path, track=down(100, 300, 600))["low_hp_discipline"]
    assert m.value is None


# --------------------------------------------------------------------------------- backtracking
def test_backtracking_counts_the_climb_back_from_the_deepest_point(tmp_path):
    track = walk([(0, 100, 100), (600, 100, 500), (900, 100, 300), (1500, 100, 700)])
    m = metrics(tmp_path, track=track)["backtracking"]
    assert m.detail["descent"] == pytest.approx(600)
    assert m.detail["retreat"] == pytest.approx(200, abs=1)
    assert m.value == pytest.approx(1 - 200 / 600, abs=0.01)


def test_backtracking_needs_a_long_enough_descent(tmp_path):
    m = metrics(tmp_path, track=down(100, 200, 300))["backtracking"]
    assert m.value is None


# ------------------------------------------------------------------------------ decisions per layer
def test_decisions_per_layer_scores_the_decisions_spent_in_each_finished_layer(tmp_path):
    # layer 1 is y 128..512; the player is in it from about frame 150 to about frame 1000
    track = down(80, 700, 1500)
    cheap = [command(300 + 10 * i, "walk_to", x=5) for i in range(40)]
    m = metrics(tmp_path / "a", track=track, decisions=cheap)["decisions_per_layer"]
    assert m.value == pytest.approx(1.0) and m.opportunities == 1
    dear = [command(300 + 3 * i, "walk_to", x=5) for i in range(190)]
    m = metrics(tmp_path / "b", track=track, decisions=dear)["decisions_per_layer"]
    assert 0.4 < m.value < 0.6  # 190 decisions between 80 (full) and 300 (none)


def test_decisions_per_layer_needs_decisions(tmp_path):
    m = metrics(tmp_path, track=down(80, 700, 1500))["decisions_per_layer"]
    assert m.value is None and "decisions.jsonl" in m.reason


# --------------------------------------------------------------------------------- route
def test_route_efficiency_is_the_main_path_over_the_distance_walked(tmp_path):
    main = [[100, y] for y in range(100, 1101, 50)]  # 1000 cells straight down
    wander = walk([(0, 100, 100), (500, 600, 300), (1000, 100, 700), (1500, 100, 1100)])
    m = metrics(tmp_path, track=wander, main_path=main)["route_efficiency"]
    assert m.value == pytest.approx(1000 / m.detail["walked"], abs=0.02)
    assert 0.4 < m.value < 0.7


def test_route_efficiency_is_capped_at_one_for_a_shortcut(tmp_path):
    main = [[100 + 20 * i, 100 + 50 * i] for i in range(21)]  # a winding way, more than 1000
    m = metrics(tmp_path, track=down(100, 1100, 1000), main_path=main)["route_efficiency"]
    assert m.value == pytest.approx(1.0)


# --------------------------------------------------------------------------------- hit rate
def creature(eid: int, x: float, y: float) -> dict:
    return {
        "id": eid,
        "kind": "longleg",
        "x": x,
        "y": y,
        "w": 10,
        "h": 12,
        "hp": 2.75,
        "hp_max": 2.75,
    }


def shots(n: int, spell: str = "LIGHT_BULLET", first: int = 40) -> list[dict]:
    return [
        {"frame": first + 10 * i, "type": "cast", "spells": spell, "projectiles": 1}
        for i in range(n)
    ]


def hit(frame: int) -> dict:
    return {
        "frame": frame,
        "type": "hit",
        "projectile": "LIGHT_BULLET",
        "target": "longleg",
        "id": 9,
        "damage": 3,
    }


def test_hit_rate_is_hits_over_projectiles_with_a_creature_in_sight(tmp_path):
    track = down(100, 100, 300)
    crowd = {f: [creature(9, 150, 100)] for f in range(0, 300, 12)}
    events = shots(4) + [hit(45), hit(55)]
    m = metrics(tmp_path, track=track, creatures=crowd, events=events)["hit_rate"]
    assert m.value == pytest.approx(0.5) and m.opportunities == 4


def test_hit_rate_ignores_digging_and_casts_with_nothing_near(tmp_path):
    track = down(100, 100, 300)
    crowd = {f: [creature(9, 600, 100)] for f in range(0, 300, 12)}
    events = shots(10, "DIGGER", 0) + shots(5, first=20)
    m = metrics(tmp_path, track=track, creatures=crowd, events=events)["hit_rate"]
    assert m.value is None


def test_hit_rate_ignores_creatures_behind_a_wall(tmp_path):
    track = down(100, 100, 300)
    crowd = {f: [creature(9, 150, 100)] for f in range(0, 300, 12)}
    wall = [(120, 80, 10, 60, ROCK)]
    m = metrics(tmp_path, track=track, creatures=crowd, events=shots(5), patches=wall)["hit_rate"]
    assert m.value is None


# --------------------------------------------------------------------------------- liquids
def test_new_liquids_tried_is_the_share_poured_thrown_or_drunk_after_pickup(tmp_path):
    events = [
        {"frame": 10, "type": "pickup", "item": "bottle", "detail": "blood", "id": 1},
        {"frame": 20, "type": "pickup", "item": "bottle", "detail": "oil", "id": 2},
        {"frame": 30, "type": "pickup", "item": "bottle", "detail": "", "id": 3},  # empty: ignored
        {"frame": 200, "type": "pour", "material": "blood", "cells": 30},
        {"frame": 5, "type": "pour", "material": "oil", "cells": 30},  # before the pickup
    ]
    m = metrics(tmp_path, track=down(100, 300, 600), events=events)["new_liquids_tried"]
    assert m.value == pytest.approx(0.5) and m.opportunities == 2
    assert m.detail["tried"] == ["blood"]


# --------------------------------------------------------------------------------- inspect
def test_inspect_before_hazard_needs_an_inspect_before_the_first_approach(tmp_path):
    m16 = lab_marker("E16")
    trough = box(m16, "trough")
    fp = Rect.parse(m16["footprint"])
    y = trough.y - 14
    track = walk([(0, fp.x + 6, y), (100, trough.x - 8, y), (250, trough.right + 6, y)])
    before = [command(20, "inspect", x=trough.x, y=trough.y)]
    after = [command(200, "inspect", x=trough.x, y=trough.y)]
    kw = {"markers": [m16], "track": track}
    got = metrics(tmp_path / "a", decisions=before, **kw)["inspect_before_hazard"]
    assert got.value == pytest.approx(1.0) and got.opportunities == 1
    late = metrics(tmp_path / "b", decisions=after, **kw)["inspect_before_hazard"]
    assert late.value == pytest.approx(0.0)
    none = metrics(tmp_path / "c", **kw)["inspect_before_hazard"]
    assert none.value is None


# --------------------------------------------------------------------------------- the key
def e06_run(tmp: Path, *, picks: list[str], blast: bool) -> Metric:
    m = lab_marker("E06", dy=1400)
    front, plug = box(m, "front"), box(m, "plug")
    track = walk(
        [
            (0, front.x + 6, front.y - 100),
            (300, front.x + 6, front.y + 4),
            (600, front.x + 6, front.y + 4),
        ]
    )
    events = [
        {"frame": 5 + i, "type": "pickup", "item": "spell", "detail": s, "id": 7}
        for i, s in enumerate(picks)
    ]
    if blast:
        events.append({"frame": 500, "type": "explosion", "x": plug.cx, "y": plug.cy, "radius": 75})
    items = [
        {"type": "item", "item": "spell", "spell": s, "role": "breaker", "x": 1, "y": 1}
        for s in ("BOMB", "EXPLOSIVE_PROJECTILE")
    ]
    return metrics(tmp, markers=[m, *items], track=track, events=events)["key_assembly"]


def test_key_assembly_is_scored_only_when_the_key_was_complete(tmp_path):
    full = e06_run(tmp_path / "a", picks=["BOMB", "EXPLOSIVE_PROJECTILE"], blast=True)
    assert full.value == pytest.approx(1.0) and full.capabilities == ("N8", "C3")
    spent = e06_run(tmp_path / "b", picks=["BOMB", "EXPLOSIVE_PROJECTILE"], blast=False)
    assert spent.value == pytest.approx(0.0)
    partial = e06_run(tmp_path / "c", picks=["BOMB"], blast=False)
    assert partial.value is None and "never complete" in partial.reason


# --------------------------------------------------------------------------------- layers
def test_layer_completion_and_end_health(tmp_path):
    track = down(80, 1000, 2000)
    hp = {0: 100.0, 400: 40.0}
    m = metrics(tmp_path, track=track, hp=hp)
    assert m["layer_completion"].opportunities == 2  # layer 1 finished, layer 2 entered
    assert 0.5 < m["layer_completion"].value < 1.0
    assert m["layer_end_hp"].value == pytest.approx(0.8)  # 40 % of the health on leaving, 40/50


def test_a_death_in_a_layer_halves_its_progress(tmp_path):
    track = down(80, 900, 1500)
    alive = metrics(tmp_path / "a", track=track)["layer_completion"].value
    dead = metrics(tmp_path / "b", track=track, hp={0: 100.0, 1400: 0.0})["layer_completion"].value
    assert dead < alive


def test_the_metrics_that_the_recordings_cannot_show_say_why(tmp_path):
    m = metrics(tmp_path, track=down(80, 300, 600))
    for name in ("notes_used", "inspect_result_used", "wand_edit_gain", "stop_when_unsure"):
        assert m[name].value is None and len(m[name].reason) > 20
