"""The three observation channels and the text that renders them."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from agent_worlds import FLOOR, GROUND, START_X, WALL_X
from noitabench.agent import AgentSession, render_text
from noitabench.agent.asciimap import BURNING_CHAR, MapStyle
from noitabench.agent.content import Content
from noitabench.game import Game
from PIL import Image

Make = Callable[..., AgentSession]
CONTENT = Content.load()


def channels(a: dict[str, Any]) -> set[str]:
    return set(a["observation"])


def test_by_default_the_text_and_the_ascii_map_are_on_and_the_screenshot_is_off(
    session: AgentSession,
) -> None:
    assert channels(session.observe()) == {"state", "map"}


@pytest.mark.parametrize("text", [True, False])
@pytest.mark.parametrize("ascii_map", [True, False])
@pytest.mark.parametrize("screenshot", [True, False])
def test_each_channel_switches_on_and_off_alone(
    game: Game, make_session: Make, text: bool, ascii_map: bool, screenshot: bool
) -> None:
    s = make_session(game, text=text, ascii=ascii_map, screenshot=screenshot)
    want = {k for k, on in (("state", text), ("map", ascii_map), ("screenshot", screenshot)) if on}
    assert channels(s.observe()) == want
    a = s.decide("wait")
    assert channels(a) == want
    # what a command did is told in any case: the stop reason and the events
    assert a["stop"]["reason"] == "completed" and "events" in a
    json.dumps(a)
    render_text(a)


# -- the ASCII map ----------------------------------------------------------------------------------


def rows(a: dict[str, Any]) -> list[str]:
    return a["observation"]["map"]["rows"]


def test_the_map_is_64_by_32_with_the_player_in_the_middle(session: AgentSession) -> None:
    m = session.observe()["observation"]["map"]
    assert len(m["rows"]) == 32 and all(len(r) == 64 for r in m["rows"])
    assert m["cell"] == 4 and m["columns"] == 64
    assert m["rows"][16][32] == "@"
    assert sum(r.count("@") for r in m["rows"]) == 1


def test_beyond_the_world_the_map_shows_question_marks(session: AgentSession) -> None:
    m = session.observe()["observation"]["map"]
    assert m["origin"]["x"] < 0 and m["rows"][16].startswith("?")
    assert m["legend"]["?"] == "outside the world"


def test_the_legend_names_materials_and_nothing_else(session: AgentSession) -> None:
    legend = session.observe()["observation"]["map"]["legend"]
    names = set(CONTENT.material_keys) | {"you", "outside the world", "potion", "barrel", "on fire"}
    kinds = {
        "longleg",
        "shotgunner",
        "firemage_weak",
        "wand",
        "spell",
        "bottle",
        "bomb",
        "projectile",
    }
    assert set(legend.values()) <= names | kinds
    assert legend["#"] == "rock" and legend["."] == "air" and legend["@"] == "you"
    assert len(set(legend)) == len(legend)  # one character, one meaning


def test_the_characters_are_unique_per_material(session: AgentSession) -> None:
    style = MapStyle.build(CONTENT)
    assert len(set(style.chars)) == len(style.chars) == len(CONTENT.material_keys)
    assert style.chars[0] == "."  # air
    assert BURNING_CHAR not in style.chars  # kept for "on fire"


def put(game: Game, x: int, y: int, w: int, h: int, material: str) -> None:
    game.fill_rect(x, y, w, h, material)


def test_the_most_visible_kind_of_a_block_gives_its_character(
    game: Game, make_session: Make
) -> None:
    s = make_session(game)
    m = s.observe()["observation"]["map"]
    ox, oy = m["origin"]["x"], m["origin"]["y"]
    base_x, base_y = ox + 4 * 40, oy + 4 * 2  # a block high in the air, to the right
    cases = {  # block column offset -> (cells to put, expected character)
        0: [("rock", 2), ("water", 2)],  # liquid beats terrain
        2: [("rock", 8), ("fire", 1)],  # fire beats everything
        4: [("rock", 8), ("sand", 2)],  # powder beats terrain
        6: [("rock", 8), ("steam", 2)],  # gas beats terrain
        8: [("water", 5), ("rock", 11)],  # the commonest of the winning kind: water
    }
    for col, parts in cases.items():
        x = base_x + 4 * col
        offset = 0
        for material, cells in parts:
            for i in range(cells):
                put(game, x + (offset + i) % 4, base_y + (offset + i) // 4, 1, 1, material)
            offset += cells
    got = rows(s.observe())[2][40:49:2]
    assert list(got) == ["~", "^", "s", "'", "~"]


def test_creatures_and_items_are_drawn_over_the_terrain(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 40, GROUND)
    s = make_session(game)
    a = s.observe()
    flat = "".join(rows(a))
    assert "L" in flat and "U" in flat and "$" in flat  # a longleg, a bottle, a spell card
    legend = a["observation"]["map"]["legend"]
    assert legend["L"] == "longleg" and legend["U"] == "bottle" and legend["$"] == "spell"


# -- the screenshot -----------------------------------------------------------------------------------


def decode(a: dict[str, Any]) -> Image.Image:
    shot = a["observation"]["screenshot"]
    img = Image.open(io.BytesIO(base64.b64decode(shot["data_base64"])))
    img.load()
    return img


def test_the_screenshot_is_a_png_of_the_cells_around_the_player(
    game: Game, make_session: Make
) -> None:
    s = make_session(game, screenshot=True)
    a = s.observe()
    shot = a["observation"]["screenshot"]
    img = decode(a)
    assert img.format == "PNG" and img.size == (256, 192) == (shot["width"], shot["height"])
    px = np.array(img.convert("RGB"))
    ox, oy = shot["origin"]["x"], shot["origin"]["y"]
    rock = CONTENT.material_colors[CONTENT.material_index("rock")]
    air = CONTENT.material_colors[CONTENT.material_index("air")]
    assert tuple(px[FLOOR + 10 - oy, 60 - ox]) == rock  # a cell of the floor
    assert tuple(px[20, 200]) == air  # open air
    assert tuple(px[0, 0]) == (0, 0, 0)  # outside the world on the left
    assert (px == 255).all(axis=2).any()  # the player's box


def test_the_screenshot_can_be_magnified(game: Game, make_session: Make) -> None:
    s = make_session(game, screenshot=True, shot_scale=3)
    a = s.observe()
    assert decode(a).size == (768, 576)
    assert a["observation"]["screenshot"]["width"] == 768


def test_creatures_are_boxes_in_the_screenshot(game: Game, make_session: Make) -> None:
    game.spawn_enemy("longleg", START_X + 40, GROUND)
    s = make_session(game, screenshot=True)
    a = s.observe()
    enemy = next(e for e in a["observation"]["state"]["nearby"] if e["kind"] == "longleg")
    ox, oy = (
        a["observation"]["screenshot"]["origin"]["x"],
        a["observation"]["screenshot"]["origin"]["y"],
    )
    px = np.array(decode(a).convert("RGB"))
    assert tuple(px[enemy["y"] + 3 - oy, enemy["x"] + 3 - ox]) == (230, 40, 40)


# -- the state ----------------------------------------------------------------------------------------


def test_the_state_tells_where_you_are_and_what_you_hold(game: Game, make_session: Make) -> None:
    game.give_bottle("oil", 150)
    game.give_spell("DAMAGE")
    s = make_session(game)
    st = s.observe()["observation"]["state"]
    assert st["position"] == {"x": START_X, "y": GROUND}
    assert (st["hp"], st["hp_max"], st["levitation"], st["breath"]) == (100.0, 100.0, 1.0, 1.0)
    assert st["on_ground"] is True and st["facing"] == "right" and st["statuses"] == {}
    assert st["active_wand"] == 0 and len(st["wands"]) == 2
    assert st["wands"][0]["slots"] == [
        {"slot": 0, "spell": "LIGHT_BULLET", "uses": None},
        {"slot": 1, "spell": None},
        {"slot": 2, "spell": None},
    ]  # the numbers of a spell are for `inspect`
    assert st["spells"] == [{"index": 0, "spell": "DAMAGE", "uses": None}]
    assert st["bottles"][0]["material"] == "oil" and st["bottles"][0]["amount"] == 150
    assert st["can_edit_wands"] is True and st["goal"] == "Get as deep as you can."


def test_conditions_are_listed_in_seconds(game: Game, make_session: Make) -> None:
    game.give_bottle("water", 400)
    s = make_session(game)
    s.interrupts.disable("status_change")
    s.decide("drink(amount=100)")
    wet = s.observe()["observation"]["state"]["statuses"]["wet"]
    assert 3 < wet <= 3.4  # 100 cells, two frames each


def test_what_is_in_view_is_sorted_by_distance_and_capped(game: Game, make_session: Make) -> None:
    for i in range(20):
        game.spawn_item("bottle", START_X + 3 + 4 * i, GROUND, material="water", amount=10)
    s = make_session(game)
    st = s.observe()["observation"]["state"]
    dists = [abs(e["dx"]) for e in st["nearby"]]
    assert len(st["nearby"]) == 16 and dists == sorted(dists)
    assert st["nearby_omitted"] == 6  # 20 bottles, the spell card and the other bottle, minus 16


def test_a_wall_hides_what_is_behind_it_and_far_things_are_not_seen(
    game_at: Callable[[int], Game], make_session: Make
) -> None:
    game = game_at(WALL_X - 30)
    game.spawn_enemy("longleg", WALL_X + 30, GROUND)  # behind the wall
    game.spawn_enemy("shotgunner", WALL_X - 30 + 140, GROUND)
    s = make_session(game)
    kinds = [e["kind"] for e in s.observe()["observation"]["state"]["nearby"]]
    assert "longleg" not in kinds and "shotgunner" not in kinds
    free = game_at(WALL_X + 20)
    free.spawn_enemy("longleg", WALL_X + 70, GROUND)
    nearby = make_session(free).observe()["observation"]["state"]["nearby"]
    assert [e["hostile"] for e in nearby if e["kind"] == "longleg"] == [True]


# -- the text -----------------------------------------------------------------------------------------


def test_the_text_has_the_stop_reason_the_events_the_state_and_the_map(
    game: Game, make_session: Make
) -> None:
    game.spawn_enemy("longleg", START_X + 20, GROUND)
    s = make_session(game, screenshot=True)
    a = s.decide("aim(target=longleg); fire(until=target_dead)")
    text = render_text(a)
    assert "Decision 2" in text and "Stopped: completed (target_dead)" in text
    assert "Events:" in text and "You cast LIGHT_BULLET" in text
    assert "Position x=" in text and "Wands (* held):" in text and "In view" in text
    assert "Goal: Get as deep as you can." in text
    assert "Map: one character = 4x4 cells" in text and "Legend:" in text
    assert "Screenshot attached (256x192 PNG)" in text
    assert 'aim: {"aim_degrees"' in text and "fire: completed (target_dead)" in text


# -- fire -----------------------------------------------------------------------------------------------


def lit_block(game: Game, s: AgentSession, col: int, row: int, material: str) -> tuple[int, int]:
    """Put one `material` cell in block (`col`, `row`) of the current map and set it on fire;
    returns the cell."""
    m = s.observe()["observation"]["map"]
    x, y = m["origin"]["x"] + 4 * col + 1, m["origin"]["y"] + 4 * row + 1
    put(game, x, y, 1, 1, material)
    assert game.ignite(x, y), f"{material} would not catch fire"
    return x, y


def test_a_burning_cell_makes_its_block_show_on_fire_whatever_it_is_made_of(
    game: Game, make_session: Make
) -> None:
    s = make_session(game)
    before = s.observe()["observation"]["map"]
    assert (
        BURNING_CHAR not in "".join(before["rows"]) and "on fire" not in before["legend"].values()
    )
    lit_block(game, s, 40, 2, "oil")
    lit_block(game, s, 44, 2, "wood")
    m = s.observe()["observation"]["map"]
    assert m["rows"][2][40] == BURNING_CHAR and m["rows"][2][44] == BURNING_CHAR
    assert m["rows"][2][42] == "."  # a block next door that does not burn
    assert m["legend"][BURNING_CHAR] == "on fire"
    assert "".join(m["rows"]).count(BURNING_CHAR) == 2
    assert len(set(m["legend"])) == len(m["legend"])


def test_flames_keep_their_own_character_and_the_player_is_still_drawn_on_top(
    game: Game, make_session: Make
) -> None:
    s = make_session(game)
    m = s.observe()["observation"]["map"]
    ox, oy = m["origin"]["x"], m["origin"]["y"]
    put(game, ox + 4 * 40, oy + 4 * 2, 1, 1, "fire")
    x, y = lit_block(game, s, 40, 2, "oil")
    assert (x, y) != (ox + 4 * 40, oy + 4 * 2)
    row = s.observe()["observation"]["map"]["rows"][2]
    assert row[40] == "^", "a block that shows flames is not renamed"
    assert BURNING_CHAR not in "".join(s.observe()["observation"]["map"]["rows"][3:])


def test_fire_is_in_the_text_of_the_answer_too(game: Game, make_session: Make) -> None:
    s = make_session(game)
    lit_block(game, s, 40, 2, "oil")
    text = render_text(s.observe())
    assert f"{BURNING_CHAR} on fire" in text


def test_the_screenshot_tints_burning_cells_like_the_play_page(
    game: Game, make_session: Make
) -> None:
    s = make_session(game, screenshot=True)
    shot = s.observe()["observation"]["screenshot"]
    ox, oy = shot["origin"]["x"], shot["origin"]["y"]
    x, y = ox + 200, oy + 20
    put(game, x, y, 1, 1, "oil")
    plain = np.array(decode(s.observe()).convert("RGB"))
    assert game.ignite(x, y)
    lit = np.array(decode(s.observe()).convert("RGB"))
    oil = np.array(CONTENT.material_colors[CONTENT.material_index("oil")], dtype=float)
    expected = np.rint(oil * 0.4 + np.array([255, 150, 30]) * 0.6).astype(int)
    assert tuple(plain[20, 200]) == tuple(oil.astype(int))
    assert tuple(lit[20, 200]) == tuple(expected)
    changed = (plain != lit).any(axis=2)
    assert changed.sum() == 1 and changed[20, 200], "only the burning cell changed"


def test_fire_in_a_magnified_screenshot_covers_the_whole_cell(
    game: Game, make_session: Make
) -> None:
    s = make_session(game, screenshot=True, shot_scale=3)
    shot = s.observe()["observation"]["screenshot"]
    x, y = shot["origin"]["x"] + 200, shot["origin"]["y"] + 20
    put(game, x, y, 1, 1, "oil")
    plain = np.array(decode(s.observe()).convert("RGB"))
    game.ignite(x, y)
    lit = np.array(decode(s.observe()).convert("RGB"))
    changed = (plain != lit).any(axis=2)
    assert changed.sum() == 9 and changed[60:63, 600:603].all()


def test_fire_reaches_the_agent_only_through_the_engine(game: Game, make_session: Make) -> None:
    s = make_session(game)
    x, y = lit_block(game, s, 40, 2, "oil")
    window = s.engine.burning(x - 2, y - 2, 5, 5)
    assert window.shape == (5, 5) and window[2, 2] == 1 and window.sum() >= 1
    assert s.engine.burning(-20, -20, 8, 4).shape == (4, 8)
    assert not s.engine.burning(-20, -20, 8, 4).any(), "nothing burns outside the world"
