import test from 'node:test';
import assert from 'node:assert/strict';
import { commandsForClick } from '../js/play/clicks.js';
import { formatDecision } from '../js/play/commands.js';

const ctx = { stepTicks: 2 };
const text = (ev, hit) => formatDecision(commandsForClick(ev, hit, ctx));
const enemy = { id: 7, kind: 'longleg', x: 100, y: 60, w: 10, h: 12, hostile: true };
const bottle = { id: 3, kind: 'bottle', x: 40, y: 70, w: 4, h: 6 };

test('left click on the ground walks to that column', () => {
  assert.equal(text({ button: 0 }, { x: 180, y: 50, entity: null }), 'walk_to(x=180)');
});

test('left click on a creature aims at it and fires until it is dead', () => {
  assert.equal(text({ button: 0 }, { x: 103, y: 65, entity: enemy }), 'aim(target=7); fire(target_dead=true)');
});

test('left click on an item walks to its middle', () => {
  assert.equal(text({ button: 0 }, { x: 41, y: 72, entity: bottle }), 'walk_to(x=42)');
});

test('Shift + left click aims at the point and fires one step', () => {
  assert.equal(text({ button: 0, shiftKey: true }, { x: 60, y: 90, entity: null }), 'aim(x=60, y=90); fire(ticks=2)');
});

test('right click looks closely at the creature, the item or the cell', () => {
  assert.equal(text({ button: 2 }, { x: 103, y: 65, entity: enemy }), 'inspect(entity=7)');
  assert.equal(text({ button: 2 }, { x: 5, y: 6, entity: null }), 'inspect(x=5, y=6)');
});

test('other buttons do nothing', () => {
  assert.equal(commandsForClick({ button: 1 }, { x: 1, y: 1, entity: null }, ctx), null);
});
