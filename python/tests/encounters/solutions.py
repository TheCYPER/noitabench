"""Reference solutions: one short control script per encounter, written against the game state.

Each ``solve_E..`` takes a ``Runner`` loaded with the lab world of the scene (``driver.start``),
plays it like an agent would (drop through the door, fight, pick things up, use the liquid that
works under the world's rules) and leaves the player at the exit. ``check_E..`` says whether it
worked. The scripts read only the game state; the scene's ``meta`` tells them where the doors
and regions are, as the map would tell an agent.
"""

from __future__ import annotations

from collections.abc import Callable

from driver import Runner
from noitabench.worldgen.table import get_rules

Solver = Callable[[Runner, int, int], None]
SOLVERS: dict[str, Solver] = {}


def solver(eid: str) -> Callable[[Solver], Solver]:
    def register(fn: Solver) -> Solver:
        SOLVERS[eid] = fn
        return fn

    return register


# ---------------------------------------------------------------------------------- helpers


def enter(r: Runner, side: str = "top", fight: bool = True) -> None:
    """Walk to the shaft of a door and drop into the scene; fight what is close."""
    r.walk_to(r.meta["doors"][side][0])
    r.fall()
    r.wait(20)
    if fight:
        r.fight(within=100)


def collect(r: Runner, kinds: tuple[str, ...], limit: int = 6) -> None:
    """Pick up the wands, spells and bottles lying about that match ``kinds``, nearest first.

    The game takes the item nearest to the player, which may be another one: the script keeps
    trying (a few times per item) until the one it walked to is gone.
    """
    for _ in range(limit):
        things = [e for e in r.entities() if e["kind"] in kinds]
        if not things:
            return
        e = min(things, key=lambda e: abs(e["x"] - r.x))
        for _try in range(3):
            r.walk_to(e["x"] + e["w"] / 2 - 2, tol=2)
            r.pick_up()
            if not any(e2["id"] == e["id"] for e2 in r.entities()):
                break
        else:
            return


def leave(r: Runner, side: str = "bottom", settle: int = 30) -> bool:
    """Walk to the shaft of a door and fall through it; True if the player ends below the scene.

    An enemy at arm's length is dealt with first. The player creeps over the edge (one step,
    then a pause) and leans back in the air: at walking speed it would cross a narrow shaft
    before it fell four cells.
    """
    x, y = r.meta["doors"][side]
    for _ in range(40):
        if r.foes(within=14):
            r.fight(within=14, max_frames=120)
        if r.walk_to(x - (1 if r.x < x else -1) * 8, max_frames=30):
            break
    creep_to(r, x)
    r.fall()
    r.wait(settle)
    return r.y > y and not r.dead


def creep_to(r: Runner, x: float, max_frames: int = 300) -> None:
    """Move toward column ``x`` a step at a time until the player starts to fall (or arrives)."""
    for t in range(max_frames):
        dx = x - (r.x + 2)
        if abs(dx) <= 1.5 or not r.p["on_ground"]:
            break
        r.step(move=(1 if dx > 0 else -1) if t % 4 == 0 else 0)
    # in the air: lean back against the momentum
    for _ in range(40):
        if r.p["on_ground"]:
            break
        dx = x - (r.x + 2)
        r.step(move=(1 if dx > 2 else -1 if dx < -2 else 0))


def bottle_with(r: Runner, materials: list[str]) -> int | None:
    for i, b in enumerate(r.p["bottles"]):
        if b["material"] in materials and b["amount"] > 0:
            return i
    return None


def contact_damage(r: Runner) -> float:
    """HP the player lost to materials (acid, lava ...) so far, from the event log."""
    return sum(
        e["amount"]
        for e in r.g.events()
        if e["type"] == "damage" and e["target"] == "player" and e["source"] == "contact"
    )


def burning_around(r: Runner, rect: tuple[int, int, int, int]) -> int:
    ov = r.g.overlap(*rect)
    return ov["materials"].get("fire", 0) + ov["materials"].get("flammable_gas", 0) + ov["burning"]


def wait_for_fire_out(r: Runner, rect: tuple[int, int, int, int], limit: int = 400) -> None:
    for _ in range(limit // 10):
        r.wait(10)
        if burning_around(r, rect) == 0:
            return


# ----------------------------------------------------------------------------------- E02


def cross_lava(r: Runner, river: tuple[int, int, int, int], idx: int) -> None:
    """Pour the bottle ``idx`` on the lava river in bursts and walk over the crust it makes."""
    rx, ry, rw, _rh = river
    side = 1 if r.x < rx else -1
    far_x = rx + rw + 2 if side > 0 else rx - 5
    r.walk_to(rx - 6 if side > 0 else rx + rw + 5, tol=1)
    corridor = (rx - 10, ry - 8, rw + 20, 8)
    angle = -25 if side > 0 else 205
    for _ in range(14):
        feet = int(r.y) + 7
        ahead = [r.cell(int(r.x + side * k), feet) for k in (3, 6, 9, 12)]
        if (side > 0 and r.x >= far_x) or (side < 0 and r.x <= far_x) or r.dead:
            break
        if "lava" in ahead:
            r.pour(angle, 12, bottle=idx)
            wait_for_fire_out(r, corridor)
        r.walk_to(r.x + side * 6, tol=2, max_frames=40)


@solver("E02")
def solve_E02(r: Runner, rule_seed: int) -> None:
    """Take the bottles, pour a liquid that turns lava into rock on the river, walk over the
    crust, take the BOMB spell from the far ledge, drop down the exit shaft."""
    enter(r)
    collect(r, ("bottle",))
    rules = get_rules(rule_seed)
    idx = bottle_with(r, rules.solidifiers())
    assert idx is not None, f"no solvent among {[b['material'] for b in r.p['bottles']]}"
    cross_lava(r, r.meta["regions"]["river"], idx)
    collect(r, ("spell",))
    r.fight()
    leave(r)


def check_E02(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if "BOMB" not in [s["spell"] for s in r.p["spells"]]:
        problems.append("did not get the BOMB spell")
    if r.y <= r.meta["doors"]["bottom"][1]:
        problems.append("did not reach the exit")
    return problems


# ----------------------------------------------------------------------------------- E08


@solver("E08")
def solve_E08(r: Runner, rule_seed: int) -> None:
    """Sink to the floor of the flooded room, dig through it and let the water run into the
    cellar; deal with what lives there and leave by the doorway at the far end."""
    enter(r, fight=False)
    fx, _fy, fw, _fh = r.meta["regions"]["floor"]
    r.fall()
    r.walk_to(fx + fw / 2, tol=3)
    r.dig(-90, 14)
    r.wait(30)
    r.fall()
    # the cellar fills with the water of the room: out before the breath runs out
    leave(r, settle=0)


def check_E08(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    wx, wy, ww, wh = r.meta["regions"]["water"]
    left = r.count("water", (wx, wy, ww, wh))
    if left > 0.5 * ww * wh:
        problems.append(f"the room is still flooded ({left} water cells)")
    if r.y <= r.meta["doors"]["bottom"][1]:
        problems.append("did not reach the exit")
    return problems


# ----------------------------------------------------------------------------------- E16


def jump_gap(r: Runner, side: int, edge: float, run_up: float = 8.0) -> None:
    """Run at the last solid cell ``edge`` (the player moves in direction ``side``), jump from
    it and keep moving until the player lands again."""
    r.walk_to(edge - side * run_up - (3 if side > 0 else 0), tol=1)
    airborne = False
    for _ in range(160):
        front = r.x + (3 if side > 0 else 0)  # the box is 4 cells wide
        take_off = not airborne and r.p["on_ground"] and (front - edge) * side >= 0
        r.step(move=side, jump=take_off)
        airborne = airborne or not r.p["on_ground"]
        if (airborne and r.p["on_ground"]) or r.dead:
            return


def standing_on(r: Runner) -> set[str]:
    """The materials directly under the player's feet."""
    return {r.cell(int(r.x) + dx, int(r.y) + 7) for dx in range(4)}


@solver("E16")
def solve_E16(r: Runner, rule_seed: int) -> None:
    """Inspect, see the acid, and cross the trough by two jumps over the islet; pick up the
    potion on the way; leave by the shaft."""
    enter(r)
    tx, _ty, tw, _th = r.meta["regions"]["trough"]
    ix, _iy, iw, _ih = r.meta["regions"]["islet"]
    side = 1 if r.x < tx else -1
    near_rim = tx - 1 if side > 0 else tx + tw
    isl_far = ix + iw if side > 0 else ix - 1
    jump_gap(r, side, near_rim)
    assert "brick" in standing_on(r), f"landed on {standing_on(r)}"
    collect(r, ("bottle",), limit=1)
    jump_gap(r, side, isl_far - side, run_up=2.0)
    r.fight(within=100)
    leave(r)


def check_E16(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    burnt = contact_damage(r)
    if burnt > 3:
        problems.append(f"lost {burnt:.0f} HP to the acid although the trough can be hopped over")
    if r.y <= r.meta["doors"]["bottom"][1]:
        problems.append("did not reach the exit")
    return problems


# ----------------------------------------------------------------------------------- E12


def dig_down_through(r: Runner, region: tuple[int, int, int, int], limit: int = 60) -> None:
    """Dig straight down through a plug until the player has fallen through it (below the
    region), standing over its middle for every shot (the blast pushes the player about)."""
    x, y, w, h = region
    for _ in range(limit):
        if r.y > y + h or r.dead:
            break
        if abs(r.x - (x + w / 2 - 2)) > 1.5 and r.p["on_ground"]:
            r.walk_to(x + w / 2 - 2, tol=1)
        r.step(2, select_wand=1, fire=True, aim=-90, move=0)
        r.wait(8)
    r.fall()


@solver("E12")
def solve_E12(r: Runner, rule_seed: int) -> None:
    """Take the EXPLOSIVE_PROJECTILE spell lying by the door, then read the plugs: rock is safe
    to dig, ground opens the lava beside it. Dig the rock plug of each seam, walk the corridor
    below to the next one, then take the exit."""
    enter(r)
    collect(r, ("spell",), limit=1)
    reg = r.meta["regions"]
    dig_down_through(r, reg["safe1"])
    r.fight(within=60)
    dig_down_through(r, reg["safe2"])
    leave(r)


def check_E12(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if "EXPLOSIVE_PROJECTILE" not in [c["spell"] for c in r.p["spells"]]:
        problems.append("did not get the EXPLOSIVE_PROJECTILE spell")
    burnt = contact_damage(r)
    if burnt > 1:
        problems.append(f"touched lava ({burnt:.0f} HP)")
    if r.y <= r.meta["doors"]["bottom"][1]:
        problems.append("did not reach the exit")
    return problems


# ----------------------------------------------------------------------------------- E22


def climb_to(r: Runner, floor_y: int, from_x: float, to_x: float) -> None:
    """Jump from the floor at ``from_x`` onto a ledge whose top is at row ``floor_y``."""
    side = 1 if to_x > from_x else -1
    r.walk_to(from_x, tol=1)
    for _ in range(80):
        r.step(move=side, jump=r.p["on_ground"] and r.y + 7 > floor_y + 1)
        if r.p["on_ground"] and r.y + 7 <= floor_y + 1:
            return


@solver("E22")
def solve_E22(r: Runner, rule_seed: int) -> None:
    """The long way: drop through the hole, walk the lane under the floor, take the potion,
    leave by the shaft."""
    enter(r, fight=False)
    hx, _hy, hw, _hh = r.meta["regions"]["hole"]
    r.walk_to(hx - 4 if r.x < hx else hx + hw + 3, tol=1)
    creep_to(r, hx + hw / 2)
    r.fall()
    r.fight(within=60)
    leave(r)


def check_E22(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if r.y <= r.meta["doors"]["bottom"][1]:
        problems.append("did not reach the exit")
    return problems


# ----------------------------------------------------------------------------------- E07


def fly_over(r: Runner, side: int, to_x: float, max_frames: int = 200) -> None:
    """Jump, then levitate toward ``to_x`` and let go to land on it."""
    r.step(move=side, jump=r.p["on_ground"])
    for _ in range(max_frames):
        if (to_x - r.x) * side <= 0:
            break
        r.step(move=side, fly=True)
    r.fall()


@solver("E07")
def solve_E07(r: Runner, rule_seed: int) -> None:
    """Take the empty bottle, fill it at the pool, fly over the acid, crust the lava with what
    is in the bottle, leave."""
    enter(r)
    collect(r, ("bottle",), limit=1)
    px, _py, pw, _ph = r.meta["regions"]["pool"]
    side = 1 if r.x < px else -1
    r.walk_to(px + pw / 2 - 2, tol=1)  # wade into the pool
    r.fill(40)
    assert r.bottle_amount(0) >= 100, f"filled only {r.bottle_amount(0)}"
    ax, _ay, aw, _ah = r.meta["regions"]["acid"]
    rim = ax - 3 if side > 0 else ax + aw + 2
    r.walk_to(rim, tol=1)
    fly_over(r, side, ax + aw + 5 if side > 0 else ax - 6)
    r.fight(within=60)
    cross_lava(r, r.meta["regions"]["lava"], 0)
    leave(r)


def check_E07(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if (burnt := contact_damage(r)) > 25:
        problems.append(f"lost {burnt:.0f} HP to acid or lava")
    if r.y <= r.meta["doors"]["bottom"][1]:
        problems.append("did not reach the exit")
    return problems


# ----------------------------------------------------------------------------------- E23


def swim_across(r: Runner, pool: tuple[int, int, int, int], side: int) -> None:
    """Walk off the ledge into the pool and swim along its surface to the far ledge."""
    px, py, pw, _ph = pool
    r.walk_to(px - 3 if side > 0 else px + pw + 2, tol=1)
    target = px + pw + 2 if side > 0 else px - 5
    for _ in range(400):
        if (r.x - target) * side >= 0:
            break
        r.step(move=side, jump=r.y + 7 > py + 1)
    r.fall()


@solver("E23")
def solve_E23(r: Runner, rule_seed: int) -> None:
    """Take the vial, try a little of it on the floor, then swim across and leave."""
    enter(r)
    collect(r, ("bottle",), limit=1)
    pool = r.meta["regions"]["pool"]
    side = 1 if r.x < pool[0] else -1
    r.pour(-60 if side > 0 else 240, 3)  # the experiment: a splash on the floor ahead
    r.wait(10)
    swim_across(r, pool, side)
    leave(r)


def check_E23(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if r.y <= r.meta["doors"]["bottom"][1]:
        problems.append("did not reach the exit")
    if r.hp < 40:
        problems.append(f"only {r.hp:.0f} HP left")
    return problems


# ------------------------------------------------------------------- the optional rooms


def enter_room(r: Runner, depth: float = 8.0) -> int:
    """Walk through the side door into the room; returns +1 if the room lies to the right."""
    side = next(iter(r.meta["doors"]))
    dx = r.meta["doors"][side][0]
    way = 1 if side == "left" else -1
    r.walk_to(dx + way * depth, tol=1.5)
    return way


def pick_all(r: Runner, kinds: tuple[str, ...], limit: int = 6) -> None:
    collect(r, kinds, limit)


# ----------------------------------------------------------------------------------- E03


@solver("E03")
def solve_E03(r: Runner, rule_seed: int) -> None:
    """The Fireball spell is the wrong tool. Take the bottle of water, wet the mage with it,
    climb its platform and take the wand."""
    way = enter_room(r, depth=6)
    collect(r, ("bottle",), limit=1)
    mage = next(e for e in r.entities("firemage_weak"))
    tx, ty = mage["x"] + mage["w"] / 2, mage["y"] + mage["h"] / 2
    r.throw(r.throw_angle(tx, ty))
    for _ in range(40):  # it burns away while it is wet
        r.wait(15)
        if not r.foes(within=300, in_sight=False) or r.dead:
            break
    hx, hy, hw, hh = r.meta["regions"]["hall"]
    wait_for_fire_out(r, (hx, hy, hw, hh), limit=900)  # the oil trough burns first
    gx, gy, gw, _gh = r.meta["regions"]["guard"]
    near_edge = gx - 2 if way > 0 else gx + gw + 1
    r.walk_to(near_edge - way * 3, tol=1)
    for _ in range(80):  # climb the platform
        r.step(move=way, jump=r.p["on_ground"] and r.y + 7 > gy - 1)
        if r.p["on_ground"] and r.y + 7 <= gy + 1:
            break
    collect(r, ("wand",), limit=1)


def check_E03(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if r.foes(within=500, in_sight=False):
        problems.append("the mage is alive")
    if len(r.p["wands"]) < 3:
        problems.append("did not get the wand")
    return problems


# ----------------------------------------------------------------------------------- E04


@solver("E04")
def solve_E04(r: Runner, rule_seed: int) -> None:
    """Look at the exhibit and take the spell and the bottle."""
    enter_room(r, depth=6)
    collect(r, ("bottle", "spell"), limit=3)


def check_E04(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if not r.p["spells"]:
        problems.append("did not get the spell")
    reg = r.meta["regions"]["lava_vessel"]
    if r.count("rock", (reg[0], reg[1], reg[2], reg[3] - 1)) < 8:
        problems.append("the exhibit has no crust on the lava")
    rules = get_rules(r.meta["rule_seed"])
    liquid = r.meta["params"]["A"]
    if liquid not in rules.solidifiers():
        problems.append(f"the exhibit shows {liquid}, which does not solidify lava here")
    return problems


# ----------------------------------------------------------------------------------- E14


def burnt_off(r: Runner, rect: tuple[int, int, int, int], limit: int = 900) -> None:
    """Wait until the fire and the spilt fuel in ``rect`` are gone (the cup's lava lights it)."""
    for _ in range(limit // 10):
        r.wait(10)
        ov = r.g.overlap(*rect)["materials"]
        if not any(ov.get(k, 0) for k in ("fire", "flammable_gas", "oil", "whiskey")):
            return


@solver("E14")
def solve_E14(r: Runner, rule_seed: int) -> None:
    """Splash a little of each bottle on the edge of the river, step back from the fire, pour the
    one that made rock and cross to the wand."""
    way = enter_room(r, depth=6)
    collect(r, ("bottle",), limit=3)
    rx, ry, rw, _rh = r.meta["regions"]["river"]
    edge = rx - 5 if way > 0 else rx + rw + 4
    first = (rx, ry, 6, 1) if way > 0 else (rx + rw - 6, ry, 6, 1)  # the cells the splash lands on
    area = (rx - 14, ry - 12, rw + 28, 14)
    chosen = None
    for idx in range(len(r.p["bottles"])):
        r.walk_to(edge, tol=1)
        before = r.count("rock", first) + r.count("ground", first)
        r.pour(-30 if way > 0 else 210, 1, bottle=idx)
        r.walk_to(edge - way * 12, tol=1)  # a fuel on lava burns: step back and wait
        burnt_off(r, area)
        after = r.count("rock", first) + r.count("ground", first)
        if after > before and chosen is None:
            chosen = idx
    assert chosen is not None, "no bottle made rock"
    cross_lava(r, r.meta["regions"]["river"], chosen)
    collect(r, ("wand",), limit=1)


def check_E14(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if len(r.p["wands"]) < 3:
        problems.append("did not get the wand")
    return problems


# ----------------------------------------------------------------------------------- E18


@solver("E18")
def solve_E18(r: Runner, rule_seed: int) -> None:
    """Dig down on the far side of the hall, away from the pocket of lava, fall into the
    room and take the wand."""
    enter_room(r, depth=6)
    fx, fy, fw, fh = r.meta["regions"]["floor"]
    px, _py, pw, _ph = r.meta["regions"]["pocket"]
    spot = fx + fw - 12 if (px + pw / 2 - fx) < fw / 2 else fx + 10  # the side the pocket is not on
    r.walk_to(spot, tol=1)
    dig_down_through(r, (spot - 4, fy, 8, fh), limit=80)
    collect(r, ("wand",), limit=1)


def check_E18(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if len(r.p["wands"]) < 3:
        problems.append("did not get the wand")
    if (burnt := contact_damage(r)) > 1:
        problems.append(f"touched lava ({burnt:.0f} HP)")
    return problems


# ----------------------------------------------------------------------------------- E06


KEY = ["EXPLOSIVE_PROJECTILE", "BOMB"]  # the modifier first: it draws the card after it
BLAST_REACH = 75  # [EXPLOSIVE_PROJECTILE, BOMB]: radius 60 + 15, and the damage floor kills


def hold_key_parts(r: Runner) -> None:
    """The player carries the BOMB of E02 and the EXPLOSIVE_PROJECTILE of E12.

    The lab world holds only this scene, so the two spells found in the other scenes are handed
    over with ``give_spell`` (picking an item up puts the same card into the spell inventory).
    """
    for key in KEY:
        r.g.give_spell(key)


def assemble(r: Runner, spells: list[str]) -> None:
    """Put ``spells`` first in the spark wand with the wand editor, as a player would.

    Placing a spell into an occupied slot sends the old spell back to the inventory.
    """
    for slot, key in enumerate(spells):
        carried = [c["spell"] for c in r.p["spells"]]
        r.g.edit_wand({"op": "place", "wand": 0, "slot": slot, "from": carried.index(key)})
    held = [c["spell"] if c else None for c in r.p["wands"][0]["slots"]]
    assert held[: len(spells)] == spells, held


def bombs(r: Runner) -> list[dict]:
    return r.entities("bomb")


def throw_down_on_plug(r: Runner) -> None:
    """Stand over the middle of the plug, cast the wand straight down: the bomb drops at the
    player's feet, on the brick."""
    px, _py, pw, _ph = r.meta["regions"]["plug"]
    r.walk_to(px + pw // 2 - 2, tol=1)
    for _ in range(60):
        r.step(select_wand=0, fire=True, aim=-90)
        if bombs(r):
            break
    r.step(select_wand=0, aim=-90)
    assert bombs(r), "the wand did not throw the bomb"


def hover_out_of_reach(r: Runner, settle: int = 40) -> float:
    """Levitate through the door shaft to the far top corner of the room above, outside the
    reach of the blast, and hover there until the bomb has gone off. Returns the distance in
    cells from the bomb's last place to the player at that moment."""
    door_x, door_y = r.meta["doors"]["top"]
    px, _py, pw, _ph = r.meta["regions"]["plug"]
    away = -1 if door_x < px + pw // 2 else 1  # the side of the room that lies farther from it
    goal_x, goal_y = door_x + away * 26, r.meta["rooms"]["top"][1] - 34
    last = bombs(r)[0]
    for _ in range(300):
        now = bombs(r)
        if not now:
            break
        last = now[0]
        # through the shaft first, along the ceiling afterwards
        aim_x = goal_x if r.y < door_y - 8 else door_x - 2
        move = 0 if abs(aim_x - r.x) < 1.5 else (1 if aim_x > r.x else -1)
        r.step(select_wand=0, move=move, fly=r.y > goal_y)
    cx, cy = r.center()
    gap = ((cx - last["x"]) ** 2 + (cy - last["y"]) ** 2) ** 0.5
    for _ in range(settle):  # the fires of the blast burn out
        r.step(fly=r.y > goal_y)
    return gap


def go_down_through(r: Runner) -> None:
    """Back from the room above: through the door shaft into the hall, over to the plug and
    down the channel the blast opened (5 cells wide at its narrowest, the player is 4 wide)."""
    px, py, pw, ph = r.meta["regions"]["plug"]
    r.fall()
    r.walk_to(r.meta["doors"]["top"][0])
    r.fall()
    r.wait(20)
    # the middle of the narrowest row of the channel
    xs = [x for x in range(px - 6, px + pw + 6) if r.cell(x, py + ph - 1) == "air"]
    cx = (min(xs) + max(xs)) // 2 if xs else px + pw // 2
    r.walk_to(cx - 2, tol=2)
    for t in range(200):  # creep over the hole a step at a time, centre the box, fall through
        if r.y > py + ph:
            break
        dx = cx - (r.x + 2)
        grounded = r.p["on_ground"]
        step = t % 4 == 0 if grounded else abs(dx) > 1.5
        r.step(move=(1 if dx > 0 else -1) if abs(dx) > 0.7 and step else 0)
    r.wait(20)


def play_key(r: Runner, spells: list[str]) -> float:
    """Kill the guard, assemble ``spells`` in the spark wand, throw the bomb on the plug and keep
    out of its blast. Returns the distance between the bomb and the player when it went off."""
    enter(r)
    hold_key_parts(r)
    assemble(r, spells)
    throw_down_on_plug(r)
    return hover_out_of_reach(r)


def plug_bricks(r: Runner) -> int:
    return r.count("brick", tuple(r.meta["regions"]["plug"]))


@solver("E06")
def solve_E06(r: Runner, rule_seed: int) -> None:
    """Kill the guard, put the two parts of the key into the spark wand ([EXPLOSIVE_PROJECTILE,
    BOMB]), throw the bomb on the plug and levitate out of the reach of its blast; once it has
    gone off, come back down and drop through the channel."""
    gap = play_key(r, KEY)
    assert gap > BLAST_REACH, f"the blast reaches the player ({gap:.0f} cells away)"
    assert plug_bricks(r) < 96, "the key did not break the plug"
    go_down_through(r)


def check_E06(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    _px, py, _pw, ph = r.meta["regions"]["plug"]
    if r.y <= py + ph:
        problems.append("did not get under the plug")
    return problems


def solve_E22_short(r: Runner, rule_seed: int = 0) -> None:
    """The short way: put the Fireball spell into the spark wand, hover in the gap beside the
    ledge (more than 30 cells from the barrel, out of the blast), light the gunpowder barrel from
    there, then fly onto the ledge and walk the corridor to the shaft."""
    enter(r, fight=False)
    collect(r, ("spell",), limit=1)
    r.g.edit_wand({"op": "place", "wand": 0, "slot": 0, "from": 0})
    lx, ly, lw, _lh = r.meta["regions"]["ledge"]
    way = 1 if lx > r.x else -1
    top = ly - 7  # the player's box top when it stands on the ledge
    hover = top - 4  # box top under the ceiling of the corridor
    # the gap between the pillar and the ledge is nine cells wide; its floor is the hole
    gap_lo, gap_hi = (lx - 9, lx) if way > 0 else (lx + lw, lx + lw + 9)
    r.walk_to(gap_lo - 8 if way > 0 else gap_hi + 8 - 4, tol=1)
    for _ in range(40):  # leave the floor as soon as the box is clear of the pillar
        in_gap = r.x >= gap_lo if way > 0 else r.x + 4 <= gap_hi
        mid = (gap_lo + gap_hi) / 2 - 2
        r.step(move=0 if in_gap and abs(r.x - mid) < 1 else way, fly=in_gap and r.y > hover)
        if in_gap and r.y <= hover:
            break
    for _ in range(40):  # up to the ceiling
        if r.y <= hover:
            break
        r.step(fly=True)
    barrel = next(e for e in r.entities() if e["kind"] == "barrel_gunpowder")
    tx, ty = barrel["x"] + barrel["w"] / 2, barrel["y"] + barrel["h"] / 2 - 2
    r.step(select_wand=0, fire=True, aim=r.aim_at_point(tx, ty), fly=True)
    for _ in range(60):  # keep out of the blast until the barrel is gone
        if not any(e["kind"] == "barrel_gunpowder" for e in r.entities()):
            break
        r.step(fly=r.y > hover)
    for _ in range(20):  # the shotgunners are gone; let the fire die down
        r.step(fly=r.y > hover)
    for _ in range(90):  # over the edge, then down onto the ledge
        r.step(fly=r.y > hover, move=way if r.y <= hover + 1 and not r.p["on_ground"] else 0)
        deep = r.x > lx + 3 if way > 0 else r.x + 4 < lx + lw - 3
        if r.p["on_ground"] and r.y <= top + 1 and deep:
            break
    r.wait(10)
    leave(r, settle=120)


# ------------------------------------------------------------------- batch G1: five optional rooms


def door_way(r: Runner) -> int:
    """+1 if the scene lies to the right of its (single side) door, -1 if to the left."""
    return 1 if "left" in r.meta["doors"] else -1


# ----------------------------------------------------------------------------------- E05


def drop_down(r: Runner, region: tuple[int, int, int, int], way: int) -> None:
    """Walk to the clear column ``region`` (a shaft's open half), step off the edge and fall."""
    x, _y, w, _h = region
    r.walk_to(x - 6 if way > 0 else x + w + 6, tol=1.5)
    creep_to(r, x + w / 2)
    r.fall()
    r.wait(30)


@solver("E05")
def solve_E05(r: Runner, rule_seed: int) -> None:
    """Take both bottles from the first hall (the solvent stands on the pedestal), drop down the
    clear half of the shaft, make a crust of the lava river with the right one and walk over it
    into the vault."""
    way = enter_room(r, depth=6)
    collect(r, ("bottle",), limit=2)
    drop_down(r, r.meta["regions"]["drop"], way)
    idx = bottle_with(r, get_rules(rule_seed).solidifiers())
    assert idx is not None, f"no solvent among {[b['material'] for b in r.p['bottles']]}"
    cross_lava(r, r.meta["regions"]["river"], idx)
    collect(r, ("wand", "potion_heal"), limit=2)


def check_E05(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if len(r.p["wands"]) < 3:
        problems.append("did not get the wand of the vault")
    if not any(b["material"] == "potion_heal" for b in r.p["bottles"]):
        problems.append("did not get the potion of the vault")  # a potion is a bottle in the hand
    if (burnt := contact_damage(r)) > 12:
        problems.append(f"lost {burnt:.0f} HP to the lava")
    return problems


# ----------------------------------------------------------------------------------- E09


def shoot_barrel_from(r: Runner, back: float, limit: int = 300) -> list[dict] | None:
    """Stand ``back`` cells outside the door and shoot the gunpowder barrel with the spark wand.

    Returns the events read while shooting, the blast's own included (``Game.events`` hands each
    event out once), or ``None`` if the barrel did not blow.
    """
    way = door_way(r)
    side = next(iter(r.meta["doors"]))
    r.walk_to(r.meta["doors"][side][0] - way * back, tol=1.5)
    barrel = next(e for e in r.entities() if e["kind"] == "barrel_gunpowder")
    seen: list[dict] = []
    for _ in range(limit):
        r.step(
            select_wand=0,
            fire=True,
            aim=r.aim_at_point(barrel["x"] + barrel["w"] / 2, barrel["y"] + barrel["h"] / 2),
        )
        events = r.g.events()
        seen.extend(events)
        if any(e["type"] == "barrel_break" for e in events):
            return seen
    return None


def blast_damage(events: list[dict]) -> float:
    """HP the player lost to explosions among ``events``."""
    return sum(
        e["amount"]
        for e in events
        if e["type"] == "damage" and e["target"] == "player" and e["source"] == "explosion"
    )


@solver("E09")
def solve_E09(r: Runner, rule_seed: int) -> None:
    """Shoot the gunpowder barrel from outside the door, out of its blast: the fire runs along the
    oil to the posts, the bunker burns and takes the guard with it; then walk to the wand."""
    events = shoot_barrel_from(r, back=10)
    assert events is not None, "the barrel did not blow"
    assert blast_damage(events) == 0, "the player was in the blast"
    wait_for_fire_out(r, tuple(r.meta["regions"]["hall"]), limit=2400)
    wx, _wy, ww, _wh = r.meta["regions"]["reward"]
    assert r.walk_to(wx + ww / 2, tol=2, max_frames=1500), "could not walk to the wand"
    collect(r, ("wand",), limit=1)


def check_E09(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if r.entities("shotgunner"):
        problems.append("the guard is alive")
    if r.count("wood", tuple(r.meta["regions"]["bunker"])) > 0:
        problems.append("the bunker is still standing")
    if len(r.p["wands"]) < 3:
        problems.append("did not get the wand")
    if r.hp < 80:
        problems.append(f"only {r.hp:.0f} HP left")
    return problems


# ----------------------------------------------------------------------------------- E10


@solver("E10")
def solve_E10(r: Runner, rule_seed: int) -> None:
    """Swim across the pit at the surface and take the wand on the far ledge."""
    way = enter_room(r, depth=3)
    pool = r.meta["regions"]["pool"]
    swim_across(r, pool, way)
    collect(r, ("wand",), limit=1)


def check_E10(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if len(r.p["wands"]) < 3:
        problems.append("did not get the wand")
    if r.hp < 30:
        problems.append(f"only {r.hp:.0f} HP left")
    return problems


# ----------------------------------------------------------------------------------- E21


def hurt(r: Runner, to_hp: float) -> None:
    """Take the player down to ``to_hp`` (displayed HP) with a blast on the spot."""
    cx, cy = r.center()
    missing = (r.hp - to_hp) / 25.0 / 0.35  # internal units, the player takes 0.35 of a blast
    r.g.blast(int(cx), int(cy), 3, missing, 20000, 10, 0)
    r.wait(2)


@solver("E21")
def solve_E21(r: Runner, rule_seed: int) -> None:
    """Hurt on arrival: take the four bottles, look at what each holds (the state lists their
    contents; an agent uses inspect) and drink the healing potion."""
    enter_room(r, depth=6)
    hurt(r, 20.0)
    collect(r, ("bottle", "potion_heal"), limit=4)
    idx = bottle_with(r, ["potion_heal"])
    assert idx is not None, f"no healing potion among {[b['material'] for b in r.p['bottles']]}"
    r.step(2, select_bottle=idx)
    r.step(50, select_bottle=idx, drink=True)
    r.g.end_bottle_action()


def check_E21(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if r.hp < 90:
        problems.append(f"only {r.hp:.0f} HP after drinking the potion")
    if r.p["statuses"].get("poisoned") or r.p["statuses"].get("drunk"):
        problems.append(f"drank something else too: {sorted(r.p['statuses'])}")
    return problems


# ----------------------------------------------------------------------------------- E24


@solver("E24")
def solve_E24(r: Runner, rule_seed: int) -> None:
    """Swim the first pool (slime: nothing happens), then in the second room read the labels
    (the vial is toxic sludge), pour a splash of the bottle of water on the pool (it turns the
    sludge into water), swim across and take the wand."""
    way = enter_room(r, depth=6)
    regions = r.meta["regions"]
    collect(r, ("bottle",), limit=1)  # the vial beside the first pool
    swim_across(r, regions["pool_a"], way)
    px, pw = regions["partition"][0], regions["partition"][2]
    r.walk_to(px + pw + 4 if way > 0 else px - 3, tol=1.5)
    collect(r, ("bottle",), limit=2)  # the vial and the water beside the second
    water = bottle_with(r, ["water"])
    assert water is not None, f"no water among {[b['material'] for b in r.p['bottles']]}"
    bx, _by, bw, _bh = regions["pool_b"]
    r.walk_to(bx - 7 if way > 0 else bx + bw + 6, tol=1.0)  # keep the hit box out of the pool
    r.step(2, select_bottle=water)
    r.step(3, select_bottle=water, pour=True, aim=-35 if way > 0 else 215)  # a splash is enough
    r.g.end_bottle_action()
    r.wait(120)
    swim_across(r, regions["pool_b"], way)
    collect(r, ("wand",), limit=1)


def check_E24(r: Runner) -> list[str]:
    problems = []
    if r.dead:
        problems.append("the player died")
    if len(r.p["wands"]) < 3:
        problems.append("did not get the wand")
    if r.p["statuses"].get("poisoned"):
        problems.append("was poisoned")
    left = r.count("toxic_sludge", tuple(r.meta["regions"]["pool_b"]))
    if left > 10:
        problems.append(f"{left} cells of sludge are left in the pool")
    return problems
