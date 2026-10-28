import test from 'node:test';
import assert from 'node:assert/strict';
import {
  axisEnd, axisStep, canCompareByDecision, effectiveMode, frameForAxis, nowInfo, rateOf,
} from '../js/compare/axis.js';
import { followZoom, playerAt, playerTrack } from '../js/replay/follow.js';
import { buildMarks } from '../js/replay/timeline.js';

// ------------------------------------------------------------ following the player

test('playerTrack takes the player centre per recorded frame', () => {
  const track = playerTrack([
    { frame: 0, entities: [{ kind: 'bottle', x: 1, y: 1 }, { kind: 'player', x: 10, y: 20, w: 6, h: 14 }] },
    { frame: 12, entities: [{ kind: 'bottle', x: 1, y: 1 }] },
    { frame: 24, entities: [{ kind: 'player', x: 14, y: 20 }] },
  ]);
  assert.deepEqual(track, [{ frame: 0, x: 13, y: 27 }, { frame: 24, x: 14, y: 20 }]);
  assert.deepEqual(playerTrack([]), []);
});

test('playerAt is the last record at or before the frame', () => {
  const track = [{ frame: 0, x: 1, y: 1 }, { frame: 24, x: 2, y: 2 }];
  assert.equal(playerAt(track, 23).x, 1);
  assert.equal(playerAt(track, 24).x, 2);
  assert.equal(playerAt(track, 999).x, 2);
  assert.equal(playerAt([{ frame: 5, x: 1, y: 1 }], 4), null);
  assert.equal(playerAt([], 4), null);
});

test('followZoom: the largest level that still shows about 256 cells', () => {
  assert.equal(followZoom(700), 2);
  assert.equal(followZoom(1200), 4);
  assert.equal(followZoom(390), 1);
  assert.equal(followZoom(300), 1);
  assert.equal(followZoom(600), 2);
  assert.equal(followZoom(100), 0.25);
  assert.equal(followZoom(10), 0.25);
});

// ------------------------------------------------------------ the compare axis

const dec = (frame, frames, index, extra = {}) => ({ frame, frames, index, stop_reason: 'completed', command: [{ name: 'wait', args: {} }], ...extra });
const runA = { firstFrame: 0, lastFrame: 400, meta: { frameStride: 12 }, model: { marks: buildMarks([dec(0, 100, 1), dec(100, 200, 2), dec(300, 100, 3)]) } };
const runB = { firstFrame: 0, lastFrame: 1000, meta: { frameStride: 10 }, model: { marks: buildMarks([dec(0, 500, 1), dec(500, 500, 2)]) } };
const runBot = { firstFrame: 0, lastFrame: 600, meta: { frameStride: 12 }, model: { marks: [] } };

test('mode: decision mode needs decisions in every run', () => {
  assert.equal(canCompareByDecision([runA, runB]), true);
  assert.equal(canCompareByDecision([runA, runBot]), false);
  assert.equal(canCompareByDecision([]), false);
  assert.equal(effectiveMode('decision', [runA, runB]), 'decision');
  assert.equal(effectiveMode('decision', [runA, runBot]), 'frame');
  assert.equal(effectiveMode('frame', [runA, runB]), 'frame');
});

test('axis length is the longest run', () => {
  assert.equal(axisEnd('frame', [runA, runB]), 1000);
  assert.equal(axisEnd('decision', [runA, runB]), 3);
  assert.equal(axisEnd('frame', []), 0);
});

test('frame mode: every run shows the same game frame, clamped to its own length', () => {
  assert.equal(frameForAxis('frame', runA, 250), 250);
  assert.equal(frameForAxis('frame', runA, 900), 400, 'run A is over: it stays on its last frame');
  assert.equal(frameForAxis('frame', runA, -5), 0);
});

test('decision mode: every run shows the same decision, however long it took', () => {
  assert.equal(frameForAxis('decision', runA, 0), 0);
  assert.equal(frameForAxis('decision', runA, 1), 100);
  assert.equal(frameForAxis('decision', runB, 1), 500);
  assert.equal(frameForAxis('decision', runA, 1.5), 200);
  assert.equal(frameForAxis('decision', runB, 1.5), 750);
  assert.equal(frameForAxis('decision', runB, 2), 1000);
  assert.equal(frameForAxis('decision', runA, 3), 400, 'past its last decision: the end of the run');
  assert.equal(frameForAxis('decision', runBot, 1), 0, 'no decisions: the first frame');
});

test('rates and steps', () => {
  assert.equal(rateOf('frame'), 60);
  assert.equal(rateOf('decision'), 2);
  assert.equal(axisStep('frame', [runA, runB]), 12);
  assert.equal(axisStep('decision', [runA, runB]), 1);
});

test('nowInfo names the decision a pane is on', () => {
  let info = nowInfo('frame', runA, 150, 150);
  assert.equal(info.pos, 1);
  assert.equal(info.text, '#2  f100  completed  wait()');
  assert.equal(info.ended, false);
  info = nowInfo('frame', runA, 900, 400);
  assert.equal(info.ended, true);
  info = nowInfo('decision', runB, 1.2, 600);
  assert.equal(info.pos, 1);
  info = nowInfo('decision', runB, 2.5, 1000);
  assert.deepEqual([info.pos, info.ended], [1, true]);
  info = nowInfo('frame', runBot, 10, 10);
  assert.deepEqual([info.pos, info.text], [-1, '没有 decisions.jsonl']);
  const late = { ...runA, model: { marks: buildMarks([dec(50, 10, 1)]) } };
  assert.equal(nowInfo('frame', late, 10, 10).text, '还没有决策');
});
