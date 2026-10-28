"""Thin Python wrapper over `noitabench_core.Game`: the world plus the player, enemies, items.

All behaviour lives in Rust (`crates/game`); this class adds type hints, docstrings and a few
conveniences for scripts. Contract: `.trellis/spec/backend/contracts.md` sections 6 and 11.

A game is stepped one frame at a time (60 per second) under the player's controls. Controls are a
plain dict; keys that are missing are off:

    move       -1, 0 or 1
    jump, fly, fire, kick, interact, drink, pour, fill, throw      True while held
    aim        degrees: 0 is right, 90 is up, -90 is down
    select_wand, select_bottle      index of the wand or bottle to hold
    drop       {"wand": i}, {"spell": i} or {"bottle": i}: put that thing on the ground beside
               the player (None, or leaving the key out, drops nothing)

`jump`, `kick`, `interact` and `throw` act on the frame they go from off to on; `drop` acts on the
frame it appears or its value changes (holding the same value drops nothing more).

A bottle holds a mixture of materials up to its capacity (400 cells). `player()["bottles"]` lists
`{material, amount, contents}` per bottle: `contents` is `[{material, amount}, ...]` by material
index, `amount` the cells in all and `material` the one with the largest share (`None` when the
bottle is empty).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

try:
    import noitabench_core
except ImportError as exc:  # pragma: no cover - only without a build
    raise ImportError(
        "noitabench_core is not built. From the repo root run: "
        "maturin develop --uv --release -m crates/py/Cargo.toml"
    ) from exc

Controls = dict[str, Any]


def aim_at(from_xy: tuple[float, float], to_xy: tuple[float, float]) -> float:
    """The aim in degrees that points from one cell to another (y grows downward)."""
    return math.degrees(math.atan2(-(to_xy[1] - from_xy[1]), to_xy[0] - from_xy[0]))


class Game:
    """A simulated world with a player, enemies and items."""

    def __init__(
        self,
        width: int,
        height: int,
        seed: int,
        *,
        content_dir: str | Path | None = None,
        rule_seed: int | None = None,
        recipes: list[dict[str, Any]] | None = None,
    ) -> None:
        """An empty world. It has no secret recipes unless you give a `rule_seed` (the recipes of
        that seed, `noitabench_core.recipes(rule_seed)`) or your own `recipes`
        (`[{"potion": key, "inputs": [a, b, c]}]`)."""
        self._core = noitabench_core.Game(width, height, seed, content_dir, rule_seed, recipes)

    @classmethod
    def from_world(
        cls,
        png_path: str | Path,
        json_path: str | Path,
        seed: int | None = None,
        *,
        rule_seed: int | None = None,
        reactions_json: str | None = None,
        reactions_path: str | Path | None = None,
        recipes: list[dict[str, Any]] | None = None,
    ) -> Game:
        """Load a world file pair and place its player, enemies and items.

        Every world runs the original reaction table. Its secret recipes are those of the rule
        seed (the `rule_seed` argument, or the one in the world file); `recipes`
        (`[{"potion": key, "inputs": [a, b, c]}]`, `[]` for none) replaces them.
        `reactions_json` (the text of a `cogbench-reactions/0` file) or `reactions_path` is only
        for tests of other tables; text equal to the original table changes nothing.
        """
        if reactions_path is not None:
            if reactions_json is not None:
                raise ValueError("give reactions_json or reactions_path, not both")
            reactions_json = Path(reactions_path).read_text(encoding="utf-8")
        game = cls.__new__(cls)
        game._core = noitabench_core.Game.from_world(
            png_path, json_path, seed, rule_seed, reactions_json, recipes
        )
        return game

    # -- properties -----------------------------------------------------------------------------

    @property
    def width(self) -> int:
        return self._core.width

    @property
    def height(self) -> int:
        return self._core.height

    @property
    def frame(self) -> int:
        """Frames simulated so far."""
        return self._core.frame

    @property
    def seed(self) -> int:
        return self._core.seed

    @property
    def rule_seed(self) -> int:
        return self._core.rule_seed

    @property
    def content_hash(self) -> int:
        """Hash of the materials, reactions and tuning in use."""
        return self._core.content_hash

    def material_keys(self) -> list[str]:
        return self._core.material_keys()

    def spell_keys(self) -> list[str]:
        """The 25 spells, in catalogue order."""
        return self._core.spell_keys()

    def enemy_kinds(self) -> list[str]:
        return self._core.enemy_kinds()

    # -- running --------------------------------------------------------------------------------

    def step(self, frames: int = 1, controls: Controls | list[Controls] | None = None) -> None:
        """Advance `frames` frames. `controls` is one dict held throughout, or one dict per
        frame; `None` holds nothing."""
        self._core.step(frames, controls)

    # -- looking --------------------------------------------------------------------------------

    def player(self) -> dict[str, Any] | None:
        """The player: collision box `x, y, w, h` (top-left corner), `hit` box, velocity, `hp`
        and `hp_max` (displayed units, 100 is full), `dead`, `on_ground`, `fly` and `breath`
        (0 to 1), `statuses` (name to frames left), `wands`, `spells`, `bottles`. `None` before
        the player is spawned."""
        return self._core.player()

    def entities(self) -> list[dict[str, Any]]:
        """Player, enemies, items and projectiles: `{id, kind, x, y, w, h, hp, hp_max, vx, vy,
        detail, statuses}` with the visible box of each. A bottle also has `contents` (`[{material,
        amount}, ...]`) and a wand lying on the ground has `wand` (the same dict as in
        `player()["wands"]`)."""
        return self._core.entities()

    def events(self) -> list[dict[str, Any]]:
        """Events since the last call: reactions, explosions and the game's own (`cast`, `hit`,
        `damage`, `death`, `pickup`, `drink`, `barrel_break`, ...)."""
        return self._core.events()

    def markers(self) -> list[dict[str, Any]]:
        """Markers of the loaded world that are not spawns (encounters, rest areas, the seal)."""
        return self._core.markers()

    def state_hash(self) -> int:
        """Hash of the whole state; equal states have equal hashes."""
        return self._core.state_hash()

    # -- state ----------------------------------------------------------------------------------

    def snapshot(self) -> bytes:
        """The whole game, restorable bit-exactly with `restore`."""
        return self._core.snapshot()

    def restore(self, blob: bytes) -> None:
        self._core.restore(blob)

    def start_recording(
        self,
        dir: str | Path,
        frame_stride: int,
        rect: tuple[int, int, int, int] | None = None,
        *,
        run_id: str | None = None,
        notes: str | None = None,
        created: str | None = None,
    ) -> None:
        """Record the world and its entities (`entities.jsonl`) into `dir`."""
        self._core.start_recording(dir, frame_stride, rect, run_id, notes, created)

    def stop_recording(self) -> dict[str, Any]:
        return self._core.stop_recording()

    # -- building scenes ------------------------------------------------------------------------

    def spawn_player(self, x: int, y: int) -> int:
        """Put the player, with the starter wands, in the cell `(x, y)` it stands in (the free
        cell right above the floor)."""
        return self._core.spawn_player(x, y)

    def spawn_enemy(self, kind: str, x: int, y: int) -> int:
        """`longleg` (Hämis), `shotgunner` (Haulikkohiisi) or `firemage_weak` (Stendari)."""
        return self._core.spawn_enemy(kind, x, y)

    def spawn_item(
        self,
        kind: str,
        x: int,
        y: int,
        *,
        material: str | None = None,
        amount: int | None = None,
        tier: int | None = None,
        spell: str | None = None,
        stats: dict[str, Any] | None = None,
        spells: list[str | None] | None = None,
        contents: list[dict[str, Any]] | None = None,
    ) -> int:
        """Put an item in the cell `(x, y)`: `bottle` (`material`, `amount`, or a mixture as
        `contents=[{"material": key, "amount": cells}, ...]`), a potion
        (`potion_heal`, `potion_mana`, `potion_haste` and the eight secret potions, which the world
        never places: `potion_lively`, `potion_invulnerable`, `potion_mana_regen`, `potion_crit`,
        `potion_berserk`, `potion_levitation`, `potion_invisible`, `potion_fireproof`), `wand` (a generated one
        of `tier`, or your own with `stats` and `spells`), `spell` (a random one or `spell`) or a
        barrel (`barrel_gunpowder`, `barrel_acid`, `barrel_oil`)."""
        return self._core.spawn_item(
            kind,
            x,
            y,
            material=material,
            amount=amount,
            tier=tier,
            spell=spell,
            stats=stats,
            spells=spells,
            contents=contents,
        )

    def give_wand(
        self,
        stats: dict[str, Any],
        spells: list[str | None],
        always_cast: list[str] | None = None,
    ) -> int:
        """Hand the player a wand. `stats` needs `cast_delay`, `recharge`, `mana_max`,
        `mana_charge_speed` and `capacity`; `shuffle`, `spells_per_cast`, `spread` and
        `speed_multiplier` are optional."""
        return self._core.give_wand(stats, spells, always_cast)

    def give_spell(self, key: str) -> None:
        self._core.give_spell(key)

    def give_bottle(
        self,
        material: str | None = None,
        amount: int | None = None,
        *,
        contents: list[dict[str, Any]] | None = None,
    ) -> None:
        """Hand the player a bottle: `amount` cells of `material` (a full bottle by default; empty
        without a material), or a mixture as `contents=[{"material": key, "amount": cells}, ...]`
        (at most the capacity in all)."""
        self._core.give_bottle(material, amount, contents)

    def end_bottle_action(self) -> None:
        """End the drink, pour or fill in progress now, writing its summary events on this frame
        (otherwise they are written when the key is next let go)."""
        self._core.end_bottle_action()

    def edit_wand(self, action: dict[str, Any]) -> None:
        """One wand-editor action: `{"op": "place", "wand": 0, "slot": 1, "from": 0}` (a carried
        spell into a slot), `{"op": "take", "wand": 0, "slot": 1}` or
        `{"op": "swap", "wand": 0, "a": 0, "b": 1}`."""
        self._core.edit_wand(action)

    def blast(
        self,
        x: int,
        y: int,
        radius: int,
        damage: float = 0.0,
        ray_energy: int = 20000,
        max_durability: int = 10,
        fire_percent: int = 5,
    ) -> None:
        """An explosion at `(x, y)` that carves the grid and hurts what it reaches. `damage` is
        in internal units (the player has 4.0)."""
        self._core.blast(x, y, radius, damage, ray_energy, max_durability, fire_percent)

    # -- the pixel world ------------------------------------------------------------------------

    def paint(self, x: int, y: int, radius: int, material_key: str) -> None:
        self._core.paint(x, y, radius, material_key)

    def fill_rect(self, x: int, y: int, w: int, h: int, material_key: str) -> None:
        self._core.fill_rect(x, y, w, h, material_key)

    def ignite(self, x: int, y: int) -> bool:
        return self._core.ignite(x, y)

    def explode(
        self,
        x: int,
        y: int,
        radius: int,
        ray_energy: int,
        max_durability: int,
        fire_percent: int = 5,
    ) -> int:
        """Carve the grid with a ray explosion (no damage); returns the cells destroyed."""
        return self._core.explode(x, y, radius, ray_energy, max_durability, fire_percent)

    def grid(self) -> bytes:
        return self._core.grid()

    def grid_array(self) -> Any:
        """The grid as a `(height, width)` uint8 numpy array (a copy)."""
        import numpy as np

        return np.frombuffer(self.grid(), dtype=np.uint8).reshape(self.height, self.width).copy()

    def cell(self, x: int, y: int) -> dict[str, Any]:
        return self._core.cell(x, y)

    def burning_rect(self, x: int, y: int, w: int, h: int) -> bytes:
        """Which cells of the rectangle `[x, x+w) x [y, y+h)` are burning: `w * h` bytes,
        row-major, 1 for a burning cell and 0 for any other (and outside the world)."""
        return self._core.burning_rect(x, y, w, h)

    def overlap(self, x: int, y: int, w: int, h: int) -> dict[str, Any]:
        return self._core.overlap(x, y, w, h)

    def raycast(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        mask: str | list[str] = "blocking",
        *,
        ignore: str | None = None,
    ) -> dict[str, Any] | None:
        return self._core.raycast(x0, y0, x1, y1, mask, ignore)

    def sweep_box(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        dx: int,
        dy: int,
        mask: str | list[str] = "blocking",
        *,
        step_up: int = 0,
        ignore: str | None = None,
    ) -> dict[str, Any]:
        return self._core.sweep_box(x, y, w, h, dx, dy, mask, step_up, ignore)

    def contact_damage(
        self, x: int, y: int, w: int, h: int, *, min_cells: int = 4, max_cells: int = 85
    ) -> dict[str, Any]:
        return self._core.contact_damage(x, y, w, h, min_cells, max_cells)


def read_events(path: str | Path) -> list[dict[str, Any]]:
    """The events of a recording (`events.jsonl`)."""
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def wand_trial(
    stats: dict[str, Any],
    slots: list[Any],
    *,
    frames: int = 600,
    seed: int = 0,
    always_cast: list[str] | None = None,
    keep_casts: int = 64,
) -> dict[str, Any]:
    """The wand practice range: hold the fire key on a wand outside any world for `frames` frames
    (at most 7,200) and report each click, the mana, and the damage to a dummy that every shot
    hits. `stats` is a wand-stats dict (as for `Game.give_wand`); `slots` has one entry per slot:
    `None`, a spell key, or `{"spell": key, "uses": n}`. `seed` only matters for a shuffle wand.
    Damage is in displayed HP. Read-only: no game is involved (contracts section 9). Numbers
    that do not fit the engine's integers raise `ValueError`, like every other bad input."""
    try:
        return noitabench_core.wand_trial(
            stats,
            slots,
            frames=frames,
            seed=seed,
            always_cast=always_cast,
            keep_casts=keep_casts,
        )
    except OverflowError as err:  # an integer too big for the engine's 32 bits
        raise ValueError(f"a number is out of range: {err}") from err
