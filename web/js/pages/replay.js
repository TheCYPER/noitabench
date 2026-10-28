import { FRAMES_PER_SECOND, SPEEDS, advance, createPlayback, seekToFrame, seekToStep, stepForTime } from '../replay/clock.js';
import { renderDecision } from '../replay/decision-panel.js';
import { detailFor } from '../replay/model.js';
import { fillLegend } from '../replay/legend.js';
import { fillMeta, updateSidePanels } from '../replay/panels.js';
import { createPane } from '../replay/pane.js';
import { reportLinkFor } from '../report/link.js';
import { loadRun } from '../replay/run.js';
import { createTimeline } from '../replay/timeline-canvas.js';
import { fractionIn, markAtFrame, markLabel } from '../replay/timeline.js';
import { FileSet } from '../ui/file-set.js';
import { $, clear, describeError, h, showMessage } from '../ui/dom.js';
import { shortcutAllowed } from '../ui/keys.js';
import { loadMaterials } from '../ui/load-materials.js';
import { wireOpeners } from '../ui/open-files.js';
import { sameOriginUrl } from '../ui/same-origin.js';

/** A long gap between two animation frames (hidden tab) must not skip the run. */
const MAX_TICK_MS = 250;
const RUN_FILES = [
  'meta.json', 'frames.bin', 'entities.jsonl', 'events.jsonl', 'decisions.jsonl',
  'transcript.jsonl', 'harness.jsonl', 'summary.json',
];

const el = {
  open: $('open'), message: $('message'), viewer: $('viewer'),
  runPicker: $('run-picker'), runSelect: /** @type {HTMLSelectElement} */ ($('run-select')),
  play: $('btn-play'), prev: $('btn-prev'), next: $('btn-next'),
  decPrev: $('btn-dec-prev'), decNext: $('btn-dec-next'),
  scrub: /** @type {HTMLInputElement} */ ($('scrub')), time: $('time'),
  speed: /** @type {HTMLSelectElement} */ ($('speed')),
  chkEntities: /** @type {HTMLInputElement} */ ($('chk-entities')),
  chkEvents: /** @type {HTMLInputElement} */ ($('chk-events')),
  chkFollow: /** @type {HTMLInputElement} */ ($('chk-follow')),
  chkShade: /** @type {HTMLInputElement} */ ($('chk-shade')),
  timelineBox: $('timeline-box'), tlLabel: $('tl-label'), legend: $('legend'),
  meta: $('meta'), decision: $('decision'), entities: $('entities'), events: $('events'),
};

/** One plain state object; every redraw reads from it. */
const state = {
  files: /** @type {FileSet|null} */ (null),
  table: null,
  run: null,
  pane: null,
  timeline: null,
  pb: createPlayback(),
  /** position of the selected decision in run.model.marks, -1 = none yet */
  selected: -1,
  /** the decision the panel was last drawn for */
  drawnSelected: null,
  raf: 0,
  lastTick: 0,
};

wireOpeners({
  drop: el.open,
  folderInput: $('in-folder'), filesInput: $('in-files'),
  folderButton: $('btn-folder'), filesButton: $('btn-files'),
  onFiles: openFiles,
});
for (const s of SPEEDS) el.speed.append(h('option', { value: String(s), selected: s === 1 }, `${s}×`));
fillLegend(el.legend);

// ---------------------------------------------------------------- loading

async function openFiles(files) {
  const dirs = files.runDirs();
  if (dirs.length === 0) {
    showMessage(el.message, `No recording found in the ${files.size} file(s) you opened: a run folder must contain meta.json and frames.bin.`);
    return;
  }
  state.files = files;
  clear(el.runSelect);
  for (const d of dirs) el.runSelect.append(h('option', { value: d }, d === '' ? '(top level)' : d));
  el.runPicker.hidden = dirs.length < 2;
  await openRun(dirs[0]);
}

async function openRun(dir) {
  showMessage(el.message, 'Loading…', 'info');
  try {
    state.table ??= await loadMaterials(state.files);
    const run = await loadRun(state.files.within(dir));
    start(run);
    showMessage(el.message, run.warnings.join('\n'), 'warn');
  } catch (err) {
    showMessage(el.message, describeError(err));
  }
}
el.runSelect.addEventListener('change', () => openRun(el.runSelect.value));

function start(run) {
  state.run = run;
  el.viewer.hidden = false;
  el.open.classList.add('compact');
  state.pane ??= buildPane();
  state.timeline ??= buildTimeline();
  state.pane.opts.follow = el.chkFollow.checked;
  state.pane.load(run);
  state.pane.setShading(el.chkShade.checked);
  state.pb = createPlayback();
  state.pb.time = run.firstFrame;
  state.pb.speed = Number(el.speed.value);
  state.lastTick = 0;
  state.selected = -1;
  state.drawnSelected = null;
  const marks = run.model.marks;
  el.timelineBox.hidden = marks.length === 0;
  state.timeline.setLanes(marks.length ? [{ marks, lastFrame: run.lastFrame }] : []);
  el.scrub.max = String(run.store.length - 1);
  updateControls();
  fillMeta(el, run);
  refreshDecision();
  state.pane.stage.requestDraw();
  schedule();
}

function buildPane() {
  const showMsg = (text, kind) => showMessage(el.message, text, kind);
  return createPane({
    canvas: /** @type {HTMLCanvasElement} */ ($('canvas')), table: state.table,
    zoomOut: $('zoom-out'), zoomIn: $('zoom-in'), zoomFit: $('zoom-fit'), zoomLabel: $('zoom-label'),
    readout: $('readout'),
    isPlaying: () => state.pb.playing,
    onShown: (pane) => { updateSidePanels(el, state.run, pane.shownFrame); updateHud(); },
    onError: (pane, err) => { state.pb.playing = false; updateControls(); showMsg(describeError(err), 'error'); },
    onRecovered: () => showMsg(state.run.warnings.join('\n'), 'warn'),
    onSettled: () => schedule(),
    onFollowOff: () => { el.chkFollow.checked = false; },
  });
}

function buildTimeline() {
  return createTimeline($('timeline'), {
    onSeek: ({ pos }) => selectDecision(pos),
    onHover: (hit) => { el.tlLabel.textContent = hit ? markLabel(state.run.model.marks[hit.pos]) : currentLabel(); },
    onKey: (dir) => selectDecision(state.selected + dir),
  });
}

// ---------------------------------------------------------------- decisions

function marks() { return state.run?.model.marks ?? []; }

function currentLabel() {
  const m = marks()[state.selected];
  return m ? markLabel(m) : '';
}

/** Selects a decision and moves the clock to the game frame at which it was asked. */
function selectDecision(pos) {
  const list = marks();
  if (list.length === 0) return;
  const p = Math.max(0, Math.min(list.length - 1, pos));
  state.selected = p;
  seekToFrame(state.pb, list[p].frame, state.run.firstFrame, state.run.lastFrame);
  refreshDecision();
  schedule();
}

/** Redraws the decision panel and the timeline marker when the selected decision changed. */
function refreshDecision() {
  const { run } = state;
  if (!run || state.drawnSelected === state.selected) return;
  state.drawnSelected = state.selected;
  state.timeline.setSelected(state.selected >= 0 ? { lane: 0, pos: state.selected } : null);
  el.tlLabel.textContent = currentLabel();
  if (run.model.marks.length === 0) {
    el.decision.className = 'dp empty';
    el.decision.textContent = '没有 decisions.jsonl';
    return;
  }
  el.decision.className = 'dp';
  renderDecision(el.decision, state.selected >= 0 ? detailFor(run.model, state.selected) : null);
}

// ---------------------------------------------------------------- playback loop

function schedule() {
  if (!state.raf) state.raf = requestAnimationFrame(tick);
}

function tick(now) {
  state.raf = 0;
  const { run, pb, pane } = state;
  if (!run) return;
  const dt = state.lastTick ? now - state.lastTick : 0;
  state.lastTick = pb.playing ? now : 0;
  const wasPlaying = pb.playing;
  advance(pb, Math.min(dt, MAX_TICK_MS), run.lastFrame);
  if (wasPlaying && !pb.playing) updateControls();
  state.selected = markAtFrame(marks(), pb.time, state.selected);
  refreshDecision();
  pane.show(pb.time);
  updateHud();
  if (pb.playing || pane.busy) schedule();
}

function setPlaying(on) {
  const { run, pb } = state;
  if (!run) return;
  if (on && pb.time >= run.lastFrame) seekToStep(pb, run.store.index.steps, 0);
  pb.playing = on;
  state.lastTick = 0;
  updateControls();
  schedule();
}

/** Moves the clock to the recorded step `delta` away from the one the clock is on (not the one drawn, which can lag). */
function stepBy(delta) {
  const { run, pb } = state;
  if (!run) return;
  const steps = run.store.index.steps;
  seekToStep(pb, steps, stepForTime(steps, pb.time) + delta);
  schedule();
}

function gotoStep(step) {
  const { run, pb } = state;
  if (!run) return;
  seekToStep(pb, run.store.index.steps, step);
  schedule();
}

// ---------------------------------------------------------------- hud

function updateControls() {
  el.play.textContent = state.pb.playing ? '暂停' : '播放';
}

/** Time readout, slider and timeline playhead: they follow the clock, not the picture. */
function updateHud() {
  const { run, pb } = state;
  const steps = run.store.index.steps;
  const step = Math.max(0, Math.min(steps.length - 1, stepForTime(steps, pb.time)));
  const seconds = (pb.time - run.firstFrame) / FRAMES_PER_SECOND;
  const total = (run.lastFrame - run.firstFrame) / FRAMES_PER_SECOND;
  // The slider follows the clock, not the picture: writing the drawn step into it while the user drags would make the thumb jump back.
  el.scrub.value = String(step);
  const m = marks()[state.selected];
  el.time.textContent = `帧 ${Math.floor(pb.time)} / ${run.lastFrame}  ·  ${seconds.toFixed(1)} / ${total.toFixed(1)} s  ·  步 ${step + 1}/${run.store.length}${m ? `  ·  决策 #${m.view}` : ''}`;
  state.timeline.setPlayhead(m ? m.pos + fractionIn(m, pb.time) : null);
}

// ---------------------------------------------------------------- controls

el.play.addEventListener('click', () => setPlaying(!state.pb.playing));
el.prev.addEventListener('click', () => { setPlaying(false); stepBy(-1); });
el.next.addEventListener('click', () => { setPlaying(false); stepBy(1); });
el.decPrev.addEventListener('click', () => { setPlaying(false); selectDecision(state.selected - 1); });
el.decNext.addEventListener('click', () => { setPlaying(false); selectDecision(state.selected + 1); });
el.scrub.addEventListener('input', () => gotoStep(Number(el.scrub.value)));
el.speed.addEventListener('change', () => { state.pb.speed = Number(el.speed.value); });
el.chkEntities.addEventListener('change', () => { if (state.pane) { state.pane.opts.entities = el.chkEntities.checked; state.pane.stage.requestDraw(); } });
el.chkEvents.addEventListener('change', () => { if (state.pane) { state.pane.opts.events = el.chkEvents.checked; state.pane.stage.requestDraw(); } });
el.chkFollow.addEventListener('change', () => state.pane?.setFollow(el.chkFollow.checked));
el.chkShade.addEventListener('change', () => state.pane?.setShading(el.chkShade.checked));
$('zoom-fit').addEventListener('click', fitView);

/** Shows the whole world; that only makes sense with the camera not following the player. */
function fitView() {
  el.chkFollow.checked = false;
  state.pane?.setFollow(false);
  state.pane?.stage.fit();
}

document.addEventListener('keydown', (e) => {
  if (!state.run || !shortcutAllowed(e)) return;
  const keys = {
    ' ': () => setPlaying(!state.pb.playing),
    ArrowLeft: () => { setPlaying(false); stepBy(-1); },
    ArrowRight: () => { setPlaying(false); stepBy(1); },
    '[': () => { setPlaying(false); selectDecision(state.selected - 1); },
    ']': () => { setPlaying(false); selectDecision(state.selected + 1); },
    '+': () => state.pane.stage.zoom(1), '=': () => state.pane.stage.zoom(1),
    '-': () => state.pane.stage.zoom(-1),
    0: fitView,
  };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
});

// ---------------------------------------------------------------- optional: ?src=<run directory url>

const src = new URLSearchParams(location.search).get('src');
if (src) openFilesFromUrl(src);

async function openFilesFromUrl(raw) {
  try {
    const url = sameOriginUrl(raw, location.href);
    state.files = FileSet.fromUrls(new URL(url.pathname, url).href, RUN_FILES);
  } catch (err) {
    showMessage(el.message, describeError(err));
    return;
  }
  el.runPicker.hidden = true;
  showReportLink(raw);
  await openRun('');
}

/** If a profile.json sits in the run folder, the header links to its report (existence only; nothing is read). */
async function showReportLink(raw) {
  const href = await reportLinkFor(sameOriginUrl(raw, location.href));
  if (!href) return;
  const link = /** @type {HTMLAnchorElement} */ ($('report-link'));
  link.href = href;
  link.hidden = false;
}
