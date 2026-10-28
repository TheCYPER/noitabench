"""Fixtures for the play-server tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from noitabench.agent import AgentSession, SessionConfig, ViewConfig
from noitabench.harness.workspace import Workspace
from noitabench.play import PlayApp, Response
from play_worlds import Arena, write_arena

HOST = "127.0.0.1:8765"
GET_HEADERS = {"host": HOST}
POST_HEADERS = {"host": HOST, "content-type": "application/json", "origin": f"http://{HOST}"}


class Client:
    """Calls a `PlayApp` the way the page does."""

    def __init__(self, app: PlayApp) -> None:
        self.app = app

    def get(self, path: str, headers: dict[str, str] | None = None) -> Response:
        return self.app.handle("GET", path, GET_HEADERS if headers is None else headers)

    def post(
        self, path: str, body: Any, headers: dict[str, str] | None = None, raw: bytes | None = None
    ) -> Response:
        data = raw if raw is not None else json.dumps(body).encode("utf-8")
        return self.app.handle("POST", path, POST_HEADERS if headers is None else headers, data)

    def decide(self, request: Any) -> dict[str, Any]:
        body = {"text": request} if isinstance(request, str) else request
        res = self.post("/api/decide", body)
        assert res.status == 200, res.body
        out: dict[str, Any] = res.json()
        return out

    def state(self) -> dict[str, Any]:
        res = self.get("/api/state")
        assert res.status == 200, res.body
        out: dict[str, Any] = res.json()
        return out


@pytest.fixture
def arena(tmp_path: Path) -> Arena:
    return write_arena(tmp_path / "arena")


@pytest.fixture
def make_app(arena: Arena, tmp_path: Path) -> Callable[..., PlayApp]:
    def make(
        *,
        max_decisions: int = 1000,
        recording: Path | None = None,
        notes_dir: Path | None = None,
        half: tuple[int, int] = (128, 96),
        ascii_map: bool = False,
    ) -> PlayApp:
        game = arena.game()
        game.step(61)  # land and let the opening invincibility end
        game.events()
        notes = Workspace(notes_dir or tmp_path / "workspace")
        config = SessionConfig(
            max_decisions=max_decisions, view=ViewConfig(text=True, ascii=ascii_map)
        )
        session = AgentSession(
            game,
            config=config,
            memory=notes,
            recording_dir=recording,
            notes="human play (noitabench.play)",
        )
        return PlayApp(session, game, notes, view_half=half)

    return make


@pytest.fixture
def app(make_app: Callable[..., PlayApp]) -> PlayApp:
    return make_app()


@pytest.fixture
def client(app: PlayApp) -> Client:
    return Client(app)
