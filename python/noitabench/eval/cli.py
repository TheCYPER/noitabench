"""`python -m noitabench eval <run_dir> [--out profile.json]`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .profile import evaluate_run, write_profile
from .worldinfo import WorldFilesNotFound


def _summary(profile: dict) -> str:
    head = (
        f"{profile['run_id']} ({profile['source']}): composite {profile['composite']:.1f}, "
        f"depth {profile['depth']['score']:.1f}, ability {profile['ability_mean']:.1f}"
    )
    lines = [head]
    for name, cap in profile["capabilities"].items():
        score = "-" if cap["score"] is None else f"{cap['score']:.1f}"
        flag = "" if cap["covered"] else "  (coverage too low)"
        lines.append(
            f"  {name:>3}: {score:>6}  opportunities {cap['opportunities']:>2}"
            f"  counts {cap['discounted_score']:>5.1f}{flag}"
        )
    for enc in profile["encounters"]:
        for v in enc["visits"]:
            score = "unscored" if v["score"] is None else f"{v['score']:.2f}"
            lines.append(f"  {v['instance']:<14} {score}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m noitabench eval",
        description="Evaluate a finished run folder and write its profile.json.",
    )
    parser.add_argument("run_dir", help="run folder (runs/<id>/ or <id>/run-NN/)")
    parser.add_argument(
        "--out", help="where to write profile.json (default: <run_dir>/profile.json)"
    )
    parser.add_argument(
        "--world-files",
        nargs=2,
        metavar=("PNG", "JSON"),
        help="the world file pair, if it is not in <run_dir>/world/",
    )
    parser.add_argument("--quiet", action="store_true", help="do not print the summary")
    parser.add_argument("--json", action="store_true", help="print the whole profile as JSON")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)
    try:
        profile = evaluate_run(run_dir, tuple(args.world_files) if args.world_files else None)
        out = write_profile(profile, args.out or run_dir / "profile.json")
    except (FileNotFoundError, WorldFilesNotFound, ValueError) as err:
        print(f"eval: {err}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(_summary(profile))
        print(f"wrote {out}")
    return 0
