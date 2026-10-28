"""`python -m noitabench notes-claims`: extract the claims of the notebooks of finished runs.

    python -m noitabench notes-claims <run dir | family dir> [...] [--provider anthropic]
        [--model claude-haiku-5-5] [--api-key-env NOITABENCH_ANTHROPIC_KEY] [--max-usd 0.25]
        [--claims-from FILE] [--force]

writes `<run>/notes_claims.json` for each run (see `extract.py`). A family folder is a folder of
`run-NN` runs. Only this command ever calls a model; the evaluator reads the file it writes. The
key is read from the environment variable named by `--api-key-env` and never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..games import run_number
from .extract import ExtractionAborted, Extractor, FromFile, extract_run

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_KEY_VARIABLE = "NOITABENCH_ANTHROPIC_KEY"
DEFAULT_MAX_USD = 0.25


def find_runs(path: Path) -> list[Path]:
    """The run folders at `path`: itself if it holds `meta.json`, else its `run-NN` folders."""
    if (path / "meta.json").exists():
        return [path]
    if not path.is_dir():
        return []
    return sorted(
        p
        for p in path.iterdir()
        if p.is_dir() and run_number(p) is not None and (p / "meta.json").exists()
    )


def model_config(provider: str, model: str, api_key_env: str | None = None) -> Any:
    """How the extractor talks to its model: no thinking where the model allows it (it only
    reads), a short answer, the key from the variable named (`NOITABENCH_ANTHROPIC_KEY` for
    Anthropic when none is named)."""
    from noitabench.harness.model import ModelConfig

    key_env = api_key_env or (DEFAULT_KEY_VARIABLE if provider == "anthropic" else None)
    return ModelConfig(
        provider,
        model,
        api_key_env=key_env,
        max_output_tokens=4096,
        thinking="off" if "haiku" in model or provider == "deepseek" else "adaptive",
    )


def _model_extractor(args: argparse.Namespace) -> Extractor:
    from noitabench.harness.adapters import make_adapter
    from noitabench.harness.prices import resolve_price

    config = model_config(args.provider, args.model, args.api_key_env)
    return Extractor(make_adapter(config), resolve_price(args.model), args.max_usd)


def _from_file(path: str) -> FromFile:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise TypeError(f"{path}: must be an object {{note path: [claims]}}")
    return FromFile({str(k): list(v) for k, v in doc.items()}, Path(path).name)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m noitabench notes-claims",
        description="Read the notes of finished runs and write the claims they make (the only step that calls a model).",
    )
    parser.add_argument("paths", nargs="+", help="run folders, or family folders of run-NN folders")
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--api-key-env",
        help=f"environment variable holding the key (default {DEFAULT_KEY_VARIABLE})",
    )
    parser.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="stop spending here")
    parser.add_argument(
        "--claims-from", metavar="FILE", help="take claims from a file, call no model"
    )
    parser.add_argument("--force", action="store_true", help="extract again whatever is cached")
    args = parser.parse_args(argv)
    runs = [r for p in args.paths for r in find_runs(Path(p))]
    if not runs:
        print("notes-claims: no run folder found", file=sys.stderr)
        return 2
    try:
        extractor = _from_file(args.claims_from) if args.claims_from else _model_extractor(args)
    except (OSError, ValueError, TypeError) as err:
        print(f"notes-claims: {err}", file=sys.stderr)
        return 2
    except Exception as err:  # noqa: BLE001 - a ConfigError names what to fix, never a key
        print(f"notes-claims: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    try:
        for run in runs:
            doc = extract_run(run, extractor, force=args.force)
            if doc is None:
                print(f"{run}: no workspace folder, nothing to extract")
                continue
            files = [*(doc.start or {}).values(), *doc.end.values()]
            made = sum(len(f.claims) for f in files)
            lost = sum(len(f.dropped) for f in files)
            print(
                f"{run}: {len(files)} file(s), {made} claim(s), {lost} dropped, "
                f"{doc.calls} call(s), ${doc.cost_usd:.4f}"
                + (f", {len(doc.skipped)} NOT extracted" if doc.skipped else "")
            )
    except ExtractionAborted as err:
        print(f"notes-claims: stopped: {err}", file=sys.stderr)
        return 2
    return 0
