"""`python -m noitabench.bots.descend`: the recording and the summary files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mini_world import write_world
from noitabench.bots import descend
from noitabench.bots.terrain import Materials


def test_the_cli_plays_a_world_and_writes_the_recording(
    tmp_path: Path, mats: Materials, capsys: pytest.CaptureFixture[str]
) -> None:
    files = write_world(tmp_path / "w", mats)
    rec = tmp_path / "runs" / "descend-5"
    code = descend.main(
        [
            "--world-seed", "5", "--no-enemies", "--record", str(rec), "--stride", "4",
            "--world-files", str(files.png), str(files.json),
        ]
    )  # fmt: skip
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    summary = json.loads((rec / "descend.json").read_text())
    assert printed == summary
    assert summary["reached_bottom"] and summary["fallback_used"] and summary["deaths"] == 0
    meta = json.loads((rec / "meta.json").read_text())
    assert meta["format"] == "cogbench-rec/0" and meta["frame_stride"] == 4
    assert meta["run_id"] == "descend-5" and "no enemies" in meta["notes"]
    assert meta["last_frame"] == summary["frames"]
    assert (rec / "frames.bin").stat().st_size > 0
    entities = [json.loads(line) for line in (rec / "entities.jsonl").read_text().splitlines()]
    assert entities[0]["entities"][0]["kind"] == "player"
    log = [json.loads(line) for line in (rec / "bot_log.jsonl").read_text().splitlines()]
    assert next(e["event"] for e in log if e["event"].startswith("seal")) == "seal_fallback"
    events = [json.loads(line) for line in (rec / "events.jsonl").read_text().splitlines()]
    assert any(e["type"] == "explosion" for e in events)  # the blast that opened the seal


def test_the_exit_code_says_whether_the_bottom_was_reached(
    tmp_path: Path, mats: Materials, capsys: pytest.CaptureFixture[str]
) -> None:
    files = write_world(tmp_path / "w", mats)
    code = descend.main(
        [
            "--world-seed", "5", "--no-enemies", "--no-seal-fallback",
            "--world-files", str(files.png), str(files.json),
        ]
    )  # fmt: skip
    assert code == 1
    assert json.loads(capsys.readouterr().out)["stop_reason"] == "the seal stayed closed"


def test_require_key_fails_the_run_instead_of_falling_back(
    tmp_path: Path, mats: Materials, capsys: pytest.CaptureFixture[str]
) -> None:
    files = write_world(tmp_path / "w", mats)
    code = descend.main(
        [
            "--world-seed", "5", "--no-enemies", "--require-key",
            "--world-files", str(files.png), str(files.json),
        ]
    )  # fmt: skip
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and not out["fallback_used"] and out["stop_reason"] == "the seal stayed closed"


def test_a_world_without_enemies_has_none_to_shoot(tmp_path: Path, mats: Materials) -> None:
    enemy = {"type": "spawn_enemy", "enemy": "longleg", "x": 70, "y": 69}
    files = write_world(tmp_path / "w", mats, enemies=[enemy])
    with_enemy = descend.prepare_world(5, 0, tmp_path / "a", enemies=True, existing=files)
    without = descend.prepare_world(5, 0, tmp_path / "b", enemies=False, existing=files)
    kinds = lambda f: [m["type"] for m in json.loads(f.json.read_text())["markers"]]
    assert "spawn_enemy" in kinds(with_enemy) and "spawn_enemy" not in kinds(without)
    assert with_enemy.png.read_bytes() == without.png.read_bytes() == files.png.read_bytes()
    assert with_enemy.png.parent == tmp_path / "a"  # a self-contained pair next to the recording


def test_there_is_no_perturbation_strength_any_more() -> None:
    """CP2: one reaction table for every rule seed; the rule seed only seeds the recipes."""
    with pytest.raises(SystemExit):
        descend.main(["--world-seed", "5", "--strength", "1"])
    assert "strength" not in " ".join(descend.parse_args(["--world-seed", "5"]).__dict__)


def test_the_summary_has_no_scenes_and_no_wand_edits_in_a_world_without_either(
    tmp_path: Path, mats: Materials
) -> None:
    files = write_world(tmp_path / "w", mats)
    bot = descend.Descent(files, enemies=False, max_frames=6000)
    s = bot.run()
    assert s.scenes == [] and s.scenes_passed == 0  # the mini world has no scenes
    assert s.wand_edits == {}  # (the fallback blasts the plug; no spell of the content does)
