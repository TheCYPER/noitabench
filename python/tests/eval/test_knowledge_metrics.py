"""N2 notes_accuracy and notes_learned, on hand-made run folders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from eval_runs import box, lab_marker, walk, write_run
from noitabench.eval import evaluate_run
from noitabench.eval.encounters import evaluate_visits
from noitabench.eval.knowledge import build_knowledge, parse_claim
from noitabench.eval.knowledge.claims import FileClaims, NoteClaims, save_note_claims
from noitabench.eval.metrics import Metric, compute_metrics
from noitabench.eval.metrics.knowledge import learnable_facts, player_mixes
from noitabench.eval.recording import load_run

K = build_knowledge(0)
RECIPES = {f.fields["potion"]: f.fields["inputs"] for f in K.of_kind("recipe")}
P1, P2, P3 = list(RECIPES)[:3]


def claim(kind: str, hedged: bool = False, **fields: Any):
    made, why = parse_claim({"kind": kind, "hedged": hedged, "text": "t", **fields})
    assert made is not None, why
    return made


def files(**per_file: list) -> dict[str, FileClaims]:
    return {path: FileClaims("0" * 64, 10, tuple(cs)) for path, cs in per_file.items()}


LAVA = lambda: claim("reaction", a="lava", b="water", out=["rock"])
OIL = lambda: claim("property", material="oil", property="burns")
RECIPE = lambda p, hedged=False: claim("recipe", hedged, potion=p, inputs=RECIPES[p])


def meeting_e16(tmp: Path, events: list | None = None) -> Path:
    """A run that walks up to the acid trough of E16 (a scored visit) with some `mix` events."""
    m = lab_marker("E16", dx=300, dy=300)
    trough = box(m, "trough")
    y = trough.y - 16
    track = walk([(0, trough.x - 80, y), (200, trough.x - 80, y), (400, trough.x - 8, y),
                  (900, trough.x - 8, y)])  # fmt: skip
    return write_run(tmp / "run-02", markers=[m], track=track, events=events or [], decisions=[])


def with_claims(root: Path, *, start=None, end=None, skipped=()) -> Path:
    doc = NoteClaims(
        {"provider": "file", "model": "t"}, start=start, end=end or {}, skipped=list(skipped)
    )
    save_note_claims(doc, root)
    return root


def metrics_of(root: Path) -> dict[str, Metric]:
    run = load_run(root)
    return {m.name: m for m in compute_metrics(run, evaluate_visits(run))}


# ---------------------------------------------------------------------------------- accuracy
def test_accuracy_is_the_weighted_share_of_the_counted_claims(tmp_path):
    root = meeting_e16(tmp_path)
    two_of_three = claim(
        "recipe",
        potion=P1,
        inputs=[*RECIPES[P1][:2], "water" if "water" not in RECIPES[P1] else "coal"],
    )
    end = files(**{
        "notes/a.md": [
            LAVA(),
            OIL(),
            claim("property", material="water", property="burns"),  # wrong
            two_of_three,  # partial
            claim("property", hedged=True, material="oil", property="does_not_burn"),  # hedged
            claim("local"),
            claim("reaction", a="acid", b="oil", out=["air"]),  # unknown
        ],
        "notes/b.md": [OIL()],  # the same statement again: once
    })  # fmt: skip
    with_claims(root, start={}, end=end)
    m = metrics_of(root)["notes_accuracy"]
    assert m.value == pytest.approx((1 + 1 + 0 + 0.5) / 4) and m.opportunities == 1
    assert m.detail == {
        "correct": 2,
        "partial": 1,
        "wrong": 1,
        "hedged": 1,
        "not_judged": 2,
        "nothing_happens": {"right": 0, "wrong": 0},
    }
    assert "2 right, 1 partly, 1 wrong of 4" in m.reason


def test_claims_that_something_does_nothing_stay_out_of_accuracy(tmp_path):
    # almost every triple makes nothing: such lines would be right by default and hide errors
    root = meeting_e16(tmp_path)
    pool = sorted({x for inputs in RECIPES.values() for x in inputs})
    quiet = next(
        t
        for t in ((a, b, c) for a in pool for b in pool for c in pool if a < b < c)
        if sorted(t) not in [sorted(v) for v in RECIPES.values()]
    )
    end = files(**{
        "notes/a.md": [
            claim("property", material="water", property="burns"),  # wrong
            claim("no_recipe", inputs=list(quiet)),  # right, but left out
            claim("no_recipe", inputs=list(RECIPES[P1])),  # wrong, left out too
            claim("no_reaction", a="oil", b="water"),  # right, left out
        ],
    })  # fmt: skip
    with_claims(root, start={}, end=end)
    m = metrics_of(root)["notes_accuracy"]
    assert m.value == 0.0 and "0 right, 0 partly, 1 wrong of 1" in m.reason
    assert m.detail["nothing_happens"] == {"right": 2, "wrong": 1}


def test_told_facts_count_for_accuracy(tmp_path):
    root = meeting_e16(tmp_path)
    told = claim("drink", material="potion_heal", effect="heal")
    assert K.by_id["drink:potion_heal"].told
    with_claims(root, start={}, end=files(**{"notes/a.md": [told]}))
    assert metrics_of(root)["notes_accuracy"].value == 1.0


def test_accuracy_is_not_measured_without_claims_or_a_counted_one(tmp_path):
    root = meeting_e16(tmp_path)
    m = metrics_of(root)
    assert m["notes_accuracy"].value is None and "notes-claims" in m["notes_accuracy"].reason
    assert m["notes_learned"].value is None
    hedged = claim("property", hedged=True, material="oil", property="burns")
    with_claims(root, start={}, end=files(**{"notes/a.md": [claim("local"), hedged]}))
    m = metrics_of(root)["notes_accuracy"]
    assert m.value is None and "no claim" in m.reason


def test_an_incomplete_extraction_is_said(tmp_path):
    root = meeting_e16(tmp_path)
    skipped = [{"section": "end", "path": "notes/b.md", "reason": "x"}]
    with_claims(root, start={}, end=files(**{"notes/a.md": [OIL()]}), skipped=skipped)
    assert "1 file(s) were not extracted" in metrics_of(root)["notes_accuracy"].reason


# ------------------------------------------------------------------------------------ learned
def mixes_at_player(tmp: Path) -> list[dict]:
    m = lab_marker("E16", dx=300, dy=300)
    trough = box(m, "trough")
    x, y = trough.x - 80 + 3, trough.y - 16 + 8  # the player's centre in the first 200 frames
    return [
        {
            "frame": 100,
            "type": "mix",
            "x": int(x + 20),
            "y": int(y),
            "potion": P1,
            "cells": 3,
            "bottle": 1,
        },
        {"frame": 100, "type": "mix", "x": int(x + 400), "y": int(y), "potion": P2},  # far away
    ]


def test_a_mix_counts_only_near_the_player(tmp_path):
    root = meeting_e16(tmp_path, mixes_at_player(tmp_path))
    assert player_mixes(load_run(root)) == {P1}


def test_what_the_game_could_teach_is_the_recipes_made_and_the_lessons_of_scenes_met(tmp_path):
    root = meeting_e16(tmp_path, mixes_at_player(tmp_path))
    run = load_run(root)
    results = evaluate_visits(run)
    assert [r.visit.scene.eid for r in results] == ["E16"] and results[0].outcome.score is not None
    got = learnable_facts(run, results, K)
    # the scene also names "acid harms" and "acid eats water", but only the second is ours:
    # Noita's own acid stays common knowledge, correct when written and never a thing learned
    assert sorted(got) == sorted([f"recipe:{P1}", "reaction:r04"])
    assert K.by_id["property:acid:harms_on_contact"].encounters == ("E16",)
    assert K.by_id["property:acid:harms_on_contact"].tier == "common"
    assert learnable_facts(run, [], K) == [f"recipe:{P1}"]  # without the scene
    for fid in got:
        assert not K.by_id[fid].told and K.by_id[fid].tier in ("seed", "game")


def test_learned_is_the_share_of_those_things_that_the_final_notes_hold(tmp_path):
    root = meeting_e16(tmp_path, mixes_at_player(tmp_path))
    end = files(**{
        "notes/a.md": [
            RECIPE(P1),
            claim("property", material="acid", property="harms_on_contact"),  # Noita's: not new
            RECIPE(P3),  # right, but P3 was never made: listed, not scored
            OIL(),  # Noita's, and a lesson of scenes the run never met
        ]
    })  # fmt: skip
    with_claims(root, start={}, end=end)
    m = metrics_of(root)["notes_learned"]
    assert m.value == pytest.approx(1 / 2) and m.opportunities == 2
    assert m.detail["learned"] == {f"recipe:{P1}": 1.0, "reaction:r04": 0.0}
    assert m.detail["written_without_meeting"] == [f"recipe:{P3}"]
    assert "1 of 2" in m.reason
    both = end["notes/a.md"].claims + (
        claim("reaction", a="acid", b="water", out=["flammable_gas", "air"]),
    )
    with_claims(root, start={}, end=files(**{"notes/a.md": list(both)}))
    assert metrics_of(root)["notes_learned"].value == 1.0


def test_a_partly_right_note_earns_half_and_a_hedged_one_nothing(tmp_path):
    root = meeting_e16(tmp_path, mixes_at_player(tmp_path))
    near = claim("recipe", potion=P1, inputs=RECIPES[P1][:2])  # two of three
    hedged = RECIPE(P1, hedged=True)
    with_claims(root, start={}, end=files(**{"notes/a.md": [near]}))
    assert metrics_of(root)["notes_learned"].detail["learned"][f"recipe:{P1}"] == 0.5
    with_claims(root, start={}, end=files(**{"notes/a.md": [hedged]}))
    assert metrics_of(root)["notes_learned"].detail["learned"][f"recipe:{P1}"] == 0.0


def test_what_the_start_notebook_already_held_correctly_is_not_a_thing_learned(tmp_path):
    root = meeting_e16(tmp_path, mixes_at_player(tmp_path))
    held = files(**{"notes/a.md": [RECIPE(P1)]})
    with_claims(root, start=held, end=held)
    m = metrics_of(root)["notes_learned"]
    assert set(m.detail["learned"]) == {"reaction:r04"}
    assert m.value == 0.0
    wrong_before = files(
        **{"notes/a.md": [claim("recipe", potion=P1, inputs=["water", "blood", "coal"])]}
    )
    with_claims(root, start=wrong_before, end=held)  # wrong at the start: learning it counts
    assert f"recipe:{P1}" in metrics_of(root)["notes_learned"].detail["learned"]


def test_learned_is_not_measured_when_the_start_is_unknown_or_nothing_could_be_learned(tmp_path):
    root = meeting_e16(tmp_path, mixes_at_player(tmp_path))
    gap = [{"section": "start", "path": "notes/old.md", "reason": "x"}]
    with_claims(root, start={}, end=files(**{"notes/a.md": [OIL()]}), skipped=gap)
    assert "was not extracted" in metrics_of(root)["notes_learned"].reason
    with_claims(root, start=None, end=files(**{"notes/a.md": [OIL()]}))
    m = metrics_of(root)["notes_learned"]
    assert m.value is None and "unknown" in m.reason
    quiet = tmp_path / "quiet"
    plain = write_run(quiet / "run-02", track=walk([(0, 100.0, 100.0), (60, 110.0, 100.0)]))
    with_claims(plain, start={}, end=files(**{"notes/a.md": [OIL()]}))
    m = metrics_of(plain)["notes_learned"]
    assert m.value is None and "nothing to learn" in m.reason


# --------------------------------------------------------------------------- in the profile
def test_the_profile_carries_both_metrics_into_n2(tmp_path):
    root = meeting_e16(tmp_path, mixes_at_player(tmp_path))
    with_claims(root, start={}, end=files(**{"notes/a.md": [RECIPE(P1), OIL()]}))
    profile = evaluate_run(root)
    assert profile["evaluator"]["version"] == "0.4.1"
    by_name = {m["name"]: m for m in profile["metrics"]}
    assert (
        by_name["notes_accuracy"]["status"] == "measured"
        and by_name["notes_learned"]["status"] == "measured"
    )
    n2 = {m["name"] for m in profile["capabilities"]["N2"]["metrics"]}
    assert {"notes_accuracy", "notes_learned"} <= n2
    dump = json.dumps(profile["metrics"], ensure_ascii=False)
    assert '"text"' not in dump  # no claim text in the profile
    # the start notebook was empty: no note to follow, no wrong note to mend
    assert by_name["notes_used"]["status"] == by_name["notes_corrected"]["status"] == "not_measured"


def test_a_run_without_the_file_is_scored_as_before(tmp_path):
    profile = evaluate_run(meeting_e16(tmp_path))
    by_name = {m["name"]: m for m in profile["metrics"]}
    assert (
        by_name["notes_accuracy"]["status"] == by_name["notes_learned"]["status"] == "not_measured"
    )
