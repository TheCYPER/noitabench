"""The scoring rules of the week-4 rooms (E05, E09, E10, E21, E24), on hand-made recordings.

Each test says what the player did in a few waypoints and events and checks the score and the
reasons. The geometry (footprint, regions) and the slot liquids are those of the real scene
definitions in their lab worlds; the scene's own items and creatures are placed in its regions,
where the entity list would first show them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eval_runs import box, command, damage, lab_marker, walk, write_run
from noitabench.eval.encounters import Result, evaluate_visits
from noitabench.eval.geometry import Rect
from noitabench.eval.recording import load_run

LAVA_ROW = "r01"  # lava + water -> rock: a lava cell becomes rock
SLUDGE_ROW = "r11"  # water + toxic sludge -> water


def evaluate(tmp: Path, markers, track, **kw) -> dict[str, Result]:
    """Write the run, evaluate it, return the results by encounter id (one each)."""
    run = load_run(write_run(tmp / "run", markers=markers, track=track, **kw))
    out: dict[str, Result] = {}
    for r in evaluate_visits(run):
        out.setdefault(r.visit.scene.eid, r)
    return out


def stand(r: Rect, dx: float = 0.0) -> tuple[float, float]:
    """The hit box (6 x 16) standing on the floor of region `r`, at its middle (+ `dx`)."""
    return r.x + r.w / 2 - 3 + dx, r.bottom - 16


def thing(eid: int, kind: str, at: Rect, detail: str = "", w: int = 4, h: int = 6) -> dict:
    """An entity of the first frame placed in the middle of region `at`."""
    return {
        "id": eid, "kind": kind, "x": at.cx - w / 2, "y": at.cy - h / 2, "w": w, "h": h,
        "hp": 0.0, "hp_max": 0.0, "detail": detail,
    }  # fmt: skip


def ev(frame: int, etype: str, /, **fields: Any) -> dict:
    return {"frame": frame, "type": etype, **fields}


def pickup(frame: int, eid: int, item: str = "bottle", detail: str = "") -> dict:
    return ev(frame, "pickup", item=item, detail=detail, id=eid)


def rows(frame: int, row: str, region: Rect, n: int = 5) -> list[dict]:
    """`n` reaction events of `row` along the top of `region`."""
    return [
        ev(frame + i, "reaction", id=row, x=region.x + i, y=region.y, bx=region.x + i, by=region.y)
        for i in range(n)
    ]


def poisoned(frame: int, active: int = 1) -> dict:
    return ev(frame, "status", target="player", id=1, status="poisoned", active=active)


def drink(frame: int, material: str, cells: int = 60) -> dict:
    return ev(frame, "drink", material=material, cells=cells)


def score(result: Result) -> float | None:
    return result.outcome.score


# ======================================================================================= E05
def e05_scene():
    m = lab_marker("E05")
    keys = {"solvent": m["params"]["A"], "decoy": m["params"]["B"]}
    items = [
        thing(4, "bottle", box(m, "key"), keys["solvent"]),
        thing(5, "bottle", box(m, "decoy"), keys["decoy"]),
        thing(7, "wand", box(m, "vault"), w=10, h=4),
    ]
    return m, keys, items


def e05_track(m, *, back_for_key: bool = False):
    """Into the first hall, to the key, down the shaft, across the river into the vault; with
    `back_for_key`, down the shaft first, back up for the key, and down again."""
    hall, landing, vault = box(m, "key_hall"), box(m, "landing"), box(m, "vault")
    _hx, hy = stand(hall)
    kx, _ = stand(box(m, "key"))
    sx = box(m, "drop").x
    lx, ly = stand(landing)
    vx, vy = stand(vault)
    if not back_for_key:
        points = [(0, hall.x - 10, hy), (40, hall.x + 2, hy), (100, kx, hy), (200, sx, hy),
                  (300, lx, ly), (400, lx - 10, ly), (600, vx, vy), (650, vx, vy)]  # fmt: skip
    else:
        points = [(0, hall.x - 10, hy), (40, hall.x + 2, hy), (200, sx, hy), (300, lx, ly),
                  (360, lx, ly), (450, sx, hy), (500, kx, hy), (600, sx, hy), (700, lx, ly),
                  (800, lx - 10, ly), (1000, vx, vy), (1050, vx, vy)]  # fmt: skip
    return walk(points)


def e05_events(m, keys, t_pick: int, t_pour: int) -> list[dict]:
    return [
        pickup(t_pick, 4, detail=keys["solvent"]),
        ev(t_pour, "pour", material=keys["solvent"], cells=90),
        *rows(t_pour + 10, LAVA_ROW, box(m, "river"), 8),
    ]


def test_e05_taking_the_key_before_the_shaft_and_crossing_on_a_crust_scores_full(tmp_path):
    m, keys, items = e05_scene()
    events = e05_events(m, keys, 100, 420)
    r = evaluate(tmp_path, [m], e05_track(m), events=events, creatures={0: items})["E05"]
    assert score(r) == pytest.approx(1.0), r.outcome.reasons
    assert r.outcome.facts["key_in_hand"] and r.outcome.facts["lava_solidified"]


def test_e05_going_back_up_for_the_key_scores_less_than_bringing_it(tmp_path):
    m, keys, items = e05_scene()
    events = e05_events(m, keys, 500, 820)
    r = evaluate(
        tmp_path, [m], e05_track(m, back_for_key=True), events=events, creatures={0: items}
    )["E05"]
    assert r.outcome.facts["key_fetched_late"] and not r.outcome.facts["key_in_hand"]
    assert score(r) == pytest.approx(1.0 - 0.45 * 0.4)  # the key part at 0.6
    assert any("went back up for the key" in why for why in r.outcome.reasons)


def test_e05_wading_through_the_lava_without_the_key_scores_low(tmp_path):
    m, _keys, items = e05_scene()
    events = [damage(450, 30, "contact"), damage(480, 20, "fire")]
    r = evaluate(tmp_path, [m], e05_track(m), events=events, creatures={0: items})["E05"]
    assert score(r) == pytest.approx(0.15)  # only reaching the vault: no key, no crust, 50 HP
    assert not r.outcome.facts["key_in_hand"] and not r.outcome.facts["lava_solidified"]


def test_e05_a_bottle_of_the_key_liquid_brought_from_elsewhere_counts_unless_thrown(tmp_path):
    m, keys, items = e05_scene()
    elsewhere = thing(99, "bottle", Rect(400, 400, 8, 8), keys["solvent"])
    own = [pickup(20, 99, detail=keys["solvent"]),
           ev(420, "pour", material=keys["solvent"], cells=90),
           *rows(430, LAVA_ROW, box(m, "river"), 8)]  # fmt: skip
    brought = evaluate(
        tmp_path / "a", [m], e05_track(m), events=own, creatures={0: [*items, elsewhere]}
    )["E05"]
    assert brought.outcome.facts["key_in_hand"]
    assert any(f"brought {keys['solvent']}" in why for why in brought.outcome.reasons)
    thrown = [*own, ev(150, "throw", material=keys["solvent"], cells=400)]
    lost = evaluate(
        tmp_path / "b", [m], e05_track(m), events=thrown, creatures={0: [*items, elsewhere]}
    )["E05"]
    assert not lost.outcome.facts["key_in_hand"]


def test_e05_the_first_hall_alone_is_not_scored(tmp_path):
    """Taking the bottles and leaving: the key was never needed, so memory was not put to the test."""
    m, keys, items = e05_scene()
    hall = box(m, "key_hall")
    hx, hy = stand(hall)
    track = walk([(0, hall.x - 10, hy), (60, hx, hy), (200, hall.x - 10, hy)])
    events = [pickup(100, 4, detail=keys["solvent"])]
    r = evaluate(tmp_path, [m], track, events=events, creatures={0: items})["E05"]
    assert score(r) is None and "never went down" in r.outcome.reasons[0]


def test_e05_a_run_that_never_comes_near_it_has_no_visit(tmp_path):
    m, _keys, items = e05_scene()
    track = walk([(0, 400, 300), (300, 450, 300)])
    assert "E05" not in evaluate(tmp_path, [m], track, creatures={0: items})


def test_e04_counts_the_vault_river_among_the_later_lava_rivers(tmp_path):
    """The lesson of the ruin (E04) applies to the river in front of the vault too."""
    lab = lab_marker("E04", dx=0, dy=400)
    m, keys, items = e05_scene()
    bench = box(lab, "bench")
    bx, by = stand(bench)
    track = walk([(0, bx, by), (300, bx, by), (330, 400, 200), (400, 400, 200)])
    track += [(f + 400, x, y) for f, x, y in e05_track(m)]
    events = [pickup(100, 50, detail=lab["params"]["A"])]
    events += [{**e, "frame": e["frame"] + 400} for e in e05_events(m, keys, 100, 420)]
    r = evaluate(tmp_path, [lab, m], track, events=events, creatures={0: items})
    assert r["E05"].outcome.facts["lava_solidified"]
    assert r["E04"].outcome.facts == {"later": 1, "used": 1}


# ======================================================================================= E09
def e09_scene():
    m = lab_marker("E09")
    items = [
        thing(4, "barrel_gunpowder", box(m, "barrel"), w=8, h=10),
        thing(7, "wand", box(m, "reward"), w=10, h=4),
    ]
    guard = thing(5, "shotgunner", box(m, "interior"), w=6, h=15) | {"hp": 22.5, "hp_max": 22.5}
    return m, [*items, guard]


def e09_walk_in(m, t0: int, t1: int):
    hall = box(m, "hall")
    _hx, hy = stand(hall)
    rx, _ = stand(box(m, "reward"))
    return [(t0, hall.x - 12, hy), (t1, rx, hy)]


def test_e09_blowing_the_barrel_from_outside_burns_the_bunker_and_scores_full(tmp_path):
    """The best play blows the barrel before the visit begins: the scene's own barrel and guard
    are judged whenever it happened."""
    m, things = e09_scene()
    hall, posts, barrel = box(m, "hall"), box(m, "posts"), box(m, "barrel")
    _hx, hy = stand(hall)
    track = walk([(0, hall.x - 12, hy), (480, hall.x - 12, hy), *e09_walk_in(m, 500, 700)])
    events = [
        ev(100, "hit", projectile="LIGHT_BULLET", target="barrel_gunpowder", id=4, damage=3.0),
        ev(100, "barrel_break", kind="barrel_gunpowder", id=4, x=barrel.cx, y=barrel.y + 6,
           burning=0),
        ev(150, "ignite", x=posts.x + 1, y=posts.y + 2, material="wood", by="fire"),
        ev(450, "death", target="shotgunner", id=5, source="fire", x=0, y=0),
        pickup(710, 7, item="wand"),
    ]  # fmt: skip
    r = evaluate(tmp_path, [m], track, events=events, creatures={0: things})["E09"]
    assert score(r) == pytest.approx(1.0), r.outcome.reasons
    assert r.outcome.facts["guard_death"] == "fire" and r.outcome.facts["wood_burned"]


def test_e09_a_duel_through_the_slits_scores_low(tmp_path):
    m, things = e09_scene()
    hall = box(m, "hall")
    hx, hy = stand(hall)
    track = walk([(0, hall.x - 12, hy), (100, hx - 20, hy), (400, hx - 20, hy)])
    events = [
        *[ev(f, "hit", projectile="LIGHT_BULLET", target="shotgunner", id=5, damage=3.0)
          for f in (200, 220, 240)],
        damage(210, 27, "hit") | {"x": hx - 20, "y": hy},
        damage(250, 27, "hit") | {"x": hx - 20, "y": hy},
        ev(260, "death", target="shotgunner", id=5, source="hit", x=0, y=0),
    ]  # fmt: skip
    r = evaluate(tmp_path, [m], track, events=events, creatures={0: things})["E09"]
    assert score(r) == pytest.approx(0.20 / 0.85)  # won, but no fire, 54 HP; no barrel
    assert any("a duel" in why for why in r.outcome.reasons)
    assert r.outcome.facts["guard_shots"] == 3


def test_e09_the_right_idea_from_inside_the_blast_costs_the_safety_parts(tmp_path):
    m, things = e09_scene()
    hall, posts, barrel = box(m, "hall"), box(m, "posts"), box(m, "barrel")
    _hx, hy = stand(hall)
    near_barrel = barrel.cx - 15
    track = walk([(0, hall.x - 12, hy), (80, near_barrel, hy), (600, near_barrel, hy)])
    events = [
        ev(100, "barrel_break", kind="barrel_gunpowder", id=4, x=barrel.cx, y=barrel.y + 6,
           burning=0),
        damage(100, 26, "explosion") | {"x": near_barrel, "y": hy},
        ev(150, "ignite", x=posts.x + 1, y=posts.y + 2, material="wood", by="fire"),
        ev(450, "death", target="shotgunner", id=5, source="fire", x=0, y=0),
    ]  # fmt: skip
    r = evaluate(tmp_path, [m], track, events=events, creatures={0: things})["E09"]
    expected = 0.45 + 0.20 + 0.15 * (1 - 26 / 30) + 0.20 * (1 - 26 / 50)
    assert score(r) == pytest.approx(expected)


def test_e09_a_barrel_set_off_by_the_guards_buckshot_is_not_the_players_fire(tmp_path):
    m, things = e09_scene()
    hall, posts, barrel = box(m, "hall"), box(m, "posts"), box(m, "barrel")
    hx, hy = stand(hall)
    track = walk([(0, hall.x - 12, hy), (80, hx, hy), (600, hx, hy)])
    fire = [
        ev(150, "ignite", x=posts.x + 1, y=posts.y + 2, material="wood", by="fire"),
        ev(450, "death", target="shotgunner", id=5, source="fire", x=0, y=0),
    ]
    burst = ev(100, "barrel_break", kind="barrel_gunpowder", id=4, x=barrel.cx,
               y=barrel.y + 6, burning=0)  # fmt: skip
    by_guard = [ev(99, "hit", projectile="buckshot", target="barrel_gunpowder", id=4,
                   damage=2.0), burst, *fire]  # fmt: skip
    r = evaluate(tmp_path / "a", [m], track, events=by_guard, creatures={0: things})["E09"]
    assert r.outcome.facts["barrel_by"] == "guard"
    assert any("the guard's own shot" in why for why in r.outcome.reasons)
    assert score(r) == pytest.approx(0.0)  # out of the blast, the fire and the death: luck
    took = [*by_guard, pickup(500, 7, item="wand")]
    won = evaluate(tmp_path / "c", [m], track, events=took, creatures={0: things})["E09"]
    assert won.outcome.facts["won"] and score(won) == pytest.approx((0.20 + 0.20) / 0.85)
    by_me = [ev(99, "hit", projectile="LIGHT_BULLET", target="barrel_gunpowder", id=4,
                damage=3.0), burst, *fire]  # fmt: skip
    mine = evaluate(tmp_path / "b", [m], track, events=by_me, creatures={0: things})["E09"]
    assert mine.outcome.facts["barrel_by"] == "player" and score(mine) == pytest.approx(1.0)


def test_e09_the_doorway_alone_is_not_scored(tmp_path):
    m, things = e09_scene()
    fp, hall = Rect.parse(m["footprint"]), box(m, "hall")
    _hx, hy = stand(hall)
    track = walk([(0, fp.x - 20, hy), (100, fp.x - 3, hy), (300, fp.x - 20, hy)])
    r = evaluate(tmp_path, [m], track, creatures={0: things})["E09"]
    assert score(r) is None and "doorway" in r.outcome.reasons[0]


def test_e09_a_run_that_never_comes_near_it_has_no_visit(tmp_path):
    m, _things = e09_scene()
    assert "E09" not in evaluate(tmp_path, [m], walk([(0, 400, 300), (300, 450, 300)]))


# ======================================================================================= E10
def e10_scene(*, trapped: bool = True):
    """The lab marker and the pack of three Hämis, first on their ledge; with `trapped` they are
    down in the pit from frame 60 on."""
    m = lab_marker("E10")
    pack, pool = box(m, "pack"), box(m, "pool")
    crowd: dict[int, list[dict]] = {}
    for f in range(0, 1201, 12):
        row = []
        for k, eid in enumerate((6, 7, 8)):
            if trapped and f >= 60:
                x, y = pool.x + 4 + 8 * k, pool.bottom - 8
            else:
                x, y = pack.x + 5 * k, pack.y
            row.append({"id": eid, "kind": "longleg", "x": x, "y": y, "w": 10, "h": 8,
                        "hp": 3.0 if trapped else 0.0, "hp_max": 3.0})  # fmt: skip
        crowd[f] = row
    wand = thing(5, "wand", box(m, "reward"), w=10, h=4)
    crowd[0].append(wand)
    return m, crowd


def e10_swim(m):
    near, pool, far = box(m, "near"), box(m, "pool"), box(m, "far")
    nx, ny = stand(near)
    fx, fy = stand(far)
    return walk([(0, near.x - 10, ny), (60, nx, ny), (120, pool.x - 4, ny),
                 (180, pool.cx, pool.y - 12), (240, far.x + 2, fy), (300, fx, fy)])  # fmt: skip


def test_e10_swimming_across_while_the_pack_falls_in_scores_full(tmp_path):
    m, crowd = e10_scene()
    events = [damage(170, 9, "melee"), damage(180, 8, "melee"), pickup(290, 5, item="wand")]
    track = e10_swim(m) + [(f, *e10_swim(m)[-1][1:]) for f in range(312, 1201, 12)]
    r = evaluate(tmp_path, [m], track, events=events, creatures=crowd)["E10"]
    assert score(r) == pytest.approx(1.0), r.outcome.reasons
    assert r.outcome.facts["trapped"] == 3 and r.outcome.facts["crossed"]


def test_e10_standing_at_the_edge_and_being_bitten_scores_low(tmp_path):
    m, crowd = e10_scene()
    near, pool = box(m, "near"), box(m, "pool")
    _nx, ny = stand(near)
    track = walk([(0, near.x - 10, ny), (60, pool.x - 8, ny), (600, pool.x - 8, ny)])
    events = [damage(f, 15, "melee") for f in (120, 200, 280, 360)]
    alive = evaluate(tmp_path / "a", [m], track, events=events, creatures=crowd)["E10"]
    assert score(alive) == pytest.approx(0.20)  # only what the water did by itself
    died = [*events, ev(400, "death", target="player", id=1, source="melee", x=0, y=0)]
    dead = evaluate(tmp_path / "b", [m], track, events=died, creatures=crowd)["E10"]
    assert score(dead) == pytest.approx(0.0), dead.outcome.reasons


def test_e10_a_pack_shot_down_on_its_ledge_did_not_meet_the_water(tmp_path):
    m, crowd = e10_scene(trapped=False)
    events = [pickup(290, 5, item="wand")]
    r = evaluate(tmp_path, [m], e10_swim(m), events=events, creatures=crowd)["E10"]
    assert r.outcome.facts["trapped"] == 0
    assert score(r) == pytest.approx(0.80)


def test_e10_without_its_pack_the_water_part_is_left_out(tmp_path):
    m, _crowd = e10_scene()
    r = evaluate(tmp_path, [m], e10_swim(m))["E10"]
    assert score(r) == pytest.approx(1.0)
    assert any("water: not measured (no pack" in why for why in r.outcome.reasons)


def test_e10_the_doorway_alone_is_not_scored_and_far_away_is_no_visit(tmp_path):
    m, crowd = e10_scene()
    fp, near = Rect.parse(m["footprint"]), box(m, "near")
    _nx, ny = stand(near)
    door = walk([(0, fp.x - 20, ny), (100, fp.x - 3, ny), (300, fp.x - 20, ny)])
    r = evaluate(tmp_path / "a", [m], door, creatures=crowd)["E10"]
    assert score(r) is None and "doorway" in r.outcome.reasons[0]
    far_away = walk([(0, 400, 300), (300, 450, 300)])
    assert "E10" not in evaluate(tmp_path / "b", [m], far_away, creatures=crowd)


# ======================================================================================= E21
def e21_scene():
    m = lab_marker("E21")
    shelf = box(m, "bottles")
    contents = ["toxic_sludge", m["params"]["A"], "potion_heal", m["params"]["B"]]
    items = []
    for k, liquid in enumerate(contents):
        spot = Rect(shelf.x + 4 * k, shelf.y, 4, 6)
        kind = "potion_heal" if liquid == "potion_heal" else "bottle"
        items.append(thing(4 + k, kind, spot, liquid))
    return m, items


def e21_track(m):
    nook = box(m, "nook")
    nx, ny = stand(nook)
    fp = Rect.parse(m["footprint"])
    return walk([(0, fp.x - 10, ny), (40, fp.x + 2, ny), (100, nx, ny), (500, nx, ny),
                 (600, fp.x - 10, ny)])  # fmt: skip


HURT = {0: 100.0, 20: 20.0}  # hurt before reaching the bench


def looks(*ids: int, frame: int = 120) -> list[dict]:
    return [command(frame + 4 * k, "inspect", entity=i) for k, i in enumerate(ids)]


def test_e21_looking_at_the_bottles_then_drinking_the_potion_scores_full(tmp_path):
    m, items = e21_scene()
    events = [pickup(150, 6, detail="potion_heal"), drink(200, "potion_heal", 400)]
    r = evaluate(tmp_path, [m], e21_track(m), hp=HURT, events=events, creatures={0: items},
                 decisions=looks(4, 5, 6, 7))["E21"]  # fmt: skip
    assert score(r) == pytest.approx(1.0), r.outcome.reasons
    assert r.outcome.facts["hurt_on_arrival"] and r.outcome.facts["looked_first"]


def test_e21_the_potion_drunk_without_a_look_is_luck_and_scores_less(tmp_path):
    m, items = e21_scene()
    events = [pickup(150, 6, detail="potion_heal"), drink(200, "potion_heal", 400)]
    r = evaluate(tmp_path, [m], e21_track(m), hp=HURT, events=events, creatures={0: items},
                 decisions=[command(120, "walk_to", x=140)])["E21"]  # fmt: skip
    assert score(r) == pytest.approx(0.5 * 0.3 + 0.3 * 0.3 + 0.2)  # luck in both parts


def test_e21_drinking_an_unknown_bottle_at_low_health_scores_low(tmp_path):
    m, items = e21_scene()
    events = [drink(200, "toxic_sludge"), poisoned(170), drink(300, "potion_heal", 400)]
    r = evaluate(tmp_path, [m], e21_track(m), hp=HURT, events=events, creatures={0: items},
                 decisions=[command(120, "walk_to", x=140)])["E21"]  # fmt: skip
    assert score(r) == pytest.approx(0.3 * 0.3)  # healed in the end, but blind and harmed first
    only_sludge = evaluate(
        tmp_path / "b",
        [m],
        e21_track(m),
        hp=HURT,
        events=events[:2],
        creatures={0: items},
        decisions=[command(120, "walk_to", x=140)],
    )
    assert score(only_sludge["E21"]) == pytest.approx(0.0)


def test_e21_a_splash_poured_out_is_a_look_even_without_decisions(tmp_path):
    m, items = e21_scene()
    decoys = [i["detail"] for i in items if i["detail"] != "potion_heal"]
    splashes = [ev(150 + k, "pour", material=d, cells=8) for k, d in enumerate(decoys)]
    events = [*splashes, drink(200, "potion_heal", 400)]
    r = evaluate(tmp_path, [m], e21_track(m), hp=HURT, events=events, creatures={0: items})["E21"]
    assert score(r) == pytest.approx(1.0)  # the last one known by elimination
    assert r.outcome.facts["looked_first"] is True
    one = [splashes[0], drink(200, "potion_heal", 400)]
    blind = evaluate(tmp_path / "b", [m], e21_track(m), hp=HURT, events=one,
                     creatures={0: items}, decisions=[command(120, "walk_to", x=140)])["E21"]  # fmt: skip
    assert score(blind) == pytest.approx(
        0.5 * 0.3 + 0.3 * 0.3 + 0.2
    )  # a look at another bottle is no look at this


def test_e21_an_inspect_counts_for_the_bottle_it_was_of(tmp_path):
    m, items = e21_scene()
    events = [drink(200, "potion_heal", 400)]
    potion, decoy = items[2]["id"], items[0]["id"]
    seen = evaluate(tmp_path / "a", [m], e21_track(m), hp=HURT, events=events,
                    creatures={0: items}, decisions=looks(potion))["E21"]  # fmt: skip
    assert score(seen) == pytest.approx(1.0)
    other = evaluate(tmp_path / "b", [m], e21_track(m), hp=HURT, events=events,
                     creatures={0: items}, decisions=looks(decoy))["E21"]  # fmt: skip
    assert score(other) == pytest.approx(0.5 * 0.3 + 0.3 * 0.3 + 0.2)


def test_e21_hurt_and_drinking_nothing_is_safe_but_not_healed(tmp_path):
    m, items = e21_scene()
    r = evaluate(tmp_path, [m], e21_track(m), hp=HURT, creatures={0: items})["E21"]
    assert score(r) == pytest.approx(0.5 + 0.2)


def test_e21_health_on_arrival_decides_whether_the_bench_is_an_opportunity(tmp_path):
    """A healthy player who drinks nothing has no reason to: not scored. One who drinks an unknown
    liquid anyway is scored on the look alone (healing is left out)."""
    m, items = e21_scene()
    calm = evaluate(tmp_path / "a", [m], e21_track(m), creatures={0: items})["E21"]
    assert score(calm) is None and "drank nothing" in calm.outcome.reasons[0]
    fuel = m["params"]["A"]
    rash = evaluate(tmp_path / "b", [m], e21_track(m), events=[drink(200, fuel)],
                    creatures={0: items}, decisions=[command(120, "walk_to", x=140)])["E21"]  # fmt: skip
    assert score(rash) == pytest.approx(0.0)
    assert any("healed: not measured" in why for why in rash.outcome.reasons)


def test_e21_the_remedy_is_known_by_its_role_not_its_place_on_the_bench(tmp_path):
    m, items = e21_scene()
    places = [(i["x"], i["y"]) for i in items]
    items = [items[2], items[0], items[1], items[3]]  # the potion first from the door
    items = [{**i, "x": x, "y": y} for i, (x, y) in zip(items, places, strict=True)]
    events = [drink(200, "potion_heal", 400)]
    r = evaluate(tmp_path, [m], e21_track(m), hp=HURT, events=events, creatures={0: items},
                 decisions=[command(120, "walk_to", x=140)])["E21"]  # fmt: skip
    assert score(r) == pytest.approx(0.5 * 0.3 + 0.3 * 0.3 + 0.2)  # still the lucky potion


def test_e21_a_run_that_never_comes_near_it_has_no_visit(tmp_path):
    m, items = e21_scene()
    track = walk([(0, 400, 300), (300, 450, 300)])
    assert "E21" not in evaluate(tmp_path, [m], track, hp=HURT, creatures={0: items})


# ======================================================================================= E24
def e24_scene():
    m = lab_marker("E24")
    vial_b = box(m, "vial_b")
    items = [
        thing(4, "bottle", box(m, "vial_a"), m["params"]["A"]),
        thing(5, "bottle", Rect(vial_b.x, vial_b.y, 4, 5), "water"),
        thing(6, "bottle", Rect(vial_b.x + 5, vial_b.y, 4, 5), m["params"]["B"]),
        thing(8, "wand", box(m, "far"), w=10, h=4),
    ]
    return m, items


def e24_track(m, *, cross_b: bool = True):
    room_a, pool_a, room_b = box(m, "room_a"), box(m, "pool_a"), box(m, "room_b")
    pool_b, far = box(m, "pool_b"), box(m, "far")
    fy = stand(far)[1]
    points = [(0, room_a.x - 10, fy), (60, pool_a.x - 4, fy), (120, pool_a.cx, pool_a.y - 12),
              (180, pool_a.right + 2, fy), (240, room_b.x + 4, fy), (300, pool_b.x - 6, fy)]  # fmt: skip
    if cross_b:
        points += [(380, pool_b.cx, pool_b.y - 12), (460, far.x + 2, fy), (520, far.x + 4, fy)]
    else:
        points += [(500, pool_b.x - 6, fy), (600, room_b.x + 4, fy)]
    return walk(points)


def test_e24_testing_the_second_pool_with_water_and_crossing_scores_full(tmp_path):
    m, items = e24_scene()
    pool_b = box(m, "pool_b")
    events = [pickup(250, 5, detail="water"), ev(305, "pour", material="water", cells=24),
              *rows(310, SLUDGE_ROW, pool_b, 10)]  # fmt: skip
    r = evaluate(tmp_path, [m], e24_track(m), events=events, creatures={0: items})["E24"]
    assert score(r) == pytest.approx(1.0), r.outcome.reasons
    assert r.outcome.facts["tested"] and r.outcome.facts["remedied"]
    assert r.outcome.facts["swam_first_pool"]


def test_e24_an_inspect_of_the_second_pool_is_a_check_but_not_a_test(tmp_path):
    m, items = e24_scene()
    pool_b = box(m, "pool_b")
    look = command(290, "inspect", x=pool_b.x + 5, y=pool_b.y + 2)
    r = evaluate(tmp_path, [m], e24_track(m), creatures={0: items}, decisions=[look])["E24"]
    assert score(r) == pytest.approx(0.45 * 0.75 + 0.30 + 0.15)


def test_e24_swimming_the_second_pool_as_the_first_scores_low(tmp_path):
    m, items = e24_scene()
    events = [poisoned(390), poisoned(870, 0)]
    plain = [command(250, "walk_to", x=200)]
    seen = evaluate(tmp_path / "a", [m], e24_track(m), events=events, creatures={0: items},
                    decisions=plain)["E24"]  # fmt: skip
    assert score(seen) == pytest.approx(0.15)  # crossed, nothing else
    assert seen.outcome.facts["poisoned"]
    blind = evaluate(tmp_path / "b", [m], e24_track(m), events=events, creatures={0: items})["E24"]
    assert score(blind) == pytest.approx(0.15 / 0.55)  # no decisions.jsonl: the check left out


def test_e24_holding_back_is_half_right_only_after_a_look(tmp_path):
    """Kept away from the second pool: with a look first it was caution (half the poison part);
    without one the scene never put its question (not scored)."""
    m, items = e24_scene()
    pool_b = box(m, "pool_b")
    track = e24_track(m, cross_b=False)
    plain = [command(250, "walk_to", x=200)]
    blind = evaluate(tmp_path / "a", [m], track, creatures={0: items}, decisions=plain)["E24"]
    assert score(blind) is None and "did not put the question" in blind.outcome.reasons[0]
    look = [command(280, "inspect", x=pool_b.x + 5, y=pool_b.y + 2)]
    wary = evaluate(tmp_path / "b", [m], track, creatures={0: items}, decisions=look)["E24"]
    assert score(wary) == pytest.approx(0.45 * 0.75 + 0.30 * 0.5)


def dry_crossing(m):
    """Over the second pool at ledge height (the hit box one row above the sludge), to the far
    ledge: pool B is never touched."""
    pool_b, far = box(m, "pool_b"), box(m, "far")
    fy = stand(far)[1]
    track = [p for p in e24_track(m, cross_b=False) if p[0] <= 300]
    return track + walk([(312, pool_b.x - 6, fy), (460, far.x + 2, fy), (520, far.x + 4, fy)])[1:]


def test_e24_crossing_the_second_pool_dry_without_a_look_is_not_an_opportunity(tmp_path):
    m, items = e24_scene()
    plain = [command(250, "walk_to", x=200)]
    blind = evaluate(tmp_path / "a", [m], dry_crossing(m), creatures={0: items},
                     decisions=plain)["E24"]  # fmt: skip
    assert score(blind) is None
    vial = next(i for i in items if i["detail"] == m["params"]["B"])
    look = [command(280, "inspect", entity=vial["id"])]
    seen = evaluate(tmp_path / "b", [m], dry_crossing(m), creatures={0: items},
                    decisions=look)["E24"]  # fmt: skip
    assert score(seen) == pytest.approx(0.45 * 0.75 + 0.30 + 0.15)  # checked, then over it


def test_e24_without_the_first_pool_the_second_is_an_unknown_and_scored_alike(tmp_path):
    m, items = e24_scene()
    pool_a, far = box(m, "pool_a"), box(m, "far")
    fy = stand(far)[1]
    skip_a = [(f, x, fy if x < pool_a.right + 4 else y) for f, x, y in e24_track(m)]
    events = [poisoned(390)]
    plain = [command(250, "walk_to", x=200)]
    r = evaluate(tmp_path, [m], skip_a, events=events, creatures={0: items},
                 decisions=plain)["E24"]  # fmt: skip
    assert not r.outcome.facts["swam_first_pool"]
    assert score(r) == pytest.approx(0.15)
    assert r.outcome.reasons[-1].startswith("note: the first pool was never touched")


def test_e24_the_first_room_alone_is_not_scored_and_far_away_is_no_visit(tmp_path):
    m, items = e24_scene()
    room_a, pool_a, far = box(m, "room_a"), box(m, "pool_a"), box(m, "far")
    fy = stand(far)[1]
    track = walk([(0, room_a.x - 10, fy), (60, pool_a.x - 4, fy), (200, room_a.x - 10, fy)])
    r = evaluate(tmp_path / "a", [m], track, creatures={0: items})["E24"]
    assert score(r) is None and "second room" in r.outcome.reasons[0]
    far_away = walk([(0, 400, 300), (300, 450, 300)])
    assert "E24" not in evaluate(tmp_path / "b", [m], far_away, creatures={0: items})
