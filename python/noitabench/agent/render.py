"""The observation as the text a model reads.

`render_text` works on the answer dict alone (the one `AgentSession.decide` returns and the
protocol writes), so a recording can be shown again without the game. The screenshot is an image
and is not part of the text; a note says it is attached.
"""

from __future__ import annotations

import json
from typing import Any


def _stop_line(stop: dict[str, Any]) -> str:
    reason = stop["reason"]
    detail = f" ({stop['detail']})" if stop.get("detail") else ""
    run = ""
    if stop.get("frames"):
        run = f" after {stop['ticks']} tick(s), {stop['frames']} frames"
    msg = f" {stop['message']}" if stop.get("message") else ""
    return f"Stopped: {reason}{detail}{run}.{msg}"


def _result_line(r: dict[str, Any]) -> str:
    head = f"  {r['command']}"
    if not r["ok"]:
        return f"{head}: FAILED ({r['code']}) {r['message']}"
    parts = []
    stop = r.get("stop")
    if stop:
        parts.append(stop["reason"] + (f" ({stop['detail']})" if stop.get("detail") else ""))
    if "result" in r:
        parts.append(json.dumps(r["result"], separators=(",", ":"), ensure_ascii=False))
    return f"{head}: " + (" ".join(parts) or "ok")


def _wand_line(w: dict[str, Any]) -> str:
    slots = ", ".join(
        f"[{s['slot']}] {s['spell'] or '-'}"
        + (f" ({s['uses']} uses)" if s.get("uses") is not None else "")
        for s in w["slots"]
    )
    mark = "*" if w["active"] else " "
    return (
        f"  {w['index']}{mark} mana {w['mana']:g}/{w['mana_max']:g} (+{w['mana_per_second']:g}/s), "
        f"cooldown {w['cooldown']} | cast delay {w['cast_delay']}, recharge {w['recharge']}, "
        f"{w['spells_per_cast']} spell(s)/cast, capacity {w['capacity']} | {slots}"
    )


def _entity_line(e: dict[str, Any]) -> str:
    bits = [f"#{e['id']} {e['kind']}"]
    bits.append(f"at ({e['x']},{e['y']}) {e['dx']:+d},{e['dy']:+d}")
    if e.get("hostile"):
        bits.append("[hostile]")
    if e.get("aimed"):
        bits.append("[aimed at]")
    return "  " + " ".join(bits)


def _bottle_line(b: dict[str, Any]) -> str:
    held = ", ".join(f"{part['material']} {part['amount']}" for part in b["contents"])
    return f"  [{b['index']}]{'*' if b['active'] else ''} {held or 'empty'} ({b['amount']}/{b['capacity']})"


def _state_lines(s: dict[str, Any]) -> list[str]:
    pos = s["position"]
    lines = [
        f"Position x={pos['x']} y={pos['y']} | HP {s['hp']:g}/{s['hp_max']:g} | "
        f"levitation {round(100 * s['levitation'])}% | breath {round(100 * s['breath'])}% | "
        f"{'on ground' if s['on_ground'] else 'in the air'} | facing {s['facing']} | "
        f"aim {s['aim']['degrees']:g} deg"
        + (f" (following #{s['aim']['follows']})" if s["aim"]["follows"] is not None else ""),
    ]
    if s["statuses"]:
        lines.append("Conditions: " + ", ".join(f"{k} {v:g}s" for k, v in s["statuses"].items()))
    lines.append("Wands (* held):")
    lines += [_wand_line(w) for w in s["wands"]] or ["  none"]
    if s["spells"]:
        lines.append(
            "Carried spells: "
            + ", ".join(
                f"[{c['index']}] {c['spell']}"
                + (f" ({c['uses']} uses)" if c["uses"] is not None else "")
                for c in s["spells"]
            )
        )
    if s["bottles"]:
        lines.append("Bottles (* held):")
        lines += [_bottle_line(b) for b in s["bottles"]]
    if s["can_edit_wands"]:
        lines.append("You can rearrange your wands here.")
    lines.append("In view (nearest first):")
    lines += [_entity_line(e) for e in s["nearby"]] or ["  nothing"]
    if s.get("nearby_omitted"):
        lines.append(f"  ... and {s['nearby_omitted']} more")
    lines.append(f"Goal: {s['goal']}")
    return lines


def _map_lines(m: dict[str, Any]) -> list[str]:
    cell, ox, oy = m["cell"], m["origin"]["x"], m["origin"]["y"]
    cols = m["columns"]
    ruler = [" "] * cols
    for c in range(0, cols, 8):
        label = str(ox + c * cell)
        for i, ch in enumerate(label):
            if c + i < cols:
                ruler[c + i] = ch
    lines = [f"Map: one character = {cell}x{cell} cells; the top-left corner is x={ox}, y={oy}."]
    lines.append("      x: " + "".join(ruler))
    for r, row in enumerate(m["rows"]):
        y = oy + r * cell
        label = f"{y:>5}  " if r % 4 == 0 else "       "
        lines.append(label + row)
    lines.append("Legend: " + "  ".join(f"{c} {n}" for c, n in sorted(m["legend"].items())))
    return lines


def render_text(response: dict[str, Any]) -> str:
    """The whole answer as text."""
    head = (
        f"Decision {response['decision']} (frame {response['frame']}, "
        f"{response['seconds']:g} s). {response['decisions_left']} decisions left."
    )
    lines = [head]
    if response.get("over"):
        lines.append(f"The game is over: {response['over']}.")
    lines.append(_stop_line(response["stop"]))
    if response["results"]:
        lines.append("Commands:")
        lines += [_result_line(r) for r in response["results"]]
    if response["events"]:
        lines.append("Events:")
        lines += [f"  tick {e['tick']}: {e['text']}" for e in response["events"]]
        if response.get("events_omitted"):
            lines.append(f"  ... {response['events_omitted']} more events not shown")
    obs = response.get("observation", {})
    if "state" in obs:
        lines += _state_lines(obs["state"])
    if "map" in obs:
        lines += _map_lines(obs["map"])
    if "screenshot" in obs:
        shot = obs["screenshot"]
        lines.append(f"Screenshot attached ({shot['width']}x{shot['height']} PNG).")
    return "\n".join(lines)
