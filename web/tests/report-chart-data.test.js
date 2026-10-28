import test from 'node:test';
import assert from 'node:assert/strict';
import { capabilityRows, encounterMatrix, metricMatrix, playerText, summaryRows, thinCapabilities, uniqueLabels } from '../js/report/chart-data.js';
import { parseProfile } from '../js/report/profile.js';
import { load, raw } from './report-helpers.js';

const KEYS = ['N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7', 'N8', 'N9', 'N10', 'C'];

test('one row per capability in a fixed order, one cell per profile', () => {
  const rows = capabilityRows([load('agent')]);
  assert.deepEqual(rows.map((r) => r.key), KEYS);
  const n1 = rows[0].cells[0];
  assert.deepEqual([n1.present, n1.score, n1.discounted, n1.opportunities, n1.thin], [true, 72.73, 43.64, 3, false]);
  assert.equal(rows[3].cells[0].thin, true, 'N4 had one opportunity');
  assert.equal(rows[1].cells[0].score, null, 'N2 was never met');
  assert.equal(rows[1].cells[0].thin, true, 'not covered; the chart marks only the bars that have a score');
});

test('profiles line up row by row, and a missing capability is a gap, not a zero', () => {
  const noC = raw('human');
  delete noC.capabilities.C;
  const rows = capabilityRows([load('agent'), parseProfile(noC, 'human-no-c')]);
  assert.deepEqual(rows.map((r) => r.key), KEYS);
  const c = rows.find((r) => r.key === 'C');
  assert.equal(c.cells[0].present, true);
  assert.equal(c.cells[1].present, false);
  assert.equal(c.cells[1].score, null);
});

test('a capability only some profile has is added after the known ones', () => {
  const extra = raw('human');
  extra.capabilities.N11 = { score: 10, opportunities: 2, covered: true };
  const rows = capabilityRows([load('agent'), parseProfile(extra, 'extra')]);
  assert.deepEqual(rows.map((r) => r.key), [...KEYS, 'N11']);
  assert.equal(rows[11].cells[0].present, false);
  assert.equal(rows[11].cells[1].score, 10);
});

test('thin = scored with fewer than two opportunities; a profile without the covered flag is judged by the count', () => {
  assert.deepEqual(thinCapabilities(load('agent')), ['N4', 'N6', 'N7', 'N10']);
  assert.deepEqual(thinCapabilities(load('bot')), ['N4', 'N7', 'N8']);
  const noFlag = parseProfile({ format: 'cogbench-profile/0', capabilities: { N1: { score: 5, opportunities: 1 }, N2: { score: 5, opportunities: 2 } } }, 'f');
  assert.deepEqual(thinCapabilities(noFlag), ['N1']);
});

test('labels are unique within a set', () => {
  const a = load('agent');
  assert.deepEqual(uniqueLabels([a, load('human'), a, a]), ['fx-agent', 'fx-human', 'fx-agent #2', 'fx-agent #3']);
  const bare = parseProfile({ format: 'cogbench-profile/0' }, 'dir/profile.json');
  assert.deepEqual(uniqueLabels([bare]), ['dir/profile.json']);
});

test('who played', () => {
  assert.equal(playerText(load('agent')), 'claude-haiku-5-5');
  assert.equal(playerText(load('human')), '人类');
  assert.equal(playerText(load('bot')), '脚本 bot');
  assert.equal(playerText(parseProfile({ format: 'cogbench-profile/0', source: 'robot' }, 'x')), '来源未知');
});

test('summary rows: the headline figures of every profile, null where a profile has none', () => {
  const rows = summaryRows([load('agent'), load('bot')]);
  const by = Object.fromEntries(rows.map((r) => [r.key, r.cells]));
  assert.deepEqual(by.composite, [30.59, 56.21]);
  assert.deepEqual(by.ability, [24.68, 45.26]);
  assert.deepEqual(by.depth, [54.24, 100]);
  assert.deepEqual(by.decisions, [235, null]);
  assert.deepEqual(by.frames, [16580, 3969]);
  assert.deepEqual(by.usd, [0.051279, null]);
  assert.deepEqual(by.calls, [47, null]);
});

test('the encounter matrix has one row per encounter, numeric order, aligned across profiles', () => {
  const rows = encounterMatrix([load('agent'), load('bot'), load('human')]);
  assert.deepEqual(rows.map((r) => r.id), ['E02', 'E03', 'E04', 'E06', 'E07', 'E08', 'E12', 'E14', 'E16', 'E18', 'E22', 'E23']);
  const e07 = rows.find((r) => r.id === 'E07');
  assert.equal(e07.name, '连环关卡');
  assert.deepEqual(e07.nodes, ['N3', 'N1']);
  assert.deepEqual(e07.cells.map((c) => c.status), ['scored', 'scored', 'unmet']);
  assert.equal(e07.cells[0].mean, 0.1819);
  assert.equal(rows.find((r) => r.id === 'E04').cells[0].status, 'unscored');
  assert.equal(rows.find((r) => r.id === 'E02').cells[0].status, 'unmet');
  assert.equal(rows.find((r) => r.id === 'E02').cells[1].best, 1);
  const e23 = rows.find((r) => r.id === 'E23');
  assert.deepEqual([e23.cells[1].visits, e23.cells[1].scored, e23.cells[1].mean], [2, 2, 0.5], 'two visits are averaged');
});

test('E9 sorts before E10 (numbers, not text), and an encounter only one profile lists is absent in the others', () => {
  const a = parseProfile({ format: 'cogbench-profile/0', encounters: [{ id: 'E10', nodes: ['N1'], placed: 1 }, { id: 'E9', nodes: ['N2'], placed: 1 }, { id: 'E99', nodes: ['N3'], placed: 1 }] }, 'a');
  const b = parseProfile({ format: 'cogbench-profile/0', encounters: [{ id: 'E9', nodes: ['N2'], placed: 0 }, { id: 'E10', nodes: ['N1'], placed: 0 }] }, 'b');
  const rows = encounterMatrix([a, b]);
  assert.deepEqual(rows.map((r) => r.id), ['E9', 'E10', 'E99']);
  assert.deepEqual(rows[0].cells.map((c) => c.status), ['unmet', 'unmet']);
  assert.deepEqual(rows[2].cells.map((c) => c.status), ['unmet', 'absent']);
  assert.equal(rows[2].name, '', 'an unknown encounter has no name, only its id');
  assert.equal(rows[0].cells[1].placed, 0);
});

test('the metric matrix keeps the first profile\'s order and marks gaps', () => {
  const only = raw('human');
  only.metrics = only.metrics.slice(0, 3);
  only.metrics.push({ name: 'brand_new', capabilities: ['N1'], value: 0.5, status: 'measured', opportunities: 1, reason: '' });
  const rows = metricMatrix([load('agent'), parseProfile(only, 'few')]);
  assert.equal(rows[0].name, 'repeat_harm');
  assert.equal(rows.at(-1).name, 'brand_new');
  assert.equal(rows.at(-1).label, 'brand_new');
  assert.deepEqual(rows.at(-1).cells.map((c) => c.present), [false, true]);
  assert.equal(rows.find((r) => r.name === 'route_efficiency').cells[1].present, false);
  const m = rows.find((r) => r.name === 'backtracking');
  assert.deepEqual([m.cells[0].status, m.cells[0].value, m.cells[1].present], ['measured', 0.9408, true]);
});
