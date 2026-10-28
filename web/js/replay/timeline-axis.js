import { lastAtOrBefore } from '../format/recording.js';
import { stopRank } from './timeline.js';

/**
 * The horizontal axis of the decision timeline, in two modes:
 *   'decision'  every decision is as wide as the next (decision i covers [i, i+1))
 *   'frame'     decision i covers its game frames [frame, frame + frames]
 * Pure functions, no DOM.
 *
 * @typedef {'decision'|'frame'} AxisMode
 */

/**
 * The stretch of the axis a mark covers.
 * @param {AxisMode} mode
 * @param {import('./timeline.js').Mark} m
 * @returns {[number, number]}
 */
export function spanOf(mode, m) {
  return mode === 'frame' ? [m.frame, m.endFrame] : [m.pos, m.pos + 1];
}

/**
 * Length of the axis that fits every lane.
 * @param {AxisMode} mode
 * @param {{marks:import('./timeline.js').Mark[], lastFrame?:number}[]} lanes
 */
export function axisLength(mode, lanes) {
  let max = 0;
  for (const lane of lanes) {
    const n = lane.marks.length;
    if (mode === 'decision') max = Math.max(max, n);
    else max = Math.max(max, lane.lastFrame ?? (n ? lane.marks[n - 1].endFrame : 0));
  }
  return max;
}

/**
 * The mark under axis position `t`, or -1 when the lane has none there.
 * @param {AxisMode} mode
 * @param {import('./timeline.js').Mark[]} marks
 * @param {number} t
 * @param {boolean} [clamp]  past the end give the last mark instead of -1
 */
export function markAtAxis(mode, marks, t, clamp = false) {
  const n = marks.length;
  if (n === 0) return -1;
  if (mode === 'decision') {
    if (t < 0) return clamp ? 0 : -1;
    if (t >= n) return clamp ? n - 1 : -1;
    return Math.floor(t);
  }
  const i = lastAtOrBefore(marks, t);
  if (i < 0) return clamp ? 0 : -1;
  if (!clamp && t > marks[n - 1].endFrame) return -1;
  return i;
}

/**
 * Which mark each pixel column of a lane shows. A column covered by several
 * marks shows the most important stop reason (dead first); on a tie the
 * earlier mark stays. A mark always gets at least one column.
 *
 * @param {AxisMode} mode
 * @param {import('./timeline.js').Mark[]} marks
 * @param {number} length  axis length
 * @param {number} width  columns
 * @returns {Int32Array}  mark position per column, -1 where nothing is
 */
export function columnsFor(mode, marks, length, width) {
  const cols = new Int32Array(width).fill(-1);
  if (length <= 0 || width <= 0) return cols;
  const rank = new Int8Array(width).fill(-1);
  for (const m of marks) {
    const [a, b] = spanOf(mode, m);
    const x0 = Math.min(width - 1, Math.floor((a / length) * width));
    const x1 = Math.min(width, Math.max(x0 + 1, Math.ceil((b / length) * width)));
    const r = stopRank(m.stopReason) + (m.died ? 20 : 0);
    for (let x = x0; x < x1; x++) {
      if (r > rank[x]) { rank[x] = r; cols[x] = m.pos; }
    }
  }
  return cols;
}

/**
 * The column a mark's flag (death, briefing) is drawn in.
 * @param {AxisMode} mode
 * @param {import('./timeline.js').Mark} m
 * @param {number} length
 * @param {number} width
 */
export function columnOf(mode, m, length, width) {
  if (length <= 0) return 0;
  return Math.min(width - 1, Math.floor((spanOf(mode, m)[0] / length) * width));
}
