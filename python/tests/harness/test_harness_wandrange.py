"""The wand practice range: the `wand_range` tool and its rules about what may be tried."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from layer_context import make_rig
from noitabench.agent.errors import CommandError
from noitabench.agent.visibility import leaks
from noitabench.game import wand_trial
from noitabench.harness import ToolCall
from noitabench.harness.model import ToolResult
from noitabench.harness.prompt import FORBIDDEN_STEMS
from noitabench.harness.wandrange import (
    KEEP_CLICKS,
    SHUFFLE_RUNS,
    register_wand_range,
    wand_range,
    wand_range_spec,
)

_STEMS = re.compile(r"\b(" + "|".join(FORBIDDEN_STEMS) + r")", re.IGNORECASE)


@pytest.fixture
def rig(tmp_path: Path, make_game):
    game = make_game()
    game.give_spell("DAMAGE")
    game.give_spell("BULLET")
    return make_rig(tmp_path, game, register=register_wand_range)


def tool(rig, **args: Any) -> ToolResult:
    return rig.toolbox.execute([ToolCall("t", "wand_range", args)]).results[0]


def report(rig, **args: Any) -> dict[str, Any]:
    result = tool(rig, **args)
    assert not result.is_error, result.content
    return json.loads(result.content)


def error(rig, **args: Any) -> str:
    result = tool(rig, **args)
    assert result.is_error, result.content
    return result.content


# -- what it reports ------------------------------------------------------------------------------


def test_the_held_wand_is_tried_as_it_is(rig) -> None:
    r = report(rig)
    assert r["wand"] == "wand 0" and r["slots"] == ["LIGHT_BULLET", None, None]
    assert r["seconds"] == 10.0
    # cast delay 10 + 3 and recharge 22: a click every 22 frames, as the engine says
    assert r["timeline"][0]["plays"] == "LIGHT_BULLET" and r["timeline"][0]["t"] == 0.0
    assert r["timeline"][1]["t"] == pytest.approx(22 / 60, abs=0.01)
    assert r["clicks_per_second"] == pytest.approx(60 / 22, abs=0.15)
    # 3 displayed HP per hit, times the +20% a 5% critical chance is worth on average
    assert r["damage_per_second"] == pytest.approx(3.6 * 60 / 22, abs=0.5)
    assert r["mana"]["start"] == 100.0 and r["mana"]["regained_per_second"] == 30.0
    assert "first_short_of_mana_at" not in r["mana"]


def test_it_takes_no_time_and_changes_nothing(rig) -> None:
    before = (
        rig.session.decisions,
        rig.session.frame,
        rig.session.state_hash(),
        rig.session.carried(),
    )
    for args in ({}, {"wand": 1}, {"slots": ["DAMAGE", "LIGHT_BULLET"]}, {"seconds": 30}):
        report(rig, **args)
    after = (
        rig.session.decisions,
        rig.session.frame,
        rig.session.state_hash(),
        rig.session.carried(),
    )
    assert before == after
    assert rig.budget.model_calls == 0


def test_another_order_of_the_spells_one_carries_can_be_tried(rig) -> None:
    plain = report(rig)
    better = report(rig, slots=["DAMAGE", "LIGHT_BULLET", "BULLET"], seconds=5)
    assert better["slots"] == ["DAMAGE", "LIGHT_BULLET", "BULLET"]
    assert better["timeline"][0]["plays"] == "DAMAGE+LIGHT_BULLET"
    assert better["damage_per_second"] > 3 * plain["damage_per_second"]
    assert better["mana"]["spent_per_second"] > plain["mana"]["spent_per_second"]
    # the wand itself was not edited
    assert rig.session.carried()["wands"][0]["slots"][1] is None


def test_running_short_of_mana_is_said(rig) -> None:
    # a wand with little mana and a dear spell
    r = report(
        rig,
        stats={
            "mana_max": 15,
            "mana_per_second": 0,
            "cast_delay": 0,
            "recharge": 0,
            "capacity": 1,
        },
        slots=["BULLET"],
        seconds=3,
    )
    assert r["wand"] == "given numbers"
    assert r["mana"]["first_short_of_mana_at"] == 0.0 and r["clicks_per_second"] == 0
    assert any("BULLET" in s and "not enough mana" in s for s in r["passed_over"])
    assert r["timeline"][0]["passed_over"] == ["BULLET (not enough mana)"]


def test_a_target_has_a_time_to_die(rig) -> None:
    quick = report(rig, slots=["DAMAGE", "LIGHT_BULLET", "BULLET"], target_hp=30)
    slow = report(rig, target_hp=30)
    assert quick["seconds_to_kill"] < slow["seconds_to_kill"]
    assert report(rig, target_hp=1e9, seconds=2)["seconds_to_kill"] is None


def test_a_shuffling_wand_is_run_several_times(rig) -> None:
    stats = {
        "mana_max": 200,
        "mana_per_second": 30,
        "cast_delay": 5,
        "recharge": 20,
        "capacity": 4,
        "shuffle": True,
    }
    slots = ["LIGHT_BULLET", "BULLET", "DAMAGE"]
    r = report(rig, stats=stats, slots=slots)
    assert any(f"{SHUFFLE_RUNS} shuffles" in n for n in r["notes"])
    assert report(rig, stats=stats, slots=slots) == r, "the same question, the same answer"


def test_the_timeline_is_short_and_says_how_much_was_cut(rig) -> None:
    r = report(rig, seconds=30)
    assert len(r["timeline"]) == 10 and r["timeline_cut"] > 0
    assert KEEP_CLICKS >= 600


def test_the_report_holds_nothing_hidden(rig) -> None:
    blob = json.dumps(report(rig, slots=["DAMAGE", "LIGHT_BULLET", "BULLET"]))
    assert leaks(json.loads(blob)) == []
    for hidden in ("speed_multiplier", "ray_energy", "durability", "seed", "rule", "recipe"):
        assert hidden not in blob
    assert _STEMS.findall(blob) == []


# -- what may be tried ----------------------------------------------------------------------------


def test_only_spells_one_carries_can_be_tried_each_card_once(rig) -> None:
    msg = error(rig, slots=["BOMB"])
    assert "not_carried" in msg and "BOMB" in msg and "LIGHT_BULLET" in msg
    twice = error(rig, slots=["DAMAGE", "DAMAGE"])
    assert "not_carried" in twice and "only 1 DAMAGE" in twice
    # a card in another wand can be borrowed for the try: it is all the same cards
    report(rig, slots=["DIGGER", "LIGHT_BULLET"])
    # a spell is named by its key, not case-sensitively
    assert report(rig, slots=["damage", "light bullet"])["slots"] == ["DAMAGE", "LIGHT_BULLET"]


def test_spells_one_has_not_found_stay_hidden_even_with_made_up_numbers(rig) -> None:
    msg = error(
        rig,
        stats={
            "mana_max": 500,
            "mana_per_second": 100,
            "cast_delay": 1,
            "recharge": 1,
            "capacity": 5,
        },
        slots=["BOMB", "FIREBALL"],
    )
    assert "not_carried" in msg and "BOMB" in msg


def test_mistakes_are_answers_not_crashes(rig) -> None:
    assert "no_such_wand" in error(rig, wand=9)
    assert "too_many_slots" in error(rig, slots=["DAMAGE", "BULLET", "LIGHT_BULLET", None])
    assert "bad_argument" in error(rig, seconds=0)
    assert "bad_argument" in error(rig, seconds=1000)
    assert "bad_argument" in error(rig, seconds="long")
    assert "bad_argument" in error(rig, target_hp=-4)
    assert "bad_argument" in error(rig, stats={"mana_max": 5})
    assert "bad_argument" in error(
        rig,
        stats={
            "mana_max": 5,
            "mana_per_second": 5,
            "cast_delay": 1,
            "recharge": 1,
            "capacity": 2,
            "luck": 1,
        },
        slots=[],
    )
    assert "bad_argument" in error(
        rig,
        stats={"mana_max": 5, "mana_per_second": 5, "cast_delay": 1, "recharge": 1, "capacity": 2},
    )
    assert "bad_argument" in error(rig, wand=0, stats={}, slots=[])
    assert "bad_argument" in error(rig, slots="DAMAGE")
    assert "bad_wand" in error(
        rig,
        stats={"mana_max": 5, "mana_per_second": 5, "cast_delay": 1, "recharge": 1, "capacity": 0},
        slots=[],
    )


def test_limited_uses_are_the_cards_uses(tmp_path: Path, make_game) -> None:
    game = make_game()
    game.give_spell("BOMB")  # one BOMB card, three uses
    rig = make_rig(tmp_path, game, register=register_wand_range)
    r = report(rig, slots=["BOMB"], seconds=20)
    assert r["used_up"] == ["BOMB"]
    assert r["damage_total"] == pytest.approx(3 * 125, abs=1)


def test_the_tool_schema_is_plain() -> None:
    spec = wand_range_spec()
    assert spec.name == "wand_range" and spec.schema["required"] == []
    assert _STEMS.findall(spec.description + json.dumps(spec.schema)) == []


def test_direct_call_raises_the_same_errors(rig) -> None:
    with pytest.raises(CommandError) as err:
        wand_range(rig.session, {"slots": ["NOPE"]})
    assert err.value.code == "not_carried"


# -- numbers the engine cannot take ---------------------------------------------------------------


CLEAN = {"mana_max": 100, "mana_per_second": 10, "cast_delay": 5, "recharge": 5, "capacity": 4}


@pytest.mark.parametrize(
    "stats",
    [
        {**CLEAN, "capacity": 2**40},
        {**CLEAN, "cast_delay": 2**31 - 1},
        {**CLEAN, "recharge": -(2**31)},
        {**CLEAN, "cast_delay": 2**70},
        {**CLEAN, "mana_max": float("inf")},
        {**CLEAN, "mana_max": float("nan")},
        {**CLEAN, "mana_per_second": 1e300},
        {**CLEAN, "spread": float("inf")},
        {**CLEAN, "capacity": 4.5},
        {**CLEAN, "capacity": float("inf")},
        {**CLEAN, "spells_per_cast": 2**40},
        {**CLEAN, "mana_max": True},
        {**CLEAN, "shuffle": "yes"},
        {**CLEAN, "capacity": None},
    ],
)
def test_made_up_numbers_the_engine_cannot_take_are_answers_not_crashes(rig, stats) -> None:
    # `tool` runs the call through the toolbox: an exception that escaped would stop the game
    result = tool(rig, stats=stats, slots=["BULLET"])
    assert result.is_error and result.content.split(":")[0] in {"bad_argument", "bad_wand"}


@pytest.mark.parametrize("wand", [float("inf"), float("nan"), 1e400, 0.5, "0", True, None, [0]])
def test_a_wand_index_is_a_whole_number(rig, wand) -> None:
    assert "bad_argument" in error(rig, wand=wand)


def test_a_refused_wand_does_not_say_what_the_engines_limits_are(rig) -> None:
    message = error(rig, stats={**CLEAN, "capacity": 100}, slots=["BULLET"])
    assert "bad_wand" in message
    assert not any(ch.isdigit() for ch in message.split("bad_wand:")[1].replace("1", "")), message


def test_a_wand_that_clicks_every_frame_still_gets_its_time_to_kill(rig) -> None:
    fast = {**CLEAN, "mana_max": 1e6, "mana_per_second": 0, "cast_delay": -100, "recharge": -100}
    fast["capacity"] = 1
    r = report(rig, stats=fast, slots=["BULLET"], seconds=30, target_hp=20000)
    assert r["clicks_per_second"] == pytest.approx(60, abs=0.5)
    # the report follows only the first clicks; the dummy dies later than those
    assert r["seconds_to_kill"] is None and "later than" in r["seconds_to_kill_note"]
    never = report(rig, stats=fast, slots=["BULLET"], seconds=30, target_hp=1e12)
    assert never["seconds_to_kill"] is None and "seconds_to_kill_note" not in never
    soon = report(rig, stats=fast, slots=["BULLET"], seconds=30, target_hp=50)
    assert soon["seconds_to_kill"] < 1 and "seconds_to_kill_note" not in soon


def test_the_practice_range_function_raises_value_error_for_every_bad_wand() -> None:
    clean = {
        "mana_max": 100.0,
        "mana_charge_speed": 10.0,
        "cast_delay": 5,
        "recharge": 5,
        "capacity": 3,
    }
    for bad in (
        {**clean, "capacity": 0},
        {**clean, "capacity": 2**40},
        {**clean, "cast_delay": 2**31 - 1},
        {**clean, "cast_delay": -(2**31)},
        {**clean, "recharge": 2**31},
        {**clean, "mana_max": float("nan")},
    ):
        with pytest.raises(ValueError):
            wand_trial(bad, ["LIGHT_BULLET"], frames=60)
    with pytest.raises(ValueError):
        wand_trial(clean, ["NOPE"], frames=60)
    with pytest.raises(ValueError):
        wand_trial(clean, ["LIGHT_BULLET"] * 4, frames=60)  # more slots than capacity
    with pytest.raises(ValueError):
        wand_trial(clean, ["LIGHT_BULLET"], frames=7201)
    with pytest.raises(ValueError):
        wand_trial(clean, ["LIGHT_BULLET"], frames=0)
    with pytest.raises(ValueError):
        wand_trial(clean, ["LIGHT_BULLET"], always_cast=["DAMAGE"] * 5)
    assert wand_trial(clean, ["LIGHT_BULLET"], frames=60) == wand_trial(
        clean, ["LIGHT_BULLET"], frames=60
    ), "same call, same answer"
