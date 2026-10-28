"""The human play server: the same `AgentSession` as an agent plays, behind a local web page.

    python -m noitabench play serve --world-seed 3

`app.PlayApp` is the whole server as one object (`handle(method, target, headers, body)` returns a
`Response`; no sockets), `server.py` puts it behind `http.server`, `cli.py` is the command line.
`view.py` builds the picture the page draws. The notebook of the player is the harness workspace
(`noitabench.harness.workspace.Workspace`): the same folder and quota an agent's notes use.
See `.trellis/spec/backend/contracts.md`, "Play server".
"""

from .app import PlayApp, Response

__all__ = ["PlayApp", "Response"]
