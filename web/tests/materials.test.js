import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { materialLabel, parseMaterials } from '../js/format/materials.js';
import { FormatError } from '../js/format/errors.js';
import { MATERIALS_PATH } from './helpers.js';

const real = JSON.parse(readFileSync(MATERIALS_PATH, 'utf8'));

test('parses the real content/materials.json', () => {
  const t = parseMaterials(real);
  assert.equal(t.list.length, real.materials.length);
  assert.equal(t.list.length, 34); // 22 + the alchemy set (metal, 4 ingredients, 7 secret potions)
  assert.equal(t.byIndex[22].key, 'metal');
  assert.equal(t.byIndex[0].key, 'air');
  assert.equal(t.byIndex[11].key, 'sand');
  assert.deepEqual([...t.rgb.subarray(11 * 3, 11 * 3 + 3)], [0xd9, 0xb5, 0x6a]);
  assert.equal(t.kinds[14], 'static');
  assert.match(materialLabel(t, 11), /sand/);
});

test('unused indexes are magenta so bad recordings stand out', () => {
  const t = parseMaterials(real);
  assert.deepEqual([...t.rgb.subarray(200 * 3, 200 * 3 + 3)], [255, 0, 255]);
  assert.match(materialLabel(t, 200), /unknown #200/);
});

test('rejects a wrong format string, naming the file', () => {
  assert.throws(() => parseMaterials({ ...real, format: 'cogbench-materials/9' }, 'm.json'), (e) => e instanceof FormatError && /^m\.json: .*cogbench-materials\/0/.test(e.message));
});

test('rejects duplicate indexes, bad colours, indexes above 255', () => {
  const mk = (materials) => ({ format: 'cogbench-materials/0', materials });
  assert.throws(() => parseMaterials(mk([{ index: 1, key: 'a', color: '#000000' }, { index: 1, key: 'b', color: '#000000' }])), /used twice/);
  assert.throws(() => parseMaterials(mk([{ index: 1, key: 'a', color: 'red' }])), /#RRGGBB/);
  assert.throws(() => parseMaterials(mk([{ index: 256, key: 'a', color: '#000000' }])), /0\.\.255/);
});
