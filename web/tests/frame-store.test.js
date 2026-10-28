import test from 'node:test';
import assert from 'node:assert/strict';
import { FrameStore } from '../js/format/frame-store.js';
import { indexFrames } from '../js/format/recording.js';
import { fixtureBuffer, fixtureJson, record, sha256, toArrayBuffer } from './helpers.js';

const expected = fixtureJson('expected.json');
const world = { width: 128, height: 96 };

function storeFor(dir, opts) {
  const buf = fixtureBuffer(dir, 'frames.bin');
  return new FrameStore(buf, indexFrames(buf, world), opts);
}

async function assertStepMatches(store, dir, step) {
  await store.seek(step);
  const frame = store.index.steps[step].frame;
  assert.equal(sha256(store.state), expected[dir].checks[String(frame)], `${dir} step ${step} (frame ${frame})`);
}

test('full-frame recording: every step matches the Python state, in any order', async () => {
  const s = storeFor('rec_synthetic');
  assert.equal(s.length, expected.rec_synthetic.steps);
  for (const step of [0, 1, 2, 59, 30, 5, 58, 0, 17]) await assertStepMatches(s, 'rec_synthetic', step);
});

test('delta recording: replaying from the keyframe gives the exact state', async () => {
  const s = storeFor('rec_synthetic_delta');
  assert.equal(s.length, expected.rec_synthetic_delta.steps);
  // forward one by one, then jumps both ways
  for (let i = 0; i < s.length; i++) await assertStepMatches(s, 'rec_synthetic_delta', i);
  const last = s.length - 1;
  for (const step of [Math.floor(last / 2), last, 3, 0, last - 2, 1]) await assertStepMatches(s, 'rec_synthetic_delta', step);
});

test('delta recording has steps with two records', () => {
  assert.ok(expected.rec_synthetic_delta.multi_record_steps > 0);
});

test('full-frame seeks decode one record, however far the jump', async () => {
  const s = storeFor('rec_synthetic');
  await s.seek(50);
  assert.equal(s.cachedRecords, 1);
});

test('seek clamps to the valid range and serialises concurrent calls', async () => {
  const s = storeFor('rec_synthetic');
  const results = await Promise.all([s.seek(10), s.seek(999), s.seek(-5), s.seek(20)]);
  assert.deepEqual(results, [10, s.length - 1, 0, 20]);
  assert.equal(s.applied, 20);
  await assertStepMatches(s, 'rec_synthetic', 20);
});

test('the LRU stays under its byte budget and still seeks correctly', async () => {
  const frameBytes = 128 * 96;
  const s = storeFor('rec_synthetic', { cacheBytes: frameBytes * 3 });
  for (let i = 0; i < 12; i++) await s.seek(i);
  assert.ok(s.cachedRecords <= 3, `cache holds ${s.cachedRecords}`);
  await assertStepMatches(s, 'rec_synthetic', 4); // evicted earlier, decoded again
});

test('version changes whenever the picture changes', async () => {
  const s = storeFor('rec_synthetic');
  const v0 = s.version;
  await s.seek(3);
  assert.ok(s.version > v0);
});

test('a rect recording shows only the bounding box and keeps its origin', async () => {
  const w = { width: 20, height: 10 };
  const a = Uint8Array.from({ length: 6 * 4 }, (_, i) => 1 + (i % 5));
  const b = Uint8Array.from({ length: 6 * 4 }, (_, i) => 9 - (i % 5));
  const buf = toArrayBuffer(record({ frame: 0, x0: 5, y0: 3, w: 6, h: 4, data: a }), record({ frame: 4, x0: 5, y0: 3, w: 6, h: 4, data: b }));
  const s = new FrameStore(buf, indexFrames(buf, w));
  assert.deepEqual([s.origin, s.width, s.height], [{ x: 5, y: 3 }, 6, 4]);
  await s.seek(1);
  assert.deepEqual([...s.state], [...b]);
});

test('records on one frame number are applied together, partial rects land in place', async () => {
  const w = { width: 8, height: 4 };
  const full = new Uint8Array(32).fill(1);
  const left = new Uint8Array(2 * 4).fill(7);     // x 0..2, all rows
  const right = new Uint8Array(3 * 2).fill(9);    // x 5..8, rows 1..3
  const buf = toArrayBuffer(
    record({ frame: 0, w: 8, h: 4, data: full }),
    record({ frame: 6, x0: 0, y0: 0, w: 2, h: 4, data: left }),
    record({ frame: 6, x0: 5, y0: 1, w: 3, h: 2, data: right }),
  );
  const idx = indexFrames(buf, w);
  assert.equal(idx.steps.length, 2);
  assert.equal(idx.steps[1].count, 2);
  const s = new FrameStore(buf, idx);
  await s.seek(1);
  const rows = [0, 1, 2, 3].map((y) => [...s.state.subarray(y * 8, y * 8 + 8)].join(''));
  assert.deepEqual(rows, ['77111111', '77111999', '77111999', '77111111']);
  await s.seek(0);
  assert.ok(s.state.every((v) => v === 1));
});

test('a recording that never has a key step starts from air', async () => {
  const w = { width: 4, height: 2 };
  const buf = toArrayBuffer(
    record({ frame: 0, x0: 0, y0: 0, w: 2, h: 2, data: [3, 3, 3, 3] }),
    record({ frame: 1, x0: 2, y0: 0, w: 2, h: 2, data: [4, 4, 4, 4] }),
  );
  const idx = indexFrames(buf, w);
  assert.equal(idx.steps.every((s) => !s.key), true);
  const s = new FrameStore(buf, idx);
  await s.seek(1);
  assert.deepEqual([...s.state], [3, 3, 4, 4, 3, 3, 4, 4]);
  await s.seek(0);
  assert.deepEqual([...s.state], [3, 3, 0, 0, 3, 3, 0, 0]);
});

test('a corrupt record fails the seek and leaves no half picture behind', async () => {
  const w = { width: 4, height: 2 };
  const bad = record({ frame: 1, w: 4, h: 2, data: new Uint8Array(8).fill(2) });
  bad[19] ^= 0xff;
  bad[20] ^= 0xff;
  const buf = toArrayBuffer(record({ frame: 0, w: 4, h: 2, data: new Uint8Array(8).fill(1) }), bad);
  const s = new FrameStore(buf, indexFrames(buf, w));
  await s.seek(0);
  await assert.rejects(s.seek(1), /zlib data is corrupt/);
  assert.equal(s.applied, -1);
  await s.seek(0); // recovers
  assert.ok(s.state.every((v) => v === 1));
});

test('a long forward seek through delta records finds the key step once, not once per step', async () => {
  const w = { width: 4, height: 2 };
  const parts = [record({ frame: 0, w: 4, h: 2, data: new Uint8Array(8).fill(1) })];
  for (let f = 1; f <= 400; f++) parts.push(record({ frame: f, x0: f % 4, y0: f % 2, w: 1, h: 1, data: [2 + (f % 5)], codec: 0 }));
  const buf = toArrayBuffer(...parts);
  const s = new FrameStore(buf, indexFrames(buf, w));
  let lookups = 0;
  const find = s._keyAtOrBefore.bind(s);
  s._keyAtOrBefore = (t) => { lookups++; return find(t); };
  await s.seek(400);
  assert.equal(s.applied, 400);
  assert.ok(lookups <= 2, `${lookups} key lookups for one seek`);
  // and the picture is the same as stepping one by one
  const jumped = Uint8Array.from(s.state);
  const t = new FrameStore(buf, indexFrames(buf, w));
  for (let i = 0; i <= 400; i++) await t.seek(i);
  assert.deepEqual([...jumped], [...t.state]);
  await s.seek(3); // backwards: restart from the key step
  assert.equal(s.applied, 3);
});
