"""The worked exchange of tick-design 4.5.1, played on a world built for it.

decision 1  start
decision 2  walk_to(x=180, until=edge)   stopped: edge, a drop (a pit with acid at the bottom);
                                 a plain walk_to would step off and fall in (it is normal play)
decision 3  jump(right)          completed: landed
decision 4  walk_to(x=180)       interrupted: a hostile creature came into view
decision 5  aim(...); fire(until=target_dead)   completed: target dead, events listed
decision 6  walk_to(x=180)       completed
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    write_arena,
)
from noitabench.agent import AgentSession, render_text
from noitabench.agent.vocab import TICK_FRAMES

START = 40
PIT = (100, 8)  # left column and width of the pit: eight cells wide
ENEMY_X = 290  # farther from x=180 than the player can see (128)


def example_session(tmp_path: Path) -> AgentSession:
    def edit(grid: Any, keys: dict[str, int]) -> None:
        rock = keys["rock"]
        grid[100:FLOOR, WALL_X : WALL_X + WALL_W] = 0  # the arena's obstacles are not part of this
        grid[FLOOR : FLOOR + PIT_DEPTH, PIT_X : PIT_X + PIT_W] = rock
        grid[FLOOR - LEDGE_H : FLOOR, LEDGE_X : LEDGE_X + LEDGE_W] = 0
        grid[FLOOR : FLOOR + POOL_DEPTH, POOL_X : POOL_X + POOL_W] = rock
        grid[FLOOR : FLOOR + 14, PIT[0] : PIT[0] + PIT[1]] = 0  # the pit of the example
        grid[FLOOR + 10 : FLOOR + 14, PIT[0] : PIT[0] + PIT[1]] = keys["acid"]  # acid at the bottom

    arena = write_arena(
        tmp_path,
        edit=edit,
        spawn_x=START,
        base_markers=[{"type": "spawn_player", "x": START, "y": GROUND}],
    )
    game = arena.game(seed=5)
    game.step(61)
    game.events()
    game.spawn_enemy("longleg", ENEMY_X, GROUND)
    return AgentSession(game)


def pos(s: AgentSession) -> int:
    return s.observe()["observation"]["state"]["position"]["x"]


def test_the_worked_exchange_plays_out_as_written(tmp_path: Path) -> None:
    s = example_session(tmp_path)
    log: list[tuple[str, dict[str, Any]]] = []

    def step(text: str) -> dict[str, Any]:
        a = s.decide(text)
        log.append((text, a))
        return a

    first = s.observe()
    assert first["stop"]["reason"] == "start" and first["decision"] == 1
    assert pos(s) == START

    # decision 2: the walk is stopped where the ground ends (a plain walk would step off)
    a = step("walk_to(x=180, until=edge)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "edge")
    assert "drop" in a["stop"]["message"] and PIT[0] - 8 <= pos(s) < PIT[0]
    assert a["decision"] == 2 and all(e["type"] != "damage" for e in a["events"])

    # decision 3: a jump over the pit
    a = step("jump(right)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "landed")
    assert pos(s) > PIT[0] + PIT[1]

    # decision 4: a hostile creature comes into view
    a = step("walk_to(x=180)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("interrupted", "new_enemy")
    enemy = next(e for e in a["observation"]["state"]["nearby"] if e["kind"] == "longleg")
    assert enemy["hostile"] and f"#{enemy['id']}" in a["stop"]["message"]
    assert pos(s) < 180

    # decision 5: aim at it and shoot until it is dead
    a = step(f"aim({enemy['id']}); fire(until=target_dead)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "target_dead")
    types = [e["type"] for e in a["events"]]
    assert "cast" in types and "death" in types
    assert all(e["tick"] >= 1 for e in a["events"])
    assert all(e["kind"] != "longleg" for e in a["observation"]["state"]["nearby"])

    # decision 6: on to 180
    a = step("walk_to(x=180)")
    assert (a["stop"]["reason"], a["stop"]["detail"]) == ("completed", "reached")
    assert abs(pos(s) - 180) <= 1

    # the game time between decisions is a whole number of ticks, however long the thinking
    frames = [x["stop"]["frames"] for _, x in log]
    assert all(f % TICK_FRAMES == 0 for f in frames)
    assert s.decisions == 5
    text = render_text(log[0][1])
    assert "There is a drop ahead." in text and "Stopped: completed (edge)" in text


def test_the_same_exchange_twice_gives_the_same_frames(tmp_path: Path) -> None:
    runs = []
    for i in range(2):
        s = example_session(tmp_path / str(i))
        runs.append(
            [
                s.decide(t)["frame"]
                for t in (
                    "walk_to(x=180, until=edge)",
                    "jump(right)",
                    "walk_to(x=180)",
                    "wait(ticks=2)",
                )
            ]
        )
    assert runs[0] == runs[1]
    assert all((f - runs[0][0]) % TICK_FRAMES == 0 for f in runs[0])


def test_the_pit_is_deeper_than_what_walking_with_until_edge_steps_down(tmp_path: Path) -> None:
    s = example_session(tmp_path)
    s.decide("move(right, until=edge)")
    assert pos(s) < PIT[0]  # it never walked in


def test_a_plain_walk_steps_off_the_ledge_and_falls_in(tmp_path: Path) -> None:
    s = example_session(tmp_path)
    s.decide("move(right)")
    assert pos(s) >= PIT[0]  # walking off a ledge is normal play
