import test from 'node:test';
import assert from 'node:assert/strict';
import { FormatError } from '../js/format/errors.js';
import { base64ToBytes, decodeView, entityAt, materialAt, unpackBits } from '../js/play/view-data.js';
import { fixtureJson } from './helpers.js';

const b64 = (bytes) => Buffer.from(bytes).toString('base64');

test('base64 and packed bits: the first cell is the top bit of the first byte', () => {
  assert.deepEqual([...base64ToBytes(b64([0, 1, 255]))], [0, 1, 255]);
  assert.deepEqual([...unpackBits(Uint8Array.of(0b10100000, 0b01000000), 10)], [1, 0, 1, 0, 0, 0, 0, 0, 0, 1]);
  assert.equal(unpackBits(new Uint8Array(0), 0).length, 0);
});

const raw = (extra = {}) => ({
  frame: 5, origin: { x: 10, y: -2 }, width: 4, height: 2, outside: 255,
  materials: b64([255, 0, 15, 15, 255, 0, 4, 15]),
  burning: b64([0b00100000]),
  player: { x: 12, y: -1, w: 6, h: 16, position: { x: 14, y: 14 } },
  entities: [],
  ...extra,
});

test('decodeView gives one byte per cell for materials and fire', () => {
  const v = decodeView(raw());
  assert.equal(v.materials.length, 8);
  assert.deepEqual([...v.burning], [0, 0, 1, 0, 0, 0, 0, 0]);
  assert.deepEqual(v.origin, { x: 10, y: -2 });
  assert.equal(v.player.position.x, 14);
});

test('materialAt reads world cells and says null outside the window or the world', () => {
  const v = decodeView(raw());
  assert.equal(materialAt(v, 12, -2), 15);
  assert.equal(materialAt(v, 16, 6), null, 'outside the window');
  assert.equal(materialAt(v, 10, -2), null, 'outside the world (255)');
  assert.equal(materialAt(v, 11, -1), 0);
});

test('the legend is the list of {index, name} the server allows to be named, junk left out', () => {
  const pairs = [{ index: 0, name: 'air' }, { index: 15, name: 'rock' }, { index: 4, name: 'water' }];
  assert.deepEqual(decodeView(raw({ legend: pairs })).legend, pairs);
  const junk = [
    { index: 0, name: 'air' }, { index: 255, name: 'outside' }, { index: -1, name: 'x' }, { index: 1.5, name: 'x' },
    { index: '3', name: 'x' }, null, 7, { index: 7, name: 'sand' }, { index: 8 }, { index: 9, name: '' },
    { index: 10, name: 4 }, { index: 0, name: 'again' },
  ];
  assert.deepEqual(decodeView(raw({ legend: junk })).legend, [{ index: 0, name: 'air' }, { index: 7, name: 'sand' }],
    'outside (255), non-indices, nameless and repeated entries drop out');
  assert.deepEqual(decodeView(raw({ legend: [0, 15] })).legend, [], 'bare indices (an old server) name nothing');
  assert.deepEqual(decodeView(raw()).legend, [], 'a server without a legend names nothing');
  assert.deepEqual(decodeView(raw({ legend: 'air' })).legend, []);
});

test('a view whose sizes do not add up is a format error naming the problem', () => {
  assert.throws(() => decodeView(raw({ materials: b64([1, 2, 3]) })), (e) => e instanceof FormatError && /materials has 3 bytes, expected 8/.test(e.message));
  assert.throws(() => decodeView(raw({ burning: b64([0, 0]) })), /burning has 2 bytes, expected 1/);
  assert.throws(() => decodeView(raw({ width: 0 })), /width and height/);
  assert.throws(() => decodeView(null), FormatError);
});

const things = [
  { id: 1, kind: 'bottle', x: 50, y: 70, w: 4, h: 6 },
  { id: 2, kind: 'longleg', x: 52, y: 60, w: 10, h: 12, hostile: true },
];

test('entityAt: boxes are a little bigger than they look, hostile ones win', () => {
  assert.equal(entityAt(things, 51, 73).id, 2, 'both are near: the hostile one');
  assert.equal(entityAt(things, 49, 75).id, 1, 'only the bottle is near');
  assert.equal(entityAt(things, 200, 200), null);
  assert.equal(entityAt([], 1, 1), null);
  assert.equal(entityAt(things, 48, 76, 0), null, 'no padding: outside');
});

test('a real answer of the play server decodes to what the game holds', () => {
  const { response, expected } = fixtureJson('play_state.json');
  const v = decodeView(response.view);
  assert.equal(v.width, 64);
  assert.equal(v.height, 144);
  const lit = [];
  v.burning.forEach((b, i) => { if (b) lit.push([v.origin.x + (i % v.width), v.origin.y + Math.floor(i / v.width)]); });
  assert.deepEqual(lit, expected.burning_cells);
  assert.deepEqual(v.legend, expected.legend, 'the names are those of the ASCII map legend');
  assert.ok(v.legend.length > 0 && v.legend.every((e) => typeof e.name === 'string' && e.name));
  assert.ok(lit.length > 0);
  for (const p of expected.probes) assert.equal(materialAt(v, p.x, p.y), p.material, JSON.stringify(p));
  let outside = 0;
  for (const m of v.materials) if (m === v.outside) outside++;
  assert.equal(outside, expected.outside_cells);
  assert.ok(outside > 0, 'the window hangs over the top of the world');
  const hostile = v.entities.find((e) => e.hostile);
  assert.equal(hostile.kind, 'longleg');
  assert.deepEqual(Object.keys(hostile).sort(), ['h', 'hostile', 'id', 'kind', 'w', 'x', 'y']);
});
