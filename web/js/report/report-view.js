import { h } from '../ui/dom.js';
import { LETTERS, uniqueLabels } from './chart-data.js';
import { renderCapabilities } from './capability-view.js';
import { renderEncounterMatrix, renderEncounters } from './encounter-view.js';
import { renderAwareness, renderNotes } from './extras-view.js';
import { renderMetricMatrix, renderMetrics } from './metric-view.js';
import { badge, details } from './bits.js';
import { renderSummary } from './summary-view.js';

/**
 * Every section of the report for the profiles on the page: the full detail of one profile, or the side-by-side
 * comparison of 2 to 4 with each profile's own detail folded away at the end.
 *
 * @param {import('./profile.js').Profile[]} profiles
 * @returns {HTMLElement[]}
 */
export function renderReport(profiles) {
  const labels = uniqueLabels(profiles);
  if (profiles.length === 1) {
    const [p] = profiles;
    return [
      renderSummary(profiles, labels),
      renderCapabilities(profiles, labels),
      renderEncounters(p),
      renderMetrics(p),
      renderNotes(p),
      renderAwareness(profiles, labels),
    ];
  }
  const out = [
    renderSummary(profiles, labels),
    renderCapabilities(profiles, labels),
    renderEncounterMatrix(profiles, labels),
    renderMetricMatrix(profiles, labels),
    renderAwareness(profiles, labels),
  ];
  const each = h('section', { className: 'panel' });
  each.append(h('h2', {}, '每一局的明细'));
  profiles.forEach((p, i) => {
    const d = details('', 'run-detail');
    const summary = d.firstChild;
    summary.append(badge(i, LETTERS[i]), ' ', h('span', {}, labels[i]));
    d.append(renderEncounters(p), renderMetrics(p), renderNotes(p));
    each.append(d);
  });
  out.push(each);
  return out;
}
