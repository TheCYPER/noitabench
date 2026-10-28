import { lastAtOrBefore } from '../format/recording.js';
import { stopText } from './text.js';

/**
 * The decision timeline: one mark per line of decisions.jsonl, and the maps
 * between game frames and decisions. Pure functions, no DOM.
 *
 * A decision line says: at game frame `frame` the player was asked; it then
 * gave `command`, which ran for `frames` frames. So decision i covers the game
 * frames [frame, frame + frames]; several decisions can share one frame
 * (commands that take no game time).
 */

/** Stop reasons, most important first: when marks share a pixel the first one in this list wins. */
export const STOP_REASONS = ['dead', 'invalid', 'interrupted', 'time_limit', 'over', 'completed', 'start'];

/** Colour and label of each stop reason (contracts.md section 15). */
export const STOP_STYLE = {
  start: { color: '#60a5fa', label: '开局' },
  completed: { color: '#4ade80', label: '完成' },
  interrupted: { color: '#fb923c', label: '被打断' },
  time_limit: { color: '#facc15', label: '满 5 秒' },
  invalid: { color: '#f87171', label: '指令无效' },
  dead: { color: '#ef4444', label: '死亡' },
  over: { color: '#a78bfa', label: '结束' },
};
export const UNKNOWN_STOP = { color: '#9ca3af', label: '其他' };

/** @param {string} reason */
export const stopStyle = (reason) => (Object.hasOwn(STOP_STYLE, reason) ? STOP_STYLE[reason] : UNKNOWN_STOP);

/**
 * Importance of a stop reason: `dead` is the highest, `start` the lowest known one, unknown reasons 0.
 * @param {string} reason
 */
export function stopRank(reason) {
  const i = STOP_REASONS.indexOf(reason);
  return i < 0 ? 0 : STOP_REASONS.length - i;
}

/**
 * `index` is the decision counter after the decision (what the budget has used so far; an `inspect` costs one
 * more, a notes-only decision nothing), `view` the number the player saw when it was asked ("Decision 12 (frame
 * ..." in the transcript): `index - cost + 1`. With every decision costing 1 they are the same.
 * @typedef {{
 *   pos:number, index:number, view:number, frame:number, frames:number, endFrame:number,
 *   stopReason:string, stopDetail:string, ok:boolean, cost:number|null,
 *   commands:string[], result:object|null, digest:string,
 *   died:boolean, briefing:boolean,
 * }} Mark
 */

/**
 * Text of one command: `walk_to(x=140)`. Accepts the checked form
 * `{name, args}` and a plain string (older recordings, text requests).
 * @param {unknown} c
 * @returns {string}
 */
export function commandText(c) {
  if (typeof c === 'string') return c;
  if (c && typeof c === 'object' && typeof c.name === 'string') {
    const args = c.args && typeof c.args === 'object' ? c.args : {};
    return `${c.name}(${Object.entries(args).map(([k, v]) => `${k}=${argText(v)}`).join(', ')})`;
  }
  return JSON.stringify(c ?? '');
}

function argText(v) {
  if (v && typeof v === 'object') {
    return `{${Object.entries(v).map(([k, x]) => `${k}: ${argText(x)}`).join(', ')}}`;
  }
  return typeof v === 'string' ? JSON.stringify(v) : String(v);
}

/**
 * Marks from the lines of decisions.jsonl (already sorted by frame).
 *
 * `extra.briefingBefore` is the set of view numbers that start a new model
 * conversation after a briefing (the first decision with that number gets the
 * flag); `extra.diedAtEnd` says the transcript ended with the player dead, so
 * the last decision is the death, in addition to a result that says `dead`.
 *
 * @param {object[]} decisions
 * @param {{briefingBefore?:Set<number>, diedAtEnd?:boolean}} [extra]
 * @returns {Mark[]}
 */
export function buildMarks(decisions, extra = {}) {
  const { briefingBefore = new Set(), diedAtEnd = false } = extra;
  const seenViews = new Set();
  return decisions.map((d, pos) => {
    const next = decisions[pos + 1];
    const prev = decisions[pos - 1];
    const frames = Number.isFinite(d.frames) ? d.frames : next ? Math.max(0, next.frame - d.frame) : 0;
    const index = Number.isInteger(d.index) ? d.index : pos + 1;
    const cost = Number.isFinite(d.cost) ? d.cost : null;
    const view = cost === null ? index : index - cost + 1;
    const startsBriefing = briefingBefore.has(view) && !seenViews.has(view);
    seenViews.add(view);
    const commands = Array.isArray(d.command) ? d.command.map(commandText) : d.command === undefined ? [] : [commandText(d.command)];
    const result = d.result && typeof d.result === 'object' ? d.result : null;
    return {
      pos,
      index,
      view,
      frame: d.frame,
      frames,
      endFrame: d.frame + frames,
      stopReason: typeof d.stop_reason === 'string' ? d.stop_reason : '',
      stopDetail: stopDetail(prev),
      ok: d.ok !== false,
      cost,
      commands,
      result,
      digest: typeof d.observation_digest === 'string' ? d.observation_digest : '',
      died: result?.reason === 'dead' || (diedAtEnd && pos === decisions.length - 1),
      briefing: startsBriefing,
    };
  });
}

/** Why the previous command stopped (the detail the player was shown with this decision). */
function stopDetail(prev) {
  const r = prev?.result;
  if (!r) return '';
  return String(r.detail ?? r.code ?? '');
}

/**
 * One-line label of a mark: `#12  f840  completed (reached)` (the number is the one the player saw).
 * @param {Mark} m
 */
export function markLabel(m) {
  const stop = m.stopReason ? stopText(m) : '';
  return `#${m.view}  f${m.frame}${stop ? `  ${stop}` : ''}${m.died ? '  死亡' : ''}`;
}

/**
 * The decision that is current at game frame `time`. This is the last mark
 * whose frame is not after `time`. When several marks share a frame the last
 * of them wins, except that a mark the user just picked (`hold`) is kept
 * while the clock still stands exactly on its frame, so choosing the first of
 * two same-frame decisions does not jump to the second one at once.
 *
 * @param {Mark[]} marks
 * @param {number} time  game frame (may be fractional)
 * @param {number} [hold]  position of the current selection, -1 for none
 * @returns {number}  position, or -1 before the first decision
 */
export function markAtFrame(marks, time, hold = -1) {
  if (hold >= 0 && hold < marks.length && marks[hold].frame === time) return hold;
  return lastAtOrBefore(marks, time);
}

/**
 * Game frame at decision position `t` (a float: 2.5 = halfway through the
 * frames of the third decision). Past the last decision the run's end.
 *
 * @param {Mark[]} marks
 * @param {number} t
 * @param {number} fallback  frame to use when there are no marks
 * @returns {number}
 */
export function frameAtDecision(marks, t, fallback = 0) {
  if (marks.length === 0) return fallback;
  if (!(t > 0)) return marks[0].frame; // also NaN
  if (t >= marks.length) return marks[marks.length - 1].endFrame;
  const i = Math.floor(t);
  return marks[i].frame + (t - i) * marks[i].frames;
}

/**
 * How far through decision `pos` the clock is, 0..1 (1 when it took no game time).
 * @param {Mark} m
 * @param {number} time
 */
export function fractionIn(m, time) {
  if (m.frames <= 0) return 0;
  return Math.min(1, Math.max(0, (time - m.frame) / m.frames));
}

/**
 * Decision positions with a death mark or a briefing, for the jump keys.
 * @param {Mark[]} marks
 * @param {'died'|'briefing'} flag
 * @returns {number[]}
 */
export function flagged(marks, flag) {
  return marks.filter((m) => m[flag]).map((m) => m.pos);
}
