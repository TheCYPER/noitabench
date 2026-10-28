"""N2 notes_used and notes_corrected: were the notes of an earlier game followed, and mended?

Both read the notebook the game began with (`start` of `notes_claims.json`, contracts section 21)
judged against the knowledge base of the run's rule seed, and the one it ended with (`end`). They
need `workspace_start/` (or a previous `run-NN/workspace/`, see `knowledge/extract.py`) and are
`not_measured` without it, without `notes_claims.json`, when part of the start was not extracted,
or when no situation for a note arose. A hedged claim never counts. A statement made in several
files counts once (`judge_section`); a read of any file that holds it is a read of the note.

**Situation** of a note: the moment the game put its claim to the test.

- a recipe claim: the player made the potion (a `mix` event of it near the player), or poured all
  the claimed inputs. Pours of one attempt lie at most `POUR_GAP` frames and `POUR_NEAR` cells
  apart (the place of a pour is the player's centre at its frame); the attempt is complete at the
  pour that brings the last input. The first of the two moments is the situation;
- a claim on a fact that an encounter lesson links to scenes (`Fact.encounters`): a scored visit
  of one of those scenes (score not None); each such visit is a situation.

**notes_used**: one opportunity per counted claim of the start notebook judged correct or partly
right whose situation arose.

- It must have been *read* before its situation: a `workspace_read` (or `memory_read`) of a file
  holding the claim, or any search, at a frame not after it (the frame of a read is that of the
  decision asked next). Without `decisions.jsonl` the time of a read is unknown and a read counts
  as early (said in the reason). No read in sight while programs ran (they read notes unseen):
  the claim is left out, as `notes_recall` does. A run that logged no notebook call at all (no
  transcript: the play server, the scripted bot) is `not_measured`.
- Success: a recipe claim, the player made the potion after the read, 1.0 if no ingredient of
  `data.tag_members()["ingredient"]` outside the real recipe was poured from the read until that
  first mix, else 0.5. A scene claim, a visit that began at or after the read scored at least
  `USE_SUCCESS` (best of those visits). Anything else, and a note not read before: 0.
- A partly right claim halves the value.
- `misled` (detail): counted wrong claims that were read before their situation and then failed
  (a recipe: its inputs were poured and no such potion came from the start of the attempt until
  `MIX_LAG` frames after it; a scene: every visit from the read on scored under `USE_SUCCESS`).

**notes_corrected**: one opportunity per counted wrong claim of the start notebook that the game
contradicted (not measured if part of the final notebook was not extracted: a wrong note that
looks gone may be in the file that was left out):

- a recipe claim: the player poured all the claimed inputs and the potion did not come from
  that attempt (no `mix` of it from its start until `MIX_LAG` frames after its last pour), or
  made the potion at a time when the claimed inputs were not all poured near the mix;
- a drink claim: the player drank that material;
- a claim whose fact is linked to scenes: a scored visit of one of them.

Value: the end notebook holds a correct counted claim on the same subject (`subject_of`) and no
wrong counted one 1.0; no wrong counted claim on it is left (gone, or hedged) 0.5; still there 0.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..encounters import Result
from ..knowledge import data
from ..knowledge.claims import NoteClaims
from ..knowledge.facts import Fact, Knowledge, build_knowledge
from ..knowledge.judge import Judged, claim_key, judge_section, subject_of
from ..recording import RunData, as_int
from . import Metric, metric_group
from .knowledge import NO_CLAIMS, Mix, extraction_gap, player_mix_events
from .notes import _programs_ran, notebook_calls

POUR_GAP = 1800  # frames between pours that belong to one attempt at a potion
POUR_NEAR = 96  # cells between the places of such pours (and of a pour and its mix)
MIX_LAG = 300  # frames after the last pour in which a potion is still due (the pour is logged
#                when its action ends, a little after the cells have met)
USE_SUCCESS = 0.7  # the score of a scene that counts as a note followed to success
EXTRA_TRIED = 0.5  # value of a recipe that was made, but after other ingredients were tried
CORRECTED_GONE = 0.5


# --------------------------------------------------------------------------- what was played
@dataclass(frozen=True)
class Pour:
    frame: int
    material: str
    x: float
    y: float


@dataclass(frozen=True)
class Attempt:
    """All inputs of a recipe claim poured together: from the earliest of the latest pours of each
    input in reach, to the pour that completed them."""

    start: int
    frame: int


@dataclass(frozen=True)
class Seen:
    """A scored visit of an encounter."""

    eid: str
    enter: int
    score: float


@dataclass(frozen=True)
class Play:
    mixes: tuple[Mix, ...]
    pours: tuple[Pour, ...]
    drinks: frozenset[str]
    visits: tuple[Seen, ...]
    reads: tuple[tuple[str, str | None, int], ...]  # (kind, path, frame) of reads and searches
    seen: bool  # the run logged the notebook calls (a transcript, or memory_* decisions)
    timed: bool  # decisions.jsonl is there: the frames of reads are known
    programs: bool  # programs ran: reads may have gone unseen
    ingredients: frozenset[str]

    @staticmethod
    def of(run: RunData, results: list[Result]) -> Play:
        pours = []
        for e in run.events.of_type("pour"):
            frame = as_int(e.get("frame"))
            me = run.track.at(frame)
            if me is not None:
                pours.append(
                    Pour(frame, str(e.get("material", "")), me.x + me.w / 2, me.y + me.h / 2)
                )
        reads = [
            (c.kind, c.path, c.frame) for c in notebook_calls(run) if c.kind in ("read", "search")
        ]
        return Play(
            mixes=tuple(player_mix_events(run)),
            pours=tuple(pours),
            drinks=frozenset(str(e.get("material", "")) for e in run.events.of_type("drink")),
            visits=tuple(
                sorted(
                    (
                        Seen(r.visit.scene.eid, r.visit.enter, r.outcome.score)
                        for r in results
                        if r.outcome.score is not None
                    ),
                    key=lambda v: (v.enter, v.eid),
                )
            ),
            reads=tuple(reads),
            seen=bool(run.transcript) or bool(reads),
            timed=run.decisions.present,
            programs=_programs_ran(run),
            ingredients=frozenset(data.tag_members()["ingredient"]),
        )

    def first_read(self, paths: set[str]) -> int | None:
        """The frame of the first read of a file in `paths` (a search reads them all); -1 when the
        time of reads is not known; None if none was read in sight."""
        frames = [f for kind, path, f in self.reads if kind == "search" or path in paths]
        if not frames:
            return None
        return min(frames) if self.timed else -1

    def seen_in(self, encounters: Iterable[str]) -> list[Seen]:
        wanted = set(encounters)
        return [v for v in self.visits if v.eid in wanted]


def _apart(a: Pour, x: float, y: float) -> float:
    return math.hypot(a.x - x, a.y - y)


def covering_attempt(pours: Iterable[Pour], inputs: Iterable[str]) -> Attempt | None:
    """The first moment at which every one of `inputs` was poured within `POUR_GAP` frames and
    `POUR_NEAR` cells of the latest pour, or None."""
    wanted, listed = set(inputs), list(pours)
    if not wanted:
        return None
    for p in listed:
        if p.material not in wanted:
            continue
        latest: dict[str, int] = {}
        for q in listed:
            if (
                q.material in wanted
                and 0 <= p.frame - q.frame <= POUR_GAP
                and _apart(q, p.x, p.y) <= POUR_NEAR
            ):
                latest[q.material] = max(latest.get(q.material, -1), q.frame)
        if len(latest) == len(wanted):
            return Attempt(min(latest.values()), p.frame)
    return None


def poured_near(pours: Iterable[Pour], mix: Mix) -> set[str]:
    """The materials poured close to a mix in the `POUR_GAP` frames before it (and the `MIX_LAG`
    after: the end of a pour is logged late)."""
    return {
        q.material
        for q in pours
        if mix.frame - POUR_GAP <= q.frame <= mix.frame + MIX_LAG
        and _apart(q, mix.x, mix.y) <= POUR_NEAR
    }


def made_between(play: Play, potion: str, f0: int, f1: int) -> bool:
    return any(m.potion == potion and f0 <= m.frame <= f1 for m in play.mixes)


# ----------------------------------------------------------------------------- a note followed
@dataclass(frozen=True)
class Use:
    fact: str
    value: float | None  # None: left out (reads may have gone unseen)
    reason: str

    def scaled(self, weight: float) -> Use:
        return self if self.value is None else Use(self.fact, self.value * weight, self.reason)


def _unread(fact: Fact, play: Play) -> Use:
    if play.programs:
        return Use(fact.id, None, "no read in sight, but programs ran (they can read unseen)")
    return Use(fact.id, 0.0, "had the note, did not read it")


def _recipe_use(claim_inputs: list[str], fact: Fact, paths: set[str], play: Play) -> Use | None:
    potion, real = fact.fields["potion"], set(fact.fields["inputs"])
    made = [m.frame for m in play.mixes if m.potion == potion]
    attempt = covering_attempt(play.pours, claim_inputs)
    arose = min([*made[:1], *([attempt.frame] if attempt else [])], default=None)
    if arose is None:
        return None
    read = play.first_read(paths)
    if read is None:
        return _unread(fact, play)
    if read > arose:
        return Use(
            fact.id, 0.0, f"read it at frame {read}, after trying the potion (frame {arose})"
        )
    later = [f for f in made if f >= read]
    if not later:
        return Use(fact.id, 0.0, "read it, but did not make the potion after that")
    first = later[0]
    extra = sorted(
        {
            p.material
            for p in play.pours
            if read <= p.frame <= first
            and p.material in play.ingredients
            and p.material not in real
        }
    )
    if extra:
        return Use(fact.id, EXTRA_TRIED, f"made it after trying {', '.join(extra)} as well")
    return Use(fact.id, 1.0, "made it from the note without trying anything else")


def _scene_use(fact: Fact, paths: set[str], play: Play) -> Use | None:
    visits = play.seen_in(fact.encounters)
    if not visits:
        return None
    read = play.first_read(paths)
    if read is None:
        return _unread(fact, play)
    usable = [v for v in visits if read <= v.enter]
    if not usable:
        return Use(fact.id, 0.0, f"read it at frame {read}, after the scene(s) it is about")
    best = max(usable, key=lambda v: v.score)
    if best.score >= USE_SUCCESS:
        return Use(fact.id, 1.0, f"read before {best.eid}, which went well ({best.score:.2f})")
    return Use(fact.id, 0.0, f"read before {best.eid}, which went badly ({best.score:.2f})")


def use_of(j: Judged, paths: set[str], k: Knowledge, play: Play) -> Use | None:
    """What came of a right or partly right note, or None if its moment never came."""
    fact = k.by_id.get(j.verdict.fact_id or "")
    if fact is None or j.verdict.weight is None:
        return None
    if j.claim.kind == "recipe" and fact.kind == "recipe":
        found = _recipe_use(list(j.claim.fields["inputs"]), fact, paths, play)
    elif fact.encounters:
        found = _scene_use(fact, paths, play)
    else:
        return None
    return None if found is None else found.scaled(j.verdict.weight)


def misled_by(j: Judged, paths: set[str], k: Knowledge, play: Play) -> str | None:
    """Why a wrong note, read before its moment, led nowhere; None if it did not."""
    fact = k.by_id.get(j.verdict.fact_id or "")
    if fact is None:
        return None
    if j.claim.kind == "recipe" and fact.kind == "recipe":
        attempt = covering_attempt(play.pours, j.claim.fields["inputs"])
        read = play.first_read(paths)
        if attempt is None or read is None or read > attempt.frame:
            return None
        potion = fact.fields["potion"]
        if made_between(play, potion, attempt.start, attempt.frame + MIX_LAG):
            return None
        return f"poured what it says after reading it (frame {attempt.frame}): no {potion}"
    visits = play.seen_in(fact.encounters)
    read = play.first_read(paths)
    usable = [v for v in visits if read is not None and read <= v.enter]
    if usable and all(v.score < USE_SUCCESS for v in usable):
        return f"read before {usable[0].eid}, which went badly"
    return None


# --------------------------------------------------------------------------- a note mended
def contradiction(j: Judged, k: Knowledge, play: Play) -> str | None:
    """How the game showed a wrong note to be wrong, or None if it did not."""
    claim = j.claim
    fact = k.by_id.get(j.verdict.fact_id or "")
    if fact is None:
        return None
    if claim.kind == "recipe" and fact.kind == "recipe":
        potion, claimed = fact.fields["potion"], list(claim.fields["inputs"])
        attempt = covering_attempt(play.pours, claimed)
        if attempt is not None and not made_between(
            play, potion, attempt.start, attempt.frame + MIX_LAG
        ):
            return f"poured the claimed inputs (frame {attempt.frame}) and got no {potion}"
        for m in play.mixes:
            if m.potion == potion and not set(claimed) <= poured_near(play.pours, m):
                return f"made {potion} (frame {m.frame}) without those inputs"
    if claim.kind == "drink" and claim.fields["material"] in play.drinks:
        return f"drank {claim.fields['material']}"
    seen = play.seen_in(fact.encounters)
    if seen:
        return f"met {seen[0].eid}, which tests it"
    return None


def corrected_value(j: Judged, end: list[Judged], k: Knowledge) -> tuple[float, str]:
    """1.0 / 0.5 / 0 by what the final notebook says on the subject of a wrong start claim."""
    subject = subject_of(j.claim, k)
    here = [e for e in end if e.counted and subject_of(e.claim, k) == subject]
    if any(e.verdict.verdict == "wrong" for e in here):
        return 0.0, "the wrong claim is still in the notes"
    if any(e.verdict.verdict == "correct" for e in here):
        return 1.0, "replaced by a correct claim"
    return CORRECTED_GONE, "the wrong claim is gone or hedged"


# ------------------------------------------------------------------------------- the metrics
def _start_problem(doc: NoteClaims) -> str | None:
    if doc.start is None:
        return "the notebook the game began with is unknown (no workspace_start/, no opening)"
    if any(s.get("section") == "start" for s in doc.skipped):
        return "part of the notebook the game began with was not extracted"
    return None


def _label(j: Judged) -> str:
    return j.verdict.fact_id or j.claim.kind


def _used(
    start: list[Judged], paths_of: dict[str, set[str]], k: Knowledge, play: Play, doc: NoteClaims
) -> Metric:
    names = ("notes_used", ("N2",))
    right = [j for j in start if j.counted and j.verdict.verdict in ("correct", "partial")]
    wrong = [j for j in start if j.counted and j.verdict.verdict == "wrong"]
    misled = []
    for j in wrong:
        why = misled_by(j, paths_of[claim_key(j.claim)], k, play)
        if why is not None:
            misled.append({"fact": _label(j), "why": why})
    gap = extraction_gap(doc)
    if right and not play.seen:
        why = "no transcript: the play server and the scripted bot do not log reads of notes"
        return Metric(*names, None, 0, why + gap)
    uses: list[Use] = []
    unseen: list[str] = []
    no_moment: list[str] = []
    for j in right:
        found = use_of(j, paths_of[claim_key(j.claim)], k, play)
        if found is None:
            no_moment.append(_label(j))
        elif found.value is None:
            unseen.append(found.fact)
        else:
            uses.append(found)
    detail: dict[str, Any] = {
        "used": [{"fact": u.fact, "value": u.value, "why": u.reason} for u in uses],
        "misled": misled,
        "unseen_reads": unseen,
        "no_moment": no_moment,
        "hedged": sum(1 for j in start if j.claim.hedged),
        "reads_untimed": not play.timed,
    }
    if not right:
        why = "the notebook the game began with holds no claim that counts as right"
        return Metric(*names, None, 0, why + gap, detail)
    if not uses:
        why = "no note of the start notebook came into play"
        if unseen:
            why += f" ({len(unseen)} left out: programs ran and no read was in sight)"
        return Metric(*names, None, 0, why + gap, detail)
    followed = sum(1 for u in uses if (u.value or 0.0) > 0)
    reason = f"{followed} of {len(uses)} right notes read in time and followed to success"
    if misled:
        reason += f"; {len(misled)} wrong note(s) read in time led nowhere"
    if not play.timed:
        reason += "; reads are counted as early (no decisions.jsonl)"
    value = sum(u.value or 0.0 for u in uses) / len(uses)
    return Metric(*names, value, len(uses), reason + gap, detail)


def _corrected(
    start: list[Judged], end: list[Judged], k: Knowledge, play: Play, doc: NoteClaims
) -> Metric:
    names = ("notes_corrected", ("N2",))
    wrong = [j for j in start if j.counted and j.verdict.verdict == "wrong"]
    if not wrong:
        why = "the notebook the game began with holds no wrong claim that counts"
        return Metric(*names, None, 0, why + extraction_gap(doc))
    if any(s.get("section") == "end" for s in doc.skipped):
        # a wrong note that is "gone" may only be in a file that was not extracted
        why = (
            "part of the final notebook was not extracted: whether a wrong note is gone is unknown"
        )
        return Metric(*names, None, 0, why + extraction_gap(doc))
    mended: list[dict[str, Any]] = []
    for j in wrong:
        how = contradiction(j, k, play)
        if how is not None:
            value, said = corrected_value(j, end, k)
            mended.append({"fact": _label(j), "value": value, "tested": how, "end": said})
    detail = {"wrong_claims": len(wrong), "tested": mended}
    gap = extraction_gap(doc)
    if not mended:
        why = f"none of the {len(wrong)} wrong note(s) was put to the test in this game"
        return Metric(*names, None, 0, why + gap, detail)
    fixed = sum(1 for m in mended if m["value"] >= 1.0)
    reason = f"{fixed} of {len(mended)} wrong notes that the game contradicted were mended"
    value = sum(m["value"] for m in mended) / len(mended)
    return Metric(*names, value, len(mended), reason + gap, detail)


@metric_group
def notes_use(run: RunData, results: list[Result]) -> list[Metric]:
    names = [("notes_used", ("N2",)), ("notes_corrected", ("N2",))]
    doc = run.note_claims
    if doc is None:
        return [Metric(*n, None, 0, NO_CLAIMS) for n in names]
    if (problem := _start_problem(doc)) is not None:
        return [Metric(*n, None, 0, problem) for n in names]
    k = build_knowledge(run.world.rule_seed)
    pairs = doc.section("start")
    paths_of: dict[str, set[str]] = {}
    for item in judge_section(pairs, k, distinct=False):
        paths_of.setdefault(claim_key(item.claim), set()).add(item.path)
    start = judge_section(pairs, k)
    end = judge_section(doc.section("end"), k)
    play = Play.of(run, results)
    return [_used(start, paths_of, k, play, doc), _corrected(start, end, k, play, doc)]
