import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeHarness, normalizeTranscript } from '../js/format/harness-run.js';
import { parseJsonl } from '../js/format/recording.js';
import { buildCostIndex, costAtDecision, rowOfCall } from '../js/replay/costs.js';
import { buildModel, detailFor } from '../js/replay/model.js';
import { callText, countText, programText, resultText, stopText, summaryText, usdText } from '../js/replay/text.js';
import { parseRunSummary } from '../js/format/harness-run.js';
import { fixtureBytes } from './helpers.js';

const lines = (...p) => parseJsonl(fixtureBytes(...p).toString('utf8'), p.join('/')).items;
const harness = normalizeHarness(lines('harness_run', 'harness.jsonl'));
const runParts = {
  decisions: lines('harness_run', 'decisions.jsonl'),
  transcript: normalizeTranscript(lines('harness_run', 'transcript.jsonl')),
  harness,
};

test('cost so far counts every call up to the one that decided', () => {
  const idx = buildCostIndex(harness);
  assert.deepEqual(costAtDecision(idx, 1), { usd: 0.000462, calls: 1, helperCalls: 0 });
  assert.deepEqual(costAtDecision(idx, 2), { usd: 0.00094, calls: 2, helperCalls: 0 });
  // decision 5 is decided by call 5 (made after 4 decisions); decision 6 is inside the same program, the next call is call 6
  assert.equal(costAtDecision(idx, 5).calls, 5);
  assert.equal(costAtDecision(idx, 39).calls, 5);
  assert.equal(costAtDecision(idx, 40).calls, 6);
  assert.equal(costAtDecision(idx, 40).usd, 0.00536);
});

test('the briefing call is part of the cost of the decision after it', () => {
  const idx = buildCostIndex(harness);
  assert.equal(costAtDecision(idx, 173).usd, 0.035310, 'before the briefing call');
  assert.equal(costAtDecision(idx, 174).usd, 0.038368, 'after the briefing and the next play call');
});

test('past the last row the total stays; spend never goes down', () => {
  const idx = buildCostIndex(harness);
  assert.equal(costAtDecision(idx, 5000).usd, 0.051279);
  let prev = 0;
  for (let n = 1; n <= 240; n++) {
    const c = costAtDecision(idx, n).usd;
    assert.ok(c >= prev, `decision ${n}`);
    prev = c;
  }
});

test('helper calls are counted apart and share the cumulative total', () => {
  const idx = buildCostIndex([
    { call: 1, decision: 0, cumulative_usd: 0.01, cost_usd: 0.01 },
    { call: 1, decision: 0, agent: 'h1', cumulative_usd: 0.03, cost_usd: 0.02 },
    { call: 2, decision: 1, cumulative_usd: 0.04, cost_usd: 0.01 },
  ]);
  assert.deepEqual(costAtDecision(idx, 1), { usd: 0.03, calls: 2, helperCalls: 1 });
  assert.deepEqual(costAtDecision(idx, 2), { usd: 0.04, calls: 3, helperCalls: 1 });
  assert.equal(rowOfCall(idx, 1).costUsd, 0.01, 'the player call, not the helper one');
});

test('a damaged row with a huge decision number costs nothing and breaks nothing', () => {
  const idx = buildCostIndex([
    { call: 1, decision: 0, cumulative_usd: 0.01, cost_usd: 0.01 },
    { call: 2, decision: 1e30, cumulative_usd: 5, cost_usd: 5 },
    { call: 3, decision: 4294967296, cumulative_usd: 6, cost_usd: 1 },
    { call: 4, decision: -3, cumulative_usd: 7, cost_usd: 1 },
    { call: 5, decision: 2.5, cumulative_usd: 8, cost_usd: 1 },
  ]);
  assert.deepEqual(costAtDecision(idx, 1), { usd: 0.01, calls: 1, helperCalls: 0 });
  assert.deepEqual(costAtDecision(idx, 5000), { usd: 0.01, calls: 1, helperCalls: 0 }, 'a row with a huge number counts only for decisions that far on');
  assert.deepEqual(costAtDecision(idx, 4294967298), { usd: 6, calls: 2, helperCalls: 0 });
  assert.equal(costAtDecision(idx, 1e31).calls, 3, 'a negative or fractional number is not placed on the timeline');
  assert.equal(costAtDecision(idx, 0).calls, 1, 'decision numbers below 1 are read as the first');
});

test('rows out of order and several rows per decision number', () => {
  const idx = buildCostIndex([
    { call: 3, decision: 2, cumulative_usd: 0.03, cost_usd: 0.01 },
    { call: 1, decision: 0, cumulative_usd: 0.01, cost_usd: 0.01 },
    { call: 2, decision: 2, agent: 'h1', cumulative_usd: 0.02, cost_usd: 0.01 },
  ]);
  assert.deepEqual(costAtDecision(idx, 1), { usd: 0.01, calls: 1, helperCalls: 0 });
  assert.deepEqual(costAtDecision(idx, 2), { usd: 0.01, calls: 1, helperCalls: 0 });
  assert.deepEqual(costAtDecision(idx, 3), { usd: 0.03, calls: 3, helperCalls: 1 });
});

test('no cost log, unpriced model', () => {
  assert.equal(costAtDecision(buildCostIndex([]), 3), null);
  const idx = buildCostIndex([{ call: 1, decision: 0, cumulative_usd: null, cost_usd: null }]);
  assert.deepEqual(costAtDecision(idx, 1), { usd: null, calls: 1, helperCalls: 0 });
  assert.equal(rowOfCall(idx, 99), null);
});

test('rowOfCall reads one row', () => {
  const row = rowOfCall(buildCostIndex(harness), 3);
  assert.equal(row.costUsd, 0.001003);
  assert.equal(row.latency, 9.251);
  assert.equal(row.outputTokens, 1255);
  assert.equal(row.promptTokens, 21153);
});

// ------------------------------------------------------------ the model

test('model: marks carry the briefing and the death from the transcript', () => {
  const model = buildModel(runParts);
  assert.equal(model.marks.length, 54);
  const brief = model.marks.filter((m) => m.briefing).map((m) => m.index);
  assert.deepEqual(brief, [174]);
  assert.deepEqual(model.marks.filter((m) => m.died).map((m) => m.index), [235]);
  assert.equal(model.hasTranscript, true);
  assert.equal(model.hasCosts, true);
});

test('model: a briefing at the very end of a run belongs to the last decision', () => {
  const model = buildModel({
    decisions: [{ frame: 0, index: 1, stop_reason: 'start', command: [] }],
    transcript: [
      { kind: 'assistant', purpose: 'play', call: 1, decision: 0, text: '', thinking: '', tool_calls: [] },
      { kind: 'results', call: 1, decision: 1, results: [] },
      { kind: 'summary', call: 2, text: 'B' },
    ],
  });
  assert.equal(model.marks[0].briefing, true);
});

test('detail of a decision inside a program', () => {
  const model = buildModel(runParts);
  const pos = model.marks.findIndex((m) => m.index === 12);
  const d = detailFor(model, pos);
  assert.equal(d.mark.index, 12);
  assert.equal(d.turn.call, 5);
  assert.deepEqual(d.inTurn, { k: 8, count: 35 });
  assert.equal(d.observation.complete, false, 'decision 12 was only printed in part');
  assert.equal(d.cost.calls, 5);
  assert.equal(d.call.costUsd, 0.001374);
  assert.equal(d.briefing, null);
  assert.equal(d.end, null);
  assert.equal(d.total, 54);
});

test('detail of the first decision has the opening as its view', () => {
  const model = buildModel(runParts);
  const d = detailFor(model, 0);
  assert.equal(d.observation.complete, true);
  assert.match(d.observation.text, /^Decision 1 \(frame 0, 0 s\)/);
  assert.deepEqual(d.inTurn, { k: 1, count: 1 });
  assert.match(d.turn.thinking, /efficient/);
});

test('detail of the decision after a briefing and of the last one', () => {
  const model = buildModel(runParts);
  const after = detailFor(model, model.marks.findIndex((m) => m.index === 174));
  assert.match(after.briefing.text, /^BRIEFING/);
  const last = detailFor(model, model.marks.length - 1);
  assert.deepEqual(last.end, { over: 'dead', detail: '' });
  assert.equal(last.mark.died, true);
  assert.match(last.observation.text, /^Decision 235/);
});

test('detail of a decision the transcript does not cover', () => {
  const model = buildModel(runParts);
  const d = detailFor(model, model.marks.findIndex((m) => m.index === 233));
  assert.equal(d.turn.call, 45);
  const gap = buildModel({ decisions: [{ frame: 0, index: 99, stop_reason: 'start', command: [] }], transcript: runParts.transcript });
  const g = detailFor(gap, 0);
  assert.equal(g.turn, null);
  assert.equal(g.hasTranscript, true);
  assert.equal(g.observation, null);
});

test('a human run: commands and stop reasons only', () => {
  const human = lines('human_run', 'decisions.jsonl');
  assert.ok(human.length > 5);
  const model = buildModel({ decisions: human });
  assert.equal(model.hasTranscript, false);
  assert.equal(model.hasCosts, false);
  assert.equal(model.marks.filter((m) => m.briefing || m.died).length, 0);
  const d = detailFor(model, 3);
  assert.equal(d.turn, null);
  assert.equal(d.observation, null);
  assert.equal(d.cost, null);
  assert.equal(d.call, null);
  assert.equal(d.hasTranscript, false);
  assert.ok(d.mark.commands.length >= 1);
  assert.match(d.mark.commands[0], /^\w+\(/);
});

test('a bot run: no decisions at all', () => {
  const model = buildModel({});
  assert.deepEqual(model.marks, []);
  assert.equal(detailFor(model, 0), null);
});

// ------------------------------------------------------------ texts

test('usd, counts, results', () => {
  assert.equal(usdText(0.051279), '$0.0513');
  assert.equal(usdText(12.3456), '$12.35');
  assert.equal(usdText(null), '—');
  assert.equal(countText(1234567), '1,234,567');
  assert.equal(countText(undefined), '—');
  assert.equal(resultText({ reason: 'completed', detail: 'reached', ticks: 2, frames: 20 }), 'completed (reached) · 2 tick · 20 帧');
  assert.equal(resultText({ reason: 'invalid', code: 'not_in_view', message: 'aim: no 51 is in view.', ticks: 1, frames: 10 }),
    'invalid not_in_view · 1 tick · 10 帧 · aim: no 51 is in view.');
  assert.equal(resultText(null), '');
  assert.equal(stopText({ stopReason: 'interrupted', stopDetail: 'damage' }), 'interrupted (damage)');
  assert.equal(stopText({ stopReason: '', stopDetail: '' }), '—');
});

test('program, call and summary lines', () => {
  assert.equal(programText({ label: 'run_code', ok: true, commands: 35, steps: 35, seconds: 0.475, limit: null, ended: null, error: '' }),
    'run_code · 35 条指令 · 35 步 · 0.475 s');
  assert.equal(programText({ label: 'hook 2', ok: false, commands: null, steps: null, seconds: null, limit: 'cpu', ended: 'dead', error: 'x' }),
    'hook 2 · 失败 · 触到上限：cpu · 游戏结束：dead');
  assert.equal(callText(rowOfCall(buildCostIndex(harness), 1)), '$0.0005 · 3.813 s · 输出 330 token · 上下文 17,914');
  assert.equal(callText(null), '');
  const s = parseRunSummary(JSON.parse(fixtureBytes('harness_run', 'summary.json').toString('utf8')));
  assert.equal(summaryText(s), 'claude-haiku-5-5 · 结束：dead · 235 个决策 · 47 次调用 · $0.0513');
});

test('decisions that cost more than one are matched to the transcript by the number the player saw', () => {
  const a = (call, decision, extra = {}) => ({ kind: 'assistant', purpose: 'play', call, decision, text: '', thinking: '', tool_calls: [], ...extra });
  const model = buildModel({
    decisions: [
      { frame: 0, index: 1, cost: 1, stop_reason: 'start', command: [{ name: 'wait', args: {} }] },
      { frame: 10, index: 3, cost: 2, stop_reason: 'completed', command: [{ name: 'inspect', args: { x: 1, y: 2 } }, { name: 'wait', args: {} }] },
      { frame: 20, index: 4, cost: 1, stop_reason: 'completed', command: [{ name: 'fire', args: {} }] },
    ],
    transcript: [
      { kind: 'opening', text: 'Decision 1 (frame 0, 0 s).\nStopped: start.\nA\nB\nC\nD' },
      a(1, 0, { text: 'first' }),
      { kind: 'results', call: 1, decision: 1, results: [{ name: 'wait', is_error: false, content: 'Decision 2 (frame 10, 0 s).\nStopped: completed.\nA\nB\nC\nD' }] },
      a(2, 1, { text: 'second' }),
      { kind: 'results', call: 2, decision: 3, results: [{ name: 'inspect', is_error: false, content: 'Decision 4 (frame 20, 0 s).\nStopped: completed.\nA\nB\nC\nD' }] },
      a(3, 3, { text: 'third' }),
      { kind: 'results', call: 3, decision: 4, results: [] },
    ],
    harness: [
      { call: 1, decision: 0, cumulative_usd: 0.1 }, { call: 2, decision: 1, cumulative_usd: 0.2 }, { call: 3, decision: 3, cumulative_usd: 0.3 },
    ],
  });
  assert.deepEqual(model.marks.map((m) => m.view), [1, 2, 4]);
  const second = detailFor(model, 1);
  assert.equal(second.turn.text, 'second');
  assert.match(second.observation.text, /^Decision 2 \(frame 10/);
  assert.deepEqual(second.inTurn, { k: 1, count: 1 });
  assert.equal(second.cost.usd, 0.2, 'what had been spent when the player was shown Decision 2');
  const third = detailFor(model, 2);
  assert.equal(third.turn.text, 'third');
  assert.match(third.observation.text, /^Decision 4 \(frame 20/);
  assert.equal(third.cost.usd, 0.3);
});

test('a notes-only decision (cost 0) shares its number with the next one and does not borrow its turn', () => {
  const a = (call, decision, extra = {}) => ({ kind: 'assistant', purpose: 'play', call, decision, text: '', thinking: '', tool_calls: [], ...extra });
  const view = (n) => `Decision ${n} (frame 0, 0 s).\nStopped: completed.\nA\nB\nC\nD`;
  const model = buildModel({
    decisions: [
      { frame: 0, index: 0, cost: 0, stop_reason: 'start', command: [{ name: 'memory_write', args: { path: 'a' } }], frames: 0 },
      { frame: 0, index: 1, cost: 1, stop_reason: 'start', command: [{ name: 'wait', args: {} }], frames: 10 },
    ],
    transcript: [
      { kind: 'opening', text: view(1) },
      a(1, 0, { text: 'write a note' }),
      { kind: 'results', call: 1, decision: 0, text: view(1) },
      a(2, 0, { text: 'now wait' }),
      { kind: 'results', call: 2, decision: 1, text: view(2) },
    ],
    harness: [{ call: 1, decision: 0, cumulative_usd: 0.1 }, { call: 2, decision: 0, cumulative_usd: 0.2 }],
  });
  assert.deepEqual(model.marks.map((m) => [m.view, m.cost]), [[1, 0], [1, 1]]);
  const notes = detailFor(model, 0);
  assert.equal(notes.turn, null, 'the turn that owns Decision 1 is the second one');
  assert.match(notes.observation.text, /^Decision 1 /);
  const wait = detailFor(model, 1);
  assert.equal(wait.turn.text, 'now wait');
  assert.deepEqual(wait.inTurn, { k: 1, count: 1 });
});
