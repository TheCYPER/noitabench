import test from 'node:test';
import assert from 'node:assert/strict';
import { editClick, emptyEdit, takePicked } from '../js/play/edit-state.js';
import { formatCommand } from '../js/play/commands.js';

const slot = (wand, s, filled) => ({ kind: 'slot', wand, slot: s, filled });
const spell = (index) => ({ kind: 'spell', index });

test('a carried spell, then a slot: place it', () => {
  let r = editClick(emptyEdit(), spell(2));
  assert.equal(r.command, null);
  assert.equal(r.state.spell, 2);
  r = editClick(r.state, slot(0, 1, false));
  assert.equal(formatCommand(r.command), 'edit_wand(op=place, wand=0, slot=1, spell=2)');
  assert.deepEqual(r.state, emptyEdit());
});

test('clicking the same carried spell again lets go of it', () => {
  const r = editClick(editClick(emptyEdit(), spell(1)).state, spell(1));
  assert.deepEqual(r.state, emptyEdit());
});

test('two slots of one wand: swap', () => {
  let r = editClick(emptyEdit(), slot(1, 0, true));
  assert.deepEqual(r.state.slot, { wand: 1, slot: 0 });
  assert.equal(r.command, null);
  r = editClick(r.state, slot(1, 2, false));
  assert.equal(formatCommand(r.command), 'edit_wand(op=swap, wand=1, a=0, b=2)');
  assert.deepEqual(r.state, emptyEdit());
});

test('an empty slot alone selects nothing; the same slot twice cancels', () => {
  assert.deepEqual(editClick(emptyEdit(), slot(0, 0, false)).state, emptyEdit());
  let r = editClick(emptyEdit(), slot(0, 0, true));
  r = editClick(r.state, slot(0, 0, true));
  assert.deepEqual(r.state, emptyEdit());
  assert.equal(r.command, null);
});

test('a slot of another wand starts over instead of swapping across wands', () => {
  let r = editClick(emptyEdit(), slot(0, 0, true));
  r = editClick(r.state, slot(1, 1, true));
  assert.equal(r.command, null);
  assert.deepEqual(r.state.slot, { wand: 1, slot: 1 });
});

test('taking out the picked slot', () => {
  const picked = editClick(emptyEdit(), slot(0, 3, true)).state;
  const r = takePicked(picked);
  assert.equal(formatCommand(r.command), 'edit_wand(op=take, wand=0, slot=3)');
  assert.deepEqual(r.state, emptyEdit());
  assert.equal(takePicked(emptyEdit()).command, null);
});
