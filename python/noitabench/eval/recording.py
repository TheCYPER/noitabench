"""A run folder read for evaluation: the recording, the decisions and the harness logs.

Files used (all optional except `meta.json`, `entities.jsonl` and the world file pair):

- `meta.json`, `entities.jsonl`, `events.jsonl`, `frames.bin`: the recording (contracts section 5);
- `decisions.jsonl`: one line per decision point (agents and the human player; the scripted bot
  writes none);
- `transcript.jsonl`, `harness.jsonl`, `summary.json`, `workspace/`: the harness run folder
  (contracts section 17; `workspace/` is the notebook as the game left it, read as file sizes);
- `notes_claims.json`: the claims extracted from the notes (`python -m noitabench notes-claims`,
  contracts section 21); without it the knowledge metrics are not measured;
- the world file pair: see `worldinfo.find_world_files`.

Nothing is simulated again: everything the evaluation says comes from these files.
"""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .frames import FrameReader
from .geometry import Sample, Track
from .knowledge.claims import NoteClaims, load_note_claims
from .worldinfo import WorldInfo, find_world_files, load_world

ITEM_KINDS = ("wand", "spell", "bottle", "bomb", "projectile", "player")
ITEM_PREFIXES = ("potion_", "barrel_")


def is_creature(kind: str) -> bool:
    """An enemy kind (anything in the entity list that is not the player or an item)."""
    return kind not in ITEM_KINDS and not kind.startswith(ITEM_PREFIXES)


@dataclass
class Life:
    """What the entity list says about one creature over the run.

    `path` holds `(frame, centre x, feet y, hp)` for every sample the creature was in."""

    id: int
    kind: str
    first_frame: int
    last_frame: int
    last_x: float
    last_y: float
    last_hp: float
    first_x: float = 0.0
    first_y: float = 0.0
    path: list[tuple[int, float, float, float]] = field(default_factory=list)


@dataclass(frozen=True)
class Item:
    """An item of the entity list (bottle, potion, wand, spell, barrel) where it was first seen:
    a scene's own items are told apart by that place."""

    id: int
    kind: str
    detail: str
    first_frame: int
    x: float  # centre at the first sample that listed it
    y: float


@dataclass
class Command:
    """One command of a decision, with the frame at which the decision was asked."""

    frame: int
    index: int
    name: str
    args: dict[str, Any]


class Events:
    """The event log, sorted by frame, with range queries."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self._frames = [r.get("frame", 0) for r in rows]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def between(self, f0: int, f1: int, *types: str) -> list[dict[str, Any]]:
        """Events with `f0 <= frame <= f1`, only of the given types if any are given."""
        lo = bisect_left(self._frames, f0)
        hi = bisect_right(self._frames, f1)
        out = self.rows[lo:hi]
        return [e for e in out if e.get("type") in types] if types else list(out)

    def of_type(self, *types: str) -> list[dict[str, Any]]:
        return [e for e in self.rows if e.get("type") in types]

    def player_damage(self, f0: int, f1: int, *sources: str) -> list[dict[str, Any]]:
        """`damage` events to the player in `[f0, f1]`, only from these sources if any."""
        return [
            e
            for e in self.between(f0, f1, "damage")
            if e.get("target") == "player" and (not sources or e.get("source") in sources)
        ]


@dataclass
class Decisions:
    """`decisions.jsonl`: empty if the run has none."""

    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return bool(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def commands(self, f0: int, f1: int, *names: str) -> list[Command]:
        """The commands of decisions asked in `[f0, f1]`, only these names if any are given."""
        out: list[Command] = []
        for row in self.rows:
            frame = as_int(row.get("frame"))
            if frame < f0 or frame > f1:
                continue
            commands = row.get("command")
            for c in commands if isinstance(commands, list) else []:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name", ""))
                if not names or name in names:
                    args = c.get("args")
                    out.append(
                        Command(
                            frame,
                            as_int(row.get("index")),
                            name,
                            args if isinstance(args, dict) else {},
                        )
                    )
        return out

    def cost_of(self, row: dict[str, Any]) -> int:
        """What a decision cost: its `cost` field, else 1 (older files have none)."""
        return as_int(row.get("cost"), 1)

    def cost_between(self, f0: int, f1: int) -> int:
        """Decisions charged for the decisions asked in `[f0, f1)` (the `cost` field, else 1)."""
        return sum(self.cost_of(r) for r in self.rows if f0 <= as_int(r.get("frame")) < f1)

    @property
    def total_cost(self) -> int:
        return sum(self.cost_of(r) for r in self.rows)

    def frame_at(self, counter: int) -> int | None:
        """The game frame while the decision counter stood at `counter` (nothing advances
        between decisions): the frame at which the first decision begun at or after that count
        was asked. None if no decision came after it."""
        for row in self.rows:
            if as_int(row.get("index")) - self.cost_of(row) >= counter:
                return as_int(row.get("frame"))
        return None


@dataclass
class RunData:
    root: Path
    run_id: str
    meta: dict[str, Any]
    world: WorldInfo
    track: Track
    events: Events
    decisions: Decisions
    lives: dict[int, Life]
    creature_frames: list[tuple[int, list[tuple[str, float, float, float]]]]
    transcript: list[dict[str, Any]]
    summary: dict[str, Any] | None
    frames: FrameReader
    source: str
    items: dict[int, Item] = field(default_factory=dict)
    workspace: dict[str, int] | None = None  # `workspace/` at the end: path -> characters
    note_claims: NoteClaims | None = None  # `notes_claims.json` (K2): the notes as claims
    _creature_times: list[int] | None = field(default=None, repr=False)

    @property
    def last_frame(self) -> int:
        return max(self.track.last_frame, as_int(self.meta.get("last_frame")))

    @property
    def player_died(self) -> bool:
        return bool(self.died_at() is not None)

    def died_at(self) -> int | None:
        for e in self.events.of_type("death"):
            if e.get("target") == "player":
                return int(e["frame"])
        last = self.track.samples[-1] if self.track.samples else None
        if last is not None and last.hp <= 0:
            return last.frame
        return None

    def creatures_around(
        self, frame: int, x: float, y: float, radius: float
    ) -> list[tuple[str, float, float]]:
        """The living creatures within `radius` of `(x, y)` at the sample at (or before) `frame`:
        `(kind, centre x, centre y)`."""
        if not self.creature_frames:
            return []
        if self._creature_times is None:
            self._creature_times = [f for f, _ in self.creature_frames]
        i = max(0, bisect_right(self._creature_times, frame) - 1)
        return [
            (kind, cx, cy)
            for kind, cx, cy, hp in self.creature_frames[i][1]
            if hp > 0 and (cx - x) ** 2 + (cy - y) ** 2 <= radius * radius
        ]


# ------------------------------------------------------------------------------------ loading
def as_int(value: Any, default: int = 0) -> int:
    """`int(value)`, or `default` for None, text that is not a number and the like (a damaged
    row of a run that was cut off must not stop the evaluation)."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line of a run that was cut off
            if isinstance(row, dict):
                yield row


def _json_file(path: Path) -> dict[str, Any] | None:
    """A JSON object read from `path`; None if the file is missing, damaged or not an object."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _event_rows(path: Path) -> list[dict[str, Any]]:
    """The events with a frame number, in frame order (equal frames keep their file order)."""
    rows = [r for r in _jsonl(path) if isinstance(r.get("frame"), (int, float))]
    return sorted(rows, key=lambda r: r["frame"])


def _centre(e: dict[str, Any]) -> tuple[float, float]:
    return as_float(e["x"]) + as_float(e.get("w")) / 2, as_float(e["y"]) + as_float(e.get("h")) / 2


def _track_creature(
    lives: dict[int, Life], e: dict[str, Any], kind: str, frame: int
) -> tuple[str, float, float, float]:
    """Add one sample of a creature to its `Life`; return `(kind, cx, cy, hp)` for the crowd."""
    eid = as_int(e.get("id"), -1)
    (cx, cy), hp = _centre(e), as_float(e.get("hp"))
    life = lives.get(eid)
    if life is None:
        life = lives[eid] = Life(eid, kind, frame, frame, cx, cy, hp, cx, cy)
    else:
        life.last_frame, life.last_x, life.last_y, life.last_hp = frame, cx, cy, hp
    life.path.append((frame, cx, as_float(e["y"]) + as_float(e.get("h")), hp))
    return kind, cx, cy, hp


def _read_entities(
    path: Path,
) -> tuple[
    list[Sample],
    dict[int, Life],
    list[tuple[int, list[tuple[str, float, float, float]]]],
    dict[int, Item],
]:
    samples: list[Sample] = []
    lives: dict[int, Life] = {}
    crowd: list[tuple[int, list[tuple[str, float, float, float]]]] = []
    items: dict[int, Item] = {}
    for row in _jsonl(path):
        frame = as_int(row.get("frame"))
        here: list[tuple[str, float, float, float]] = []
        entities = row.get("entities")
        for e in entities if isinstance(entities, list) else []:
            if not isinstance(e, dict) or "x" not in e or "y" not in e:
                continue
            kind = str(e.get("kind", ""))
            if kind == "player":
                samples.append(
                    Sample(
                        frame,
                        as_float(e["x"]),
                        as_float(e["y"]),
                        as_float(e.get("w"), 6.0),
                        as_float(e.get("h"), 16.0),
                        as_float(e.get("hp")),
                        as_float(e.get("hp_max"), 100.0),
                    )
                )
            elif is_creature(kind):
                here.append(_track_creature(lives, e, kind, frame))
            elif kind != "projectile" and as_int(e.get("id"), -1) not in items:
                cx, cy = _centre(e)
                eid = as_int(e.get("id"), -1)
                items[eid] = Item(eid, kind, str(e.get("detail") or ""), frame, cx, cy)
        crowd.append((frame, here))
    samples.sort(key=lambda s: s.frame)
    crowd.sort(key=lambda c: c[0])
    for life in lives.values():
        life.path.sort()
    return samples, lives, crowd, items


def _workspace(root: Path) -> dict[str, int] | None:
    """The notebook as the game left it (`<run>/workspace/`): relative path -> characters.

    None if the run folder has no `workspace/` (the scripted bot, the play server)."""
    folder = root / "workspace"
    if not folder.is_dir():
        return None
    out: dict[str, int] = {}
    for f in sorted(folder.rglob("*")):
        if f.is_file() and not f.is_symlink() and not f.name.startswith("."):
            rel = f.relative_to(folder).as_posix()
            if rel.startswith("."):
                continue  # `.libs/` and the like: not notes
            try:
                with f.open(encoding="utf-8", errors="replace", newline="") as handle:
                    out[rel] = len(handle.read())
            except OSError:
                continue
    return out


def _source(root: Path, meta: dict[str, Any]) -> str:
    notes = str(meta.get("notes", "")).lower()
    if "human play" in notes:
        return "human"
    if (root / "summary.json").exists() or (root / "transcript.jsonl").exists():
        return "agent"
    if "scripted" in notes or (root / "descend.json").exists() or (root / "bot_log.jsonl").exists():
        return "bot"
    return "unknown"


def load_run(
    run_dir: Path | str, world_files: tuple[Path | str, Path | str] | None = None
) -> RunData:
    """Read the run folder `run_dir`. Raises `FileNotFoundError`/`ValueError` with the path.

    Damaged optional files (a cut-off `events.jsonl`, an unreadable `summary.json`, a torn
    `frames.bin`) are read as far as they go; a missing or unreadable `meta.json`, entities file
    or world file is an error that names the file."""
    root = Path(run_dir)
    meta_path = root / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"{root}: no meta.json (not a recording folder)")
    meta = _json_file(meta_path)
    if meta is None:
        raise ValueError(f"{meta_path}: not a readable JSON object")
    explicit = None if world_files is None else (Path(world_files[0]), Path(world_files[1]))
    png, js = find_world_files(root, explicit, seed=_as_int(meta.get("seed")))
    world = load_world(png, js)
    samples, lives, crowd, items = _read_entities(root / "entities.jsonl")
    if not samples:
        raise ValueError(f"{root}: entities.jsonl is missing or has no player samples")
    size = None
    dims = meta.get("world")
    if isinstance(dims, dict) and "width" in dims and "height" in dims:
        size = (as_int(dims["width"]), as_int(dims["height"]))
    return RunData(
        root=root,
        run_id=str(meta.get("run_id") or root.name),
        meta=meta,
        world=world,
        track=Track(samples),
        events=Events(_event_rows(root / "events.jsonl")),
        decisions=Decisions(list(_jsonl(root / "decisions.jsonl"))),
        lives=lives,
        creature_frames=crowd,
        transcript=list(_jsonl(root / "transcript.jsonl")),
        summary=_json_file(root / "summary.json"),
        frames=FrameReader(root / "frames.bin", world.grid, size or (world.width, world.height)),
        source=_source(root, meta),
        items=items,
        workspace=_workspace(root),
        note_claims=load_note_claims(root / "notes_claims.json"),
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
