import test from 'node:test';
import assert from 'node:assert/strict';
import { loadRun } from '../js/replay/run.js';
import { fixtureFileSet, fixtureJson, sha256 } from './helpers.js';

// rec_sim/ was written by the real simulation (cogbench-sim, see rec_sim/HOWTO.md).
// expected.json holds state hashes decoded by Python (make_sim_expected.py), not by the viewer.
const expected = fixtureJson('rec_sim', 'expected.json');

test('a recording written by cogbench-sim loads without warnings', async () => {
  const run = await loadRun(fixtureFileSet('rec_sim'));
  assert.deepEqual(run.warnings, []);
  assert.equal(run.store.length, expected.steps);
  assert.deepEqual([run.store.width, run.store.height, run.store.origin], [expected.width, expected.height, { x: 0, y: 0 }]);
  assert.equal(run.events.length, expected.events);
  assert.deepEqual(run.entities, []); // the sim does not write entities.jsonl yet: optional
  assert.deepEqual(run.decisions, []);
  assert.equal(run.meta.frameStride, 6);
  assert.deepEqual([run.firstFrame, run.lastFrame], [0, 240]);
});

test('u64 seeds in the sim meta.json keep every digit', async () => {
  const run = await loadRun(fixtureFileSet('rec_sim'));
  assert.equal(run.meta.seed, expected.seed);
  assert.equal(run.meta.ruleSeed, expected.rule_seed);
  assert.ok(BigInt(run.meta.seed) > 2n ** 53n);
});

test('every step of the sim recording decodes to the Python-decoded state, in any order', async () => {
  const run = await loadRun(fixtureFileSet('rec_sim'));
  const { store } = run;
  const steps = store.index.steps;
  const order = [0, 40, 7, 8, 39, 1, 22, 22, 3];
  for (let i = 0; i < steps.length; i++) order.push(i);
  for (const s of order) {
    await store.seek(s);
    assert.equal(sha256(store.state), expected.checks[String(steps[s].frame)], `step ${s} (frame ${steps[s].frame})`);
  }
});

test('sim events have the fields the overlays read', async () => {
  const run = await loadRun(fixtureFileSet('rec_sim'));
  const types = new Set(run.events.map((e) => e.type));
  assert.ok(types.has('reaction') && types.has('ignite'));
  for (const e of run.events) assert.ok(Number.isInteger(e.frame) && Number.isInteger(e.x) && Number.isInteger(e.y), JSON.stringify(e));
  assert.ok(run.events.every((e, i, a) => i === 0 || a[i - 1].frame <= e.frame));
});
