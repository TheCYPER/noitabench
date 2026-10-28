"""The evaluation of real runs: the scripted bot on a generated world, and the CP3 model run.

The bot passes all nine must-pass scenes and reaches the bottom, so its profile should show it.
The CP3 run (`runs/cp3-haiku-42`, a Claude Haiku game that died in layer 2) is read-only and
only used if it is there (`runs/` is not in git).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from noitabench.eval import evaluate_run

REPO = Path(__file__).resolve().parents[3]
CP3 = REPO / "runs" / "cp3-haiku-42"
MUST_PASS = {"E02", "E06", "E07", "E08", "E12", "E16", "E22", "E23"}


@pytest.fixture(scope="module")
def bot_run(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bot") / "bot-42"
    env = {**os.environ, "PYTHONPATH": str(REPO / "python")}
    cmd = [
        sys.executable,
        "-m",
        "noitabench.bots.descend",
        "--world-seed",
        "42",
        "--no-enemies",
        "--no-seal-fallback",
        "--record",
        str(out),
    ]
    done = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    return out


@pytest.fixture(scope="module")
def bot_profile(bot_run: Path) -> dict:
    return evaluate_run(bot_run)


def test_the_bot_visits_and_passes_every_must_pass_scene(bot_profile):
    seen = {e["id"]: [v for v in e["visits"] if v["must_pass"]] for e in bot_profile["encounters"]}
    assert {eid for eid, vs in seen.items() if vs} == MUST_PASS
    assert sum(len(vs) for vs in seen.values()) == 9  # E23 is placed twice
    for eid, vs in seen.items():
        for v in vs:
            assert v["scored"] and v["score"] >= 0.5, (eid, v["reasons"])


def test_the_bot_opens_the_seal_with_the_assembled_key(bot_profile):
    e06 = next(e for e in bot_profile["encounters"] if e["id"] == "E06")["visits"][0]
    assert e06["facts"]["opened"] and e06["facts"]["key_blast"]
    assert e06["facts"]["parts_before"] == e06["facts"]["parts"] == 2
    assert e06["score"] == pytest.approx(1.0)
    key = next(m for m in bot_profile["metrics"] if m["name"] == "key_assembly")
    assert key["value"] == 1.0


def test_the_bot_reaches_the_bottom_and_scores_high_overall(bot_profile):
    assert bot_profile["source"] == "bot" and bot_profile["model"] is None
    assert bot_profile["depth"]["score"] > 99 and bot_profile["depth"]["reached_sealed_room"]
    assert 45 < bot_profile["composite"] < 70  # the discount: seven covered, the rest thin
    assert bot_profile["composite"] == pytest.approx(
        0.8 * bot_profile["ability_mean"] + 0.2 * bot_profile["depth"]["score"], abs=0.01
    )
    assert bot_profile["depth"]["deepest_y"] == bot_profile["depth"]["deepest_raw_y"]
    assert not bot_profile["depth"]["capped_at_seal"]
    assert bot_profile["outcome"]["died"] is False
    caps = bot_profile["capabilities"]
    assert caps["C"]["covered"] and caps["C"]["score"] > 95
    assert all(caps[n]["score"] is not None for n in ("N1", "N3", "N5", "N9"))
    assert bot_profile["steps"]["decisions"] is None  # the bot writes no decisions.jsonl
    assert any("decisions.jsonl" in n for n in bot_profile["evaluator"]["notes"])


def test_the_bot_profile_names_what_it_could_not_measure(bot_profile):
    by_name = {m["name"]: m for m in bot_profile["metrics"]}
    assert by_name["decisions_per_layer"]["status"] == "not_measured"
    assert by_name["inspect_before_hazard"]["status"] == "not_measured"
    assert by_name["route_efficiency"]["status"] == "measured"


def cut_run(run: Path, out: Path, frame: int) -> Path:
    """A copy of the recording `run` as if it had stopped at `frame` (rows past it dropped; the
    world files are shared; `frames.bin` is left out, the first grid answers)."""
    out.mkdir(parents=True)
    for name in ("entities.jsonl", "events.jsonl"):
        kept = [
            line
            for line in (run / name).read_text().splitlines()
            if line.strip() and json.loads(line)["frame"] <= frame
        ]
        (out / name).write_text("\n".join(kept) + "\n")
    meta = json.loads((run / "meta.json").read_text()) | {"last_frame": frame, "run_id": out.name}
    (out / "meta.json").write_text(json.dumps(meta))
    (out / "world").symlink_to((run / "world").resolve())
    return out


def test_a_run_that_stops_early_scores_less_than_one_that_goes_on(bot_run, bot_profile, tmp_path):
    """The reason for the discount: under the first rule the bot cut at frame 800 (one capability
    covered, a perfect score on it) scored 84, above the same run cut at 2400 (81) and near the
    whole run (91)."""
    early = evaluate_run(cut_run(bot_run, tmp_path / "cut800", 800))
    middle = evaluate_run(cut_run(bot_run, tmp_path / "cut2400", 2400))
    assert early["composite"] < middle["composite"] < bot_profile["composite"]
    assert early["composite"] < 0.6 * bot_profile["composite"]
    assert len(early["covered"]) < len(middle["covered"]) <= len(bot_profile["covered"])
    assert early["depth"]["score"] < middle["depth"]["score"] < bot_profile["depth"]["score"]


def test_the_cli_profile_equals_the_function_result(bot_run, bot_profile, tmp_path):
    from noitabench.eval.cli import main

    out = tmp_path / "p.json"
    assert main([str(bot_run), "--out", str(out), "--quiet"]) == 0
    assert json.loads(out.read_text()) == json.loads(json.dumps(bot_profile))


@pytest.mark.skipif(not CP3.exists(), reason="runs/cp3-haiku-42 is not on this machine")
def test_the_cp3_model_run_is_read_as_an_agent_run():
    p = evaluate_run(CP3)
    assert p["source"] == "agent"
    assert p["model"] == {"provider": "anthropic", "model": "claude-haiku-5-5"}
    assert p["outcome"]["died"] and p["outcome"]["over"] == "dead"
    assert p["steps"]["decisions"] == 235
    assert p["cost"]["usd"] == pytest.approx(0.051279)
    assert 45 < p["depth"]["score"] < 65 and not p["depth"]["reached_sealed_room"]
    visited = {e["id"] for e in p["encounters"] if e["visits"]}
    assert {"E16", "E08", "E07", "E22"} <= visited
    assert 20 < p["composite"] < 45
    assert p["test_awareness"]["checked_texts"] > 50
    assert p["attribution"] and p["attribution"][0]["capability"] == "C2"
    assert p["attribution"][0]["outcome"] == "died"


def test_a_repeat_of_a_real_game_is_no_change_and_a_shorter_one_is_worse(
    bot_run, bot_profile, tmp_path
):
    """The same recording twice: every scene scores what it scored, so the change is nil. The
    same game cut at frame 2400 as game 2: it reached less deep and met fewer scenes."""
    import shutil

    fam = tmp_path / "fam"
    shutil.copytree(bot_run, fam / "run-01")
    shutil.copytree(bot_run, fam / "run-02")
    cut_run(bot_run, fam / "run-03", 2400)
    by_name = {m["name"]: m for m in evaluate_run(fam / "run-02")["metrics"]}
    gain = by_name["cross_game_gain"]
    scenes = gain["detail"]["scenes"]
    assert len(scenes) >= 7 and all(s["g"] in (0.0, None) for s in scenes)
    assert gain["status"] == "measured" and gain["value"] == 0.5
    assert gain["opportunities"] == sum(1 for s in scenes if s["g"] is not None)
    assert gain["detail"]["only_game_1"] == [] and gain["detail"]["only_this_game"] == []
    assert by_name["growth_depth"]["status"] == "not_measured"  # both on the floor of the room
    assert by_name["growth_harm"]["value"] == 0.5  # the bot is never hurt, or equally so
    assert by_name["growth_pace"]["status"] == "not_measured"  # the bot writes no decisions.jsonl
    shorter = {m["name"]: m for m in evaluate_run(fam / "run-03")["metrics"]}
    assert shorter["growth_depth"]["value"] < 0.5
    assert shorter["cross_game_gain"]["detail"]["only_game_1"]  # scenes it never reached
