"""From the engine's log to the short facts an agent is told."""

from __future__ import annotations

from typing import Any

from noitabench.agent.events import EventCollector, where
from noitabench.agent.vocab import EVENT_TYPES

PLAYER = {"x": 98, "y": 94, "w": 4, "h": 7, "wands": [{"id": 2}, {"id": 3}]}  # stands at (100, 100)


def feed(
    raw: list[dict[str, Any]], tick: int = 1, visible: set[int] | None = None
) -> EventCollector:
    c = EventCollector()
    c.add_tick(tick, raw, PLAYER, visible or set())
    return c


def ev(type_: str, frame: int = 5, **fields: Any) -> dict[str, Any]:
    return {"frame": frame, "type": type_, **fields}


def test_where_uses_words_not_coordinates() -> None:
    assert where(40, 0) == "40 px right"
    assert where(-40, 12) == "40 px left, 12 px down"
    assert where(0, -9) == "9 px up"
    assert where(2, -3) == "right next to you"


def test_only_whitelisted_events_get_through_and_reactions_never_do() -> None:
    raw = [
        ev("reaction", id="r04", x=100, y=100, bx=101, by=100),
        ev("overflow", dropped=3),
        ev("teleport", x=1, y=2),
        ev("death", target="longleg", id=9, source="hit", x=110, y=100),
    ]
    events, omitted = feed(raw, visible={9}).summary(16)
    assert [e["type"] for e in events] == ["death"] and omitted == 0
    assert "reaction" not in EVENT_TYPES and "overflow" not in EVENT_TYPES


def test_positions_become_offsets_from_the_player() -> None:
    (e,), _ = feed([ev("explosion", x=140, y=88, radius=15, destroyed=3)]).summary(16)
    assert (e["dx"], e["dy"]) == (40, -12) and e[
        "text"
    ] == "Explosion (radius 15) 40 px right, 12 px up."
    assert "x" not in e and "y" not in e  # world coordinates are not forwarded


def test_events_out_of_range_or_about_unseen_creatures_are_not_noticed() -> None:
    raw = [
        ev("explosion", x=400, y=100, radius=15, destroyed=1),
        ev("damage", target="longleg", id=7, amount=2.0, source="melee", hp=1.0, x=100, y=400),
        ev("status", target="longleg", id=8, status="on_fire", active=1),
        ev("enemy_attack", enemy="shotgunner", id=8, projectiles=3),
        ev("status", target="longleg", id=9, status="wet", active=1),
    ]
    events, _ = feed(raw, visible={9}).summary(16)
    assert [(e["type"], e.get("id")) for e in events] == [("status", 9)]


def test_repeated_events_merge_into_one_line_with_a_count() -> None:
    raw = [ev("ignite", frame=f, x=130 + f, y=100, material="oil", by="fire") for f in range(5)]
    raw += [
        ev("cast", frame=f, wand=2, spells="LIGHT_BULLET", projectiles=1, mana=5.0)
        for f in range(3)
    ]
    raw += [
        ev("damage", target="player", id=1, amount=1.5, source="fire", hp=90.0, x=100, y=100),
        ev("damage", target="player", id=1, amount=1.5, source="fire", hp=88.5, x=100, y=100),
    ]
    events, _ = feed(raw).summary(16)
    by_type = {e["type"]: e for e in events}
    assert by_type["ignite"]["count"] == 5 and by_type["ignite"]["text"].endswith("x5.")
    assert by_type["cast"]["count"] == 3 and by_type["cast"]["mana"] == 15.0
    assert by_type["cast"]["wand"] == 0  # the index in the agent's wand list, not an engine id
    assert by_type["damage"]["amount"] == 3.0 and by_type["damage"]["hp"] == 88.5


def test_how_much_health_another_creature_has_left_is_not_in_the_events() -> None:
    """Health of others comes from `inspect` (a decision), so no event may carry it."""
    raw = [
        ev("damage", target="longleg", id=9, amount=1.0, source="melee", hp=1.8, x=110, y=100),
        ev("damage", target="player", id=1, amount=1.0, source="fire", hp=97.0, x=100, y=100),
    ]
    events, _ = feed(raw, visible={9}).summary(16)
    others = next(e for e in events if e["target"] == "longleg")
    assert "hp" not in others and "HP" not in others["text"]
    assert others["text"] == "longleg #9 took 1.0 damage (melee)."
    you = next(e for e in events if e["target"] == "player")
    assert you["hp"] == 97.0 and you["text"].endswith("; HP 97.0.")


def test_damage_from_a_shot_is_told_by_the_hit_not_twice() -> None:
    raw = [
        ev(
            "hit",
            projectile="LIGHT_BULLET",
            target="longleg",
            id=9,
            damage=3.0,
            crit=0,
            x=110,
            y=100,
        ),
        ev("damage", target="longleg", id=9, amount=3.0, source="hit", hp=0.0, x=110, y=100),
    ]
    events, _ = feed(raw, visible={9}).summary(16)
    assert [e["type"] for e in events] == ["hit"]


def test_a_merge_across_ticks_keeps_the_first_tick_and_marks_the_last() -> None:
    c = EventCollector()
    c.add_tick(1, [ev("ignite", x=120, y=100, material="oil", by="fire")], PLAYER, set())
    c.add_tick(4, [ev("ignite", x=125, y=100, material="oil", by="fire")], PLAYER, set())
    (e,), _ = c.summary(16)
    assert (e["tick"], e["last_tick"], e["count"]) == (1, 4, 2)


def test_when_there_are_too_many_the_ones_about_the_player_win() -> None:
    raw = [ev("ignite", x=100 + i, y=100, material=f"m{i}", by="fire") for i in range(12)]
    raw += [
        ev("explosion", x=100 + i, y=100, radius=5 + i, destroyed=1) for i in range(10)
    ]  # 22 different world events
    raw += [
        ev("pickup", item="spell", detail="BOMB", id=4),
        ev("status", target="player", id=1, status="wet", active=1),
    ]
    events, omitted = feed(raw).summary(16)
    assert len(events) == 16 and omitted == 24 - 16
    types = [e["type"] for e in events]
    assert "pickup" in types and "status" in types
    assert [e["frame"] for e in events] == sorted(e["frame"] for e in events)  # still in time order


def test_internal_fields_do_not_leak_into_the_summary() -> None:
    (e,), _ = feed([ev("kick", x=104, y=100, hits=1)]).summary(16)
    assert not any(k.startswith("_") for k in e)
    assert set(e) == {"tick", "frame", "type", "hits", "text"}


def test_every_text_is_a_plain_sentence() -> None:
    raw = [
        ev("cast", wand=3, spells="BOMB+DAMAGE", projectiles=1, mana=30.0),
        ev("hit", projectile="BOMB", target="player", id=1, damage=5.0, crit=1, x=100, y=100),
        ev("death", target="player", id=1, source="fire", x=100, y=100),
        ev("status", target="player", id=1, status="on_fire", active=0),
        ev("pickup_failed", item="wand"),
        ev("kick", x=104, y=100, hits=0),
        ev("throw", material="oil", cells=100),
        ev("shatter", material="oil", cells=100, x=120, y=100),
        ev("barrel_break", kind="barrel_oil", id=5, x=120, y=100, burning=1),
        ev("extinguish", x=120, y=100, material="oil"),
        ev("edit_wand", wand=3),
        ev("error", message="The wand jammed."),
    ]
    events, _ = feed(raw, visible={5}).summary(16)
    texts = [e["text"] for e in events]
    assert all(t and t[0].isupper() and t.endswith(".") for t in texts), texts
    assert "You died." in texts and "You are no longer on_fire." in texts
