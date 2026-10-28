"""`family_profile.json`: a whole family folder evaluated (`cogbench-family-profile/0`).

    python -m noitabench eval runs/<family> [--control runs/<control family>]

Every `run-NN` is evaluated like a single run (its `profile.json` is written) and the family file
puts them side by side. For researchers: it carries what the `profile.json` files carry, nothing
else, and is never shown to an agent.

    {
      "format": "cogbench-family-profile/0",
      "family_dir": the folder's name, "evaluator": {"version"},
      "model": {"provider", "model"} | null, "rule_seed": int | null,    # of the first game read
      "games": [                                       # run-NN in order
        {"run", "index", "world_seed", "rule_seed", "model", "workspace_cleared",
         "composite", "ability_mean", "depth": 0..100, "hp_lost": whole game, "decisions" | null,
         "end": "dead" | "max_decisions" | ..., "cost_usd" | null,
         "growth": null for game 1 | {name: {"value", "status", "opportunities", "reason"}}}
        | {"run", "index", "error"}                   # a folder that could not be read
      ],
      "encounters": {"E02": {"run-01": mean score of its scored visits | null, ...}, ...},
      "growth": {"baseline": "run-01",
                 "mean": {name: {"value": mean over the later games where it was measured | null,
                                 "measured_games", "later_games"}}},
      "control": absent | {"family_dir", "workspace_cleared": bool, "scored": false, "note"?,
                           "paired_games": [indexes], "games": [...as above],
                           "memory_effect": {name: {"value": mean(family) - mean(control) over
                                                    the later games both measured | null,
                                                    "pairs", "family", "control"}}}
    }

`name` is one of `GROWTH_METRICS` (`metrics/growth.py`). The control family is the same model on
the same rule seed and world seeds with the workspace emptied before each game
(`harness run --clear-workspace`); `memory_effect` is display only and is never scored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import __version__
from .games import family_runs, model_dict, model_of, rule_seed_of
from .metrics.growth import GROWTH_METRICS
from .profile import build_profile, write_evaluation
from .profile import write_profile as write_run_profile
from .recording import RunData, as_float, load_run, named_folder

FAMILY_FORMAT = "cogbench-family-profile/0"


class ControlMismatch(ValueError):
    """The control family cannot be paired with the family."""


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _view(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": metric["value"],
        "status": metric["status"],
        "opportunities": metric["opportunities"],
        "reason": metric["reason"],
    }


def total_hp_lost(run: RunData) -> float:
    """HP the player lost in the whole game (the `damage` events to the player)."""
    return sum(as_float(e.get("amount")) for e in run.events.player_damage(0, 10**12))


def _game(number: int, name: str, run: RunData, profile: dict[str, Any], baseline: int) -> dict:
    by_name = {m["name"]: m for m in profile["metrics"]}
    cost = profile.get("cost") or {}
    return {
        "run": name,
        "index": number,
        "world_seed": run.world.seed,
        "rule_seed": rule_seed_of(run),
        "model": model_dict(model_of(run)),
        "workspace_cleared": (run.summary or {}).get("workspace_cleared_each_game"),
        "composite": profile["composite"],
        "ability_mean": profile["ability_mean"],
        "depth": profile["depth"]["score"],
        "hp_lost": round(total_hp_lost(run), 2),
        "decisions": profile["steps"]["decisions"],
        "end": profile["outcome"]["over"],
        "cost_usd": cost.get("usd"),
        "growth": None
        if number <= baseline
        else {n: _view(by_name[n]) for n in GROWTH_METRICS if n in by_name},
    }


def _scene_scores(profile: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for enc in profile["encounters"]:
        scores = [v["score"] for v in enc["visits"] if v["score"] is not None]
        if scores:
            out[enc["id"]] = sum(scores) / len(scores)
    return out


def _growth_mean(games: list[dict[str, Any]]) -> dict[str, Any]:
    later = [g for g in games if g.get("growth") is not None]
    out: dict[str, Any] = {}
    for name in GROWTH_METRICS:
        values = [
            g["growth"][name]["value"]
            for g in later
            if name in g["growth"] and g["growth"][name]["value"] is not None
        ]
        out[name] = {
            "value": _rounded(_mean(values)),
            "measured_games": len(values),
            "later_games": len(later),
        }
    return out


def build_family_profile(folder: Path | str, *, write_runs: bool = True) -> dict[str, Any]:
    """Evaluate every `run-NN` of `folder` (writing each `profile.json` unless `write_runs` is
    false) and put them side by side. A folder that cannot be read is an entry with an `error`."""
    root = named_folder(Path(folder))
    runs = family_runs(root)
    if not runs:
        raise FileNotFoundError(f"{root}: no run-NN folders (not a family folder)")
    baseline = runs[0][0]
    games: list[dict[str, Any]] = []
    scores: dict[str, dict[str, float | None]] = {}
    for number, run_dir in runs:
        try:
            run = load_run(run_dir)
            profile = build_profile(run)
            if write_runs:
                write_run_profile(profile, run_dir / "profile.json")
        except (OSError, ValueError) as err:
            games.append({"run": run_dir.name, "index": number, "error": str(err)})
            continue
        games.append(_game(number, run_dir.name, run, profile, baseline))
        for eid, score in _scene_scores(profile).items():
            scores.setdefault(eid, {})[run_dir.name] = round(score, 4)
    names = [g["run"] for g in games]
    read = [g for g in games if "error" not in g]
    return {
        "format": FAMILY_FORMAT,
        "family_dir": root.name,
        "evaluator": {"version": __version__},
        "model": read[0]["model"] if read else None,
        "rule_seed": read[0]["rule_seed"] if read else None,
        "games": games,
        "encounters": {
            eid: {name: by_game.get(name) for name in names}
            for eid, by_game in sorted(scores.items())
        },
        "growth": {"baseline": runs[0][1].name, "mean": _growth_mean(read)},
    }


# ------------------------------------------------------------------------------------ control
def _baseline_index(profile: dict[str, Any]) -> int:
    """The number of game 1 of a family profile (its lowest `run-NN`, readable or not)."""
    return min(g["index"] for g in profile["games"])


def _problems(family: dict[str, Any], control: dict[str, Any]) -> list[str]:
    """What keeps the two families from being paired, game by game."""
    mine = {g["index"]: g for g in family["games"] if "error" not in g}
    theirs = {g["index"]: g for g in control["games"] if "error" not in g}
    out = []
    if _baseline_index(family) != _baseline_index(control):
        out.append(
            f"game 1 is run {_baseline_index(family)} in the family, "
            f"run {_baseline_index(control)} in the control"
        )
    for index in sorted(set(mine) & set(theirs)):
        for key, label in (
            ("model", "model"),
            ("rule_seed", "rule seed"),
            ("world_seed", "world seed"),
        ):
            if mine[index][key] != theirs[index][key]:
                out.append(f"game {index}: {label} {mine[index][key]} vs {theirs[index][key]}")
    return out


def add_control(family: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    """Pair a control family with `family` (same model, rule seed and world seeds, game by game)
    and add `control` with the memory effect. Raises `ControlMismatch` with the reason if they
    cannot be paired. Display only: nothing here is scored."""
    mine = {g["index"]: g for g in family["games"] if "error" not in g}
    theirs = {g["index"]: g for g in control["games"] if "error" not in g}
    common = sorted(set(mine) & set(theirs))
    if not common:
        raise ControlMismatch(
            "no game of the family has a game with the same number in the control"
        )
    problems = _problems(family, control)
    if problems:
        raise ControlMismatch(
            "the control family is not the same experiment as the family (it must share the model, "
            "the rule seed and the world seeds game by game): " + "; ".join(problems)
        )
    baseline = _baseline_index(family)
    later = [i for i in common if i > baseline]
    if not later:
        raise ControlMismatch("no later game of the family has a partner in the control")
    effect: dict[str, Any] = {}
    for name in GROWTH_METRICS:
        pairs = []
        for i in later:
            a, b = mine[i]["growth"].get(name), theirs[i]["growth"].get(name)
            if a and b and a["value"] is not None and b["value"] is not None:
                pairs.append((a["value"], b["value"]))
        f_mean, c_mean = _mean([a for a, _ in pairs]), _mean([b for _, b in pairs])
        effect[name] = {
            "value": None if f_mean is None or c_mean is None else _rounded(f_mean - c_mean),
            "pairs": len(pairs),
            "family": _rounded(f_mean),
            "control": _rounded(c_mean),
        }
    cleared = bool(theirs) and all(g.get("workspace_cleared") is True for g in theirs.values())
    section: dict[str, Any] = {
        "family_dir": control["family_dir"],
        "workspace_cleared": cleared,
        "scored": False,
        "paired_games": later,
        "games": control["games"],
        "memory_effect": effect,
    }
    if not cleared:
        section["note"] = (
            "the control's summaries do not all say that the workspace was emptied before each game"
        )
    return {**family, "control": section}


def write_family_profile(profile: dict[str, Any], out: Path | str) -> Path:
    return write_evaluation(profile, out, what="a family profile")


# ----------------------------------------------------------------------------------- the table
def _cell(value: float | None, width: int, places: int = 2) -> str:
    return f"{'-' if value is None else format(value, f'.{places}f'):>{width}}"


def format_family(profile: dict[str, Any]) -> str:
    """A short plain table of the family (and its control, if paired)."""
    games = profile["games"]
    model = profile["model"]
    who = "no model" if model is None else f"{model['provider']}/{model['model']}"
    lines = [
        (
            f"family {profile['family_dir']}: {len(games)} game(s), {who}, "
            f"rule seed {profile['rule_seed']}; baseline {profile['growth']['baseline']}"
        ),
        "",
        f"{'game':<10}{'composite':>10}{'depth':>8}{'hp lost':>9}{'decisions':>11}  end",
    ]
    for g in games:
        if "error" in g:
            lines.append(f"{g['run']:<10}error: {g['error']}")
            continue
        steps = "-" if g["decisions"] is None else str(g["decisions"])
        lines.append(
            f"{g['run']:<10}{g['composite']:>10.1f}{g['depth']:>8.1f}{g['hp_lost']:>9.1f}"
            f"{steps:>11}  {g['end'] or '-'}"
        )
    width = 17
    head = "".join(f"{n:>{width}}" for n in GROWTH_METRICS)
    lines += [
        "",
        (
            f"growth against {profile['growth']['baseline']} "
            "(0.5 no change, 1 all the room used, 0 all lost; - not measured)"
        ),
        f"{'game':<20}{head}",
    ]
    for g in games:
        if g.get("growth") is not None:
            row = "".join(_cell(g["growth"].get(n, {}).get("value"), width) for n in GROWTH_METRICS)
            lines.append(f"{g['run']:<20}{row}")
    mean = profile["growth"]["mean"]
    lines.append(
        f"{'mean, later games':<20}"
        + "".join(_cell(mean[n]["value"], width) for n in GROWTH_METRICS)
    )
    control = profile.get("control")
    if control is not None:
        lines += [
            "",
            (
                f"memory effect against control {control['family_dir']} "
                "(family minus control, display only; paired games "
                f"{', '.join(str(i) for i in control['paired_games'])})"
            ),
            f"{'':<20}{head}",
            f"{'memory effect':<20}"
            + "".join(_cell(control["memory_effect"][n]["value"], width) for n in GROWTH_METRICS),
        ]
        if control.get("note"):
            lines.append(f"note: {control['note']}")
    return "\n".join(lines)
