"""`python -m noitabench eval <family folder>`: every game evaluated, `family_profile.json`, and the
control family (`--control`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from family_runs import GAME_1, GAME_3, example_family, make_game
from noitabench.eval.cli import main as eval_main
from noitabench.eval.family import FAMILY_FORMAT, write_family_profile
from noitabench.eval.metrics.growth import GROWTH_METRICS
from noitabench.harness.cli import main as harness_main


def run_json(*argv: str, capsys) -> tuple[int, dict]:
    code = eval_main([*argv, "--json"])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip().startswith("{") else {})


# ------------------------------------------------------------------------------ one family
def test_a_family_folder_gets_every_profile_and_a_family_profile(tmp_path, capsys):
    fam = example_family(tmp_path)
    assert eval_main([str(fam)]) == 0
    table = capsys.readouterr().out
    for name in ("run-01", "run-02", "run-03", *GROWTH_METRICS, "mean, later games"):
        assert name in table, name
    assert str(fam / "family_profile.json") in table
    for n in (1, 2, 3):
        assert (fam / f"run-0{n}" / "profile.json").exists()

    doc = json.loads((fam / "family_profile.json").read_text())
    assert doc["format"] == FAMILY_FORMAT == "cogbench-family-profile/0"
    assert doc["family_dir"] == "fam" and doc["evaluator"]["version"] == "0.5.0"
    assert doc["model"] == {"provider": "fake", "model": "m"} and doc["rule_seed"] == 0
    first, second, third = doc["games"]
    assert [g["run"] for g in doc["games"]] == ["run-01", "run-02", "run-03"]
    assert first["growth"] is None  # game 1 is the baseline
    assert first["depth"] == 30.0 and third["depth"] == 65.0
    assert first["hp_lost"] == 110.0 and third["hp_lost"] == 65.0  # the whole game
    assert first["decisions"] == 210 and third["decisions"] == 200
    assert first["end"] == "dead" and first["cost_usd"] == 0.01 and first["world_seed"] == 1
    for g in doc["games"]:
        single = json.loads((fam / g["run"] / "profile.json").read_text())
        assert g["composite"] == single["composite"] and g["ability_mean"] == single["ability_mean"]
    assert set(second["growth"]) == set(GROWTH_METRICS)
    assert second["growth"]["growth_depth"]["value"] == 0.5
    assert third["growth"]["growth_depth"]["value"] == pytest.approx(0.75, abs=1e-3)
    assert third["growth"]["growth_harm"]["status"] == "measured"
    assert third["growth"]["cross_game_gain"]["status"] == "not_measured"
    assert doc["growth"]["baseline"] == "run-01"
    mean = doc["growth"]["mean"]
    assert mean["growth_depth"]["value"] == pytest.approx((0.5 + 0.75) / 2, abs=1e-3)
    assert mean["growth_depth"]["measured_games"] == 2 and mean["growth_depth"]["later_games"] == 2
    assert mean["growth_pace"]["value"] == pytest.approx((0.5 + 0.70) / 2, abs=1e-3)
    assert mean["cross_game_gain"] == {"value": None, "measured_games": 0, "later_games": 2}
    assert doc["encounters"] == {}  # no encounter was met
    assert "control" not in doc


def test_json_quiet_and_out(tmp_path, capsys):
    fam = example_family(tmp_path)
    code, doc = run_json(str(fam), capsys=capsys)
    assert code == 0 and doc["format"] == "cogbench-family-profile/0"
    assert (fam / "family_profile.json").exists()
    assert eval_main([str(fam), "--quiet"]) == 0 and capsys.readouterr().out == ""
    where = tmp_path / "elsewhere" / "family.json"
    assert eval_main([str(fam), "--quiet", "--out", str(where)]) == 0
    assert json.loads(where.read_text())["family_dir"] == "fam"


def test_a_single_run_folder_is_evaluated_as_before(tmp_path, capsys):
    fam = example_family(tmp_path)
    assert eval_main([str(fam / "run-03"), "--out", str(tmp_path / "p.json")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("run-03 (agent): composite") and "family" not in out.splitlines()[0]
    assert (tmp_path / "p.json").exists() and not (fam / "family_profile.json").exists()
    assert not (fam / "run-03" / "profile.json").exists()  # --out moved it


def test_an_unreadable_game_is_an_entry_with_the_error(tmp_path, capsys):
    fam = example_family(tmp_path)
    (fam / "run-02" / "entities.jsonl").unlink()
    code, doc = run_json(str(fam), capsys=capsys)
    assert code == 0
    bad = doc["games"][1]
    assert bad["run"] == "run-02" and "entities.jsonl" in bad["error"] and "composite" not in bad
    assert doc["games"][2]["growth"]["growth_depth"]["status"] == "measured"
    assert doc["growth"]["mean"]["growth_depth"]["later_games"] == 1
    for g in (doc["games"][0], doc["games"][2]):
        assert "error" not in g
    (fam / "run-01" / "entities.jsonl").unlink()
    (fam / "run-03" / "entities.jsonl").unlink()
    assert eval_main([str(fam)]) == 2


def test_the_family_profile_is_never_written_into_a_workspace(tmp_path, capsys):
    fam = example_family(tmp_path)
    with pytest.raises(ValueError, match="workspace folder"):
        write_family_profile({}, tmp_path / "workspace" / "family_profile.json")
    assert eval_main([str(fam), "--out", str(tmp_path / "workspace_start" / "f.json")]) == 2
    assert "workspace folder" in capsys.readouterr().err


def test_a_family_takes_no_world_files(tmp_path, capsys):
    fam = example_family(tmp_path)
    assert eval_main([str(fam), "--world-files", "a.png", "b.json"]) == 2
    assert "single run" in capsys.readouterr().err


def test_a_folder_can_be_named_by_a_dot(tmp_path, capsys, monkeypatch):
    """`eval .` inside a game, and inside a family: the folder's own name still tells the family."""
    fam = example_family(tmp_path)
    monkeypatch.chdir(fam / "run-03")
    assert eval_main([".", "--quiet"]) == 0
    profile = json.loads((fam / "run-03" / "profile.json").read_text())
    assert profile["run_dir"] == "run-03"
    by_name = {m["name"]: m for m in profile["metrics"]}
    assert by_name["growth_depth"]["status"] == "measured"  # run-01 was found as game 1
    monkeypatch.chdir(fam / "run-03" / "world")
    assert eval_main(["../.."]) == 0  # a family folder through ..
    assert "family fam:" in capsys.readouterr().out
    monkeypatch.chdir(fam)
    assert eval_main([".", "--quiet"]) == 0
    assert json.loads((fam / "family_profile.json").read_text())["family_dir"] == "fam"


# ----------------------------------------------------------------------------------- control
CONTROL_3 = {
    "depth": 40.0,
    "frames": 800,
    "hurt": ((100, 20.0), (200, 20.0), (300, 20.0), (400, 20.0), (700, 10.0)),
    "decisions": GAME_1["decisions"],
}


def control_family(tmp_path: Path, **third) -> Path:
    ctl = tmp_path / "ctl"
    make_game(ctl / "run-01", **{**GAME_1, "cleared": True})
    make_game(ctl / "run-02", **{**GAME_1, "cleared": True})
    make_game(ctl / "run-03", **{**CONTROL_3, "cleared": True, **third})
    return ctl


def test_a_control_family_adds_the_memory_effect(tmp_path, capsys):
    fam, ctl = example_family(tmp_path), control_family(tmp_path)
    code, doc = run_json(str(fam), "--control", str(ctl), capsys=capsys)
    assert code == 0
    control = doc["control"]
    assert control["family_dir"] == "ctl" and control["workspace_cleared"] is True
    assert control["scored"] is False and control["paired_games"] == [2, 3]
    assert "note" not in control
    effect = control["memory_effect"]
    # growth_depth: family (0.5, 0.75), control (0.5, 0.5 + 0.1 / 0.7 / 2)
    ctl_depth = (0.5 + (1 + 0.1 / 0.7) / 2) / 2
    assert effect["growth_depth"]["family"] == pytest.approx(0.625, abs=1e-3)
    assert effect["growth_depth"]["control"] == pytest.approx(ctl_depth, abs=1e-3)
    assert effect["growth_depth"]["value"] == pytest.approx(0.625 - ctl_depth, abs=2e-3)
    assert effect["growth_depth"]["pairs"] == 2
    assert effect["growth_harm"]["value"] == pytest.approx(0.125, abs=1e-3)
    assert effect["growth_pace"]["value"] == pytest.approx(0.100, abs=1e-3)
    assert effect["cross_game_gain"] == {"value": None, "pairs": 0, "family": None, "control": None}
    assert [g["run"] for g in control["games"]] == ["run-01", "run-02", "run-03"]
    assert (ctl / "run-03" / "profile.json").exists()  # the control's games were evaluated too
    assert not (ctl / "family_profile.json").exists()  # but its family file is its own command

    eval_main([str(fam), "--control", str(ctl)])
    table = capsys.readouterr().out
    assert "memory effect against control ctl" in table and "display only" in table


def test_a_control_that_did_not_clear_the_workspace_is_noted(tmp_path, capsys):
    fam = example_family(tmp_path)
    ctl = tmp_path / "ctl"
    for n, spec in (("run-01", GAME_1), ("run-02", GAME_1), ("run-03", CONTROL_3)):
        make_game(ctl / n, **spec)  # cleared stays False
    code, doc = run_json(str(fam), "--control", str(ctl), capsys=capsys)
    assert code == 0 and doc["control"]["workspace_cleared"] is False
    assert "emptied" in doc["control"]["note"]


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"model": {"provider": "fake", "model": "other"}}, "model"),
        ({"rule_seed": 4}, "rule seed"),
        ({"seed": 2}, "world seed"),
    ],
)
def test_a_control_must_share_model_rule_seed_and_world_seeds(tmp_path, capsys, change, needle):
    fam, ctl = example_family(tmp_path), control_family(tmp_path, **change)
    assert eval_main([str(fam), "--control", str(ctl)]) == 2
    err = capsys.readouterr().err
    assert "game 3" in err and needle in err and "not the same experiment" in err
    assert not (fam / "family_profile.json").exists()  # nothing half-written


def test_a_control_must_start_at_the_same_game(tmp_path, capsys):
    """A control whose first folder is run-02 has another game 1: nothing to pair with."""
    fam = example_family(tmp_path)
    ctl = tmp_path / "ctl"
    make_game(ctl / "run-02", **{**GAME_1, "cleared": True})
    make_game(ctl / "run-03", **{**CONTROL_3, "cleared": True})
    assert eval_main([str(fam), "--control", str(ctl)]) == 2
    assert "game 1 is run 1 in the family, run 2 in the control" in capsys.readouterr().err


def test_an_unreadable_game_one_still_leaves_the_later_games_to_pair(tmp_path, capsys):
    fam, ctl = example_family(tmp_path), control_family(tmp_path)
    (fam / "run-01" / "entities.jsonl").unlink()
    code, doc = run_json(str(fam), "--control", str(ctl), capsys=capsys)
    assert code == 0 and "error" in doc["games"][0]
    assert doc["control"]["paired_games"] == [2, 3]
    # nothing was compared with the lost game 1, so there is no effect to show
    assert all(
        e["value"] is None and e["pairs"] == 0 for e in doc["control"]["memory_effect"].values()
    )


def test_a_control_needs_a_family_with_games_to_pair(tmp_path, capsys):
    fam = example_family(tmp_path)
    assert eval_main([str(fam), "--control", str(tmp_path / "missing")]) == 2
    assert "not a family folder" in capsys.readouterr().err
    one = tmp_path / "one"
    make_game(one / "run-01", **GAME_1)
    assert eval_main([str(fam), "--control", str(one)]) == 2  # only game 1 in common
    assert "no later game" in capsys.readouterr().err
    other = tmp_path / "other"
    make_game(other / "run-07", **GAME_1)
    assert eval_main([str(fam), "--control", str(other)]) == 2
    assert "no game of the family" in capsys.readouterr().err


def test_a_control_needs_a_family_folder_on_the_left_too(tmp_path, capsys):
    ctl = control_family(tmp_path)
    solo = make_game(tmp_path / "solo", **GAME_3)
    assert eval_main([str(solo), "--control", str(ctl)]) == 2
    assert "needs a family folder" in capsys.readouterr().err


# --------------------------------------------------------------- a family the harness made
@pytest.fixture(scope="module")
def fake_family(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("harness")
    fam = base / "fam"
    code = harness_main(
        ["run", "--provider", "fake", "--model", "fake", "--world-seed", "3", "--runs", "3",
         "--max-decisions", "4", "--out", str(fam), "--workspaces-dir", str(base / "ws"),
         "--family", "fam"]
    )  # fmt: skip
    assert code == 0
    return fam


def test_a_family_from_the_fake_model(fake_family, capsys):
    assert eval_main([str(fake_family)]) == 0
    capsys.readouterr()
    doc = json.loads((fake_family / "family_profile.json").read_text())
    first, *later = doc["games"]
    assert first["growth"] is None and len(later) == 2
    assert doc["model"] == {"provider": "fake", "model": "fake"} and doc["rule_seed"] == 0
    for g in later:
        assert g["growth"]["growth_depth"]["status"] == "measured"
        # the fake model barely walks: no shared stretch worth comparing, and no scene met
        for name in ("growth_harm", "growth_pace", "cross_game_gain"):
            assert g["growth"][name]["status"] == "not_measured" and g["growth"][name]["reason"]
    for n in (1, 2, 3):
        run = json.loads((fake_family / f"run-0{n}" / "profile.json").read_text())
        assert run["evaluator"]["version"] == "0.5.0"
    second = json.loads((fake_family / "run-02" / "profile.json").read_text())
    reasons = {m["name"]: m["reason"] for m in second["metrics"]}
    assert reasons["growth_depth"].startswith("depth ")
    first_profile = json.loads((fake_family / "run-01" / "profile.json").read_text())
    assert all(
        "no earlier game" in m["reason"]
        for m in first_profile["metrics"]
        if m["name"] in GROWTH_METRICS
    )
