"""The play server's API, in process: the page's requests without a browser."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from conftest import GET_HEADERS, POST_HEADERS, Client
from noitabench.agent import AgentSession, SessionConfig, ViewConfig
from noitabench.agent.content import CONTENT
from noitabench.agent.visibility import leaks
from noitabench.play import PlayApp
from play_worlds import GROUND, PLANK_X, SENTINELS, START_X, Arena


def window(view: dict) -> np.ndarray:
    raw = np.frombuffer(base64.b64decode(view["materials"]), dtype=np.uint8)
    return raw.reshape(view["height"], view["width"])


def burning(view: dict) -> np.ndarray:
    packed = np.frombuffer(base64.b64decode(view["burning"]), dtype=np.uint8)
    return np.unpackbits(packed)[: view["width"] * view["height"]].reshape(
        view["height"], view["width"]
    )


# -- hello and state -----------------------------------------------------------------------------


def test_hello_gives_the_constants_of_the_time_model(client: Client) -> None:
    res = client.get("/api/hello")
    assert res.status == 200
    hello = res.json()
    assert hello["mode"] == "pause"
    assert hello["tick_frames"] == 10
    assert hello["max_command_frames"] == 300
    assert hello["max_commands_per_decision"] == 4
    assert hello["max_decisions"] == 1000
    assert hello["notes_quota"] == 8000
    names = {c["name"] for c in hello["commands"]}
    assert {"move", "walk_to", "inspect", "edit_wand", "memory_write"} <= names


def test_state_is_decision_one_and_takes_no_time(client: Client) -> None:
    first = client.state()
    again = client.state()
    assert first["ok"] is True
    assert first["answer"]["decision"] == 1
    assert first["answer"]["stop"]["reason"] == "start"
    assert first["answer"]["frame"] == again["answer"]["frame"]
    assert first["answer"]["decisions_left"] == 1000
    assert first["closed"] is False
    state = first["answer"]["observation"]["state"]
    assert state["position"]["x"] == START_X
    assert "map" not in first["answer"]["observation"], "the page draws the picture itself"


def test_the_view_is_a_window_around_the_player(client: Client) -> None:
    view = client.state()["view"]
    assert (view["width"], view["height"]) == (256, 192)
    m = window(view)
    ox, oy = view["origin"]["x"], view["origin"]["y"]
    p = view["player"]
    # the player's hit box is inside the window and the window is centred on it
    cx, cy = p["x"] + p["w"] // 2, p["y"] + p["h"] // 2
    assert (ox + 128, oy + 96) == (cx, cy)
    # ground under the player: rock; air above it
    assert m[GROUND + 5 - oy, START_X - ox] != 0
    assert m[GROUND - 20 - oy, START_X - ox] == 0
    # the window hangs over the left edge of the world (x < 0): those cells are "outside"
    assert ox < 0
    assert (m[:, :-ox] == view["outside"]).all()
    assert view["outside"] == 255


def test_fire_is_a_separate_bit_mask(client: Client, app: PlayApp) -> None:
    before = client.state()["view"]
    assert burning(before).sum() == 0
    assert app.game.ignite(PLANK_X + 2, GROUND)
    view = client.state()["view"]
    mask = burning(view)
    assert mask.sum() >= 1
    gx, gy = PLANK_X + 2 - view["origin"]["x"], GROUND - view["origin"]["y"]
    assert mask[gy, gx] == 1
    assert mask[gy - 30, gx] == 0


def test_burning_rect_checks_its_rectangle(app: PlayApp) -> None:
    assert len(app.game.burning_rect(-5, -5, 10, 4)) == 40
    assert app.game.burning_rect(0, 0, 0, 7) == b""
    for bad in ((0, 0, -1, 2), (0, 0, 2, -1), (0, 0, 5000, 5000)):
        with pytest.raises(ValueError, match="burning_rect"):
            app.game.burning_rect(*bad)


def test_burning_rect_has_one_byte_per_cell_at_the_edges_of_the_integers(app: PlayApp) -> None:
    big = 2**31 - 1
    assert app.game.burning_rect(big - 1, 3, 5, 2) == bytes(10)
    assert app.game.burning_rect(3, big - 2, 2, 6) == bytes(12)
    assert app.game.burning_rect(-big - 1, -big - 1, 3, 3) == bytes(9)
    assert len(app.game.burning_rect(-300, -300, 64, 64)) == 64 * 64  # all outside the world


def test_fire_is_dark_wherever_the_picture_is_outside_the_world(client: Client) -> None:
    view = client.state()["view"]
    outside = window(view) == view["outside"]
    assert outside.any() and not outside.all()
    assert not (burning(view).astype(bool) & outside).any()


def test_the_legend_names_what_the_agents_ascii_legend_names_and_no_more(
    make_app: Callable[..., PlayApp],
) -> None:
    """The picture is the whole 256 x 192 window; names go no further than the ASCII map."""
    app = make_app(ascii_map=True)
    client = Client(app)
    keys = [m["key"] for m in json.loads((CONTENT / "materials.json").read_text())["materials"]]
    p = app.session.engine.player()
    px, py = p["x"] + p["w"] // 2, p["y"] + p["h"] // 2
    # water far above the player: inside the picture (+-96 rows), outside the ASCII map (+-64)
    app.game.fill_rect(px, py - 80, 6, 2, "water")
    # lava just above the ground: inside both
    app.game.fill_rect(px + 20, py + 5, 8, 2, "lava")
    state = client.state()
    view = state["view"]
    seen = set(window(view).ravel().tolist())
    water, lava = keys.index("water"), keys.index("lava")
    assert {water, lava} <= seen, "both are in the picture"
    ascii_names = set(state["answer"]["observation"]["map"]["legend"].values())
    legend = view["legend"]
    assert all(set(e) == {"index", "name"} for e in legend)
    assert [e["index"] for e in legend] == sorted(e["index"] for e in legend)
    named = {keys[e["index"]] for e in legend}
    assert named == ascii_names & set(keys), (
        "materials only: creatures and items are drawn as boxes"
    )
    assert "lava" in named and "water" not in named
    # the names come with the legend: display names, and only for these materials
    rows = {m["key"]: m for m in json.loads((CONTENT / "materials.json").read_text())["materials"]}
    assert {e["index"]: e["name"] for e in legend}[lava] == rows["lava"]["name_zh"]
    assert water not in {e["index"] for e in legend}


def test_only_what_an_agent_may_see_leaves_the_server(client: Client, arena: Arena) -> None:
    for res in (client.get("/api/state"), client.get("/api/hello")):
        text = res.body.decode("utf-8")
        assert not leaks(res.json())
        for word in SENTINELS:
            assert word not in text
        assert "rule_seed" not in text
    view = client.state()["view"]
    allowed = {"id", "kind", "x", "y", "w", "h", "hostile", "aimed"}
    assert view["entities"], "the bottle on the ground is in view"
    for e in view["entities"]:
        assert set(e) <= allowed, "no health, contents or statuses: those come from inspect"
    assert {e["kind"] for e in view["entities"]} == {"bottle"}


def test_the_pictures_things_are_the_agents_nearby_list(client: Client, app: PlayApp) -> None:
    """Same things, same fields (kind, place, size, hostile, aimed): the page sees no more."""
    near = app.game.spawn_enemy("longleg", START_X + 40, GROUND)
    app.game.spawn_enemy("longleg", 160, GROUND)  # behind the wall
    app.game.step(2)
    client.decide(f"aim(target={near})")
    state = client.state()
    nearby = {e["id"]: e for e in state["answer"]["observation"]["state"]["nearby"]}
    things = {e["id"]: e for e in state["view"]["entities"]}
    assert near in things and set(things) == set(nearby)
    for ident, thing in things.items():
        agent = nearby[ident]
        assert thing == {k: agent[k] for k in thing}, ident
        assert set(agent) - set(thing) <= {"dx", "dy"}, "only the offsets are the agent's alone"
    assert things[near]["aimed"] is True and things[near]["hostile"] is True


def test_creatures_behind_a_wall_are_not_in_the_view(client: Client, app: PlayApp) -> None:
    near = app.game.spawn_enemy("longleg", START_X + 40, GROUND)
    behind = app.game.spawn_enemy("longleg", 160, GROUND)  # beyond the 6-wide rock wall at x 120
    app.game.step(2)
    ids = {e["id"]: e for e in client.state()["view"]["entities"]}
    assert near in ids and ids[near]["hostile"] is True
    assert behind not in ids


# -- decisions -----------------------------------------------------------------------------------


def test_a_decision_moves_the_player_and_costs_one(client: Client) -> None:
    out = client.decide("move(right, ticks=2)")
    assert out["ok"] is True
    assert out["cost"] == 1
    assert out["answer"]["decision"] == 2
    assert out["answer"]["frame"] == client.state()["answer"]["frame"]
    assert out["answer"]["stop"]["frames"] == 20
    assert out["answer"]["observation"]["state"]["position"]["x"] > START_X
    assert out["view"]["player"]["x"] > START_X - 2


def test_commands_as_objects_are_a_decision_too(client: Client) -> None:
    body = {"commands": [{"name": "move", "args": {"direction": "left", "ticks": 1}}], "id": 9}
    out = client.decide(body)
    assert out["ok"] is True and out["id"] == 9
    assert out["answer"]["results"][0]["command"] == "move"


def test_the_server_plays_exactly_like_a_session(
    make_app: Callable[..., PlayApp], arena: Arena
) -> None:
    """The play server adds nothing to the game: same decisions, same answers, same state."""
    client = Client(make_app())
    twin = arena.game()
    twin.step(61)
    twin.events()
    session = AgentSession(twin, config=SessionConfig(view=ViewConfig(text=True, ascii=False)))
    plan = [
        "move(right, ticks=3)",
        "jump(right); wait(ticks=2)",
        "aim(angle=-45); fire(ticks=2)",
        "inspect(x=60, y=109); inspect(x=61, y=109)",
        "kick",
    ]
    for text in plan:
        before = session.decisions
        out = client.decide(text)
        direct = session.decide(text)
        assert out["answer"] == direct, text
        assert out["cost"] == session.decisions - before, text
    assert client.app.session.state_hash() == session.state_hash()


def test_the_decision_log_is_the_one_a_plain_session_writes(
    make_app: Callable[..., PlayApp], arena: Arena, tmp_path: Path
) -> None:
    """Through HTTP or direct: the same answers, the same `decisions.jsonl`, the same state;
    invalid text, a fifth command and a pair of inspects included."""
    client = Client(make_app(recording=tmp_path / "web-run"))
    twin = arena.game()
    twin.step(61)
    twin.events()
    session = AgentSession(
        twin,
        config=SessionConfig(view=ViewConfig(text=True, ascii=False)),
        recording_dir=tmp_path / "plain-run",
        notes="human play (noitabench.play)",
    )
    plan = [
        "move(right, ticks=3)",
        "wait(ticks=1); wait(ticks=1); wait(ticks=1); wait(ticks=1); wait(ticks=1)",  # 5 commands
        "walk_to(",  # cannot be read
        "fly_to_the_moon()",
        "inspect(x=60, y=109); inspect(x=61, y=109); kick",
        "aim(angle=10)",
    ]
    for text in plan:
        before = session.decisions
        out = client.decide(text)  # the page sends {"text": ...}
        direct = session.decide({"text": text})  # so does a JSON Lines client
        assert out["answer"] == direct, text
        assert out["cost"] == session.decisions - before >= 1, text
    # the fifth command was refused with the whole decision; the inspects cost one each
    assert client.app.session.decisions == session.decisions == 1 + 1 + 1 + 1 + 3 + 1
    client.post("/api/close", {})
    session.close()
    web_log = (tmp_path / "web-run" / "decisions.jsonl").read_text().splitlines()
    plain_log = (tmp_path / "plain-run" / "decisions.jsonl").read_text().splitlines()
    assert web_log == plain_log and len(web_log) == len(plan)
    codes = [json.loads(line)["result"].get("code") for line in web_log]
    assert codes[1] == "too_many_commands"
    assert client.app.session.state_hash() == session.state_hash()


def test_an_invalid_command_costs_a_decision_and_no_time(client: Client) -> None:
    out = client.decide("fly_to_the_moon()")
    assert out["ok"] is False
    assert out["cost"] == 1
    assert out["answer"]["stop"]["reason"] == "invalid"
    assert out["answer"]["results"][0]["code"] == "unknown_command"
    assert out["answer"]["frame"] == client.state()["answer"]["frame"]


def test_inspect_costs_a_decision_and_no_game_time(client: Client) -> None:
    f0 = client.state()["answer"]["frame"]
    one = client.decide("inspect(x=45, y=112)")
    assert (one["cost"], one["answer"]["frame"]) == (1, f0)
    two = client.decide("inspect(x=45, y=112); inspect(x=46, y=112)")
    assert (two["cost"], two["answer"]["frame"]) == (2, f0)
    assert two["answer"]["decisions_left"] == 1000 - 3
    result = one["answer"]["results"][0]["result"]
    assert "rock" in json.dumps(result) or "ground" in json.dumps(result)


def test_wands_can_be_edited_only_in_a_rest_area(client: Client) -> None:
    here = client.decide("edit_wand(op=swap, wand=0, a=0, b=0)")
    # the player starts inside the rest area: the edit is allowed (it may still fail on its slots)
    assert here["answer"]["results"][0].get("code") != "not_here"
    client.decide("walk_to(x=100)")
    far = client.decide("edit_wand(op=swap, wand=0, a=0, b=0)")
    assert far["answer"]["results"][0]["code"] == "not_here"
    assert client.state()["answer"]["observation"]["state"]["can_edit_wands"] is False


def test_the_decision_limit_ends_the_episode_and_closes_the_session(
    make_app: Callable[..., PlayApp], tmp_path: Path
) -> None:
    out = tmp_path / "run"
    app = make_app(max_decisions=2, recording=out)
    client = Client(app)
    first = client.decide("wait(ticks=1)")
    assert first["closed"] is False and "summary" not in first
    last = client.decide("wait(ticks=1)")
    assert last["answer"]["over"] == "decision_limit"
    assert last["answer"]["decisions_left"] == 0
    assert last["closed"] is True and last["summary"]["decisions"] == 2
    assert last["summary"]["recording"], "the recording is finished"
    # the picture of the end is still there for the page; more decisions are refused
    state = client.state()
    assert state["closed"] is True and state["answer"]["over"] == "decision_limit"
    assert state["summary"] == last["summary"]
    assert client.post("/api/decide", {"text": "wait(ticks=1)"}).status == 409
    assert client.post("/api/close", {}).json()["summary"] == last["summary"], (
        "closing again is fine"
    )
    lines = [json.loads(x) for x in (out / "decisions.jsonl").read_text().splitlines()]
    assert [x["index"] for x in lines] == [1, 2]
    assert (out / "meta.json").is_file() and (out / "frames.bin").is_file()


def test_dying_ends_the_episode_the_same_way(
    make_app: Callable[..., PlayApp], tmp_path: Path
) -> None:
    out = tmp_path / "run"
    app = make_app(recording=out)
    seen: list[dict] = []
    app.on_close = seen.append
    client = Client(app)
    p = app.session.engine.player()
    px, py = p["x"] + p["w"] // 2, p["y"] + p["h"] // 2
    app.game.fill_rect(px - 12, py - 12, 24, 20, "lava")  # the player stands in it
    dead = client.decide("wait(ticks=30)")
    for _ in range(10):  # the damage interrupts each wait; a few ticks of lava are enough
        if dead["answer"]["over"]:
            break
        assert dead["closed"] is False
        dead = client.decide("wait(ticks=30)")
    assert dead["answer"]["over"] == "dead"
    assert dead["closed"] is True and dead["summary"]["recording"]
    assert len(seen) == 1, "the close hook ran once"
    assert client.post("/api/decide", {"text": "wait"}).status == 409
    assert client.state()["answer"]["over"] == "dead"
    meta = json.loads((out / "meta.json").read_text())
    assert meta["format"] == "cogbench-rec/0"
    assert (out / "decisions.jsonl").read_text().strip(), "the decision log is closed and complete"


def test_interrupts_stop_a_long_command_as_for_an_agent(client: Client, app: PlayApp) -> None:
    app.game.spawn_enemy("longleg", START_X + 90, GROUND)
    out = client.decide("move(right, ticks=30)")
    assert out["answer"]["stop"]["reason"] == "interrupted"


def test_a_bomb_does_not_make_the_view_diverge_from_the_grid(client: Client, app: PlayApp) -> None:
    app.game.blast(START_X + 20, GROUND + 6, 8)
    view = client.state()["view"]
    m = window(view)
    gx, gy = START_X + 20 - view["origin"]["x"], GROUND + 6 - view["origin"]["y"]
    assert m[gy, gx] == 0, "the crater is in the picture"


# -- transport errors ----------------------------------------------------------------------------


def test_bad_requests_are_refused(client: Client) -> None:
    assert client.post("/api/decide", None, raw=b"{not json").status == 400
    assert client.post("/api/decide", None, raw=b"[1, 2]").status == 400
    assert client.post("/api/decide", {"nothing": 1}).status == 400
    assert client.post("/api/nothing", {}).status == 404
    assert client.get("/api/nothing").status == 404
    assert (
        client.post(
            "/api/decide", {"text": "x"}, headers={**POST_HEADERS, "content-type": "text/plain"}
        ).status
        == 415
    )
    assert client.post("/api/decide", {"text": "x" * 70_000}).status == 413
    assert client.app.handle("PUT", "/api/decide", POST_HEADERS, b"{}").status == 405


def test_only_this_machine_and_this_page_may_call(client: Client) -> None:
    assert client.get("/api/state", headers={"host": "evil.example"}).status == 403
    assert client.get("/api/state", headers={"host": "127.0.0.1:8765.evil.example"}).status == 403
    assert client.get("/api/state", headers={"host": "localhost:8765"}).status == 200
    other = {**POST_HEADERS, "origin": "http://evil.example"}
    assert client.post("/api/decide", {"text": "wait"}, headers=other).status == 403
    no_origin = {k: v for k, v in POST_HEADERS.items() if k != "origin"}
    assert client.post("/api/decide", {"text": "wait"}, headers=no_origin).status == 200


def test_a_host_with_a_trailing_newline_is_not_this_machine(client: Client) -> None:
    assert client.get("/api/state", headers={"host": "127.0.0.1:8765\n"}).status == 403
    assert client.get("/api/state", headers={"host": "localhost\n"}).status == 403


def test_the_content_type_must_be_json_exactly(client: Client) -> None:
    for kind, status in (
        ("application/json", 200),
        ("Application/JSON; charset=utf-8", 200),
        ("application/jsonx", 415),
        ("application/json5", 415),
        ("text/plain; application/json", 415),
    ):
        headers = {**POST_HEADERS, "content-type": kind}
        res = client.post("/api/notes", {"op": "list"}, headers=headers)
        assert res.status == status, kind


def test_a_bug_is_logged_but_its_text_does_not_reach_the_page(
    client: Client, app: PlayApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> dict:
        raise RuntimeError("the rule seed is 12345")

    monkeypatch.setattr(app, "state", boom)
    res = client.get("/api/state")
    assert res.status == 500
    assert res.json()["error"]["code"] == "internal"
    assert "12345" not in res.body.decode() and "RuntimeError" in res.body.decode()


# -- close ---------------------------------------------------------------------------------------


def test_close_ends_the_session_and_writes_the_recording(
    make_app: Callable[..., PlayApp], tmp_path: Path
) -> None:
    out = tmp_path / "run"
    app = make_app(recording=out)
    client = Client(app)
    client.decide("move(right, ticks=2)")
    client.decide("inspect(x=45, y=112)")
    res = client.post("/api/close", {})
    assert res.status == 200
    summary = res.json()["summary"]
    assert summary["decisions"] == 2
    assert summary["frames"] >= 20
    assert client.post("/api/close", {}).json()["summary"] == summary
    assert client.post("/api/decide", {"text": "wait"}).status == 409
    assert client.state()["closed"] is True
    lines = [json.loads(x) for x in (out / "decisions.jsonl").read_text().splitlines()]
    assert [x["index"] for x in lines] == [1, 2]
    assert [x["cost"] for x in lines] == [1, 1]
    assert lines[0]["stop_reason"] == "start"
    assert (out / "meta.json").is_file() and (out / "frames.bin").is_file()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["format"] == "cogbench-rec/0"
    assert "human" in meta["notes"]


def test_on_close_is_called_once(make_app: Callable[..., PlayApp]) -> None:
    app = make_app()
    seen: list[dict] = []
    app.on_close = seen.append
    Client(app).post("/api/close", {})
    Client(app).post("/api/close", {})
    assert len(seen) == 1


def test_get_headers_are_the_ones_the_tests_assume() -> None:
    assert GET_HEADERS["host"].startswith("127.0.0.1")
