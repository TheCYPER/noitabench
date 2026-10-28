"""`PlayApp`: the whole play server as one object, with no sockets in it.

    app = PlayApp(session, game, notes)
    response = app.handle("POST", "/api/decide", headers, b'{"text": "walk_to(x=180)"}')

The player drives the *same* `AgentSession` an agent does: the same commands, the same time
model, the same interrupts, the same decision budget, and the same recording and
`decisions.jsonl`. The server adds nothing to the game: it carries decisions in, and out it
carries the answer and a picture of the cells in view (`view.py`).

Routes (JSON in and out, everything under `/api/` is for the page):

    GET  /                    -> redirect to /web/play.html
    GET  /web/...             the static files of the web client (not `web/tests`)
    GET  /content/materials.json   the colour of each material index, nothing else (no names:
                              those come with the view's legend and with `inspect`)
    GET  /api/hello           constants of the time model, the command table, the quotas
    GET  /api/state           {ok, answer, view}: the current answer (no time passes)
    POST /api/decide          a decision: {text}, {commands: [...]} or one command; returns
                              {ok, answer, view, cost, closed[, summary]}; when the episode is
                              over (death, no decisions left) the session closes by itself, the
                              recording is finished and `closed` / `summary` say so
    GET  /api/notes           the notes list (+ limit, used, chars_left);  GET /api/notes/read?path=
    POST /api/notes           {op: list|read|write|edit|search|delete, ...} on the same files
                              an agent's memory_* commands use; no decision, no game time
    POST /api/close           end the session, stop the recording; returns the summary

Errors of the transport (unreadable JSON, a wrong host, an unknown route) are HTTP 4xx with
`{ok: false, error: {code, message}}`; a command the game refuses is HTTP 200 with `ok: false`
in the answer, as in the JSON Lines protocol.
"""

from __future__ import annotations

import json
import re
import threading
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from noitabench.agent.content import CONTENT, REPO
from noitabench.agent.errors import CommandError
from noitabench.agent.memory import MemoryBackend
from noitabench.agent.protocol import DECISION_KEYS
from noitabench.agent.session import AgentSession
from noitabench.agent.spec import COMMANDS
from noitabench.agent.vocab import (
    MAX_COMMAND_FRAMES,
    MAX_COMMANDS,
    PROTOCOL,
    SHOT_HALF,
    TICK_FRAMES,
)
from noitabench.game import Game

from .view import build_view

WEB_ROOT = REPO / "web"
HIDDEN_DIRS = frozenset({"tests", "node_modules"})  # lower case: compared with the name lowered
MAX_BODY = 64 * 1024
LOCAL_HOST = re.compile(r"^(127\.0\.0\.1|localhost)(:[0-9]{1,5})?$")
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}
# The page loads nothing from another site: no CDN, no font, no analytics.
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
}


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def json_response(status: int, obj: Any) -> Response:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return Response(status, {"Content-Type": "application/json; charset=utf-8"}, body)


def error_response(status: int, code: str, message: str) -> Response:
    return json_response(status, {"ok": False, "error": {"code": code, "message": message}})


class PlayApp:
    """The server logic for one human episode."""

    def __init__(
        self,
        session: AgentSession,
        game: Game,
        notes: MemoryBackend,
        *,
        web_root: Path = WEB_ROOT,
        content_dir: Path = CONTENT,
        view_half: tuple[int, int] = SHOT_HALF,
        on_close: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.session = session
        self.game = game
        self.notes = notes
        self.web_root = web_root.resolve()
        self.content_dir = content_dir
        self.view_half = view_half
        self.on_close = on_close
        self.closed = False
        self.summary: dict[str, Any] | None = None
        # the game is not thread-safe: one request at a time (re-entrant: `close` takes it too, from
        # a request and from the command line)
        self._lock = threading.RLock()
        self._materials: bytes | None = None
        self._names: dict[int, str] | None = None

    # -- entry point ------------------------------------------------------------------------------

    def handle(
        self, method: str, target: str, headers: Mapping[str, str] | None = None, body: bytes = b""
    ) -> Response:
        """The response to one request. `headers` need lower-case names."""
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        refused = self._guard(method, headers)
        if refused is not None:
            return _secured(refused)
        try:
            with self._lock:
                return _secured(self._route(method, target, body))
        except Exception as err:  # noqa: BLE001 - a bug: log it, keep the server up
            traceback.print_exc()
            # The text of an exception can quote game state; the page gets the kind only.
            return _secured(
                error_response(
                    500, "internal", f"The server hit a bug ({type(err).__name__}); see its log."
                )
            )

    # -- guards -----------------------------------------------------------------------------------

    def _guard(self, method: str, headers: Mapping[str, str]) -> Response | None:
        """Only this machine, only this page (DNS rebinding and cross-site posts)."""
        host = headers.get("host", "")
        if not LOCAL_HOST.fullmatch(host):  # fullmatch: `$` would let a trailing newline through
            return error_response(403, "bad_host", "This server answers only on 127.0.0.1.")
        if method not in ("GET", "POST"):
            return error_response(405, "bad_method", f"{method} is not supported.")
        if method == "POST":
            media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                return error_response(415, "bad_type", "POST bodies must be application/json.")
            origin = headers.get("origin")
            if origin is not None and origin != f"http://{host}":
                return error_response(403, "bad_origin", "Requests must come from this page.")
        return None

    # -- routing ----------------------------------------------------------------------------------

    def _route(self, method: str, target: str, body: bytes) -> Response:
        url = urlsplit(target)
        path = unquote(url.path)
        if method == "GET":
            if path == "/":
                return Response(302, {"Location": "/web/play.html"})
            if path.startswith("/web/"):
                return self._static(path[len("/web/") :])
            if path == "/favicon.ico":
                return Response(204)
            if path == "/content/materials.json":
                return self._materials_response()
            if path == "/api/hello":
                return json_response(200, self.hello())
            if path == "/api/state":
                return json_response(200, self.state())
            if path == "/api/notes":
                return self._notes_op({"op": "list"})
            if path == "/api/notes/read":
                return self._notes_op(
                    {"op": "read", "path": parse_qs(url.query).get("path", [""])[0]}
                )
            return error_response(404, "not_found", f"No such page: {path}")
        if len(body) > MAX_BODY:
            return error_response(413, "too_large", f"Bodies are limited to {MAX_BODY} bytes.")
        if path in ("/api/decide", "/api/notes", "/api/close"):
            data, bad = _json_object(body)
            if bad is not None:
                return bad
            if path == "/api/decide":
                return self._decide(data)
            if path == "/api/notes":
                return self._notes_op(data)
            return json_response(200, {"ok": True, "summary": self.close()})
        return error_response(404, "not_found", f"No such route: {path}")

    # -- the game ---------------------------------------------------------------------------------

    def hello(self) -> dict[str, Any]:
        return {
            "ok": True,
            "protocol": PROTOCOL,
            "mode": "pause",
            "tick_frames": TICK_FRAMES,
            "max_command_frames": MAX_COMMAND_FRAMES,
            "max_commands_per_decision": MAX_COMMANDS,
            "max_decisions": self.session.config.max_decisions,
            "notes_quota": self._notes_listing().get("limit"),
            "commands": [_command_info(c) for c in COMMANDS.values()],
        }

    def state(self) -> dict[str, Any]:
        """The current answer and view; no time passes and no decision is used."""
        answer = self.session.observe()
        out = {
            "ok": _all_ok(answer),
            "answer": answer,
            "view": self._view(),
            "closed": self.closed,
        }
        if self.summary is not None:
            out["summary"] = self.summary
        return out

    def _view(self) -> dict[str, Any]:
        return build_view(self.session, self.game, self.view_half, self._display_names())

    def _display_names(self) -> dict[int, str]:
        """Material index -> the name the page shows in its colour key (read once)."""
        if self._names is None:
            doc = json.loads((self.content_dir / "materials.json").read_text(encoding="utf-8"))
            self._names = {m["index"]: m.get("name_zh") or m["key"] for m in doc["materials"]}
        return self._names

    def _decide(self, data: dict[str, Any]) -> Response:
        if self.closed:
            return error_response(409, "closed", "The session has ended.")
        request = {k: v for k, v in data.items() if k != "id"}
        if not any(k in request for k in DECISION_KEYS):
            return error_response(
                400, "bad_request", f"A decision needs one of: {', '.join(DECISION_KEYS)}."
            )
        before = self.session.decisions
        answer = self.session.decide(request)
        if answer["over"]:  # death or the last decision: the episode ends here, recording and all
            self.close()
        out = {
            "ok": _all_ok(answer),
            "answer": answer,
            "view": self._view(),
            "cost": self.session.decisions - before,
            "closed": self.closed,
        }
        if self.summary is not None:
            out["summary"] = self.summary
        if "id" in data:
            out["id"] = data["id"]
        return json_response(200, out)

    def close(self) -> dict[str, Any]:
        """End the session (stops the recording, closes the decision log). Idempotent."""
        with self._lock:  # not while a decision is running
            if self.summary is None:
                self.summary = self.session.close()
                self.closed = True
                if self.on_close is not None:
                    self.on_close(self.summary)
            return self.summary

    # -- notes ------------------------------------------------------------------------------------

    def _notes_op(self, data: dict[str, Any]) -> Response:
        op = data.get("op")
        try:
            if op == "list":
                result = self._notes_listing()
            elif op == "read":
                result = self.notes.read(_text(data, "path"))
            elif op == "write":
                result = self.notes.write(
                    _text(data, "path"), _text(data, "text"), bool(data.get("append", False))
                )
            elif op == "edit":
                result = self.notes.edit(
                    _text(data, "path"), _text(data, "old"), _text(data, "new")
                )
            elif op == "search":
                result = self.notes.search(_text(data, "query"))
            elif op == "delete" and hasattr(self.notes, "delete"):
                result = self.notes.delete(_text(data, "path"))
            else:
                return error_response(
                    400, "bad_request", "op must be list, read, write, edit, search or delete."
                )
        except CommandError as err:
            return json_response(
                200, {"ok": False, "error": {"code": err.code, "message": err.message}}
            )
        except _BadField as err:
            return error_response(400, "bad_request", str(err))
        return json_response(200, {"ok": True, "result": result})

    def _notes_listing(self) -> dict[str, Any]:
        """The notes list with the quota worked out: `limit` and `used` characters (notes and
        skills together), `chars_left`. Without a notebook: `{"files": []}`."""
        try:
            listing = dict(self.notes.list())
        except CommandError:
            return {"files": [], "chars_left": 0}
        quota = listing.get("quota", {}).get("notes")  # the harness workspace says it
        limit = quota["limit"] if quota else listing.get("max_chars")
        if limit is not None:
            listing["limit"] = limit
            listing["used"] = limit - listing["chars_left"]
        return listing

    # -- static files -----------------------------------------------------------------------------

    def _static(self, rel: str) -> Response:
        """A file of the web client. Never `web/tests/` (the name is compared in lower case:
        the file system of a Mac ignores case), never a dotfile, never a link out of `web/`,
        and only the kinds of file in `MIME`."""
        missing = error_response(404, "not_found", "No such file.")
        parts = [p for p in rel.split("/") if p] or ["index.html"]
        if any(p.startswith(".") or p.lower() in HIDDEN_DIRS for p in parts):
            return missing
        try:
            file = self.web_root.joinpath(*parts).resolve()
            inside = file.relative_to(self.web_root).parts  # the real place, links followed
            if not file.is_file() or inside[0].lower() in HIDDEN_DIRS:
                return missing
            mime = MIME.get(file.suffix.lower())
            return (
                missing
                if mime is None
                else Response(200, {"Content-Type": mime}, file.read_bytes())
            )
        except (OSError, ValueError):  # a link out of web/, a NUL byte, a name that is too long
            return missing

    def _materials_response(self) -> Response:
        """`materials.json` as the page needs it: the colour of each index and nothing else. No
        key, name, kind or number of any sort: the page learns a name only through the view's
        legend (what an agent's ASCII legend would name) and through `inspect`. The format tag and
        the `color` field are those of the file, so the page reads it with the usual parser."""
        if self._materials is None:
            doc = json.loads((self.content_dir / "materials.json").read_text(encoding="utf-8"))
            slim = {
                "format": doc["format"],
                "materials": [{"index": m["index"], "color": m["color"]} for m in doc["materials"]],
            }
            self._materials = json.dumps(slim, separators=(",", ":"), ensure_ascii=False).encode()
        return Response(200, {"Content-Type": MIME[".json"]}, self._materials)


# -- helpers -------------------------------------------------------------------------------------


class _BadField(ValueError):
    pass


def _text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str):
        raise _BadField(f"`{name}` must be text")
    return value


def _json_object(body: bytes) -> tuple[dict[str, Any], Response | None]:
    try:
        data = json.loads(body.decode("utf-8") or "null")
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return {}, error_response(400, "bad_json", "The body is not valid JSON.")
    if not isinstance(data, dict):
        return {}, error_response(400, "bad_json", "The body must be a JSON object.")
    return data, None


def _all_ok(answer: Mapping[str, Any]) -> bool:
    return all(r["ok"] for r in answer["results"])


def _secured(response: Response) -> Response:
    return Response(response.status, {**SECURITY_HEADERS, **response.headers}, response.body)


def _command_info(spec: Any) -> dict[str, Any]:
    return {
        "name": spec.name,
        "summary": spec.summary,
        "timing": spec.timing,
        "arguments": [
            {
                "name": p.name,
                "kind": p.kind,
                "doc": p.doc,
                "required": p.required,
                "choices": list(p.choices),
            }
            for p in spec.params
        ],
    }
