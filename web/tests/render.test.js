import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { VARIANTS, buildPalette, buildVariantMap, paintRgba } from '../js/render/palette.js';
import { ZOOM_LEVELS, View } from '../js/render/view.js';
import { colorOf, hueOf } from '../js/render/colors.js';
import { parseMaterials } from '../js/format/materials.js';
import { MATERIALS_PATH } from './helpers.js';

const table = parseMaterials(JSON.parse(readFileSync(MATERIALS_PATH, 'utf8')));
const px = (pal, m, v = 0) => [...pal.subarray((m * VARIANTS + v) * 3, (m * VARIANTS + v) * 3 + 3)];

test('palette: material colours come from materials.json', () => {
  const pal = buildPalette(table, { shade: false });
  assert.deepEqual(px(pal, 4), [0x2f, 0x6f, 0xc4]); // water
  assert.deepEqual(px(pal, 0), [0x14, 0x0f, 0x0c]); // air
});

test('palette: only static terrain is shaded, and within +-12 %', () => {
  const pal = buildPalette(table, { shade: true });
  const rock = table.rgb.subarray(15 * 3, 15 * 3 + 3);
  const shades = new Set();
  for (let v = 0; v < VARIANTS; v++) {
    const c = px(pal, 15, v);
    shades.add(c.join());
    c.forEach((ch, i) => assert.ok(Math.abs(ch - rock[i]) <= Math.ceil(rock[i] * 0.12) + 1, `rock variant ${v}`));
  }
  assert.ok(shades.size > 1);
  for (let v = 0; v < VARIANTS; v++) assert.deepEqual(px(pal, 11, v), px(pal, 11, 0)); // sand is a powder: flat
  for (let v = 0; v < VARIANTS; v++) assert.deepEqual(px(pal, 4, v), px(pal, 4, 0)); // water too
});

test('variant map depends on position only and uses every variant', () => {
  const a = buildVariantMap(40, 30);
  const b = buildVariantMap(40, 30);
  assert.deepEqual(a, b);
  assert.equal(new Set(a).size, VARIANTS);
  assert.ok(a.every((v) => v < VARIANTS));
});

test('paintRgba writes opaque RGBA from indexes', () => {
  const pal = buildPalette(table, { shade: false });
  const out = new Uint8ClampedArray(3 * 4);
  paintRgba(Uint8Array.from([4, 0, 11]), pal, null, out);
  assert.deepEqual([...out], [0x2f, 0x6f, 0xc4, 255, 0x14, 0x0f, 0x0c, 255, 0xd9, 0xb5, 0x6a, 255]);
});

test('colors are stable per key', () => {
  assert.equal(hueOf('mine'), hueOf('mine'));
  assert.notEqual(hueOf('mine'), hueOf('marsh'));
  assert.match(colorOf('x', 0.5), /^hsla\(\d+, 65%, 60%, 0\.5\)$/);
});

function view(w, h, bounds, dpr = 1) {
  const v = new View();
  Object.assign(v, { cssW: w, cssH: h, dpr, bounds });
  return v;
}

test('view: fit picks the largest zoom level that shows everything', () => {
  const v = view(990, 490, { x0: 0, y0: 0, x1: 128, y1: 96 });
  assert.equal(v.fitZoom(), 4); // 490/96 = 5.1 -> 4 (5 is not a level)
  const big = view(400, 300, { x0: 0, y0: 0, x1: 768, y1: 1664 });
  assert.equal(big.fitZoom(), 0.25); // would need 0.17: never below the smallest level
  assert.ok(ZOOM_LEVELS.includes(view(1000, 1000, { x0: 0, y0: 0, x1: 100, y1: 100 }).fitZoom()));
});

test('view: a small world is centred, a big one is clamped to its edges', () => {
  const v = view(1000, 500, { x0: 0, y0: 0, x1: 100, y1: 50 });
  v.fit(); // zoom 8 -> 800x400 centred
  assert.equal(v.zoom, 8);
  assert.equal(v.sx(0), 100);
  assert.equal(v.sy(0), 50);
  const w = view(200, 200, { x0: 0, y0: 0, x1: 1000, y1: 1000 });
  w.zoom = 2;
  w.panBy(-5000, -5000);
  assert.deepEqual([w.ox, w.oy], [0, 0]);
  w.panBy(99999, 99999);
  assert.deepEqual([w.ox, w.oy], [1000 - 100, 1000 - 100]); // viewport shows 100x100 cells
});

test('view: zooming keeps the point under the pointer fixed', () => {
  const v = view(400, 400, { x0: 0, y0: 0, x1: 1000, y1: 1000 });
  v.zoom = 2;
  v.ox = 300;
  v.oy = 200;
  const before = { x: v.wx(150), y: v.wy(90) };
  v.zoomStep(1, 150, 90); // 2 -> 3
  assert.equal(v.zoom, 3);
  assert.ok(Math.abs(v.wx(150) - before.x) < 1 / (3 * v.dpr) + 1e-9);
  assert.ok(Math.abs(v.wy(90) - before.y) < 1 / (3 * v.dpr) + 1e-9);
  v.zoomStep(-1);
  v.zoomStep(-1);
  assert.equal(v.zoom, 1);
});

test('view: zoom steps stop at the ends of the level list', () => {
  const v = view(400, 400, { x0: 0, y0: 0, x1: 1000, y1: 1000 });
  for (let i = 0; i < 30; i++) v.zoomStep(1);
  assert.equal(v.zoom, ZOOM_LEVELS[ZOOM_LEVELS.length - 1]);
  for (let i = 0; i < 30; i++) v.zoomStep(-1);
  assert.equal(v.zoom, ZOOM_LEVELS[0]);
});

test('view: camera offsets snap to whole device pixels', () => {
  const v = view(400, 400, { x0: 0, y0: 0, x1: 1000, y1: 1000 }, 1.75);
  v.zoom = 3;
  v.panBy(1, 1); // 1/3 of a cell
  const k = v.zoom * v.dpr;
  assert.ok(Math.abs(v.ox * k - Math.round(v.ox * k)) < 1e-6);
});
