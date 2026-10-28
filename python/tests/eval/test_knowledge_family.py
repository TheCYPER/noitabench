"""A two-game family end to end: harness (fake model) -> notes-claims (claims from a file) -> eval.

The fake model walks a little and writes `notes/log.md`; game 2 begins with that notebook, which
the run folder keeps as `workspace_start/`. No model is called and nothing is paid."""

from __future__ import annotations

import json
from pathlib import Path

from noitabench.eval.cli import main as eval_main
from noitabench.eval.knowledge.claims import load_note_claims
from noitabench.eval.knowledge.claims_cli import main as claims_main
from noitabench.harness.cli import main as harness_main

N2_KNOWLEDGE = ("notes_accuracy", "notes_learned", "notes_used", "notes_corrected")


def tree(folder: Path) -> dict[str, str]:
    return {
        f.relative_to(folder).as_posix(): f.read_text(encoding="utf-8").strip()
        for f in sorted(folder.rglob("*"))
        if f.is_file()
    }


def test_the_second_game_is_evaluated_against_the_notebook_it_began_with(tmp_path, capsys):
    fam = tmp_path / "fam"
    code = harness_main(
        ["run", "--provider", "fake", "--model", "fake", "--world-seed", "3", "--runs", "2",
         "--max-decisions", "4", "--out", str(fam), "--workspaces-dir", str(tmp_path / "ws"),
         "--family", "e2e"]
    )  # fmt: skip
    assert code == 0
    first, second = fam / "run-01", fam / "run-02"
    assert tree(first / "workspace_start") == {}  # the family folder was new
    assert tree(second / "workspace_start") == tree(first / "workspace")
    assert tree(second / "workspace_start") == {"notes/log.md": "walked about"}

    source = tmp_path / "claims.json"
    source.write_text(
        json.dumps(
            {
                "notes/log.md": [
                    {"kind": "reaction", "a": "lava", "b": "water", "out": ["rock", "steam"],
                     "text": "walked about"},
                    {"kind": "property", "material": "oil", "property": "burns",
                     "text": "walked about"},
                ]
            }
        )
    )  # fmt: skip
    assert claims_main([str(fam), "--claims-from", str(source)]) == 0
    doc = load_note_claims(second)
    assert doc is not None and doc.start is not None and set(doc.start) == {"notes/log.md"}
    capsys.readouterr()

    assert eval_main([str(second), "--json", "--quiet"]) == 0
    profile = json.loads(capsys.readouterr().out)
    by_name = {m["name"]: m for m in profile["metrics"]}
    assert all(name in by_name for name in N2_KNOWLEDGE)
    assert (
        by_name["notes_accuracy"]["status"] == "measured"
        and by_name["notes_accuracy"]["value"] == 1.0
    )
    for name in ("notes_learned", "notes_used", "notes_corrected"):
        assert by_name[name]["status"] == "not_measured" and by_name[name]["reason"], name
    n2 = {m["name"] for m in profile["capabilities"]["N2"]["metrics"]}
    assert "notes_accuracy" in n2 and not {"notes_used", "notes_corrected"} & n2  # not measured
    assert (second / "profile.json").exists()
