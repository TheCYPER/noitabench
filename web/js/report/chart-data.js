/**
 * Turns parsed profiles into the tables the report draws. Pure functions, no DOM: one place decides how
 * several profiles line up (the same capability, encounter or metric in the same row), and a profile that lacks
 * something gets a marked gap instead of a wrong number.
 */

import { encounterName, metricName, orderedCapabilityKeys, sourceName } from './names.js';

export const MAX_PROFILES = 4;
/** A capability needs at least this many opportunities to count as covered (capability-graph.md section 5). */
export const MIN_OPPORTUNITIES = 2;
/** Series letters of the comparison view. */
export const LETTERS = ['A', 'B', 'C', 'D'];

/**
 * One label per profile, unique within the set (`run-1`, `run-1 #2`).
 * @param {import('./profile.js').Profile[]} profiles
 * @returns {string[]}
 */
export function uniqueLabels(profiles) {
  const seen = new Map();
  return profiles.map((p) => {
    const base = p.runId || p.file;
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base} #${n}`;
  });
}

/**
 * Who played: the model's name, `人类` or `脚本 bot`.
 * @param {import('./profile.js').Profile} p
 */
export function playerText(p) {
  if (p.source === 'agent' && p.model?.model) return p.model.model;
  return sourceName(p.source);
}

/**
 * @typedef {{
 *   present: boolean, score: number|null, discounted: number|null, discount: number|null,
 *   opportunities: number, thin: boolean, note: string,
 * }} CapabilityCell
 */

/**
 * One row per capability, one cell per profile.
 * @param {import('./profile.js').Profile[]} profiles
 * @returns {{key:string, cells:CapabilityCell[]}[]}
 */
export function capabilityRows(profiles) {
  const keys = orderedCapabilityKeys(profiles.flatMap((p) => [...p.capabilities.keys()]));
  return keys.map((key) => ({ key, cells: profiles.map((p) => capabilityCell(p.capabilities.get(key))) }));
}

/**
 * @param {import('./profile.js').Capability|undefined} c
 * @returns {CapabilityCell}
 */
function capabilityCell(c) {
  if (!c) return { present: false, score: null, discounted: null, discount: null, opportunities: 0, thin: false, note: '' };
  const thin = c.covered === null ? c.opportunities < MIN_OPPORTUNITIES : !c.covered;
  return {
    present: true, score: c.score, discounted: c.discounted, discount: c.discount,
    opportunities: c.opportunities, thin, note: c.note,
  };
}

/**
 * Capabilities with a score but too few opportunities, in chart order: the report marks them "覆盖不足".
 * @param {import('./profile.js').Profile} p
 */
export function thinCapabilities(p) {
  const rows = capabilityRows([p]);
  return rows.filter((r) => r.cells[0].present && r.cells[0].thin && r.cells[0].score !== null).map((r) => r.key);
}

/**
 * The headline table of the comparison: one row per figure, one cell per profile.
 * `value` feeds a bar (0..100) when the row has one.
 * @param {import('./profile.js').Profile[]} profiles
 */
export function summaryRows(profiles) {
  const each = (get) => profiles.map(get);
  return [
    { key: 'composite', label: '综合分', bar: true, cells: each((p) => p.composite) },
    { key: 'ability', label: '能力分（占 80%）', bar: true, cells: each((p) => p.ability) },
    { key: 'depth', label: '深度分（占 20%）', bar: true, cells: each((p) => p.depth.score) },
    { key: 'decisions', label: '决策数', bar: false, cells: each((p) => p.steps.decisions) },
    { key: 'frames', label: '游戏帧', bar: false, cells: each((p) => p.steps.frames ?? p.outcome.frames) },
    { key: 'usd', label: '花费（美元）', bar: false, cells: each((p) => p.cost?.usd ?? null) },
    { key: 'calls', label: '模型调用', bar: false, cells: each((p) => p.cost?.modelCalls ?? null) },
  ];
}

/**
 * @typedef {{
 *   status: 'absent'|'unmet'|'unscored'|'scored', placed: number, visits: number, scored: number,
 *   mean: number|null, best: number|null,
 * }} EncounterCell
 */

/**
 * One row per encounter any profile lists, one cell per profile. `absent` = the profile does not list that
 * encounter; `unmet` = placed in the world but never visited; `unscored` = visited but the rule gave no score.
 * @param {import('./profile.js').Profile[]} profiles
 * @returns {{id:string, name:string, nodes:string[], cells:EncounterCell[]}[]}
 */
export function encounterMatrix(profiles) {
  const ids = [...new Set(profiles.flatMap((p) => p.encounters.map((e) => e.id)))].sort(byEncounterId);
  return ids.map((id) => {
    const found = profiles.map((p) => p.encounters.find((e) => e.id === id));
    const first = found.find(Boolean);
    return {
      id,
      name: encounterName(id),
      nodes: first ? first.nodes : [],
      cells: found.map(encounterCell),
    };
  });
}

/** @param {import('./profile.js').Encounter|undefined} e @returns {EncounterCell} */
function encounterCell(e) {
  if (!e) return { status: 'absent', placed: 0, visits: 0, scored: 0, mean: null, best: null };
  const scores = e.visits.filter((v) => v.scored && v.score !== null).map((v) => v.score);
  const status = e.visits.length === 0 ? 'unmet' : scores.length === 0 ? 'unscored' : 'scored';
  return {
    status,
    placed: e.placed,
    visits: e.visits.length,
    scored: scores.length,
    mean: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null,
    best: scores.length ? Math.max(...scores) : null,
  };
}

/** E2 before E10: compare the number, not the text. */
const byEncounterId = (a, b) => (Number(a.slice(1)) || 0) - (Number(b.slice(1)) || 0) || a.localeCompare(b);

/**
 * @typedef {{ present: boolean, status: string, value: number|null, reason: string, opportunities: number|null }} MetricCell
 */

/**
 * One row per metric any profile lists, in the order the first profile lists them.
 * @param {import('./profile.js').Profile[]} profiles
 * @returns {{name:string, label:string, capabilities:string[], cells:MetricCell[]}[]}
 */
export function metricMatrix(profiles) {
  const names = [];
  for (const p of profiles) for (const m of p.metrics) if (!names.includes(m.name)) names.push(m.name);
  return names.map((name) => {
    const found = profiles.map((p) => p.metrics.find((m) => m.name === name));
    const first = found.find(Boolean);
    return {
      name,
      label: metricName(name),
      capabilities: first ? first.capabilities : [],
      cells: found.map((m) => (m
        ? { present: true, status: m.status, value: m.value, reason: m.reason, opportunities: m.opportunities }
        : { present: false, status: 'absent', value: null, reason: '', opportunities: null })),
    };
  });
}
