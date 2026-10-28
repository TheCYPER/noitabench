/** Short texts for the report. Pure functions, no DOM. Scores are shown on a 0 to 100 scale. */

import { endingName } from './names.js';

/** @param {number|null|undefined} v */
const finite = (v) => typeof v === 'number' && Number.isFinite(v);

/**
 * A score on the 0..100 scale: whole numbers stay whole, others get one decimal. `—` when there is none.
 * @param {number|null|undefined} v
 */
export function scoreText(v) {
  if (!finite(v)) return '—';
  const r = Math.round(v * 10) / 10;
  if (!finite(r)) return '—';
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

/**
 * A share of the composite (weight x part) with two decimals, as many as the profile's own numbers have: shown
 * with one decimal, two parts such as 19.7 and 10.8 add up to 30.5 beside a composite of 30.6.
 * @param {number|null|undefined} v
 */
export function shareText(v) {
  if (!finite(v)) return '—';
  const r = Math.round(v * 100) / 100;
  return finite(r) ? String(r) : '—';
}

/**
 * A 0..1 value times 100, with the decimal point moved in the number's own digits (`0.0295` -> `2.95`), not by
 * a float multiplication that gives `2.9499999999999997` and rounds the tie the wrong way.
 * @param {number} v
 */
export function percent(v) {
  const s = String(v);
  return s.includes('e') ? v * 100 : Number(`${s}e2`);
}

/**
 * A value of the 0..1 kind (an encounter's score, a metric's value) on the 0..100 scale.
 * @param {number|null|undefined} v
 */
export const unitText = (v) => scoreText(finite(v) ? percent(v) : null);

/**
 * Dollars: four decimals below one dollar, two above.
 * @param {number|null|undefined} v
 */
export function usdText(v) {
  if (!finite(v)) return '—';
  return `$${v.toFixed(Math.abs(v) < 1 ? 4 : 2)}`;
}

/** @param {number|null|undefined} v */
export const countText = (v) => (finite(v) ? v.toLocaleString('en-US') : '—');

/**
 * Game time: the recording runs at 60 frames a second.
 * @param {number|null|undefined} frames
 */
export function gameTimeText(frames) {
  if (!finite(frames)) return '—';
  const s = frames / 60;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} 分 ${Math.round(s - m * 60)} 秒`;
}

/**
 * Pieces of the "how it ended" line, from the profile's outcome and depth.
 * @param {import('./profile.js').Profile} p
 * @returns {string[]}
 */
export function outcomeParts(p) {
  const parts = [];
  if (p.depth.reachedSealedRoom) parts.push('到达封印室');
  const { over, died, frames } = p.outcome;
  if (died || over === 'dead') parts.push('死亡');
  else if (over) parts.push(endingName(over) ?? `结束（${over}）`);
  // a profile without an `outcome` says nothing about the ending: "no death" would be a claim it never made
  if (parts.length === 0) parts.push(frames === null ? '—' : '录像结束，没有死亡');
  return parts;
}

/** @param {import('./profile.js').Profile} p */
export const outcomeText = (p) => outcomeParts(p).join(' · ');

/**
 * Splits an evaluator reason such as `crossed: +0.25 of 0.25 (reached the far ledge)` into the criterion, the
 * points earned and possible (as 0..100) and the detail. `not measured` and anything else come back as a
 * plain `detail`, so an unknown wording is shown untouched.
 * @param {string} text
 * @returns {{criterion:string, earned:number|null, max:number|null, detail:string, raw:string}}
 */
export function parseReason(text) {
  const raw = String(text);
  const points = /^([\w.-]+): ([+-]?\d+(?:\.\d+)?) of (\d+(?:\.\d+)?)(?: \((.*)\))?$/s.exec(raw);
  if (points) {
    return { criterion: points[1], earned: percent(Number(points[2])), max: percent(Number(points[3])), detail: points[4] ?? '', raw };
  }
  const unmeasured = /^([\w.-]+): not measured(?: \((.*)\))?$/s.exec(raw);
  if (unmeasured) return { criterion: unmeasured[1], earned: null, max: null, detail: `未测：${unmeasured[2] ?? ''}`.replace(/：$/, ''), raw };
  return { criterion: '', earned: null, max: null, detail: raw, raw };
}

/**
 * Cuts a snippet around the phrase that matched, so a page can mark the phrase without parsing markup.
 * @param {string} snippet
 * @param {string} phrase
 * @returns {{before:string, match:string, after:string}}
 */
export function splitSnippet(snippet, phrase) {
  const i = phrase ? snippet.toLowerCase().indexOf(phrase.toLowerCase()) : -1;
  if (i < 0) return { before: snippet, match: '', after: '' };
  return { before: snippet.slice(0, i), match: snippet.slice(i, i + phrase.length), after: snippet.slice(i + phrase.length) };
}

/**
 * The text that stands for one bar, for screen readers and for tests. `opportunities: null` = a plain value
 * (the composite, a metric) that has no opportunity count to read out.
 * @param {{present:boolean, score:number|null, discounted:number|null, opportunities:number|null, thin:boolean}} s
 */
export function barLabel(s) {
  if (!s.present) return '没有数据';
  if (s.score === null) return s.opportunities === null ? '没有数据' : '没有遇到';
  const value = s.discounted !== null ? `${scoreText(s.score)}，打折后 ${scoreText(s.discounted)}` : scoreText(s.score);
  const chances = s.opportunities === null ? '' : `，机会 ${s.opportunities} 次`;
  return `${value}${chances}${s.thin ? '，覆盖不足' : ''}`;
}

/**
 * A capability's own `note` from the evaluator says what the bar and the chip already say ("no encounter met and
 * no metric measured", "coverage too low (1 opportunities, need 2)"); anything else is worth showing.
 * @param {string} note
 */
export function isRoutineNote(note) {
  return /^(no encounter met and no metric measured|no combined scene met and no metric measured|coverage too low \()/.test(note);
}

/**
 * The evaluator's warning about a composite, in Chinese when it is one of the two it writes; any other wording
 * (a newer evaluator) is shown as it is.
 * @param {string} note
 */
export function compositeNoteText(note) {
  const thin = /^thin: only (\d+) of (\d+) capabilities were covered/.exec(note);
  if (thin) return `只有 ${thin[1]} / ${thin[2]} 项能力有 2 次以上的机会；其余的按打折计入，所以这个综合分不能直接和覆盖更全的局比。`;
  if (/^no capability was scored/.test(note)) return '没有任何一项能力得到分数：能力分按 0 计，综合分只剩深度分的 20%。';
  return note;
}
