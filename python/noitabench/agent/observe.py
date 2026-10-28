"""The three observation channels, each of which can be switched off:

- `state`: the structured text channel - position, health, conditions, wands, spells, bottles
  (with their contents), what is in view (kind, place and size of each thing, nothing else);
- `map`: the ASCII map around the player with a legend of material names;
- `screenshot`: a PNG of the cells around the player.

All three are built from the player, the entity list and the grid window around the player.
They never use markers, seeds or rules (`visibility.py`).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .aim import Aim
from .asciimap import MapStyle, render_map
from .content import Content
from .engine import Engine, hit_center, position_of, public_kind
from .inspecting import wand_info
from .screenshot import render_png
from .vocab import FPS, GOAL, SHOT_HALF


@dataclass(frozen=True)
class ViewConfig:
    """Which channels are on, and how big they are."""

    text: bool = True
    ascii: bool = True
    screenshot: bool = False
    ascii_cols: int = 64
    ascii_rows: int = 32
    ascii_cell: int = 4
    shot_scale: int = 1
    entity_cap: int = 16
    event_cap: int = 16
    goal: str = GOAL

    def __post_init__(self) -> None:
        if self.ascii_cell < 1 or self.ascii_cols < 1 or self.ascii_rows < 1:
            raise ValueError("the ASCII map needs positive sizes")
        if self.shot_scale < 1:
            raise ValueError("shot_scale must be at least 1")

    @property
    def view_half(self) -> tuple[int, int]:
        """How far the player sees, in cells: the extent of the ASCII map around the player
        (default 128 by 64), whether or not the map channel is on."""
        return self.ascii_cols * self.ascii_cell // 2, self.ascii_rows * self.ascii_cell // 2


def _round(v: float, digits: int = 1) -> float:
    return round(float(v), digits)


class Observer:
    """Builds the channels of an observation."""

    def __init__(self, engine: Engine, content: Content, view: ViewConfig) -> None:
        self.engine = engine
        self.content = content
        self.view = view
        self.style = MapStyle.build(content)

    # -- channels ---------------------------------------------------------------------------------

    def channels(
        self,
        player: dict[str, Any],
        visible: list[dict[str, Any]],
        aim: Aim,
        can_edit_wands: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        shown = [{**v, "kind": public_kind(v["kind"])} for v in visible]
        if self.view.text:
            out["state"] = self.state(player, shown, aim, can_edit_wands)
        cx, cy = (int(v) for v in hit_center(player))
        me = _player_entity(player)
        if self.view.ascii:
            out["map"] = self.ascii_map(cx, cy, [me, *shown])
        if self.view.screenshot:
            out["screenshot"] = self.screenshot(cx, cy, [me, *shown])
        return out

    def state(
        self,
        p: dict[str, Any],
        visible: list[dict[str, Any]],
        aim: Aim,
        can_edit_wands: bool,
    ) -> dict[str, Any]:
        x, y = position_of(p)
        wands = [
            wand_info(self.content, i, w, i == p["active_wand"], numbers=False)
            for i, w in enumerate(p["wands"])
        ]
        for w in wands:
            w.pop("what")
        nearby, omitted = self._nearby(visible, aim)
        state: dict[str, Any] = {
            "position": {"x": x, "y": y},
            "hp": _round(p["hp"]),
            "hp_max": _round(p["hp_max"]),
            "levitation": _round(p["fly"], 2),
            "breath": _round(p["breath"], 2),
            "on_ground": bool(p["on_ground"]),
            "facing": "right" if p["facing"] >= 0 else "left",
            "velocity": {"x": _round(p["vx"]), "y": _round(p["vy"])},
            "aim": {
                "degrees": _round(p["aim"]),
                "follows": aim.entity if aim.mode == "entity" else None,
            },
            "statuses": {k: _round(v / FPS) for k, v in sorted(p["statuses"].items())},
            "active_wand": p["active_wand"],
            "wands": wands,
            "spells": [
                {"index": i, "spell": s["spell"], "uses": s["uses"]}
                for i, s in enumerate(p["spells"])
            ],
            "bottles": [
                {
                    "index": i,
                    "material": b["material"] or None,
                    "amount": b["amount"],
                    "capacity": self.content.bottle_capacity,
                    "active": i == p["active_bottle"],
                    "contents": [dict(part) for part in b["contents"]],
                }
                for i, b in enumerate(p["bottles"])
            ],
            "nearby": nearby,
            "can_edit_wands": can_edit_wands,
            "goal": self.view.goal,
        }
        if omitted:
            state["nearby_omitted"] = omitted
        return state

    def _nearby(self, visible: list[dict[str, Any]], aim: Aim) -> tuple[list[dict[str, Any]], int]:
        cap = self.view.entity_cap
        solid = [e for e in visible if e["kind"] != "projectile"]
        shots = [e for e in visible if e["kind"] == "projectile"]
        chosen = (solid + shots)[:cap]
        chosen.sort(key=lambda e: (e["dist"], e["id"]))
        return [self._entity(e, aim) for e in chosen], len(visible) - len(chosen)

    def _entity(self, e: dict[str, Any], aim: Aim) -> dict[str, Any]:
        """What can be seen of something in view: what it is and where, nothing more. Its
        contents, spell, health and conditions come only from `inspect`."""
        out: dict[str, Any] = {
            "id": e["id"],
            "kind": e["kind"],
            "x": e["x"],
            "y": e["y"],
            "w": e["w"],
            "h": e["h"],
            "dx": e["dx"],
            "dy": e["dy"],
        }
        if self.engine.hostile(e):
            out["hostile"] = True
        if aim.mode == "entity" and aim.entity == e["id"]:
            out["aimed"] = True
        return out

    def ascii_map(self, cx: int, cy: int, entities: list[dict[str, Any]]) -> dict[str, Any]:
        v = self.view
        w, h = v.ascii_cols * v.ascii_cell, v.ascii_rows * v.ascii_cell
        origin = (cx - w // 2, cy - h // 2)
        window = self.engine.window(origin[0], origin[1], w, h)
        fire = self.engine.burning(origin[0], origin[1], w, h)
        rows, legend = render_map(window, self.style, v.ascii_cell, entities, origin, fire)
        return {
            "cell": v.ascii_cell,
            "origin": {"x": origin[0], "y": origin[1]},
            "columns": v.ascii_cols,
            "rows": rows,
            "legend": legend,
        }

    def screenshot(self, cx: int, cy: int, entities: list[dict[str, Any]]) -> dict[str, Any]:
        w, h = 2 * SHOT_HALF[0], 2 * SHOT_HALF[1]
        origin = (cx - w // 2, cy - h // 2)
        window = self.engine.window(origin[0], origin[1], w, h)
        fire = self.engine.burning(origin[0], origin[1], w, h)
        png = render_png(
            window,
            self.content,
            origin,
            entities,
            self.engine.enemy_kinds,
            self.view.shot_scale,
            fire,
        )
        return {
            "format": "png",
            "width": w * self.view.shot_scale,
            "height": h * self.view.shot_scale,
            "origin": {"x": origin[0], "y": origin[1]},
            "data_base64": base64.b64encode(png).decode("ascii"),
        }


def _player_entity(p: dict[str, Any]) -> dict[str, Any]:
    x, y, w, h = p["hit"]
    return {"kind": "player", "x": x, "y": y, "w": w, "h": h, "cx": x + w / 2, "cy": y + h / 2}
