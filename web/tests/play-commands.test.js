import test from 'node:test';
import assert from 'node:assert/strict';
import {
  aimPoint, aimTarget, cmd, dropBottle, editPlace, editSwap, editTake, fire, formatCommand, formatDecision,
  formatValue, inspectCell, inspectEntity, inspectWand, move, pickup, walkTo,
} from '../js/play/commands.js';

test('commands are {name, args} and leave out arguments that are not given', () => {
  assert.deepEqual(move('left', undefined), { name: 'move', args: { direction: 'left' } });
  assert.deepEqual(pickup(), { name: 'pickup', args: {} });
  assert.deepEqual(pickup(12), { name: 'pickup', args: { item: 12 } });
  assert.deepEqual(inspectWand(0), { name: 'inspect', args: { wand: 0 } });
  assert.deepEqual(inspectWand(0, 2), { name: 'inspect', args: { wand: 0, slot: 2 } });
  assert.deepEqual(cmd('kick'), { name: 'kick', args: {} });
});

test('until conditions go beside the arguments, the way the server reads them', () => {
  assert.deepEqual(fire({ ticks: 3 }), { name: 'fire', args: { ticks: 3 } });
  assert.deepEqual(fire({ target_dead: true }), { name: 'fire', args: { target_dead: true } });
  assert.deepEqual(fire(), { name: 'fire', args: {} });
});

test('text form: the line a player could type', () => {
  assert.equal(formatCommand(move('left', 2)), 'move(direction=left, ticks=2)');
  assert.equal(formatCommand(walkTo(180)), 'walk_to(x=180)');
  assert.equal(formatCommand(aimTarget(4)), 'aim(target=4)');
  assert.equal(formatCommand(aimPoint(10, -3)), 'aim(x=10, y=-3)');
  assert.equal(formatCommand(inspectCell(5, 6)), 'inspect(x=5, y=6)');
  assert.equal(formatCommand(inspectEntity(9)), 'inspect(entity=9)');
  assert.equal(formatCommand(dropBottle(1)), 'drop(bottle=1)');
  assert.equal(formatCommand(editPlace(0, 1, 2)), 'edit_wand(op=place, wand=0, slot=1, spell=2)');
  assert.equal(formatCommand(editTake(0, 1)), 'edit_wand(op=take, wand=0, slot=1)');
  assert.equal(formatCommand(editSwap(1, 0, 2)), 'edit_wand(op=swap, wand=1, a=0, b=2)');
  assert.equal(formatDecision([walkTo(3), fire({ target_dead: true })]), 'walk_to(x=3); fire(target_dead=true)');
});

test('values: words bare, other text quoted, objects as JSON', () => {
  assert.equal(formatValue('right'), 'right');
  assert.equal(formatValue('chem.md'), '"chem.md"');
  assert.equal(formatValue('a b'), '"a b"');
  assert.equal(formatValue(true), 'true');
  assert.equal(formatValue(-4), '-4');
  assert.equal(formatValue({ ticks: 2 }), '{"ticks":2}');
});
