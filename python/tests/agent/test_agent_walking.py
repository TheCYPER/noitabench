"""Walking: no stop for a drop (the player walks off a ledge and falls), `until=edge` for the old
caution, and a wall that is felt (the key held for a tick without moving) instead of predicted.

The worlds are flat ground with one feature each: a narrow shaft, a wide pit, a step down, walls
and ledges of several heights, written as world file pairs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agent_worlds import (
    FLOOR,
    GROUND,
    LEDGE_H,
    LEDGE_W,
    LEDGE_X,
    PIT_DEPTH,
    PIT_W,
    PIT_X,
    POOL_DEPTH,
    POOL_W,
    POOL_X,
    WALL_W,
    WALL_X,
    settle,
    write_arena,
)
from noitabench.agent import AgentSession, SessionConfig, ViewConfig
from noitabench.agent.engine import position_of
from noitabench.agent.errors import CommandError
from noitabench.agent.validate import validate_command
from noitabench.agent.vocab import CLIFF_DEPTH, STALL_FRAMES, TICK_FRAMES

SHAFT_X, SHAFT_W, SHAFT_DEPTH = 250, 20, 40  # wide enough that the far wall cannot be climbed
NARROW_W = 5  # a shaft a held direction scrambles out of again (a step-up works in the air too)
Make = Callable[..., AgentSession]


def clear_obstacles(grid: Any, keys: dict[str, int]) -> None:
    """The arena's wall, pit, ledge and pool are not part of these worlds."""
    rock = keys["rock"]
    grid[100:FLOOR, WALL_X : WALL_X + WALL_W] = 0
    grid[FLOOR : FLOOR + PIT_DEPTH, PIT_X : PIT_X + PIT_W] = rock
    grid[FLOOR - LEDGE_H : FLOOR, LEDGE_X : LEDGE_X + LEDGE_W] = 0
    grid[FLOOR : FLOOR + POOL_DEPTH, POOL_X : POOL_X + POOL_W] = rock


def session_in(
    tmp_path: Path, spawn_x: int, edit: Callable[[Any, dict[str, int]], None] | None = None
) -> AgentSession:
    def both(grid: Any, keys: dict[str, int]) -> None:
        clear_obstacles(grid, keys)
        if edit is not None:
            edit(grid, keys)

    game = write_arena(tmp_path, edit=both, spawn_x=spawn_x).game()
    settle(game)
    return AgentSession(game, config=SessionConfig(view=ViewConfig()))


def shaft(grid: Any, keys: dict[str, int]) -> None:
    grid[FLOOR : FLOOR + SHAFT_DEPTH, SHAFT_X : SHAFT_X + SHAFT_W] = 0


def narrow_shaft(grid: Any, keys: dict[str, int]) -> None:
    grid[FLOOR : FLOOR + SHAFT_DEPTH, SHAFT_X : SHAFT_X + NARROW_W] = 0


def pit(width: int, depth: int) -> Callable[[Any, dict[str, int]], None]:
    def carve(grid: Any, keys: dict[str, int]) -> None:
        grid[FLOOR : FLOOR + depth, SHAFT_X : SHAFT_X + width] = 0

    return carve


def feet(s: AgentSession) -> tuple[int, int]:
    return position_of(s.engine.player())


def stop_of(s: AgentSession, text: str) -> dict[str, Any]:
    a = s.decide(text)
    assert a["results"][0]["ok"], a["results"]
    stop: dict[str, Any] = a["stop"]
    return stop


# -- a drop does not stop a walk ----------------------------------------------------------------------


def test_standing_at_the_edge_of_a_shaft_a_walk_steps_off_and_falls(tmp_path: Path) -> None:
    """The case that was reported: the old walk would not start next to the shaft ("There is a
    drop ahead"), so the player could only get in by jumping."""
    s = session_in(tmp_path, SHAFT_X - 2, shaft)
    assert feet(s)[1] == GROUND
    stop = stop_of(s, "move(right)")
    x, y = feet(s)
    assert y > FLOOR + 20, "it is down in the shaft"
    assert s.engine.player()["on_ground"]
    # falling along the wall is not a stall: the wall is felt only once it stands on the bottom
    assert (stop["reason"], stop["detail"]) == ("interrupted", "blocked")
    assert stop["frames"] >= 3 * TICK_FRAMES + STALL_FRAMES
    assert SHAFT_X <= x < SHAFT_X + SHAFT_W


def test_a_walk_with_the_blocked_interrupt_off_also_falls_and_ends_at_the_bottom_wall(
    tmp_path: Path,
) -> None:
    s = session_in(tmp_path, SHAFT_X - 2, shaft)
    s.interrupts.disable("blocked")
    stop = stop_of(s, "move(right)")
    assert (stop["reason"], stop["detail"]) == ("completed", "blocked")
    assert feet(s)[1] > FLOOR + 20


def test_walking_off_a_ledge_holds_the_direction_in_the_air_until_it_lands(
    tmp_path: Path,
) -> None:
    s = session_in(tmp_path, SHAFT_X - 8, pit(40, 60))
    stop = stop_of(s, "move(right, until=landed)")
    assert (stop["reason"], stop["detail"]) == ("completed", "landed")
    x, y = feet(s)
    assert y > FLOOR + 50 and s.engine.player()["on_ground"]
    assert x > SHAFT_X + 5, "it kept moving right while it fell"


def test_walk_to_brakes_at_its_column_on_the_way_down_and_ends_standing(tmp_path: Path) -> None:
    s = session_in(tmp_path, SHAFT_X - 8, pit(40, 60))
    target = SHAFT_X + 14
    stop = stop_of(s, f"walk_to(x={target})")
    x, y = feet(s)
    assert (stop["reason"], stop["detail"]) == ("completed", "reached")
    assert s.engine.player()["on_ground"] and y > FLOOR + 50, "it ends once it stands again"
    assert abs(x - target) <= 1


def test_a_fall_is_not_a_wall_for_the_stall_rule(tmp_path: Path) -> None:
    """Pressing against the shaft wall while falling moves the player every frame."""
    s = session_in(tmp_path, SHAFT_X - 2, shaft)
    a = s.decide("move(right, ticks=3)")
    assert a["stop"]["detail"] == "ticks"
    assert not s.engine.player()["on_ground"], "still in the air, no stall reported"


def test_a_walk_to_the_column_of_a_narrow_shaft_drops_straight_in(tmp_path: Path) -> None:
    s = session_in(tmp_path, SHAFT_X - 20, narrow_shaft)
    centre = SHAFT_X + NARROW_W // 2 + 1  # the 4-wide player must be wholly over the opening
    stop = stop_of(s, f"walk_to(x={centre})")
    x, y = feet(s)
    assert (stop["reason"], stop["detail"]) == ("completed", "reached")
    assert y > FLOOR + 20 and abs(x - centre) <= 1


# -- until=edge ----------------------------------------------------------------------------------------


def test_until_edge_stops_with_the_front_foot_on_the_ground_and_costs_no_time_again(
    tmp_path: Path,
) -> None:
    s = session_in(tmp_path, SHAFT_X - 40, shaft)
    stop = stop_of(s, "move(right, until=edge)")
    p = s.engine.player()
    assert (stop["reason"], stop["detail"]) == ("completed", "edge")
    assert stop["message"] == "There is a drop ahead."
    front = p["x"] + p["w"] - 1
    assert front < SHAFT_X and SHAFT_X - front <= 3, "at the edge, not over it"
    again = stop_of(s, "move(right, until=edge)")
    assert (again["detail"], again["frames"]) == ("edge", 0)
    # without the condition the same walk steps off
    stepped = stop_of(s, "move(right)")
    assert feet(s)[1] > FLOOR + 20 and stepped["frames"] > 0


def test_walk_to_with_until_edge_stops_before_a_shaft_in_the_way(tmp_path: Path) -> None:
    s = session_in(tmp_path, SHAFT_X - 40, shaft)
    stop = stop_of(s, f"walk_to(x={SHAFT_X + 20}, until=edge)")
    assert stop["detail"] == "edge" and feet(s)[0] < SHAFT_X


def test_until_edge_passes_a_step_down_that_is_not_a_cliff(tmp_path: Path) -> None:
    step = CLIFF_DEPTH - 3

    def step_down(grid: Any, keys: dict[str, int]) -> None:
        grid[FLOOR : FLOOR + step, 200:] = 0  # the ground to the right lies `step` cells lower

    s = session_in(tmp_path, 160, step_down)
    stop = stop_of(s, "move(right, until=edge)")
    assert feet(s)[0] > 200 and stop["detail"] == "blocked"  # it stepped down and ran on


def test_until_edge_stops_at_a_step_down_that_is_a_cliff(tmp_path: Path) -> None:
    def cliff(grid: Any, keys: dict[str, int]) -> None:
        grid[FLOOR : FLOOR + CLIFF_DEPTH + 4, 200:] = 0

    s = session_in(tmp_path, 160, cliff)
    stop = stop_of(s, "move(right, until=edge)")
    assert stop["detail"] == "edge" and feet(s)[0] < 200


def test_until_edge_still_ends_at_a_wall(tmp_path: Path) -> None:
    s = session_in(
        tmp_path, 160, lambda g, k: g.__setitem__((slice(100, FLOOR), slice(220, 226)), k["rock"])
    )
    stop = stop_of(s, "move(right, until=edge)")
    assert (stop["reason"], stop["detail"]) == ("interrupted", "blocked")


@pytest.mark.parametrize("name", ["jump", "fly", "wait", "fire", "kick"])
def test_edge_belongs_to_walking_only(name: str) -> None:
    with pytest.raises(CommandError) as err:
        validate_command(name, {"until": {"edge": True}})
    assert "edge" in err.value.message
    validate_command("move", {"direction": "right", "until": {"edge": True}})
    validate_command("walk_to", {"x": 10, "edge": True})
    assert validate_command("move", {"direction": "left", "edge": False}).args == {
        "direction": "left"
    }


# -- a wall is felt, not predicted --------------------------------------------------------------------


@pytest.mark.parametrize("interrupt", [True, False])
def test_walking_into_a_wall_ends_after_a_tick_of_pushing(tmp_path: Path, interrupt: bool) -> None:
    s = session_in(
        tmp_path, 160, lambda g, k: g.__setitem__((slice(100, FLOOR), slice(220, 226)), k["rock"])
    )
    s.decide("walk_to(x=214)")
    if not interrupt:
        s.interrupts.disable("blocked")
    first = stop_of(s, "move(right)")
    assert first["detail"] == "blocked" and first["message"] == "A wall is in the way."
    # already against it: nothing moves for `STALL_FRAMES` frames, then the walk knows
    again = stop_of(s, "move(right)")
    assert (again["detail"], again["frames"]) == ("blocked", STALL_FRAMES)
    assert again["reason"] == ("interrupted" if interrupt else "completed")
    # and `until=blocked` says the same, as a completion
    assert stop_of(s, "move(right, until=blocked)")["frames"] == STALL_FRAMES


@pytest.mark.parametrize("height", [1, 3, 4])
def test_a_ledge_up_to_the_step_height_is_walked_over(tmp_path: Path, height: int) -> None:
    def ledge(grid: Any, keys: dict[str, int]) -> None:
        grid[FLOOR - height : FLOOR, 200:230] = keys["ground"]

    s = session_in(tmp_path, 180, ledge)
    stop = stop_of(s, "walk_to(x=215)")
    assert stop["detail"] == "reached" and feet(s)[1] == GROUND - height


def test_a_ledge_higher_than_the_step_height_is_a_wall(tmp_path: Path) -> None:
    def ledge(grid: Any, keys: dict[str, int]) -> None:
        grid[FLOOR - 5 : FLOOR, 200:230] = keys["ground"]

    s = session_in(tmp_path, 180, ledge)
    stop = stop_of(s, "walk_to(x=215)")
    assert (stop["reason"], stop["detail"]) == ("interrupted", "blocked")
    assert feet(s)[0] < 200


def test_a_low_ceiling_over_a_ledge_is_a_wall_too(tmp_path: Path) -> None:
    def tunnel(grid: Any, keys: dict[str, int]) -> None:
        grid[FLOOR - 3 : FLOOR, 200:230] = keys["ground"]  # a step of 3 ...
        grid[FLOOR - 12 : FLOOR - 9, 195:230] = keys["rock"]  # ... under a ceiling too low to climb

    s = session_in(tmp_path, 180, tunnel)
    stop = stop_of(s, "walk_to(x=215)")
    assert stop["detail"] == "blocked" and feet(s)[0] < 200


def test_a_walk_into_the_wall_around_the_arena_is_felt_like_any_other(tmp_path: Path) -> None:
    """`move(left)` from beside the boundary rock: blocked, and quickly (two ticks at most)."""
    s = session_in(tmp_path, 12)
    stop = stop_of(s, "move(left)")
    assert (stop["reason"], stop["detail"]) == ("interrupted", "blocked")
    assert feet(s)[0] <= 10 and stop["frames"] <= 2 * TICK_FRAMES


# -- landed, determinism --------------------------------------------------------------------------------


def test_landed_for_a_walk_waits_for_a_touchdown(tmp_path: Path) -> None:
    s = session_in(tmp_path, 160)
    stop = stop_of(s, "move(right, ticks=3, until=landed)")
    assert (stop["detail"], stop["ticks"]) == ("ticks", 3), "on the ground all along: no landing"


def test_the_same_walks_twice_give_the_same_frames(tmp_path: Path) -> None:
    runs = []
    for i in range(2):
        s = session_in(tmp_path / str(i), SHAFT_X - 40, shaft)
        frames = []
        for text in ("move(right, until=edge)", "move(right)", "move(left)", "wait(ticks=1)"):
            frames.append((s.decide(text)["frame"], feet(s)))
        runs.append(frames)
    assert runs[0] == runs[1]
    assert all(f % TICK_FRAMES == runs[0][0][0] % TICK_FRAMES for f, _ in runs[0])
