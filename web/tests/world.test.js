import test from 'node:test';
import assert from 'node:assert/strict';
import { biomeAt, loadWorld, parseWorldJson } from '../js/format/world.js';
import { encodePng, fixtureBuffer, fixtureJson, sha256 } from './helpers.js';

const doc = () => structuredClone(fixtureJson('world_synthetic.json'));
const expected = fixtureJson('expected.json');

test('loads the synthetic world pair', async () => {
  const w = await loadWorld(fixtureBuffer('world_synthetic.png'), doc(), { png: 'world_synthetic.png', json: 'world_synthetic.json' });
  assert.equal(w.width, 256);
  assert.equal(w.cellSize, 64);
  assert.equal(sha256(w.cells), expected.world_synthetic.sha256);
  assert.equal(w.markers.length, 11);
  assert.equal(w.markers.filter((m) => m.type === 'encounter' && m.must_pass).length, 2);
  assert.equal(w.mainPath.length, 6);
  assert.equal(biomeAt(w, 70, 10), 'mine');
  assert.equal(biomeAt(w, 255, 191), 'brick_ruin');
  assert.equal(biomeAt(w, 300, 10), null);
});

test('keeps unknown marker types and unknown top-level fields', () => {
  const d = doc();
  d.something_new = { a: 1 };
  const w = parseWorldJson(d);
  assert.ok(w.markers.some((m) => m.type === 'future_marker_type'));
});

test('main_path is optional', () => {
  const d = doc();
  delete d.main_path;
  assert.equal(parseWorldJson(d).mainPath, null);
});

test('main_path is also read from meta.main_path, where the cogbench generator writes it; the top level wins', () => {
  const d = doc();
  const top = d.main_path;
  delete d.main_path;
  d.meta = { generator: 'noitabench.worldgen', main_path: [[1, 2], [3, 4]] };
  assert.deepEqual(parseWorldJson(d).mainPath, [{ x: 1, y: 2 }, { x: 3, y: 4 }]);
  d.main_path = top;
  assert.equal(parseWorldJson(d).mainPath.length, 6);
  d.meta = 'not an object';
  delete d.main_path;
  assert.equal(parseWorldJson(d).mainPath, null);
});

test('validation errors name the file and the problem', () => {
  const bad = (mutate, re) => {
    const d = doc();
    mutate(d);
    assert.throws(() => parseWorldJson(d, 'w.json'), re);
  };
  bad((d) => { d.format = 'cogbench-world/3'; }, /FormatError: w\.json: format is "cogbench-world\/3"/);
  bad((d) => { d.width = 0; }, /width and height/);
  bad((d) => { delete d.biome_cell_size; }, /biome_cell_size/);
  bad((d) => { d.biome_map = 'x'; }, /biome_map/);
  bad((d) => { d.markers[0].x = 'left'; }, /markers\[0\].*numeric x and y/);
  bad((d) => { delete d.markers[5].trigger; }, /encounter E16.*trigger/);
  bad((d) => { d.main_path = [[1]]; }, /main_path\[0\]/);
});

test('PNG and JSON sizes must agree', async () => {
  const png = encodePng([[0, 1], [1, 0]], 8, new Array(768).fill(0));
  const buf = png.buffer.slice(png.byteOffset, png.byteOffset + png.byteLength);
  await assert.rejects(loadWorld(buf, doc(), { png: 'tiny.png', json: 'w.json' }), /^FormatError: tiny\.png: PNG is 2x2 but w\.json says 256x192/);
});
