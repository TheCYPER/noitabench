"""Recordings follow `cogbench-rec/0` (contract section 5), read back with an independent reader."""

from __future__ import annotations

from pathlib import Path

import noitabench_core
import pytest
from sim_recording_reader import read_events, read_frames, read_meta


def scene() -> noitabench_core.Env:
    env = noitabench_core.Env(70, 50, 12)
    env.fill_rect(0, 40, 70, 10, "rock")
    env.paint(20, 10, 5, "water")
    env.paint(45, 30, 4, "gunpowder")
    env.ignite(45, 30)
    return env


def test_meta_frames_events(tmp_path: Path) -> None:
    env = scene()
    run = tmp_path / "demo-x"
    env.start_recording(run, 3, notes="hello")
    env.step_frames(100)
    summary = env.stop_recording()

    meta = read_meta(run)
    assert meta["format"] == "cogbench-rec/0"
    assert meta["run_id"] == "demo-x"
    assert meta["world"] == {"width": 70, "height": 50}
    assert meta["materials_format"] == "cogbench-materials/0"
    assert (meta["seed"], meta["rule_seed"], meta["frame_stride"]) == (12, 0, 3)
    assert meta["notes"] == "hello" and meta["created"].endswith("Z")

    frames = read_frames(run)
    numbers = [f.frame for f in frames]
    assert numbers == [*range(0, 100, 3), 100]
    assert summary["frames"] == len(frames) and summary["last_frame"] == 100
    last = frames[-1]
    assert (last.x0, last.y0, last.w, last.h) == (0, 0, 70, 50)
    assert last.pixels == env.grid()

    events = read_events(run)
    assert any(e["type"] == "explosion" for e in events)
    assert all(isinstance(e["frame"], int) for e in events)


def test_rect_recording(tmp_path: Path) -> None:
    env = scene()
    env.start_recording(tmp_path / "r", 10, rect=(10, 5, 30, 20))
    env.step_frames(20)
    env.stop_recording()
    frames = read_frames(tmp_path / "r")
    assert [f.frame for f in frames] == [0, 10, 20]
    assert {(f.x0, f.y0, f.w, f.h) for f in frames} == {(10, 5, 30, 20)}
    world = env.grid()
    for y in range(20):
        row = frames[-1].pixels[y * 30 : (y + 1) * 30]
        assert row == world[(5 + y) * 70 + 10 : (5 + y) * 70 + 40]


def test_recording_errors(tmp_path: Path) -> None:
    env = scene()
    with pytest.raises(ValueError, match="frame_stride"):
        env.start_recording(tmp_path / "a", 0)
    with pytest.raises(ValueError, match="must lie inside"):
        env.start_recording(tmp_path / "b", 1, rect=(60, 40, 20, 20))
    env.start_recording(tmp_path / "c", 1)
    with pytest.raises(ValueError, match="already running"):
        env.start_recording(tmp_path / "d", 1)
    env.stop_recording()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(RuntimeError, match="creating"):
        env.start_recording(blocker / "run", 1)


def test_restore_is_refused_while_recording(tmp_path: Path) -> None:
    env = scene()
    blob = env.snapshot()
    env.start_recording(tmp_path / "run", 2)
    env.step_frames(4)
    with pytest.raises(ValueError, match="stop it before restoring"):
        env.restore(blob)
    env.stop_recording()
    env.restore(blob)
    assert env.frame == 0
