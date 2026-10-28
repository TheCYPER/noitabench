"""Make a recording you can open in the web viewer.

    .venv/bin/python examples/try_it.py scene            # a small hand-made scene
    .venv/bin/python examples/try_it.py world --seed 7   # a generated world, left to settle

Each run prints the replay link. The web server must be running from the repo root:
    .venv/bin/python -m http.server 8000
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import noitabench_core as nc

VIEWER = "http://127.0.0.1:8000/web"


def find_material(env: "nc.Env", key: str, x_range: range) -> tuple[int, int] | None:
    """Top-most cell of a material in the given columns, or None."""
    for y in range(env.height):
        for x in x_range:
            if env.cell(x, y)["material"] == key:
                return x, y
    return None


def scene(args: argparse.Namespace) -> Path:
    env = nc.Env(256, 192, args.seed)
    # rock floor and two walls make a basin
    env.fill_rect(0, 170, 256, 22, "rock")
    env.fill_rect(0, 60, 10, 110, "rock")
    env.fill_rect(246, 60, 10, 110, "rock")
    # a wooden shelf holding a pile of sand
    env.fill_rect(30, 100, 70, 4, "wood")
    env.paint(60, 90, 10, "sand")
    # water on the right, oil poured on top of it
    env.fill_rect(150, 130, 90, 40, "water")
    env.paint(190, 110, 12, "oil")
    # a blob of lava dropped in the middle
    env.paint(128, 40, 8, "lava")

    out = ROOT / "runs" / f"scene-{args.seed}"
    env.start_recording(str(out), 2, run_id=out.name, notes="examples/try_it.py scene")
    env.step_frames(120)
    oil = find_material(env, "oil", x_range=range(150, 240))
    if oil:
        env.ignite(*oil)  # light the oil after two seconds
    env.step_frames(120)
    env.explode(60, 110, 14, 200_000, 10)  # blow up the shelf
    env.step_frames(360)
    env.stop_recording()
    return out


def world(args: argparse.Namespace) -> Path:
    src = ROOT / "runs" / f"world-{args.seed}"
    png, js = src / f"world_{args.seed}.png", src / f"world_{args.seed}.json"
    if not png.exists():
        sys.exit(
            f"no world for seed {args.seed}; generate it first:\n"
            f"  PYTHONPATH=python .venv/bin/python -m noitabench world generate "
            f"--seed {args.seed} --out runs/world-{args.seed}"
        )
    env = nc.Env.from_world(str(png), str(js))
    out = ROOT / "runs" / f"world-{args.seed}-run"
    env.start_recording(str(out), 4, run_id=out.name, notes="examples/try_it.py world")
    env.step_frames(args.frames)
    env.stop_recording()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scene", help="record a small hand-made scene")
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(run=scene)
    p = sub.add_parser("world", help="load a generated world and record it settling")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--frames", type=int, default=600)
    p.set_defaults(run=world)
    args = parser.parse_args()
    out = args.run(args)
    print(f"recorded {out.relative_to(ROOT)}")
    print(f"open {VIEWER}/replay.html?src=../{out.relative_to(ROOT).as_posix()}/")


if __name__ == "__main__":
    main()
