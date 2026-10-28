import test from 'node:test';
import assert from 'node:assert/strict';
import { drawBiomeGrid, drawEncounters, drawEntities, drawEventMarks, drawMainPath, drawMarkers, markerStyle } from '../js/render/overlays.js';
import { View } from '../js/render/view.js';

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
const names = (ctx) => ctx.calls.map((c) => c[0]);

function view(zoom = 2) {
  const v = new View();
  Object.assign(v, { cssW: 400, cssH: 300, zoom, bounds: { x0: 0, y0: 0, x1: 400, y1: 300 } });
  return v;
}

const world = {
  cellSize: 64,
  biomeMap: [['mine', 'mine'], ['marsh', 'future_biome']],
  markers: [
    { type: 'spawn_player', x: 10, y: 10 },
    { type: 'brand_new_type', x: 20, y: 20 },
    { type: 'rest_area', x: 30, y: 30, w: 20, h: 10 },
    { type: 'encounter', encounter_id: 'E01', variant: 1, x: 50, y: 50, trigger: { x: 40, y: 40, w: 30, h: 20 }, must_pass: true },
    { type: 'encounter', encounter_id: 'E01', variant: 2, x: 90, y: 50, trigger: { x: 80, y: 40, w: 30, h: 20 }, must_pass: false },
  ],
};

test('unknown marker types still draw, with a grey question mark', () => {
  assert.equal(markerStyle('brand_new_type').glyph, '?');
  const ctx = stubCtx();
  drawMarkers(ctx, view(2), world.markers);
  const glyphs = ctx.calls.filter((c) => c[0] === 'fillText').map((c) => c[1]);
  assert.deepEqual(glyphs, ['P', '?', 'R']); // encounters are not drawn here
  assert.ok(names(ctx).includes('strokeRect'), 'the rest_area rectangle');
});

test('zoomed far out the marker discs are small and carry no letter', () => {
  const radius = (zoom) => {
    const ctx = stubCtx();
    drawMarkers(ctx, view(zoom), [world.markers[0]]);
    return [ctx.calls.find((c) => c[0] === 'arc')[3], ctx.calls.filter((c) => c[0] === 'fillText').length];
  };
  assert.deepEqual(radius(0.25), [2.625, 0]);
  assert.deepEqual(radius(4), [7, 1]);
});

test('markers can be limited to some types', () => {
  const ctx = stubCtx();
  drawMarkers(ctx, view(), world.markers, new Set(['spawn_player']));
  assert.deepEqual(ctx.calls.filter((c) => c[0] === 'fillText').map((c) => c[1]), ['P']);
});

test('only the picked encounter is highlighted, even when two share an id', () => {
  const widths = (highlight) => {
    const ctx = stubCtx();
    const seen = [];
    const strokeRect = ctx.strokeRect;
    drawEncounters(new Proxy(ctx, {
      get(t, n) { return n === 'strokeRect' ? (...a) => { seen.push(ctx.lineWidth); strokeRect(...a); } : t[n]; },
      set(t, n, v) { t[n] = v; return true; },
    }), view(), world.markers, highlight);
    return seen;
  };
  assert.deepEqual(widths(null), [3, 1.5]);                       // must_pass thick, optional thin
  assert.deepEqual(widths(world.markers[3]), [4, 1.5]);           // first E01 only
  assert.deepEqual(widths(world.markers[4]), [3, 4]);             // second E01 only
});

test('biome grid draws one outline per cell and survives unknown biome keys', () => {
  const ctx = stubCtx();
  drawBiomeGrid(ctx, view(1), world, { tint: true, labels: true });
  assert.equal(ctx.calls.filter((c) => c[0] === 'strokeRect').length, 4);
  assert.equal(ctx.calls.filter((c) => c[0] === 'fillRect').length, 4);
});

test('entities with missing fields are drawn; ones off screen are skipped', () => {
  const ctx = stubCtx();
  drawEntities(ctx, view(4), [{ x: 5, y: 5 }, { id: 2, kind: 'x', x: 10, y: 10, w: 4, h: 9, hp: 5, hp_max: 10 }, { id: 3, kind: 'far', x: 5000, y: 5000, w: 4, h: 4 }]);
  assert.equal(ctx.calls.filter((c) => c[0] === 'strokeRect').length, 2);
  assert.ok(ctx.calls.some((c) => c[0] === 'fillText' && c[1] === 'x#2'), 'label at zoom >= 3');
});

test('event rings: positioned events only, fading with age, none beyond the window', () => {
  const ctx = stubCtx();
  drawEventMarks(ctx, view(), [
    { frame: 100, type: 'reaction', x: 10, y: 10 },
    { frame: 90, type: 'explosion', x: 20, y: 20, radius: 9 },
    { frame: 99, type: 'future_event' },                 // no position
    { frame: 40, type: 'reaction', x: 30, y: 30 },        // outside a 45 frame window
  ], 100, 45);
  assert.equal(ctx.calls.filter((c) => c[0] === 'arc').length, 4); // two rings and two dots
});

test('the main path needs two points', () => {
  const ctx = stubCtx();
  drawMainPath(ctx, view(), null);
  drawMainPath(ctx, view(), [{ x: 1, y: 1 }]);
  assert.equal(ctx.calls.length, 0);
  drawMainPath(ctx, view(), [{ x: 1, y: 1 }, { x: 5, y: 5 }]);
  assert.ok(names(ctx).includes('lineTo') && names(ctx).includes('stroke'));
});
