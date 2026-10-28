"""L3, hooks: the game reacts to events for the player."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_worlds import GROUND, PIT_X, POOL_X, START_X, WALL_X
from noitabench.harness.hooks import MAX_HOOK_RUNS, MAX_HOOKS, fired_events
from noitabench.harness.sandbox import sandbox_available
from rig import arena_game, make_rig

pytestmark = pytest.mark.skipif(not sandbox_available(), reason="needs macOS sandbox-exec")

SAY_HI = "print('hook fired:', event['name'], '|', event['message'])\n"


def near_enemy(tmp_path: Path):
    game = arena_game(tmp_path / "arena", START_X)
    game.spawn_enemy("longleg", START_X + 18, GROUND)
    return make_rig(tmp_path / "rig", game=game)


# -- reading the answer ------------------------------------------------------------------------


def stop(reason: str, detail: str = "", also: tuple[str, ...] = (), message: str = "") -> dict:
    out: dict = {"reason": reason, "ticks": 1, "frames": 10}
    if detail:
        out["detail"] = detail
    if also:
        out["also"] = list(also)
    if message:
        out["message"] = message
    return out


def test_fired_events_reads_the_stops_of_every_command() -> None:
    answer = {
        "stop": stop("interrupted", "damage", ("new_enemy", "blocked"), "You took damage."),
        "results": [
            {"stop": stop("completed", "ticks", ("fell_in_liquid",))},
            {"stop": stop("interrupted", "damage", (), "again")},
        ],
    }
    assert fired_events(answer) == [
        ("damage", "You took damage."),
        ("new_enemy", "A creature came into view."),
        ("entered_liquid", "You are in a liquid."),
    ]
    assert fired_events({"stop": stop("time_limit"), "results": []}) == []
    assert fired_events({"stop": stop("invalid"), "results": []}) == []
    assert fired_events({"stop": stop("interrupted", "blocked"), "results": []}) == []
    hp = {"stop": stop("completed", "x", ("hp_low", "status_change")), "results": []}
    assert [e for e, _ in fired_events(hp)] == ["hp_below", "status_change"]


# -- the tools ------------------------------------------------------------------------------------


def test_interrupts_are_switched_through_the_session_and_cleared_again(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    on = rig.session.interrupts.enabled
    assert "fell_in_liquid" not in on and "damage" in on
    result = rig.call("hook_set", event="entered_liquid", action="interrupt")
    assert not result.is_error, result.content
    assert "fell_in_liquid" in rig.session.interrupts.enabled
    assert '"stops_on":["damage","new_enemy","status_change","entered_liquid"]' in result.content
    rig.call("hook_set", event="damage", action="interrupt", on=False)
    assert "damage" not in rig.session.interrupts.enabled
    listing = rig.call("hook_list").content
    assert '"id":"h1"' in listing and '"id":"h2"' in listing and '"on":false' in listing
    rig.call("hook_clear", id="h1")
    rig.call("hook_clear", id="h2")
    assert rig.session.interrupts.enabled == {"damage", "new_enemy", "status_change", "blocked"}
    assert rig.call("hook_clear", id="h9").content.startswith("no_such_hook")
    assert rig.decisions == 0  # hooks take no step


def test_a_second_switch_for_an_event_replaces_the_first(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.call("hook_set", event="new_material", action="interrupt")
    second = rig.call("hook_set", event="new_material", action="interrupt", on=False)
    assert "It replaces hook h1." in second.content
    assert "new_material" not in rig.session.interrupts.enabled
    assert rig.call("hook_list").content.count('"event":"new_material"') == 1


def test_hp_below_sets_the_threshold_and_keeps_only_one(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write("scripts/low.py", "print('low')")
    missing = rig.call("hook_set", event="hp_below", action="run", script="low")
    assert missing.content.startswith("bad_value")  # needs the HP
    ok = rig.call("hook_set", event="hp_below", action="run", script="low", value=40)
    assert not ok.is_error, ok.content
    assert rig.session.interrupts.hp_threshold == 40 and "hp_low" in rig.session.interrupts.enabled
    rig.call("hook_set", event="hp_below", action="interrupt", value=25)
    assert rig.session.interrupts.hp_threshold == 25
    assert rig.call("hook_list").content.count('"event":"hp_below"') == 1  # one hook, not two
    rig.call("hook_clear", id="all")
    assert "hp_low" not in rig.session.interrupts.enabled


def test_bad_arguments_are_refused_with_a_code(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write("scripts/ok.py", "print(1)")
    cases = [
        ({"event": "boredom", "action": "interrupt"}, "bad_event"),
        ({"event": "damage", "action": "shout"}, "bad_action"),
        ({"event": "damage", "action": "run", "script": "nothing"}, "no_such_script"),
        ({"event": "damage", "action": "run", "script": "../x"}, "bad_script"),
        ({"event": "damage", "action": "run"}, "bad_script"),
        ({"event": "damage", "action": "interrupt", "value": 3}, "bad_value"),
        ({"event": "damage", "action": "interrupt", "script": "ok"}, "bad_action"),
    ]
    for args, code in cases:
        result = rig.call("hook_set", **args)
        assert result.is_error and result.content.startswith(code), (args, result.content)
    assert rig.call("hook_list").content.startswith('{"hooks":[]')


def test_there_is_a_limit_on_hooks(tmp_path: Path) -> None:
    rig = make_rig(tmp_path / "rig")
    rig.write("scripts/a.py", "print(1)")
    for _ in range(3):
        assert not rig.call("hook_set", event="damage", action="run", script="a").is_error
    over = rig.call("hook_set", event="damage", action="run", script="a")
    assert over.content.startswith("too_many_hooks")
    made = 3
    for event in ("new_enemy", "status_change", "new_material", "entered_liquid"):
        for _ in range(3):
            if not rig.call("hook_set", event=event, action="run", script="a").is_error:
                made += 1
    assert made == MAX_HOOKS  # the twelfth was the last, whatever the event
    assert rig.call("hook_set", event="damage", action="interrupt").content.startswith(
        "too_many_hooks"
    )


# -- firing -----------------------------------------------------------------------------------------


def test_damage_runs_the_script_right_after_the_step_and_adds_its_output(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    rig.write("scripts/ouch.py", SAY_HI + "game.inspect(x=60, y=159)\nprint('looked')\n")
    assert not rig.call("hook_set", event="damage", action="run", script="ouch").is_error
    result = rig.call("wait", ticks=25)
    text = result.content
    assert "Stopped: interrupted (damage)" in text.split("Hook h1")[0]  # the step's own answer
    assert "Hook h1 (damage: You took damage.) ran scripts/ouch.py after Decision 2." in text
    assert "hook fired: damage | You took damage." in text and "looked" in text
    assert "Game commands run: 1. Steps used: 1." in text  # the script's look cost a step too
    assert rig.decisions == 2
    listing = rig.call("hook_list").content
    assert '"runs":1' in listing


def test_the_output_of_a_hook_goes_to_the_last_result_of_the_turn(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    rig.write("scripts/ouch.py", SAY_HI)
    rig.call("hook_set", event="damage", action="run", script="ouch")
    out = rig.turn(("wait", {"ticks": 25}), ("workspace_list", {}))
    assert "Hook h1" not in out.results[0].content
    assert "Hook h1 (damage" in out.results[1].content


def test_a_script_does_not_start_hooks_and_its_commands_are_capped(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    rig.write(
        "scripts/loop.py",
        "n = 0\ntry:\n    while True:\n        game.wait(ticks=1)\n        n += 1\n"
        "except game.LimitReached:\n    print('ran', n, 'commands')\n",
    )
    rig.call("hook_set", event="damage", action="run", script="loop")
    result = rig.call("wait", ticks=25)
    assert "ran 20 commands" in result.content
    assert result.content.count("Hook h1 (damage") == 1  # the waits in the script hurt too
    assert rig.decisions == 1 + 20


def test_a_script_that_fails_is_reported_and_the_game_goes_on(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    rig.write("scripts/bad.py", "print('start')\nraise RuntimeError('oops')\n")
    rig.call("hook_set", event="damage", action="run", script="bad")
    result = rig.call("wait", ticks=25)
    assert (
        "The script stopped with an error." in result.content
        and "RuntimeError: oops" in result.content
    )
    assert not rig.session.over
    rig.workspace.delete("scripts/bad.py")
    again = rig.call("wait", ticks=25)
    assert "could not run scripts/bad.py" in again.content or "Hook h1" not in again.content


def test_new_enemy_status_change_and_the_rest_each_fire(tmp_path: Path) -> None:
    # a creature comes into view
    game = arena_game(tmp_path / "a1", WALL_X + 20)
    game.spawn_enemy("longleg", WALL_X + 20 + 150, GROUND)
    rig = make_rig(tmp_path / "r1", game=game)
    rig.write("scripts/s.py", SAY_HI)
    rig.call("hook_set", event="new_enemy", action="run", script="s")
    result = rig.call("walk_to", x=WALL_X + 80)
    assert "hook fired: new_enemy | Came into view: longleg" in result.content

    # a new condition
    game = arena_game(tmp_path / "a2")
    game.give_bottle("oil", 400)
    rig = make_rig(tmp_path / "r2", game=game)
    rig.write("scripts/s.py", SAY_HI)
    rig.call("hook_set", event="status_change", action="run", script="s")
    result = rig.call("drink", amount=400)
    assert "hook fired: status_change | You are now oiled" in result.content

    # falling into a liquid
    rig = make_rig(tmp_path / "r3", spawn_x=POOL_X - 12)
    rig.write("scripts/s.py", SAY_HI)
    rig.call("hook_set", event="entered_liquid", action="run", script="s")
    result = rig.call("jump", direction="right")
    assert "hook fired: entered_liquid | You are in a liquid." in result.content

    # something new in view
    rig = make_rig(tmp_path / "r4", spawn_x=WALL_X + 20)
    rig.write("scripts/s.py", SAY_HI)
    rig.call("hook_set", event="new_material", action="run", script="s")
    rig.call("wait")  # learns what is in view
    result = rig.call("walk_to", x=PIT_X - 15)
    assert "hook fired: new_material | You see" in result.content

    # HP falls below the value
    game = arena_game(tmp_path / "a5")
    game.give_bottle("acid", 400)
    rig = make_rig(tmp_path / "r5", game=game)
    rig.write("scripts/s.py", SAY_HI + "print(event['value'])\n")
    rig.call("hook_set", event="damage", action="interrupt", on=False)
    rig.call("hook_set", event="hp_below", action="run", script="s", value=95)
    result = rig.call("drink", amount=400)
    assert (
        "hook fired: hp_below | Your HP is below 95." in result.content
        and "\n95.0" in result.content
    )


def test_switching_damage_off_lets_a_command_run_on_through_a_hit(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    interrupted = rig.call("wait", ticks=25)
    assert "interrupted (damage)" in interrupted.content
    rig = near_enemy(tmp_path / "second")
    rig.call("hook_set", event="damage", action="interrupt", on=False)
    rig.call("hook_set", event="status_change", action="interrupt", on=False)
    rig.call("hook_set", event="new_enemy", action="interrupt", on=False)
    through = rig.call("wait", ticks=25)
    assert "completed (ticks)" in through.content


def test_hooks_fire_for_decisions_made_inside_a_program(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    rig.write("scripts/ouch.py", SAY_HI)
    rig.call("hook_set", event="damage", action="run", script="ouch")
    result = rig.call("run_code", code="a = game.wait(ticks=25)\nprint(a['stop']['detail'])")
    assert result.content.index("damage") < result.content.index("Hook h1")
    assert "hook fired: damage" in result.content
    assert rig.decisions == 1


def test_scripts_stop_running_after_the_limit_and_the_player_is_told_once(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    rig.write("scripts/s.py", "pass\n")
    rig.call("hook_set", event="damage", action="run", script="s")
    engine = rig.toolbox._watchers[0].__self__  # type: ignore[attr-defined]
    engine._total_runs = MAX_HOOK_RUNS - 1
    first = rig.call("wait", ticks=25)
    assert "Hook h1" in first.content
    second = rig.call("wait", ticks=25)
    assert second.content.count("will not run again") == 1
    third = rig.call("wait", ticks=25)
    assert "will not run again" not in third.content


def test_a_hook_does_not_run_once_the_game_is_over(tmp_path: Path) -> None:
    game = arena_game(tmp_path / "arena", START_X)
    game.spawn_enemy("longleg", START_X + 18, GROUND)
    rig = make_rig(tmp_path / "rig", game=game, max_decisions=1)
    rig.write("scripts/s.py", "game.wait(ticks=1)\n")
    rig.call("hook_set", event="damage", action="run", script="s")
    result = rig.call("wait", ticks=25)
    assert rig.session.over and "Hook h1" not in result.content


def test_a_hook_that_cannot_run_does_not_undo_the_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = near_enemy(tmp_path)
    rig.write("scripts/s.py", "pass\n")
    rig.call("hook_set", event="damage", action="run", script="s")
    engine = rig.toolbox._watchers[0].__self__  # type: ignore[attr-defined]

    def no_process(*_args, **_kwargs):
        raise OSError("cannot start a process")

    monkeypatch.setattr(engine.rt, "run", no_process)
    result = rig.call("wait", ticks=25)
    assert not result.is_error and "Stopped: interrupted (damage)" in result.content
    assert rig.decisions == 1 and not rig.session.over
    assert not rig.call("wait", ticks=1).is_error


def test_hooks_are_logged(tmp_path: Path) -> None:
    rig = near_enemy(tmp_path)
    rig.write("scripts/s.py", "game.wait(ticks=1)\n")
    rig.call("hook_set", event="damage", action="run", script="s")
    rig.call("wait", ticks=25)
    rig.logs.close()
    run = next(r for r in rig.transcript() if r["kind"] == "code_run")
    assert run["label"] == "hook h1" and run["commands"] == 1
