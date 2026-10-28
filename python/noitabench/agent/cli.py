"""`python -m noitabench agent play ...`: one episode over JSON Lines on stdin and stdout.

    python -m noitabench agent play --world-seed 42 --rule-seed 7 --out runs/agent-42

Generates the world of the seed (or loads `--world-files PNG JSON`), starts a session and serves
the protocol of `protocol.py`: the first line written is the `hello` line with the first
observation; then each line read is a decision and each line written its answer. With `--out`
the game is recorded there and `decisions.jsonl` is written next to the recording. Diagnostics
go to stderr, never to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from noitabench.game import Game

from .observe import ViewConfig
from .protocol import serve
from .session import AgentSession, SessionConfig
from .vocab import DEFAULT_MAX_DECISIONS


def open_game(
    png: Path | str,
    world_json: Path | str,
    *,
    game_seed: int | None = None,
    rule_seed: int | None = None,
) -> Game:
    """A game on a world file pair. Every world runs the original reaction table; the rule seed
    (default: the one in the world file, or 0) only decides the secret recipes."""
    doc: dict[str, Any] = json.loads(Path(world_json).read_text(encoding="utf-8"))
    rules = int(doc.get("rule_seed", 0)) if rule_seed is None else rule_seed
    return Game.from_world(png, world_json, game_seed, rule_seed=rules)


def build_world(world_seed: int, rule_seed: int, out_dir: Path) -> tuple[Path, Path]:
    """Generate the world of `world_seed` into `out_dir`; returns the file pair."""
    from noitabench.worldgen import generate_world
    from noitabench.worldgen.config import load_materials

    world = generate_world(world_seed, rule_seed)
    return world.write(out_dir, f"world_{world_seed}", load_materials())


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="noitabench agent", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    play = sub.add_parser("play", help="serve one episode over JSON Lines (stdin, stdout)")
    play.add_argument("--world-seed", type=int, help="seed of the world to generate")
    play.add_argument(
        "--rule-seed", type=int, default=None, help="rule seed (default: the world's, or 0)"
    )
    play.add_argument("--world-files", nargs=2, metavar=("PNG", "JSON"), help="a world file pair")
    play.add_argument("--game-seed", type=int, default=None, help="seed of the simulation")
    play.add_argument("--out", default=None, help="recording directory (default: none)")
    play.add_argument("--max-decisions", type=int, default=DEFAULT_MAX_DECISIONS)
    play.add_argument("--stride", type=int, default=12, help="recording: frames per full frame")
    play.add_argument("--no-text", action="store_true", help="switch the state channel off")
    play.add_argument("--no-ascii", action="store_true", help="switch the ASCII map off")
    play.add_argument("--screenshot", action="store_true", help="switch the screenshot on")
    play.add_argument("--shot-scale", type=int, default=1, help="screenshot magnification")
    return p


def cmd_play(args: argparse.Namespace) -> int:
    if (args.world_seed is None) == (args.world_files is None):
        raise SystemExit("give exactly one of --world-seed and --world-files")
    out = Path(args.out) if args.out else None
    if args.world_files:
        png, js = Path(args.world_files[0]), Path(args.world_files[1])
    else:
        folder = (out / "world") if out else Path(tempfile.mkdtemp(prefix="cogbench-world-"))
        png, js = build_world(args.world_seed, args.rule_seed or 0, folder)
        print(f"world written to {folder}", file=sys.stderr)
    game = open_game(png, js, game_seed=args.game_seed, rule_seed=args.rule_seed)
    view = ViewConfig(
        text=not args.no_text,
        ascii=not args.no_ascii,
        screenshot=args.screenshot,
        shot_scale=args.shot_scale,
    )
    config = SessionConfig(max_decisions=args.max_decisions, view=view, frame_stride=args.stride)
    session = AgentSession(game, config=config, recording_dir=out)
    summary = serve(session, sys.stdin, sys.stdout)
    print(f"episode finished: {json.dumps(summary)}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    return cmd_play(args)
