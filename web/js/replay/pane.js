import { materialLabel } from '../format/materials.js';
import { lastAtOrBefore } from '../format/recording.js';
import { drawEntities, drawEventMarks } from '../render/overlays.js';
import { createStage } from '../ui/stage.js';
import { eventsInWindow, stepForTime } from './clock.js';
import { followZoom, playerAt, playerTrack } from './follow.js';
import { createSync } from './sync.js';

/** Event rings stay visible this many game frames. */
const EVENT_WINDOW = 45;
/** A busy frame can log thousands of events; only the newest get a ring. */
const MAX_EVENT_MARKS = 400;
/** A drag shorter than this many CSS pixels is a click, not a pan. */
const DRAG_PIXELS = 4;

/**
 * One run on one canvas: the renderer, the camera, the overlays and the
 * seek-by-seek frame sync. The replay page has one pane, the compare page up
 * to four. The pane draws; the page owns the clock and says which game frame
 * to show with `show(frame)`.
 *
 * @param {{
 *   canvas: HTMLCanvasElement, table: import('../format/materials.js').MaterialTable,
 *   zoomOut: HTMLElement, zoomIn: HTMLElement, zoomFit: HTMLElement, zoomLabel: HTMLElement, readout: HTMLElement,
 *   isPlaying: () => boolean,
 *   onShown?: (pane:any) => void, onError?: (pane:any, err:unknown) => void,
 *   onRecovered?: (pane:any) => void, onSettled?: (pane:any) => void, onFollowOff?: (pane:any) => void,
 * }} o
 */
export function createPane(o) {
  const pane = {
    run: /** @type {import('./run.js').Run|null} */ (null),
    sync: /** @type {ReturnType<typeof createSync>|null} */ (null),
    track: /** @type {ReturnType<typeof playerTrack>} */ ([]),
    failed: false,
    opts: { entities: true, events: true, follow: true },
    /** While true the zoom is the one followZoom picks for the canvas width; a zoom the user chose switches it off. */
    auto: true,
    autoZoom: 0,
    stage: null,
    /** Frame of the picture on screen, or null before the first one. */
    get shownFrame() {
      const { run, sync } = pane;
      return run && sync && sync.shown >= 0 ? run.store.index.steps[sync.shown].frame : null;
    },
    get busy() { return pane.sync?.busy ?? false; },
    load, show, repaint, setFollow, setShading,
  };

  pane.stage = createStage({
    canvas: o.canvas, table: o.table,
    zoomOut: o.zoomOut, zoomIn: o.zoomIn, zoomFit: o.zoomFit, zoomLabel: o.zoomLabel, readout: o.readout,
    overlays: () => { prepareDraw(); return overlays(pane); },
    describeCell: (c) => `(${c.x}, ${c.y})  ${materialLabel(o.table, c.material)}`,
  });
  watchDrag(o.canvas, pane, o.onFollowOff);

  /** Shows a run: grid, camera and a fresh sync (a seek still running on the previous run cannot touch this one). */
  function load(run) {
    pane.run = run;
    pane.failed = false;
    pane.track = playerTrack(run.entities);
    const { store } = run;
    const { renderer } = pane.stage;
    renderer.setGrid(store.state, store.width, store.height, store.origin);
    pane.sync = buildSync(run);
    pane.auto = true;
    pane.autoZoom = 0;
    if (!(pane.opts.follow && pane.track.length)) pane.stage.fit();
    pane.stage.requestDraw();
  }

  /**
   * Runs at the start of every draw, when the canvas size is final: with follow
   * on the zoom fits the canvas (until the user zooms) and the camera sits on
   * the player. A pane resizes when the compare page adds another run.
   */
  function prepareDraw() {
    if (!pane.opts.follow || pane.track.length === 0) return;
    const { view } = pane.stage.renderer;
    if (pane.auto && pane.autoZoom !== 0 && view.zoom !== pane.autoZoom) pane.auto = false;
    if (pane.auto) {
      const z = followZoom(view.cssW);
      if (view.zoom !== z) view.zoomTo(z);
      pane.autoZoom = z;
    }
    const frame = pane.shownFrame;
    const p = frame === null ? null : playerAt(pane.track, frame);
    if (p) view.centerOn(p.x, p.y);
  }

  function buildSync(run) {
    const sync = createSync(run.store, {
      onShown: () => {
        if (pane.sync !== sync) return;
        if (pane.failed) { pane.failed = false; o.onRecovered?.(pane); }
        repaint();
        if (o.isPlaying()) run.store.prefetch(sync.shown + 1, 3);
        o.onShown?.(pane);
      },
      onError: (err) => {
        if (pane.sync !== sync) return;
        pane.failed = true;
        repaint(); // the store reset itself: show the blank picture, not a stale one
        o.onError?.(pane, err);
      },
      onSettled: () => { if (pane.sync === sync) o.onSettled?.(pane); },
    });
    return sync;
  }

  /** Redraws the new picture (the camera moves in `prepareDraw`). */
  function repaint() {
    pane.stage.renderer.markDirty();
    pane.stage.drawNow();
  }

  /**
   * Asks for the picture of game frame `frame`.
   * @param {number} frame
   * @returns {boolean} true while a seek is running
   */
  function show(frame) {
    const { run, sync } = pane;
    if (!run || !sync) return false;
    return sync.pump(stepForTime(run.store.index.steps, frame));
  }

  function setFollow(on) {
    pane.opts.follow = on;
    pane.auto = on;
    pane.autoZoom = 0;
    pane.stage.requestDraw();
  }

  function setShading(on) {
    pane.stage.renderer.setShading(on);
    pane.stage.requestDraw();
  }

  return pane;
}

/** Dragging the picture means the user wants to look elsewhere: follow turns itself off. */
function watchDrag(canvas, pane, onFollowOff) {
  let start = null;
  canvas.addEventListener('pointerdown', (e) => { start = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener('pointerup', () => { start = null; });
  canvas.addEventListener('pointercancel', () => { start = null; });
  canvas.addEventListener('pointermove', (e) => {
    if (!start || !pane.opts.follow || !(e.buttons & 1)) return;
    if (Math.hypot(e.clientX - start.x, e.clientY - start.y) < DRAG_PIXELS) return;
    pane.opts.follow = false;
    start = null;
    onFollowOff?.(pane);
  });
}

function overlays(pane) {
  const { run, sync, opts } = pane;
  if (!run || !sync || sync.shown < 0) return [];
  const frame = run.store.index.steps[sync.shown].frame;
  const out = [];
  if (opts.entities) {
    const i = lastAtOrBefore(run.entities, frame);
    if (i >= 0) out.push((ctx, view) => drawEntities(ctx, view, run.entities[i].entities));
  }
  if (opts.events) {
    const evs = eventsInWindow(run.events, frame, EVENT_WINDOW).slice(-MAX_EVENT_MARKS);
    out.push((ctx, view) => drawEventMarks(ctx, view, evs, frame, EVENT_WINDOW));
  }
  return out;
}
