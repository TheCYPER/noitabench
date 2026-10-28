"""Thin Python wrapper over the compiled simulation core (`noitabench_core.Env`).

All behaviour lives in Rust; this class only adds type hints, docstrings and a numpy view of
the grid. The method names and semantics are the contract of
`.trellis/spec/backend/contracts.md` section 6; later weeks extend this class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import noitabench_core
except ImportError as exc:  # pragma: no cover - only without a build
    raise ImportError(
        "noitabench_core is not built. From the repo root run: "
        "maturin develop --uv --release -m crates/py/Cargo.toml"
    ) from exc


class Env:
    """A simulated world of `width` x `height` cells, driven at 60 frames per second."""

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
        self._core = noitabench_core.Env(width, height, seed, content_dir, rule_seed, recipes)

    @classmethod
    def from_world(
        cls,
        png_path: str | Path,
        json_path: str | Path,
        seed: int | None = None,
        *,
        content_dir: str | Path | None = None,
        recipes: list[dict[str, Any]] | None = None,
    ) -> Env:
        """Load a world file pair (indexed PNG plus JSON side file, contract section 4). The
        world has the secret recipes of the rule seed in its file; `recipes` replaces them (`[]`
        for none)."""
        env = cls.__new__(cls)
        env._core = noitabench_core.Env.from_world(png_path, json_path, seed, content_dir, recipes)
        return env

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
        """Material keys in index order: `keys[i]` is the material with cell value `i`."""
        return self._core.material_keys()

    # -- running --------------------------------------------------------------------------------

    def step_frames(self, n: int) -> None:
        """Advance `n` frames."""
        self._core.step_frames(n)

    def paint(self, x: int, y: int, radius: int, material_key: str) -> None:
        """Paint a filled disc of a material."""
        self._core.paint(x, y, radius, material_key)

    def fill_rect(self, x: int, y: int, w: int, h: int, material_key: str) -> None:
        """Fill the rectangle `[x, x+w) x [y, y+h)` with a material."""
        self._core.fill_rect(x, y, w, h, material_key)

    def ignite(self, x: int, y: int) -> bool:
        """Set a burnable cell alight; returns whether it caught."""
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
        """Run a ray explosion now; returns the number of cells destroyed."""
        return self._core.explode(x, y, radius, ray_energy, max_durability, fire_percent)

    # -- looking --------------------------------------------------------------------------------

    def grid(self) -> bytes:
        """`width * height` bytes: the material index of every cell, row-major."""
        return self._core.grid()

    def grid_array(self) -> Any:
        """The grid as a `(height, width)` uint8 numpy array (a copy)."""
        import numpy as np

        return np.frombuffer(self.grid(), dtype=np.uint8).reshape(self.height, self.width).copy()

    def cell(self, x: int, y: int) -> dict[str, Any]:
        """`{material, index, burning, lifetime}` of one cell."""
        return self._core.cell(x, y)

    def events(self) -> list[dict[str, Any]]:
        """Events since the last call (reactions, ignitions, extinguishing, explosions)."""
        return self._core.events()

    def state_hash(self) -> int:
        """Hash of the full simulation state; equal states have equal hashes."""
        return self._core.state_hash()

    def awake_chunks(self) -> int:
        """How many 64x64 chunks will be visited next frame."""
        return self._core.awake_chunks()

    # -- questions about the grid (entities and projectiles ask these) -----------------------------

    def overlap(self, x: int, y: int, w: int, h: int) -> dict[str, Any]:
        """What lies under the box `[x, x+w) x [y, y+h)`.

        Returns `{inside, outside, burning, kinds, materials}`: cell counts inside and beyond the
        world edge, burning cells, and the non-zero counts per kind and per material key.
        """
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
        """First cell on the line `(x0, y0)` to `(x1, y1)` that `mask` stops on, or `None`.

        `mask` is a preset (`any`, `surfaces`, `surfaces_and_liquids`, `platforms`, `blocking`) or
        a list of kinds (`air`, `gas`, `fire`, `liquid`, `powder`, `static`); `ignore` names one
        material key that does not stop the line. Cells outside the world always stop it. The
        hit is `{x, y, material, kind, last_free, step, steps}`.
        """
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
        """Move the box by `(dx, dy)`, sideways first, stopping at what `mask` blocks.

        Returns `{x, y, blocked_x, blocked_y, climbed}`; `blocked_*` is the key of the material
        that cut the move short (or `None`), `climbed` the cells lifted over ledges (`step_up`).
        """
        return self._core.sweep_box(x, y, w, h, dx, dy, mask, step_up, ignore)

    def contact_damage(
        self, x: int, y: int, w: int, h: int, *, min_cells: int = 4, max_cells: int = 85
    ) -> dict[str, Any]:
        """Raw contact damage of one frame on the box, from the damage table in `materials.json`.

        A material counts from `min_cells` cells and for at most `max_cells`. Returns
        `{raw, parts}` with `parts` a list of `{material, cells, counted, damage}` (`cells`:
        overlap, `counted`: `min(cells, max_cells)`). Multiply `raw` by 25 for the displayed value.
        """
        return self._core.contact_damage(x, y, w, h, min_cells, max_cells)

    # -- state ----------------------------------------------------------------------------------

    def snapshot(self) -> bytes:
        """The full state, restorable bit-exactly with `restore`."""
        return self._core.snapshot()

    def restore(self, blob: bytes) -> None:
        """Replace the state with a snapshot. Pending events are cleared."""
        self._core.restore(blob)

    def set_all_dirty(self, enabled: bool) -> None:
        """Test switch: visit every cell every frame instead of only the awake chunks."""
        self._core.set_all_dirty(enabled)

    # -- recording ------------------------------------------------------------------------------

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
        """Write a `cogbench-rec/0` recording into `dir`, one frame every `frame_stride`."""
        self._core.start_recording(dir, frame_stride, rect, run_id, notes, created)

    def stop_recording(self) -> dict[str, Any]:
        """Finish the recording; returns `{dir, frames, first_frame, last_frame}`."""
        return self._core.stop_recording()
