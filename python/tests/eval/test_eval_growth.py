"""Cross-game growth: the formula, the metrics against game 1 of a family folder, the cache of
game 1, and the refusals (design `research/2026-10-28-cross-game-design.md`)."""

from __future__ import annotations

import json
import random
from types import SimpleNamespace

import pytest
from eval_runs import walk, write_run
from family_runs import GAME_1, GAME_3, SEAL, example_family, make_game, metrics_of
from noitabench.eval import evaluate_run
from noitabench.eval.depth import deepest, depth_curve, depth_score, reach_frame
from noitabench.eval.metrics import growth
from noitabench.eval.metrics.growth import (
    GROWTH_METRICS,
    Baseline,
    bounded_gain,
    cost_gain,
    growth_value,
)
from noitabench.eval.recording import load_run


# ------------------------------------------------------------------------------ the formula
def test_the_worked_example_of_the_design():
    # E02 0.40 -> 0.85: 0.45 / 0.60; E16 1.00 -> 1.00 skipped; E08 0.60 -> 0.30: -0.30 / 0.60
    gains = [bounded_gain(0.40, 0.85), bounded_gain(1.0, 1.0), bounded_gain(0.60, 0.30)]
    assert gains == [pytest.approx(0.75), None, pytest.approx(-0.5)]
    kept = [g for g in gains if g is not None]
    assert growth_value(kept) == pytest.approx(0.5625)
    assert growth_value([bounded_gain(0.30, 0.65)]) == pytest.approx(0.75)  # depth 30 -> 65
    assert growth_value([cost_gain(80, 40)]) == pytest.approx(0.75)  # HP lost
    assert growth_value([cost_gain(200, 120)]) == pytest.approx(0.70)  # decisions spent


def test_the_formula_edge_cases():
    assert bounded_gain(1.0, 1.0) is None  # nothing to gain, nothing to lose
    assert bounded_gain(0.0, 0.0) == 0.0
    assert bounded_gain(0.0, 0.4) == pytest.approx(0.4)  # all of the room is 1; 0.4 of it used
    assert bounded_gain(0.0, 1.0) == pytest.approx(1.0)
    assert bounded_gain(0.8, 0.2) == pytest.approx(-0.75)  # three quarters of game 1's lost
    assert bounded_gain(1.0, 0.0) == pytest.approx(-1.0)
    assert bounded_gain(0.5, 0.5) == 0.0
    assert cost_gain(0, 0) == 0.0  # both free
    assert cost_gain(0, 30) == pytest.approx(-1.0)  # lost nothing, then lost
    assert cost_gain(30, 0) == pytest.approx(1.0)
    assert cost_gain(50, 50) == 0.0
    assert cost_gain(40, 60) == pytest.approx(-20 / 60)
    assert growth_value([-1.0]) == 0.0 and growth_value([1.0]) == 1.0
    assert growth_value([0.0]) == 0.5  # no change is half, not zero


def result(eid: str, score: float | None):
    scene = SimpleNamespace(eid=eid)
    return SimpleNamespace(visit=SimpleNamespace(scene=scene), outcome=SimpleNamespace(score=score))


def baseline(scenes: dict[str, float]) -> Baseline:
    return Baseline("run-01", None, scenes, [], 0.0)  # type: ignore[arg-type]


def test_cross_game_gain_counts_the_scenes_scored_in_both_games():
    base = baseline({"E02": 0.40, "E16": 1.0, "E08": 0.60, "E23": 0.5})
    mine = [
        result("E02", 0.85),
        result("E16", 1.0),
        result("E08", 0.30),
        result("E10", 0.9),  # not in game 1
        result("E23", None),  # visited, not scored
    ]
    m = growth._gain(base, mine)  # type: ignore[arg-type]
    assert m.name == "cross_game_gain" and m.capabilities == ("N2",)
    assert m.value == pytest.approx(0.5625) and m.opportunities == 2  # E16 is no opportunity
    by_id = {s["id"]: s for s in m.detail["scenes"]}
    assert by_id["E02"] == {"id": "E02", "game_1": 0.4, "this_game": 0.85, "g": 0.75}
    assert by_id["E16"]["g"] is None
    assert by_id["E08"]["g"] == -0.5
    assert m.detail["only_game_1"] == ["E23"] and m.detail["only_this_game"] == ["E10"]
    assert m.detail["mean_g"] == 0.125


def test_a_scene_met_twice_counts_once_by_its_mean():
    base = baseline({"E08": 0.4})
    mine = [result("E08", 0.8), result("E08", 0.6)]
    m = growth._gain(base, mine)  # type: ignore[arg-type]
    assert m.opportunities == 1
    assert m.detail["scenes"][0]["this_game"] == 0.7  # the mean of 0.8 and 0.6
    assert m.value == pytest.approx((1 + 0.3 / 0.6) / 2)


def test_cross_game_gain_needs_a_scene_in_both_games_and_one_that_was_not_perfect():
    none = growth._gain(baseline({"E02": 0.5}), [result("E10", 0.5)])  # type: ignore[arg-type]
    assert none.value is None and "both games" in none.reason
    perfect = growth._gain(baseline({"E02": 1.0}), [result("E02", 1.0)])  # type: ignore[arg-type]
    assert perfect.value is None and "perfect" in perfect.reason


def test_game_three_against_game_one_is_the_design_example(tmp_path):
    fam = example_family(tmp_path)
    profile = evaluate_run(fam / "run-03")
    m = metrics_of(profile)
    assert m["growth_depth"]["value"] == pytest.approx(0.75, abs=1e-3)
    assert m["growth_harm"]["value"] == pytest.approx(0.75, abs=1e-3)
    assert m["growth_pace"]["value"] == pytest.approx(0.70, abs=1e-3)
    assert m["cross_game_gain"]["status"] == "not_measured"  # no encounter met in either game
    assert all(m[n]["opportunities"] == 1 for n in ("growth_depth", "growth_harm", "growth_pace"))
    c4 = profile["capabilities"]["C"]["parts"]["C4"]
    assert c4["score"] == pytest.approx(100 * (0.75 + 0.75 + 0.70) / 3, abs=0.1)  # 73.3
    assert c4["opportunities"] == 3 and c4["covered"]
    # the numbers it was made of are in the detail
    d = m["growth_depth"]["detail"]
    assert d["baseline"] == "run-01" and d["game_1"] == 30.0 and d["this_game"] == 65.0
    h = m["growth_harm"]["detail"]
    assert h["shared_depth"] == 30.0
    assert h["game_1"]["hp_lost"] == 80.0 and h["this_game"]["hp_lost"] == 40.0
    assert h["game_1"]["frame"] == 600.0 and h["this_game"]["frame"] == pytest.approx(
        553.8, abs=0.1
    )
    p = m["growth_pace"]["detail"]
    assert p["game_1"]["decisions"] == 200 and p["this_game"]["decisions"] == 120


def test_a_repeat_of_game_one_is_no_change(tmp_path):
    m = metrics_of(evaluate_run(example_family(tmp_path) / "run-02"))
    for name in ("growth_depth", "growth_harm", "growth_pace"):
        assert m[name]["value"] == 0.5, name


def test_game_one_and_a_run_outside_a_family_have_nothing_to_compare_with(tmp_path):
    fam = example_family(tmp_path)
    first = metrics_of(evaluate_run(fam / "run-01"))
    assert set(first) == set(GROWTH_METRICS)
    for m in first.values():
        assert m["status"] == "not_measured" and "game 1" in m["reason"] and m["opportunities"] == 0
    single = make_game(tmp_path / "solo", **GAME_3)
    for m in metrics_of(evaluate_run(single)).values():
        assert m["status"] == "not_measured" and "family folder" in m["reason"]


def test_a_game_without_growth_scores_what_it_scored_before(tmp_path):
    """Growth metrics that are not measured change no capability and no composite."""
    solo = evaluate_run(make_game(tmp_path / "solo", **GAME_3))
    assert solo["capabilities"]["C"]["parts"]["C4"]["score"] is None
    assert "cross_game_gain" not in {m["name"] for m in solo["capabilities"]["N2"]["metrics"]}
    fam = example_family(tmp_path)
    one, three = evaluate_run(fam / "run-01"), evaluate_run(fam / "run-03")
    assert one["capabilities"]["C"]["parts"]["C4"]["score"] is None
    assert three["capabilities"]["C"]["parts"]["C4"]["score"] is not None
    assert three["ability_mean"] > solo["ability_mean"]  # C4 now counts in C
    assert three["composite"] > solo["composite"]


def test_games_that_differ_in_model_or_rule_seed_are_not_compared(tmp_path):
    fam = tmp_path / "fam"
    make_game(fam / "run-01", **GAME_1)
    make_game(fam / "run-02", **{**GAME_3, "model": {"provider": "fake", "model": "other"}})
    make_game(fam / "run-03", **{**GAME_3, "rule_seed": 5})
    make_game(fam / "run-04", **{**GAME_3, "model": None})
    for name, needle in (("run-02", "fake/m"), ("run-03", "rule seed"), ("run-04", "no model")):
        m = metrics_of(evaluate_run(fam / name))
        for n in GROWTH_METRICS:
            assert m[n]["status"] == "not_measured", (name, n)
            assert "not comparable" in m[n]["reason"] and needle in m[n]["reason"], (name, n)


def test_an_unreadable_game_one_is_said_so(tmp_path):
    fam = example_family(tmp_path)
    (fam / "run-01" / "entities.jsonl").unlink()
    m = metrics_of(evaluate_run(fam / "run-03"))
    for n in GROWTH_METRICS:
        assert m[n]["status"] == "not_measured" and "cannot be read" in m[n]["reason"]


def test_the_lowest_run_folder_is_game_one(tmp_path):
    fam = tmp_path / "fam"
    make_game(fam / "run-02", **GAME_1)
    make_game(fam / "run-03", **GAME_3)
    assert metrics_of(evaluate_run(fam / "run-02"))["growth_depth"]["status"] == "not_measured"
    m = metrics_of(evaluate_run(fam / "run-03"))
    assert m["growth_depth"]["status"] == "measured"
    assert m["growth_depth"]["detail"]["baseline"] == "run-02"


def test_a_gap_in_the_numbering_changes_nothing(tmp_path):
    """Game 1 is the lowest `run-NN`, wherever the others are (a lost or deleted run-02)."""
    fam = tmp_path / "fam"
    make_game(fam / "run-01", **GAME_1)
    make_game(fam / "run-03", **GAME_3)
    make_game(fam / "run-07", **GAME_3)
    for name in ("run-03", "run-07"):
        m = metrics_of(evaluate_run(fam / name))
        assert m["growth_depth"]["detail"]["baseline"] == "run-01", name
        assert m["growth_pace"]["value"] == pytest.approx(0.70, abs=1e-3), name


def test_a_shared_stretch_under_five_points_is_not_compared_for_harm_and_pace(tmp_path):
    fam = tmp_path / "fam"
    make_game(fam / "run-01", depth=3.0, frames=100, decisions=(0, 10))
    make_game(fam / "run-02", depth=40.0, frames=400, decisions=(0, 10))
    m = metrics_of(evaluate_run(fam / "run-02"))
    assert m["growth_depth"]["status"] == "measured"
    for name in ("growth_harm", "growth_pace"):
        assert m[name]["status"] == "not_measured" and "shared stretch" in m[name]["reason"]


def test_pace_needs_decisions_in_both_games(tmp_path):
    fam = tmp_path / "fam"
    make_game(fam / "run-01", depth=30.0, frames=300, hurt=((100, 10.0),))
    make_game(fam / "run-02", depth=60.0, frames=600, hurt=((100, 10.0),), decisions=(0, 5))
    m = metrics_of(evaluate_run(fam / "run-02"))
    assert m["growth_harm"]["status"] == "measured" and m["growth_harm"]["value"] == 0.5
    assert m["growth_pace"]["status"] == "not_measured" and "game 1" in m["growth_pace"]["reason"]


def test_pace_needs_decisions_in_this_game_too(tmp_path):
    fam = tmp_path / "fam"
    make_game(fam / "run-01", depth=30.0, frames=300, hurt=((100, 10.0),), decisions=(0, 5))
    make_game(fam / "run-02", depth=60.0, frames=600, hurt=((100, 10.0),))
    m = metrics_of(evaluate_run(fam / "run-02"))
    assert m["growth_harm"]["status"] == "measured"
    assert (
        m["growth_pace"]["status"] == "not_measured" and "this game" in m["growth_pace"]["reason"]
    )


def test_reaching_the_floor_twice_is_no_depth_to_compare(tmp_path):
    fam = tmp_path / "fam"
    make_game(fam / "run-01", depth=100.0, frames=600, x=440, decisions=(0,))
    make_game(fam / "run-02", depth=100.0, frames=500, x=440, decisions=(0,))
    m = metrics_of(evaluate_run(fam / "run-02"))
    assert (
        m["growth_depth"]["status"] == "not_measured"
        and "both games" in m["growth_depth"]["reason"]
    )
    assert m["growth_harm"]["status"] == "measured" and m["growth_harm"]["value"] == 0.5


def test_a_game_that_died_early_is_compared_over_the_stretch_both_walked(tmp_path):
    """Game 3 reached depth 20 with 10 HP lost and 8 decisions, then died; game 1 went to depth 60
    after 50 HP and 60 decisions, 40 of them before depth 20. Over the shared stretch (depth 20)
    the early death is not frugal: the costs to depth 20 are what is compared."""
    fam = tmp_path / "fam"
    make_game(
        fam / "run-01",
        depth=60.0,
        frames=600,
        hurt=((50, 10.0), (100, 10.0), (500, 30.0)),
        decisions=tuple(range(0, 600, 10)),  # 60 decisions; depth 20 at frame 200: 20 before
    )
    make_game(
        fam / "run-02",
        depth=20.0,
        frames=200,
        hurt=((100, 10.0),),
        decisions=tuple(range(0, 200, 25)),  # 8 decisions
    )
    m = metrics_of(evaluate_run(fam / "run-02"))
    h, p = m["growth_harm"]["detail"], m["growth_pace"]["detail"]
    assert h["shared_depth"] == 20.0
    assert h["game_1"]["hp_lost"] == 20.0 and h["this_game"]["hp_lost"] == 10.0
    assert p["game_1"]["decisions"] == 20 and p["this_game"]["decisions"] == 8
    assert m["growth_harm"]["value"] == pytest.approx((1 + 0.5) / 2)
    assert m["growth_pace"]["value"] == pytest.approx((1 + 12 / 20) / 2)


# -------------------------------------------------------------------------- depth over time
def test_the_depth_curve_is_the_depth_score_sample_by_sample(tmp_path):
    seal = {"x": 436, "y": 1574, "w": 16, "h": 6, "room": {"x": 376, "y": 1580, "w": 136, "h": 56}}
    track = walk([(0, 150, 77), (800, 300, 1500), (1000, 300, 1640)])  # a shaft beside the vault
    run = load_run(write_run(tmp_path / "a", track=track, seal=seal))
    curve = depth_curve(run)
    assert len(curve) == len(run.track.samples)
    assert max(d for _f, d in curve) == pytest.approx(depth_score(run)["score"], abs=0.005)
    assert max(d for _f, d in curve) < 97  # capped at the top of the plug
    assert reach_frame(curve, 99.0) is None  # the shaft never opened the seal

    into_room = walk([(0, 150, 77), (600, 440, 1500), (700, 440, 1560), (760, 440, 1620)])
    run2 = load_run(write_run(tmp_path / "b", track=into_room, seal=seal))
    assert depth_score(run2)["score"] == 100.0
    assert reach_frame(depth_curve(run2), 100.0) is not None


def test_the_moment_a_depth_was_reached_is_interpolated_between_the_samples(tmp_path):
    run = load_run(
        write_run(tmp_path / "a", track=walk([(0, 150, 77), (600, 150, 800)]), seal=SEAL)
    )
    curve = depth_curve(run)
    end = curve[-1][1]
    # straight down at a steady pace: half the depth at half the frames, whatever the stride
    assert reach_frame(curve, end / 2) == pytest.approx(300.0, abs=0.01)
    assert reach_frame(curve, end) == pytest.approx(600.0, abs=0.01)
    assert reach_frame(curve, end + 1) is None
    assert reach_frame(curve, 0.0) == 0.0


def test_a_game_reaches_its_own_deepest_point_whatever_the_curve():
    """The shared depth is the lower of two maxima: each game must find it in its own curve, with
    float noise, jumps between samples, and a player who climbs back up."""
    rng = random.Random(7)
    for _ in range(500):
        frames = sorted(rng.sample(range(5000), rng.randint(2, 40)))
        depths = [0.0] + [
            rng.choice([0.0, 100.0, rng.uniform(0, 100), rng.random() ** 3 * 100])
            for _ in frames[1:]
        ]
        curve = list(zip(frames, depths, strict=True))
        top = deepest(curve)
        for level in (top, top * (1 - 1e-12), top / 2):
            at = reach_frame(curve, level)
            assert at is not None and frames[0] <= at <= frames[-1], (level, curve)
        first_at = next(f for f, d in curve if d >= top)
        assert reach_frame(curve, top) <= first_at
        assert reach_frame(curve, top + 1e-3) is None


# --------------------------------------------------------------------------- game 1 is cached
def test_game_one_is_scored_once_for_all_the_later_games(tmp_path, monkeypatch):
    fam = example_family(tmp_path)
    calls = []
    real = growth.evaluate_visits
    monkeypatch.setattr(growth, "evaluate_visits", lambda run: calls.append(run.root) or real(run))
    evaluate_run(fam / "run-02")
    evaluate_run(fam / "run-03")
    assert calls == [fam / "run-01"]
    # a changed recording is read again
    (fam / "run-01" / "events.jsonl").write_text("")
    evaluate_run(fam / "run-03")
    assert len(calls) == 2


def test_game_one_is_read_again_when_its_world_file_changed(tmp_path, monkeypatch):
    fam = example_family(tmp_path)
    calls = []
    real = growth.evaluate_visits
    monkeypatch.setattr(growth, "evaluate_visits", lambda run: calls.append(run.root) or real(run))
    evaluate_run(fam / "run-02")
    path = fam / "run-01" / "world" / "world.json"
    path.write_text(json.dumps(json.loads(path.read_text()), indent=1))  # same world, new bytes
    evaluate_run(fam / "run-03")
    assert len(calls) == 2


def test_only_a_few_games_are_kept(tmp_path):
    for i in range(growth.CACHE_SIZE + 3):
        fam = tmp_path / f"fam{i}"
        make_game(fam / "run-01", **GAME_1)
        make_game(fam / "run-02", **GAME_3)
        evaluate_run(fam / "run-02")
    assert len(growth._CACHE) == growth.CACHE_SIZE
