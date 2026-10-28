import test from 'node:test';
import assert from 'node:assert/strict';
import { parseMaterials } from '../js/format/materials.js';

// The play server sends the colour of each material index and nothing else (no key, name or kind).
const served = {
  format: 'cogbench-materials/0',
  materials: [{ index: 0, color: '#140f0c' }, { index: 15, color: '#6b625a' }, { index: 4, color: '#2a6fd6' }],
};

test('the page reads the colours-only materials file the play server serves', () => {
  const t = parseMaterials(served, 'content/materials.json');
  assert.deepEqual([...t.rgb.slice(15 * 3, 15 * 3 + 3)], [0x6b, 0x62, 0x5a]);
  assert.deepEqual([...t.rgb.slice(0, 3)], [0x14, 0x0f, 0x0c]);
  assert.deepEqual([...t.rgb.slice(200 * 3, 200 * 3 + 3)], [255, 0, 255], 'unknown indices stay magenta');
  assert.equal(t.kinds[15], '', 'no kind: the page draws with flat colours');
  assert.deepEqual(Object.keys(t.byIndex[15]).sort(), ['color', 'index'], 'and learns no name from the file');
});
