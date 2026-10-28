import { h } from '../ui/dom.js';
import { LETTERS, metricMatrix } from './chart-data.js';
import { badge, chip, valueBar } from './bits.js';
import { unitText } from './format.js';
import { capabilityShort, metricName } from './names.js';

const isMeasured = (m) => m.status === 'measured' && m.value !== null;

/**
 * The global metrics of one profile: the measured ones with their value, the others with the reason they
 * were not measured.
 * @param {import('./profile.js').Profile} p
 */
export function renderMetrics(p) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '全局指标'));
  const measured = p.metrics.filter(isMeasured);
  const rest = p.metrics.filter((m) => !isMeasured(m));
  root.append(h('p', { className: 'rpt-muted' }, `整局都在算、不依赖遭遇点的指标（值 0 到 100）。已测 ${measured.length} 个，未测 ${rest.length} 个。`));
  if (p.metrics.length === 0) {
    root.append(h('p', { className: 'empty' }, '这份 profile 没有指标。'));
    return root;
  }
  const list = h('ul', { className: 'plain metric-list' });
  for (const m of measured) list.append(metricItem(m, true));
  for (const m of rest) list.append(metricItem(m, false));
  root.append(list);
  return root;
}

function metricItem(m, measured) {
  const li = h('li', { className: `metric${measured ? '' : ' metric-off'}` });
  const head = h('div', { className: 'metric-head' });
  head.append(h('span', { className: 'metric-name' }, metricName(m.name)));
  for (const c of m.capabilities) head.append(chip(`${c} ${capabilityShort(c)}`));
  head.append(chip(measured ? '已测' : '未测', measured ? 'ok' : 'off'));
  li.append(head);
  if (measured) {
    const line = h('div', { className: 'metric-value' });
    line.append(h('b', {}, unitText(m.value)), valueBar(m.value * 100, 0));
    if (m.opportunities !== null) line.append(h('span', { className: 'rpt-muted' }, `机会 ${m.opportunities}`));
    li.append(line);
  }
  if (m.reason) li.append(h('div', { className: 'rpt-muted metric-reason' }, m.reason));
  return li;
}

/**
 * The comparison of the metrics of several profiles.
 * @param {import('./profile.js').Profile[]} profiles
 * @param {string[]} labels
 */
export function renderMetricMatrix(profiles, labels) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '全局指标'));
  root.append(h('p', { className: 'rpt-muted' }, '格子里是指标的值（0 到 100）；「未测」= 这一局没有足够的数据（原因在下面每一局的明细里）。'));
  const wrap = h('div', { className: 'table-wrap' });
  const table = h('table', { className: 'list rpt-table' });
  const head = h('tr');
  head.append(h('th', {}, '指标'));
  profiles.forEach((_, i) => {
    const th = h('th', { scope: 'col' });
    th.append(badge(i, LETTERS[i]), ' ', h('span', {}, labels[i]));
    head.append(th);
  });
  table.append(head);
  for (const row of metricMatrix(profiles)) {
    const tr = h('tr');
    const th = h('th', { scope: 'row' });
    th.append(h('span', {}, row.label), h('div', { className: 'rpt-muted' }, row.capabilities.join('、')));
    tr.append(th);
    row.cells.forEach((cell, i) => tr.append(metricCell(cell, i)));
    table.append(tr);
  }
  wrap.append(table);
  root.append(wrap);
  return root;
}

function metricCell(cell, i) {
  const td = h('td');
  if (!cell.present) td.append(h('span', { className: 'rpt-muted', title: '这份 profile 没有这个指标' }, '·'));
  else if (cell.status === 'measured' && cell.value !== null) td.append(h('span', { className: 'num' }, unitText(cell.value)), valueBar(cell.value * 100, i));
  else td.append(h('span', { className: 'rpt-muted' }, '未测'));
  return td;
}
