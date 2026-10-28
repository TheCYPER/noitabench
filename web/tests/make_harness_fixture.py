"""Cuts the small harness-run fixtures for the replay tests out of real runs.

    .venv/bin/python web/tests/make_harness_fixture.py [runs/cp3-haiku-42] [runs/cp3-human-42]

Writes web/tests/fixtures/harness_run/ (decisions, transcript, harness log and summary of a
Claude Haiku game: a few turns from the start including a 35-step Code Mode program, the
briefing and the death) and web/tests/fixtures/human_run/decisions.jsonl (a few decisions of a
human game: no transcript). Records are copied unchanged, except that harness.jsonl loses its
request ids and summary.json gets recognisable made-up seeds (so that a test can check that no page
shows them) and no key variable name.

The fixtures are committed; this script only documents where they came from.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures"
HAIKU = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1] / "runs" / "cp3-haiku-42"
HUMAN = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE.parents[1] / "runs" / "cp3-human-42"

DECISIONS = set(range(1, 41)) | set(range(166, 177)) | {233, 234, 235}
SEQS = set(range(1, 13)) | set(range(75, 90)) | set(range(106, 115))
CALLS = set(range(1, 7)) | set(range(31, 38)) | {45, 46, 47}


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def dump(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def main():
    d = OUT / "harness_run"
    dump(d / "decisions.jsonl", [r for r in lines(HAIKU / "decisions.jsonl") if r["index"] in DECISIONS])
    dump(d / "transcript.jsonl", [r for r in lines(HAIKU / "transcript.jsonl") if r["seq"] in SEQS])
    calls = [r for r in lines(HAIKU / "harness.jsonl") if r["call"] in CALLS]
    dump(d / "harness.jsonl", [{**r, "request_id": "req_fixture"} for r in calls])
    summary = json.loads((HAIKU / "summary.json").read_text(encoding="utf-8"))
    summary["world_seed"] = 424242
    summary["rule_seed"] = 717171
    summary["model"]["api_key_env"] = None
    (d / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    h = OUT / "human_run"
    dump(h / "decisions.jsonl", [r for r in lines(HUMAN / "decisions.jsonl") if r["index"] <= 12 or r["index"] in (461, 462)])


if __name__ == "__main__":
    main()
