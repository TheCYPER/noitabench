import { h } from '../ui/dom.js';
import { LETTERS, playerText, summaryRows } from './chart-data.js';
import { badge, valueBar } from './bits.js';
import { compositeNoteText, countText, gameTimeText, outcomeParts, outcomeText, scoreText, shareText, usdText } from './format.js';

/** How far the parts may be from the composite before the page stops showing them as a sum (rounding only). */
const SUM_TOLERANCE = 0.06;

/**
 * The top of the page: one profile's headline, or the comparison table of several.
 * @param {import('./profile.js').Profile[]} profiles
 * @param {string[]} labels
 */
export function renderSummary(profiles, labels) {
  return profiles.length === 1 ? renderHeadline(profiles[0], labels[0]) : renderComparison(profiles, labels);
}

/**
 * The composite as 0.8 × ability + 0.2 × depth, when the numbers the profile carries add up; else null.
 * @param {import('./profile.js').Profile} p
 * @returns {{ability:number, depth:number}|null}
 */
export function contributions(p) {
  if (p.composite === null || p.ability === null || p.depth.score === null) return null;
  const ability = 0.8 * p.ability;
  const depth = 0.2 * p.depth.score;
  return Math.abs(ability + depth - p.composite) <= SUM_TOLERANCE ? { ability, depth } : null;
}

function renderHeadline(p, label) {
  const root = h('section', { className: 'panel rpt-head' });
  const title = h('div', { className: 'rpt-title' });
  title.append(h('h1', {}, label), h('span', { className: 'rpt-sub' }, subtitle(p)));
  root.append(title);

  const hero = h('div', { className: 'rpt-hero' });
  const big = h('div', { className: 'rpt-composite' });
  big.append(h('span', { className: 'rpt-num' }, scoreText(p.composite)), h('span', { className: 'rpt-cap' }, '综合分 / 100'));
  hero.append(big, parts(p));
  root.append(hero);

  if (p.compositeNote) root.append(h('p', { className: 'message warn' }, compositeNoteText(p.compositeNote)));
  if (!p.hasDiscount) {
    root.append(h('p', { className: 'message info' }, '这份 profile 来自较早的评分版本：覆盖不足（机会少于 2 次）的能力没有计入能力分，下面的条也没有「打折后」一栏。'));
  }
  root.append(facts(p));
  return root;
}

function subtitle(p) {
  return [playerText(p), p.model?.provider && p.source === 'agent' ? p.model.provider : ''].filter(Boolean).join(' · ');
}

/** The two parts of the composite, each with its weight, and the sum when it adds up. */
function parts(p) {
  const sum = contributions(p);
  const box = h('div', { className: 'rpt-parts' });
  box.append(part('能力分', p.ability, 0.8, sum?.ability ?? null, 0, p.abilityRaw !== null && p.hasDiscount ? `未打折的平均 ${scoreText(p.abilityRaw)}` : ''));
  box.append(part('深度分', p.depth.score, 0.2, sum?.depth ?? null, 0, depthNote(p)));
  return box;
}

function depthNote(p) {
  if (p.depth.reachedSealedRoom) return '到达封印室';
  return p.depth.cappedAtSeal ? '封印以下的挖掘不计入深度' : '';
}

function part(name, value, weight, contribution, series, note) {
  const el = h('div', { className: 'rpt-part' });
  const head = h('div', { className: 'rpt-part-head' });
  head.append(h('span', { className: 'rpt-part-name' }, name), h('b', {}, scoreText(value)));
  if (contribution !== null) head.append(h('span', { className: 'rpt-muted' }, `× ${weight} = ${shareText(contribution)}`));
  el.append(head, valueBar(value, series));
  if (note) el.append(h('div', { className: 'rpt-muted' }, note));
  return el;
}

/** Outcome, steps, cost, and which capabilities had too few opportunities. */
function facts(p) {
  const dl = h('dl', { className: 'meta rpt-facts' });
  const row = (k, v) => dl.append(h('dt', {}, k), h('dd', {}, v));
  row('结果', outcomeText(p));
  row('步数', stepsText(p));
  row('花费', costText(p));
  if (p.cost) row('耗时', p.cost.wallSeconds === null ? '—' : `${p.cost.wallSeconds.toFixed(0)} s（真实时间）`);
  return dl;
}

/** @param {import('./profile.js').Profile} p */
export function stepsText(p) {
  const frames = p.steps.frames ?? p.outcome.frames;
  const bits = [];
  if (p.steps.decisions !== null) bits.push(`${countText(p.steps.decisions)} 个决策`);
  if (frames !== null) bits.push(`${countText(frames)} 帧（游戏时间 ${gameTimeText(frames)}）`);
  return bits.join(' · ') || '—';
}

/** @param {import('./profile.js').Profile} p */
export function costText(p) {
  if (!p.cost) return '没有（不是模型局，或缺少 summary.json）';
  const bits = [p.cost.usd === null ? '—' : usdText(p.cost.usd)];
  if (p.cost.costKnown === false) bits.push('价格未知，美元数不可信');
  if (p.cost.modelCalls !== null) bits.push(`${countText(p.cost.modelCalls)} 次模型调用`);
  return bits.join(' · ');
}

function renderComparison(profiles, labels) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '对比'));
  root.append(legend(profiles, labels));
  const wrap = h('div', { className: 'table-wrap' });
  const table = h('table', { className: 'list rpt-table' });
  const head = h('tr');
  head.append(h('th', {}, '项目'));
  profiles.forEach((p, i) => {
    const th = h('th', { scope: 'col' });
    th.append(badge(i, LETTERS[i]), ' ', h('span', {}, labels[i]));
    head.append(th);
  });
  table.append(head);
  for (const row of summaryRows(profiles)) table.append(summaryRow(row));
  table.append(textRow('结果', profiles.map((p) => outcomeParts(p).join(' · '))));
  table.append(textRow('玩家', profiles.map(playerText)));
  wrap.append(table);
  root.append(wrap);
  for (const [i, p] of profiles.entries()) {
    if (p.compositeNote) root.append(h('p', { className: 'message warn' }, `${LETTERS[i]} ${labels[i]}：${compositeNoteText(p.compositeNote)}`));
  }
  if (profiles.some((p) => !p.hasDiscount) && profiles.some((p) => p.hasDiscount)) {
    root.append(h('p', { className: 'message warn' }, '这些 profile 不是同一版评分算出来的（有的没有「打折后」一栏）：综合分不能直接比。'));
  }
  return root;
}

function summaryRow(row) {
  const tr = h('tr');
  tr.append(h('th', { scope: 'row' }, row.label));
  row.cells.forEach((value, i) => {
    const td = h('td');
    td.append(h('span', { className: 'num' }, cellText(row.key, value)));
    if (row.bar && value !== null) td.append(valueBar(value, i));
    tr.append(td);
  });
  return tr;
}

function cellText(key, value) {
  if (value === null || value === undefined) return '—';
  if (key === 'usd') return usdText(value);
  if (key === 'decisions' || key === 'frames' || key === 'calls') return countText(value);
  return scoreText(value);
}

function textRow(label, values) {
  const tr = h('tr');
  tr.append(h('th', { scope: 'row' }, label));
  for (const v of values) tr.append(h('td', {}, v));
  return tr;
}

/**
 * Which colour and letter is which profile.
 * @param {import('./profile.js').Profile[]} profiles
 * @param {string[]} labels
 */
export function legend(profiles, labels) {
  const box = h('div', { className: 'rpt-legend' });
  profiles.forEach((p, i) => {
    const item = h('span', { className: 'rpt-legend-item' });
    item.append(badge(i, LETTERS[i]), h('span', {}, ` ${labels[i]} · ${playerText(p)}`));
    box.append(item);
  });
  return box;
}
