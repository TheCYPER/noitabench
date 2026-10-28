"""Build `crates/game/tests/data/wand_fixtures.json`: the casting fixtures that only use in-scope
spells, with the wrong expectations of the research file corrected (DN-WAND-09).

The research file `wand-cast-test-cases.json` has 32 fixtures for the full Noita spell set. The
wand engine of the game only has the 25 spells of `content/spells.json`, so a fixture is kept when
every spell id it mentions (slots, always-casts, forced permutation) is one of them. The others are
listed under `excluded` with the missing spells, so nobody wonders where they went.

    python -m noitabench.content_tools.build_wand_fixtures            # write the file
    python -m noitabench.content_tools.build_wand_fixtures --check    # fail if out of date
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from noitabench.content_tools.build_spells import DEFAULT_OUT as SPELLS_FILE
from noitabench.content_tools.build_spells import REPO, RESEARCH

SOURCE = RESEARCH / "wand-cast-test-cases.json"
DEFAULT_OUT = REPO / "crates" / "game" / "tests" / "data" / "wand_fixtures.json"

# Expected values of the research file that are wrong (wand-casting.md "Verification"):
# (fixture id, click index, key, wrong value, right value). The asserts keep this honest: if the
# research file is fixed, the build fails and this table must be updated.
CORRECTIONS: tuple[tuple[str, int, str, Any, Any], ...] = (
    # BURST_2 is free: DAMAGE 5 + 2 x LIGHT_BULLET 5 = 15, not 10.
    ("draw_01_multicast_modifier", 0, "mana_spent", 10, 15),
    # Three TAUs are 3 x 35 plus three LIGHT_BULLETs at 3 each = 114, not 105.
    ("greek_01_tau_recursion", 0, "fire_rate_wait_frames", 105, 114),
)
# Replaced by the corrected 2-click vector KV-01 (needs RESET, so it is out of scope anyway).
DROPPED = {"refresh_03_spells_per_cast_forces_wrap"}


def _spell_ids(case: dict[str, Any]) -> set[str]:
    ids = set(case.get("slots", ())) | set(case.get("forced_permutation", ()))
    ids |= set(case.get("wand", {}).get("always_casts", ()))
    for variant in case.get("variants", ()):
        ids |= set(variant.get("slots", ()))
    return ids


def _correct(case: dict[str, Any]) -> dict[str, Any]:
    fixed = copy.deepcopy(case)
    notes = []
    for case_id, click, key, wrong, right in CORRECTIONS:
        if case_id != case["id"]:
            continue
        if fixed["clicks"][click][key] != wrong:
            raise ValueError(f"{case_id}: expected {key} = {wrong} in the research file")
        fixed["clicks"][click][key] = right
        notes.append(f"{key}: {wrong} -> {right} (DN-WAND-09)")
    if notes:
        fixed["corrected"] = notes
    return fixed


def build() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    known = {spell["key"] for spell in json.loads(SPELLS_FILE.read_text("utf-8"))["spells"]}
    cases, excluded = [], {}
    for case in source["cases"]:
        missing = sorted(_spell_ids(case) - known)
        if case["id"] in DROPPED:
            excluded[case["id"]] = ["(replaced by KV-01)", *missing]
        elif missing:
            excluded[case["id"]] = missing
        else:
            cases.append(_correct(case))
    return {
        "format": "cogbench-wand-fixtures/0",
        "source": "research/wand-cast-test-cases.json, filtered to the 25 in-scope spells",
        "default_wand": source["_meta"]["default_wand"],
        "cases": cases,
        "excluded": excluded,
    }


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m noitabench.content_tools.build_wand_fixtures")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="only compare with the existing file")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is out of date; re-run without --check", file=sys.stderr)
            return 1
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    document = json.loads(text)
    print(
        f"wrote {args.out}: {len(document['cases'])} fixtures, {len(document['excluded'])} excluded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
