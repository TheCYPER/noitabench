import test from 'node:test';
import assert from 'node:assert/strict';
import { inspect } from 'node:util';
import { FormatError } from '../js/format/errors.js';
import { PROFILE_FORMAT, parseProfile, parseProfileText, safeNotes } from '../js/report/profile.js';
import { capabilityName, capabilityShort, encounterName, metricName, orderedCapabilityKeys } from '../js/report/names.js';
import { fixtureBytes } from './helpers.js';
import { SEEDS, load, raw } from './report-helpers.js';

test('the agent fixture is read as the evaluator wrote it', () => {
  const p = load('agent');
  assert.equal(p.runId, 'fx-agent');
  assert.equal(p.source, 'agent');
  assert.deepEqual(p.model, { provider: 'anthropic', model: 'claude-haiku-5-5' });
  assert.equal(p.composite, 30.59);
  assert.equal(p.ability, 24.68);
  assert.equal(p.abilityRaw, 63.9);
  assert.equal(p.depth.score, 54.24);
  assert.equal(p.depth.reachedSealedRoom, false);
  assert.equal(p.outcome.over, 'dead');
  assert.equal(p.outcome.died, true);
  assert.equal(p.cost.usd, 0.051279);
  assert.equal(p.cost.modelCalls, 47);
  assert.equal(p.cost.costKnown, true);
  assert.equal(p.steps.decisions, 235);
  assert.equal(p.awareness.hits, 0);
  assert.equal(p.awareness.checked, 79);
  assert.equal(p.encounters.length, 12);
  assert.equal(p.metrics.length, 18);
  assert.deepEqual(p.covered, ['C', 'N1', 'N3', 'N5', 'N9']);
  assert.equal(p.hasDiscount, true);
});

test('capabilities keep the raw score, the discount and the discounted score', () => {
  const p = load('agent');
  const n1 = p.capabilities.get('N1');
  assert.deepEqual([n1.score, n1.opportunities, n1.covered, n1.discount, n1.discounted], [72.73, 3, true, 0.6, 43.64]);
  const n4 = p.capabilities.get('N4');
  assert.equal(n4.covered, false);
  assert.equal(n4.opportunities, 1);
  const n2 = p.capabilities.get('N2');
  assert.equal(n2.score, null, 'a capability that was never met has no score');
  assert.equal(n2.discounted, 0);
  assert.equal(p.capabilities.get('N1').encounters[0].id, 'E07');
  assert.equal(p.capabilities.get('N3').metrics[0].name, 'backtracking');
});

test('C carries its parts C1 to C4', () => {
  const c = load('agent').capabilities.get('C');
  assert.deepEqual(c.parts.map((x) => x.name), ['C1', 'C2', 'C3', 'C4']);
  assert.equal(c.parts[0].score, 59.09);
  assert.equal(c.parts[2].score, null);
});

test('encounters, visits and metrics', () => {
  const p = load('agent');
  const e07 = p.encounters.find((e) => e.id === 'E07');
  assert.deepEqual([e07.placed, e07.mustPassPlaced, e07.nodes], [2, 1, ['N3', 'N1']]);
  const [v] = e07.visits;
  assert.deepEqual([v.layer, v.mustPass, v.scored, v.score], [2, true, true, 0.1819]);
  assert.ok(v.reasons[0].startsWith('filled: '));
  const unscored = p.encounters.find((e) => e.id === 'E04').visits[0];
  assert.equal(unscored.scored, false);
  assert.equal(unscored.score, null);
  const m = p.metrics.find((x) => x.name === 'low_hp_discipline');
  assert.deepEqual([m.status, m.value, m.opportunities], ['measured', 0, 1]);
  assert.equal(p.metrics.find((x) => x.name === 'notes_used').status, 'not_measured');
});

test('the bot and the human fixtures: no model, no cost, no transcript', () => {
  const bot = load('bot');
  assert.equal(bot.source, 'bot');
  assert.equal(bot.model, null);
  assert.equal(bot.cost, null);
  assert.equal(bot.awareness, null);
  assert.equal(bot.depth.reachedSealedRoom, true);
  assert.equal(bot.outcome.over, '');
  const human = load('human');
  assert.equal(human.source, 'human');
  assert.match(human.compositeNote, /^thin: only 2 of 11/);
  assert.equal(human.steps.decisions, 478);
});

test('a seed never survives parsing', () => {
  for (const name of ['bot', 'agent', 'human']) {
    const text = inspect(load(name), { depth: null, maxArrayLength: null, maxStringLength: null });
    for (const seed of SEEDS) assert.ok(!text.includes(seed), `${name}: ${seed}`);
    assert.ok(!text.includes('world_424242'), 'the world file name carries the seed too');
  }
});

test('notes that quote seeds are replaced, others stay', () => {
  const notes = safeNotes([
    'the world file has seed 424242 but the recording seed 7: the scenes below may be those of another world',
    'scripted bot: it plans on the whole grid',
  ]);
  assert.ok(!notes[0].includes('424242'));
  assert.equal(notes[1], 'scripted bot: it plans on the whole grid');
  const p = parseProfile({ ...raw('agent'), evaluator: { version: '0', notes: ['recording seed 717171 differs'] } }, 'x');
  assert.ok(!inspect(p, { depth: null }).includes('717171'));
});

test('a profile of another format, or not an object, is refused with the file name first', () => {
  assert.throws(() => parseProfile({ format: 'cogbench-rec/0' }, 'a/profile.json'), (e) => e instanceof FormatError && e.message.startsWith('a/profile.json: ') && /cogbench-rec\/0/.test(e.message));
  assert.throws(() => parseProfile({}, 'p.json'), /expected "cogbench-profile\/0"/);
  assert.throws(() => parseProfile([], 'p.json'), /not a JSON object/);
  assert.throws(() => parseProfile(null, 'p.json'), /not a JSON object/);
  assert.throws(() => parseProfileText('{"format": ', 'p.json'), /p\.json: not valid JSON/);
  assert.throws(() => parseProfileText(fixtureBytes('profiles', 'agent.profile.json').toString('utf8').replace('cogbench-profile/0', 'cogbench-profile/9'), 'p.json'), /cogbench-profile\/9/);
});

test('a bare profile opens: every part is optional', () => {
  const p = parseProfile({ format: PROFILE_FORMAT }, 'bare.json');
  assert.equal(p.runId, 'bare.json');
  assert.equal(p.composite, null);
  assert.equal(p.capabilities.size, 0);
  assert.deepEqual([p.encounters, p.metrics, p.attribution, p.notes], [[], [], [], []]);
  assert.equal(p.cost, null);
  assert.equal(p.awareness, null);
  assert.equal(p.hasDiscount, false);
  assert.equal(p.source, 'unknown');
});

test('fields of the wrong type are ignored, not trusted', () => {
  const p = parseProfile({
    format: PROFILE_FORMAT, composite: '91', ability_mean: NaN, run_id: 7, source: 3,
    capabilities: [], encounters: [1, null, 'x', { id: 'E01', visits: [null, { score: 'a', reasons: [1, 'ok'] }] }],
    metrics: [5, { name: 'm', value: 'x', status: 7 }], cost: 'free', test_awareness: [],
    depth: { score: '10' }, evaluator: { notes: [1, 'n'] },
  }, 'odd.json');
  assert.equal(p.composite, null);
  assert.equal(p.ability, null);
  assert.equal(p.runId, 'odd.json');
  assert.equal(p.encounters.length, 1);
  assert.deepEqual(p.encounters[0].visits.map((v) => v.reasons), [['ok']]);
  assert.equal(p.encounters[0].visits[0].score, null);
  assert.deepEqual(p.metrics.map((m) => [m.name, m.status, m.value]), [['m', 'not_measured', null]]);
  assert.equal(p.cost, null);
  assert.equal(p.depth.score, null);
  assert.deepEqual(p.notes, ['n']);
});

test('older profiles (before the discount) open without a discounted score', () => {
  const json = raw('agent');
  const legacy = structuredClone(json);
  delete legacy.ability_raw_mean;
  delete legacy.depth.capped_at_seal;
  for (const c of Object.values(legacy.capabilities)) {
    delete c.discount;
    delete c.discounted_score;
  }
  const p = parseProfile(legacy, 'old.json');
  assert.equal(p.hasDiscount, false);
  assert.equal(p.abilityRaw, null);
  assert.equal(p.capabilities.get('N1').discounted, null);
  assert.equal(p.capabilities.get('N1').score, 72.73);
});

test('a profile with only the factor still gets the product', () => {
  const json = { format: PROFILE_FORMAT, capabilities: { N1: { score: 80, opportunities: 3, covered: true, discount: 0.6 } } };
  const c = parseProfile(json, 'f.json').capabilities.get('N1');
  assert.equal(c.discounted, 48);
});

test('keys that name Object.prototype members are plain keys', () => {
  const text = '{"format":"cogbench-profile/0","capabilities":{"__proto__":{"score":1},"constructor":{"score":2}}}';
  const p = parseProfileText(text, 'p.json');
  assert.deepEqual([...p.capabilities.keys()].sort(), ['__proto__', 'constructor']);
  assert.equal(capabilityShort('constructor'), 'constructor');
  assert.equal(capabilityName('__proto__'), '__proto__');
  assert.equal(encounterName('constructor'), '');
  assert.equal(metricName('toString'), 'toString');
});

test('capability keys are ordered N1 to N10, then C, then anything new', () => {
  assert.deepEqual(orderedCapabilityKeys(['C', 'N10', 'N2', 'N1', 'X1', 'N9']), ['N1', 'N2', 'N9', 'N10', 'C', 'X1']);
});

test('an attribution entry keeps only the fields the evaluator writes', () => {
  const entry = { capability: 'C2', layer: 2, outcome: 'died', frame: 9, encounter: 'E22', nodes: ['N9', 3], reason: 'r', seed: 424242, x: 5, variant: 'v', last_harm: { frame: 9, source: 'hit', kind: 'hit', x: 1 } };
  const p = parseProfile({ format: PROFILE_FORMAT, attribution: [entry, { layer: 'two', last_harm: 'no' }] }, 'a.json');
  assert.deepEqual(p.attribution[0], { capability: 'C2', layer: 2, outcome: 'died', frame: 9, encounter: 'E22', nodes: ['N9'], reason: 'r', last_harm: { frame: 9, source: 'hit', kind: 'hit' } });
  assert.deepEqual(p.attribution[1], {});
});
