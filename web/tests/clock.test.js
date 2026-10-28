import test from 'node:test';
import assert from 'node:assert/strict';
import { advance, createPlayback, eventsInWindow, seekToStep, stepForTime } from '../js/replay/clock.js';

const steps = [0, 2, 4, 10, 12].map((frame) => ({ frame }));

test('stepForTime picks the last step at or before the time', () => {
  assert.equal(stepForTime(steps, -3), 0);
  assert.equal(stepForTime(steps, 0), 0);
  assert.equal(stepForTime(steps, 3.9), 1);
  assert.equal(stepForTime(steps, 4), 2);
  assert.equal(stepForTime(steps, 9), 2);
  assert.equal(stepForTime(steps, 999), 4);
});

test('advance moves 60 game frames per second at 1x and scales with speed', () => {
  const pb = createPlayback();
  pb.playing = true;
  advance(pb, 500, 1000);
  assert.equal(pb.time, 30);
  pb.speed = 8;
  advance(pb, 250, 1000);
  assert.equal(pb.time, 30 + 120);
  pb.speed = 0.25;
  advance(pb, 1000, 1000);
  assert.equal(pb.time, 30 + 120 + 15);
});

test('advance does nothing while paused and stops at the last frame', () => {
  const pb = createPlayback();
  advance(pb, 1000, 100);
  assert.equal(pb.time, 0);
  pb.playing = true;
  pb.speed = 8;
  advance(pb, 10_000, 100);
  assert.deepEqual([pb.time, pb.playing], [100, false]);
});

test('seekToStep clamps and moves the clock', () => {
  const pb = createPlayback();
  assert.equal(seekToStep(pb, steps, 3), 3);
  assert.equal(pb.time, 10);
  assert.equal(seekToStep(pb, steps, 99), 4);
  assert.equal(seekToStep(pb, steps, -1), 0);
  assert.equal(pb.time, 0);
});

test('eventsInWindow returns the events in (frame - window, frame]', () => {
  const ev = [3, 5, 5, 9, 20].map((frame, i) => ({ frame, i }));
  const ids = (frame, window) => eventsInWindow(ev, frame, window).map((e) => e.i);
  assert.deepEqual(ids(9, 5), [1, 2, 3]);      // (4, 9] holds frames 5, 5, 9
  assert.deepEqual(ids(9, 4), [3]);            // (5, 9]: frame 5 is excluded, the window is open at the low end
  assert.deepEqual(ids(2, 10), []);            // nothing has happened yet
  assert.deepEqual(ids(100, 10), []);          // (90, 100] is empty
  assert.deepEqual(ids(20, 100), [0, 1, 2, 3, 4]);
});
