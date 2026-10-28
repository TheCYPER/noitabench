"""`PlayApp` behind `http.server`: standard library only, bound to this machine.

The deviation from design.md section 8 ("WebSocket"): in pause mode the page asks, the game
answers once and then waits, so plain request and response says all there is to say. A
WebSocket is for the real-time mode (phase 2).
"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .app import MAX_BODY, PlayApp, error_response

HOST = "127.0.0.1"  # never a public address: the game has no login
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
SINGLE_HEADERS = ("host", "origin", "content-type", "content-length")  # a second copy: refused


def make_server(app: PlayApp, port: int = 8765, host: str = HOST) -> ThreadingHTTPServer:
    """A server for `app`; `port` 0 picks a free port (`server.server_port`). Only a loopback
    address is accepted for `host`."""
    if host not in LOOPBACK:
        raise ValueError(f"the play server listens on this machine only, not on {host!r}")

    class Handler(BaseHTTPRequestHandler):
        server_version = "cogbench-play"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._serve()

        def do_POST(self) -> None:
            self._serve()

        def do_PUT(self) -> None:
            self._serve()

        do_DELETE = do_PATCH = do_PUT

        def _refuse(self, status: int, code: str, message: str) -> None:
            """Answer and drop the connection: its unread bytes must not become a request."""
            self._send(error_response(status, code, message))
            self.close_connection = True

        def _unreadable(self) -> tuple[int, str, str] | None:
            """Why the request cannot be taken as it came, or `None`."""
            if any(len(self.headers.get_all(name) or []) > 1 for name in SINGLE_HEADERS):
                return 400, "bad_request", "A header was given twice."
            if self.headers.get("Transfer-Encoding") is not None:
                return 400, "bad_request", "Chunked bodies are not supported."
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return 413, "too_large", "The body is too large or unreadable."
            return None

        def _serve(self) -> None:
            problem = self._unreadable()
            if problem is not None:
                self._refuse(*problem)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            self._send(app.handle(self.command, self.path, headers, body))

        def _send(self, response: Any) -> None:
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, fmt: str, *args: Any) -> None:
            # `path` is not set yet when the request line itself was bad
            if "/api/state" not in getattr(self, "path", ""):  # the page asks it once at start
                print(f"{self.address_string()} {fmt % args}", file=sys.stderr)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    """Run `server` on a background thread (tests); stop it with `server.shutdown()`."""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread
