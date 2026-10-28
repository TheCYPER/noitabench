"""L1: the workspace folder, its quotas and its walls."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from noitabench.agent import AgentSession
from noitabench.agent.errors import CommandError
from noitabench.harness import ConfigError
from noitabench.harness.workspace import (
    CODE_QUOTA,
    NOTES_QUOTA,
    Workspace,
    family_name,
    normalize,
)


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "ws")


def code_of(err: pytest.ExceptionInfo[CommandError]) -> str:
    return err.value.code


# -- files ----------------------------------------------------------------------------------------


def test_write_read_edit_search_list_delete(ws: Workspace) -> None:
    out = ws.write("notes/chem.md", "water puts out fire\nlava + water = rock\n", False)
    assert out["path"] == "notes/chem.md" and out["chars_left"] == NOTES_QUOTA - 40
    assert ws.read("notes/chem.md")["text"].startswith("water puts out fire")
    ws.write("notes/chem.md", "acid eats dirt\n", True)
    assert ws.read("notes/chem.md")["text"].endswith("acid eats dirt\n")
    ws.edit("notes/chem.md", "acid eats dirt", "acid eats rock")
    hits = ws.search("ACID")["hits"]
    assert hits == [{"path": "notes/chem.md", "line": 3, "text": "acid eats rock"}]
    listing = ws.list()
    assert [f["path"] for f in listing["files"]] == ["notes/chem.md"]
    assert listing["quota"]["notes"]["limit"] == NOTES_QUOTA
    ws.delete("notes/chem.md")
    assert ws.list()["files"] == []
    with pytest.raises(CommandError) as err:
        ws.read("notes/chem.md")
    assert code_of(err) == "no_such_note"


def test_a_name_without_a_folder_goes_to_notes(ws: Workspace) -> None:
    ws.write("chem.md", "x", False)
    assert (ws.root / "notes" / "chem.md").read_text() == "x"
    assert ws.read("notes/chem.md")["text"] == "x"
    assert normalize("skills/a.md") == ("skills/a.md", "skills")
    assert normalize("a/b.md") == ("notes/a/b.md", "notes")


def test_edit_needs_exactly_one_match(ws: Workspace) -> None:
    ws.write("a.md", "aa bb aa", False)
    for old in ("aa", "zz", ""):
        with pytest.raises(CommandError) as err:
            ws.edit("a.md", old, "x")
        assert code_of(err) == "edit_failed"
    assert ws.read("a.md")["text"] == "aa bb aa"


def test_read_in_parts(ws: Workspace) -> None:
    ws.write("scripts/big.py", "x" * 30_000, False)
    first = ws.read("scripts/big.py")
    assert len(first["text"]) == 20_000 and first["more_from"] == 20_000
    rest = ws.read("scripts/big.py", offset=first["more_from"])
    assert len(rest["text"]) == 10_000 and "more_from" not in rest


# -- quotas ---------------------------------------------------------------------------------------


def test_notes_and_skills_share_one_allowance(ws: Workspace) -> None:
    ws.write("notes/a.md", "a" * 5_000, False)
    ws.write("skills/b.md", "b" * 3_000, False)  # exactly full: 8,000
    assert ws.quota("notes").left == 0
    with pytest.raises(CommandError) as err:
        ws.write("skills/c.md", "c", False)
    assert code_of(err) == "notes_full"
    assert "8000" in err.value.message and "delete" in err.value.message
    assert not (ws.root / "skills" / "c.md").exists()  # nothing was written


def test_a_rewrite_counts_only_the_difference(ws: Workspace) -> None:
    ws.write("notes/a.md", "a" * 7_000, False)
    ws.write("notes/a.md", "b" * 7_900, False)  # replaces: fits
    with pytest.raises(CommandError):
        ws.write("notes/a.md", "c" * 101, True)  # appends: one character over
    assert ws.read("notes/a.md")["chars"] == 7_900


def test_plugins_and_scripts_have_their_own_larger_allowance(ws: Workspace) -> None:
    ws.write("notes/a.md", "a" * NOTES_QUOTA, False)  # the notes are full...
    ws.write("plugins/p.py", "p" * 40_000, False)  # ...which does not touch the code area
    ws.write("scripts/s.py", "s" * 24_000, False)
    assert ws.quota("plugins").left == 0
    with pytest.raises(CommandError) as err:
        ws.write("scripts/t.py", "t", False)
    assert code_of(err) == "code_full" and str(CODE_QUOTA) in err.value.message
    ws.delete("plugins/p.py")
    ws.write("scripts/t.py", "t", False)  # room again


def test_edit_over_the_quota_is_refused_and_leaves_the_file(ws: Workspace) -> None:
    ws.write("notes/a.md", "x" * 7_990 + "end", False)
    with pytest.raises(CommandError) as err:
        ws.edit("notes/a.md", "end", "end" + "y" * 100)
    assert code_of(err) == "notes_full"
    assert ws.read("notes/a.md")["text"].endswith("end")


def test_file_count_is_limited(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "w", max_files=3)
    for i in range(3):
        ws.write(f"n{i}.md", "x", False)
    with pytest.raises(CommandError) as err:
        ws.write("n3.md", "x", False)
    assert code_of(err) == "too_many_files"
    ws.write("n0.md", "y", False)  # an existing file may still be rewritten


# -- walls ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "/etc/passwd",
        "notes/../../x",
        "notes/../x",
        "notes//x",
        "notes/./x",
        "~/x",
        "..",
        ".",
        "",
        "   ",
        "notes\\..\\x",
        "notes/x\x00y",
        "notes/\nx",
        ".hidden",
        "notes/.hidden",
        "notes/ok/../../../x",
        "a" * 200,
        "notes/a/b/c/d/e.md",
        "notes",
        "notes/",
        "notes/x*y",
        "notes/x|y",
    ],
)
def test_paths_cannot_leave_or_be_odd(ws: Workspace, path: str) -> None:
    with pytest.raises(CommandError) as err:
        ws.write(path, "x", False)
    assert code_of(err) == "bad_path"
    for op in (lambda: ws.read(path), lambda: ws.delete(path), lambda: ws.edit(path, "a", "b")):
        with pytest.raises(CommandError):
            op()
    outside = sorted(p.name for p in ws.root.parent.iterdir())
    assert outside == ["ws"]  # nothing next to the workspace


def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    secret = tmp_path / "secret.txt"
    secret.write_text("do not read", encoding="utf-8")
    os.symlink(secret, ws.root / "notes" / "link.md")
    with pytest.raises(CommandError):
        ws.read("notes/link.md")
    with pytest.raises(CommandError):
        ws.write("notes/link.md", "overwrite", False)
    assert secret.read_text() == "do not read"
    assert ws.list()["files"] == []  # a link is not a file of the workspace
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    os.symlink(outside_dir, ws.root / "skills" / "dir")
    with pytest.raises(CommandError):
        ws.write("skills/dir/x.md", "escape", False)
    assert list(outside_dir.iterdir()) == []


def test_text_is_checked(ws: Workspace) -> None:
    with pytest.raises(CommandError) as err:
        ws.write("a.md", "bad\x00text", False)
    assert code_of(err) == "bad_text"
    with pytest.raises(CommandError):
        ws.search("  ")


def test_unicode_names_and_text(ws: Workspace) -> None:
    ws.write("notes/化学.md", "水加岩浆 = 岩石", False)
    assert ws.search("岩浆")["hits"][0]["path"] == "notes/化学.md"
    assert ws.list()["files"][0]["chars"] == 9  # characters, not bytes


def test_the_quota_counts_what_was_written_not_what_line_ends_become(ws: Workspace) -> None:
    # a CR LF pair is two characters on disk and on the way back; it must not be read as one
    # (that would let the player keep twice the allowance in a file)
    ws.write("notes/a.md", "\r\n" * 2_000, False)
    assert ws.read("notes/a.md")["chars"] == 4_000 and ws.quota("notes").used == 4_000
    with pytest.raises(CommandError) as err:
        ws.write("notes/b.md", "\r\n" * 2_001, False)
    assert code_of(err) == "notes_full"
    ws.write("notes/b.md", "\r\n" * 2_000, False)
    assert ws.quota("notes").left == 0
    total = sum(p.stat().st_size for p in (ws.root / "notes").iterdir())
    assert total == NOTES_QUOTA  # ASCII: one byte per character


def test_text_that_cannot_be_stored_is_refused_with_a_reason(ws: Workspace) -> None:
    with pytest.raises(CommandError) as err:
        ws.write("notes/a.md", "lone surrogate \ud800", False)
    assert code_of(err) == "bad_text"
    assert ws.list()["files"] == []  # nothing half-written, no temp file left
    assert not [p for p in (ws.root / "notes").iterdir()]


def test_a_file_and_a_folder_cannot_share_a_name(ws: Workspace) -> None:
    ws.write("notes/x.md", "file", False)
    with pytest.raises(CommandError) as err:
        ws.write("notes/x.md/y.md", "inside a file", False)
    assert code_of(err) == "bad_path" and "file, not a folder" in err.value.message
    ws.write("notes/d/e.md", "deep", False)
    with pytest.raises(CommandError) as err:
        ws.write("notes/d", "a file where a folder is", False)
    assert code_of(err) == "bad_path" and "folder" in err.value.message
    assert ws.read("notes/d/e.md")["text"] == "deep"
    assert not [p for p in (ws.root / "notes").iterdir() if p.name.startswith(".tmp-")]


def test_without_a_code_area_the_larger_allowance_is_out_of_reach(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws", code_area=False)
    # the code folders are ordinary names then: the file lands in notes/ and counts there
    done = ws.write("scripts/big.md", "x" * 7_000, False)
    assert done["path"] == "notes/scripts/big.md" and done["chars_left"] == 1_000
    with pytest.raises(CommandError) as err:
        ws.write("plugins/more.md", "y" * 2_000, False)
    assert code_of(err) == "notes_full"
    assert list(ws.usage()) == ["notes"]  # the player is not shown a second allowance
    assert "code" not in ws.list()["quota"]
    # files that an earlier run left in the code folders are neither listed nor counted
    (ws.root / "plugins" / "old.py").write_text("print(1)")
    assert ws.file_names() == ["notes/scripts/big.md"]
    with pytest.raises(CommandError):
        ws.read("plugins/old.py")
    assert Workspace(tmp_path / "ws").usage()["code"]["used"] == 8  # the default has both


def test_the_run_gives_the_code_area_only_to_the_layers_that_use_it(
    tmp_path: Path, run_config, make_game
) -> None:
    from noitabench.harness import run_family
    from noitabench.harness.adapters.scripted import Say, ScriptedAdapter, call

    script = [
        Say.tools(call("workspace_write", path="scripts/a.md", text="hi")),
        *([Say.tools(call("wait", ticks=1))] * 5),
    ]
    cfg = run_config(max_decisions=2, family="nocode")
    summary = run_family(cfg, adapter=ScriptedAdapter(script), game_factory=make_game)[0]
    assert summary["workspace"]["files"] == ["notes/scripts/a.md"]
    assert list(summary["workspace"]["usage"]) == ["notes"]


# -- lifetime -------------------------------------------------------------------------------------


def test_files_survive_a_new_workspace_object(tmp_path: Path) -> None:
    root = tmp_path / "workspaces" / "family"
    Workspace(root).write("notes/a.md", "remember", False)
    again = Workspace(root)
    assert again.read("notes/a.md")["text"] == "remember"
    again.clear()
    assert Workspace(root).list()["files"] == []
    assert sorted(p.name for p in root.iterdir()) == ["notes", "plugins", "scripts", "skills"]


def test_snapshot_restore_and_copy(ws: Workspace, tmp_path: Path) -> None:
    ws.write("notes/a.md", "one", False)
    ws.write("scripts/s.py", "two", False)
    snap = ws.snapshot()
    ws.clear()
    ws.restore(snap)
    assert ws.snapshot() == snap
    ws.copy_to(tmp_path / "copy")
    assert (tmp_path / "copy" / "scripts" / "s.py").read_text() == "two"


def test_temp_files_are_neither_listed_nor_counted(ws: Workspace) -> None:
    (ws.root / "notes" / ".tmp-leftover").write_text("x" * 7_000)
    assert ws.list()["files"] == [] and ws.quota("notes").used == 0


def test_family_names(tmp_path: Path) -> None:
    assert family_name("runs/h1 test!") == "runs-h1-test"
    assert family_name("../../etc") == "etc"
    with pytest.raises(ConfigError):
        family_name("///")


# -- as the notes of a session --------------------------------------------------------------------


def test_the_agent_notes_commands_use_the_workspace(ws: Workspace, make_game) -> None:
    session = AgentSession(make_game(), memory=ws)
    answer = session.decide("memory_write(path='skills/x.md', text='hello')")
    assert answer["results"][0]["ok"], answer["results"]
    assert ws.read("skills/x.md")["text"] == "hello"
    answer = session.decide("memory_write(path='../x', text='escape')")
    assert not answer["results"][0]["ok"] and answer["results"][0]["code"] == "bad_path"
    answer = session.decide(f"memory_write(path='b.md', text='{'z' * 9000}')")
    assert answer["results"][0]["code"] == "notes_full"


def test_every_notes_command_answers_without_hidden_fields(ws: Workspace, make_game) -> None:
    session = AgentSession(make_game(), memory=ws)  # `paranoid` is on: a hidden key would raise
    texts = [
        "memory_write(path='notes/a.md', text='lava is hot')",
        "memory_write(path='notes/a.md', text=' really', append=true)",
        "memory_read(path='notes/a.md')",
        "memory_search(query='LAVA')",
        "memory_edit(path='notes/a.md', old='hot', new='very hot')",
        "memory_list",
    ]
    for text in texts:
        answer = session.decide(text)
        assert answer["results"][0]["ok"], (text, answer["results"])
    assert ws.read("notes/a.md")["text"] == "lava is very hot really"
    assert answer["results"][0]["result"]["files"][0]["path"] == "notes/a.md"
