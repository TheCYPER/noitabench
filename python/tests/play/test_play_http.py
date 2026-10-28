"""The real thing: `http.server` on a free port, driven with the standard library."""

from __future__ import annotations

import http.client
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from noitabench.harness.workspace import Workspace
from noitabench.play import PlayApp
from noitabench.play.app import WEB_ROOT
from noitabench.play.cli import _parser, build_app, world_folder
from noitabench.play.server import make_server, serve_in_thread
from play_worlds import START_X, Arena


def start(app: PlayApp):
    server = make_server(app, 0)  # port 0: any free port
    serve_in_thread(server)
    return server


@pytest.fixture
def served(arena: Arena, tmp_path: Path) -> Iterator[tuple[PlayApp, int]]:
    args = _parser().parse_args(
        [
            "serve",
            "--world-files",
            str(arena.png),
            str(arena.json),
            "--no-record",
            "--workspace-root",
            str(tmp_path / "ws"),
        ]
    )
    app = build_app(args, None)
    server = start(app)
    yield app, server.server_port
    server.shutdown()
    server.server_close()
    app.close()


def call(
    port: int, method: str, path: str, body: object | None = None, headers: dict | None = None
):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body)
        hdrs.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=hdrs)
    res = conn.getresponse()
    payload = res.read()
    conn.close()
    return res, payload


def test_a_short_game_over_http(served: tuple[PlayApp, int]) -> None:
    _app, port = served
    res, body = call(port, "GET", "/web/play.html")
    assert res.status == 200 and b"<canvas" in body
    res, body = call(port, "GET", "/api/state")
    first = json.loads(body)
    assert res.status == 200 and first["answer"]["decision"] == 1
    x0 = first["answer"]["observation"]["state"]["position"]["x"]
    assert x0 == START_X
    res, body = call(port, "POST", "/api/decide", {"text": "move(right, ticks=3); wait(ticks=1)"})
    out = json.loads(body)
    assert res.status == 200 and out["cost"] == 1
    assert out["answer"]["observation"]["state"]["position"]["x"] > x0
    res, body = call(port, "POST", "/api/notes", {"op": "write", "path": "n.md", "text": "ok"})
    assert json.loads(body)["ok"] is True
    res, body = call(port, "POST", "/api/close", {})
    assert json.loads(body)["summary"]["decisions"] == 1
    res, _ = call(port, "POST", "/api/decide", {"text": "wait"})
    assert res.status == 409


def test_the_server_refuses_a_foreign_host_and_a_foreign_origin(
    served: tuple[PlayApp, int],
) -> None:
    _app, port = served
    res, _ = call(port, "GET", "/api/state", headers={"Host": "evil.example"})
    assert res.status == 403
    res, _ = call(port, "POST", "/api/decide", {"text": "wait"}, {"Origin": "http://evil.example"})
    assert res.status == 403
    res, _ = call(port, "POST", "/api/decide", {"text": "wait"}, {"Content-Type": "text/plain"})
    assert res.status == 415
    res, _ = call(port, "PUT", "/api/decide", {"text": "wait"})
    assert res.status == 405


def test_the_server_listens_on_this_machine_only(served: tuple[PlayApp, int]) -> None:
    app, port = served
    server = make_server(app, 0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
    assert port > 0


def test_a_huge_body_is_refused_without_reading_it(served: tuple[PlayApp, int]) -> None:
    _app, port = served
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.putrequest("POST", "/api/decide")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(10_000_000))
    conn.endheaders()
    res = conn.getresponse()
    assert res.status == 413
    conn.close()


def raw_exchange(port: int, request: bytes) -> bytes:
    """Sends bytes as they are and returns everything the server says before it hangs up."""
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request)
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    return data


def test_requests_that_could_be_smuggled_or_doubled_are_refused(
    served: tuple[PlayApp, int],
) -> None:
    _app, port = served
    ok = f"Host: 127.0.0.1:{port}\r\n"
    close = "Connection: close\r\n\r\n"
    twice = raw_exchange(
        port, f"GET /api/state HTTP/1.1\r\nHost: evil.example\r\n{ok}{close}".encode()
    )
    assert twice.startswith(b"HTTP/1.1 400"), "two Host headers: the second must not win"
    chunked = raw_exchange(
        port,
        (
            f"POST /api/notes HTTP/1.1\r\n{ok}Content-Type: application/json\r\n"
            f"Transfer-Encoding: chunked\r\n{close}0\r\n\r\n"
        ).encode(),
    )
    assert chunked.startswith(b"HTTP/1.1 400")
    for length in ("-5", "abc", str(10**9)):
        bad = raw_exchange(
            port,
            (
                f"POST /api/notes HTTP/1.1\r\n{ok}Content-Type: application/json\r\n"
                f"Content-Length: {length}\r\n{close}"
            ).encode(),
        )
        assert bad.startswith(b"HTTP/1.1 413"), length


def test_a_broken_request_line_is_answered(
    served: tuple[PlayApp, int],
) -> None:
    _app, port = served
    for line in (b"NOT A REQUEST", b"Host: 127.0.0.1", b"GET", b"\xff\xfe /x HTTP/1.1"):
        answer = raw_exchange(port, line + b"\r\n\r\n")
        # the handler once died writing the log line of such a request: nothing was answered
        assert b"400" in answer or b"501" in answer, line


def test_options_and_head_are_not_answered_so_no_cross_site_preflight_passes(
    served: tuple[PlayApp, int],
) -> None:
    _app, port = served
    for method in ("OPTIONS", "HEAD"):
        res, _ = call(port, method, "/api/decide", headers={"Origin": "http://evil.example"})
        assert res.status == 501
        assert res.getheader("Access-Control-Allow-Origin") is None


def test_no_response_lets_another_site_read_it(served: tuple[PlayApp, int]) -> None:
    _app, port = served
    for path in ("/api/state", "/api/hello", "/web/play.html", "/content/materials.json"):
        res, _ = call(port, "GET", path, headers={"Origin": "http://evil.example"})
        assert res.status == 200
        assert not [h for h, _ in res.getheaders() if h.lower().startswith("access-control-")]


def test_the_server_will_not_bind_a_public_address(served: tuple[PlayApp, int]) -> None:
    app, _port = served
    for host in ("0.0.0.0", "", "192.168.1.5", "example.com"):
        with pytest.raises(ValueError, match="this machine only"):
            make_server(app, 0, host=host)


# -- the command line ------------------------------------------------------------------------------


def test_build_app_from_world_files(arena: Arena, tmp_path: Path) -> None:
    args = _parser().parse_args(
        [
            "serve",
            "--world-files",
            str(arena.png),
            str(arena.json),
            "--workspace-root",
            str(tmp_path / "w"),
        ]
    )
    out = tmp_path / "run"
    app = build_app(args, out)
    try:
        state = app.state()
        assert state["answer"]["decision"] == 1
        assert "map" not in state["answer"]["observation"], "no ASCII map unless --ascii"
        assert isinstance(app.notes, Workspace)
        # the arena's world file says rule seed 5: the notes folder is that family's
        assert app.notes.root == tmp_path / "w" / "human-5"
    finally:
        app.close()
    assert (out / "decisions.jsonl").exists() and (out / "meta.json").exists()


def test_the_generated_world_goes_beside_the_recording_not_into_it(tmp_path: Path) -> None:
    """The world file carries the tooling fields of the level (encounters, must-pass markers):
    a human who can see the recording folder must not find it there."""
    args = _parser().parse_args(
        ["serve", "--world-seed", "3", "--workspace-root", str(tmp_path / "w")]
    )
    out = tmp_path / "runs" / "play-3"
    assert world_folder(out) == tmp_path.resolve() / "runs" / "play-3-world"
    app = build_app(args, out)
    try:
        assert (world_folder(out) / "world_3.png").is_file()
        assert (world_folder(out) / "world_3.json").is_file()
    finally:
        app.close()
    names = {p.name for p in out.rglob("*")}
    assert {"decisions.jsonl", "frames.bin", "meta.json"} <= names, "the recording is there"
    assert not any(n.endswith(".png") or "world" in n for n in names), names


def test_nothing_that_is_recorded_may_live_under_the_served_folder(tmp_path: Path) -> None:
    args = _parser().parse_args(["serve", "--world-seed", "3", "--workspace-root", str(tmp_path)])
    with pytest.raises(SystemExit, match="inside web/"):
        build_app(args, WEB_ROOT / "runs" / "play-3")
    assert not (WEB_ROOT / "runs").exists(), "and nothing was created there"
    with pytest.raises(SystemExit, match="inside web/"):
        build_app(args, WEB_ROOT / "play-3")


def test_the_served_folder_is_recognised_through_a_link_and_a_different_spelling(
    tmp_path: Path,
) -> None:
    """Asked of the file system: a link to `web/` and, where the file system ignores case,
    `WEB/` are the served folder too."""
    from noitabench.play.cli import _inside_web

    link = tmp_path / "shortcut"
    link.symlink_to(WEB_ROOT, target_is_directory=True)
    assert _inside_web(link / "runs" / "play-3") and _inside_web(link)
    assert not _inside_web(tmp_path / "runs" / "play-3")
    assert not _inside_web(WEB_ROOT.parent / "runs" / "play-3")
    shouted = WEB_ROOT.parent / WEB_ROOT.name.upper()
    if shouted.exists():  # a Mac or a Windows machine
        assert _inside_web(shouted / "runs" / "play-3")


def test_the_ascii_map_is_there_when_asked(arena: Arena, tmp_path: Path) -> None:
    args = _parser().parse_args(
        [
            "serve",
            "--world-files",
            str(arena.png),
            str(arena.json),
            "--no-record",
            "--ascii",
            "--workspace-root",
            str(tmp_path / "w"),
            "--family",
            "mine",
        ]
    )
    app = build_app(args, None)
    try:
        assert "map" in app.state()["answer"]["observation"]
        assert app.notes.root.name == "mine"
    finally:
        app.close()


def test_the_command_line_checks_its_arguments(arena: Arena, tmp_path: Path) -> None:
    parser = _parser()
    with pytest.raises(SystemExit):
        build_app(parser.parse_args(["serve"]), None)
    both = parser.parse_args(
        ["serve", "--world-seed", "3", "--world-files", str(arena.png), str(arena.json)]
    )
    with pytest.raises(SystemExit):
        build_app(both, None)
    bad = parser.parse_args(
        ["serve", "--world-files", str(arena.png), str(arena.json), "--family", "../x"]
    )
    with pytest.raises(SystemExit):
        build_app(bad, None)


def test_a_port_that_is_taken_is_reported_not_a_traceback(arena: Arena, tmp_path: Path) -> None:
    import socket

    from noitabench.play.cli import cmd_serve

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        args = _parser().parse_args(
            [
                "serve",
                "--world-files",
                str(arena.png),
                str(arena.json),
                "--no-record",
                "--port",
                str(taken.getsockname()[1]),
                "--workspace-root",
                str(tmp_path / "w"),
            ]
        )
        with pytest.raises(SystemExit) as err:
            cmd_serve(args)
    assert "cannot listen" in str(err.value)
