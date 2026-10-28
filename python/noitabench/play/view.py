"""The picture the play page draws: the cells around the player, fire, and what can be seen.

A human sees what the screenshot channel of an agent shows, and no more: the cells in a
256 x 192 window around the player (`SHOT_HALF`), and the creatures and items inside the agent's
view range with a clear line of sight (`Engine.visible`). Nothing about them beyond kind, place
and size: health, contents and statuses come from `inspect`, which costs a decision exactly as it
does for an agent. Cells outside the world are `OUTSIDE` (255). Fire is a separate bit mask
because the cell grid of a recording has no burning state.

The view is plain JSON: `materials` is `width * height` bytes (row-major material indices),
`burning` the same cells as a packed bit mask (`numpy.packbits`: the first cell is the top bit of
the first byte), both base64. `legend` lists the materials the page may *name* as `{index, name}`
pairs: exactly those the ASCII map's legend names for an agent (its extent, its rule for which
material a block shows). The picture itself holds more cells and more kinds of cell; the names do
not go beyond the map. This is the only place the page learns a material's name (the materials
file it loads has colours only), apart from the results of `inspect`.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import numpy as np

from noitabench.agent.engine import OUTSIDE, hit_center, position_of, public_kind
from noitabench.agent.session import AgentSession
from noitabench.agent.visibility import check_clean
from noitabench.agent.vocab import SHOT_HALF
from noitabench.game import Game


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def build_view(
    session: AgentSession,
    game: Game | None = None,
    half: tuple[int, int] = SHOT_HALF,
    names: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """The window of `2 * half[0]` by `2 * half[1]` cells centred on the player, and what is in
    view. Raises `AssertionError` if it holds a field an agent may not see (a bug). Everything,
    fire included, is read through the session's engine like an agent's observation; `game` is
    not used any more and is only kept so that existing callers still work. `names` gives the
    display name of a material index for the legend (default: the name an agent's legend uses)."""
    engine = session.engine
    p = engine.player()
    cx, cy = (int(v) for v in hit_center(p))
    w, h = 2 * half[0], 2 * half[1]
    ox, oy = cx - w // 2, cy - h // 2
    materials = engine.window(ox, oy, w, h)
    fire = engine.burning(ox, oy, w, h).reshape(-1)
    hx, hy, hw, hh = p["hit"]
    x, y = position_of(p)
    view = {
        "frame": engine.frame,
        "origin": {"x": ox, "y": oy},
        "width": w,
        "height": h,
        "outside": OUTSIDE,
        "materials": _b64(materials.tobytes()),
        "burning": _b64(np.packbits(fire).tobytes()),
        "legend": _named_materials(session, cx, cy, names or {}),
        "player": {"x": hx, "y": hy, "w": hw, "h": hh, "position": {"x": x, "y": y}},
        "entities": [_entity(session, e) for e in engine.visible(p, engine.entities())],
    }
    if session.config.paranoid:
        check_clean(view)
    return view


def _named_materials(
    session: AgentSession, cx: int, cy: int, names: Mapping[int, str]
) -> list[dict[str, Any]]:
    """`{index, name}` for each material the ASCII legend of an agent names around `(cx, cy)`,
    in index order; the name is `names[index]` if given, else the agent's own."""
    observer = session.observer
    named = set(observer.ascii_map(cx, cy, [])["legend"].values())
    return [
        {"index": i, "name": names.get(i, key)}
        for i, key in enumerate(observer.style.names)
        if key in named
    ]


def _entity(session: AgentSession, e: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": e["id"],
        "kind": public_kind(e["kind"]),
        "x": e["x"],
        "y": e["y"],
        "w": e["w"],
        "h": e["h"],
    }
    if session.engine.hostile(e):
        out["hostile"] = True
    if session.aim.mode == "entity" and session.aim.entity == e["id"]:
        out["aimed"] = True
    return out
