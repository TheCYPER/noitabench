import test from 'node:test';
import assert from 'node:assert/strict';
import {
  decodeRecord, indexFrames, lastAtOrBefore, normalizeEntities, normalizeEvents, parseJsonl, parseMeta,
} from '../js/format/recording.js';
import { FormatError } from '../js/format/errors.js';
import { fixtureBuffer, fixtureJson, record, toArrayBuffer } from './helpers.js';

const world = { width: 8, height: 4 };

test('parseMeta accepts the fixtures and ignores unknown fields', () => {
  const m = parseMeta(fixtureJson('rec_synthetic_delta', 'meta.json'), 'meta.json');
  assert.equal(m.width, 128);
  assert.equal(m.frameStride, 3);
  assert.equal(m.runId, 'synthetic-delta');
});

test('parseMeta errors name the file', () => {
  const ok = fixtureJson('rec_synthetic', 'meta.json');
  assert.throws(() => parseMeta({ ...ok, format: 'cogbench-rec/1' }, 'meta.json'), /meta\.json: format is "cogbench-rec\/1"/);
  assert.throws(() => parseMeta({ ...ok, world: { width: 0, height: 3 } }, 'meta.json'), /world\.width/);
  assert.throws(() => parseMeta({ ...ok, frame_stride: 0 }, 'meta.json'), /frame_stride/);
  assert.equal(parseMeta({ ...ok, frame_stride: undefined }).frameStride, 1);
});

test('indexes the full-frame fixture without decompressing', () => {
  const idx = indexFrames(fixtureBuffer('rec_synthetic', 'frames.bin'), { width: 128, height: 96 });
  assert.equal(idx.steps.length, 60);
  assert.ok(idx.steps.every((s) => s.key && s.count === 1));
  assert.deepEqual(idx.bbox, { x0: 0, y0: 0, x1: 128, y1: 96 });
  assert.deepEqual(idx.steps.slice(0, 3).map((s) => s.frame), [0, 2, 4]);
  assert.deepEqual([...new Set(idx.records.map((r) => r.codec))].sort(), [0, 1]);
});

test('indexes the delta fixture: first step is the only key, some steps hold two records', () => {
  const idx = indexFrames(fixtureBuffer('rec_synthetic_delta', 'frames.bin'), { width: 128, height: 96 });
  assert.equal(idx.steps[0].key, true);
  assert.equal(idx.steps.filter((s) => s.key).length, 1);
  assert.ok(idx.steps.some((s) => s.count === 2));
});

test('reads raw and zlib records written by hand', async () => {
  const data = Uint8Array.from({ length: 8 * 4 }, (_, i) => i % 7);
  const buf = toArrayBuffer(record({ frame: 0, w: 8, h: 4, data, codec: 0 }), record({ frame: 5, w: 8, h: 4, data, codec: 1 }));
  const idx = indexFrames(buf, world);
  assert.equal(idx.records.length, 2);
  assert.deepEqual([...(await decodeRecord(buf, idx.records[0]))], [...data]);
  assert.deepEqual([...(await decodeRecord(buf, idx.records[1]))], [...data]);
});

test('truncated and malformed frames.bin give precise errors', () => {
  const good = record({ frame: 0, w: 8, h: 4, data: new Uint8Array(32), codec: 0 });
  const err = (buf, re) => assert.throws(() => indexFrames(buf, world, 'frames.bin'), (e) => e instanceof FormatError && re.test(e.message));
  err(toArrayBuffer(good.subarray(0, 10)), /truncated record header at byte 0/);
  err(toArrayBuffer(good.subarray(0, 30)), /payload of 32 bytes runs past the end/);
  err(toArrayBuffer(good, good.subarray(0, 10)), /truncated record header at byte 49/);
  err(toArrayBuffer(good, good.subarray(0, 20)), /record #1 at byte 49: payload of 32 bytes runs past the end/);
  err(toArrayBuffer(), /no frame records/);
  const badCodec = Buffer.from(good);
  badCodec[12] = 9;
  err(toArrayBuffer(badCodec), /unknown codec 9/);
  err(toArrayBuffer(record({ frame: 0, w: 9, h: 4, data: new Uint8Array(36), codec: 0 })), /outside the 8x4 world/);
  err(toArrayBuffer(record({ frame: 0, x0: 4, w: 8, h: 4, data: new Uint8Array(32), codec: 0 })), /outside the 8x4 world/);
  err(toArrayBuffer(record({ frame: 3, w: 8, h: 4, data: new Uint8Array(32) }), record({ frame: 2, w: 8, h: 4, data: new Uint8Array(32) })), /frame 2 comes after frame 3/);
  const shortRaw = record({ frame: 0, w: 8, h: 4, data: new Uint8Array(31), codec: 0 });
  err(toArrayBuffer(shortRaw), /raw payload is 31 bytes but 8x4 needs 32/);
});

test('a zlib payload that inflates to the wrong size is reported', async () => {
  const buf = toArrayBuffer(record({ frame: 0, w: 8, h: 4, data: new Uint8Array(30), codec: 1 }));
  const idx = indexFrames(buf, world);
  await assert.rejects(decodeRecord(buf, idx.records[0], 'frames.bin'), /decoded 30 bytes but 8x4 needs 32/);
});

test('corrupt zlib data is a FormatError, not a crash', async () => {
  const good = record({ frame: 0, w: 8, h: 4, data: new Uint8Array(32).fill(3), codec: 1 });
  good[20] ^= 0xff;
  good[21] ^= 0xff;
  const buf = toArrayBuffer(good);
  const idx = indexFrames(buf, world);
  await assert.rejects(decodeRecord(buf, idx.records[0], 'frames.bin'), (e) => e instanceof FormatError && /^frames\.bin: zlib data is corrupt/.test(e.message));
});

test('parseJsonl collects bad lines instead of throwing', () => {
  const { items, errors } = parseJsonl('{"a":1}\n\nnot json\n[1,2]\n{"b":2}', 'events.jsonl');
  assert.equal(items.length, 2);
  assert.equal(errors.length, 2);
  assert.match(errors[0], /events\.jsonl: line 3 is not valid JSON/);
  assert.match(errors[1], /line 4 is not a JSON object/);
});

test('entities and events are normalised, sorted and tolerant', () => {
  const ents = normalizeEntities([
    { frame: 4, entities: [{ id: 1, kind: 'p', x: 1, y: 2 }, { id: 2, kind: 'bad' }] },
    { frame: 2, entities: [] },
    { frame: 'x', entities: [] },
    { frame: 6 },
  ]);
  assert.deepEqual(ents.map((e) => e.frame), [2, 4]);
  assert.equal(ents[1].entities.length, 1);
  const evs = normalizeEvents([{ frame: 9, type: 'b' }, { frame: 3, type: 'a' }, { frame: 9, type: 'a' }, { type: 'no frame' }]);
  assert.deepEqual(evs.map((e) => `${e.frame}${e.type}`), ['3a', '9b', '9a']);
});

test('lastAtOrBefore', () => {
  const a = [{ frame: 0 }, { frame: 2 }, { frame: 2 }, { frame: 7 }];
  assert.equal(lastAtOrBefore(a, -1), -1);
  assert.equal(lastAtOrBefore(a, 0), 0);
  assert.equal(lastAtOrBefore(a, 1), 0);
  assert.equal(lastAtOrBefore(a, 2), 2);
  assert.equal(lastAtOrBefore(a, 100), 3);
  assert.equal(lastAtOrBefore([], 5), -1);
});
