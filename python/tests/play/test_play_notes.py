"""The notes panel: the harness workspace (same folder, same quota as an agent's notes) through
the play API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from conftest import Client
from noitabench.harness.workspace import Workspace
from noitabench.play import PlayApp


def write(client: Client, path: str, text: str, append: bool = False) -> dict:
    out: dict = client.post(
        "/api/notes", {"op": "write", "path": path, "text": text, "append": append}
    ).json()
    return out


def test_notes_api_round_trip(client: Client) -> None:
    res = write(client, "a.md", "hello")
    assert res == {"ok": True, "result": {"path": "notes/a.md", "chars": 5, "chars_left": 7995}}
    read = client.post("/api/notes", {"op": "read", "path": "a.md"}).json()["result"]
    assert read["text"] == "hello"
    listing = client.get("/api/notes").json()["result"]
    assert listing["files"] == [{"path": "notes/a.md", "chars": 5}]
    assert (listing["limit"], listing["used"], listing["chars_left"]) == (8000, 5, 7995)
    assert client.get("/api/notes/read?path=a.md").json()["result"]["text"] == "hello"
    edit = client.post("/api/notes", {"op": "edit", "path": "a.md", "old": "hello", "new": "bye"})
    assert edit.json()["result"]["chars"] == 3
    found = client.post("/api/notes", {"op": "search", "query": "bye"}).json()["result"]
    assert found["hits"][0]["path"] == "notes/a.md"
    write(client, "a.md", " more", append=True)
    assert client.get("/api/notes/read?path=a.md").json()["result"]["text"] == "bye more"
    gone = client.post("/api/notes", {"op": "delete", "path": "a.md"}).json()
    assert gone["ok"] is True and gone["result"]["deleted"] is True
    assert client.get("/api/notes").json()["result"]["files"] == []


def test_the_quota_is_the_agents_8000_characters(client: Client) -> None:
    full = write(client, "a.md", "x" * 8001)
    assert full["ok"] is False and full["error"]["code"] == "notes_full"
    assert write(client, "a.md", "x" * 8000)["ok"] is True
    again = write(client, "b.md", "y")
    assert again["error"]["code"] == "notes_full"
    assert client.get("/api/notes").json()["result"]["chars_left"] == 0
    # skills count against the same 8,000 characters as notes
    assert write(client, "skills/c.md", "z")["error"]["code"] == "notes_full"


def test_bad_paths_and_bad_requests(client: Client, tmp_path: Path) -> None:
    for path in ("../x", "/etc/passwd", ".hidden", "a//b", "a\\b"):
        assert write(client, path, "hi")["error"]["code"] == "bad_path", path
    assert client.post("/api/notes", {"op": "explode"}).status == 400
    assert client.post("/api/notes", {"op": "write", "path": "a.md"}).status == 400
    assert client.post("/api/notes", {"op": "write", "path": 3, "text": "x"}).status == 400
    missing = client.post("/api/notes", {"op": "read", "path": "nope.md"}).json()
    assert missing["ok"] is False and missing["error"]["code"] == "no_such_note"


def test_notes_cost_no_decision_and_are_what_memory_commands_see(client: Client) -> None:
    before = client.state()["answer"]["decisions_left"]
    write(client, "plan.md", "go right")
    assert client.state()["answer"]["decisions_left"] == before
    out = client.decide('memory_read(path="plan.md")')
    assert out["answer"]["results"][0]["result"]["text"] == "go right"
    client.decide('memory_write(path="found.md", text="lava is hot")')
    read = client.post("/api/notes", {"op": "read", "path": "found.md"}).json()
    assert read["result"]["text"] == "lava is hot"


def test_notes_stay_for_the_next_episode(make_app: Callable[..., PlayApp], tmp_path: Path) -> None:
    folder = tmp_path / "workspaces" / "human-5"
    first = Client(make_app(notes_dir=folder))
    write(first, "keep.md", "remember")
    second = Client(make_app(notes_dir=folder))
    assert second.get("/api/notes").json()["result"]["files"] == [
        {"path": "notes/keep.md", "chars": 8}
    ]
    assert (folder / "notes" / "keep.md").read_text() == "remember"
    assert isinstance(second.app.notes, Workspace)


def test_chinese_notes(client: Client) -> None:
    assert write(client, "化学.md", "水能灭火")["ok"] is True
    read = client.post("/api/notes", {"op": "read", "path": "化学.md"}).json()
    assert read["result"]["text"] == "水能灭火"
