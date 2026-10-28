"""Grid queries for entities and projectiles through Python: rays, sweeps, overlap, contact damage."""

from __future__ import annotations

import noitabench_core
import pytest
from noitabench.env import Env


def arena() -> noitabench_core.Env:
    env = noitabench_core.Env(60, 40, 1)
    env.fill_rect(0, 30, 60, 10, "rock")
    return env


def test_contract_query_methods_exist() -> None:
    env = noitabench_core.Env(8, 8, 1)
    for name in ("overlap", "raycast", "sweep_box", "contact_damage"):
        assert callable(getattr(env, name)), name


def test_overlap_counts_materials_and_kinds() -> None:
    env = arena()
    env.fill_rect(10, 20, 6, 4, "water")
    env.fill_rect(10, 24, 6, 2, "sand")
    o = env.overlap(8, 18, 10, 10)
    assert (o["inside"], o["outside"], o["burning"]) == (100, 0, 0)
    assert o["materials"] == {"air": 64, "water": 24, "sand": 12}
    assert o["kinds"] == {"air": 64, "liquid": 24, "powder": 12}
    out = env.overlap(-2, -3, 6, 8)
    assert (out["inside"], out["outside"]) == (20, 28)


def test_raycast_finds_the_first_blocking_cell() -> None:
    env = arena()
    env.fill_rect(20, 10, 1, 5, "wood")
    hit = env.raycast(0, 12, 40, 12)
    assert hit == {
        "x": 20, "y": 12, "material": "wood", "kind": "static", "last_free": (19, 12),
        "step": 20, "steps": 40,
    }  # fmt: skip
    assert env.raycast(0, 5, 40, 5) is None
    # ignore lets the line through one material; the next obstacle is the floor line
    assert env.raycast(0, 12, 40, 12, ignore="wood") is None
    down = env.raycast(10, 0, 10, 39)
    assert down is not None and (down["y"], down["material"]) == (30, "rock")


def test_raycast_masks_and_the_world_edge() -> None:
    env = arena()
    env.fill_rect(5, 10, 1, 4, "water")
    assert env.raycast(0, 12, 20, 12, "blocking") is None
    assert env.raycast(0, 12, 20, 12, "surfaces_and_liquids")["material"] == "water"
    assert env.raycast(0, 12, 20, 12, ["liquid"])["x"] == 5
    # leaving the world is a hit on the boundary, whatever the mask
    edge = env.raycast(50, 5, 90, 5, [])
    assert edge is not None and (edge["x"], edge["material"]) == (60, "boundary")


def test_sweep_box_falls_climbs_and_stops() -> None:
    env = arena()
    s = env.sweep_box(10, 0, 4, 6, 0, 100)
    assert (s["x"], s["y"], s["blocked_y"], s["blocked_x"]) == (10, 24, "rock", None)
    env.fill_rect(30, 27, 20, 3, "rock")  # a ledge of 3
    walk = env.sweep_box(20, 24, 4, 6, 20, 0)
    assert (walk["x"], walk["blocked_x"]) == (26, "rock")
    up = env.sweep_box(20, 24, 4, 6, 20, 0, step_up=4)
    assert (up["x"], up["y"], up["climbed"], up["blocked_x"]) == (40, 21, 3, None)
    water_walk = Env(30, 20, 1)
    water_walk.fill_rect(10, 5, 5, 5, "water")
    assert water_walk.sweep_box(2, 5, 3, 4, 20, 0)["blocked_x"] is None


def test_contact_damage_follows_the_rule() -> None:
    env = arena()
    env.fill_rect(10, 10, 5, 17, "acid")
    d = env.contact_damage(10, 10, 5, 17)
    assert d["raw"] == pytest.approx(0.425)
    assert d["parts"] == [
        {"material": "acid", "cells": 85, "counted": 85, "damage": pytest.approx(0.425)}
    ]
    env.fill_rect(45, 0, 10, 10, "acid")  # 100 cells: only 85 are paid for
    big = env.contact_damage(45, 0, 10, 10)["parts"][0]
    assert (big["cells"], big["counted"]) == (100, 85)
    env.fill_rect(30, 10, 3, 1, "lava")  # 3 cells are under the floor of 4
    assert env.contact_damage(28, 9, 6, 3)["raw"] == 0.0
    assert env.contact_damage(28, 9, 6, 3, min_cells=3)["raw"] == pytest.approx(0.009)


def test_query_arguments_are_value_errors() -> None:
    env = arena()
    with pytest.raises(ValueError, match="unknown mask `walls`"):
        env.raycast(0, 0, 5, 5, "walls")
    with pytest.raises(ValueError, match="unknown kind `rock`"):
        env.raycast(0, 0, 5, 5, ["rock"])
    with pytest.raises(ValueError, match="unknown material `unobtanium`"):
        env.sweep_box(0, 0, 2, 2, 1, 1, ignore="unobtanium")
    with pytest.raises(ValueError, match="x must fit in 32 bits"):
        env.overlap(2**40, 0, 3, 3)
    with pytest.raises(ValueError, match="w must fit in 32 bits"):
        env.overlap(0, 0, 10**30, 3)  # beyond 64 bits is still a ValueError
    with pytest.raises(ValueError, match="step_up must fit in 32 bits"):
        env.sweep_box(0, 0, 2, 2, 1, 1, step_up=-(2**70))
    with pytest.raises(ValueError, match="min_cells must be 0"):
        env.contact_damage(0, 0, 3, 3, min_cells=-1)
    with pytest.raises(ValueError, match="max_cells must be 0"):
        env.contact_damage(0, 0, 3, 3, max_cells=2**40)
    # extreme but valid numbers terminate
    assert env.raycast(0, 0, 2**31 - 1, 2**31 - 1, []) is not None
    assert env.overlap(-(2**31), -(2**31), 2**31 - 1, 2**31 - 1)["inside"] == 0


def test_wrapper_mirrors_the_query_methods() -> None:
    env = Env(60, 40, 1)
    env.fill_rect(0, 30, 60, 10, "rock")
    assert env.raycast(5, 0, 5, 39)["y"] == 30
    assert env.sweep_box(5, 0, 2, 4, 0, 99)["y"] == 26
    assert env.overlap(0, 28, 4, 4)["materials"] == {"air": 8, "rock": 8}
    assert env.contact_damage(0, 28, 4, 4)["raw"] == 0.0
