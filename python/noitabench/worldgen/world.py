"""The generated world and its file pair (contracts section 4, ``cogbench-world/0``)."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from .config import Materials

FORMAT = "cogbench-world/0"
REQUIRED_KEYS = (
    "seed",
    "rule_seed",
    "width",
    "height",
    "biome_cell_size",
    "biome_map",
    "markers",
)


@dataclass
class World:
    seed: int
    rule_seed: int
    grid: np.ndarray  # (height, width) uint8 material indices
    biome_cell_size: int
    biome_map: list[list[str]]
    markers: list[dict]
    meta: dict = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.grid.shape[1])

    @property
    def height(self) -> int:
        return int(self.grid.shape[0])

    def markers_of(self, kind: str) -> list[dict]:
        return [m for m in self.markers if m["type"] == kind]

    # ---------------------------------------------------------------- files
    def png_bytes(self, mats: Materials) -> bytes:
        img = Image.frombytes("P", (self.width, self.height), self.grid.tobytes())
        img.putpalette(mats.palette())
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=9)
        return buf.getvalue()

    def json_text(self) -> str:
        """Stable JSON: one top-level key per line, one marker per line."""

        def dump(o) -> str:
            return json.dumps(o, ensure_ascii=False, separators=(", ", ": "))

        lines = [
            f'  "format": {dump(FORMAT)}',
            f'  "seed": {self.seed}',
            f'  "rule_seed": {self.rule_seed}',
            f'  "width": {self.width}',
            f'  "height": {self.height}',
            f'  "biome_cell_size": {self.biome_cell_size}',
            '  "biome_map": [\n' + ",\n".join("    " + dump(r) for r in self.biome_map) + "\n  ]",
            '  "markers": [\n' + ",\n".join("    " + dump(m) for m in self.markers) + "\n  ]",
            f'  "meta": {dump(self.meta)}',
        ]
        return "{\n" + ",\n".join(lines) + "\n}\n"

    def write(self, out_dir: Path | str, name: str, mats: Materials) -> tuple[Path, Path]:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        png, js = out / f"{name}.png", out / f"{name}.json"
        png.write_bytes(self.png_bytes(mats))
        js.write_text(self.json_text(), encoding="utf-8")
        return png, js


def load_world(png_path: Path | str, json_path: Path | str) -> World:
    """Read a world file pair back (used by tests and the preview tool)."""
    try:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ValueError(f"{json_path}: cannot read world JSON ({err})") from err
    if data.get("format") != FORMAT:
        raise ValueError(f"{json_path}: format must be {FORMAT}")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"{json_path}: missing fields {missing}")
    img = Image.open(png_path)
    if img.mode != "P":
        raise ValueError(f"{png_path}: expected an 8-bit indexed PNG, got mode {img.mode}")
    grid = np.array(img, dtype=np.uint8)
    if grid.shape != (data["height"], data["width"]):
        raise ValueError(f"{png_path}: size does not match {json_path}")
    return World(
        data["seed"],
        data["rule_seed"],
        grid,
        data["biome_cell_size"],
        data["biome_map"],
        data["markers"],
        data.get("meta", {}),
    )
