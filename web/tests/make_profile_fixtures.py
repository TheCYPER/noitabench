"""Cuts the profile fixtures of the report tests out of real runs.

    .venv/bin/python web/tests/make_profile_fixtures.py [runs/descend-42] [runs/cp3-haiku-42] [runs/cp3-human-42]

Evaluates the three runs with the current evaluator (`noitabench.eval.evaluate_run`) and writes
web/tests/fixtures/profiles/{bot,agent,human}.profile.json: the profiles unchanged, except that

- the world and rule seeds and the world file name are replaced by recognisable made-up values
  (424242, 717171, world_424242.json), so a test can check that no page shows them;
- the run name (which carries the seed) becomes fx-bot, fx-agent, fx-human;

The fixtures are committed; this script only documents where they came from.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "python"))

from noitabench.eval import evaluate_run  # noqa: E402

RUNS = [Path(a) for a in sys.argv[1:4]] or [
    ROOT / "runs" / "descend-42",
    ROOT / "runs" / "cp3-haiku-42",
    ROOT / "runs" / "cp3-human-42",
]
NAMES = ["bot", "agent", "human"]


def main() -> None:
    out = HERE / "fixtures" / "profiles"
    out.mkdir(parents=True, exist_ok=True)
    for name, run in zip(NAMES, RUNS):
        profile = evaluate_run(run)
        profile["world"] = {"seed": 424242, "rule_seed": 717171, "file": "world_424242.json"}
        profile["run_id"] = profile["run_dir"] = f"fx-{name}"
        path = out / f"{name}.profile.json"
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
