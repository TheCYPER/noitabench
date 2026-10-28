"""N2 notes_accuracy and notes_learned: are the notes right, and did the game teach what they say?

The claims the notes of a run make are extracted by `python -m noitabench notes-claims` (contracts
section 21) and judged against the knowledge base of the run's rule seed by code
(`eval/knowledge/judge.py`). Without `notes_claims.json` both metrics are `not_measured`: the
evaluator never calls a model.

notes_accuracy: the claims of the notebook the game ended with that count (judged correct, partly
    right or wrong, and not hedged; a statement made in several files once). Value = the sum of
    their weights (1, 0.5, 0) over their number: one opportunity. Told facts count here (a note
    that repeats what the game tells is right). Claims that something does nothing (`no_recipe`,
    `no_reaction`) are left out and tallied in the detail: almost every triple and pair does
    nothing (212 of the 220 triples), so they would be right by default and drown the errors.
    Not measured if no claim counts.
notes_learned: one opportunity per fact of tier `seed` or `game`, not told, that the game let the
    player learn and that the start notebook did not already hold correctly: a recipe whose potion
    the player made (a `mix` event within `NEAR_PLAYER` cells of the player's centre at its frame:
    a bottle the player carries mixes at the player), and a fact an encounter lesson links to a
    scene the player met (a scored visit). Value per opportunity: a correct unhedged claim in the
    end notebook 1, a partly right one 0.5, none 0. Correct `seed` and `game` facts the player
    wrote without meeting them are listed in the detail and not scored. Not measured if the
    notebook the game began with is unknown (`start` absent, or a file of it left unextracted),
    or if nothing was there to learn.

`notes_used` and `notes_corrected`, the two metrics that use the start notebook in a later game,
are in `notes_use.py`.

An extraction that is incomplete (`skipped` in the file: money ran out, a model error) is said in
the reason; the metrics are then computed from the files that were extracted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..encounters import Result
from ..knowledge.claims import NoteClaims
from ..knowledge.facts import Knowledge, build_knowledge
from ..knowledge.judge import Judged, judge_section
from ..recording import RunData
from . import Metric, metric_group

NEAR_PLAYER = 48  # cells: a mix this close to the player's centre is the player's own
LEARNABLE_TIERS = ("seed", "game")
NEGATIVE_KINDS = ("no_recipe", "no_reaction")  # right by default: not in notes_accuracy
NO_CLAIMS = (
    "no notes_claims.json: extract the claims of the notes with "
    "`python -m noitabench notes-claims <run>` (the evaluator calls no model)"
)


@dataclass(frozen=True)
class Mix:
    """A potion the player made: the frame and the place of its `mix` event."""

    frame: int
    potion: str
    x: float
    y: float


def player_mix_events(run: RunData) -> list[Mix]:
    """The `mix` events at most `NEAR_PLAYER` cells from the player's centre, in frame order."""
    made: list[Mix] = []
    for e in run.events.of_type("mix"):
        me = run.track.at(int(e["frame"]))
        if me is None:
            continue
        dx = float(e["x"]) - (me.x + me.w / 2)
        dy = float(e["y"]) - (me.y + me.h / 2)
        if dx * dx + dy * dy <= NEAR_PLAYER**2:
            made.append(Mix(int(e["frame"]), str(e["potion"]), float(e["x"]), float(e["y"])))
    return made


def player_mixes(run: RunData) -> set[str]:
    """The potions the player made."""
    return {m.potion for m in player_mix_events(run)}


def scenes_met(results: list[Result]) -> set[str]:
    """Encounters with a scored visit: the ones whose question was put."""
    return {r.visit.scene.eid for r in results if r.outcome.score is not None}


def extraction_gap(doc: NoteClaims) -> str:
    """The sentence that ends a reason when part of the notes was not extracted, else ''."""
    return f"; {len(doc.skipped)} file(s) were not extracted" if doc.skipped else ""


def best_value(judged: list[Judged], fact_id: str) -> float:
    """1 for a correct unhedged claim on the fact, else 0.5 for a partly right one, else 0."""
    values = [j.verdict.weight or 0.0 for j in judged if j.counted and j.verdict.fact_id == fact_id]
    return max((v for v in values if v > 0), default=0.0)


@metric_group
def notes_accuracy(run: RunData, _results: list[Result]) -> list[Metric]:
    names = ("notes_accuracy", ("N2",))
    doc = run.note_claims
    if doc is None:
        return [Metric(*names, None, 0, NO_CLAIMS)]
    k = build_knowledge(run.world.rule_seed)
    judged = judge_section(doc.section("end"), k)
    negatives = [j for j in judged if j.counted and j.claim.kind in NEGATIVE_KINDS]
    counted = [j for j in judged if j.counted and j.claim.kind not in NEGATIVE_KINDS]
    tally = {
        v: sum(1 for j in counted if j.verdict.verdict == v)
        for v in ("correct", "partial", "wrong")
    }
    detail: dict[str, Any] = {
        **tally,
        "hedged": sum(1 for j in judged if j.claim.hedged and j.verdict.verdict in tally),
        "not_judged": sum(1 for j in judged if j.verdict.verdict in ("unknown", "local", "other")),
        "nothing_happens": {
            "right": sum(1 for j in negatives if j.verdict.verdict == "correct"),
            "wrong": sum(1 for j in negatives if j.verdict.verdict == "wrong"),
        },
    }
    if not counted:
        return [
            Metric(
                *names, None, 0, "no claim of the final notes counts" + extraction_gap(doc), detail
            )
        ]
    total = sum(j.verdict.weight or 0.0 for j in counted)
    reason = f"{tally['correct']} right, {tally['partial']} partly, {tally['wrong']} wrong of {len(counted)}"
    return [Metric(*names, total / len(counted), 1, reason + extraction_gap(doc), detail)]


def learnable_facts(run: RunData, results: list[Result], k: Knowledge) -> list[str]:
    """Ids of the not-told `seed`/`game` facts the game let the player learn."""
    met, made = scenes_met(results), player_mixes(run)
    out = []
    for f in k.facts:
        if f.tier not in LEARNABLE_TIERS or f.told:
            continue
        if (f.kind == "recipe" and f.fields["potion"] in made) or (
            f.encounters and met & set(f.encounters)
        ):
            out.append(f.id)
    return out


@metric_group
def notes_learned(run: RunData, results: list[Result]) -> list[Metric]:
    names = ("notes_learned", ("N2",))
    doc = run.note_claims
    if doc is None:
        return [Metric(*names, None, 0, NO_CLAIMS)]
    if doc.start is None:
        why = "the notebook the game began with is unknown: what was learned cannot be told"
        return [Metric(*names, None, 0, why)]
    if any(s.get("section") == "start" for s in doc.skipped):
        why = "part of the notebook the game began with was not extracted: what it held is unknown"
        return [Metric(*names, None, 0, why)]
    k = build_knowledge(run.world.rule_seed)
    held = judge_section(doc.section("start"), k)
    end = judge_section(doc.section("end"), k)
    already = {j.verdict.fact_id for j in held if j.counted and j.verdict.verdict == "correct"}
    chances = [fid for fid in learnable_facts(run, results, k) if fid not in already]
    unmet = sorted(
        {
            j.verdict.fact_id
            for j in end
            if j.counted
            and j.verdict.verdict == "correct"
            and j.verdict.fact_id
            and j.verdict.tier in LEARNABLE_TIERS
            and not j.verdict.told
            and j.verdict.fact_id not in chances
            and j.verdict.fact_id not in already
        }
    )
    values = {fid: best_value(end, fid) for fid in chances}
    detail = {"learned": values, "written_without_meeting": unmet}
    if not chances:
        why = "nothing to learn: no secret potion was made and no scene with a lesson was met"
        return [Metric(*names, None, 0, why + extraction_gap(doc), detail)]
    right = sum(1 for v in values.values() if v >= 1.0)
    reason = f"{right} of {len(chances)} things the game could teach are in the final notes"
    value = sum(values.values()) / len(values)
    return [Metric(*names, value, len(chances), reason + extraction_gap(doc), detail)]
