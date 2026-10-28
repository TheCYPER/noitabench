"""The ASCII map: the world around the player, one character per `cell`x`cell` block.

A character stands for a material by name only (the legend lists names, never properties). When
a block holds several materials the most visible kind wins - fire, then liquid, powder, gas,
terrain, air (OBS-R02) - and the commonest material of that kind gives the character. A block with
a burning cell (a cell that is on fire, whatever it is made of) shows `!`, "on fire", unless the
block shows flames anyway. Creatures and items overwrite the block of their centre. `?` is
outside the world.

Characters are fixed by the content: a preferred table below, then a deterministic pool for
materials added later, so the same `materials.json` always gives the same legend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .content import Content
from .engine import OUTSIDE

PREFERRED = {
    "air": ".",
    "steam": "'",
    "flammable_gas": '"',
    "fire": "^",
    "water": "~",
    "blood": "r",
    "oil": "o",
    "whiskey": "y",
    "acid": "a",
    "lava": "l",
    "toxic_sludge": "t",
    "sand": "s",
    "coal": "c",
    "gunpowder": "g",
    "ground": ":",
    "rock": "#",
    "wood": "w",
    "brick": "=",
    "potion_heal": "h",
    "potion_mana": "m",
    "potion_haste": "z",
    "potion_lively": "v",
}
ENTITY_CHARS = {"player": "@", "longleg": "L", "shotgunner": "S", "firemage_weak": "F"}
ITEM_CHARS = {"wand": "/", "spell": "$", "bottle": "U", "bomb": "Q", "projectile": "*"}
UNKNOWN_ENTITY = "&"
OUTSIDE_CHAR = "?"
BURNING_CHAR = "!"
BURNING_NAME = "on fire"
_POOL = "bdefijknpqux" + "0123456789" + "%+-_|<>{}[]()!@\\"
KIND_RANK = {"air": 0, "static": 1, "gas": 2, "powder": 3, "liquid": 4, "fire": 5}


def entity_char(kind: str) -> str:
    if kind in ENTITY_CHARS:
        return ENTITY_CHARS[kind]
    if kind in ITEM_CHARS:
        return ITEM_CHARS[kind]
    if kind.startswith("potion_"):
        return "P"
    if kind.startswith("barrel_"):
        return "B"
    return "E" if kind else UNKNOWN_ENTITY


@dataclass(frozen=True)
class MapStyle:
    """Material index -> character, fixed for a content set."""

    chars: tuple[str, ...]
    ranks: tuple[int, ...]
    names: tuple[str, ...]

    @classmethod
    def build(cls, content: Content) -> MapStyle:
        reserved = {
            *ENTITY_CHARS.values(),
            *ITEM_CHARS.values(),
            "P",
            "B",
            "E",
            UNKNOWN_ENTITY,
            OUTSIDE_CHAR,
            BURNING_CHAR,
            " ",
        }
        used = {c for k, c in PREFERRED.items() if k in content.material_keys}
        pool = iter(c for c in _POOL if c not in reserved and c not in used)
        chars = []
        for key in content.material_keys:
            if key in PREFERRED:
                chars.append(PREFERRED[key])
                continue
            try:
                chars.append(next(pool))
            except StopIteration as err:  # pragma: no cover - 40+ new materials
                raise ValueError("more materials than characters for the map legend") from err
        ranks = tuple(KIND_RANK[k] for k in content.material_kinds)
        return cls(tuple(chars), ranks, content.material_keys)

    def legend(self) -> dict[str, str]:
        """Every character of the map and what it stands for."""
        out = {c: n for c, n in zip(self.chars, self.names, strict=True)}
        out[OUTSIDE_CHAR] = "outside the world"
        out[BURNING_CHAR] = BURNING_NAME
        return out


def render_map(
    window: np.ndarray,
    style: MapStyle,
    cell: int,
    entities: list[dict[str, Any]],
    origin: tuple[int, int],
    burning: np.ndarray | None = None,
) -> tuple[list[str], dict[str, str]]:
    """The map rows for a material window (height and width multiples of `cell`) whose top-left
    world cell is `origin`, and the legend of the characters used. `entities` need `kind`, `cx`,
    `cy` (centre) and are drawn on the block they stand in. `burning` (same shape as `window`,
    0 or 1) marks the cells that are on fire."""
    h, w = window.shape
    rows, cols = h // cell, w // cell
    n = len(style.chars)
    rank = np.array([*style.ranks, -1], dtype=np.int16)  # the last entry: outside
    idx = np.where(window == OUTSIDE, n, window).astype(np.int64)
    blocks = (
        idx.reshape(rows, cell, cols, cell).transpose(0, 2, 1, 3).reshape(rows * cols, cell * cell)
    )
    cell_rank = rank[blocks]
    best = cell_rank.max(axis=1, keepdims=True)
    counts = np.zeros((rows * cols, n + 1), dtype=np.int32)
    block_ids = np.repeat(np.arange(rows * cols), cell * cell).reshape(blocks.shape)
    np.add.at(counts, (block_ids, blocks), (cell_rank == best).astype(np.int32))
    winner = counts.argmax(axis=1)
    char_table = np.array([*style.chars, OUTSIDE_CHAR])
    grid = char_table[winner].reshape(rows, cols)
    if burning is not None:
        grid = _mark_burning(grid, best.reshape(rows, cols), burning, cell)
    used = {str(c) for c in np.unique(grid)}
    legend = {c: name for c, name in style.legend().items() if c in used}
    for e in entities:
        col, row = int((e["cx"] - origin[0]) // cell), int((e["cy"] - origin[1]) // cell)
        if 0 <= col < cols and 0 <= row < rows:
            ch = entity_char(e["kind"])
            grid[row, col] = ch
            legend[ch] = _entity_name(e["kind"])
    return ["".join(r) for r in grid], legend


def _entity_name(kind: str) -> str:
    if kind == "player":
        return "you"
    if kind.startswith("potion_"):
        return "potion"
    if kind.startswith("barrel_"):
        return "barrel"
    return kind if kind else "creature or item"


def _mark_burning(
    grid: np.ndarray, best_rank: np.ndarray, burning: np.ndarray, cell: int
) -> np.ndarray:
    """`grid` with `BURNING_CHAR` in every block that holds a burning cell and does not already
    show flames (`best_rank` is the rank of the most visible kind of each block)."""
    rows, cols = grid.shape
    blocks = burning.reshape(rows, cell, cols, cell).any(axis=(1, 3))
    on_fire = blocks & (best_rank < KIND_RANK["fire"])
    return np.where(on_fire, BURNING_CHAR, grid)
