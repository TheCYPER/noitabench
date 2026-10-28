"""The readable copy of the knowledge base, and the command that prints it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from noitabench.__main__ import main as noitabench_main
from noitabench.eval.knowledge.cli import main as knowledge_main
from noitabench.eval.knowledge.doc import recipe_lines, render_document
from noitabench.eval.knowledge.facts import build_knowledge
from noitabench.eval.knowledge.prompt import system_prompt
from noitabench.eval.knowledge.vocab import vocabulary

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "knowledge-base.md"


def test_the_committed_document_is_a_fresh_render():
    """Regenerate with `python -m noitabench knowledge --doc docs/knowledge-base.md`."""
    assert DOC.read_text(encoding="utf-8") == render_document()


def test_every_fact_but_the_recipes_has_exactly_one_line():
    text = render_document()
    for f in build_knowledge(0).facts:
        want = 0 if f.kind == "recipe" else 1
        assert text.count(f"`{f.id}`") == want, f.id
    lines = [ln for ln in text.splitlines() if ln.startswith("- ") and "`" in ln]
    assert len(lines) == sum(1 for f in build_knowledge(0).facts if f.kind != "recipe")


def test_the_document_holds_no_recipe():
    text = render_document()
    for seed in range(10):
        k = build_knowledge(seed)
        for sentence in recipe_lines(seed):
            assert sentence not in text
        for r in k.of_kind("recipe"):
            potion = vocabulary().potions[r.fields["potion"]].lower()
            ingredients = [vocabulary().materials[m].lower() for m in r.fields["inputs"]]
            for line in text.splitlines():
                # no line names a potion with its three ingredients
                assert not (
                    potion in line.lower() and all(i in line.lower() for i in ingredients)
                ), line
        assert "is mixed from" not in text
    assert "knowledge --seed N" in text  # how a researcher gets one seed's recipes


def test_the_document_is_grouped_by_tier_and_kind_and_marks_what_is_told():
    text = render_document()
    tiers = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert [t[:5] for t in tiers] == ["## 1.", "## 2.", "## 3."]
    assert " [told]" in text and "(scenes: E02 Lava river" in text and "E05 The vault" in text
    first_game = text.index("## 2.")
    assert text.index("### Reactions", first_game) < text.index(
        "### What drinking does", first_game
    )


def test_the_command_writes_the_document_and_prints_one_seeds_recipes(tmp_path, capsys):
    out = tmp_path / "sub" / "kb.md"
    assert knowledge_main(["--doc", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == render_document()
    assert knowledge_main(["--seed", "3"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed == recipe_lines(3) and len(printed) == 8
    assert knowledge_main(["--seed", "3", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["rule_seed"] == 3 and any(f["kind"] == "recipe" for f in doc["facts"])
    with pytest.raises(SystemExit):
        knowledge_main([])
    with pytest.raises(SystemExit):
        knowledge_main(["--json"])


def test_python_m_noitabench_dispatches_both_commands(tmp_path, capsys):
    assert noitabench_main(["knowledge", "--seed", "0"]) == 0
    assert "is mixed from" in capsys.readouterr().out
    assert noitabench_main(["notes-claims", str(tmp_path / "nothing")]) == 2


CJK = re.compile("[\u4e00-\u9fff]")


def test_the_knowledge_base_and_the_extractor_prompt_are_english():
    """The sentences, the document and the prompt use `name_en` and hold no Chinese."""
    for seed in (0, 3):
        for f in build_knowledge(seed).facts:
            assert not CJK.search(f.note), f.id
    assert not CJK.search(render_document())
    assert not CJK.search(system_prompt())
    assert "Drinking water: makes you wet" in render_document()
    assert "lava + water -> rock + steam" in render_document()
    assert recipe_lines(0)[0].count(" is mixed from ") == 1


def test_the_knowledge_package_never_reads_a_chinese_name():
    for path in (REPO / "python" / "noitabench" / "eval" / "knowledge").glob("*.py"):
        assert "name_zh" not in path.read_text(encoding="utf-8"), path.name
