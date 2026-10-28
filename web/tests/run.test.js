import test from 'node:test';
import assert from 'node:assert/strict';
import { FormatError } from '../js/format/errors.js';
import { loadRun } from '../js/replay/run.js';
import { fixtureFileSet, fixtureJson, sha256 } from './helpers.js';

const expected = fixtureJson('expected.json');

test('loads the full synthetic run with every optional file', async () => {
  const run = await loadRun(fixtureFileSet('rec_synthetic'));
  assert.deepEqual(run.warnings, []);
  assert.equal(run.store.length, 60);
  assert.equal(run.entities.length, 60);
  assert.equal(run.events.length, 6);
  assert.equal(run.decisions.length, 3);
  assert.deepEqual([run.firstFrame, run.lastFrame], [0, 118]);
  await run.store.seek(59);
  assert.equal(sha256(run.store.state), expected.rec_synthetic.checks['118']);
});

test('the delta run has no optional files and still loads', async () => {
  const run = await loadRun(fixtureFileSet('rec_synthetic_delta'));
  assert.deepEqual([run.entities, run.events, run.decisions, run.warnings], [[], [], [], []]);
  assert.equal(run.meta.runId, 'synthetic-delta');
});

test('missing required files are FormatErrors that name the file', async () => {
  const bad = (opts, re) => assert.rejects(loadRun(fixtureFileSet('rec_synthetic', opts)), (e) => e instanceof FormatError && re.test(e.message));
  await bad({ skip: ['meta.json'] }, /^meta\.json: file is missing/);
  await bad({ skip: ['frames.bin'] }, /^frames\.bin: file is missing/);
  await bad({ extra: { 'meta.json': '{"format": "cogbench-rec/0", ' } }, /^meta\.json: not valid JSON/);
  await bad({ extra: { 'meta.json': '{"format": "cogbench-rec/7"}' } }, /^meta\.json: format is "cogbench-rec\/7"/);
  await bad({ extra: { 'frames.bin': '' } }, /^frames\.bin: no frame records/);
});

test('a damaged optional file is a warning, the run still loads', async () => {
  const run = await loadRun(fixtureFileSet('rec_synthetic', {
    extra: {
      'events.jsonl': '{"frame":3,"type":"a"}\nnot json\n{"frame":"x","type":"b"}\n[1]\n',
      'entities.jsonl': '{"frame":0,"entities":"nope"}\n{"frame":2,"entities":[]}\n',
      'decisions.jsonl': '{"index":0}\n',
    },
  }));
  assert.equal(run.events.length, 1);
  assert.equal(run.entities.length, 1);
  assert.equal(run.decisions.length, 0);
  assert.equal(run.warnings.length, 4);
  assert.match(run.warnings.join('\n'), /events\.jsonl: line 2 is not valid JSON \(and 1 more bad lines\)/);
  assert.match(run.warnings.join('\n'), /events\.jsonl: 1 line\(s\) ignored/);
  assert.match(run.warnings.join('\n'), /entities\.jsonl: 1 line\(s\) ignored/);
  assert.match(run.warnings.join('\n'), /decisions\.jsonl: 1 line\(s\) ignored/);
});

test('FileSet.json names the file when the JSON is bad', async () => {
  const fs = fixtureFileSet('rec_synthetic', { extra: { 'materials.json': '{oops' } });
  await assert.rejects(fs.json('materials.json'), (e) => e instanceof FormatError && /^materials\.json: not valid JSON/.test(e.message));
});
