import { MAX_PROFILES, LETTERS, uniqueLabels } from '../report/chart-data.js';
import { badge } from '../report/bits.js';
import { loadFromFiles, loadFromUrls } from '../report/load.js';
import { renderReport } from '../report/report-view.js';
import { $, clear, describeError, h, showMessage } from '../ui/dom.js';
import { wireOpeners } from '../ui/open-files.js';

const el = {
  open: $('open'), message: $('message'), viewer: $('viewer'),
  series: $('series'), sections: $('sections'), clear: $('btn-clear'),
};

/** One plain state object: the profiles on the page, in the order they were opened. */
const state = {
  profiles: /** @type {import('../report/profile.js').Profile[]} */ ([]),
};

wireOpeners({
  drop: el.open,
  folderInput: $('in-folder'), filesInput: $('in-files'),
  folderButton: $('btn-folder'), filesButton: $('btn-files'),
  onFiles: (files) => loadFromFiles(files).then(add, (err) => showMessage(el.message, describeError(err))),
});
el.clear.addEventListener('click', () => { state.profiles = []; showMessage(el.message, ''); render(); });

/**
 * Adds freshly read profiles (up to the limit) and shows the warnings of the read.
 * @param {{profiles: import('../report/profile.js').Profile[], warnings: string[]}} read
 */
function add(read) {
  const warnings = [...read.warnings];
  const room = MAX_PROFILES - state.profiles.length;
  if (read.profiles.length > room) warnings.push(`最多同时看 ${MAX_PROFILES} 份，有 ${read.profiles.length - Math.max(room, 0)} 份没有打开。`);
  state.profiles = [...state.profiles, ...read.profiles.slice(0, Math.max(room, 0))];
  const failedAll = read.profiles.length === 0 && state.profiles.length === 0;
  showMessage(el.message, warnings.join('\n'), failedAll ? 'error' : 'warn');
  render();
}

function remove(index) {
  state.profiles = state.profiles.filter((_, i) => i !== index);
  showMessage(el.message, ''); // the warnings were about the files that were opened then
  render();
}

function render() {
  const has = state.profiles.length > 0;
  el.viewer.hidden = !has;
  el.clear.hidden = !has;
  el.open.classList.toggle('compact', has);
  clear(el.series);
  clear(el.sections);
  if (!has) return;
  const labels = uniqueLabels(state.profiles);
  state.profiles.forEach((p, i) => el.series.append(seriesChip(p, labels[i], i)));
  el.series.append(h('span', { className: 'rpt-muted' }, state.profiles.length < MAX_PROFILES ? '再拖一份进来可以对比。' : ''));
  for (const section of renderReport(state.profiles)) el.sections.append(section);
}

function seriesChip(p, label, i) {
  const chip = h('span', { className: 'rpt-series-chip' });
  if (state.profiles.length > 1) chip.append(badge(i, LETTERS[i]), ' ');
  chip.append(h('span', { className: 'rpt-series-name' }, label));
  const x = h('button', { type: 'button', className: 'rpt-x', title: `移除 ${label}` }, '×');
  x.setAttribute('aria-label', `移除 ${label}`);
  x.addEventListener('click', () => remove(i));
  chip.append(x);
  return chip;
}

// ---------------------------------------------------------------- optional: ?profile=<url> (repeatable)

const wanted = new URLSearchParams(location.search).getAll('profile');
if (wanted.length > 0) {
  showMessage(el.message, 'Loading…', 'info');
  loadFromUrls(wanted, location.href).then(add, (err) => showMessage(el.message, describeError(err)));
}
