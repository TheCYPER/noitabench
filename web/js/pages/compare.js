import { axisEnd, axisStep, canCompareByDecision, effectiveMode, frameForAxis, nowInfo, rateOf } from '../compare/axis.js';
import { buildPaneView, showNow } from '../compare/pane-view.js';
import { SPEEDS, createPlayback } from '../replay/clock.js';
import { renderDecision } from '../replay/decision-panel.js';
import { fillLegend } from '../replay/legend.js';
import { detailFor } from '../replay/model.js';
import { createPane } from '../replay/pane.js';
import { loadRun } from '../replay/run.js';
import { createTimeline } from '../replay/timeline-canvas.js';
import { markLabel } from '../replay/timeline.js';
import { FileSet } from '../ui/file-set.js';
import { $, clear, describeError, h, showMessage } from '../ui/dom.js';
import { shortcutAllowed } from '../ui/keys.js';
import { loadMaterials } from '../ui/load-materials.js';
import { wireOpeners } from '../ui/open-files.js';
import { sameOriginUrl } from '../ui/same-origin.js';

const MAX_RUNS = 4;
/** A long gap between two animation frames (hidden tab) must not skip the runs. */
const MAX_TICK_MS = 250;
const RUN_FILES = [
  'meta.json', 'frames.bin', 'entities.jsonl', 'events.jsonl', 'decisions.jsonl',
  'transcript.jsonl', 'harness.jsonl', 'summary.json',
];

const el = {
  open: $('open'), message: $('message'), viewer: $('viewer'), clear: $('btn-clear'),
  panes: $('panes'), laneNames: $('lane-names'), tlLabel: $('tl-label'),
  play: $('btn-play'), prev: $('btn-prev'), next: $('btn-next'),
  mode: /** @type {HTMLSelectElement} */ ($('mode')),
  speed: /** @type {HTMLSelectElement} */ ($('speed')),
  scrub: /** @type {HTMLInputElement} */ ($('scrub')), time: $('time'),
  chkEntities: /** @type {HTMLInputElement} */ ($('chk-entities')),
  chkEvents: /** @type {HTMLInputElement} */ ($('chk-events')),
  chkFollow: /** @type {HTMLInputElement} */ ($('chk-follow')),
};

/**
 * One plain state object. `entries` holds the loaded runs in pane order; `t` is the shared position
 * (a game frame in frame mode, a decision position in decision mode).
 */
const state = {
  table: null,
  entries: /** @type {{label:string, run:any, pane:any, view:any, pos:number, drawnPos:number|null}[]} */ ([]),
  pb: createPlayback(),
  wanted: /** @type {'frame'|'decision'} */ ('frame'),
  mode: /** @type {'frame'|'decision'} */ ('frame'),
  end: 0,
  raf: 0,
  lastTick: 0,
  /** loads run one after the other, so panes appear in the order they were opened */
  queue: Promise.resolve(),
};

const timeline = createTimeline($('timeline'), {
  onSeek: ({ t }) => seekTo(t),
  onHover: (hit) => {
    const e = hit && state.entries[hit.lane];
    el.tlLabel.textContent = e ? `${e.label}  ${markLabel(e.run.model.marks[hit.pos])}` : '';
  },
  onKey: (dir) => seekTo(state.pb.time + dir * stepSize()),
});
fillLegend($('legend'));
for (const s of SPEEDS) el.speed.append(h('option', { value: String(s), selected: s === 1 }, `${s}×`));
wireOpeners({
  drop: el.open,
  folderInput: $('in-folder'), filesInput: $('in-files'),
  folderButton: $('btn-folder'), filesButton: $('btn-files'),
  onFiles: (files) => enqueue(() => openFiles(files)),
});

// ---------------------------------------------------------------- loading

const enqueue = (task) => { state.queue = state.queue.then(task, task); return state.queue; };

async function openFiles(files) {
  const dirs = files.runDirs();
  if (dirs.length === 0) {
    showMessage(el.message, `No recording found in the ${files.size} file(s) you opened: a run folder must contain meta.json and frames.bin.`);
    return;
  }
  const room = MAX_RUNS - state.entries.length;
  const warnings = [];
  if (dirs.length > room) warnings.push(`最多同时对比 ${MAX_RUNS} 个录像，${dirs.length - Math.max(room, 0)} 个没有打开。`);
  for (const dir of dirs.slice(0, Math.max(room, 0))) await addRun(files, dir, warnings);
  showMessage(el.message, warnings.join('\n'), 'warn');
}

async function addRun(files, dir, warnings, hint = dir.split('/').pop()) {
  showMessage(el.message, 'Loading…', 'info');
  try {
    state.table ??= await loadMaterials(files);
    const run = await loadRun(files.within(dir));
    const name = run.meta.runId || hint || `录像 ${state.entries.length + 1}`;
    warnings.push(...run.warnings.map((w) => `${name}: ${w}`));
    mountRun(run, name);
  } catch (err) {
    warnings.push(`${hint || dir || '录像'}: ${describeError(err)}`);
  }
}

function mountRun(run, hint) {
  const label = run.meta.runId || hint;
  const entry = { label, run, pane: null, view: null, pos: -1, drawnPos: null };
  entry.view = buildPaneView({
    title: label, sub: subtitle(run),
    onRemove: () => { removeEntry(entry); },
  });
  el.panes.append(entry.view.root);
  entry.pane = createPane({
    canvas: entry.view.canvas, table: state.table,
    zoomOut: entry.view.zoomOut, zoomIn: entry.view.zoomIn, zoomFit: entry.view.zoomFit, zoomLabel: entry.view.zoomLabel,
    readout: entry.view.readout,
    isPlaying: () => state.pb.playing,
    onShown: () => {},
    onError: (_p, err) => showMessage(el.message, `${label}: ${describeError(err)}`),
    onRecovered: () => showMessage(el.message, ''),
    onSettled: () => schedule(),
    onFollowOff: () => { el.chkFollow.checked = false; },
  });
  entry.pane.opts.follow = el.chkFollow.checked;
  entry.pane.opts.entities = el.chkEntities.checked;
  entry.pane.opts.events = el.chkEvents.checked;
  entry.view.details.addEventListener('toggle', () => { entry.drawnPos = null; showAll(); });
  state.entries.push(entry);
  el.viewer.hidden = false;
  el.open.classList.add('compact');
  relayout();
  entry.pane.load(run); // after the pane is in the grid, so the canvas has its size
  schedule();
}

function subtitle(run) {
  const bits = [];
  if (run.summary?.model) bits.push(run.summary.model);
  else if (run.meta.notes) bits.push(run.meta.notes);
  bits.push(run.model.marks.length ? `${run.model.marks.length} 个决策` : '没有决策记录');
  return bits.join(' · ');
}

function removeEntry(entry) {
  entry.view.root.remove();
  state.entries = state.entries.filter((e) => e !== entry);
  if (state.entries.length === 0) {
    el.viewer.hidden = true;
    el.open.classList.remove('compact');
    state.pb.playing = false;
  }
  relayout();
  showAll();
}

/** Recomputes everything that depends on which runs are loaded. */
function relayout() {
  const runs = state.entries.map((e) => e.run);
  state.mode = effectiveMode(state.wanted, runs);
  el.mode.value = state.mode;
  /** @type {HTMLOptionElement} */ (el.mode.querySelector('option[value=decision]')).disabled = !canCompareByDecision(runs);
  state.end = axisEnd(state.mode, runs);
  state.pb.time = Math.min(state.pb.time, state.end);
  el.scrub.max = String(state.end);
  el.panes.dataset.count = String(state.entries.length);
  el.clear.hidden = state.entries.length === 0;
  timeline.setMode(state.mode);
  timeline.setLanes(state.entries.map((e) => ({ marks: e.run.model.marks, lastFrame: e.run.lastFrame })));
  clear(el.laneNames);
  state.entries.forEach((e, i) => el.laneNames.append(h('span', {}, `第 ${i + 1} 行：${e.label}`)));
  el.play.textContent = state.pb.playing ? '暂停' : '播放';
}

// ---------------------------------------------------------------- clock

function schedule() {
  if (!state.raf) state.raf = requestAnimationFrame(tick);
}

function tick(now) {
  state.raf = 0;
  const pb = state.pb;
  const dt = state.lastTick ? Math.min(now - state.lastTick, MAX_TICK_MS) : 0;
  state.lastTick = pb.playing ? now : 0;
  if (pb.playing) {
    pb.time += (dt / 1000) * rateOf(state.mode) * pb.speed;
    if (pb.time >= state.end) { pb.time = state.end; setPlaying(false); }
  }
  showAll();
  if (pb.playing || state.entries.some((e) => e.pane.busy)) schedule();
}

function setPlaying(on) {
  if (on && state.pb.time >= state.end) state.pb.time = 0;
  state.pb.playing = on && state.entries.length > 0;
  state.lastTick = 0;
  el.play.textContent = state.pb.playing ? '暂停' : '播放';
  schedule();
}

function seekTo(t) {
  state.pb.time = Math.min(state.end, Math.max(0, t));
  schedule();
}

const stepSize = () => axisStep(state.mode, state.entries.map((e) => e.run));

/** Puts every pane on the picture and decision of the shared position. */
function showAll() {
  const { pb, mode } = state;
  for (const e of state.entries) {
    const frame = frameForAxis(mode, e.run, pb.time);
    e.pane.show(frame);
    const info = nowInfo(mode, e.run, pb.time, frame);
    showNow(e.view.now, info);
    if (e.view.details.open && e.drawnPos !== info.pos) {
      renderDecision(e.view.box, info.pos >= 0 ? detailFor(e.run.model, info.pos) : null, { compact: true });
      e.drawnPos = info.pos;
    }
    e.pos = info.pos;
  }
  timeline.setPlayhead(state.entries.length ? pb.time : null);
  el.scrub.value = String(pb.time);
  const unit = mode === 'frame' ? `帧 ${Math.floor(pb.time)} / ${state.end}  ·  ${(pb.time / 60).toFixed(1)} s` : `第 ${Math.min(state.end, pb.time + 1).toFixed(1)} / ${state.end} 个决策`;
  el.time.textContent = unit;
}

// ---------------------------------------------------------------- controls

el.play.addEventListener('click', () => setPlaying(!state.pb.playing));
el.prev.addEventListener('click', () => { setPlaying(false); seekTo(state.pb.time - stepSize()); });
el.next.addEventListener('click', () => { setPlaying(false); seekTo(state.pb.time + stepSize()); });
el.scrub.addEventListener('input', () => seekTo(Number(el.scrub.value)));
el.speed.addEventListener('change', () => { state.pb.speed = Number(el.speed.value); });
el.mode.addEventListener('change', () => {
  // keep roughly the same moment: convert the shared position through the first run
  const first = state.entries[0];
  const before = state.mode;
  const frame = first ? frameForAxis(before, first.run, state.pb.time) : 0;
  state.wanted = /** @type {'frame'|'decision'} */ (el.mode.value);
  relayout();
  if (first && state.mode !== before) {
    const marks = first.run.model.marks;
    const i = Math.max(0, marks.findLastIndex((m) => m.frame <= frame));
    state.pb.time = state.mode === 'frame' ? frame : i + (marks[i]?.frames ? (frame - marks[i].frame) / marks[i].frames : 0);
  }
  schedule();
});
const eachPane = (fn) => state.entries.forEach((e) => fn(e.pane));
el.chkEntities.addEventListener('change', () => eachPane((p) => { p.opts.entities = el.chkEntities.checked; p.stage.requestDraw(); }));
el.chkEvents.addEventListener('change', () => eachPane((p) => { p.opts.events = el.chkEvents.checked; p.stage.requestDraw(); }));
el.chkFollow.addEventListener('change', () => eachPane((p) => p.setFollow(el.chkFollow.checked)));
el.clear.addEventListener('click', () => { for (const e of [...state.entries]) removeEntry(e); });

document.addEventListener('keydown', (e) => {
  if (state.entries.length === 0 || !shortcutAllowed(e)) return;
  const keys = {
    ' ': () => setPlaying(!state.pb.playing),
    ArrowLeft: () => { setPlaying(false); seekTo(state.pb.time - stepSize()); },
    ArrowRight: () => { setPlaying(false); seekTo(state.pb.time + stepSize()); },
  };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
});

// ---------------------------------------------------------------- optional: ?src=<run directory url>&src=...

const sources = new URLSearchParams(location.search).getAll('src');
if (sources.length) enqueue(() => openUrls(sources));

async function openUrls(list) {
  const warnings = [];
  if (list.length > MAX_RUNS) warnings.push(`最多同时对比 ${MAX_RUNS} 个录像，只打开前 ${MAX_RUNS} 个。`);
  for (const raw of list.slice(0, MAX_RUNS)) {
    try {
      const url = sameOriginUrl(raw, location.href);
      const files = FileSet.fromUrls(new URL(url.pathname, url).href, RUN_FILES);
      await addRun(files, '', warnings, url.pathname.split('/').filter(Boolean).pop());
    } catch (err) {
      warnings.push(describeError(err));
    }
  }
  showMessage(el.message, warnings.join('\n'), 'warn');
}
