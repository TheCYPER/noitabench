import { lastAtOrBefore } from '../format/recording.js';
import { clear, h, summarize } from '../ui/dom.js';
import { summaryText } from './text.js';

/** Newest events listed in the side panel. */
const EVENT_LIST_LENGTH = 12;

/**
 * @typedef {{meta:HTMLElement, entities:HTMLElement, events:HTMLElement}} SidePanels
 * The side-panel containers of replay.html that show the recording itself.
 */

const round = (v) => (Number.isInteger(v) ? v : Math.round(v * 10) / 10);

/**
 * The rows of the "recording" panel. The world seed and the rule seed are
 * deliberately not among them: a replay is read by people who may play the
 * same world again, and the rule seed fixes the secret potion recipes.
 *
 * @param {import('./run.js').Run} run
 * @returns {[string, string][]}
 */
export function metaRows(run) {
  const m = run.meta;
  const rows = [
    ['run', m.runId || '—'], ['created', m.created ?? '—'], ['world', `${m.width}×${m.height}`],
    ['stride', String(m.frameStride)],
    ['steps', `${run.store.length} (frames ${run.firstFrame}–${run.lastFrame})`],
    ['view', `${run.store.width}×${run.store.height} at (${run.store.origin.x}, ${run.store.origin.y})`],
    ['entities', run.entities.length ? `${run.entities.length} lines` : '—'],
    ['events', run.events.length ? `${run.events.length}` : '—'],
    ['decisions', run.decisions.length ? `${run.decisions.length}` : '—'],
    ['transcript', run.transcript.length ? `${run.transcript.length} records` : '—'],
  ];
  if (run.summary) rows.push(['harness', summaryText(run.summary)]);
  if (m.notes) rows.push(['notes', m.notes]);
  return rows;
}

/**
 * Fills the static "recording" panel.
 * @param {SidePanels} el
 * @param {import('./run.js').Run} run
 */
export function fillMeta(el, run) {
  clear(el.meta);
  for (const [k, v] of metaRows(run)) el.meta.append(h('dt', {}, k), h('dd', {}, v));
}

/**
 * Redraws the entity list and the newest events for the picture at game frame `frame`.
 * @param {SidePanels} el
 * @param {import('./run.js').Run} run
 * @param {number} frame
 */
export function updateSidePanels(el, run, frame) {
  updateEntities(el.entities, run, frame);
  updateEvents(el.events, run, frame);
}

function updateEntities(box, run, frame) {
  const i = lastAtOrBefore(run.entities, frame);
  clear(box);
  if (i < 0) {
    box.append(h('div', { className: 'empty' }, run.entities.length ? '这一帧之前没有实体记录' : '没有 entities.jsonl'));
    return;
  }
  const table = h('table', { className: 'list mono' });
  for (const e of run.entities[i].entities) {
    const hp = typeof e.hp === 'number' ? `${e.hp}${e.hp_max ? `/${e.hp_max}` : ''}` : '';
    const row = h('tr');
    row.append(h('td', {}, `${e.kind ?? '?'}#${e.id ?? '?'}`), h('td', {}, hp), h('td', {}, `${round(e.x)}, ${round(e.y)}`));
    table.append(row);
  }
  box.append(table);
}

function updateEvents(list, run, frame) {
  clear(list);
  const hi = lastAtOrBefore(run.events, frame);
  if (hi < 0) {
    list.append(h('li', { className: 'empty' }, run.events.length ? '还没有事件' : '没有 events.jsonl'));
    return;
  }
  for (let i = hi; i >= Math.max(0, hi - (EVENT_LIST_LENGTH - 1)); i--) {
    const e = run.events[i];
    list.append(h('li', { className: 'mono' }, `f${e.frame} ${e.type} ${summarize(e, ['frame', 'type'])}`));
  }
}
