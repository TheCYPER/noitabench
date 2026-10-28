"""`python -m noitabench knowledge`: print or write the knowledge base.

    python -m noitabench knowledge --doc docs/knowledge-base.md        the readable document
    python -m noitabench knowledge --seed N [--json]                   one rule seed's recipes
                                                                       (or the whole base as JSON)

The recipes are an answer key: they are printed only on request, for researchers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .doc import recipe_lines, render_document
from .facts import build_knowledge


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m noitabench knowledge",
        description="Print the knowledge base that the agents' notes are judged against.",
    )
    parser.add_argument(
        "--doc", metavar="FILE", help="write the readable document, in English (no recipes)"
    )
    parser.add_argument("--seed", type=int, help="the rule seed whose recipes to print")
    parser.add_argument(
        "--json", action="store_true", help="print the whole base of --seed as JSON"
    )
    args = parser.parse_args(argv)
    if args.doc is None and args.seed is None:
        parser.error("give --doc FILE, --seed N, or both")
    if args.json and args.seed is None:
        parser.error("--json needs --seed")
    if args.doc is not None:
        path = Path(args.doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_document(), encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)
    if args.seed is not None:
        if args.json:
            print(json.dumps(build_knowledge(args.seed).as_dict(), ensure_ascii=False, indent=2))
        else:
            print("\n".join(recipe_lines(args.seed)))
    return 0
