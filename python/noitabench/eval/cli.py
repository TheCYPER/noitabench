"""`python -m noitabench eval <run_dir | family_dir> [--out FILE] [--control FAMILY_DIR]`.

A run folder gives its `profile.json`. A family folder (`run-NN` folders from `harness run --runs N`)
evaluates every game and writes `family_profile.json` next to them (`family.py`); `--control`
pairs it with a control family (the workspace emptied each game) for the memory effect.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .family import (
    ControlMismatch,
    add_control,
    build_family_profile,
    format_family,
    write_family_profile,
)
from .games import is_family_folder
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


def _family_main(args: argparse.Namespace, folder: Path) -> int:
    if args.world_files:
        print("eval: --world-files is for a single run folder", file=sys.stderr)
        return 2
    try:
        profile = build_family_profile(folder)
        if args.control:
            control_dir = Path(args.control)
            if not is_family_folder(control_dir):
                raise ControlMismatch(f"{control_dir}: not a family folder (no run-NN folders)")
            profile = add_control(profile, build_family_profile(control_dir))
        out = write_family_profile(profile, args.out or folder / "family_profile.json")
    except (OSError, ValueError) as err:  # ControlMismatch is a ValueError
        print(f"eval: {err}", file=sys.stderr)
        return 2
    for game in profile["games"]:
        if "error" in game:
            print(f"eval: {game['run']}: {game['error']}", file=sys.stderr)
    if all("error" in g for g in profile["games"]):
        print("eval: none of the games could be evaluated", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(format_family(profile))
        print(f"wrote {out}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m noitabench eval",
        description=(
            "Evaluate a finished run folder and write its profile.json; or a family folder "
            "(run-01, run-02, ...) and write each game's profile.json and family_profile.json."
        ),
    )
    parser.add_argument("run_dir", help="run folder (runs/<id>/ or <id>/run-NN/) or family folder")
    parser.add_argument(
        "--out",
        help=(
            "where to write profile.json (default: <run_dir>/profile.json); for a family folder, "
            "family_profile.json (default: <run_dir>/family_profile.json)"
        ),
    )
    parser.add_argument(
        "--world-files",
        nargs=2,
        metavar=("PNG", "JSON"),
        help="the world file pair, if it is not in <run_dir>/world/",
    )
    parser.add_argument(
        "--control",
        metavar="FAMILY_DIR",
        help=(
            "family folder only: a control family (same model, rule seed and world seeds, "
            "workspace emptied each game); adds the memory effect, display only"
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="do not print the summary")
    parser.add_argument("--json", action="store_true", help="print the whole profile as JSON")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)
    if is_family_folder(run_dir):
        return _family_main(args, run_dir)
    if args.control:
        print("eval: --control needs a family folder (run-NN folders)", file=sys.stderr)
        return 2
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
