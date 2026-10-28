/**
 * Cost so far, from harness.jsonl (one row per model call: `decision` is how
 * many decisions the player had made when the call started, `cumulative_usd`
 * the budget spent after it, helpers' calls have an `agent` field and share
 * the same budget). Pure functions, no DOM.
 */

const finite = (v) => (Number.isFinite(v) ? v : null);

/**
 * Index for fast lookups by decision number. One entry per distinct `decision`
 * value of the log, so a damaged row with a huge number costs nothing.
 * @param {object[]} rows  normalized harness.jsonl
 */
export function buildCostIndex(rows) {
  const placed = rows.filter((r) => Number.isInteger(r.decision) && r.decision >= 0);
  const order = placed.map((r, i) => ({ r, i })).sort((a, b) => a.r.decision - b.r.decision || a.i - b.i);
  /** @type {number[]} */ const keys = [];
  /** @type {{usd:number|null, calls:number, helperCalls:number}[]} the figures after every call made with at most `keys[i]` decisions behind it */
  const sums = [];
  let calls = 0;
  let helperCalls = 0;
  let usd = null;
  for (const { r } of order) {
    calls++;
    if (r.agent) helperCalls++;
    const c = finite(r.cumulative_usd);
    if (c !== null) usd = usd === null ? c : Math.max(usd, c);
    const sum = { usd, calls, helperCalls };
    if (keys.length && keys[keys.length - 1] === r.decision) sums[sums.length - 1] = sum;
    else { keys.push(r.decision); sums.push(sum); }
  }
  return { keys, sums, rows, byCall: indexCalls(rows) };
}

function indexCalls(rows) {
  const m = new Map();
  for (const r of rows) if (!r.agent && Number.isFinite(r.call)) m.set(r.call, r);
  return m;
}

/**
 * What had been spent when the player made decision number `n`: every model
 * call up to and including the one that produced the command of that
 * decision (the next call, made after it, is not counted).
 *
 * @param {ReturnType<typeof buildCostIndex>} index
 * @param {number} n  decision number (1-based)
 * @returns {{usd:number|null, calls:number, helperCalls:number}|null}  null if there is no cost log
 */
export function costAtDecision(index, n) {
  if (index.keys.length === 0) return null;
  const d = Math.max(0, n - 1);
  let lo = 0;
  let hi = index.keys.length - 1;
  let at = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (index.keys[mid] <= d) { at = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return at < 0 ? { usd: null, calls: 0, helperCalls: 0 } : index.sums[at];
}

/**
 * The row of one model call by the player (not a helper).
 * @param {ReturnType<typeof buildCostIndex>} index
 * @param {number} call
 */
export function rowOfCall(index, call) {
  const r = index.byCall.get(call);
  if (!r) return null;
  return {
    costUsd: finite(r.cost_usd), latency: finite(r.latency_s), model: typeof r.model === 'string' ? r.model : '',
    inputTokens: finite(r.input_tokens), cacheRead: finite(r.cache_read_tokens),
    cacheWrite: finite(r.cache_write_tokens), outputTokens: finite(r.output_tokens),
    thinkingTokens: finite(r.thinking_tokens), promptTokens: finite(r.prompt_tokens),
  };
}
