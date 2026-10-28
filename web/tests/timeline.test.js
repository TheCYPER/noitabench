import test from 'node:test';
import assert from 'node:assert/strict';
import { parseJsonl } from '../js/format/recording.js';
import {
  STOP_REASONS, buildMarks, commandText, flagged, fractionIn, frameAtDecision, markAtFrame, markLabel, stopRank, stopStyle,
} from '../js/replay/timeline.js';
import { axisLength, columnOf, columnsFor, markAtAxis, spanOf } from '../js/replay/timeline-axis.js';
import { fixtureBytes } from './helpers.js';

const lines = (...p) => parseJsonl(fixtureBytes(...p).toString('utf8'), p.join('/')).items;
const decisions = lines('harness_run', 'decisions.jsonl');

test('marks come straight from decisions.jsonl', () => {
  const marks = buildMarks(decisions);
  assert.equal(marks.length, 54);
  const [first, second] = marks;
  assert.deepEqual([first.pos, first.index, first.frame, first.frames, first.endFrame], [0, 1, 0, 210, 210]);
  assert.equal(first.stopReason, 'start');
  assert.deepEqual(first.commands, ['swap_wand(wand=1)', 'aim(angle=-90)', 'fire(until={ticks: 20})']);
  assert.equal(second.frame, 210);
  assert.equal(second.stopDetail, 'ticks', 'the detail is why the previous command stopped');
  assert.equal(first.stopDetail, '');
  assert.equal(first.digest, '9fad29a0d32565cc');
});

test('the death is the decision whose result says dead', () => {
  const marks = buildMarks(decisions);
  const died = flagged(marks, 'died');
  assert.deepEqual(died, [53]);
  assert.equal(marks[53].index, 235);
  assert.equal(marks[52].died, false);
  assert.match(markLabel(marks[53]), /^#235 {2}f16550 {2}invalid .*死亡$/);
});

test('failed commands are marked not ok', () => {
  const marks = buildMarks(decisions);
  const bad = marks.filter((m) => !m.ok).map((m) => m.index);
  assert.deepEqual(bad, [174, 233, 234]);
});

test('extra: a briefing before a decision and a death announced by the transcript', () => {
  const marks = buildMarks(decisions.slice(0, 3), { briefingBefore: new Set([2]), diedAtEnd: true });
  assert.deepEqual(marks.map((m) => [m.briefing, m.died]), [[false, false], [true, false], [false, true]]);
  assert.deepEqual(buildMarks(decisions.slice(0, 3)).map((m) => m.died), [false, false, false]);
});

test('older recordings: string commands, 0-based index, no frames field', () => {
  const synthetic = lines('rec_synthetic', 'decisions.jsonl');
  const marks = buildMarks(synthetic);
  assert.deepEqual(marks.map((m) => m.index), [0, 1, 2]);
  assert.deepEqual(marks[0].commands, ['walk_to(x=100)']);
  assert.deepEqual(marks.map((m) => m.frames), [40, 50, 0], 'a missing frames field is the gap to the next decision');
  assert.equal(marks[0].cost, null);
});

test('commandText covers every shape', () => {
  assert.equal(commandText({ name: 'kick', args: {} }), 'kick()');
  assert.equal(commandText({ name: 'walk_to', args: { x: 140, until: { ticks: 3, blocked: true } } }), 'walk_to(x=140, until={ticks: 3, blocked: true})');
  assert.equal(commandText({ name: 'aim', args: { target: '51' } }), 'aim(target="51")');
  assert.equal(commandText('wait'), 'wait');
  assert.equal(commandText(null), '""');
});

test('markAtFrame: the last decision asked at or before the frame', () => {
  const marks = buildMarks(decisions);
  assert.equal(markAtFrame(marks, 0), 0);
  assert.equal(markAtFrame(marks, 209), 0);
  assert.equal(markAtFrame(marks, 210), 1);
  assert.equal(markAtFrame(marks, 99999), 53);
  assert.equal(markAtFrame(marks, -1), -1);
});

test('markAtFrame holds the picked decision while the clock stands on its frame', () => {
  // decisions 5 and 6 of the real run share frame 780 (aim takes no time)
  const marks = buildMarks([
    { frame: 100, index: 1, stop_reason: 'start', command: [] },
    { frame: 780, index: 2, stop_reason: 'completed', command: [], frames: 0 },
    { frame: 780, index: 3, stop_reason: 'completed', command: [], frames: 60 },
    { frame: 840, index: 4, stop_reason: 'completed', command: [] },
  ]);
  assert.equal(markAtFrame(marks, 780), 2, 'no pick: the last one of the frame');
  assert.equal(markAtFrame(marks, 780, 1), 1, 'picked: kept');
  assert.equal(markAtFrame(marks, 781, 1), 2, 'the clock moved on: the later decision');
  assert.equal(markAtFrame(marks, 779, 1), 0, 'the clock went back');
});

test('frameAtDecision interpolates inside a decision', () => {
  const marks = buildMarks(decisions);
  assert.equal(frameAtDecision(marks, 0), 0);
  assert.equal(frameAtDecision(marks, 0.5), 105);
  assert.equal(frameAtDecision(marks, 1), 210);
  assert.equal(frameAtDecision(marks, 1.5), 360);
  assert.equal(frameAtDecision(marks, 54), 16580, 'past the end: the end of the last decision');
  assert.equal(frameAtDecision(marks, -3), 0);
  assert.equal(frameAtDecision([], 4, 77), 77);
  assert.equal(frameAtDecision(marks, NaN), 0, 'a position that is not a number is the start');
});

test('fractionIn', () => {
  const marks = buildMarks(decisions);
  assert.equal(fractionIn(marks[0], 105), 0.5);
  assert.equal(fractionIn(marks[0], 9999), 1);
  assert.equal(fractionIn(marks[0], -5), 0);
  assert.equal(fractionIn({ frame: 5, frames: 0 }, 5), 0);
});

test('stop reasons rank dead first and unknown ones last', () => {
  assert.equal(STOP_REASONS[0], 'dead');
  assert.ok(stopRank('dead') > stopRank('invalid'));
  assert.ok(stopRank('invalid') > stopRank('interrupted'));
  assert.ok(stopRank('interrupted') > stopRank('completed'));
  assert.ok(stopRank('completed') > stopRank('start'));
  assert.equal(stopRank('made_up'), 0);
  assert.equal(stopStyle('made_up').label, '其他');
  for (const odd of ['__proto__', 'constructor', 'toString', 'hasOwnProperty']) assert.equal(stopStyle(odd).label, '其他', odd);
  assert.match(stopStyle('completed').color, /^#[0-9a-f]{6}$/);
});

// ------------------------------------------------------------ axis

test('axis spans and lengths', () => {
  const marks = buildMarks(decisions);
  assert.deepEqual(spanOf('decision', marks[3]), [3, 4]);
  assert.deepEqual(spanOf('frame', marks[1]), [210, 510]);
  assert.equal(axisLength('decision', [{ marks }, { marks: marks.slice(0, 4) }]), 54);
  assert.equal(axisLength('frame', [{ marks, lastFrame: 20000 }]), 20000);
  assert.equal(axisLength('frame', [{ marks }]), 16580, 'no lastFrame: the end of the last decision');
  assert.equal(axisLength('decision', []), 0);
});

test('markAtAxis', () => {
  const marks = buildMarks(decisions);
  assert.equal(markAtAxis('decision', marks, 3.7), 3);
  assert.equal(markAtAxis('decision', marks, 54), -1);
  assert.equal(markAtAxis('decision', marks, 54, true), 53);
  assert.equal(markAtAxis('decision', marks, -1), -1);
  assert.equal(markAtAxis('frame', marks, 300), 1);
  assert.equal(markAtAxis('frame', marks, 99999), -1);
  assert.equal(markAtAxis('frame', marks, 99999, true), 53);
  assert.equal(markAtAxis('frame', [], 5), -1);
});

test('columnsFor: every mark gets a column, the most important reason wins a shared one', () => {
  const marks = buildMarks([
    { frame: 0, index: 1, stop_reason: 'start', command: [], frames: 10 },
    { frame: 10, index: 2, stop_reason: 'completed', command: [], frames: 10 },
    { frame: 20, index: 3, stop_reason: 'interrupted', command: [], frames: 10 },
    { frame: 30, index: 4, stop_reason: 'completed', command: [], frames: 10 },
  ]);
  assert.deepEqual([...columnsFor('decision', marks, 4, 4)], [0, 1, 2, 3]);
  assert.deepEqual([...columnsFor('decision', marks, 4, 2)], [1, 2], 'two marks per column: completed beats start, interrupted beats completed');
  assert.deepEqual([...columnsFor('decision', marks, 4, 8)], [0, 0, 1, 1, 2, 2, 3, 3]);
  assert.deepEqual([...columnsFor('decision', marks, 4, 1)], [2]);
  assert.deepEqual([...columnsFor('decision', marks, 0, 3)], [-1, -1, -1]);
  const long = buildMarks(decisions);
  const cols = columnsFor('decision', long, 54, 5);
  assert.ok(cols.every((c) => c >= 0));
  assert.equal(cols[cols.length - 1], 53, 'the death, though it shares a column with others, wins it');
});

test('columnsFor in frame mode gives a zero-length mark one column', () => {
  const marks = buildMarks([
    { frame: 0, index: 1, stop_reason: 'start', command: [], frames: 100 },
    { frame: 100, index: 2, stop_reason: 'invalid', command: [], frames: 0 },
    { frame: 100, index: 3, stop_reason: 'completed', command: [], frames: 100 },
  ]);
  const cols = [...columnsFor('frame', marks, 200, 20)];
  assert.equal(cols[10], 1, 'invalid outranks completed in the shared column');
  assert.equal(cols[0], 0);
  assert.equal(cols[19], 2);
});

test('columnOf puts a flag in the first column of a mark', () => {
  const marks = buildMarks(decisions);
  assert.equal(columnOf('decision', marks[13], 54, 108), 26);
  assert.equal(columnOf('decision', marks[53], 54, 108), 106);
  assert.equal(columnOf('frame', marks[1], 16580, 1000), 12);
  assert.equal(columnOf('decision', marks[0], 0, 10), 0);
});

test('index counts what the budget used, view is the number the player saw', () => {
  // costs 1, 2 (an inspect on top), 0 (notes only), 1
  const marks = buildMarks([
    { frame: 0, index: 1, cost: 1, stop_reason: 'start', command: [] },
    { frame: 10, index: 3, cost: 2, stop_reason: 'completed', command: [] },
    { frame: 20, index: 3, cost: 0, stop_reason: 'completed', command: [] },
    { frame: 20, index: 4, cost: 1, stop_reason: 'completed', command: [] },
  ]);
  assert.deepEqual(marks.map((m) => m.index), [1, 3, 3, 4]);
  assert.deepEqual(marks.map((m) => m.view), [1, 2, 4, 4]);
  assert.match(markLabel(marks[1]), /^#2 /);
  const withBriefing = buildMarks([
    { frame: 0, index: 1, cost: 0, stop_reason: 'start', command: [] },
    { frame: 0, index: 1, cost: 1, stop_reason: 'start', command: [] },
  ], { briefingBefore: new Set([2]) });
  assert.deepEqual(withBriefing.map((m) => m.view), [2, 1]);
  assert.deepEqual(withBriefing.map((m) => m.briefing), [true, false], 'only the first decision with that number gets the flag');
});
