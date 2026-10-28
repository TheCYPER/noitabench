"""What the bot reads from `content/spells.json` about explosions.

A spell's own explosion (`projectile.explosion`: radius, `max_durability`) and what a modifier adds
to the explosion of the spell it modifies (`shot.explosion_radius`, `shot.explosion_durability`:
the largest bonus counts, copies do not stack). A field the content does not have (yet) counts as
zero. `explosion_options` pairs every projectile in hand with the modifier that helps it most.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from .terrain import CONTENT

DEFAULT_FUSE = 180  # frames a thrown bomb burns when the content does not say


@dataclass(frozen=True)
class SpellInfo:
    """What the planner needs to know about one spell."""

    key: str
    kind: str
    mana: float
    max_uses: int | None
    body: str = ""  # projectile, thrown_body, static, material_particle
    durability: int | None = None  # hardest durability its own explosion removes
    radius: int = 0  # radius of its own explosion
    fuse: int = DEFAULT_FUSE  # frames until a thrown body goes off
    bonus_durability: int = 0  # added to the explosion of the spell it modifies
    bonus_radius: float = 0.0


def load_spells(path: Path | None = None) -> dict[str, SpellInfo]:
    """The explosion numbers of every spell in `content/spells.json`."""
    data = json.loads((path or CONTENT / "spells.json").read_text(encoding="utf-8"))
    out: dict[str, SpellInfo] = {}
    for s in data["spells"]:
        projectile = s.get("projectile") or {}
        explosion = projectile.get("explosion")
        shot = s.get("shot") or {}
        out[str(s["key"])] = SpellInfo(
            key=str(s["key"]),
            kind=str(s["type"]),
            mana=float(s["mana"]),
            max_uses=None if s.get("max_uses") is None else int(s["max_uses"]),
            body=str(projectile.get("body") or ""),
            durability=None if explosion is None else int(explosion["max_durability"]),
            radius=0 if explosion is None else int(explosion["radius"]),
            fuse=int(projectile.get("lifetime") or DEFAULT_FUSE),
            bonus_durability=int(shot.get("explosion_durability") or 0),
            bonus_radius=float(shot.get("explosion_radius") or 0.0),
        )
    return out


def explosion_options(
    held: Iterable[str], infos: dict[str, SpellInfo]
) -> list[tuple[tuple[str, ...], int, int]]:
    """Every projectile in hand with the modifier that helps it most: `(spells, durability,
    radius)`, the spells in wand order. A spell with an explosion alone is an option too."""
    known = [infos[k] for k in dict.fromkeys(held) if k in infos]
    projectiles = [
        s
        for s in known
        if s.kind in ("projectile", "static_projectile") and s.durability is not None
    ]
    helpers = [s for s in known if s.kind == "modifier" and s.bonus_durability > 0]
    options: list[tuple[tuple[str, ...], int, int]] = []
    for p, m in product(projectiles, [None, *helpers]):
        assert p.durability is not None
        bonus = 0 if m is None else m.bonus_durability
        grown = 0 if m is None else round(m.bonus_radius)
        spells = (p.key,) if m is None else (m.key, p.key)
        options.append((spells, p.durability + bonus, p.radius + max(0, grown)))
    return options


def best_reach(held: Iterable[str], path: Path | None = None) -> int | None:
    """The hardest durability the spells in hand can remove, or None if none has an explosion."""
    options = explosion_options(held, load_spells(path))
    return max((d for _, d, _ in options), default=None)
