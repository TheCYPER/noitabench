"""The N2 notes metrics and the N4 first-contact metric, on hand-made run folders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eval_runs import box, command, damage, lab_marker, walk, write_run
from noitabench.eval import evaluate_run
from noitabench.eval.encounters import evaluate_visits
from noitabench.eval.metrics import Metric, compute_metrics
from noitabench.eval.metrics.notes import note_path, opening_notebook
from noitabench.eval.recording import load_run
from noitabench.harness.prompt import opening_message
from noitabench.worldgen.config import load_materials

MATS = load_materials()
LAVA, WATER, ACID, SLUDGE = MATS["lava"], MATS["water"], MATS["acid"], MATS["toxic_sludge"]
VIEW = "Decision 1 (frame 0, 0 s).\n..."
# the harness's own wording (`notes.py` parses it: these tests fail if it changes)
OPENING = opening_message(VIEW, [("notes/chem.md", 120), ("skills/dig.md", 40)], 7840)
EMPTY = opening_message(VIEW, [], 8000)


def metrics_of(root: Path) -> dict[str, Metric]:
    run = load_run(root)
    return {m.name: m for m in compute_metrics(run, evaluate_visits(run))}


def status(frame: int, name: str, active: int = 1) -> dict[str, Any]:
    return {"frame": frame, "type": "status", "target": "player", "id": 1, "status": name,
            "active": active}  # fmt: skip


def death(frame: int, source: str = "contact") -> dict[str, Any]:
    return {"frame": frame, "type": "death", "target": "player", "id": 1, "source": source}


# ================================================================================ N2 notes
def turn(decision: int, *calls: tuple[str, dict[str, Any]], agent: str | None = None) -> list:
    """An assistant record with `calls` and its results record (all succeeded)."""
    ids = [f"c{decision}-{k}" for k in range(len(calls))]
    a = {"kind": "assistant", "call": decision + 1, "decision": decision, "text": "",
         "thinking": "", "tool_calls": [{"id": i, "name": n, "arguments": args}
                                        for i, (n, args) in zip(ids, calls, strict=True)]}  # fmt: skip
    r = {"kind": "results", "call": decision + 1, "decision": decision,
         "results": [{"id": i, "name": n, "is_error": False, "content": "ok"}
                     for i, (n, _a) in zip(ids, calls, strict=True)]}  # fmt: skip
    if agent:
        a["agent"] = r["agent"] = agent
    return [a, r]


def notes_run(
    tmp: Path,
    transcript: list | None,
    *,
    workspace: dict[str, str] | None = None,
    decisions: list | None = None,
) -> Path:
    """A run that meets E16 at about frame 300, with 10 decisions 100 frames apart."""
    m = lab_marker("E16", dx=300, dy=300)
    trough = box(m, "trough")
    y = trough.y - 16
    track = walk([(0, trough.x - 80, y), (200, trough.x - 80, y), (400, trough.x - 8, y),
                  (900, trough.x - 8, y)])  # fmt: skip
    if decisions is None:
        decisions = [command(100 * k, "wait", until={"ticks": 10}) for k in range(10)]
    root = write_run(tmp / "run", markers=[m], track=track, decisions=decisions,
                     transcript=transcript)  # fmt: skip
    if workspace is not None:
        for rel, text in workspace.items():
            path = root / "workspace" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (root / "workspace").mkdir(exist_ok=True)
    return root


def test_the_opening_lists_the_notebook_at_the_start():
    assert opening_notebook([{"kind": "opening", "text": OPENING}]) == {
        "notes/chem.md": 120,
        "skills/dig.md": 40,
    }
    assert opening_notebook([{"kind": "opening", "text": EMPTY}]) == {}
    assert opening_notebook([{"kind": "assistant", "text": "hi"}]) is None
    spaced = opening_message(VIEW, [("notes/lava river.md", 9), ("notes/a-b.c.md", 3)], 10)
    assert opening_notebook([{"kind": "opening", "text": spaced}]) == {
        "notes/lava river.md": 9,
        "notes/a-b.c.md": 3,
    }


def test_note_paths_are_filed_as_the_workspace_files_them():
    from noitabench.harness.workspace import AREAS, NOTES_AREAS, normalize

    for raw in ("chem.md", "chem/lava.md", "skills/x.md", "notes/a.md", "scripts/x.py"):
        assert note_path(raw) == normalize(raw, AREAS)[0], raw
        assert note_path(raw, code_area=False) == normalize(raw, NOTES_AREAS)[0], raw


def test_reading_kept_notes_before_the_first_scene_is_full_recall(tmp_path):
    t = [{"kind": "opening", "text": OPENING}, *turn(0, ("workspace_read", {"path": "chem.md"}))]
    m = metrics_of(notes_run(tmp_path, t))["notes_recall"]
    assert m.value == pytest.approx(1.0) and m.opportunities == 1
    assert m.detail["kept_at_start"] == ["notes/chem.md", "skills/dig.md"]


def test_reading_them_only_after_the_first_scene_is_half(tmp_path):
    t = [{"kind": "opening", "text": OPENING}, *turn(6, ("workspace_read", {"path": "chem.md"}))]
    m = metrics_of(notes_run(tmp_path, t))["notes_recall"]
    assert m.value == pytest.approx(0.5)
    assert m.detail["first_read_frame"] == 600


def test_a_search_or_a_helper_reading_counts_and_a_failed_read_does_not(tmp_path):
    search = [{"kind": "opening", "text": OPENING},
              *turn(1, ("workspace_search", {"query": "lava"}), agent="h1")]  # fmt: skip
    assert metrics_of(notes_run(tmp_path / "a", search))["notes_recall"].value == 1.0
    failed = [{"kind": "opening", "text": OPENING}, *turn(1, ("workspace_read", {"path": "x"}))]
    failed[-1]["results"][0]["is_error"] = True
    failed += turn(2, ("workspace_read", {"path": "notes/other.md"}))  # not a kept note
    assert metrics_of(notes_run(tmp_path / "b", failed))["notes_recall"].value == 0.0


def test_recall_is_not_measured_without_kept_notes_a_transcript_or_when_programs_ran(tmp_path):
    empty = [{"kind": "opening", "text": EMPTY}]
    assert metrics_of(notes_run(tmp_path / "a", empty))["notes_recall"].value is None
    assert metrics_of(notes_run(tmp_path / "b", None))["notes_recall"].value is None
    code = [{"kind": "opening", "text": OPENING}, {"kind": "code_run", "label": "run_code"}]
    m = metrics_of(notes_run(tmp_path / "c", code))["notes_recall"]
    assert m.value is None and "programs ran" in m.reason


def test_notes_kept_reads_the_notebook_left_at_the_end(tmp_path):
    t = [{"kind": "opening", "text": OPENING}, {"kind": "code_run", "label": "run_code"}]
    grown = {"notes/chem.md": "x" * 200, "skills/dig.md": "y" * 40}
    m = metrics_of(notes_run(tmp_path / "a", t, workspace=grown))["notes_kept"]
    assert m.value == 1.0 and m.detail["files"] == ["notes/chem.md"]  # a program may have
    same = {"notes/chem.md": "x" * 120, "skills/dig.md": "y" * 40}
    assert metrics_of(notes_run(tmp_path / "b", t, workspace=same))["notes_kept"].value == 0.0


def test_notes_kept_from_a_visible_write_a_text_mode_note_or_nothing_at_all(tmp_path):
    t = [{"kind": "opening", "text": EMPTY}, *turn(3, ("workspace_write", {"path": "a.md",
                                                                           "text": "lava"}))]  # fmt: skip
    assert metrics_of(notes_run(tmp_path / "a", t))["notes_kept"].value == 1.0
    text_mode = [*[command(100 * k, "wait") for k in range(4)],
                 command(400, "memory_write", path="lava.md", text="water crusts it")]  # fmt: skip
    m = metrics_of(notes_run(tmp_path / "b", [{"kind": "opening", "text": EMPTY}],
                             decisions=text_mode))["notes_kept"]  # fmt: skip
    assert m.value == 1.0
    nothing = [{"kind": "opening", "text": EMPTY}]
    m = metrics_of(notes_run(tmp_path / "c", nothing, workspace={}))["notes_kept"]
    assert m.value == 0.0 and m.opportunities == 1


def test_a_change_at_the_end_that_nobody_wrote_is_not_a_kept_note(tmp_path):
    """The harness re-cleans notes and copies them cleaned: sizes change with no write."""
    t = [{"kind": "opening", "text": OPENING}]
    cleaned = {"notes/chem.md": "x" * 100, "skills/dig.md": "y" * 40}
    m = metrics_of(notes_run(tmp_path / "a", t, workspace=cleaned))["notes_kept"]
    assert m.value == 0.0
    wrote = [*t, *turn(2, ("workspace_edit", {"path": "chem.md", "old": "a", "new": "b"}))]
    m = metrics_of(notes_run(tmp_path / "b", wrote, workspace=cleaned))["notes_kept"]
    assert m.value == 1.0 and m.detail["files"] == ["notes/chem.md"]
    gone = [*t, *turn(2, ("workspace_write", {"path": "tmp.md", "text": "x"}))]
    m = metrics_of(notes_run(tmp_path / "c", gone, workspace={"notes/chem.md": "x" * 120,
                                                               "skills/dig.md": "y" * 40}))  # fmt: skip
    assert m["notes_kept"].value == 0.0  # written, then deleted: nothing left for later


def test_notes_kept_is_not_measured_without_a_transcript_or_with_unseen_programs(tmp_path):
    assert metrics_of(notes_run(tmp_path / "a", None))["notes_kept"].value is None
    code = [{"kind": "opening", "text": EMPTY}, {"kind": "code_run", "label": "run_code"}]
    unseen = metrics_of(notes_run(tmp_path / "b", code))["notes_kept"]
    assert unseen.value is None and "programs ran" in unseen.reason
    seen_empty = metrics_of(notes_run(tmp_path / "c", code, workspace={}))["notes_kept"]
    assert seen_empty.value == 0.0  # the final notebook shows the programs kept nothing


def test_notes_used_and_corrected_need_the_notes_extracted_into_claims(tmp_path):
    found = metrics_of(notes_run(tmp_path, [{"kind": "opening", "text": OPENING}]))
    for name in ("notes_used", "notes_corrected"):
        assert found[name].value is None and "notes-claims" in found[name].reason


# ======================================================================== N4 first contact
BRICK = MATS["brick"]
FEET = 216  # the hit box of a player standing at (100, 200) covers rows 200 to 215


def standing(frames: int, x: float = 100.0, y: float = 200.0):
    return walk([(0, x, y), (frames, x, y)])


def physics(tmp: Path, *, recorded: bool = True, patches=(), **kw) -> Metric:
    """The metric on a run whose grid (`patches`, else one cell of air) is recorded at every
    sample, unless `recorded` is False (then only the world PNG exists)."""
    patches = list(patches) or ([(0, 0, 1, 1, MATS["air"])] if recorded else [])
    root = write_run(tmp / "run", patches=patches, recorded=recorded, **kw)
    return metrics_of(root)["first_contact_physics"]


def drink_of(frame: int, material: str) -> dict[str, Any]:
    return {"frame": frame, "type": "drink", "material": material, "cells": 40}


def test_nothing_met_is_not_measured(tmp_path):
    m = physics(tmp_path, track=standing(600))
    assert m.value is None and m.opportunities == 0


def test_lava_within_three_cells_is_met_and_never_touching_it_is_full(tmp_path):
    met = physics(tmp_path / "a", track=standing(600), patches=[(95, FEET + 2, 20, 10, LAVA)])
    assert met.value == pytest.approx(1.0) and met.opportunities == 1
    assert met.detail["lava"]["why"] == "met it and never touched it"
    far = physics(tmp_path / "b", track=standing(600), patches=[(95, FEET + 3, 20, 10, LAVA)])
    assert far.value is None  # four cells below the feet: not within reach
    walled = [(95, FEET, 20, 2, BRICK), (95, FEET + 2, 20, 10, LAVA)]
    assert physics(tmp_path / "c", track=standing(600), patches=walled).value is None


def test_a_touch_at_the_first_meeting_scores_at_most_half(tmp_path):
    lava = [(95, 195, 20, 40, LAVA)]
    lit = [status(100, "on_fire"), status(130, "wet"), status(130, "on_fire", 0)]
    out_and_back = walk([(0, 100, 200), (130, 100, 200), (131, 300, 200), (350, 300, 200),
                         (351, 100, 200), (600, 100, 200)])  # fmt: skip
    quick = physics(tmp_path / "a", track=out_and_back, patches=lava,
                    events=[*lit, damage(100, 6, "contact"), damage(400, 40, "contact"),
                            status(400, "on_fire")])  # fmt: skip
    assert quick.value == pytest.approx(0.5 * (1 - 6 / 50))  # the second dip is N1's repeat
    assert quick.detail["lava"]["why"] == "touched it: 6 HP with the burning"
    burned = [status(100, "on_fire"), status(460, "on_fire", 0),
              *[damage(f, 2.5, "fire") for f in range(130, 461, 30)]]  # fmt: skip
    left = physics(tmp_path / "b", track=standing(600), patches=lava,
                   events=[*burned, damage(100, 2, "contact")])  # fmt: skip
    assert left.detail["lava"]["value"] == pytest.approx(0.5 * (1 - 32 / 50))
    assert "fire" not in left.detail  # the burning was the lava's: judged with it
    slow = physics(tmp_path / "c", track=standing(600), patches=lava,
                   events=[status(100, "on_fire"),
                           *[damage(f, 10, "contact") for f in (100, 130, 160, 190, 220)]])  # fmt: skip
    assert slow.value == pytest.approx(0.0)
    dead = physics(tmp_path / "d", track=standing(600), patches=lava,
                   events=[status(100, "on_fire"), damage(100, 6, "contact"), death(120)])  # fmt: skip
    assert dead.value == pytest.approx(0.0)


def test_a_touch_seen_only_on_the_grid_counts_with_damage_logged_as_fire(tmp_path):
    """The engine sums contact and fire damage into one event named after the last source: a
    lava wade can log no `contact` event at all. The hit box in the lava is the touch."""
    lava = [(95, 195, 20, 40, LAVA)]
    wade = walk([(0, 300, 200), (100, 300, 200), (101, 100, 200), (200, 100, 200),
                 (201, 300, 200), (600, 300, 200)])  # fmt: skip
    events = [status(110, "on_fire"), damage(110, 0.1, "fire"), damage(140, 14.2, "fire"),
              status(470, "on_fire", 0)]  # fmt: skip
    m = physics(tmp_path, track=wade, patches=lava, events=events)
    assert m.detail["lava"]["value"] == pytest.approx(0.5 * (1 - 14.3 / 50))
    assert "fire" not in m.detail  # that burning is the lava's


def test_a_graze_under_two_hp_that_began_nothing_is_no_touch(tmp_path):
    acid = [(95, 195, 20, 40, ACID)]
    graze = physics(tmp_path / "a", track=standing(300), patches=acid,
                    events=[damage(100, 0.75, "contact")])  # fmt: skip
    assert graze.detail["acid"]["value"] == 1.0 and "grazed" in graze.detail["acid"]["why"]
    real = physics(tmp_path / "b", track=standing(300), patches=acid,
                   events=[damage(100, 6, "contact")])  # fmt: skip
    assert real.detail["acid"]["value"] == pytest.approx(0.5 * (1 - 6 / 50))


def test_only_the_first_meeting_is_judged(tmp_path):
    """Met at the start and left alone; the touch comes at a later meeting (N1's business)."""
    lava = [(95, FEET + 2, 20, 10, LAVA)]
    track = walk([(0, 100, 200), (100, 100, 200), (101, 300, 200), (500, 300, 200),
                  (501, 100, 210), (700, 100, 210)])  # fmt: skip
    later = [status(520, "on_fire"), damage(520, 6, "contact")]
    m = physics(tmp_path, track=track, patches=lava, events=later)
    assert m.detail["lava"] == {"frame": 0, "value": 1.0, "why": "met it and never touched it"}


def test_poison_taken_beside_lava_is_not_a_lava_touch(tmp_path):
    """Lava always sets the player on fire; damage named lava with no burning is the poison."""
    events = [status(80, "poisoned"), damage(100, 1, "contact"), damage(130, 1, "contact"),
              status(560, "poisoned", 0)]  # fmt: skip
    beside = [(95, FEET + 1, 20, 10, LAVA)]  # a cell below the hit box: named lava, not touched
    m = physics(tmp_path, track=standing(600), patches=beside, events=events)
    assert m.detail["lava"]["value"] == 1.0  # met, never burned: never touched
    assert m.detail["toxic"]["why"].startswith("touched it")


def test_each_kind_is_one_opportunity_and_poison_is_toxic(tmp_path):
    patches = [(95, 195, 20, 40, ACID)]
    events = [damage(100, 30, "contact"), status(300, "poisoned"), damage(330, 8, "contact"),
              damage(360, 8, "contact"), status(780, "poisoned", 0)]  # fmt: skip
    m = physics(tmp_path, track=walk([(0, 100, 200), (200, 100, 200), (250, 300, 200),
                                      (900, 300, 200)]), patches=patches, events=events)  # fmt: skip
    assert m.opportunities == 2 and set(m.detail) == {"acid", "toxic"}
    assert m.detail["toxic"]["value"] == pytest.approx(0.5 * 0.6)  # one poisoning: 16 of 40 HP
    assert m.detail["acid"]["value"] == pytest.approx(0.5 * 0.4)  # 30 of 50 HP


def test_a_poisoning_or_a_burning_that_a_drink_began_is_no_contact(tmp_path):
    drunk = [status(100, "poisoned"), drink_of(140, "toxic_sludge"), damage(130, 8, "contact"),
             damage(160, 8, "contact"), status(580, "poisoned", 0)]  # fmt: skip
    m = physics(tmp_path / "a", track=standing(700), events=drunk)
    assert m.value is None and "toxic" not in m.detail
    burnt = [status(100, "on_fire"), drink_of(120, "lava"), status(460, "on_fire", 0)]
    assert physics(tmp_path / "b", track=standing(700), events=burnt).value is None


def test_without_a_recorded_grid_or_past_the_scan_cap_meetings_are_not_known(tmp_path, monkeypatch):
    lava = [(95, FEET + 2, 20, 10, LAVA)]
    png_only = physics(tmp_path / "a", track=standing(600), patches=lava, recorded=False)
    assert png_only.value is None and "no recorded grid" in png_only.detail["lava"]["why"]
    from noitabench.eval.metrics import meetings

    monkeypatch.setattr(meetings, "MAX_MEET_CHECKS", 5)
    late = walk([(0, 300, 200), (200, 300, 200), (201, 100, 200), (600, 100, 200)])
    cut = physics(tmp_path / "b", track=late, patches=lava)
    assert cut.value is None and "the scan stopped at 5 samples" in cut.detail["lava"]["why"]


def test_fire_put_out_beats_burning_out_with_water_at_hand(tmp_path):
    out = physics(tmp_path / "a", track=standing(900),
                  events=[status(100, "on_fire"), status(160, "wet"), status(160, "on_fire", 0)])  # fmt: skip
    assert out.detail["fire"]["value"] == 1.0 and out.value == 1.0
    burn = [status(100, "on_fire"), status(460, "on_fire", 0)]
    pool = [(140, 230, 30, 10, WATER)]  # 40 cells from the player: at hand
    at_hand = physics(tmp_path / "b", track=standing(900), patches=pool, events=burn)
    assert at_hand.detail["fire"]["value"] == 0.0
    bottle = [{"frame": 50, "type": "pickup", "item": "bottle", "detail": "water", "id": 9}]
    carried = physics(tmp_path / "c", track=standing(900), events=[*bottle, *burn])
    assert carried.detail["fire"]["value"] == 0.0
    far = physics(tmp_path / "d", track=standing(900), patches=[(400, 230, 30, 10, WATER)],
                  events=burn)  # fmt: skip
    assert far.value is None and "no water at hand" in far.reason  # waiting was all it could do
    oiled = physics(tmp_path / "e", track=standing(900),
                    events=[status(50, "oiled"), status(100, "on_fire"),
                            status(460, "on_fire", 0)])  # fmt: skip
    assert oiled.detail["fire"]["value"] == 1.0  # oiled it burns 720 frames: 360 was cut short
    dead = physics(tmp_path / "f", track=standing(900),
                   events=[status(100, "on_fire"), death(300, "fire")])  # fmt: skip
    assert dead.detail["fire"]["value"] == 0.0
    still = physics(tmp_path / "g", track=standing(200), events=[status(150, "on_fire")])
    assert still.value is None and "still burning" in still.reason


def test_only_a_dive_that_used_half_the_breath_is_an_opportunity(tmp_path):
    pool = [(80, 180, 60, 60, WATER)]  # the head of a box at (100, 200) is under water
    dip = walk([(0, 100, 150), (100, 100, 150), (101, 100, 200), (200, 100, 200),
                (201, 100, 150), (900, 100, 150)])  # fmt: skip
    short = physics(tmp_path / "a", track=dip, patches=pool,
                    events=[status(100, "wet"), status(900, "wet", 0)])  # fmt: skip
    assert short.value is None and short.opportunities == 0  # 100 of 420 frames: no question
    long = physics(tmp_path / "b", track=standing(900), patches=pool,
                   events=[status(100, "wet"), status(800, "wet", 0)])  # fmt: skip
    assert long.detail["deep_water"]["value"] == pytest.approx(1.0)
    drown = [damage(f, 7.5, "contact") for f in (500, 530, 560)]
    wet = physics(tmp_path / "c", track=standing(900), patches=pool,
                  events=[status(100, "wet"), *drown, status(800, "wet", 0)])  # fmt: skip
    assert wet.detail["deep_water"]["value"] == pytest.approx(1 - 22.5 / 30)
    shallow = physics(tmp_path / "d", track=standing(900), patches=[(80, 210, 60, 40, WATER)],
                      events=[status(100, "wet"), status(800, "wet", 0)])  # fmt: skip
    assert shallow.value is None  # wet, but the head stayed above the surface
    unrecorded = physics(tmp_path / "e", track=standing(900), patches=pool, recorded=False,
                         events=[status(100, "wet"), status(800, "wet", 0)])  # fmt: skip
    assert unrecorded.detail["deep_water"]["value"] is None  # the PNG alone is no record


def test_the_first_contact_metric_feeds_n4_in_the_profile(tmp_path):
    root = write_run(tmp_path / "run", track=standing(900),
                     events=[status(100, "on_fire"), status(160, "wet"),
                             status(160, "on_fire", 0)])  # fmt: skip
    caps = evaluate_run(root)["capabilities"]
    assert caps["N4"]["score"] == pytest.approx(100.0)
    assert caps["N4"]["metrics"] == [
        {"name": "first_contact_physics", "weight": 1.0, "value": 1.0, "n": 1}
    ]


def test_without_decisions_the_time_of_a_read_is_unknown_and_reading_counts(tmp_path):
    t = [{"kind": "opening", "text": OPENING}, *turn(6, ("workspace_read", {"path": "chem.md"}))]
    m = metrics_of(notes_run(tmp_path, t, decisions=[]))["notes_recall"]
    assert m.value == pytest.approx(1.0) and "not known" in m.reason
