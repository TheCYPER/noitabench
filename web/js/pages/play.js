import { drawAim, drawBurning, drawPlayerBox, drawVisible } from '../render/play-overlays.js';
import { GridRenderer } from '../render/grid-renderer.js';
import { $, clear, describeError, h, showMessage } from '../ui/dom.js';
import { shortcutAllowed } from '../ui/keys.js';
import { loadMaterials } from '../ui/load-materials.js';
import { createApi } from '../play/api.js';
import { commandsForClick } from '../play/clicks.js';
import {
  dropBottle, dropSpell, dropWand, formatDecision, inspectBottle, inspectSpell, inspectWand, swapWand,
} from '../play/commands.js';
import { editClick, emptyEdit, takePicked } from '../play/edit-state.js';
import { budgetLine, commandSignature, endBanner, eventRows, latestInspect, resultRows, stopText } from '../play/hud.js';
import { BINDINGS, Gestures, STEP_CHOICES, isGameKey } from '../play/keymap.js';
import { createNotesPanel } from '../play/notes-panel.js';
import { renderBottles, renderLegend, renderSpells, renderVitals, renderWands } from '../play/panels.js';
import { decodeView, entityAt } from '../play/view-data.js';

/** Colour for cells outside the world (material index 255 in the window). */
const OUTSIDE_RGB = [10, 8, 7];

const el = {
  message: $('message'), banner: $('banner'), canvas: /** @type {HTMLCanvasElement} */ ($('canvas')), readout: $('readout'),
  cmdForm: $('cmd-form'), cmdText: /** @type {HTMLInputElement} */ ($('cmd-text')), cmdRun: $('cmd-run'),
  step: /** @type {HTMLSelectElement} */ ($('step-ticks')),
  zoomIn: $('zoom-in'), zoomOut: $('zoom-out'), zoomFit: $('zoom-fit'), zoomLabel: $('zoom-label'),
  chkFire: /** @type {HTMLInputElement} */ ($('chk-fire')), chkAim: /** @type {HTMLInputElement} */ ($('chk-aim')),
  end: $('btn-end'), budget: $('budget'), stop: $('stop'), results: $('results'), events: $('events'),
  vitals: $('vitals'), wands: $('wands'), spells: $('spells'), bottles: $('bottles'), legend: $('legend'),
  cmdHelp: $('cmd-help'), editHint: $('edit-hint'), editActions: $('edit-actions'), inspect: $('inspect'), keys: /** @type {HTMLTableElement} */ ($('keys')),
};

const S = {
  api: createApi(location.href),
  renderer: /** @type {GridRenderer|null} */ (null),
  answer: null, view: null, cost: null, lastText: '',
  busy: false, closed: false, recorded: false, stepTicks: 1, bottle: /** @type {number|null} */ (null),
  edit: emptyEdit(), inspectText: null, autoFit: true, raf: 0,
  history: /** @type {string[]} */ ([]), historyAt: 0,
  gestures: new Gestures(), // W: a tap jumps, a hold levitates (decided when the key comes up)
};

const state = () => S.answer.observation.state;
const keyContext = () => {
  const st = S.answer ? state() : null;
  return {
    stepTicks: S.stepTicks, bottle: S.bottle ?? undefined, wandCount: st?.wands.length,
    activeBottle: st?.bottles.find((b) => b.active)?.index, activeWand: st?.active_wand,
  };
};

// ------------------------------------------------------------------ talking to the server

/** Sends one decision (commands or typed text) and shows what came back. Returns true if every command was accepted. */
async function submit(request, shown) {
  if (S.busy || S.closed || !S.answer || S.answer.over) return false;
  S.busy = true;
  el.cmdRun.disabled = true;
  showMessage(el.message, '');
  try {
    const res = await S.api.decide(request);
    S.lastText = shown ?? (request.commands ? formatDecision(request.commands) : request.text);
    S.cost = res.cost;
    apply(res);
    return res.ok;
  } catch (err) {
    showMessage(el.message, describeError(err));
    return false;
  } finally {
    S.busy = false;
    el.cmdRun.disabled = S.closed || Boolean(S.answer?.over);
  }
}

function apply(res) {
  S.answer = res.answer;
  S.view = decodeView(res.view);
  S.edit = emptyEdit();
  if (S.bottle !== null && S.bottle >= state().bottles.length) S.bottle = null;
  const seen = latestInspect(res.answer);
  if (seen) S.inspectText = `${S.lastText}\n${JSON.stringify(seen.result, null, 2)}`;
  S.closed = Boolean(res.closed);
  if (res.summary) S.recorded = Boolean(res.summary.recording); // the server closes by itself when the episode is over
  renderAll();
}

// ------------------------------------------------------------------ drawing

function currentOverlays() {
  const v = S.view;
  if (!v) return [];
  const aim = state().aim.degrees;
  return [
    (ctx, cam) => { if (el.chkFire.checked) drawBurning(ctx, cam, v); },
    (ctx, cam) => drawVisible(ctx, cam, v.entities),
    (ctx, cam) => drawPlayerBox(ctx, cam, v.player),
    (ctx, cam) => { if (el.chkAim.checked) drawAim(ctx, cam, v.player, aim); },
  ];
}

function drawNow() {
  S.raf = 0;
  const r = S.renderer;
  if (!r) return;
  r.resize();
  if (S.view) fitOrCenter();
  r.render(currentOverlays());
  const z = r.view.zoom;
  el.zoomLabel.textContent = `${z < 1 ? `1/${1 / z}` : z}×`;
}
const requestDraw = () => { if (!S.raf) S.raf = requestAnimationFrame(drawNow); };

/** Fit the whole window in the canvas, or keep the player in the middle when the player zoomed. */
function fitOrCenter() {
  const { view } = S.renderer;
  const p = S.view.player;
  if (S.autoFit) view.zoom = view.fitZoom(8);
  view.centerOn(p.x + p.w / 2, p.y + p.h / 2);
}

function showView() {
  const v = S.view;
  S.renderer.setGrid(v.materials, v.width, v.height, v.origin);
  requestDraw();
}

function renderAll() {
  showView();
  const a = S.answer;
  const st = state();
  el.budget.textContent = budgetLine(a, S.cost);
  el.stop.textContent = `${S.lastText ? `${S.lastText} → ` : ''}${stopText(a.stop)}`;
  clear(el.results);
  for (const r of resultRows(a)) el.results.append(h('li', { className: r.ok ? '' : 'bad' }, r.text));
  clear(el.events);
  for (const text of eventRows(a)) el.events.append(h('li', {}, text));
  renderVitals(el.vitals, st);
  renderSide(st);
  renderLegend(el.legend, S.view.legend, S.renderer.table);
  el.inspect.textContent = S.inspectText ?? '还没有查看过东西。';
  showMessage(el.banner, endBanner(a, S.closed, S.recorded), 'warn');
  const dead = Boolean(a.over) || S.closed;
  el.cmdRun.disabled = dead;
  el.end.disabled = S.closed;
}

function renderSide(st) {
  const send = (command) => submit({ commands: [command] });
  renderWands(el.wands, st, {
    canEdit: st.can_edit_wands, picked: S.edit.slot,
    onSwap: (i) => send(swapWand(i)), onInspect: (i) => send(inspectWand(i)), onDrop: (i) => send(dropWand(i)),
    onSlot: (wand, slot, filled) => editStep({ kind: 'slot', wand, slot, filled }),
  });
  renderSpells(el.spells, st, {
    canEdit: st.can_edit_wands, picked: S.edit.spell,
    onPick: (i) => editStep({ kind: 'spell', index: i }),
    onInspect: (i) => send(inspectSpell(i)), onDrop: (i) => send(dropSpell(i)),
  });
  renderBottles(el.bottles, st, {
    chosen: S.bottle,
    onChoose: (i) => { S.bottle = i; renderSide(state()); },
    onInspect: (i) => send(inspectBottle(i)), onDrop: (i) => send(dropBottle(i)),
  });
  renderEditHint(st);
}

function renderEditHint(st) {
  clear(el.editActions);
  if (!st.can_edit_wands) {
    el.editHint.textContent = '这里不能改法杖：只有休息区和改杖台可以。';
    return;
  }
  const cancel = h('button', { type: 'button', className: 'small' }, '取消选择');
  cancel.addEventListener('click', () => { S.edit = emptyEdit(); renderSide(state()); });
  if (S.edit.spell !== null) {
    el.editHint.textContent = `已选中法术 [${S.edit.spell}]：点一根法杖的槽放进去。`;
    el.editActions.append(cancel);
  } else if (S.edit.slot) {
    el.editHint.textContent = `已选中法杖 ${S.edit.slot.wand} 的槽 ${S.edit.slot.slot}：点同一根法杖的另一个槽交换，或取出。`;
    const take = h('button', { type: 'button', className: 'small primary' }, '取出');
    take.addEventListener('click', () => { const r = takePicked(S.edit); S.edit = r.state; if (r.command) submit({ commands: [r.command] }); });
    el.editActions.append(take, cancel);
  } else {
    el.editHint.textContent = '点一个带着的法术，再点法杖的槽；或点法杖里的两个槽交换。每个改动算一个决策。';
  }
}

function editStep(target) {
  const r = editClick(S.edit, target);
  S.edit = r.state;
  if (r.command) submit({ commands: [r.command] });
  else renderSide(state());
}

// ------------------------------------------------------------------ input

function pointerCell(e) {
  const rect = el.canvas.getBoundingClientRect();
  const view = S.renderer.view;
  const wx = view.wx(e.clientX - rect.left);
  const wy = view.wy(e.clientY - rect.top);
  return { wx, wy, x: Math.floor(wx), y: Math.floor(wy), entity: S.view ? entityAt(S.view.entities, wx, wy) : null };
}

el.canvas.addEventListener('pointermove', (e) => {
  if (!S.view) return;
  const c = pointerCell(e);
  const who = c.entity ? `  ${c.entity.kind}#${c.entity.id}` : '';
  el.readout.textContent = `(${c.x}, ${c.y})${who}`;
});
el.canvas.addEventListener('click', (e) => {
  if (!S.view) return;
  const c = pointerCell(e);
  const commands = commandsForClick({ button: 0, shiftKey: e.shiftKey }, c, keyContext());
  if (commands) submit({ commands });
});
el.canvas.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  if (!S.view) return;
  const commands = commandsForClick({ button: 2 }, pointerCell(e), keyContext());
  if (commands) submit({ commands });
});

window.addEventListener('keydown', (e) => {
  if (!shortcutAllowed(e)) return;
  if (e.key === 'Enter') { e.preventDefault(); el.cmdText.focus(); return; }
  if (e.key === '+' || e.key === '=') { zoom(1); return; }
  if (e.key === '-') { zoom(-1); return; }
  if (e.key === '0') { S.autoFit = true; requestDraw(); return; }
  if (!S.answer) return;
  if (isGameKey(e)) e.preventDefault();
  const commands = S.gestures.down(e, keyContext(), e.timeStamp);
  if (commands) submit({ commands });
});
// W / Up is decided when it comes up: under 200 ms a jump, longer levitation for as long as it was held
window.addEventListener('keyup', (e) => {
  const commands = S.gestures.up(e, e.timeStamp);
  if (commands && S.answer) {
    e.preventDefault();
    submit({ commands });
  }
});
window.addEventListener('blur', () => S.gestures.reset()); // no key-up will come

function zoom(dir) {
  if (!S.renderer) return;
  S.autoFit = false;
  S.renderer.view.zoomStep(dir);
  requestDraw();
}
el.zoomIn.addEventListener('click', () => zoom(1));
el.zoomOut.addEventListener('click', () => zoom(-1));
el.zoomFit.addEventListener('click', () => { S.autoFit = true; requestDraw(); });
// a form control that keeps the focus would swallow the game keys, so let go of it after a change
const letGo = (control) => control.addEventListener('change', () => control.blur());
el.chkFire.addEventListener('change', requestDraw);
el.chkAim.addEventListener('change', requestDraw);
el.step.addEventListener('change', () => { S.stepTicks = Number(el.step.value); });
[el.chkFire, el.chkAim, el.step].forEach(letGo);

el.cmdForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = el.cmdText.value.trim();
  if (!text) return;
  S.history.push(text);
  S.historyAt = S.history.length;
  if (await submit({ text }, text)) el.cmdText.value = '';
});
el.cmdText.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { el.cmdText.blur(); return; }
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
  e.preventDefault();
  S.historyAt = Math.max(0, Math.min(S.history.length, S.historyAt + (e.key === 'ArrowUp' ? -1 : 1)));
  el.cmdText.value = S.history[S.historyAt] ?? '';
});

el.end.addEventListener('click', async () => {
  if (S.closed || !window.confirm('结束这一局？录像会保存，之后不能再继续。')) return;
  try {
    const res = await S.api.close();
    S.closed = true;
    S.recorded = Boolean(res.summary.recording);
    showMessage(el.message, `已结束：${res.summary.decisions} 个决策，${res.summary.frames} 帧。`, 'info');
    if (S.answer) renderAll();
  } catch (err) {
    showMessage(el.message, describeError(err));
  }
});

// ------------------------------------------------------------------ start

function fillStatic() {
  for (const n of STEP_CHOICES) el.step.append(h('option', { value: String(n) }, `${n} tick（${n * 10} 帧）`));
  const rows = BINDINGS.map((b) => [b.label, b.text]);
  rows.push(['1-9', '拿起第 n 根法杖'], ['Enter', '去命令框'], ['+ − 0', '缩放']);
  for (const [k, text] of rows) {
    const tr = h('tr');
    tr.append(h('td', { className: 'mono' }, k), h('td', {}, text));
    el.keys.append(tr);
  }
}

async function start() {
  fillStatic();
  try {
    const table = await loadMaterials(null);
    const rgb = table.rgb.slice();
    rgb.set(OUTSIDE_RGB, 255 * 3);
    S.renderer = new GridRenderer(el.canvas, { ...table, rgb });
    S.renderer.setShading(false);
    new ResizeObserver(requestDraw).observe(el.canvas);
    el.canvas.addEventListener('wheel', (e) => { e.preventDefault(); zoom(e.deltaY < 0 ? 1 : -1); }, { passive: false });
    const [hello, first] = await Promise.all([S.api.hello(), S.api.state()]);
    const notes = createNotesPanel({
      api: S.api, select: /** @type {HTMLSelectElement} */ ($('notes-select')), name: /** @type {HTMLInputElement} */ ($('notes-name')),
      text: /** @type {HTMLTextAreaElement} */ ($('notes-text')), quota: $('notes-quota'), status: $('notes-status'),
      save: $('notes-save'), fresh: $('notes-new'), remove: $('notes-delete'),
    });
    for (const c of hello.commands) {
      el.cmdHelp.append(h('dt', {}, commandSignature(c)), h('dd', {}, c.summary));
    }
    S.cost = null;
    apply(first);
    await notes.refresh('');
    el.canvas.focus();
  } catch (err) {
    showMessage(el.message, describeError(err));
  }
}
start();
