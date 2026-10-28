import { axisLength, columnOf, columnsFor, markAtAxis } from './timeline-axis.js';
import { stopStyle } from './timeline.js';

const LANE_H = 18;
const LANE_GAP = 4;
const TOP = 9;
const BG = '#0b0907';
const LANE_BG = '#2a221b';
const ACCENT = '#e2a23a';

/**
 * Draws the decision timeline on a canvas: one lane per run, one coloured
 * mark per decision (colour = stop reason), a red post at a death, a triangle
 * at a new briefing, the selected decision outlined and a playhead.
 * Clicking or dragging asks the page to seek; the page owns all state.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {{
 *   onSeek: (hit:{lane:number,pos:number,t:number}) => void,
 *   onHover?: (hit:{lane:number,pos:number}|null) => void,
 *   onKey?: (dir:-1|1) => void,
 * }} cb
 */
export function createTimeline(canvas, cb) {
  const state = {
    lanes: /** @type {{marks:import('./timeline.js').Mark[], lastFrame?:number}[]} */ ([]),
    mode: /** @type {import('./timeline-axis.js').AxisMode} */ ('decision'),
    selected: /** @type {({lane:number,pos:number})|null} */ (null),
    playhead: /** @type {number|null} */ (null),
    columns: /** @type {Int32Array[]} */ ([]),
    width: 0,
  };
  const ctx = canvas.getContext('2d');
  let dragging = false;
  let raf = 0;

  const length = () => axisLength(state.mode, state.lanes);
  const heightFor = (n) => TOP + Math.max(1, n) * (LANE_H + LANE_GAP);
  const laneTop = (i) => TOP + i * (LANE_H + LANE_GAP);

  function layout() {
    const dpr = window.devicePixelRatio || 1;
    const cssW = Math.max(1, Math.floor(canvas.clientWidth));
    const cssH = heightFor(state.lanes.length);
    canvas.style.height = `${cssH}px`;
    if (canvas.width !== Math.round(cssW * dpr) || canvas.height !== Math.round(cssH * dpr)) {
      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
    }
    const changed = state.width !== cssW;
    state.width = cssW;
    return { dpr, cssW, cssH, changed };
  }

  function draw() {
    raf = 0;
    const { dpr, cssW, cssH } = layout();
    const len = length();
    if (state.columns.length !== state.lanes.length || state.columns.some((c) => c.length !== cssW)) {
      state.columns = state.lanes.map((l) => columnsFor(state.mode, l.marks, len, cssW));
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, cssW, cssH);
    state.lanes.forEach((lane, i) => drawLane(lane, i, len, cssW));
    if (state.playhead !== null && len > 0) {
      const x = Math.round((Math.min(state.playhead, len) / len) * cssW) + 0.5;
      ctx.fillStyle = ACCENT;
      ctx.fillRect(Math.min(cssW - 2, Math.max(0, x - 1)), 0, 2, cssH);
    }
  }

  function drawLane(lane, i, len, cssW) {
    const y = laneTop(i);
    ctx.fillStyle = LANE_BG;
    ctx.fillRect(0, y, cssW, LANE_H);
    const cols = state.columns[i];
    let x = 0;
    while (x < cssW) {
      const pos = cols[x];
      let end = x + 1;
      while (end < cssW && cols[end] === pos) end++;
      if (pos >= 0) {
        ctx.fillStyle = stopStyle(lane.marks[pos].stopReason).color;
        ctx.fillRect(x, y + 2, end - x, LANE_H - 4);
      }
      x = end;
    }
    for (const m of lane.marks) {
      if (m.died) flagDeath(columnOf(state.mode, m, len, cssW), y);
      if (m.briefing) flagBriefing(columnOf(state.mode, m, len, cssW), y);
    }
    if (state.selected?.lane === i) outline(lane.marks[state.selected.pos], y, len, cssW);
  }

  function flagDeath(x, y) {
    ctx.fillStyle = '#fff';
    ctx.fillRect(x - 1, y - 1, 3, LANE_H + 2);
    ctx.fillStyle = '#7f1d1d';
    ctx.fillRect(x, y, 1, LANE_H);
  }

  function flagBriefing(x, y) {
    ctx.fillStyle = ACCENT;
    ctx.beginPath();
    ctx.moveTo(x - 4, y - TOP + 1);
    ctx.lineTo(x + 4, y - TOP + 1);
    ctx.lineTo(x, y - 1);
    ctx.closePath();
    ctx.fill();
  }

  function outline(m, y, len, cssW) {
    if (!m || len <= 0) return;
    const x = columnOf(state.mode, m, len, cssW);
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x - 1.5, y + 0.5, 4, LANE_H - 1);
  }

  const request = () => { if (!raf) raf = requestAnimationFrame(draw); };

  function hit(e) {
    const r = canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const len = length();
    const t = Math.min(len, Math.max(0, (x / Math.max(1, r.width)) * len));
    const lane = Math.min(state.lanes.length - 1, Math.max(0, Math.floor((y - TOP) / (LANE_H + LANE_GAP))));
    const marks = state.lanes[lane]?.marks ?? [];
    const pos = markAtAxis(state.mode, marks, t, dragging);
    return { lane, pos, t };
  }

  canvas.addEventListener('pointerdown', (e) => {
    if (state.lanes.length === 0) return;
    dragging = true;
    canvas.setPointerCapture(e.pointerId);
    canvas.focus();
    const hh = hit(e);
    if (hh.pos >= 0) cb.onSeek(hh);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (state.lanes.length === 0) return;
    const hh = hit(e);
    if (dragging && hh.pos >= 0) cb.onSeek(hh);
    else if (!dragging) cb.onHover?.(hh.pos >= 0 ? hh : null);
  });
  const stop = () => { dragging = false; };
  canvas.addEventListener('pointerup', stop);
  canvas.addEventListener('pointercancel', stop);
  canvas.addEventListener('pointerleave', () => { if (!dragging) cb.onHover?.(null); });
  canvas.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      e.stopPropagation();
      cb.onKey?.(e.key === 'ArrowLeft' ? -1 : 1);
    }
  });
  new ResizeObserver(request).observe(canvas);

  return {
    /** @param {{marks:import('./timeline.js').Mark[], lastFrame?:number}[]} lanes */
    setLanes(lanes) { state.lanes = lanes; state.columns = []; state.selected = null; state.playhead = null; request(); },
    /** @param {import('./timeline-axis.js').AxisMode} mode */
    setMode(mode) { state.mode = mode; state.columns = []; request(); },
    /** @param {{lane:number,pos:number}|null} sel */
    setSelected(sel) { state.selected = sel; request(); },
    /** @param {number|null} t  axis position */
    setPlayhead(t) { state.playhead = t; request(); },
    redraw: request,
    get mode() { return state.mode; },
  };
}
