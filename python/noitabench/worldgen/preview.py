"""Preview images: upscaled terrain with biome borders, the main path and markers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .clearance import Blast, seal_blasts
from .config import BiomeMap, Materials, load_biome_map, load_materials
from .world import World

CJK_FONTS = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)
COLORS = {
    "player": (60, 255, 90),
    "enemy": (255, 70, 70),
    "item": (255, 225, 60),
    "must": (255, 60, 220),
    "optional": (70, 220, 255),
    "rest": (90, 255, 140),
    "seal": (255, 200, 40),
    "path": (255, 40, 40),
    "border": (255, 255, 255),
    "bowl": (255, 150, 40),
    "deposit": (235, 235, 235),
    "bottle": (120, 200, 255),
    "lane": (170, 255, 90),
    "blast": (255, 120, 120),
}


def _font(size: int, cjk: bool = False) -> ImageFont.ImageFont:
    if cjk:
        for path in CJK_FONTS:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def terrain_image(world: World, mats: Materials, scale: int, shade: bool = True) -> Image.Image:
    """Terrain in material colours. ``shade`` adds a fixed, seed-independent brightness
    variation per cell (four levels) so flat areas read as terrain; without it the image
    is the world PNG's exact palette colours."""
    pal = np.array(mats.palette(), dtype=np.float32).reshape(256, 3)
    rgb = pal[world.grid]
    if shade:
        levels = np.array([0.91, 0.97, 1.03, 1.09], dtype=np.float32)
        pick = np.random.Generator(np.random.PCG64(12345)).integers(0, 4, world.grid.shape)
        rgb = rgb * levels[pick][:, :, None]
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


class _Painter:
    """Draws overlay shapes in world coordinates onto a transparent layer."""

    def __init__(self, size: tuple[int, int], scale: int, header: int):
        self.layer = Image.new("RGBA", size, (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.layer)
        self.s, self.header = scale, header
        self.small = _font(max(9, 5 * scale))
        self.label = _font(max(10, 6 * scale), cjk=True)

    def px(self, x: float, y: float) -> tuple[float, float]:
        return x * self.s, y * self.s + self.header

    def box(self, x0, y0, x1, y1, color, width=1, alpha=255) -> None:
        (a, b), (c, d) = self.px(x0, y0), self.px(x1, y1)
        self.d.rectangle([a, b, c - 1, d - 1], outline=(*color, alpha), width=width)

    def text(self, x, y, msg, color, font, alpha=255) -> None:
        self.d.text(
            self.px(x, y),
            msg,
            fill=(*color, alpha),
            font=font,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )

    # one method per marker type -------------------------------------------------
    def spawn_enemy(self, m: dict) -> None:
        x, y = self.px(m["x"], m["y"])
        self.d.rectangle([x - 2, y - 8, x + 2, y - 3], fill=(*COLORS["enemy"], 255))

    def item(self, m: dict) -> None:
        x, y = self.px(m["x"], m["y"])
        y -= 4
        shape = [(x, y - 4), (x + 4, y), (x, y + 4), (x - 4, y)]
        if m["item"] == "bottle" and m.get("contents"):
            self.d.polygon(shape, fill=(*COLORS["bottle"], 255))  # a full bottle: blue
        elif m["item"] == "bottle":
            self.d.polygon(shape, outline=(*COLORS["bottle"], 255), width=2)  # an empty one
        else:
            self.d.polygon(shape, fill=(*COLORS["item"], 255))

    def alchemy_bowl(self, m: dict) -> None:
        self.box(m["x"] - 2, m["y"], m["x"] + m["w"] + 2, m["y"] + m["h"] + 2, COLORS["bowl"], 2)
        self.text(m["x"] - 2, m["y"] - 8 * self.s // 2 - 2, "BOWL", COLORS["bowl"], self.small)

    def deposit(self, d: dict) -> None:
        x, y = self.px(d["x"], d["y"])
        self.d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(*COLORS["deposit"], 255), width=2)
        self.text(d["x"] + 4, d["y"] - 12, d["material"], COLORS["deposit"], self.small)

    def spawn_player(self, m: dict) -> None:
        x, y = self.px(m["x"], m["y"])
        y -= 6
        self.d.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(*COLORS["player"], 255), width=2)
        self.text(m["x"] + 6, m["y"] - 14, "START", COLORS["player"], self.small)

    def encounter(self, m: dict) -> None:
        t = m["trigger"]
        col = COLORS["must"] if m["must_pass"] else COLORS["optional"]
        self.box(t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"], col, 2 if m["must_pass"] else 1)
        name = (
            m["encounter_id"]
            + ("*" if m["must_pass"] else "")
            + (" (empty)" if m.get("placeholder", True) else "")
        )
        self.text(t["x"] + 2, t["y"] + 1, name, col, self.small)

    def rest_area(self, m: dict) -> None:
        self.box(m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"], COLORS["rest"], 2)
        self.text(m["x"] + 6, m["y"] + 3, f"REST {m['index']}", COLORS["rest"], self.small)

    def edit_station(self, m: dict) -> None:
        self.box(m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"], COLORS["rest"], 1)
        self.text(m["x"] + 6, m["y"] + 3, "EDIT", COLORS["rest"], self.small)

    def seal(self, m: dict) -> None:
        self.box(m["x"], m["y"], m["x"] + m["w"], m["y"] + m["h"], COLORS["seal"], 2)
        r = m["room"]
        self.box(r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"], COLORS["seal"], 1)
        self.text(r["x"] + 4, r["y"] + 2, "SEAL", COLORS["seal"], self.small)

    def clearance(self, meta: dict, blasts: list[Blast]) -> None:
        """The tunnels of the must-pass scenes and the zone round the seal key's blast (tooling
        only): no lava or acid within reach of the player's hit box inside them."""
        for lane in meta.get("clearance", {}).get("lanes", []):
            for t in lane["tunnels"]:
                self.box(t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"], COLORS["lane"], 1, 170)
        for blast in blasts:
            x0, y0, x1, y1 = blast.hall
            r = blast.radius
            (a, b), (c, d) = self.px(x0 - r, y0 - r), self.px(x1 + r, y1 + r)
            self.d.rounded_rectangle(
                [a, b, c, d], radius=r * self.s, outline=(*COLORS["blast"], 200), width=2
            )


def render_preview(
    world: World,
    mats: Materials | None = None,
    bm: BiomeMap | None = None,
    scale: int = 2,
    overlay: bool = True,
) -> Image.Image:
    """Terrain image; with ``overlay`` also biome borders, main path, markers and a header."""
    mats = mats or load_materials()
    bm = bm or load_biome_map()
    if not overlay:
        return terrain_image(world, mats, scale, shade=False)
    terrain = terrain_image(world, mats, scale)
    header = 34 * scale // 2 + 10
    canvas = Image.new("RGB", (terrain.width, terrain.height + header), (18, 18, 22))
    canvas.paste(terrain, (0, header))
    paint = _Painter(canvas.size, scale, header)
    seen: set[str] = set()
    for key in sorted({k for row in world.biome_map for k in row}):
        x0, y0, x1, y1 = bm.region(key)
        paint.box(x0, y0, x1, y1, COLORS["border"], 1, 90)
        if key not in seen:
            seen.add(key)
            b = bm.biomes.get(key)
            title = f"{b.name_en} {b.name_zh}" if b else key.replace("_", " ").title()
            paint.text(x0 + 4, y0 + 2, title, (255, 255, 255), paint.label, 230)
    pts = [paint.px(x, y) for x, y in world.meta.get("main_path", [])]
    if len(pts) > 1:
        paint.d.line(pts, fill=(*COLORS["path"], 200), width=max(2, scale))
    for d in world.meta.get("deposits", []):  # ingredient deposits (not markers: tooling only)
        paint.deposit(d)
    paint.clearance(world.meta, seal_blasts(world.markers))
    for m in world.markers:
        draw = getattr(paint, m["type"], None)
        if draw is not None:
            draw(m)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), paint.layer).convert("RGB")
    _draw_header(canvas, world, header, scale)
    return canvas


def _draw_header(img: Image.Image, world: World, header: int, scale: int) -> None:
    d = ImageDraw.Draw(img)
    f = _font(max(11, 7 * scale))
    chk = world.meta.get("checks", {})
    d.text(
        (6, 4),
        f"seed {world.seed}  rule seed {world.rule_seed}   {world.width}x{world.height}   "
        f"attempt {world.meta.get('attempt', 0)}   "
        f"enemies {chk.get('enemies', '?')}  items {chk.get('items', '?')}  "
        f"encounters {chk.get('encounters', '?')} (must-pass {chk.get('must_pass', '?')})",
        fill=(235, 235, 235),
        font=f,
    )
    x = 6
    y = header - max(12, 7 * scale) - 3
    for name, key in (
        ("player", "player"), ("enemy", "enemy"), ("item", "item"), ("must-pass slot *", "must"),
        ("optional slot", "optional"), ("rest area", "rest"), ("seal", "seal"), ("main path", "path"),
        ("alchemy bowl", "bowl"), ("ingredient deposit", "deposit"), ("bottle", "bottle"),
        ("hazard-free tunnel", "lane"), ("key blast zone", "blast"),
    ):  # fmt: skip
        d.rectangle([x, y + 2, x + 9, y + 11], fill=COLORS[key])
        d.text((x + 13, y), name, fill=(220, 220, 220), font=f)
        x += 13 + int(d.textlength(name, font=f)) + 14


def save_preview(world: World, path: Path | str, scale: int = 2, overlay: bool = True) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    render_preview(world, scale=scale, overlay=overlay).save(
        out, format="PNG", optimize=False, compress_level=6
    )
    return out


def save_crop(
    world: World, path: Path | str, box: tuple[int, int, int, int], scale: int = 4
) -> Path:
    """Plain close-up of the world rectangle ``box`` (x0, y0, x1, y1) at ``scale``."""
    x0, y0, x1, y1 = box
    if x1 > world.width or y1 > world.height:
        raise ValueError(f"crop {box} reaches outside the {world.width}x{world.height} world")
    img = terrain_image(world, load_materials(), scale, shade=False)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.crop((x0 * scale, y0 * scale, x1 * scale, y1 * scale)).save(out, format="PNG")
    return out
