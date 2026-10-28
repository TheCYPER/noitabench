"""Reproducibility: same seed and calls give the same grid, events and recordings."""

from __future__ import annotations

import hashlib
from pathlib import Path

import noitabench_core
from sim_recording_reader import read_events, read_frames


def build(seed: int) -> noitabench_core.Env:
    env = noitabench_core.Env(96, 64, seed)
    env.fill_rect(0, 56, 96, 8, "rock")
    env.fill_rect(30, 40, 4, 16, "wood")
    env.paint(20, 10, 6, "water")
    env.paint(70, 12, 5, "oil")
    env.paint(48, 30, 5, "sand")
    env.paint(60, 52, 3, "gunpowder")
    env.paint(62, 45, 2, "lava")
    env.paint(31, 39, 1, "fire")
    return env


def fingerprint(env: noitabench_core.Env) -> tuple[str, list[dict], int]:
    return hashlib.sha256(env.grid()).hexdigest(), env.events(), env.state_hash()


def test_same_seed_twice_is_identical() -> None:
    a, b = build(7), build(7)
    a.step_frames(400)
    b.step_frames(400)
    fa, fb = fingerprint(a), fingerprint(b)
    assert fa == fb
    assert len(fa[1]) > 20, "the scene should produce events"


def test_a_different_seed_differs() -> None:
    a, b = build(7), build(8)
    a.step_frames(400)
    b.step_frames(400)
    assert a.state_hash() != b.state_hash()


def test_step_in_pieces_equals_one_go() -> None:
    a, b = build(3), build(3)
    a.step_frames(300)
    for _ in range(30):
        b.step_frames(10)
    assert a.state_hash() == b.state_hash()


def test_snapshot_restore_continue_is_identical() -> None:
    uninterrupted = build(5)
    uninterrupted.step_frames(120)
    uninterrupted.events()
    blob = uninterrupted.snapshot()
    uninterrupted.step_frames(200)
    expected = fingerprint(uninterrupted)

    resumed = build(5)  # any other state: restore replaces everything
    resumed.step_frames(17)
    resumed.restore(blob)
    assert resumed.frame == 120
    resumed.step_frames(200)
    assert fingerprint(resumed) == expected


def test_recordings_of_two_runs_are_byte_identical(tmp_path: Path) -> None:
    runs = []
    for name in ("a", "b"):
        env = build(9)
        run = tmp_path / name
        env.start_recording(run, 4, created="2026-10-26T00:00:00Z", run_id="same")
        env.step_frames(240)
        env.stop_recording()
        runs.append(run)
    for file in ("meta.json", "frames.bin", "events.jsonl"):
        assert (runs[0] / file).read_bytes() == (runs[1] / file).read_bytes(), file
    assert len(read_frames(runs[0])) == 1 + 60
    assert read_events(runs[0])
