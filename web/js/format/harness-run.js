import { isNum, isObject } from './errors.js';

/**
 * Readers for the three optional files the harness writes next to a
 * recording (contracts.md section 17): transcript.jsonl, harness.jsonl and
 * summary.json. They are diagnostics, so nothing here throws: a line or a
 * field that does not fit is dropped.
 */

export const HARNESS_RUN_FORMAT = 'cogbench-harness-run/0';

/**
 * transcript.jsonl lines -> the records with a string `kind`, in file order
 * (the harness writes them in the order things happened).
 * @param {object[]} items
 * @returns {object[]}
 */
export function normalizeTranscript(items) {
  return items.filter((r) => typeof r.kind === 'string');
}

/**
 * harness.jsonl lines -> one row per model call, in file order. Rows without
 * a numeric `decision` are kept (they still cost something) but cannot be
 * placed on the timeline.
 * @param {object[]} items
 * @returns {object[]}
 */
export function normalizeHarness(items) {
  return items.filter((r) => isObject(r) && (isNum(r.call) || isNum(r.decision)));
}

const str = (v) => (typeof v === 'string' ? v : '');
const num = (v) => (isNum(v) ? v : null);

/**
 * The part of summary.json the replay pages show: who played and how it
 * ended. This is a whitelist on purpose: the file also holds the world and
 * rule seeds, which no replay page shows, so they are never copied out.
 *
 * @param {unknown} json
 * @returns {null | {
 *   model: string, provider: string, mode: string, layers: string[],
 *   over: string, detail: string, decisions: number|null, frames: number|null,
 *   modelCalls: number|null, costUsd: number|null, wallSeconds: number|null,
 *   helperCalls: number|null, helperCostUsd: number|null, maxUsd: number|null,
 * }}
 */
export function parseRunSummary(json) {
  if (!isObject(json) || !String(json.format).startsWith('cogbench-harness-run/')) return null;
  const model = isObject(json.model) ? json.model : {};
  const result = isObject(json.result) ? json.result : {};
  const helpers = isObject(json.helpers) ? json.helpers : {};
  const limits = isObject(json.limits) ? json.limits : {};
  return {
    model: str(model.model),
    provider: str(model.provider),
    mode: str(json.mode),
    layers: Array.isArray(json.layers) ? json.layers.filter((l) => typeof l === 'string') : [],
    over: str(result.over),
    detail: str(result.detail),
    decisions: num(result.decisions),
    frames: num(result.frames),
    modelCalls: num(result.model_calls),
    costUsd: num(result.cost_usd),
    wallSeconds: num(result.wall_seconds),
    helperCalls: num(helpers.model_calls),
    helperCostUsd: num(helpers.cost_usd),
    maxUsd: num(limits.max_usd),
  };
}
