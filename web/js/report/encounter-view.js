import { h } from '../ui/dom.js';
import { LETTERS, encounterMatrix } from './chart-data.js';
import { badge, chip, valueBar } from './bits.js';
import { parseReason, scoreText, unitText } from './format.js';
import { capabilityShort, encounterName } from './names.js';

/** The mean score of the scored visits of an encounter (0..1), or null. */
export function meanScore(encounter) {
  const scores = encounter.visits.filter((v) => v.scored && v.score !== null).map((v) => v.score);
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
}

/**
 * Every encounter of one profile: the ones the player met with their visits and the reasons behind each score,
 * the others as one line.
 * @param {import('./profile.js').Profile} p
 */
export function renderEncounters(p) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '遭遇点'));
  const met = p.encounters.filter((e) => e.visits.length > 0).length;
  root.append(h('p', { className: 'rpt-muted' }, `评分已实现 ${p.encounters.length} 个遭遇点，这一局遇到 ${met} 个。「放置」是这张图里放了几处，「必经」是主路上绕不开的；一次进入触发区并停留算一次接触，每次接触按规则给 0 到 100 分。`));
  const list = h('div', { className: 'enc-list' });
  for (const e of p.encounters) list.append(encounterBlock(e));
  root.append(list);
  return root;
}

function heading(e) {
  const frag = h('span', { className: 'enc-head' });
  frag.append(h('span', { className: 'cap-code' }, e.id), ' ', h('span', { className: 'enc-name' }, encounterName(e.id)));
  return frag;
}

function nodeChips(e) {
  const box = h('span', { className: 'enc-nodes' });
  for (const n of e.nodes) box.append(chip(`${n} ${capabilityShort(n)}`));
  return box;
}

function placedText(e) {
  return `放置 ${e.placed}${e.mustPassPlaced ? `（必经 ${e.mustPassPlaced}）` : ''}`;
}

function encounterBlock(e) {
  if (e.visits.length === 0) {
    const row = h('div', { className: 'enc enc-unmet' });
    row.append(heading(e), nodeChips(e), h('span', { className: 'rpt-muted' }, ` ${placedText(e)} · 没遇到`));
    return row;
  }
  const mean = meanScore(e);
  const d = h('details', { className: 'enc', open: true });
  const summary = h('summary');
  summary.append(heading(e), nodeChips(e), h('span', { className: 'rpt-muted' }, ` ${placedText(e)} · 遇到 ${e.visits.length} 次 · 平均 ${mean === null ? '未计分' : unitText(mean)}`));
  d.append(summary);
  e.visits.forEach((v, i) => d.append(visitBlock(v, i + 1)));
  return d;
}

function visitBlock(v, n) {
  const box = h('div', { className: 'visit' });
  const head = h('div', { className: 'visit-head' });
  const where = [`第 ${n} 次`, v.layer === null ? '' : `第 ${v.layer} 层`, frameRange(v), v.mustPass ? '必经' : '可选'].filter(Boolean).join(' · ');
  head.append(h('span', {}, where));
  const score = h('span', { className: 'visit-score' });
  if (v.scored && v.score !== null) score.append(h('b', {}, unitText(v.score)), valueBar(v.score * 100, 0));
  else score.append(h('span', { className: 'rpt-muted' }, '未计分'));
  head.append(score);
  box.append(head);
  const reasons = h('ul', { className: 'reasons' });
  for (const r of v.reasons) reasons.append(reasonLine(parseReason(r)));
  if (v.reasons.length) box.append(reasons);
  return box;
}

function frameRange(v) {
  if (v.enter === null) return '';
  return v.exit === null || v.exit === v.enter ? `帧 ${v.enter}` : `帧 ${v.enter}–${v.exit}`;
}

function reasonLine(r) {
  const li = h('li', { className: 'reason' });
  if (r.criterion) li.append(h('code', { className: 'reason-key' }, r.criterion));
  if (r.earned !== null && r.max !== null) {
    li.append(h('span', { className: 'reason-pts' }, `${scoreText(r.earned)} / ${scoreText(r.max)}`));
  }
  if (r.detail) li.append(h('span', { className: 'reason-detail' }, r.detail));
  return li;
}

/**
 * The comparison of the encounters of several profiles: one row per encounter, one cell per profile.
 * @param {import('./profile.js').Profile[]} profiles
 * @param {string[]} labels
 */
export function renderEncounterMatrix(profiles, labels) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '遭遇点'));
  root.append(h('p', { className: 'rpt-muted' }, '格子里是这个遭遇点各次接触的平均分（0 到 100）。「—」= 这张图里放了、但没遇到；「·」= 这份 profile 没有这个遭遇点。'));
  const wrap = h('div', { className: 'table-wrap' });
  const table = h('table', { className: 'list rpt-table' });
  const head = h('tr');
  head.append(h('th', {}, '遭遇点'));
  profiles.forEach((_, i) => {
    const th = h('th', { scope: 'col' });
    th.append(badge(i, LETTERS[i]), ' ', h('span', {}, labels[i]));
    head.append(th);
  });
  table.append(head);
  for (const row of encounterMatrix(profiles)) {
    const tr = h('tr');
    const th = h('th', { scope: 'row' });
    th.append(heading(row), h('div', { className: 'rpt-muted' }, row.nodes.map(capabilityShort).join('、')));
    tr.append(th);
    row.cells.forEach((cell, i) => tr.append(matrixCell(cell, i)));
    table.append(tr);
  }
  wrap.append(table);
  root.append(wrap);
  return root;
}

function matrixCell(cell, i) {
  const td = h('td');
  if (cell.status === 'absent') {
    td.append(h('span', { className: 'rpt-muted', title: '这份 profile 没有这个遭遇点' }, '·'));
  } else if (cell.status === 'unmet') {
    td.append(h('span', { className: 'rpt-muted' }, cell.placed ? '—' : '未放置'));
  } else if (cell.status === 'unscored') {
    td.append(h('span', { className: 'rpt-muted' }, `未计分（${cell.visits} 次）`));
  } else {
    td.append(h('span', { className: 'num' }, unitText(cell.mean)));
    if (cell.scored > 1) td.append(h('span', { className: 'rpt-muted' }, ` ×${cell.scored}`));
    td.append(valueBar(cell.mean * 100, i));
  }
  return td;
}
