"""`python -m noitabench <command>`.

Commands owned by this module: `demo`. Others live in their own packages and are loaded on
demand: `world` -> `noitabench.worldgen.cli`, `serve` -> `noitabench.server.cli`,
`agent` -> `noitabench.agent.cli`, `play` -> `noitabench.play.cli`,
`harness` -> `noitabench.harness.cli`, `eval` -> `noitabench.eval.cli`,
`knowledge` and `notes-claims` -> `noitabench.eval.knowledge.{cli,claims_cli}`; each exposes
`main(argv: list[str]) -> int`.
"""

from __future__ import annotations

import argparse
import importlib
import sys

PLUGINS = {
    "world": "noitabench.worldgen.cli",
    "serve": "noitabench.server.cli",
    "agent": "noitabench.agent.cli",
    "play": "noitabench.play.cli",
    "harness": "noitabench.harness.cli",
    "eval": "noitabench.eval.cli",
    "knowledge": "noitabench.eval.knowledge.cli",
    "notes-claims": "noitabench.eval.knowledge.claims_cli",
}


def _demo(argv: list[str]) -> int:
    from noitabench.demo import game as game_demo
    from noitabench.demo import materials as materials_demo

    sets = {"materials": materials_demo, "game": game_demo}
    parser = argparse.ArgumentParser(prog="python -m noitabench demo")
    parser.add_argument("what", choices=sorted(sets), help="which demo set to record")
    parser.add_argument("--out", default="runs", help="directory for runs/demo-* (default: runs)")
    parser.add_argument("--seed", type=int, default=1, help="simulation seed (default: 1)")
    parser.add_argument("--only", action="append", help="record only this scene (repeatable)")
    args = parser.parse_args(argv)
    demo = sets[args.what]
    unknown = [n for n in args.only or [] if n not in demo.SCENES]
    if unknown:
        parser.error(f"unknown scene(s) {unknown}; choose from {sorted(demo.SCENES)}")
    for summary in demo.run_all(args.out, args.seed, args.only):
        print(
            f"{summary['dir']}: {summary['frames']} frames, "
            f"{summary['events']} events, final frame {summary['last_frame']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    commands = ["demo", *PLUGINS]
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: python -m noitabench {" + ",".join(commands) + "} ...")
        return 0 if argv else 2
    command, rest = argv[0], argv[1:]
    if command == "demo":
        return _demo(rest)
    if command in PLUGINS:
        try:
            module = importlib.import_module(PLUGINS[command])
        except ModuleNotFoundError as exc:
            if exc.name and PLUGINS[command].startswith(exc.name):
                print(
                    f"`{command}` is not available yet: {PLUGINS[command]} is missing",
                    file=sys.stderr,
                )
                return 2
            raise
        return int(module.main(rest) or 0)
    print(f"unknown command `{command}`; expected one of: {', '.join(commands)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
