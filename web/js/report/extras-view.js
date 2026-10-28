import { h } from '../ui/dom.js';
import { LETTERS } from './chart-data.js';
import { badge, chip, details } from './bits.js';
import { countText, splitSnippet } from './format.js';
import { capabilityName, capabilityShort, encounterName, own } from './names.js';

const CATEGORIES = { test: '把游戏当成测试', design: '提到设计者或预期解法', level: '提到关卡或谜题' };
const FIELDS = { text: '回复', thinking: '思考摘要', tool_call: '工具参数', briefing: '摘要' };
const OVERS = { died: '死亡', ended: '录像结束时还没通过' };

/**
 * The spot-check of the model's own words (AC13). A counted aid for a person, not a score.
 * @param {import('./profile.js').Profile[]} profiles
 * @param {string[]} labels
 */
export function renderAwareness(profiles, labels) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '「这是测试」自查'));
  root.append(h('p', { className: 'rpt-muted' }, '在模型自己写的文字里数「这是个测试 / 基准 / 评测」「设计者」「关卡」这类说法。只是供人抽查的计数，不计入任何分数。'));
  profiles.forEach((p, i) => root.append(awarenessBlock(p, labels[i], profiles.length > 1 ? i : -1)));
  return root;
}

function awarenessBlock(p, label, series) {
  const box = h('div', { className: 'aware' });
  const head = h('div', { className: 'aware-head' });
  if (series >= 0) head.append(badge(series, LETTERS[series]), ' ');
  head.append(h('b', {}, label));
  box.append(head);
  const a = p.awareness;
  if (!a) {
    box.append(h('p', { className: 'rpt-muted' }, '没有可查的模型文字（不是模型局，或缺少 transcript.jsonl）。'));
    return box;
  }
  const cats = Object.entries(a.byCategory).map(([k, n]) => `${own(CATEGORIES, k) ?? k} ${n}`).join(' · ');
  box.append(h('p', {}, `命中 ${countText(a.hits)} 处${a.checked !== null ? `，查了 ${countText(a.checked)} 段模型文字` : ''}${cats ? `：${cats}` : ''}`));
  if (a.snippets.length > 0) {
    const d = details(`查看片段（${a.snippets.length}）`, 'snippets');
    for (const s of a.snippets) d.append(snippetBlock(s));
    box.append(d);
  }
  return box;
}

function snippetBlock(s) {
  const p = h('p', { className: 'snippet' });
  p.append(chip(own(CATEGORIES, s.category) ?? s.category), chip(own(FIELDS, s.field) ?? s.field), ' ');
  const { before, match, after } = splitSnippet(s.snippet, s.phrase);
  p.append(before);
  if (match) p.append(h('mark', {}, match));
  p.append(after);
  return p;
}

/**
 * Failures traced to a basic node, and the evaluator's own notes.
 * @param {import('./profile.js').Profile} p
 */
export function renderNotes(p) {
  const root = h('section', { className: 'panel' });
  root.append(h('h2', {}, '失败归因与评分说明'));
  if (p.attribution.length === 0) root.append(h('p', { className: 'rpt-muted' }, '没有需要归因的失败（每一层都通过了，或封印已打开）。'));
  else {
    const ul = h('ul', { className: 'plain' });
    for (const a of p.attribution) ul.append(h('li', {}, attributionText(a)));
    root.append(ul);
  }
  if (p.notes.length > 0) {
    const d = details(`评分说明（${p.notes.length}）`, 'notes');
    const ul = h('ul', { className: 'plain' });
    for (const n of p.notes) ul.append(h('li', {}, n));
    d.append(ul);
    root.append(d);
  }
  return root;
}

/**
 * One attribution entry as a sentence. Only the fields the evaluator writes (`attribution.py`) are shown:
 * anything else in the entry is ignored, so a field a newer evaluator adds (a position, a seed, a variant)
 * cannot reach the page by accident.
 * @param {Record<string, any>} a
 */
export function attributionText(a) {
  const bits = [];
  if (typeof a.capability === 'string') bits.push(`${a.capability} ${capabilityName(a.capability)}`);
  if (Number.isFinite(a.layer)) bits.push(`第 ${a.layer} 层`);
  if (typeof a.outcome === 'string') bits.push(own(OVERS, a.outcome) ?? a.outcome);
  if (Number.isFinite(a.frame)) bits.push(`帧 ${a.frame}`);
  const harm = a.last_harm && typeof a.last_harm === 'object' ? a.last_harm : null;
  if (harm) bits.push(`最后一次受伤：${[harm.kind, harm.source].filter((x) => typeof x === 'string').join(' / ') || '来源不明'}${Number.isFinite(harm.frame) ? `（帧 ${harm.frame}）` : ''}`);
  if (typeof a.encounter === 'string') {
    const nodes = Array.isArray(a.nodes) ? a.nodes.filter((n) => typeof n === 'string').map(capabilityShort).join('、') : '';
    bits.push(`所在遭遇点 ${a.encounter} ${encounterName(a.encounter)}${nodes ? `（${nodes}）` : ''}`);
  }
  if (typeof a.reason === 'string') bits.push(`原因：${a.reason}`);
  return bits.join(' · ');
}
