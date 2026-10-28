"""`python -m noitabench play serve ...`: a human plays one episode in the browser.

    python -m noitabench play serve --world-seed 3 --rule-seed 7 --out runs/play-3

Generates the world of the seed (or loads `--world-files PNG JSON`), starts an `AgentSession`
on it and serves the play page at http://127.0.0.1:8765/ (this machine only). With `--out` the
game is recorded there, `decisions.jsonl` included, in the format an agent's episode has. The
generated world files (they carry the level's tooling fields) go to a sibling folder,
`<out>-world/`, never into the recording and never under `web/`, the only folder the server
serves.
Notes are kept in the harness workspace `workspaces/<family>/` (`--family`, default
`human-<rule seed>`): the same folder and the same 8,000-character quota as an agent's notebook,
and they stay for the next episode.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any

from noitabench.agent.cli import build_world, open_game
from noitabench.agent.content import REPO
from noitabench.agent.observe import ViewConfig
from noitabench.agent.session import AgentSession, SessionConfig
from noitabench.agent.vocab import DEFAULT_MAX_DECISIONS
from noitabench.harness.workspace import FAMILY, Workspace

from .app import WEB_ROOT, PlayApp
from .server import HOST, make_server

DEFAULT_PORT = 8765


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="noitabench play", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="serve the play page and the game behind it")
    serve.add_argument("--world-seed", type=int, help="seed of the world to generate")
    serve.add_argument("--rule-seed", type=int, default=None, help="rule seed (default: 0)")
    serve.add_argument("--world-files", nargs=2, metavar=("PNG", "JSON"), help="a world file pair")
    serve.add_argument("--game-seed", type=int, default=None, help="seed of the simulation")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default 8765)")
    serve.add_argument("--out", default=None, help="recording directory (default runs/play-<seed>)")
    serve.add_argument("--no-record", action="store_true", help="do not record the episode")
    serve.add_argument("--family", default=None, help="notes folder name (default human-<rule>)")
    serve.add_argument("--workspace-root", default=str(REPO / "workspaces"))
    serve.add_argument("--max-decisions", type=int, default=DEFAULT_MAX_DECISIONS)
    serve.add_argument("--stride", type=int, default=12, help="recording: frames per full frame")
    serve.add_argument("--ascii", action="store_true", help="also send the agents' ASCII map")
    serve.add_argument("--exit-on-close", action="store_true", help="stop serving after 'End'")
    return p


def _recording_dir(args: argparse.Namespace) -> Path | None:
    if args.no_record:
        return None
    if args.out:
        return Path(args.out)
    tag = args.world_seed if args.world_seed is not None else "files"
    n = 0
    while Path("runs", f"play-{tag}" + (f"-{n}" if n else "")).exists():
        n += 1
    return Path("runs", f"play-{tag}" + (f"-{n}" if n else ""))


def world_folder(out: Path) -> Path:
    """Where the generated world of a recording goes: `runs/play-3` -> `runs/play-3-world`."""
    out = out.resolve()
    return out.parent / f"{out.name}-world"


def _inside_web(path: Path) -> bool:
    """Is `path` (which need not exist yet) `web/` or something under it? Asked of the file
    system, not of the spelling: a Mac ignores case, so `WEB/runs` is `web/runs`."""
    where = path.resolve()
    web = WEB_ROOT.resolve()
    return any(p.exists() and p.samefile(web) for p in (where, *where.parents))


def _check_not_served(path: Path, what: str) -> None:
    """The server serves `web/` and nothing else; a folder under it would be public."""
    if _inside_web(path):
        raise SystemExit(f"{what} {str(path)!r} is inside web/, which the play server serves")


def build_app(args: argparse.Namespace, out: Path | None) -> PlayApp:
    """The app for the command-line arguments: world, game, session, notes."""
    if (args.world_seed is None) == (args.world_files is None):
        raise SystemExit("give exactly one of --world-seed and --world-files")
    if out is not None:
        _check_not_served(out, "the recording folder")
    rule_seed = args.rule_seed
    if args.world_files:
        png, js = Path(args.world_files[0]), Path(args.world_files[1])
        shown = json.loads(js.read_text(encoding="utf-8")).get("rule_seed", 0)
    else:
        folder = world_folder(out) if out else Path(tempfile.mkdtemp(prefix="cogbench-world-"))
        _check_not_served(folder, "the world folder")
        png, js = build_world(args.world_seed, rule_seed or 0, folder)
        print(f"world written to {folder}", file=sys.stderr)
        shown = rule_seed or 0
    family = args.family or f"human-{shown}"
    if not FAMILY.match(family):
        raise SystemExit(f"--family {family!r}: use letters, digits, '_', '-' and '.' only")
    game = open_game(png, js, game_seed=args.game_seed, rule_seed=rule_seed)
    # The page shows the picture, so the agents' ASCII map is off unless asked for.
    view = ViewConfig(text=True, ascii=args.ascii, screenshot=False)
    config = SessionConfig(max_decisions=args.max_decisions, view=view, frame_stride=args.stride)
    notes = Workspace(Path(args.workspace_root) / family)
    session = AgentSession(
        game, config=config, memory=notes, recording_dir=out, notes="human play (noitabench.play)"
    )
    return PlayApp(session, game, notes)


def _interrupt(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt  # `kill` ends an episode the way Ctrl-C does: recording closed


def cmd_serve(args: argparse.Namespace) -> int:
    out = _recording_dir(args)
    app = build_app(args, out)
    try:
        server = make_server(app, args.port)
    except OSError as err:
        app.close()
        raise SystemExit(
            f"cannot listen on {HOST}:{args.port} ({err.strerror}); try --port 0"
        ) from err
    if args.exit_on_close:
        app.on_close = lambda _summary: _stop_soon(server)
    signal.signal(signal.SIGTERM, _interrupt)
    url = f"http://{HOST}:{server.server_port}/"
    print(f"play at {url}  (Ctrl-C to stop)", flush=True)
    if out:
        print(f"recording to {out}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping", file=sys.stderr)
    finally:
        server.server_close()
        summary = app.close()
        print(f"episode finished: {json.dumps(summary)}", file=sys.stderr)
    return 0


def _stop_soon(server: Any) -> None:
    import threading

    threading.Thread(target=server.shutdown, daemon=True).start()


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    return cmd_serve(args)
