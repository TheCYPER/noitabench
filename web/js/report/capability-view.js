import { h } from '../ui/dom.js';
import { LETTERS, capabilityRows, thinCapabilities } from './chart-data.js';
import { badge, chip, details, scoreBar } from './bits.js';
import { isRoutineNote, scoreText, unitText } from './format.js';
import { capabilityName, capabilityShort, encounterName, metricName } from './names.js';
import { legend } from './summary-view.js';

/**
 * The capability profile: one row per capability, one bar per profile in each row.
 * @param {import('./profile.js').Profile[]} profiles
 * @param {string[]} labels
 */
export function renderCapabilities(profiles, labels) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '能力画像'));
  if (profiles.length > 1) root.append(legend(profiles, labels));
  root.append(key(profiles.some((p) => p.hasDiscount)));
  const list = h('div', { className: 'cap-list' });
  for (const row of capabilityRows(profiles)) list.append(capabilityRow(row, profiles));
  root.append(list);
  if (profiles.length === 1) root.append(thinLine(profiles[0]));
  return root;
}

/** What the bar styles mean. */
function key(discounted) {
  const box = h('div', { className: 'rpt-key' });
  const item = (swatch, text) => {
    const el = h('span', { className: 'rpt-key-item' });
    el.append(h('span', { className: `swatch-bar ${swatch}` }), h('span', {}, text));
    box.append(el);
  };
  if (discounted) {
    item('raw', '浅色：这项能力的原始分');
    item('fill', '深色：打折后的分（原始分 × n/(n+2)，n = 机会数），能力分取它的平均');
  } else {
    item('fill', '条长：这项能力的分（0 到 100）');
  }
  item('hatch', '斜纹：覆盖不足（机会少于 2 次）');
  item('empty', '空：没有遇到（打折版评分里按 0 计）');
  return box;
}

function capabilityRow(row, profiles) {
  const el = h('div', { className: 'cap-row' });
  const label = h('div', { className: 'cap-label', title: capabilityName(row.key) });
  label.append(h('span', { className: 'cap-code' }, row.key), h('span', { className: 'cap-name' }, capabilityShort(row.key)));
  el.append(label);
  const lines = h('div', { className: 'cap-lines' });
  row.cells.forEach((cell, i) => {
    const line = h('div', { className: 'cap-line' });
    if (profiles.length > 1) line.append(badge(i, LETTERS[i]));
    line.append(scoreBar(cell, i), valueText(cell));
    lines.append(line);
  });
  el.append(lines);
  if (profiles.length === 1) {
    const src = sources(profiles[0].capabilities.get(row.key));
    if (src) el.append(src);
  }
  return el;
}

/** The numbers beside a bar: the figure that counts, the raw score and the opportunities. */
function valueText(cell) {
  const box = h('span', { className: 'cap-val' });
  if (!cell.present) {
    box.append(h('span', { className: 'rpt-muted' }, '没有数据'));
    return box;
  }
  if (cell.score === null) {
    box.append(h('b', {}, cell.discounted === null ? '—' : scoreText(cell.discounted)), h('span', { className: 'rpt-muted' }, cell.discounted === null ? ' 未遇到' : ' 未遇到，按 0 计'));
    return box;
  }
  const main = cell.discounted ?? cell.score;
  box.append(h('b', {}, scoreText(main)));
  const sub = [];
  if (cell.discounted !== null) sub.push(`原始 ${scoreText(cell.score)}`);
  if (cell.discount !== null) sub.push(`× ${cell.discount.toFixed(2)}`);
  sub.push(`机会 ${cell.opportunities}`);
  box.append(h('span', { className: 'rpt-muted' }, ` ${sub.join(' · ')}`));
  if (cell.thin) box.append(' ', chip('覆盖不足', 'thin'));
  return box;
}

/** What a score was made of: the encounters and metrics behind it (one profile only). */
function sources(cap) {
  if (!cap) return null;
  const items = [];
  for (const e of cap.encounters) {
    const role = e.role === 'secondary' ? '次要节点' : e.role === 'scene' ? '组合场景' : '主要节点';
    items.push(`${e.id} ${encounterName(e.id)} · ${role}${e.weight !== null && e.weight !== 1 ? `（权重 ${e.weight}）` : ''} · ${unitText(e.score)}`);
  }
  for (const m of cap.metrics) items.push(`${metricName(m.name)} · ${unitText(m.value)}${m.n !== null ? `（${m.n} 次）` : ''}`);
  for (const part of cap.parts) {
    items.push(`${part.name} ${capabilityName(part.name)} · ${part.score === null ? '没有分' : scoreText(part.score)}（机会 ${part.opportunities}）`);
  }
  if (cap.note && !isRoutineNote(cap.note)) items.push(`说明：${cap.note}`);
  if (items.length === 0) return null;
  const d = details(`这个分是怎么来的（${items.length}）`, 'cap-sources');
  const ul = h('ul', { className: 'plain' });
  for (const t of items) ul.append(h('li', {}, t));
  d.append(ul);
  return d;
}

function thinLine(p) {
  const thin = thinCapabilities(p);
  if (thin.length === 0) return h('p', { className: 'rpt-muted' }, '每项有分的能力都至少有 2 次机会。');
  return h('p', { className: 'rpt-muted' }, `覆盖不足（机会少于 2 次）：${thin.map((k) => `${k} ${capabilityShort(k)}`).join('、')}。`);
}
