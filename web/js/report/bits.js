import { h } from '../ui/dom.js';
import { barLabel } from './format.js';

/** CSS class of series `i` (0-based); the colours are the `--r-s1` to `--r-s4` tokens. */
export const seriesClass = (i) => `series-${(i % 4) + 1}`;

/** A percentage width for a 0..100 score, clamped. @param {number} v */
export const widthOf = (v) => `${Math.max(0, Math.min(100, v))}%`;

/**
 * A small coloured badge with the series letter. The letter, not only the colour, tells the series apart.
 * @param {number} i
 * @param {string} letter
 */
export function badge(i, letter) {
  return h('span', { className: `badge ${seriesClass(i)}`, title: `序列 ${letter}` }, letter);
}

/** @param {string} text @param {string} [kind] extra class, for example `thin` */
export function chip(text, kind = '') {
  return h('span', { className: `chip ${kind}`.trim() }, text);
}

/**
 * A horizontal 0..100 bar. With a discounted score the pale bar is the raw score and the solid one the
 * discounted score; without one the solid bar is the score. A thin capability's raw bar is hatched, so
 * "covered by too few opportunities" does not depend on colour. An empty track means no score.
 *
 * @param {{present:boolean, score:number|null, discounted:number|null, opportunities:number|null, thin:boolean}} cell
 * @param {number} series  0-based series index (colour)
 */
export function scoreBar(cell, series) {
  const el = h('div', { className: `bar ${seriesClass(series)}` });
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', barLabel(cell));
  if (!cell.present || cell.score === null) {
    el.className += ' empty';
    return el;
  }
  if (cell.discounted !== null) {
    const raw = h('div', { className: `bar-raw${cell.thin ? ' hatch' : ''}` });
    raw.style.width = widthOf(cell.score);
    const fill = h('div', { className: 'bar-fill' });
    fill.style.width = widthOf(cell.discounted);
    el.append(raw, fill);
  } else {
    const fill = h('div', { className: `bar-fill${cell.thin ? ' hatch' : ''}` });
    fill.style.width = widthOf(cell.score);
    el.append(fill);
  }
  return el;
}

/**
 * A plain bar for one number on a 0..100 scale (the parts of the composite, an encounter or metric value).
 * @param {number|null} value
 * @param {number} series
 */
export function valueBar(value, series) {
  return scoreBar({ present: true, score: value, discounted: null, opportunities: null, thin: false }, series);
}

/**
 * A `dl`-style pair for the stat lists.
 * @param {HTMLElement} dl
 * @param {string} term
 * @param {string|HTMLElement} value
 */
export function addStat(dl, term, value) {
  dl.append(h('dt', {}, term), typeof value === 'string' ? h('dd', {}, value) : wrap('dd', value));
}

function wrap(tag, child) {
  const el = h(tag);
  el.append(child);
  return el;
}

/**
 * A `<details>` with a summary line.
 * @param {string} summary
 * @param {string} [className]
 * @param {boolean} [open]
 */
export function details(summary, className = '', open = false) {
  const el = h('details', { className, open });
  el.append(h('summary', {}, summary));
  return el;
}
