import { editPlace, editSwap, editTake } from './commands.js';

/**
 * The wand-edit panel as a small state machine. A click on a carried spell picks it up; a click
 * on a slot then places it there. Without a spell in hand, a click on a filled slot picks that
 * slot, and a click on another slot of the same wand swaps the two. Every finished action is
 * one `edit_wand` command (one decision, as for an agent).
 *
 * @typedef {{spell:number|null, slot:{wand:number, slot:number}|null}} EditState
 */

/** @returns {EditState} */
export const emptyEdit = () => ({ spell: null, slot: null });

/**
 * @param {EditState} st
 * @param {{kind:'spell', index:number} | {kind:'slot', wand:number, slot:number, filled:boolean}} target
 * @returns {{state:EditState, command:import('./commands.js').Command|null}}
 */
export function editClick(st, target) {
  if (target.kind === 'spell') {
    return { state: { spell: st.spell === target.index ? null : target.index, slot: null }, command: null };
  }
  if (st.spell !== null) {
    return { state: emptyEdit(), command: editPlace(target.wand, target.slot, st.spell) };
  }
  if (st.slot === null) {
    return { state: target.filled ? { spell: null, slot: { wand: target.wand, slot: target.slot } } : st, command: null };
  }
  if (st.slot.wand === target.wand && st.slot.slot === target.slot) return { state: emptyEdit(), command: null };
  if (st.slot.wand === target.wand) return { state: emptyEdit(), command: editSwap(target.wand, st.slot.slot, target.slot) };
  // another wand: start over from this slot
  return { state: target.filled ? { spell: null, slot: { wand: target.wand, slot: target.slot } } : emptyEdit(), command: null };
}

/** "Take the picked slot out" */
export function takePicked(st) {
  return st.slot ? { state: emptyEdit(), command: editTake(st.slot.wand, st.slot.slot) } : { state: st, command: null };
}
