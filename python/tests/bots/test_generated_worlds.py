"""The bot on worlds of the generator, with the enemies left out.

Every must-pass scene of these worlds is a true chokepoint (brick seams and shells), so the way
down leads through nine footprints. The bot has to go through each of them, without tunnelling
under the scenes that are not dig zones, solve the chain of E07 and the river of E02 with their
own bottles, open the seal with the world's own key (the bomb and the modifier, assembled in the
edit hall), and keep out of its blast; the same world must give the same run. The seeds are
played in processes at once."""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest
from noitabench.bots.descend import Summary, play_world

SEEDS = (0, 1, 2, 4, 5, 6)
MIN_REACHED = 5
FRAME_BUDGET = 9000
SCENES = ["E16", "E08", "E07", "E23", "E22", "E23", "E12", "E02", "E06"]  # (sorted below)
DUG = {"E08", "E12"}  # the dig zones: digging is their way
Run = tuple[Summary, list[dict]]


def play(seed: int, out: Path) -> Run | None:
    return play_world(seed, 0, out, enemies=False, max_frames=FRAME_BUDGET, seal_fallback=False)


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Run]:
    out = tmp_path_factory.mktemp("worlds")
    with ProcessPoolExecutor(max_workers=min(len(SEEDS), os.cpu_count() or 1)) as pool:
        futures = {
            seed: pool.submit(
                play_world,
                seed,
                0,
                out / str(seed),
                enemies=False,
                max_frames=FRAME_BUDGET,
                seal_fallback=False,
            )
            for seed in SEEDS
        }
        found = {seed: f.result() for seed, f in futures.items()}
    for seed, run in found.items():
        if run is None:
            print(f"seed {seed}: the generator makes no world")
    return {seed: run for seed, run in found.items() if run is not None}


def test_the_bot_reaches_the_sealed_room_on_five_worlds(runs: dict[int, Run]) -> None:
    assert len(runs) >= MIN_REACHED, f"only {sorted(runs)} of {SEEDS} could be generated"
    failed = {seed: s.stop_reason for seed, (s, _) in runs.items() if not s.reached_bottom}
    assert not failed, failed
    for seed, (s, _) in runs.items():
        assert s.reached_seal and s.seal_opened and s.deaths == 0, (seed, s)
        assert s.frames < FRAME_BUDGET, (seed, s.frames)
        assert s.depth_fraction > 0.95, (seed, s.depth_fraction)


def test_the_bot_goes_through_every_must_pass_scene_and_digs_only_where_the_scene_is_dug(
    runs: dict[int, Run],
) -> None:
    """No bypass: each footprint is entered and left downwards, in the order of depth; the
    scenes that are not dig zones are passed without the digging wand."""
    for seed, (s, _) in runs.items():
        ids = [v["eid"] for v in s.scenes]
        assert sorted(ids) == sorted(SCENES), (seed, ids)
        assert s.scenes_passed == len(s.scenes) == 9, (seed, s.scenes)
        passed = [v["passed"] for v in s.scenes]  # (the scenes come shallowest first)
        assert all(v["entered"] is not None and v["entered"] < v["passed"] for v in s.scenes), seed
        assert all(v["from_above"] for v in s.scenes), (seed, "a footprint was entered sideways")
        assert passed == sorted(passed), (seed, "the scenes were not passed in order of depth")
        assert not any(v["died"] for v in s.scenes), seed
        for v in s.scenes:
            if v["eid"] not in DUG:
                assert v["dig_frames"] == 0, (seed, v["eid"], "tunnelled under a scene")
        assert any(v["dig_frames"] > 0 for v in s.scenes if v["eid"] == "E12"), seed  # E12: dug


def test_e07_and_e02_are_solved_with_their_own_bottles(runs: dict[int, Run]) -> None:
    for seed, (s, log) in runs.items():
        events = [e["event"] for e in log]
        assert "filled" in events and "chain_lava" in events, seed  # E07: the pool's liquid
        assert next(e for e in log if e["event"] == "chain_lava")["cleared"] is True, seed
        bomb = [r for r in s.key_results if r["detail"] == "BOMB"]
        assert bomb and bomb[0]["result"] == "fetched", (seed, s.key_results)
        assert s.hazard_solved and s.seal_keys_fetched == s.seal_keys == 2, seed  # E02: crusted


def test_the_seal_is_opened_with_the_worlds_own_key_and_the_bot_keeps_clear_of_the_blast(
    runs: dict[int, Run],
) -> None:
    """E12's modifier and E02's bomb are fetched, put in a wand in that order in the edit hall
    and the bomb is thrown from far enough away: no test API (`Game.blast`, `give_spell`)."""
    for seed, (s, log) in runs.items():
        assert s.seal_key_result == "used" and not s.fallback_used, (seed, s)
        assert s.fallback_tool == "" and s.bombs >= 1 and s.deaths == 0, seed
        radius = next(e["radius"] for e in log if e["event"] == "breaker_assembled")
        blasts = [e for e in log if e["event"] == "blast"]
        assert blasts and all(e["distance"] > radius for e in blasts), (seed, radius, blasts)


def test_the_wands_are_edited_only_at_the_edit_station(runs: dict[int, Run]) -> None:
    """With no enemies there is no fight to arm for: the only edits are the ones that put the
    two spells of the key into a wand and take them out again, in the hall above the plug (the
    game wrapper of the bot refuses an edit anywhere else)."""
    for seed, (s, _) in runs.items():
        assert set(s.wand_edits) == {"edit_station"} and s.wand_edits["edit_station"] >= 4, seed


def test_the_bot_stays_near_the_generators_main_path(runs: dict[int, Run]) -> None:
    for seed, (s, _) in runs.items():
        assert s.waypoints > 100, seed
        assert s.waypoints_passed >= 0.4 * s.waypoints, (seed, s.waypoints_passed, s.waypoints)


def test_the_same_world_gives_the_same_run(runs: dict[int, Run], tmp_path: Path) -> None:
    seed = next(iter(runs))
    again = play(seed, tmp_path)
    assert again is not None
    a, b = runs[seed][0], again[0]
    assert a.state_hash == b.state_hash and a.frames == b.frames
    assert a.scenes == b.scenes and runs[seed][1] == again[1]
