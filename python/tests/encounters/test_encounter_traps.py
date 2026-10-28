"""The traps of the scenes are real: the wrong move costs something (cp1-feedback section 3.1).

The reference solutions (``test_encounter_solutions.py``) show the scenes can be solved; these
tests show the obvious shortcut does not work, so a solved scene means something.
"""

from __future__ import annotations

import colorsys

import pytest
import solutions
from driver import start
from noitabench.worldgen.config import load_materials
from noitabench.worldgen.encounter_defs import instantiate, load_encounters
from noitabench.worldgen.table import get_rules

RULE_SEEDS = [0, 3, 6]


@pytest.mark.parametrize("rule_seed", RULE_SEEDS)
def test_wading_through_the_lava_river_of_e02_costs_hp(rule_seed):
    r = start("E02", 0, rule_seed)
    solutions.enter(r)
    rx, _ry, rw, _rh = r.meta["regions"]["river"]
    side = 1 if r.x < rx else -1
    r.walk_to(rx + rw + 3 if side > 0 else rx - 6, tol=1, max_frames=400)
    assert r.dead or r.hp < 85, f"{r.hp:.0f} HP left after wading"


@pytest.mark.parametrize("rule_seed", RULE_SEEDS)
def test_a_liquid_that_does_not_solidify_lava_leaves_the_river_of_e02_alone(rule_seed):
    r = start("E02", 0, rule_seed)
    solutions.enter(r)
    solutions.collect(r, ("bottle",))
    rules = get_rules(rule_seed)
    decoys = [
        i
        for i, b in enumerate(r.p["bottles"])
        if b["amount"] > 0 and b["material"] not in rules.solidifiers()
    ]
    assert decoys, "the scene hands out a liquid that does not solidify lava"
    rx, ry, rw, rh = r.meta["regions"]["river"]
    before = r.count("lava", (rx, ry, rw, rh))
    r.walk_to(rx - 6 if r.x < rx else rx + rw + 5, tol=1)
    r.pour(-25 if r.x < rx else 205, 40, bottle=decoys[0])
    r.wait(120)
    assert r.count("lava", (rx, ry, rw, rh)) >= 0.7 * before


def test_the_starter_wand_does_not_open_the_brick_plug_of_e06():
    r = start("E06", 0, 0)
    solutions.enter(r)
    px, py, pw, ph = r.meta["regions"]["plug"]
    bricks = r.count("brick", (px, py, pw, ph))
    assert bricks > 0
    r.walk_to(px + pw / 2 - 2, tol=2)
    for _ in range(12):  # twelve digging bolts straight down onto the plug
        r.dig(-90, 14)
        r.wait(10)
    assert r.count("brick", (px, py, pw, ph)) == bricks


@pytest.mark.parametrize("rule_seed", RULE_SEEDS)
def test_the_water_of_the_acid_vat_of_e16_is_not_free_acid(rule_seed):
    """The acid lies in a brick vat; the floor of the hall is dry (no free acid)."""
    r = start("E16", 0, rule_seed)
    fp = r.meta["footprint"]
    inside = r.count("acid", tuple(r.meta["regions"]["trough"]))
    assert inside > 0
    assert (
        r.count("acid", (fp["x"], fp["y"], fp["w"], fp["h"])) == inside
    )  # all of it is in the vat


# ------------------------------------------------------------------- batch G1: five optional rooms


@pytest.mark.parametrize("variant", [0, 1])
def test_wading_through_the_lava_door_of_e05_costs_hp(variant):
    r = start("E05", variant, 0)
    way = solutions.enter_room(r, depth=6)
    solutions.drop_down(r, r.meta["regions"]["drop"], way)
    rx, _ry, rw, _rh = r.meta["regions"]["river"]
    side = 1 if r.x < rx else -1
    r.walk_to(rx + rw + 3 if side > 0 else rx - 6, tol=1, max_frames=400)  # through the lava
    r.wait(360)  # the fire it lit on the wader burns for six seconds
    assert r.dead or r.hp < 75, f"{r.hp:.0f} HP left after wading"


@pytest.mark.parametrize("variant", [0, 1, 2, 3])
def test_the_key_of_e05_is_far_from_the_river_and_out_of_sight_of_it(variant):
    """The solvent bottle stands in the first hall, a floor and a roof of rock and brick above the
    river (and 70 cells of walk and climb from it): remembering it matters."""
    r = start("E05", variant, 0)
    reg = r.meta["regions"]
    rx, ry, rw, rh = reg["river"]
    river = (rx + rw // 2, ry + rh // 2)
    rules = get_rules(0)
    key = next(
        e for e in r.entities("bottle") if e["detail"] in rules.solidifiers()
    )  # the bottle with a solvent (the decoy holds oil or whiskey)
    where = (key["x"] + key["w"] // 2, key["y"] + key["h"] // 2)
    assert river[1] - where[1] >= 20
    assert r.g.raycast(where[0], where[1], river[0], river[1], "surfaces") is not None
    kx, ky, kw, kh = reg["key"]
    assert kx <= where[0] < kx + kw and ky <= where[1] < ky + kh


def test_the_vault_of_e05_cannot_be_tunnelled_into_from_the_first_hall():
    r = start("E05", 0, 0)
    reg = r.meta["regions"]
    rx, ry, rw, rh = reg["roof"]
    bricks = r.count("brick", (rx, ry, rw, rh))
    solutions.enter_room(r, depth=6)
    r.walk_to(reg["vault"][0] + 4, tol=2)  # right over the vault
    for _ in range(10):
        r.dig(-90, 14)
        r.wait(10)
    r.fall()
    assert r.count("brick", (rx, ry, rw, rh)) == bricks
    assert r.y < ry, "the player fell through the roof of the vault"


@pytest.mark.parametrize("variant", [0, 1])
def test_the_planks_of_e09_stop_spark_bolts(variant):
    """Wood is durability 10 and a spark bolt breaks 8: bolts that burst on the near post leave
    the posts and the bunker whole. (From the door the bolts burst on the brick pedestal: the
    shots are fired from the floor beyond it.)"""
    r = start("E09", variant, 0)
    way = solutions.enter_room(r, depth=3)
    fp, reg = r.meta["footprint"], r.meta["regions"]
    px, py, pw, _ph = reg["posts"]
    post = (px + 1.5 if way > 0 else px + pw - 1.5, py + 5)  # the near post, under the bunker
    r.walk_to(fp["x"] + 44 if way > 0 else fp["x"] + fp["w"] - 45, tol=1.5)  # past the pedestal
    r.wait(20)

    def wood() -> int:
        return r.count("wood", tuple(reg["posts"])) + r.count("wood", tuple(reg["bunker"]))

    before, bursts = wood(), 0
    for frame in range(90):
        r.step(select_wand=0, fire=frame < 60, aim=r.aim_at_point(*post))
        bursts += sum(e["type"] == "explosion" and abs(e["x"] - post[0]) <= 3 for e in r.g.events())
    assert bursts > 0, "no bolt reached the post"
    assert wood() == before


@pytest.mark.parametrize("variant", [0, 1])
def test_standing_in_the_line_of_the_slits_of_e09_costs_hp(variant):
    """The guard sees the floor of the hall through its slits: one to three volleys (about 20 HP
    each) in 300 frames."""
    r = start("E09", variant, 0)
    way = solutions.enter_room(r, depth=3)
    bx, _by, bw, _bh = r.meta["regions"]["bunker"]
    r.walk_to(bx - 28 if way > 0 else bx + bw + 24, tol=2)
    r.wait(300)
    assert r.dead or r.hp < 85, f"{r.hp:.0f} HP left"


@pytest.mark.parametrize("variant", [0, 1])
def test_shooting_the_barrel_of_e09_from_inside_the_hall_costs_hp(variant):
    """The blast reaches 30 cells and 75 HP: stand in the door passage and it takes a quarter."""
    r = start("E09", variant, 0)
    way = solutions.enter_room(r, depth=3)
    barrel = next(e for e in r.entities() if e["kind"] == "barrel_gunpowder")
    seen: list[dict] = []
    for _ in range(300):
        r.step(
            select_wand=0,
            fire=True,
            aim=r.aim_at_point(barrel["x"] + barrel["w"] / 2, barrel["y"] + barrel["h"] / 2),
        )
        seen.extend(r.g.events())
        if any(e["type"] == "barrel_break" for e in seen):
            break
    assert any(e["type"] == "barrel_break" for e in seen), "the barrel did not blow"
    assert solutions.blast_damage(seen) > 15, f"{r.hp:.0f} HP left; way {way}"


@pytest.mark.parametrize("variant", [0, 1])
def test_the_pack_of_e10_falls_into_the_pit_and_stays_there(variant):
    """Hämis jump 16 cells; the pit is 22 deep. Whoever falls in stays in (wet, at the bottom or
    against a wall); none ever stands on the near ledge."""
    r = start("E10", variant, 0)
    way = solutions.enter_room(r, depth=3)
    px, py, pw, _ph = r.meta["regions"]["pool"]
    r.walk_to(px - 30 if way > 0 else px + pw + 26, tol=2)  # out of the reach of the wall
    r.wait(600)
    foes = r.entities("longleg")
    assert foes
    for e in foes:
        feet = e["y"] + e["h"]
        assert feet > py + 3, f"a Hämis stands at the level of the ledge: {e}"
        assert px - 6 <= e["x"] <= px + pw + 6


@pytest.mark.parametrize("variant", [0, 1])
def test_standing_at_the_edge_of_the_pit_of_e10_costs_hp(variant):
    """The pack, trapped, jumps at the wall nearest the player and bites through it."""
    r = start("E10", variant, 0)
    way = solutions.enter_room(r, depth=3)
    px, _py, pw, _ph = r.meta["regions"]["pool"]
    r.walk_to(px - 12 if way > 0 else px + pw + 8, tol=1.5)
    r.wait(400)
    assert r.dead or r.hp < 70, f"{r.hp:.0f} HP left"


@pytest.mark.parametrize("variant", [0, 1, 2, 3, 4, 5])
def test_the_first_bottle_of_e21_is_never_the_remedy(variant):
    r = start("E21", variant, 0, settle=False)
    side = next(iter(r.meta["doors"]))
    door_x = r.meta["doors"][side][0]
    things = [e for e in r.entities() if e["kind"] in ("bottle", "potion_heal")]
    assert len(things) == 4
    nearest = min(things, key=lambda e: abs(e["x"] - door_x))
    assert nearest["kind"] != "potion_heal"
    assert sum(e["kind"] == "potion_heal" for e in things) == 1
    # none of the three others heals: they are a sludge, a fuel and one more plain liquid
    others = {e["detail"] for e in things if e["kind"] == "bottle"}
    assert "toxic_sludge" in others and len(others) == 3


def test_the_remedy_of_e21_changes_places_with_the_variant():
    """Kept notes cannot say "the third bottle heals": counted from the door after the bottles
    have settled, the potion is the 3rd, 4th and 2nd in the three variant pairs (a mirror keeps
    the order), never the 1st."""
    place = {}
    for variant in range(6):
        r = start("E21", variant, 0)
        r.wait(240)
        door_x = r.meta["doors"][next(iter(r.meta["doors"]))][0]
        things = [e for e in r.entities() if e["kind"] in ("bottle", "potion_heal")]
        things.sort(key=lambda e: abs(e["x"] + e["w"] / 2 - door_x))
        place[variant] = 1 + [e["kind"] for e in things].index("potion_heal")
    assert place == {0: 3, 1: 3, 2: 4, 3: 4, 4: 2, 5: 2}


@pytest.mark.parametrize("variant", [0, 1, 2, 4])  # every pair of fuel and plain liquid
def test_drinking_every_unknown_bottle_of_e21_at_low_hp_is_survivable_but_hurts(variant):
    """Harmful but not deadly: sludge poisons (never below 2 %), whiskey shakes the aim, oil
    makes the drinker flammable; the healing potion is the only one that mends."""
    r = start("E21", variant, 0)
    solutions.enter_room(r, depth=6)
    solutions.hurt(r, 12.0)
    solutions.collect(r, ("bottle", "potion_heal"), limit=4)
    seen: list[dict] = []
    for i, b in enumerate(list(r.p["bottles"])):  # an emptied bottle keeps its place in the list
        if b["material"] == "potion_heal":
            continue
        r.step(2, select_bottle=i)
        r.step(40, select_bottle=i, drink=True)
        r.g.end_bottle_action()
        seen.extend(r.g.events())
    r.wait(600)
    seen.extend(r.g.events())
    assert not r.dead
    assert r.hp < 15, f"{r.hp:.0f} HP: the unknown liquids do not heal"
    assert "poisoned" in {e["status"] for e in seen if e["type"] == "status"}


@pytest.mark.parametrize("variant", [0, 1])
def test_the_pool_of_slime_in_e24_does_nothing_and_the_pool_of_sludge_poisons(variant):
    r = start("E24", variant, 0)
    way = solutions.enter_room(r, depth=6)
    reg = r.meta["regions"]
    solutions.swim_across(r, reg["pool_a"], way)
    assert r.hp == 100 and not r.p["statuses"], r.p["statuses"]
    px, pw = reg["partition"][0], reg["partition"][2]
    r.walk_to(px + pw + 4 if way > 0 else px - 3, tol=1.5)
    solutions.swim_across(r, reg["pool_b"], way)
    assert "poisoned" in r.p["statuses"]
    r.wait(500)
    assert r.hp < 95


def test_the_two_rooms_of_e24_are_built_alike_and_their_liquids_look_alike():
    """Same geometry, same markers, two different green liquids."""
    defs = load_encounters()["E24"]
    mats = load_materials()
    inst = instantiate(defs, get_rules(0), 0, mats)
    a_x, a_w = defs.regions["room_a"][0], defs.regions["room_a"][2]
    b_x = defs.regions["room_b"][0]
    room_a = inst.grid[:, a_x : a_x + a_w].copy()
    room_b = inst.grid[:, b_x : b_x + a_w].copy()
    assert room_a.shape == room_b.shape
    differs = room_a != room_b
    pairs = set(zip(room_a[differs].tolist(), room_b[differs].tolist(), strict=True))
    assert pairs == {(mats["slime"], mats["toxic_sludge"])}
    greens = [_rgb(mats, k) for k in ("slime", "toxic_sludge")]
    assert all(g > r and g > b for r, g, b in greens), greens  # both are green
    hues = [colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360 for r, g, b in greens]
    assert abs(hues[0] - hues[1]) < 70, hues  # about 56 degrees apart on the colour wheel


def _rgb(mats, key: str) -> tuple[int, int, int]:
    import json

    from noitabench.worldgen.contentio import CONTENT_DIR

    rows = json.loads((CONTENT_DIR / "materials.json").read_text())["materials"]
    colour = next(m["color"] for m in rows if m["key"] == key).lstrip("#")
    return int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16)
