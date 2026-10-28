"""Time model B: ticks, decision points, `until` conditions, the 300-frame cap, braking."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from agent_worlds import GROUND, LEDGE_X, PIT_X, START_X, WALL_X
from noitabench.agent import AgentSession
from noitabench.agent.engine import position_of
from noitabench.agent.vocab import STALL_FRAMES
from noitabench.game import Game

Make = Callable[..., AgentSession]


def where(s: AgentSession) -> tuple[int, int]:
    return position_of(s.engine.player())


def goto(s: AgentSession, x: int) -> None:
    """Stand at column `x` (a plain walk, for set-up)."""
    a = s.decide(f"walk_to(x={x})")
    assert a["stop"]["reason"] == "completed", a["stop"]


# -- the world waits ---------------------------------------------------------------------------------


def test_the_world_waits_while_the_agent_thinks(session: AgentSession) -> None:
    before = (session.frame, session.state_hash())
    first = session.observe()
    again = session.observe()
    assert first == again and (session.frame, session.state_hash()) == before
    assert first["stop"] == {"reason": "start", "ticks": 0, "frames": 0}
    assert first["decision"] == 1 and first["decisions_left"] == 1000


def test_inspect_takes_no_time_but_counts_as_a_decision(session: AgentSession) -> None:
    frame, h = session.frame, session.state_hash()
    answer = session.decide(f"inspect(x={START_X}, y={GROUND})")
    assert answer["results"][0]["result"]["material"] == "air"
    assert (session.frame, session.state_hash()) == (frame, h)
    assert answer["decision"] == 2 and answer["decisions_left"] == 999
    assert answer["stop"] == {"reason": "completed", "ticks": 0, "frames": 0}


@pytest.mark.parametrize(
    "text",
    [
        "walk_to(x=33)",
        "walk_to(x=100)",
        "jump(right)",
        "fly(up, ticks=2)",
        "kick",
        "wait",
        "drink(amount=25)",
    ],
)
def test_decision_points_fall_on_tick_boundaries(game: Game, make_session: Make, text: str) -> None:
    game.give_bottle("water", 400)
    s = make_session(game)
    start = s.frame
    answer = s.decide(text)
    assert answer["stop"]["frames"] > 0
    assert (s.frame - start) % 10 == 0 and answer["stop"]["frames"] == s.frame - start
    assert answer["stop"]["ticks"] == answer["stop"]["frames"] // 10


# -- until conditions --------------------------------------------------------------------------------


def test_until_ticks(session: AgentSession) -> None:
    a = session.decide("wait(ticks=3)")
    assert a["stop"] == {"reason": "completed", "detail": "ticks", "ticks": 3, "frames": 30}


def test_until_distance_and_x_walk_there_and_stop(session: AgentSession) -> None:
    session.decide("move(right, distance=30)")
    assert abs(where(session)[0] - (START_X + 30)) <= 1
    session.decide("move(right, until={'x': 100})")
    assert abs(where(session)[0] - 100) <= 1
    a = session.decide("move(right, x=70)")  # behind: the other way
    assert a["stop"]["reason"] == "invalid" and a["stop"]["code"] == "wrong_side"


def test_until_distance_and_x_also_work_without_braking(session: AgentSession) -> None:
    x0, y0 = where(session)
    a = session.decide("fly(right, distance=15)")  # the distance is the straight one
    x1, y1 = where(session)
    assert a["stop"]["detail"] == "distance" and math.hypot(x1 - x0, y1 - y0) >= 15
    a = session.decide("fly(right, x=120)")
    assert a["stop"]["detail"] == "x"


def test_until_blocked_ends_the_command_where_the_default_interrupts(
    game: Game, make_session: Make
) -> None:
    s = make_session(game)
    goto(s, WALL_X - 15)
    interrupted = s.decide("move(right)")["stop"]
    assert (interrupted["reason"], interrupted["detail"]) == ("interrupted", "blocked")
    assert "wall" in interrupted["message"]
    done = s.decide("move(right, until=blocked)")["stop"]
    assert (done["reason"], done["detail"]) == ("completed", "blocked")
    assert done["frames"] == STALL_FRAMES  # already against the wall: it takes a tick to feel it


def test_until_landed(session: AgentSession) -> None:
    session.decide("fly(up, ticks=4)")
    a = session.decide("wait(until=landed)")
    assert a["stop"]["detail"] == "landed" and a["stop"]["frames"] > 0
    assert session.engine.player()["on_ground"]


def test_landed_on_the_ground_already_is_met_at_once_unless_the_command_takes_off(
    session: AgentSession,
) -> None:
    standing = session.decide("wait(until=landed)")["stop"]
    assert (standing["detail"], standing["ticks"]) == ("landed", 1)
    flying = session.decide("fly(up, until=landed)")["stop"]
    assert flying["detail"] == "levitation_empty"  # still up: taking off is not a landing
    assert session.decide("wait(until=landed)")["stop"]["frames"] > 0


def test_jump_ends_when_it_lands(session: AgentSession) -> None:
    a = session.decide("jump(up)")
    assert a["stop"]["detail"] == "landed" and 20 <= a["stop"]["frames"] <= 60
    x0 = where(session)[0]
    session.decide("jump(right)")
    assert where(session)[0] > x0 + 10


def test_until_hp_below_is_checked_every_frame(game: Game, make_session: Make) -> None:
    game.give_bottle("acid", 400)
    s = make_session(game)
    a = s.decide("drink(amount=400, until={'hp_below': 90})")
    assert a["stop"]["detail"] == "hp_below"
    assert s.engine.player()["hp"] < 90


def test_until_target_dead_and_mana_empty(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 60, GROUND)
    s = make_session(game)
    enemy = next(e for e in s.observe()["observation"]["state"]["nearby"] if e["kind"] == "longleg")
    answer = s.decide(f"aim(entity={enemy['id']}); fire(until=target_dead)")
    assert answer["stop"]["detail"] == "target_dead"
    assert any(e["type"] == "death" for e in answer["events"])
    gone = s.decide("fire(until=target_dead)")  # nothing to aim at any more
    assert gone["stop"]["code"] == "no_target"


def test_fire_stops_by_itself_when_the_wand_cannot_pay(game: Game, make_session: Make) -> None:
    stats = {"cast_delay": 5, "recharge": 5, "mana_max": 100, "mana_charge_speed": 1, "capacity": 1}
    game.give_wand(stats, ["FIREBALL"])
    s = make_session(game)
    s.decide("swap_wand(2)")
    a = s.decide("fire")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "mana_empty")
    b = s.decide("fire(until=mana_empty)")
    assert b["stop"]["detail"] == "mana_empty" and b["stop"]["frames"] <= 10


def test_until_event(session: AgentSession) -> None:
    a = session.decide("fire(until={'event': 'cast'}, ticks=10)")
    assert (a["stop"]["detail"], a["stop"]["ticks"]) == ("event", 1)
    never = session.decide("wait(event='damage')")
    assert never["stop"]["reason"] == "time_limit"


# -- the cap ---------------------------------------------------------------------------------------------


def test_one_decision_never_lasts_more_than_300_frames(session: AgentSession) -> None:
    full = session.decide("wait(ticks=30)")["stop"]
    assert (full["reason"], full["frames"]) == ("completed", 300)
    capped = session.decide("wait(event='damage')")["stop"]
    assert (capped["reason"], capped["frames"], capped["ticks"]) == ("time_limit", 300, 30)
    assert "5 seconds" in capped["message"]


def test_the_commands_of_a_decision_share_the_budget(session: AgentSession) -> None:
    a = session.decide("wait(ticks=20); wait(ticks=20); wait(ticks=1)")
    assert a["stop"]["reason"] == "time_limit"
    assert a["stop"]["frames"] == 100  # the second one got the 100 frames that were left
    assert [r["ok"] for r in a["results"]] == [True, True, False]
    assert a["results"][2]["code"] == "skipped"
    full = session.decide("wait(ticks=30); wait(ticks=1)")
    assert full["results"][1]["code"] == "no_time_left"


def test_an_interrupt_drops_the_rest_of_the_decision(game: Game, make_session: Make) -> None:
    s = make_session(game)
    goto(s, WALL_X - 15)
    start = s.frame
    a = s.decide("move(right); kick; wait(ticks=3)")
    assert a["stop"]["detail"] == "blocked"
    assert [r["code"] for r in a["results"][1:]] == ["skipped", "skipped"]
    assert (s.frame - start) % 10 == 0 and s.frame - start == a["stop"]["frames"]
    assert not any(e["type"] == "kick" for e in a["events"])  # the kick did not happen


# -- walking ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", [45, 77, 120, 12, 29, 31])
def test_walk_to_stops_within_a_cell_of_the_target(session: AgentSession, target: int) -> None:
    a = session.decide(f"walk_to(x={target})")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "reached")
    assert abs(where(session)[0] - target) <= 1
    assert abs(session.engine.player()["vx"]) < 20  # and it is no longer running


def test_a_move_stops_at_a_wall(game: Game, make_session: Make) -> None:
    s = make_session(game)
    goto(s, WALL_X - 40)
    a = s.decide("move(right)")
    p = s.engine.player()
    assert a["stop"]["detail"] == "blocked" and p["x"] + p["w"] == WALL_X


def test_a_move_with_until_edge_stops_at_a_drop_with_the_front_foot_on_the_ground(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    s = make_session(game_at(PIT_X - 40))
    a = s.decide("move(right, until=edge)")
    p = s.engine.player()
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "edge")
    assert "drop" in a["stop"]["message"]
    assert p["x"] + p["w"] - 1 < PIT_X and PIT_X - (p["x"] + p["w"]) <= 3  # at the edge, not over
    again = s.decide("move(right, until=edge)")
    assert again["stop"]["frames"] == 0  # still at the edge: nothing happens, no time passes
    jumped = s.decide("jump(right)")  # the way over: a jump
    assert jumped["stop"]["detail"] == "landed" and where(s)[0] > PIT_X + 12


def test_a_low_ledge_is_stepped_over(game_at: Callable[[int], Game], make_session: Make) -> None:
    s = make_session(game_at(LEDGE_X - 10))
    a = s.decide(f"walk_to(x={LEDGE_X + 20})")
    assert a["stop"]["detail"] == "reached"


def test_walking_into_the_world_edge_is_blocked(session: AgentSession) -> None:
    a = session.decide("move(left)")
    assert a["stop"]["detail"] == "blocked" and where(session)[0] <= 10
