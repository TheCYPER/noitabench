"""Capability scores, the depth score, the composite and the rubric arithmetic."""

from __future__ import annotations

import pytest
from eval_runs import box, lab_marker, walk, write_run
from noitabench.eval.context import Visit
from noitabench.eval.encounters import Result
from noitabench.eval.geometry import Rect
from noitabench.eval.metrics import Metric
from noitabench.eval.recording import load_run
from noitabench.eval.rubric import Outcome, Rubric, linear
from noitabench.eval.scoring import capability_scores, composite, depth_score, discount
from noitabench.eval.worldinfo import Scene


def result(eid: str, score: float | None, x: int = 0) -> Result:
    rect = Rect(x, 0, 10, 10)
    scene = Scene(eid, 0, False, True, 1, "t", {}, rect, rect, {}, x, 0)
    return Result(Visit(scene, ((0, 1),)), Outcome(score, [], {}))


def metric(name: str, caps: tuple[str, ...], value: float | None, n: int = 1) -> Metric:
    return Metric(name, caps, value, n)


# ---------------------------------------------------------------------------------- rubric
def test_rubric_is_the_weighted_mean_of_the_measured_parts():
    r = Rubric()
    r.add("a", 0.5, 1.0, "yes")
    r.add("b", 0.3, 0.0, "no")
    r.add("c", 0.2, None, "cannot tell")
    assert r.score() == pytest.approx(0.5 / 0.8)
    assert r.reasons()[2].startswith("c: not measured")


def test_rubric_with_nothing_measured_has_no_score():
    r = Rubric()
    r.add("a", 1.0, None, "?")
    assert r.score() is None


def test_linear_runs_between_good_and_bad_in_either_direction():
    assert linear(0, 0, 50) == 1.0 and linear(50, 0, 50) == 0.0 and linear(25, 0, 50) == 0.5
    assert linear(1, 1, 6) == 1.0 and linear(9, 1, 6) == 0.0
    assert linear(500, 600, 3600) == 1.0
    assert linear(10, 50, 0) == pytest.approx(0.2)  # good above bad


# ------------------------------------------------------------------------------ capabilities
def test_a_capability_is_the_weighted_mean_of_visits_and_metrics():
    # E16 is N7 main (weight 1) and N9 second (0.5); E22 is N9 main (weight 1)
    results = [result("E16", 1.0), result("E22", 0.4, x=50)]
    metrics = [metric("low_hp_discipline", ("N9",), 0.0)]
    caps = capability_scores(results, metrics)
    # N9: E22 1 x 0.4, E16 0.5 x 1.0, metric 1 x 0.0
    assert caps["N9"].score == pytest.approx(100 * (0.4 + 0.5 + 0.0) / 2.5)
    assert caps["N9"].opportunities == 3 and caps["N9"].covered
    assert [e["role"] for e in caps["N9"].encounters] == ["secondary", "main"]


def test_fewer_than_two_opportunities_keeps_the_score_but_is_not_covered():
    caps = capability_scores([result("E08", 1.0)], [])
    assert caps["N4"].score == pytest.approx(100.0)
    assert caps["N4"].opportunities == 1 and not caps["N4"].covered
    assert "coverage too low" in caps["N4"].note


def test_a_metric_counts_its_trials_as_opportunities():
    caps = capability_scores([], [metric("repeat_harm", ("N1",), 0.5, n=3)])
    assert caps["N1"].covered and caps["N1"].opportunities == 3
    assert caps["N1"].score == pytest.approx(50.0)


def test_an_unscored_visit_and_an_unmeasured_metric_add_nothing():
    caps = capability_scores([result("E04", None)], [metric("x", ("N2",), None, n=5)])
    assert caps["N2"].score is None and caps["N2"].opportunities == 0 and not caps["N2"].covered


def test_the_combined_capability_is_the_mean_of_its_scored_parts():
    results = [result("E07", 0.5), result("E06", 1.0, x=40)]
    metrics = [metric("layer_completion", ("C2",), 1.0, n=2)]
    caps = capability_scores(results, metrics)
    c = caps["C"]
    assert c.parts["C1"].score == pytest.approx(50.0)  # E07 feeds C1
    assert c.parts["C2"].score == pytest.approx(100.0)
    assert c.parts["C3"].score == pytest.approx(100.0)  # E06 feeds C3
    assert c.parts["C4"].score is None  # needs two games
    assert c.score == pytest.approx((50 + 100 + 100) / 3)
    assert c.covered and c.opportunities == 4


# ------------------------------------------------------------------------------------ discount
def test_the_discount_is_n_over_n_plus_two():
    assert discount(0) == 0.0
    assert discount(1) == pytest.approx(1 / 3)
    assert discount(2) == pytest.approx(1 / 2)
    assert discount(5) == pytest.approx(5 / 7)
    assert discount(-3) == 0.0


def test_a_capability_reports_its_discount_and_what_it_counts_for():
    caps = capability_scores([result("E08", 1.0)], [metric("x", ("N1",), 0.6, n=4)])
    n4, n1, n2 = caps["N4"].as_dict(), caps["N1"].as_dict(), caps["N2"].as_dict()
    assert n4["opportunities"] == 1 and n4["covered"] is False
    assert n4["score"] == 100.0 and n4["discount"] == pytest.approx(1 / 3, abs=1e-4)
    assert n4["discounted_score"] == pytest.approx(100 / 3, abs=0.01)
    assert n1["discount"] == pytest.approx(4 / 6, abs=1e-4)
    assert n1["discounted_score"] == pytest.approx(60 * 4 / 6, abs=0.01)
    assert n2["score"] is None and n2["discount"] == 0.0 and n2["discounted_score"] == 0.0


def test_the_combined_capability_has_a_discount_but_its_parts_do_not():
    caps = capability_scores([result("E07", 0.5), result("E06", 1.0, x=40)], [])
    c = caps["C"].as_dict()
    assert c["opportunities"] == 2 and c["discount"] == pytest.approx(0.5)
    assert c["discounted_score"] == pytest.approx(0.5 * (50 + 100) / 2, abs=0.01)
    assert all("discount" not in part for part in c["parts"].values())


# --------------------------------------------------------------------------------- composite
def test_composite_is_80_percent_of_the_discounted_mean_and_20_percent_depth():
    results = [result("E08", 1.0), result("E12", 0.5, x=30)]  # N4: E08 main; N5: E12 main, E08 2nd
    metrics = [metric("backtracking", ("N3",), 0.5, n=2), metric("repeat_harm", ("N1",), 1.0, n=2)]
    caps = capability_scores(results, metrics)
    out = composite(caps, {"score": 40.0})
    assert set(out["covered"]) == {"N1", "N3", "N5"}  # N4 has one opportunity: not covered
    assert "N4" in out["left_out"] and "N2" in out["left_out"]
    expected = sum(c.score * c.opportunities / (c.opportunities + 2)
                   for c in caps.values() if c.score is not None) / 11  # fmt: skip
    assert out["ability_mean"] == pytest.approx(expected, abs=0.01)
    assert out["composite"] == pytest.approx(0.8 * expected + 0.2 * 40, abs=0.01)
    plain = sum(c.score for c in caps.values() if c.score is not None) / 4
    assert out["ability_raw_mean"] == pytest.approx(plain, abs=0.01)


def test_composite_by_hand_with_the_discount_and_the_combined_capability():
    """Every number below is worked out by hand from capability graph sections 3 to 5.

    N1: E07 is its second node (0.5 x 0.6) and repeat_harm one metric (0.8): (0.8 + 0.3) / 1.5,
        3 opportunities (one visit and two trials): counts 2/3 x 73.33 x 3/5.
    N3: E06 and E07 are main nodes (0.5, 0.6), backtracking is a metric (0.9): 2.0 / 3, n = 3.
    N5: E06 is its second node (0.5 x 0.5), route_efficiency a metric (0.7): 0.95 / 1.5, n = 2.
    C1: E07 (0.6) and layer_end_hp (1.0); C3: E06 (0.5); C2 and C4 have nothing: C = (80 + 50) / 2,
        n = 4.
    The other seven capabilities were never met and count 0; the sum of the four that count is
    divided by 11, and depth 40 gives the other 20 %."""
    results = [result("E07", 0.6), result("E06", 0.5, x=40)]
    metrics = [
        metric("repeat_harm", ("N1",), 0.8, n=2),
        metric("backtracking", ("N3",), 0.9, n=1),
        metric("route_efficiency", ("N5",), 0.7, n=1),
        metric("layer_end_hp", ("C1",), 1.0, n=2),
    ]
    caps = capability_scores(results, metrics)
    assert caps["N1"].score == pytest.approx(100 * 1.1 / 1.5) and caps["N1"].opportunities == 3
    assert caps["N3"].score == pytest.approx(100 * 2.0 / 3) and caps["N3"].opportunities == 3
    assert caps["N5"].score == pytest.approx(100 * 0.95 / 1.5) and caps["N5"].opportunities == 2
    assert caps["C"].parts["C1"].score == pytest.approx(80.0)
    assert caps["C"].parts["C3"].score == pytest.approx(50.0)
    assert caps["C"].score == pytest.approx(65.0) and caps["C"].opportunities == 4
    out = composite(caps, {"score": 40.0})
    assert out["covered"] == ["C", "N1", "N3", "N5"]
    total = 100 * 1.1 / 1.5 * 3 / 5 + 100 * 2 / 3 * 3 / 5 + 100 * 0.95 / 1.5 * 2 / 4 + 65.0 * 4 / 6
    assert out["ability_mean"] == pytest.approx(total / 11, abs=0.005)
    assert out["composite"] == pytest.approx(0.8 * total / 11 + 0.2 * 40, abs=0.005)
    assert total == pytest.approx(44 + 40 + 31.6667 + 43.3333, abs=0.001)  # 159
    assert out["composite"] == pytest.approx(19.56, abs=0.005)


def test_exactly_two_opportunities_cover_a_capability_and_one_does_not():
    two = capability_scores([result("E08", 1.0)], [metric("x", ("N4",), 0.0, n=1)])
    assert two["N4"].covered and two["N4"].opportunities == 2
    assert two["N4"].score == pytest.approx(100 * (1.0 + 0.0) / 2)
    one = capability_scores([result("E08", 1.0)], [])
    assert not one["N4"].covered and composite(one, {"score": 0.0})["covered"] == []


def test_a_capability_met_once_still_counts_a_third_of_its_score():
    one = capability_scores([result("E08", 1.0)], [])
    out = composite(one, {"score": 0.0})
    assert one["N4"].opportunities == one["N5"].opportunities == 1  # E08: N4 main, N5 second
    assert out["covered"] == []
    assert out["composite"] == pytest.approx(0.8 * 2 * (100 / 3) / 11, abs=0.01)  # not 0


def test_meeting_little_cannot_beat_a_longer_imperfect_play():
    """The reason for the discount: under the first rule (uncovered capabilities left out, the
    rest re-weighted) a perfect first scene or two scored above a long descent that was merely
    good. Now each capability counts for what it was met for."""
    short = capability_scores([], [metric("repeat_harm", ("N1",), 1.0, n=2)])  # perfect, n = 2
    long_run = capability_scores(
        [],
        [metric(f"m{i}", (f"N{i}",), 0.5, n=4) for i in range(1, 11)],  # half, ten, n = 4
    )
    a = composite(short, {"score": 20.0})
    b = composite(long_run, {"score": 20.0})
    assert a["ability_raw_mean"] == 100.0 and b["ability_raw_mean"] == 50.0  # the old measure
    assert b["composite"] > a["composite"]
    assert a["composite"] == pytest.approx(0.8 * 50 / 11 + 4, abs=0.01)
    assert b["composite"] == pytest.approx(0.8 * (10 * 50 * 4 / 6) / 11 + 4, abs=0.01)


def test_more_opportunities_never_lower_the_composite():
    totals = []
    for n in range(1, 9):
        caps = capability_scores([], [metric("repeat_harm", ("N1",), 0.7, n=n)])
        totals.append(composite(caps, {"score": 30.0})["composite"])
    assert totals == sorted(totals) and totals[0] < totals[-1]


def test_the_depth_share_is_a_fifth_whatever_the_ability():
    caps = capability_scores([], [metric("repeat_harm", ("N1",), 0.5, n=2)])
    ability = 0.8 * (50 * 2 / 4) / 11
    assert composite(caps, {"score": 100.0})["composite"] == pytest.approx(ability + 20, abs=0.01)
    assert composite(caps, {"score": 0.0})["composite"] == pytest.approx(ability, abs=0.01)


def test_composite_with_nothing_scored_is_the_depth_share_alone():
    caps = capability_scores([], [])
    out = composite(caps, {"score": 50.0})
    assert out["ability_mean"] == 0.0 and out["ability_raw_mean"] is None
    assert out["composite"] == pytest.approx(10.0)
    assert "ability share counts as 0" in out["note"]


# ----------------------------------------------------------------------------------- depth
def test_depth_runs_from_the_start_to_the_floor_of_the_sealed_room(tmp_path):
    seal = {"x": 400, "y": 1574, "w": 16, "h": 6, "room": {"x": 376, "y": 1580, "w": 136, "h": 56}}
    track = walk([(0, 150, 77), (600, 150, 800)])
    run = load_run(write_run(tmp_path / "a", track=track, seal=seal))
    d = depth_score(run)
    assert d["bottom_y"] == 1636 and d["start_y"] == 93
    assert d["score"] == pytest.approx(100 * (816 - 93) / (1636 - 93), abs=0.05)
    assert not d["reached_sealed_room"]
    deep = walk([(0, 150, 77), (900, 400, 1610)])
    d = depth_score(load_run(write_run(tmp_path / "b", track=deep, seal=seal)))
    assert d["score"] > 99 and d["reached_sealed_room"]


SEAL = {"x": 436, "y": 1574, "w": 16, "h": 6, "room": {"x": 376, "y": 1580, "w": 136, "h": 56}}


def test_a_tunnel_dug_past_the_vault_does_not_count_below_the_seal(tmp_path):
    """The digger can open a shaft beside the vault down to the bottom row of the world; with
    the plug intact that is no depth: it is capped at the top edge of the plug."""
    track = walk([(0, 150, 77), (800, 300, 1500), (1000, 300, 1640)])  # x 300 is outside the room
    d = depth_score(load_run(write_run(tmp_path / "a", track=track, seal=SEAL)))
    assert d["deepest_raw_y"] == 1656 and d["deepest_y"] == 1574 and d["capped_at_seal"]
    assert not d["reached_sealed_room"]
    assert d["score"] == pytest.approx(100 * (1574 - 93) / (1636 - 93), abs=0.05)
    assert d["score"] < 97


def test_standing_on_the_plug_counts_up_to_its_top_edge(tmp_path):
    track = walk([(0, 150, 77), (600, 440, 1558)])  # feet at 1574, on the plug
    d = depth_score(load_run(write_run(tmp_path / "a", track=track, seal=SEAL)))
    assert d["deepest_y"] == 1574 and not d["capped_at_seal"]
    assert d["score"] == pytest.approx(100 * (1574 - 93) / (1636 - 93), abs=0.05)


def test_going_through_the_plug_into_the_room_counts_down_to_the_floor(tmp_path):
    track = walk([(0, 150, 77), (600, 440, 1500), (700, 440, 1560), (760, 440, 1620)])
    d = depth_score(load_run(write_run(tmp_path / "a", track=track, seal=SEAL)))
    assert d["reached_sealed_room"] and not d["capped_at_seal"]
    assert d["deepest_y"] == 1636 and d["score"] == 100.0


def test_a_shaft_beside_the_vault_and_a_visit_to_the_room_count_only_the_room_samples(tmp_path):
    """Deep outside the room (cheated) and then inside it (opened): the samples outside the room
    below the plug add nothing; the ones inside count."""
    track = walk([(0, 150, 77), (600, 300, 1640), (700, 300, 1500), (800, 440, 1500),
                  (900, 440, 1580)])  # fmt: skip
    d = depth_score(load_run(write_run(tmp_path / "a", track=track, seal=SEAL)))
    assert d["reached_sealed_room"]
    assert d["deepest_raw_y"] == 1656 and d["deepest_y"] == 1596  # the last sample, in the room
    assert d["score"] == pytest.approx(100 * (1596 - 93) / (1636 - 93), abs=0.05)


def test_a_world_without_a_seal_room_caps_nothing(tmp_path):
    seal = {"x": 436, "y": 1574, "w": 16, "h": 6}  # no room box: an older world file
    track = walk([(0, 150, 77), (600, 300, 1500)])
    d = depth_score(load_run(write_run(tmp_path / "a", track=track, seal=seal)))
    assert not d["capped_at_seal"] and d["deepest_y"] == d["deepest_raw_y"] == 1516


def test_standing_still_scores_zero_depth(tmp_path):
    run = load_run(write_run(tmp_path / "a", track=walk([(0, 150, 77), (300, 150, 77)])))
    assert depth_score(run)["score"] == 0.0


def test_a_scene_marker_helper_gives_real_regions():
    m = lab_marker("E02")
    assert box(m, "river").w == 30
