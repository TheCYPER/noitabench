"""The indicators of capability graph section 4 that the recordings cannot show.

Each is reported as `not_measured` with the reason, so a reader of `profile.json` sees what the
score does not cover. Nothing here is estimated.
"""

from __future__ import annotations

from ..encounters import Result
from ..recording import RunData
from . import Metric, metric_group

# (name, capabilities, reason)
UNMEASURED: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "cross_game_gain",
        ("N2", "C4"),
        (
            "the gain from game to game in one rule-seed family needs two or more games; "
            "a single run has none"
        ),
    ),
    (
        "fire_and_buoyancy",
        ("N4",),
        (
            "keeping out of the way of rising fire and using what floats need the burning state "
            "per frame (frames.bin v0 holds none) and the intent of a move; gases do no harm of "
            "their own here; first meetings with harmful liquids, catching fire and deep dives "
            "are scored (first_contact_physics)"
        ),
    ),
    (
        "experiment_value",
        ("N6",),
        (
            "whether a trial changed the later behaviour needs the model's intentions, "
            "not the recording"
        ),
    ),
    (
        "inspect_result_used",
        ("N7",),
        "the result of an inspect is not in decisions.jsonl (only a digest of the answer)",
    ),
    (
        "wand_edit_gain",
        ("N8",),
        (
            "the damage or passage gained by each wand edit would need the wand before and after "
            "(edit_wand events carry only the wand index); the seal key is scored instead"
        ),
    ),
    (
        "stop_when_unsure",
        ("N10",),
        (
            "stopping when unsure (and having enough signal before dying) needs the model's own "
            "uncertainty; only the scenes that pose it are scored: trying the vial first (E23), "
            "looking at the second pool before swimming it (E24) and at the bottles before "
            "drinking (E21)"
        ),
    ),
)


@metric_group
def not_measured(_run: RunData, _results: list[Result]) -> list[Metric]:
    return [Metric(name, caps, None, 0, reason) for name, caps, reason in UNMEASURED]
