"""`profile.json`: the evaluation of one run (`cogbench-profile/0`).

    {
      "format": "cogbench-profile/0",
      "run_id", "run_dir": the folder's name (not its path: the same folder gives the same file
                wherever it lies), "source": "agent" | "human" | "bot" | "unknown",
      "model": {"provider", "model"} | null,            # from summary.json (agents only)
      "world": {"seed", "rule_seed", "file"},
      "composite": 0..100,                              # 0.8 x ability_mean + 0.2 x depth score
      "ability_mean": 0..100,         # the mean over all 11 capabilities (N1..N10, C) of their
                                     # `discounted_score` (score x n / (n + 2); no score = 0)
      "ability_raw_mean": 0..100 | null,  # the mean of the scores that exist, no discount (info)
      "composite_note": str | null,   # "thin: only k of 11 ..." when fewer than 5 capabilities
                                     # were covered; "no capability ..." when none was scored
      "covered": ["N1", ...],        # capabilities with a score and n >= 2 opportunities
      "left_out": ["N2", ...],       # the others: they stay in the mean at their discounted score
      "depth": {"score", "fraction", "start_y",
                "deepest_y",          # the lowest point that counts (capped at the seal plug's
                                      # top unless the hit box was inside the sealed room)
                "deepest_raw_y",      # the lowest point reached, whatever the room
                "capped_at_seal": bool, "bottom_y", "reached_sealed_room"},
      "outcome": {"over", "died", "death_frame", "frames"},
      "capabilities": {
        "N1" .. "N10": {"score": 0..100 | null, "opportunities", "covered", "note"?,
                        "discount": n / (n + 2), "discounted_score": score x discount (0 if null),
                        "encounters": [{"id", "instance", "role", "weight", "score"}],
                        "metrics": [{"name", "weight", "value", "n"}]},
        "C": {"score", "opportunities", "covered", "discount", "discounted_score",
              "parts": {"C1".."C4": <as above, without discount fields>}}
      },
      "encounters": [                                    # the 17 implemented, in id order
        {"id", "nodes", "placed": n, "must_pass_placed": n,
         "visits": [{"instance", "must_pass", "layer", "variant", "enter_frame", "exit_frame",
                     "stays": [[enter, exit], ...], "scored": bool, "score": 0..1 | null,
                     "reasons": [str], "facts": {...}}]}
      ],
      "metrics": [{"name", "capabilities", "value": 0..1 | null, "status": "measured" |
                   "not_measured", "opportunities", "reason", "detail"}],
      "attribution": [...],                              # failures traced to nodes (attribution.py)
      "cost": {"usd", "model_calls", "input_tokens", ...} | null,   # from summary.json
      "steps": {"decisions", "decision_records", "frames"},
      "test_awareness": {"checked_texts", "hits", "by_category", "snippets"} | null,
      "evaluator": {"version", "notes": [...]}
    }

A game after the first of a family folder (`run-02`, ...) also carries `cross_game_gain` (N2) and
`growth_depth`, `growth_harm`, `growth_pace` (C4) against game 1 (`metrics/growth.py`); in game 1
and in a run outside a family folder they are `not_measured` and change no score.

`covered: false` capabilities (fewer than 2 opportunities) keep their score here and count in the
composite only at their discount (one opportunity: a third). Since 2026-10-28 `ability_mean` is
the discounted mean; before it was the plain mean of the covered ones. The profile is evaluation
output: it is never given to an agent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .attribution import attribute
from .awareness import scan_transcript
from .depth import depth_score
from .encounters import Result, evaluate_visits, implemented
from .metrics import compute_metrics
from .recording import RunData, load_run
from .scoring import capability_scores, composite
from .worldinfo import encounter_nodes

PROFILE_FORMAT = "cogbench-profile/0"


def _visit_dict(r: Result) -> dict[str, Any]:
    v = r.visit
    return {
        "instance": v.scene.key,
        "must_pass": v.scene.must_pass,
        "layer": v.scene.layer,
        "variant": v.scene.variant,
        "enter_frame": v.enter,
        "exit_frame": v.exit,
        "stays": [list(s) for s in v.segments],
        "scored": r.outcome.score is not None,
        "score": None if r.outcome.score is None else round(r.outcome.score, 4),
        "reasons": r.outcome.reasons,
        "facts": r.outcome.facts,
    }


def _encounters(run: RunData, results: list[Result]) -> list[dict[str, Any]]:
    out = []
    for eid in implemented():
        placed = run.world.scenes_of(eid)
        out.append(
            {
                "id": eid,
                "nodes": list(encounter_nodes(eid)),
                "placed": len(placed),
                "must_pass_placed": sum(1 for s in placed if s.must_pass),
                "visits": [_visit_dict(r) for r in results if r.visit.scene.eid == eid],
            }
        )
    return out


def _part(doc: dict[str, Any] | None, key: str) -> dict[str, Any]:
    """`doc[key]` if it is an object, else an empty one (a damaged `summary.json`)."""
    value = (doc or {}).get(key)
    return value if isinstance(value, dict) else {}


def _model(run: RunData) -> dict[str, Any] | None:
    model = _part(run.summary, "model")
    if not model:
        return None
    return {"provider": model.get("provider"), "model": model.get("model")}


def _cost(run: RunData) -> dict[str, Any] | None:
    result = _part(run.summary, "result")
    if not result:
        return None
    usage = _part(result, "usage")
    return {
        "usd": result.get("cost_usd"),
        "cost_known": (run.summary or {}).get("cost_known"),
        "model_calls": result.get("model_calls"),
        "wall_seconds": result.get("wall_seconds"),
        "input_tokens": usage.get("input_tokens"),
        "cache_read_tokens": usage.get("cache_read_tokens"),
        "cache_write_tokens": usage.get("cache_write_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "thinking_tokens": usage.get("thinking_tokens"),
    }


def _outcome(run: RunData) -> dict[str, Any]:
    result = _part(run.summary, "result")
    died = run.died_at()
    return {
        "over": result.get("over") or ("dead" if died is not None else None),
        "died": died is not None,
        "death_frame": died,
        "frames": run.last_frame,
    }


def _notes(run: RunData) -> list[str]:
    notes = []
    if not run.decisions.present:
        notes.append(
            "no decisions.jsonl: the parts of the rules that need the decisions "
            "(inspects, decisions per layer) are not measured"
        )
    seed = run.meta.get("seed")
    if isinstance(seed, int) and not isinstance(seed, bool) and seed != run.world.seed:
        notes.append(
            f"the world file has seed {run.world.seed} but the recording seed {seed}: "
            "the scenes below may be those of another world"
        )
    if run.world.png_path is None:
        notes.append("no world PNG: hazards under the player are named from damage events only")
    if run.source == "bot":
        notes.append("scripted bot: it plans on the whole grid, it is a reference, not a player")
    return notes


def build_profile(run: RunData) -> dict[str, Any]:
    results = evaluate_visits(run)
    metrics = compute_metrics(run, results)
    capabilities = capability_scores(results, metrics)
    depth = depth_score(run)
    total = composite(capabilities, depth)
    awareness = scan_transcript(run.transcript) if run.transcript else None
    return {
        "format": PROFILE_FORMAT,
        "run_id": run.run_id,
        "run_dir": run.root.name,
        "source": run.source,
        "model": _model(run),
        "world": {
            "seed": run.world.seed,
            "rule_seed": run.world.rule_seed,
            "file": run.world.json_path.name if run.world.json_path else None,
        },
        "composite": total["composite"],
        "ability_mean": total["ability_mean"],
        "ability_raw_mean": total["ability_raw_mean"],
        "composite_note": total["note"],
        "covered": total["covered"],
        "left_out": total["left_out"],
        "depth": depth,
        "outcome": _outcome(run),
        "capabilities": {k: c.as_dict() for k, c in capabilities.items()},
        "encounters": _encounters(run, results),
        "metrics": [m.as_dict() for m in metrics],
        "attribution": attribute(run, results),
        "cost": _cost(run),
        "steps": {
            "decisions": run.decisions.total_cost if run.decisions.present else None,
            "decision_records": len(run.decisions),
            "frames": run.last_frame,
        },
        "test_awareness": awareness,
        "evaluator": {"version": __version__, "notes": _notes(run)},
    }


def evaluate_run(
    run_dir: Path | str, world_files: tuple[Path | str, Path | str] | None = None
) -> dict[str, Any]:
    """Read the run folder and return its profile."""
    return build_profile(load_run(run_dir, world_files))


# what an agent can read, or a notebook copy kept in a run folder: never write there
FORBIDDEN_FOLDERS = ("workspace", "workspace_start", "workspaces")


def write_profile(profile: dict[str, Any], out: Path | str) -> Path:
    """Write `profile.json`. Refuses a path inside a workspace folder: the profile is evaluation
    output and must not lie where an agent (or a human player's notebook) can read it."""
    return write_evaluation(profile, out, what="a profile")


def write_evaluation(doc: dict[str, Any], out: Path | str, *, what: str) -> Path:
    """Write an evaluation file (`profile.json`, `family_profile.json`), same guard as above."""
    path = Path(out)
    if any(part in FORBIDDEN_FOLDERS for part in path.resolve().parts):
        raise ValueError(f"{path}: refusing to write {what} into a workspace folder")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return path
