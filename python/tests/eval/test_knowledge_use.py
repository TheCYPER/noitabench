"""N2 notes_used and notes_corrected, on hand-made families of run folders (`fam/run-01`,
`fam/run-02`): the second game begins with the first game's notebook (`workspace_start/`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from eval_runs import box, command, damage, lab_marker, walk, write_run
from noitabench.eval import evaluate_run
from noitabench.eval.encounters import evaluate_visits
from noitabench.eval.knowledge import build_knowledge, data, parse_claim
from noitabench.eval.knowledge.claims import FileClaims, NoteClaims, save_note_claims
from noitabench.eval.knowledge.extract import FromFile, extract_run
from noitabench.eval.metrics import Metric, compute_metrics
from noitabench.eval.metrics.knowledge import player_mix_events
from noitabench.eval.metrics.notes_use import (
    MIX_LAG,
    POUR_GAP,
    POUR_NEAR,
    USE_SUCCESS,
    Attempt,
    Pour,
    covering_attempt,
)
from noitabench.eval.recording import load_run
from noitabench.harness.prompt import opening_message

K = build_knowledge(0)
RECIPES = {f.fields["potion"]: f.fields["inputs"] for f in K.of_kind("recipe")}
P1, P2 = list(RECIPES)[:2]
POOL = list(data.tag_members()["ingredient"])
EXTRA = next(m for m in POOL if m not in RECIPES[P1])  # an ingredient P1 does not use
VIEW = "Decision 1 (frame 0, 0 s).\n..."
NOTE = "notes/a.md"
OTHER = "notes/b.md"


def wrong_inputs(potion: str) -> list[str]:
    """Three ingredients that share nothing with the potion's recipe and make no other potion."""
    real = set(RECIPES[potion])
    others = [set(v) for v in RECIPES.values()]
    spare = [m for m in POOL if m not in real]
    for a in range(len(spare)):
        for b in range(a + 1, len(spare)):
            for c in range(b + 1, len(spare)):
                trio = {spare[a], spare[b], spare[c]}
                if trio not in others:
                    return sorted(trio)
    raise AssertionError("no wrong trio")


WRONG = wrong_inputs(P1)


def claim(kind: str, hedged: bool = False, **fields: Any):
    made, why = parse_claim({"kind": kind, "hedged": hedged, "text": "t", **fields})
    assert made is not None, why
    return made


def recipe(potion: str, inputs: list[str] | None = None, hedged: bool = False):
    return claim("recipe", hedged, potion=potion, inputs=inputs or RECIPES[potion])


def ACID_WATER(out: tuple[str, ...] = ("flammable_gas", "air")):
    return claim("reaction", a="acid", b="water", out=list(out))


def claims_in(path: str, *claims) -> dict[str, FileClaims]:
    return {path: FileClaims("0" * 64, 10, tuple(claims))}


# ------------------------------------------------------------------------------- the family
def turn(decision: int, *calls: tuple[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """An assistant record with `calls` and its results record (all succeeded)."""
    ids = [f"c{decision}-{k}" for k in range(len(calls))]
    assistant = {
        "kind": "assistant", "call": decision + 1, "decision": decision, "text": "", "thinking": "",
        "tool_calls": [{"id": i, "name": n, "arguments": a} for i, (n, a) in zip(ids, calls, strict=True)],
    }  # fmt: skip
    results = {
        "kind": "results", "call": decision + 1, "decision": decision,
        "results": [{"id": i, "name": n, "is_error": False, "content": "ok"} for i, (n, _a) in zip(ids, calls, strict=True)],
    }  # fmt: skip
    return [assistant, results]


def read(decision: int, path: str = NOTE):
    return turn(decision, ("workspace_read", {"path": path}))


def search(decision: int):
    return turn(decision, ("workspace_search", {"query": "lava"}))


def pour(frame: int, material: str) -> dict[str, Any]:
    return {"frame": frame, "type": "pour", "material": material, "cells": 30}


def mix(frame: int, potion: str, *, far: bool = False) -> dict[str, Any]:
    dx = 600 if far else 20
    return {"frame": frame, "type": "mix", "x": CENTRE[0] + dx, "y": CENTRE[1], "potion": potion}


def drink(frame: int, material: str) -> dict[str, Any]:
    return {"frame": frame, "type": "drink", "material": material, "cells": 10}


def pours_of(inputs: list[str], first: int = 40, step: int = 30) -> list[dict[str, Any]]:
    return [pour(first + step * i, m) for i, m in enumerate(inputs)]


def _scene() -> tuple[dict[str, Any], Any]:
    m = lab_marker("E16", dx=300, dy=300)
    return m, box(m, "trough")


MARKER, TROUGH = _scene()
CENTRE = (TROUGH.x - 80 + 3, TROUGH.y - 16 + 8)  # the player's centre in the first 200 frames


def family(
    tmp: Path,
    start: dict[str, str] | None = None,
    *,
    end: dict[str, str] | None = None,
    start_claims: dict[str, FileClaims] | None = None,
    end_claims: dict[str, FileClaims] | None = None,
    events: list | tuple = (),
    transcript: list | None = None,
    inspect: bool = True,
    harm: float = 0.0,
    timed: bool = True,
    log: bool = True,
    skipped: tuple = (),
) -> Path:
    """`tmp/fam/run-02`: the game meets E16 at about frame 400, with ten decisions 100 frames
    apart (an `inspect` of the trough among them), and begins with `start` as its notebook."""
    start = {NOTE: "lava and water make rock; mix oil here"} if start is None else start
    fam = tmp / "fam"
    first = write_run(fam / "run-01", track=walk([(0, 100.0, 100.0), (60, 110.0, 100.0)]))
    for rel, text in start.items():  # what game 1 left, and game 2 begins with
        (first / "workspace" / rel).parent.mkdir(parents=True, exist_ok=True)
        (first / "workspace" / rel).write_text(text)
    y = TROUGH.y - 16
    track = walk([(0, TROUGH.x - 80, y), (200, TROUGH.x - 80, y), (400, TROUGH.x + 2, y + 8), (900, TROUGH.x + 2, y + 8)])  # fmt: skip
    rows = [command(100 * k, "wait", until={"ticks": 10}) for k in range(10)]
    if inspect:
        rows[3] = command(300, "inspect", x=TROUGH.x + 2, y=TROUGH.y + 2)
    held = [(p, len(t)) for p, t in sorted(start.items())]
    opening = [
        {"kind": "opening", "text": opening_message(VIEW, held, 8000 - sum(n for _, n in held))}
    ]
    hurt = [damage(430, harm)] if harm else []
    root = write_run(
        fam / "run-02",
        markers=[MARKER],
        track=track,
        events=[*events, *hurt],
        decisions=rows if timed else None,
        transcript=[*opening, *(transcript or [])] if log else None,
    )
    for name, notes in (("workspace_start", start), ("workspace", start if end is None else end)):
        (root / name).mkdir(exist_ok=True)
        for rel, text in notes.items():
            (root / name / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / name / rel).write_text(text)
    if start_claims is not None or end_claims is not None:
        doc = NoteClaims(
            {"provider": "file", "model": "t"},
            start=start_claims,
            end=end_claims or {},
            skipped=list(skipped),
        )
        save_note_claims(doc, root)
    return root


def metrics_of(root: Path) -> dict[str, Metric]:
    run = load_run(root)
    return {m.name: m for m in compute_metrics(run, evaluate_visits(run))}


def used(root: Path) -> Metric:
    return metrics_of(root)["notes_used"]


def corrected(root: Path) -> Metric:
    return metrics_of(root)["notes_corrected"]


def visit_score(root: Path) -> float:
    (result,) = evaluate_visits(load_run(root))
    return result.outcome.score


# ------------------------------------------------------------------------ the fixtures hold
def test_the_fixture_scene_is_met_well_or_badly_as_it_is_built(tmp_path):
    good = family(tmp_path / "a", inspect=True)
    bad = family(tmp_path / "b", inspect=False, harm=60.0)
    assert visit_score(good) >= USE_SUCCESS > visit_score(bad)


def test_the_wrong_trio_shares_nothing_with_the_recipe_and_makes_no_other_potion():
    assert not set(WRONG) & set(RECIPES[P1]) and len(WRONG) == 3
    assert all(set(WRONG) != set(v) for v in RECIPES.values())


# ----------------------------------------------------------------------------- notes_used: recipes
def test_a_recipe_read_and_followed_at_once_is_full_use(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(0), events=events,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    m = used(root)
    assert m.value == 1.0 and m.opportunities == 1
    assert m.detail["used"] == [
        {"fact": f"recipe:{P1}", "value": 1.0, "why": m.detail["used"][0]["why"]}
    ]
    assert "1 of 1" in m.reason and m.detail["misled"] == []


def test_other_ingredients_tried_after_the_read_halve_it(tmp_path):
    events = [pour(20, EXTRA), *pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(0), events=events, start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    assert used(root).value == 0.5


def test_a_pour_before_the_read_is_not_counted_against_the_note(tmp_path):
    events = [pour(20, EXTRA), mix(190, P1), *pours_of(RECIPES[P1], 160, 10)]
    root = family(tmp_path, transcript=read(1), events=events,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    m = used(root)  # read at frame 100, the extra pour at 20, the mix at 190
    assert m.value == 1.0 and m.opportunities == 1


def test_a_partly_right_recipe_is_worth_half(tmp_path):
    two = recipe(P1, RECIPES[P1][:2])
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(0), events=events, start_claims=claims_in(NOTE, two), end_claims={})  # fmt: skip
    assert K.recipe(P1) is not None
    assert used(root).value == 0.5


def test_a_recipe_known_by_its_effect_is_found_through_the_potion(tmp_path):
    effect = K.by_id[f"drink:{P1}"].fields["effect"]
    by_effect = claim("recipe", effect=effect, inputs=RECIPES[P1])
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(0), events=events, start_claims=claims_in(NOTE, by_effect), end_claims={})  # fmt: skip
    assert used(root).value == 1.0


def test_an_unread_note_earns_nothing(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, events=events, start_claims=claims_in(NOTE, recipe(P1)), end_claims={})
    m = used(root)
    assert m.value == 0.0 and m.opportunities == 1
    assert "did not read it" in m.detail["used"][0]["why"]


def test_programs_that_may_have_read_the_note_leave_the_claim_out(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    code = [{"kind": "code_run", "label": "run_code"}]
    root = family(tmp_path, events=events, transcript=code,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    m = used(root)
    assert (
        m.value is None
        and "programs ran" in m.reason
        and m.detail["unseen_reads"] == [f"recipe:{P1}"]
    )


def test_a_note_read_only_after_the_potion_was_tried_earns_nothing(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(5), events=events,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    m = used(root)
    assert m.value == 0.0 and "after trying the potion" in m.detail["used"][0]["why"]


def test_read_but_the_potion_never_made_is_nothing(tmp_path):
    events = pours_of(RECIPES[P1], 40, 25)  # poured, no mix
    root = family(tmp_path, transcript=read(0), events=events,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    m = used(root)
    assert m.value == 0.0 and "did not make the potion" in m.detail["used"][0]["why"]


def test_a_search_reads_every_file_and_any_file_holding_the_claim_will_do(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    both = {
        NOTE: FileClaims("0" * 64, 5, (recipe(P1),)),
        OTHER: FileClaims("1" * 64, 5, (recipe(P1),)),
    }
    texts = {NOTE: "lava and water make rock", OTHER: "the recipe, again"}
    by_search = family(tmp_path / "s", texts, transcript=search(0), events=events, start_claims=both, end_claims={})  # fmt: skip
    assert (
        used(by_search).value == 1.0 and used(by_search).opportunities == 1
    )  # the claim counts once
    by_second = family(tmp_path / "t", texts, transcript=read(0, OTHER), events=events, start_claims=both, end_claims={})  # fmt: skip
    assert used(by_second).value == 1.0
    wrong_file = family(
        tmp_path / "u", {**texts, "notes/c.md": "nothing about it"}, transcript=read(0, "notes/c.md"), events=events,
        start_claims=both, end_claims={},
    )  # fmt: skip
    assert used(wrong_file).value == 0.0


def test_a_potion_mixed_far_from_the_player_is_not_the_players(tmp_path):
    events = [mix(95, P1, far=True)]
    root = family(tmp_path, transcript=read(0), events=events,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    assert player_mix_events(load_run(root)) == []
    m = used(root)
    assert (
        m.value is None
        and "came into play" in m.reason
        and m.detail["no_moment"] == [f"recipe:{P1}"]
    )


def test_without_decisions_a_read_counts_as_early_and_the_reason_says_so(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(7), events=events, timed=False,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    m = used(root)
    assert m.value == 1.0 and "no decisions.jsonl" in m.reason and m.detail["reads_untimed"]


# ------------------------------------------------------------------- notes_used: linked scenes
def test_a_note_about_a_scene_is_followed_when_the_scene_goes_well(tmp_path):
    root = family(
        tmp_path, transcript=read(0), start_claims=claims_in(NOTE, ACID_WATER()), end_claims={}
    )
    m = used(root)
    assert m.value == 1.0 and m.opportunities == 1
    assert "went well" in m.detail["used"][0]["why"]
    # Noita's own acid fact is linked to the same scene and counts the same
    harms = claim("property", material="acid", property="harms_on_contact")
    root = family(
        tmp_path / "h", transcript=read(0), start_claims=claims_in(NOTE, harms), end_claims={}
    )
    assert used(root).value == 1.0


def test_a_scene_that_goes_badly_is_no_success_and_a_wrong_note_read_before_it_misled(tmp_path):
    notes = claims_in(NOTE, ACID_WATER(), ACID_WATER(("steam",)))  # one right, one wrong
    root = family(
        tmp_path, transcript=read(0), inspect=False, harm=60.0, start_claims=notes, end_claims={}
    )
    m = used(root)
    assert m.value == 0.0 and m.opportunities == 1
    assert m.detail["misled"] == [{"fact": "reaction:r04", "why": m.detail["misled"][0]["why"]}]
    assert "led nowhere" in m.reason
    fine = family(tmp_path / "f", transcript=read(0), start_claims=notes, end_claims={})
    assert (
        used(fine).value == 1.0 and used(fine).detail["misled"] == []
    )  # the wrong one: no failure


def test_a_scene_note_read_after_the_scene_is_nothing(tmp_path):
    root = family(
        tmp_path, transcript=read(8), start_claims=claims_in(NOTE, ACID_WATER()), end_claims={}
    )
    m = used(root)
    assert m.value == 0.0 and "after the scene" in m.detail["used"][0]["why"]


# ------------------------------------------------------------------ notes_used: not measured
def test_used_and_corrected_say_why_they_are_not_measured(tmp_path):
    bare = family(tmp_path / "a")  # no notes_claims.json
    for name in ("notes_used", "notes_corrected"):
        assert (
            metrics_of(bare)[name].value is None and "notes-claims" in metrics_of(bare)[name].reason
        )
    unknown = family(tmp_path / "b", start_claims=None, end_claims={})
    gap = [{"section": "start", "path": NOTE, "reason": "x"}]
    partial = family(tmp_path / "c", start_claims={}, end_claims={}, skipped=gap)
    for root, text in ((unknown, "unknown"), (partial, "not extracted")):
        for name in ("notes_used", "notes_corrected"):
            m = metrics_of(root)[name]
            assert m.value is None and text in m.reason


def test_a_start_notebook_without_a_counted_claim_of_the_kind_has_nothing_to_measure(tmp_path):
    hedged = recipe(P1, hedged=True)
    only = family(
        tmp_path / "a", start_claims=claims_in(NOTE, hedged, claim("local")), end_claims={}
    )
    assert "no claim that counts as right" in used(only).reason
    assert "no wrong claim" in corrected(only).reason
    empty = family(tmp_path / "b", start={}, start_claims={}, end_claims={})
    assert "no claim that counts as right" in used(empty).reason
    right_only = family(tmp_path / "c", start_claims=claims_in(NOTE, recipe(P1)), end_claims={})
    assert "no wrong claim" in corrected(right_only).reason


def test_a_run_that_logged_no_reads_cannot_tell_a_note_unread_from_one_unseen(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, events=events, log=False,
                  start_claims=claims_in(NOTE, recipe(P1)), end_claims={})  # fmt: skip
    m = used(root)
    assert m.value is None and "no transcript" in m.reason


def test_a_hedged_note_is_judged_but_never_used(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(0), events=events,
                  start_claims=claims_in(NOTE, recipe(P1, hedged=True)), end_claims={})  # fmt: skip
    m = used(root)
    assert m.value is None and m.detail["hedged"] == 1


def test_a_family_of_notes_with_no_moment_is_not_measured(tmp_path):
    root = family(
        tmp_path, transcript=read(0), start_claims=claims_in(NOTE, recipe(P1)), end_claims={}
    )
    m = used(root)
    assert m.value is None and m.opportunities == 0 and "came into play" in m.reason


def test_a_recipe_note_left_unread_while_a_scene_note_is_followed_averages(tmp_path):
    notes = claims_in(NOTE, recipe(P1), ACID_WATER())
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, transcript=read(5), events=events, start_claims=notes, end_claims={})
    m = used(root)  # read at frame 500: after the potion (0) and after the scene (~400)
    assert m.value == 0.0 and m.opportunities == 2
    early = family(
        tmp_path / "e", transcript=read(0), events=events, start_claims=notes, end_claims={}
    )
    assert used(early).value == 1.0


# ---------------------------------------------------------------------------- notes_corrected
def test_a_wrong_recipe_that_was_poured_and_gave_nothing_is_contradicted(tmp_path):
    wrong = recipe(P1, WRONG)
    events = pours_of(WRONG, 40, 25)  # no potion within MIX_LAG
    cases = (
        (claims_in(NOTE, recipe(P1)), 1.0),  # the right recipe now stands
        ({}, 0.5),  # the wrong line is gone
        (claims_in(NOTE, recipe(P1, WRONG, hedged=True)), 0.5),  # or hedged
        (claims_in(NOTE, recipe(P1, WRONG)), 0.0),  # still there
        (claims_in(NOTE, recipe(P1), recipe(P1, WRONG)), 0.0),  # the notes still contradict
    )
    for n, (end_claims, value) in enumerate(cases):
        root = family(tmp_path / f"v{n}", events=events,
                      start_claims=claims_in(NOTE, wrong), end_claims=end_claims)  # fmt: skip
        m = corrected(root)
        assert m.value == value and m.opportunities == 1, (value, m.detail)
        assert f"no {P1}" in m.detail["tested"][0]["tested"]


def test_a_wrong_recipe_is_contradicted_by_making_the_potion_another_way(tmp_path):
    events = [*pours_of(RECIPES[P1], 40, 25), mix(95, P1)]
    root = family(tmp_path, events=events, start_claims=claims_in(NOTE, recipe(P1, WRONG)),
                  end_claims=claims_in(NOTE, recipe(P1)))  # fmt: skip
    m = corrected(root)
    assert m.value == 1.0 and "without those inputs" in m.detail["tested"][0]["tested"]


def test_a_wrong_recipe_that_came_true_after_all_is_not_contradicted(tmp_path):
    # the claimed trio was poured in the same place before the potion came: the note was tested
    # and the potion followed within the lag, so the game did not show it wrong
    trio = [*WRONG, *RECIPES[P1]]
    events = [*pours_of(trio, 20, 10), mix(60 + 100, P1)]
    root = family(
        tmp_path, events=events, start_claims=claims_in(NOTE, recipe(P1, WRONG)), end_claims={}
    )
    assert corrected(root).value is None


def test_a_wrong_drink_is_contradicted_by_drinking_it(tmp_path):
    wrong = claim("drink", material="oil", effect="heal")
    right = claim("drink", material="oil", effect="oiled")
    root = family(tmp_path, events=[drink(60, "oil")], start_claims=claims_in(NOTE, wrong),
                  end_claims=claims_in(NOTE, right))  # fmt: skip
    m = corrected(root)
    assert m.value == 1.0 and m.detail["tested"][0]["tested"] == "drank oil"
    untouched = family(tmp_path / "u", start_claims=claims_in(NOTE, wrong), end_claims={})
    assert corrected(untouched).value is None and "put to the test" in corrected(untouched).reason


def test_a_wrong_note_on_a_scene_is_contradicted_by_meeting_it(tmp_path):
    wrong = ACID_WATER(("steam",))
    root = family(
        tmp_path, start_claims=claims_in(NOTE, wrong), end_claims=claims_in(NOTE, ACID_WATER())
    )
    m = corrected(root)
    assert m.value == 1.0 and "E16" in m.detail["tested"][0]["tested"]
    still = family(
        tmp_path / "s", start_claims=claims_in(NOTE, wrong), end_claims=claims_in(NOTE, wrong)
    )
    assert corrected(still).value == 0.0


def test_hedged_wrong_notes_are_not_counted_and_untested_ones_are_left_out(tmp_path):
    hedged = recipe(P1, WRONG, hedged=True)
    root = family(
        tmp_path,
        events=pours_of(WRONG, 40, 25),
        start_claims=claims_in(NOTE, hedged),
        end_claims={},
    )
    assert corrected(root).value is None and "no wrong claim" in corrected(root).reason
    untested = family(
        tmp_path / "u", start_claims=claims_in(NOTE, recipe(P1, WRONG)), end_claims={}
    )
    m = corrected(untested)
    assert m.value is None and "put to the test" in m.reason and m.detail["wrong_claims"] == 1


def test_two_wrong_notes_average_their_values(tmp_path):
    notes = claims_in(NOTE, recipe(P1, WRONG), claim("drink", material="oil", effect="heal"))
    end = claims_in(NOTE, claim("drink", material="oil", effect="oiled"))  # one mended, one gone
    root = family(
        tmp_path,
        events=[*pours_of(WRONG, 40, 25), drink(150, "oil")],
        start_claims=notes,
        end_claims=end,
    )
    m = corrected(root)
    assert m.opportunities == 2 and m.value == pytest.approx(0.75)


def test_a_wrong_note_is_not_called_gone_when_part_of_the_final_notes_was_not_extracted(tmp_path):
    events = pours_of(WRONG, 40, 25)  # poured, no potion: the wrong recipe was put to the test
    gap = [{"section": "end", "path": OTHER, "reason": "x"}]
    root = family(tmp_path, events=events, start_claims=claims_in(NOTE, recipe(P1, WRONG)),
                  end_claims={}, skipped=gap)  # fmt: skip
    m = corrected(root)
    assert m.value is None and m.opportunities == 0 and "final notebook" in m.reason
    complete = family(tmp_path / "c", events=events,
                      start_claims=claims_in(NOTE, recipe(P1, WRONG)), end_claims={})  # fmt: skip
    assert corrected(complete).value == 0.5  # the same play, fully extracted: gone


# ----------------------------------------------------------------- the helpers and the profile
def test_pours_make_an_attempt_only_when_close_in_time_and_place():
    here = [
        Pour(100, "oil", 50.0, 50.0),
        Pour(130, "sand", 55.0, 50.0),
        Pour(160, "coal", 60.0, 50.0),
    ]
    assert covering_attempt(here, ["oil", "sand", "coal"]) == Attempt(100, 160)
    assert covering_attempt(here, ["oil", "sand", "gold_dust"]) is None
    slow = [Pour(100, "oil", 50.0, 50.0), Pour(100 + POUR_GAP + 1, "sand", 50.0, 50.0)]
    assert covering_attempt(slow, ["oil", "sand"]) is None
    assert covering_attempt(
        slow[:1] + [Pour(100 + POUR_GAP, "sand", 50.0, 50.0)], ["oil", "sand"]
    ) == Attempt(100, 100 + POUR_GAP)
    far = [Pour(100, "oil", 50.0, 50.0), Pour(110, "sand", 50.0 + POUR_NEAR + 1, 50.0)]
    assert covering_attempt(far, ["oil", "sand"]) is None
    assert covering_attempt(here, []) is None
    assert MIX_LAG > 0


def test_an_extracted_family_end_to_end_through_the_files(tmp_path):
    """workspace_start/ and workspace/ extracted by `extract_run` (claims from a file), then
    evaluated: the metrics find the start section, and a profile carries them into N2."""
    root = family(
        tmp_path,
        {NOTE: "acid and water make a gas; oil burns well"},
        end={NOTE: "acid and water make a gas; oil burns well; mixing sand + coal is useless"},
        transcript=read(0),
    )
    source = {NOTE: [
        {"kind": "reaction", "a": "acid", "b": "water", "out": ["flammable_gas"], "text": "acid and water make a gas"},
        {"kind": "property", "material": "oil", "property": "burns", "text": "oil burns well"},
    ]}  # fmt: skip
    doc = extract_run(root, FromFile(source))
    assert doc is not None and doc.start is not None and set(doc.start) == {NOTE}
    found = metrics_of(root)
    assert found["notes_used"].value == 1.0 and found["notes_used"].opportunities == 1
    assert found["notes_corrected"].value is None
    profile = evaluate_run(root)
    by_name = {m["name"]: m for m in profile["metrics"]}
    n2 = {m["name"] for m in profile["capabilities"]["N2"]["metrics"]}
    assert {"notes_used", "notes_corrected", "notes_accuracy", "notes_learned"} <= set(by_name)
    assert "notes_used" in n2 and by_name["notes_used"]["status"] == "measured"
    assert '"text"' not in json.dumps(profile["metrics"])
