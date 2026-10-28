"""Games of a family folder: which run folders belong together, and what makes two games alike.

A family is the output of `harness run --runs N --out runs/<name>`: a folder holding `run-01/`,
`run-02/`, ... (the games, in order) and `family.json`. Game 1 is the lowest `run-NN`. Two games
are comparable (cross-game growth, a control family) only if they share the model and the rule
seed; a control family must also share the world seed of each game.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .recording import RunData

_RUN_DIR = re.compile(r"^run-(\d+)$")


def run_number(path: Path) -> int | None:
    """`N` for a folder named `run-N`/`run-NN`, else None."""
    m = _RUN_DIR.match(path.name)
    return int(m.group(1)) if m else None


def family_runs(folder: Path) -> list[tuple[int, Path]]:
    """The `(number, folder)` of every `run-NN` directory in `folder`, lowest number first."""
    if not folder.is_dir():
        return []
    found = [(n, p) for p in folder.iterdir() if p.is_dir() and (n := run_number(p)) is not None]
    return sorted(found)


def is_family_folder(path: Path) -> bool:
    """A folder of games (not itself a recording): no `meta.json`, at least one `run-NN`."""
    return path.is_dir() and not (path / "meta.json").exists() and bool(family_runs(path))


def first_game(run_dir: Path) -> Path | None:
    """The lowest `run-NN` next to `run_dir` (which may itself be it); None if `run_dir` is not a
    `run-NN` folder or has no such siblings."""
    if run_number(run_dir) is None:
        return None
    runs = family_runs(run_dir.parent)
    return runs[0][1] if runs else None


def model_of(run: RunData) -> tuple[str, str] | None:
    """`(provider, model)` from `summary.json`; None for a run without one (human, scripted)."""
    model = (run.summary or {}).get("model")
    if not isinstance(model, dict) or not (model.get("provider") or model.get("model")):
        return None
    return str(model.get("provider")), str(model.get("model"))


def rule_seed_of(run: RunData) -> int | None:
    """The rule seed of the game: `meta.json`, else the world file."""
    for value in (run.meta.get("rule_seed"), run.world.rule_seed):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def model_text(model: tuple[str, str] | None) -> str:
    return "no model" if model is None else f"{model[0]}/{model[1]}"


def model_dict(model: tuple[str, str] | None) -> dict[str, Any] | None:
    return None if model is None else {"provider": model[0], "model": model[1]}
