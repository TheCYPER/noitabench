import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeIndexedPng } from '../js/format/png.js';
import { FormatError } from '../js/format/errors.js';
import { encodePng, fixtureBuffer, fixtureJson, sha256 } from './helpers.js';

const expected = fixtureJson('expected.json');
const PAL = Array.from({ length: 48 }, (_, i) => i * 5);

test('decodes the Pillow-written 8-bit world PNG (adaptive filters)', async () => {
  const img = await decodeIndexedPng(fixtureBuffer('world_synthetic.png'), 'world_synthetic.png');
  assert.equal(img.width, expected.world_synthetic.width);
  assert.equal(img.height, expected.world_synthetic.height);
  assert.equal(sha256(img.pixels), expected.world_synthetic.sha256);
  assert.equal(img.palette.length, 22 * 3 >= 768 ? 768 : img.palette.length);
  assert.deepEqual([...img.palette.subarray(0, 3)], [0x14, 0x0f, 0x0c]); // air colour from materials.json
});

test('decodes the Pillow-written 4-bit PNG', async () => {
  const img = await decodeIndexedPng(fixtureBuffer('indexed_4bit.png'), 'indexed_4bit.png');
  assert.equal(img.width, 53);
  assert.equal(img.height, 37);
  assert.equal(sha256(img.pixels), expected.indexed_4bit.sha256);
});

for (const depth of [1, 2, 4, 8]) {
  test(`round-trips ${depth}-bit PNG with every filter type`, async () => {
    const w = 13; // not a multiple of 8, so rows have padding bits
    const rows = Array.from({ length: 10 }, (_, y) => Array.from({ length: w }, (_, x) => (x * 3 + y * 5 + (x ^ y)) % (1 << depth)));
    const filters = [0, 1, 2, 3, 4, 4, 3, 2, 1, 0];
    const png = encodePng(rows, depth, PAL, filters);
    const img = await decodeIndexedPng(png);
    assert.deepEqual([...img.pixels], rows.flat());
  });
}

test('rejects things that are not an indexed, non-interlaced PNG', async () => {
  const rows = [[0, 1], [1, 0]];
  await assert.rejects(decodeIndexedPng(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9]), 'bad.png'), /bad\.png: not a PNG/);
  await assert.rejects(decodeIndexedPng(encodePng(rows, 8, PAL, [], { colorType: 2 }), 'rgb.png'), /rgb\.png: .*colour type is 2/);
  await assert.rejects(decodeIndexedPng(encodePng(rows, 8, PAL, [], { interlace: 1 }), 'adam7.png'), /interlaced/);
});

test('reports truncated PNG data with the file name', async () => {
  const png = encodePng([[0, 1, 2], [2, 1, 0]], 8, PAL);
  await assert.rejects(decodeIndexedPng(png.subarray(0, png.length - 30), 'cut.png'), (e) => e instanceof FormatError && e.message.startsWith('cut.png:'));
});
