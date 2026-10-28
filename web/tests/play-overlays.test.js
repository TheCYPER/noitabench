import test from 'node:test';
import assert from 'node:assert/strict';
import { drawAim, drawBurning, drawPlayerBox, drawVisible } from '../js/render/play-overlays.js';
import { View } from '../js/render/view.js';
import { decodeView } from '../js/play/view-data.js';
import { fixtureJson } from './helpers.js';

/** A 2D context stand-in that records calls; properties can be set freely. */
function stubCtx() {
  const calls = [];
  const target = { calls };
  return new Proxy(target, {
    get(t, name) {
      if (name in t) return t[name];
      return (...args) => { calls.push([name, ...args]); };
    },
    set(t, name, value) { t[name] = value; return true; },
  });
}
const rects = (ctx) => ctx.calls.filter((c) => c[0] === 'fillRect').map((c) => c.slice(1));

function camera({ zoom = 2, ox = 0, oy = 0, w = 400, h = 300 } = {}) {
  const v = new View();
  Object.assign(v, { cssW: w, cssH: h, zoom, ox, oy });
  return v;
}

/** A 4 x 3 view with the cells in `lit` burning. */
const tinyView = (lit) => ({
  origin: { x: 100, y: 50 },
  width: 4,
  height: 3,
  burning: Uint8Array.from({ length: 12 }, (_, i) => (lit.includes(i) ? 1 : 0)),
});

test('drawBurning paints one square per burning cell, where the cell is on screen', () => {
  const ctx = stubCtx();
  // cells 0 = (100,50), 5 = (101,51), 11 = (103,52)
  drawBurning(ctx, camera({ zoom: 3, ox: 100, oy: 50 }), tinyView([0, 5, 11]));
  assert.deepEqual(rects(ctx), [[0, 0, 3, 3], [3, 3, 3, 3], [9, 6, 3, 3]]);
});

test('drawBurning with nothing burning draws nothing; far out it still draws at least a pixel', () => {
  const none = stubCtx();
  drawBurning(none, camera(), tinyView([]));
  assert.deepEqual(rects(none), []);
  const far = stubCtx();
  drawBurning(far, camera({ zoom: 0.25, ox: 100, oy: 50 }), tinyView([5]));
  assert.deepEqual(rects(far), [[0.25, 0.25, 1, 1]]);
});

test('drawBurning skips cells that are off the canvas', () => {
  const ctx = stubCtx();
  // the camera starts at x = 102: cells 0 and 1 of the first row are to the left of the canvas
  drawBurning(ctx, camera({ zoom: 10, ox: 102, oy: 50, w: 20, h: 10 }), tinyView([0, 1, 2, 3, 4]));
  assert.deepEqual(rects(ctx).map((r) => r.slice(0, 2)), [[0, 0], [10, 0]], 'cells (102,50) and (103,50); the next row is below');
});

test('the fire of a real answer of the server lands on the cells the game says burn', () => {
  const { response, expected } = fixtureJson('play_state.json');
  const view = decodeView(response.view);
  const cam = camera({ zoom: 4, ox: view.origin.x, oy: view.origin.y, w: 4 * view.width, h: 4 * view.height });
  const ctx = stubCtx();
  drawBurning(ctx, cam, view);
  const drawn = rects(ctx).map(([x, y]) => [view.origin.x + x / 4, view.origin.y + y / 4]);
  assert.deepEqual(drawn, expected.burning_cells);
});

test('drawVisible: a box per thing, hostile ones red, a label only when zoomed in, no health anywhere', () => {
  const things = [
    { id: 7, kind: 'longleg', x: 10, y: 20, w: 6, h: 8, hostile: true, aimed: true },
    { id: 9, kind: 'bottle', x: 40, y: 20, w: 3, h: 5 },
    { id: 3, kind: 'wand', x: 5000, y: 20, w: 3, h: 5 },
  ];
  const near = stubCtx();
  drawVisible(near, camera({ zoom: 2 }), things);
  assert.equal(near.calls.filter((c) => c[0] === 'strokeRect').length, 2, 'the third is off screen');
  assert.deepEqual(near.calls.filter((c) => c[0] === 'fillText').map((c) => c[1]), ['longleg#7', 'bottle#9']);
  const far = stubCtx();
  drawVisible(far, camera({ zoom: 1 }), things);
  assert.equal(far.calls.filter((c) => c[0] === 'fillText').length, 0, 'no labels below zoom 2');
  assert.deepEqual(rects(far).map((r) => r.slice(2)), [[6, 8], [4, 5]], 'tiny things stay at least 4 px');
});

test('drawPlayerBox and drawAim follow the player; 90 degrees aims up', () => {
  const p = { x: 10, y: 20, w: 6, h: 16 };
  const box = stubCtx();
  drawPlayerBox(box, camera({ zoom: 2 }), p);
  assert.deepEqual(box.calls.find((c) => c[0] === 'strokeRect').slice(1), [20, 40, 12, 32]);
  const aim = stubCtx();
  drawAim(aim, camera({ zoom: 1 }), p, 90, 10);
  const [, x0, y0] = aim.calls.find((c) => c[0] === 'moveTo');
  const [, x1, y1] = aim.calls.find((c) => c[0] === 'lineTo');
  assert.deepEqual([x0, y0], [13, 28]);
  assert.ok(Math.abs(x1 - 13) < 1e-9 && Math.abs(y1 - 18) < 1e-9, 'straight up: y gets smaller');
  const right = stubCtx();
  drawAim(right, camera({ zoom: 1 }), p, 0, 10);
  const [, rx, ry] = right.calls.find((c) => c[0] === 'lineTo');
  assert.ok(Math.abs(rx - 23) < 1e-9 && Math.abs(ry - 28) < 1e-9);
});
