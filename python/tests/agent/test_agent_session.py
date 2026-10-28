"""Reproducibility, `decisions.jsonl`, snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import GROUND, Arena, settle, write_arena
from noitabench.agent import AgentSession, SessionConfig, ViewConfig, render_text
from noitabench.agent.recorder import digest

COMMANDS = [
    "walk_to(x=44)",
    "pickup",
    "edit_wand(op=place, wand=0, slot=1, spell=0)",
    "walk_to(x=54)",
    "pickup",
    "aim(target=longleg); fire(until=target_dead)",
    "drink(amount=60)",
    "move(right, ticks=7)",
    "jump(right)",
    "fire(ticks=5)",
    "inspect(wand=0)",
    "wait(ticks=12)",
    "kick; swap_wand(1)",
    "bogus",
    "walk_to(x=120)",
]


def fresh(tmp_path: Path, name: str, recording: Path | None = None, **view: Any) -> AgentSession:
    arena: Arena = write_arena(tmp_path / name)
    game = arena.game(seed=11)
    settle(game)
    game.spawn_enemy("longleg", 80, GROUND)
    game.give_bottle("water", 400)
    return AgentSession(
        game,
        config=SessionConfig(view=ViewConfig(**view)),
        recording_dir=recording,
    )


def play(s: AgentSession, commands: list[str]) -> list[dict[str, Any]]:
    return [s.observe(), *(s.decide(c) for c in commands)]


def test_same_world_same_commands_same_everything(tmp_path: Path) -> None:
    a, b = fresh(tmp_path, "a", screenshot=True), fresh(tmp_path, "b", screenshot=True)
    ra, rb = play(a, COMMANDS), play(b, COMMANDS)
    assert ra == rb  # every observation, stop reason, event and decision frame
    assert [x["frame"] for x in ra] == [x["frame"] for x in rb]
    assert a.state_hash() == b.state_hash()
    assert [render_text(x) for x in ra] == [render_text(x) for x in rb]


def test_the_result_does_not_depend_on_whether_it_is_recorded(tmp_path: Path) -> None:
    plain = fresh(tmp_path, "plain")
    recorded = fresh(tmp_path, "rec", recording=tmp_path / "run")
    ra, rb = play(plain, COMMANDS), play(recorded, COMMANDS)
    recorded.close()
    assert ra == rb and plain.state_hash() == recorded.state_hash()


def test_decisions_jsonl_sits_next_to_the_recording(tmp_path: Path) -> None:
    run = tmp_path / "run"
    s = fresh(tmp_path, "w", recording=run)
    answers = play(s, COMMANDS)
    summary = s.close()
    assert summary["decisions"] == len(COMMANDS) and summary["recording"]["last_frame"] == s.frame
    assert {p.name for p in run.iterdir()} >= {
        "meta.json", "frames.bin", "events.jsonl", "entities.jsonl", "decisions.jsonl",
    }  # fmt: skip
    lines = [json.loads(x) for x in (run / "decisions.jsonl").read_text().splitlines()]
    assert len(lines) == len(COMMANDS)
    first = lines[0]
    assert first["index"] == 1 and first["stop_reason"] == "start"
    assert first["frame"] == answers[0]["frame"]
    assert first["command"] == [{"name": "walk_to", "args": {"x": 44}}]
    assert first["observation_digest"] == digest(answers[0])
    for prev, line, shown in zip(lines, lines[1:], answers[1:], strict=False):
        assert line["index"] == prev["index"] + 1
        assert line["stop_reason"] == prev["result"]["reason"]  # what the agent was told
        assert line["frame"] == prev["frame"] + prev["frames"]  # time passes only inside commands
        assert line["observation_digest"] == digest(shown)  # a digest of what it was shown
    start = lines[0]["frame"]
    assert all((line["frame"] - start) % 10 == 0 for line in lines)  # every decision on a tick
    assert lines[-2]["command"] == "bogus" and lines[-2]["ok"] is False  # what it sent, as sent


def test_decisions_jsonl_is_the_same_for_the_same_run(tmp_path: Path) -> None:
    for name in ("one", "two"):
        s = fresh(tmp_path, name, recording=tmp_path / f"run-{name}")
        play(s, COMMANDS)
        s.close()
    one = (tmp_path / "run-one" / "decisions.jsonl").read_text()
    two = (tmp_path / "run-two" / "decisions.jsonl").read_text()
    assert one == two and one.count("\n") == len(COMMANDS)


def test_meta_of_the_recording_still_names_the_world_seeds(tmp_path: Path) -> None:
    run = tmp_path / "run"
    s = fresh(tmp_path, "w", recording=run)
    s.decide("wait")
    s.close()
    meta = json.loads((run / "meta.json").read_text())
    assert meta["format"] == "cogbench-rec/0" and meta["seed"] == 11 and "decisions" not in meta


def test_snapshot_and_restore_reproduce_the_rest_of_the_episode(tmp_path: Path) -> None:
    s = fresh(tmp_path, "w", screenshot=True)
    play(s, COMMANDS[:7])
    s.interrupts.enable("hp_low", hp_below=40)
    blob = s.snapshot()
    rest = play(s, COMMANDS[7:])
    end_hash = s.state_hash()
    s.restore(blob)
    again = play(s, COMMANDS[7:])
    assert again[1:] == rest[1:] and s.state_hash() == end_hash
    # restored into a new session on the same world
    other = fresh(tmp_path, "other", screenshot=True)
    other.restore(blob)
    assert play(other, COMMANDS[7:])[1:] == rest[1:]
    assert other.interrupts.enabled == s.interrupts.enabled


def test_a_snapshot_keeps_the_notes(tmp_path: Path) -> None:
    from noitabench.agent import InMemoryNotes

    game = write_arena(tmp_path / "n").game()
    settle(game)
    s = AgentSession(game, memory=InMemoryNotes())
    s.decide("memory_write('a.md', 'one')")
    blob = s.snapshot()
    s.decide("memory_write('a.md', 'two')")
    s.restore(blob)
    assert s.decide("memory_read('a.md')")["results"][0]["result"]["text"] == "one"


def test_restore_is_refused_while_recording(tmp_path: Path) -> None:
    s = fresh(tmp_path, "w", recording=tmp_path / "run")
    blob = s.snapshot()
    with pytest.raises(ValueError, match="recording is running"):
        s.restore(blob)
    s.close()


def test_a_garbage_snapshot_is_refused(session: AgentSession) -> None:
    with pytest.raises(ValueError, match="not a session snapshot"):
        session.restore(json.dumps({"format": "other"}).encode())


def test_looking_changes_nothing(tmp_path: Path) -> None:
    quiet, curious = fresh(tmp_path, "a"), fresh(tmp_path, "b")
    for c in COMMANDS:
        quiet.decide(c)
        curious.observe()
        curious.decide(c)
        curious.observe()
    assert quiet.state_hash() == curious.state_hash() and quiet.frame == curious.frame


def test_a_session_on_a_world_without_a_player_is_refused() -> None:
    from noitabench.game import Game

    with pytest.raises(ValueError, match="no player"):
        AgentSession(Game(30, 30, 1))


def test_the_session_content_must_match_the_built_game(tmp_path: Path, game: Any) -> None:
    import shutil

    from noitabench.agent.content import CONTENT

    bad = tmp_path / "content"
    shutil.copytree(CONTENT, bad)
    doc = json.loads((bad / "materials.json").read_text())
    doc["materials"][1]["key"] = "mist"
    (bad / "materials.json").write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="does not match the built game"):
        AgentSession(game, config=SessionConfig(content_dir=bad))
