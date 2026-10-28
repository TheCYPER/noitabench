import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeHarness, normalizeTranscript, parseRunSummary } from '../js/format/harness-run.js';
import { parseJsonl } from '../js/format/recording.js';
import { describeToolCall, parseTranscript, splitViews, turnForDecision } from '../js/replay/transcript.js';
import { fixtureBytes } from './helpers.js';

const lines = (...p) => parseJsonl(fixtureBytes(...p).toString('utf8'), p.join('/')).items;
const real = parseTranscript(normalizeTranscript(lines('harness_run', 'transcript.jsonl')));

test('the real transcript slice: turns, ranges and the opening', () => {
  assert.match(real.opening, /^Decision 1 \(frame 0, 0 s\)/);
  assert.equal(real.turns.length, 5 + 6 + 4, 'five at the start, the ones around the briefing (the last of them cut off), the last four');
  const [t1, t2] = real.turns;
  assert.deepEqual([t1.call, t1.first, t1.last], [1, 1, 1]);
  assert.deepEqual(t1.toolCalls.map((c) => c.name), ['swap_wand', 'aim', 'fire']);
  assert.equal(t1.toolCalls[1].text, 'aim(angle=-90)');
  assert.match(t1.thinking, /^With limited steps/);
  assert.equal(t1.results.length, 3);
  assert.deepEqual([t2.first, t2.last], [2, 2]);
});

test('a program is one turn that owns all its decisions', () => {
  const program = real.turns.find((t) => t.programs.length);
  assert.deepEqual([program.call, program.first, program.last], [5, 5, 39]);
  assert.equal(program.programs[0].label, 'run_code');
  assert.equal(program.programs[0].steps, 35);
  assert.equal(program.programs[0].firstDecision, 5);
  assert.equal(program.toolCalls[0].name, 'run_code');
  assert.match(program.toolCalls[0].code, /^game\.aim\(angle=0\)\nfor i in range\(60\):/);
  assert.equal(program.toolCalls[0].text, 'run_code()', 'the program text is kept apart from the call line');
  for (const n of [5, 12, 39]) assert.equal(turnForDecision(real.turns, n), program);
  assert.notEqual(turnForDecision(real.turns, 40), program);
});

test('turnForDecision finds nothing for decisions the log does not cover', () => {
  assert.equal(turnForDecision(real.turns, 100), null);
  assert.equal(turnForDecision(real.turns, 0), null);
  assert.equal(turnForDecision([], 1), null);
});

test('a program carries what its tool returned', () => {
  const program = real.turns.find((t) => t.programs.length);
  assert.match(program.programs[0].output, /^The program finished\.\nIt printed:/);
  const t = parseTranscript([
    A({ call: 1, decision: 0 }),
    { kind: 'code_run', label: 'run_code', job: 'code', ok: true, commands: 1, steps: 1, first_decision: 1, seconds: 0.1, error: '' },
    { kind: 'code_run', label: 'hook 3', job: 'code', ok: true, commands: 1, steps: 1, first_decision: 2, seconds: 0.1, error: '' },
    { kind: 'code_run', label: 'run_code', job: 'code', ok: false, commands: 0, steps: 0, first_decision: 3, seconds: 0.1, error: 'boom' },
    { kind: 'code_run', label: 'plugin route', job: 'code', ok: true, commands: 0, steps: 0, first_decision: 3, seconds: 0.1, error: '' },
    { kind: 'results', call: 1, decision: 2, results: [
      { name: 'run_code', is_error: false, content: 'first' }, { name: 'plugin_call', is_error: false, content: 'plugged' }, { name: 'run_code', is_error: true, content: 'second' },
    ] },
  ]);
  assert.deepEqual(t.turns[0].programs.map((p) => [p.label, p.output]), [['run_code', 'first'], ['hook 3', ''], ['run_code', 'second'], ['plugin route', 'plugged']]);
});

test('a program that failed still owns the decisions it made', () => {
  const failed = real.turns.find((t) => t.programs.some((p) => !p.ok));
  assert.deepEqual([failed.first, failed.last], [167, 168]);
  assert.match(failed.programs[0].error, /NoneType/);
});

test('the briefing sits after the decision the last turn ended on', () => {
  assert.equal(real.briefings.length, 1);
  assert.equal(real.briefings[0].after, 173);
  assert.match(real.briefings[0].text, /^BRIEFING/);
  assert.equal(real.turns.filter((t) => t.first === 174).length, 1, 'the next turn starts at 174');
});

test('the run ends with the reason', () => {
  assert.deepEqual(real.end, { over: 'dead', detail: '' });
});

test('splitViews cuts a text at its "Decision N" headers and tells full views from fragments', () => {
  const text = 'The program finished.\n0 Decision 8 (frame 840, 14 s). 993 left.\nStopped: completed\n1 Decision 10 (frame 900, 15 s). 991 left.\nStopped: x\n'
    + 'Decision 40 (frame 1790, 29.83 s).\nStopped: completed.\nCommands:\n  walk_to\nPosition x=240\nGoal: down\nMap: ...\n';
  const views = splitViews(text);
  assert.deepEqual(views.map((v) => [v.n, v.complete]), [[8, false], [10, false], [40, true]]);
  assert.match(views[2].text, /^Decision 40 \(frame 1790/);
  assert.match(views[2].text, /Map: \.\.\.$/);
  assert.deepEqual(splitViews('no views here'), []);
});

test('observations: the full view of every decision a turn ended on, fragments inside programs', () => {
  const obs = real.observations;
  assert.equal(obs.get(1).complete, true, 'from the opening');
  assert.match(obs.get(2).text, /^Decision 2 \(frame 210/, 'from the results of the first turn');
  assert.equal(obs.get(40).complete, true, 'the end of the program: its last view is printed in full');
  assert.equal(obs.get(8).complete, false, 'in the middle of the program: only the truncated print');
  assert.equal(obs.get(20).complete, false);
  assert.equal(obs.has(9), false, 'the program printed every other decision only');
  assert.match(obs.get(235).text, /^Decision 235/);
});

test('a full view wins over a fragment of the same decision', () => {
  const parsed = parseTranscript([
    { kind: 'results', call: 1, decision: 1, results: [{ name: 'run_code', content: '0 Decision 2 (frame 10, 1 s).\nStopped: x\n' }] },
    { kind: 'assistant', call: 2, decision: 1, text: '', thinking: '', tool_calls: [] },
    { kind: 'results', call: 2, decision: 2, results: [{ name: 'fire', content: 'Decision 2 (frame 10, 1 s).\nStopped: completed\nCommands:\n  fire\nPosition x=1\nGoal: g\nMap: m' }] },
  ]);
  assert.equal(parsed.observations.get(2).complete, true);
});

test('describeToolCall', () => {
  assert.deepEqual(describeToolCall({ name: 'fire', arguments: { until: { target_dead: true }, ticks: 15 } }),
    { name: 'fire', text: 'fire(until={"target_dead":true}, ticks=15)', code: null });
  assert.equal(describeToolCall({ name: 'kick', arguments: {} }).text, 'kick()');
  assert.equal(describeToolCall({ name: 'x' }).text, 'x()');
  assert.equal(describeToolCall({ name: 'workspace_write', arguments: { text: 'y'.repeat(500) } }).text.length < 300, true);
});

// ------------------------------------------------------------ shapes the real slice does not contain

const A = (extra) => ({ kind: 'assistant', purpose: 'play', text: '', thinking: '', tool_calls: [], ...extra });

test('helpers: events and their own turns are grouped under the turn that started them', () => {
  const t = parseTranscript([
    { kind: 'opening', text: 'Decision 1 (frame 0, 0 s)' },
    A({ call: 1, decision: 0, tool_calls: [{ id: 'a', name: 'spawn_agent', arguments: { task: 'plan a route' } }] }),
    { kind: 'helper', event: 'spawn', agent: 'h1', parent: 'player', depth: 1, text: 'plan a route' },
    A({ agent: 'h1', call: 1, purpose: 'helper', decision: 0, text: 'looking', tool_calls: [{ id: 'b', name: 'view', arguments: {} }] }),
    { kind: 'results', agent: 'h1', call: 1, results: [{ id: 'b', name: 'view', is_error: false, content: 'Decision 1 (frame 0...' }] },
    A({ agent: 'h1', call: 2, purpose: 'helper', decision: 0, text: 'go right' }),
    { kind: 'helper', event: 'answer', agent: 'h1', parent: 'player', depth: 1, text: 'go right', state: 'done' },
    { kind: 'results', call: 1, decision: 0, results: [{ id: 'a', name: 'spawn_agent', is_error: false, content: '{"answer":"go right"}' }] },
    A({ call: 2, decision: 0, tool_calls: [{ id: 'c', name: 'walk_to', arguments: { x: 10 } }] }),
    { kind: 'results', call: 2, decision: 1, results: [{ id: 'c', name: 'walk_to', is_error: false, content: 'Decision 2 (frame 50' }] },
  ]);
  assert.equal(t.turns.length, 2);
  const [first, second] = t.turns;
  assert.equal(first.helpers.length, 1);
  const hp = first.helpers[0];
  assert.deepEqual([hp.id, hp.kind, hp.parent, hp.depth], ['h1', 'spawn', 'player', 1]);
  assert.deepEqual(hp.events.map((e) => [e.event, e.state]), [['spawn', ''], ['answer', 'done']]);
  assert.equal(hp.turns.length, 2);
  assert.equal(hp.turns[0].results.length, 1, 'the helper results record went to the helper turn that was waiting');
  assert.equal(hp.turns[1].results, null);
  assert.equal(second.helpers.length, 0);
  assert.deepEqual([first.first, first.last], [1, 0], 'a turn that made no decision has an empty range');
  assert.equal(turnForDecision(t.turns, 1), second);
});

test('hooks, library installs and harness notes attach to their turn; a briefing between turns is its own record', () => {
  const t = parseTranscript([
    A({ call: 1, decision: 3 }),
    { kind: 'code_run', label: 'hook 2', job: 'code', ok: true, commands: 4, steps: 4, first_decision: 4, seconds: 0.1, error: '' },
    { kind: 'lib_install', name: 'networkx', ok: true, detail: 'installed', installed: ['networkx'], via: 'wheelhouse' },
    { kind: 'results', call: 1, decision: 8, results: [] },
    { kind: 'note', text: 'no usable command', nudge: 'use a tool' },
    A({ call: 2, decision: 8 }),
    { kind: 'note', text: 'refused; the same step is sent again' },
    A({ call: 2, decision: 8, text: 'again' }),
    { kind: 'results', call: 2, decision: 9, results: [{ name: 'wait', is_error: false, content: '' }] },
    A({ call: 3, purpose: 'summary', decision: 9 }),
    { kind: 'summary', call: 3, text: 'BRIEFING' },
    { kind: 'end', over: 'decision_limit', detail: '' },
  ]);
  assert.equal(t.turns.length, 3);
  assert.deepEqual(t.turns[0].programs.map((p) => p.label), ['hook 2']);
  assert.deepEqual(t.turns[0].installs.map((i) => [i.name, i.ok]), [['networkx', true]]);
  assert.deepEqual([t.turns[0].first, t.turns[0].last], [4, 8]);
  assert.deepEqual(t.looseNotes.map((n) => n.after), [8], 'a note between turns is kept with the decision count at that time');
  assert.deepEqual([t.turns[1].first, t.turns[1].last], [9, 8], 'the refused turn made no decision');
  assert.deepEqual(t.turns[1].notes, ['refused; the same step is sent again']);
  assert.equal(t.briefings[0].after, 9);
  assert.equal(t.end.over, 'decision_limit');
  assert.equal(t.turns.some((x) => x.call === 3), false, 'the briefing call is not a play turn');
});

test('text mode: the reply text is the result', () => {
  const t = parseTranscript([
    A({ call: 1, decision: 0, text: 'fire()' }),
    { kind: 'results', call: 1, decision: 1, text: 'Decision 2 (frame 10, 1 s).\nStopped: completed' },
  ]);
  assert.deepEqual(t.turns[0].results, [{ name: '', isError: false, content: 'Decision 2 (frame 10, 1 s).\nStopped: completed' }]);
  assert.equal(t.observations.has(2), true);
});

test('a log that stops in the middle of a turn does not break the parse', () => {
  const t = parseTranscript([A({ call: 1, decision: 0, tool_calls: [{ id: 'a', name: 'wait', arguments: {} }] })]);
  assert.equal(t.turns.length, 1);
  assert.equal(t.turns[0].results, null);
  assert.equal(t.end, null);
});

test('a tool call that is not an object is shown as ?()', () => {
  for (const odd of [null, undefined, 5, 'x', [1]]) assert.equal(describeToolCall(odd).text, '?()');
  const t = parseTranscript(normalizeTranscript([{ kind: 'assistant', call: 1, decision: 0, tool_calls: [null, 7, { name: 'wait' }] }]));
  assert.deepEqual(t.turns[0].toolCalls.map((c) => c.text), ['?()', '?()', 'wait()']);
});

test('garbage records are skipped', () => {
  assert.deepEqual(normalizeTranscript([{ kind: 1 }, { nokind: true }, { kind: 'end' }]), [{ kind: 'end' }]);
  const t = parseTranscript(normalizeTranscript([{ kind: 'mystery', x: 1 }, { kind: 'results', call: 1 }]));
  assert.deepEqual(t.turns, []);
});

test('harness rows and the summary', () => {
  assert.equal(normalizeHarness([{ call: 1 }, { nothing: 1 }, 'x', { decision: 3 }]).length, 2);
  const s = parseRunSummary(JSON.parse(fixtureBytes('harness_run', 'summary.json').toString('utf8')));
  assert.equal(s.model, 'claude-haiku-5-5');
  assert.equal(s.over, 'dead');
  assert.equal(s.decisions, 235);
  assert.equal(s.modelCalls, 47);
  assert.equal(s.costUsd, 0.051279);
  assert.equal(s.maxUsd, 3);
  assert.deepEqual(s.layers, ['L0', 'L1', 'L2', 'L3', 'L4', 'L5']);
  assert.equal(JSON.stringify(s).includes('424242'), false, 'the world seed is not copied out');
  assert.equal(JSON.stringify(s).includes('717171'), false, 'the rule seed is not copied out');
  assert.equal(parseRunSummary({ format: 'other/0' }), null);
  assert.equal(parseRunSummary(null), null);
  assert.equal(parseRunSummary({ format: 'cogbench-harness-run/0' }).model, '');
});
