import { FRAMES_PER_SECOND } from '../replay/clock.js';
import { axisLength } from '../replay/timeline-axis.js';
import { frameAtDecision, markAtFrame, markLabel } from '../replay/timeline.js';

/**
 * How the compare page keeps several runs in step. One shared position `t`
 * runs along an axis; each run turns it into its own game frame.
 *
 *   'frame'     t is a game frame: every run shows the same moment of game time
 *   'decision'  t is a decision position (2.5 = halfway through the frames of
 *               the third decision): every run shows the same decision number
 *
 * Pure functions, no DOM.
 *
 * @typedef {'frame'|'decision'} AxisMode
 * @typedef {{firstFrame:number, lastFrame:number, model:{marks:import('../replay/timeline.js').Mark[]}, meta?:{frameStride:number}}} CompareRun
 */

/** Decisions per second of wall time at speed 1× in decision mode. */
export const DECISIONS_PER_SECOND = 2;

/**
 * Axis units that pass per second of wall time at speed 1×.
 * @param {AxisMode} mode
 */
export const rateOf = (mode) => (mode === 'frame' ? FRAMES_PER_SECOND : DECISIONS_PER_SECOND);

/**
 * Decision mode needs decisions in every run.
 * @param {CompareRun[]} runs
 */
export const canCompareByDecision = (runs) => runs.length > 0 && runs.every((r) => r.model.marks.length > 0);

/**
 * The mode to use: the wanted one, or frame mode when decision mode is impossible.
 * @param {AxisMode} wanted
 * @param {CompareRun[]} runs
 * @returns {AxisMode}
 */
export const effectiveMode = (wanted, runs) => (wanted === 'decision' && canCompareByDecision(runs) ? 'decision' : 'frame');

/**
 * Length of the shared axis (the longest run).
 * @param {AxisMode} mode
 * @param {CompareRun[]} runs
 */
export function axisEnd(mode, runs) {
  return axisLength(mode === 'frame' ? 'frame' : 'decision', runs.map((r) => ({ marks: r.model.marks, lastFrame: r.lastFrame })));
}

/**
 * The game frame run `run` shows at shared position `t`. A run that is over
 * stays on its last frame.
 * @param {AxisMode} mode
 * @param {CompareRun} run
 * @param {number} t
 */
export function frameForAxis(mode, run, t) {
  const raw = mode === 'frame' ? t : frameAtDecision(run.model.marks, t, run.firstFrame);
  return Math.min(run.lastFrame, Math.max(run.firstFrame, raw));
}

/**
 * How far one "step" button moves the shared position: one recorded step in
 * frame mode (the coarsest stride among the runs), one decision otherwise.
 * @param {AxisMode} mode
 * @param {CompareRun[]} runs
 */
export function axisStep(mode, runs) {
  if (mode === 'decision') return 1;
  return Math.max(1, ...runs.map((r) => r.meta?.frameStride ?? 1));
}

/**
 * What a pane says about its run at shared position `t` (which is game frame
 * `frame` for this run): the current decision, and whether the run is over.
 * In decision mode the decision is the one `t` falls in; in frame mode the
 * last one asked at or before `frame`.
 *
 * @param {AxisMode} mode
 * @param {CompareRun} run
 * @param {number} t
 * @param {number} frame  frameForAxis(mode, run, t)
 * @returns {{pos:number, text:string, ended:boolean}}
 */
export function nowInfo(mode, run, t, frame) {
  const marks = run.model.marks;
  const n = marks.length;
  if (n === 0) return { pos: -1, text: '没有 decisions.jsonl', ended: frame >= run.lastFrame };
  const pos = mode === 'decision' ? Math.min(n - 1, Math.max(0, Math.floor(t))) : markAtFrame(marks, frame);
  const ended = mode === 'decision' ? t >= n : frame >= run.lastFrame;
  if (pos < 0) return { pos, text: '还没有决策', ended };
  const m = marks[pos];
  return { pos, text: `${markLabel(m)}${m.commands.length ? `  ${m.commands.join('; ')}` : ''}`, ended };
}
