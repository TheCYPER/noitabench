"""`python -m noitabench harness ...`: the commands, on the scripted `fake` provider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from noitabench.__main__ import main as top_main
from noitabench.harness.cli import main


def run_cli(*argv: str) -> int:
    return main(list(argv))


def test_prompt_prints_the_system_prompt_and_the_tools(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli("prompt") == 0
    out = capsys.readouterr().out
    assert "Get as deep as you can." in out and "- budget:" in out and "- walk_to:" in out
    assert "- workspace_write:" in out and "memory_write" not in out.split("=== tools ===")[1]


def test_estimate_prints_figures_and_warns_about_a_small_budget(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run_cli(
        "estimate", "--provider", "anthropic", "--model", "claude-haiku-5-5",
        "--max-decisions", "1000", "--runs", "3", "--budget-usd", "0.01",
    )  # fmt: skip
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert code == 0 and 0.1 < data["typical_usd"] < 5 and data["runs"] == 3
    assert data["context_limit_tokens"] == 90_000
    assert data["total_typical_usd"] == pytest.approx(3 * data["typical_usd"], rel=1e-3)
    assert "above the budget" in captured.err


def test_estimate_prints_the_assumptions_it_used(capsys: pytest.CaptureFixture[str]) -> None:
    def estimate(*argv: str) -> dict[str, float]:
        assert run_cli("estimate", "--max-decisions", "1000", *argv) == 0
        return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]

    haiku = estimate("--provider", "anthropic", "--model", "claude-haiku-5-5")
    assert haiku["calls_per_decision"] == 0.2 and haiku["output_tokens"] == 600
    assert haiku["model_calls"] == 200
    flash = ("--provider", "deepseek", "--model", "deepseek-flash")
    assert estimate(*flash)["output_tokens"] == 4_500  # it thinks unless told not to
    assert estimate(*flash, "--thinking", "off")["output_tokens"] == 600
    given = estimate(*flash, "--output-tokens", "3000", "--calls-per-decision", "1.15")
    assert given["output_tokens"] == 3_000 and given["calls_per_decision"] == 1.15
    assert given["model_calls"] == 1_150
    assert given["typical_usd"] > estimate(*flash)["typical_usd"]


@pytest.mark.parametrize("bad", ["0", "-1", "nan"])
def test_calls_per_decision_must_be_above_zero(
    bad: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_cli(
        "estimate", "--provider", "anthropic", "--model", "claude-haiku-5-5",
        "--calls-per-decision", bad,
    )  # fmt: skip
    assert code == 2 and "calls per decision" in capsys.readouterr().err


def test_estimate_can_measure_a_real_first_view(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_cli(
        "estimate", "--provider", "anthropic", "--model", "claude-haiku-5-5", "--world-seed", "1"
    )
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and 1_500 < data["observation_chars"] < 8_000


def test_an_unpriced_model_is_refused_with_a_message(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_cli("estimate", "--provider", "openai", "--model", "gpt-9") == 2
    assert "no price is known" in capsys.readouterr().err
    code = run_cli(
        "estimate", "--provider", "openai", "--model", "gpt-9",
        "--price-input", "1", "--price-output", "3",
    )  # fmt: skip
    assert code == 0
    assert (
        run_cli("estimate", "--provider", "openai", "--model", "gpt-9", "--price-input", "1") == 2
    )


def test_bad_choices_are_config_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = [
        "run",
        "--provider",
        "fake",
        "--model",
        "fake",
        "--world-seed",
        "1",
        "--out",
        str(tmp_path / "x"),
    ]
    assert run_cli(*base, "--context", "server") == 2
    assert "Anthropic" in capsys.readouterr().err
    assert run_cli(*base, "--layers", "L0,L1,L9") == 2
    assert run_cli(*base, "--no-text", "--no-ascii") == 2
    assert not (tmp_path / "x").exists()  # nothing was started


def test_a_scripted_game_on_a_generated_world(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "runs" / "h1"
    code = top_main([
        "harness", "run", "--provider", "fake", "--model", "fake", "--world-seed", "1",
        "--rule-seed", "7", "--max-decisions", "6", "--out", str(out),
        "--workspaces-dir", str(tmp_path / "ws"), "--budget-usd", "1",
    ])  # fmt: skip
    assert code == 0
    printed = capsys.readouterr().out
    assert "game 1/1 (world seed 1): decision_limit" in printed and "6 decisions" in printed
    summary = json.loads((out / "summary.json").read_text())
    assert summary["rule_seed"] == 7 and summary["world_seed"] == 1
    assert summary["result"]["over"] == "decision_limit"
    assert summary["family"] == "h1"
    assert summary["layers"] == ["L0", "L1", "L2", "L3", "L4", "L5"]  # every layer that exists
    for name in (
        "world",
        "workspace",
        "harness.jsonl",
        "transcript.jsonl",
        "decisions.jsonl",
        "meta.json",
    ):
        assert (out / name).exists(), name
    meta = json.loads((out / "meta.json").read_text())
    assert meta["rule_seed"] == 7 and meta["seed"] != 7  # the world's and the rules' seeds
    # the first call of the policy wrote a note, and the note lives in the family's folder
    assert (tmp_path / "ws" / "h1" / "notes" / "log.md").read_text() == "walked about\n"


def test_a_family_in_text_mode_with_the_control_setting(tmp_path: Path) -> None:
    out = tmp_path / "fam"
    code = run_cli(
        "run", "--provider", "fake", "--model", "fake", "--world-seed", "3", "--runs", "2",
        "--mode", "text", "--clear-workspace", "--max-decisions", "4", "--out", str(out),
        "--workspaces-dir", str(tmp_path / "ws"), "--family", "ctl",
    )  # fmt: skip
    assert code == 0
    family = json.loads((out / "family.json").read_text())
    assert [r["world_seed"] for r in family["runs"]] == [3, 4]
    assert all(r["workspace_cleared_each_game"] and r["mode"] == "text" for r in family["runs"])
    assert (out / "run-01" / "summary.json").exists() and (
        out / "run-02" / "decisions.jsonl"
    ).exists()
    # in text mode the policy writes its note with memory_write, which reaches the same notebook;
    # the control setting then empties the notebook before the second game, which writes none
    assert (out / "run-01" / "workspace" / "notes" / "log.md").read_text() == "walked about"
    assert not (out / "run-02" / "workspace" / "notes" / "log.md").exists()


def test_a_used_run_folder_is_not_written_into_unless_asked(tmp_path: Path) -> None:
    out = tmp_path / "used"
    out.mkdir()
    (out / "old.txt").write_text("earlier run")
    args = [
        "run", "--provider", "fake", "--model", "fake", "--world-seed", "1",
        "--max-decisions", "2", "--out", str(out), "--workspaces-dir", str(tmp_path / "ws"),
    ]  # fmt: skip
    assert run_cli(*args) == 2
    assert not (out / "summary.json").exists()
    assert run_cli(*args, "--overwrite") == 0
    assert (out / "summary.json").exists() and (out / "old.txt").read_text() == "earlier run"


def test_the_scripted_provider_needs_no_model_name_the_others_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "nomodel"
    code = run_cli(
        "run", "--provider", "fake", "--world-seed", "1", "--max-decisions", "2",
        "--out", str(out), "--workspaces-dir", str(tmp_path / "ws"),
    )  # fmt: skip
    assert code == 0
    assert json.loads((out / "summary.json").read_text())["model"]["model"] == "fake"
    assert run_cli("estimate", "--provider", "anthropic") == 2
    assert "--model is required for the anthropic provider" in capsys.readouterr().err
    assert run_cli("run", "--provider", "openai", "--world-seed", "1", "--out", str(tmp_path)) == 2


def test_the_patience_flag_is_passed_on_and_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(patience: str, name: str) -> int:
        return run_cli(
            "run", "--provider", "fake", "--world-seed", "1", "--max-decisions", "2",
            "--out", str(tmp_path / name), "--workspaces-dir", str(tmp_path / "ws"),
            "--patience-s", patience,
        )  # fmt: skip

    assert run("0", "off") == 0 and run("120", "short") == 0
    assert run("-5", "bad") == 2 and "patience" in capsys.readouterr().err
    assert run("nan", "worse") == 2 and "patience" in capsys.readouterr().err
    assert not (tmp_path / "bad").exists() and not (tmp_path / "worse").exists()
    result = json.loads((tmp_path / "short" / "summary.json").read_text())["result"]
    assert result["model_wait_seconds"] == 0.0


def test_estimate_for_a_conversation_that_is_never_compacted_is_much_dearer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    common = ["estimate", "--provider", "anthropic", "--model", "claude-haiku-5-5"]
    assert run_cli(*common, "--max-decisions", "1000") == 0
    compacted = json.loads(capsys.readouterr().out)
    assert run_cli(*common, "--max-decisions", "1000", "--context", "none") == 0
    grows = json.loads(capsys.readouterr().out)
    assert compacted["summaries"] > 0 and grows["summaries"] == 0
    assert grows["context_limit_tokens"] is None
    assert grows["typical_usd"] > 5 * compacted["typical_usd"]  # the dear card above 100K tokens
