import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BINDINGS, Gestures, LONG_TICKS, MAX_FLY_TICKS, TAP_MS, TICK_MS, commandsForKey, holdTicks, isGameKey,
} from '../js/play/keymap.js';
import { formatDecision } from '../js/play/commands.js';

const ctx = { stepTicks: 1, wandCount: 2, activeBottle: 0, activeWand: 0 };
const key = (k, extra = {}) => commandsForKey({ key: k, ...extra }, ctx);
const text = (k, extra, c = ctx) => formatDecision(commandsForKey({ key: k, ...extra }, c));

test('arrow keys and A/D walk one step; Shift walks as far as a command may', () => {
  assert.equal(text('ArrowLeft'), 'move(direction=left, ticks=1)');
  assert.equal(text('d'), 'move(direction=right, ticks=1)');
  assert.equal(text('D', { shiftKey: true }), `move(direction=right, ticks=${LONG_TICKS})`);
  assert.equal(text('ArrowRight', {}, { stepTicks: 5 }), 'move(direction=right, ticks=5)');
});

test('jumping to a side, waiting and firing', () => {
  assert.equal(text('q'), 'jump(direction=left)');
  assert.equal(text('e'), 'jump(direction=right)');
  assert.equal(text('s', {}, { stepTicks: 3 }), 'wait(ticks=3)');
  assert.equal(text(' '), 'fire(ticks=1)');
  assert.equal(text(' ', { shiftKey: true }), `fire(ticks=${LONG_TICKS})`);
});

test('W and Up are decided when they are let go, R is gone', () => {
  assert.equal(key('w'), null, 'the press alone sends nothing');
  assert.equal(key('ArrowUp'), null);
  assert.equal(key('r'), null, 'levitation is the hold of W now');
  assert.ok(!BINDINGS.some((b) => b.keys.includes('r')));
  const lift = BINDINGS.find((b) => b.keys.includes('w'));
  assert.deepEqual(lift.keys, ['ArrowUp', 'w']);
  assert.ok(lift.hold && /按住/.test(lift.text) && /轻点/.test(lift.text));
  assert.ok(isGameKey({ key: 'w' }) && isGameKey({ key: 'ArrowUp' }), 'the page must not scroll');
});

test('kick, pickup and the bottle keys use the chosen bottle', () => {
  assert.equal(text('k'), 'kick()');
  assert.equal(text('f'), 'pickup()');
  assert.equal(text('b'), 'drink()');
  assert.equal(text('b', {}, { stepTicks: 1, bottle: 2 }), 'drink(bottle=2)');
  assert.equal(text('p', {}, { stepTicks: 1, bottle: 0 }), 'pour(bottle=0)');
  assert.equal(text('l', {}, { stepTicks: 1, bottle: 1 }), 'fill(bottle=1)');
  assert.equal(text('t', {}, { stepTicks: 1, bottle: 1 }), 'throw(bottle=1)');
});

test('drop: the chosen bottle or the one in hand; Shift drops the wand in hand; nothing to drop means no decision', () => {
  const full = { stepTicks: 1, activeBottle: 1, activeWand: 0 };
  assert.equal(text('x', {}, full), 'drop(bottle=1)');
  assert.equal(text('x', {}, { ...full, bottle: 2 }), 'drop(bottle=2)');
  assert.equal(text('X', { shiftKey: true }, full), 'drop(wand=0)');
  assert.equal(commandsForKey({ key: 'x' }, { stepTicks: 1 }), null);
  assert.equal(commandsForKey({ key: 'X', shiftKey: true }, { stepTicks: 1 }), null);
});

test('digits hold a wand, but only one the player has', () => {
  assert.equal(text('1'), 'swap_wand(wand=0)');
  assert.equal(text('2'), 'swap_wand(wand=1)');
  assert.equal(key('3'), null);
  assert.equal(text('9', {}, { stepTicks: 1 }), 'swap_wand(wand=8)');
});

test('a held key does not repeat, and shortcuts with Ctrl, Meta or Alt are left alone', () => {
  assert.equal(key('d', { repeat: true }), null);
  assert.equal(key('d', { ctrlKey: true }), null);
  assert.equal(key('r', { metaKey: true }), null);
  assert.equal(key('a', { altKey: true }), null);
});

test('unknown keys mean nothing', () => {
  assert.equal(key('z'), null);
  assert.equal(key('Escape'), null);
  assert.equal(key('Tab'), null);
});

test('every binding builds commands the server knows by name', () => {
  const names = new Set(['move', 'jump', 'wait', 'fly', 'fire', 'kick', 'pickup', 'drink', 'pour', 'fill', 'throw', 'drop']);
  for (const b of BINDINGS) {
    for (const k of b.keys) {
      const cmds = commandsForKey({ key: k }, ctx);
      if (b.hold) {
        assert.equal(cmds, null, k); // decided on release
        assert.ok(isGameKey({ key: k }), k);
        continue;
      }
      assert.ok(cmds && cmds.length === 1, k);
      assert.ok(names.has(cmds[0].name), `${k} -> ${cmds[0].name}`);
      assert.ok(isGameKey({ key: k }), k);
    }
    assert.ok(b.label && b.text);
  }
  assert.equal(isGameKey({ key: 'Tab' }), false);
});

test('no key is bound twice', () => {
  const seen = new Set();
  for (const b of BINDINGS) for (const k of b.keys) {
    assert.ok(!seen.has(k), k);
    seen.add(k);
  }
});

// ---------------------------------------------------------------- W: a tap jumps, a hold levitates

const kd = (k, extra = {}) => ({ key: k, ...extra });
/** Runs a list of [time, 'down'|'up', key, extra?] events through a fresh Gestures; returns the decisions. */
function play(events, c = ctx) {
  const g = new Gestures();
  const out = [];
  for (const [t, kind, k, extra] of events) {
    const cmds = kind === 'down' ? g.down(kd(k, extra), c, t) : g.up({ key: k }, t);
    if (cmds) out.push({ t, text: formatDecision(cmds) });
  }
  return out;
}

test('a tap of W or Up (under 200 ms) is one jump, sent when the key comes up', () => {
  for (const k of ['w', 'W', 'ArrowUp']) {
    assert.deepEqual(play([[0, 'down', k], [TAP_MS - 1, 'up', k]]), [{ t: TAP_MS - 1, text: 'jump(direction=up)' }], k);
  }
  assert.deepEqual(play([[0, 'down', 'w']]), [], 'nothing is sent while the key is down');
});

test('a hold of W is levitation for as long as it is held: one tick per 1/6 s, 1 to 30', () => {
  assert.equal(TICK_MS, 1000 / 6);
  assert.equal(holdTicks(TAP_MS), 1);
  assert.equal(holdTicks(1000), 6);
  assert.equal(holdTicks(2500), 15);
  assert.equal(holdTicks(5000), MAX_FLY_TICKS);
  assert.equal(holdTicks(60_000), MAX_FLY_TICKS, 'a decision lasts at most 300 frames');
  assert.equal(holdTicks(0), 1);
  assert.deepEqual(play([[100, 'down', 'w'], [100 + TAP_MS, 'up', 'w']]).map((d) => d.text), ['fly(direction=up, ticks=1)'], '200 ms is a hold');
  assert.deepEqual(play([[0, 'down', 'ArrowUp'], [1000, 'up', 'ArrowUp']]).map((d) => d.text), ['fly(direction=up, ticks=6)']);
  assert.deepEqual(play([[0, 'down', 'w'], [9000, 'up', 'w']]).map((d) => d.text), ['fly(direction=up, ticks=30)']);
});

test('A/D (or Left/Right) held with a tap jump to that side; held with a hold they steer the flight', () => {
  assert.deepEqual(
    play([[0, 'down', 'd'], [50, 'down', 'w'], [120, 'up', 'w'], [150, 'up', 'd']]).map((d) => d.text),
    ['move(direction=right, ticks=1)', 'jump(direction=right)'],
    'the step of D was already a decision; the jump goes the same way',
  );
  assert.deepEqual(
    play([[0, 'down', 'ArrowLeft'], [10, 'down', 'ArrowUp'], [1010, 'up', 'ArrowUp']]).map((d) => d.text),
    ['move(direction=left, ticks=1)', 'fly(direction=left, ticks=6)'],
  );
});

test('A/D pressed while W is down only steer: no step of their own, one decision in all', () => {
  const tap = play([[0, 'down', 'w'], [40, 'down', 'a'], [90, 'up', 'w'], [100, 'up', 'a']]);
  assert.deepEqual(tap.map((d) => d.text), ['jump(direction=left)']);
  const hold = play([[0, 'down', 'w'], [300, 'down', 'ArrowRight'], [1500, 'up', 'w'], [1520, 'up', 'ArrowRight']]);
  assert.deepEqual(hold.map((d) => d.text), ['fly(direction=right, ticks=9)']);
  const letGoFirst = play([[0, 'down', 'w'], [300, 'down', 'd'], [400, 'up', 'd'], [1000, 'up', 'w']]);
  assert.deepEqual(letGoFirst.map((d) => d.text), ['fly(direction=right, ticks=6)'], 'the side chosen last counts');
  const changed = play([[0, 'down', 'd'], [10, 'down', 'w'], [20, 'down', 'a'], [500, 'up', 'w']]);
  assert.deepEqual(changed.map((d) => d.text), ['move(direction=right, ticks=1)', 'fly(direction=left, ticks=3)']);
});

test('key auto-repeat never makes an extra decision or stretches the hold', () => {
  const events = [[0, 'down', 'w']];
  for (let t = 500; t <= 900; t += 33) events.push([t, 'down', 'w', { repeat: true }]);
  events.push([1000, 'up', 'w']);
  assert.deepEqual(play(events).map((d) => d.text), ['fly(direction=up, ticks=6)'], 'timed from the first press');
  const walking = play([[0, 'down', 'd'], [500, 'down', 'd', { repeat: true }], [600, 'down', 'd', { repeat: true }], [700, 'up', 'd']]);
  assert.equal(walking.length, 1);
  const g = new Gestures();
  assert.equal(g.down(kd('w', { repeat: true }), ctx, 0), null, 'a repeat without a press starts nothing');
  assert.equal(g.up({ key: 'w' }, 100), null);
});

test('a release without a press, other keys and shortcuts are left alone', () => {
  assert.deepEqual(play([[0, 'up', 'w']]), []);
  assert.deepEqual(play([[0, 'down', 'w', { ctrlKey: true }], [50, 'up', 'w']]), [], 'Ctrl+W is the browser\'s');
  assert.deepEqual(play([[0, 'down', 'w', { metaKey: true }], [50, 'up', 'w']]), []);
  assert.deepEqual(play([[0, 'down', 'k']]).map((d) => d.text), ['kick()'], 'ordinary keys are decided on the press');
  assert.deepEqual(play([[0, 'down', 'w'], [10, 'down', 'k'], [60, 'up', 'w']]).map((d) => d.text), ['kick()', 'jump(direction=up)']);
});

test('two gestures in a row do not leak into each other, and a lost focus drops one', () => {
  const g = new Gestures();
  assert.equal(g.down(kd('d'), ctx, 0).length, 1);
  g.up({ key: 'd' }, 10);
  g.down(kd('w'), ctx, 20);
  assert.equal(formatDecision(g.up({ key: 'w' }, 60)), 'jump(direction=up)', 'D was let go before W');
  g.down(kd('w'), ctx, 100);
  g.down(kd('a'), ctx, 120);
  g.reset();
  assert.equal(g.up({ key: 'w' }, 900), null, 'the release after a blur is nothing');
  assert.equal(g.side(), null);
  g.down(kd('w'), ctx, 1000);
  assert.equal(formatDecision(g.up({ key: 'w' }, 1050)), 'jump(direction=up)', 'and the next press is fresh');
});
