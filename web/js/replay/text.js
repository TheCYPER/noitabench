/**
 * Short texts for the decision panel. Pure functions, no DOM.
 */

/**
 * Dollars: four decimals below one dollar (the cost of one move is tiny), two above.
 * @param {number|null|undefined} v
 */
export function usdText(v) {
  if (!Number.isFinite(v)) return '—';
  return `$${v.toFixed(Math.abs(v) < 1 ? 4 : 2)}`;
}

/**
 * Plain count with thousands separators, `—` when missing.
 * @param {number|null|undefined} v
 */
export function countText(v) {
  return Number.isFinite(v) ? v.toLocaleString('en-US') : '—';
}

/**
 * What a command did, from the `result` object of decisions.jsonl:
 * `completed (reached) · 2 tick · 20 帧`, or `invalid not_in_view: aim: no 51 is in view.`
 * @param {object|null} r
 */
export function resultText(r) {
  if (!r || typeof r !== 'object') return '';
  const head = [r.reason, r.detail ? `(${r.detail})` : '', r.code ?? ''].filter(Boolean).join(' ');
  const time = Number.isFinite(r.ticks) || Number.isFinite(r.frames)
    ? `${Number.isFinite(r.ticks) ? `${r.ticks} tick` : ''}${Number.isFinite(r.ticks) && Number.isFinite(r.frames) ? ' · ' : ''}${Number.isFinite(r.frames) ? `${r.frames} 帧` : ''}`
    : '';
  const message = typeof r.message === 'string' && r.message ? r.message : '';
  return [head, time, message].filter(Boolean).join(' · ');
}

/**
 * `completed (reached)`: the stop reason the player was shown with a decision.
 * @param {{stopReason:string, stopDetail:string}} m
 */
export function stopText(m) {
  return m.stopReason ? `${m.stopReason}${m.stopDetail ? ` (${m.stopDetail})` : ''}` : '—';
}

/**
 * One line about a program or hook run: `run_code · 35 条指令 · 35 步 · 0.5 s`.
 * @param {{label:string, ok:boolean, commands:number|null, steps:number|null, seconds:number|null, limit:any, ended:any, error:string}} p
 */
export function programText(p) {
  const parts = [p.label || 'program'];
  if (p.commands !== null) parts.push(`${p.commands} 条指令`);
  if (p.steps !== null) parts.push(`${p.steps} 步`);
  if (p.seconds !== null) parts.push(`${p.seconds} s`);
  if (!p.ok) parts.push('失败');
  if (p.limit) parts.push(`触到上限：${p.limit}`);
  if (p.ended) parts.push(`游戏结束：${p.ended}`);
  return parts.join(' · ');
}

/**
 * The line about the model call that made a turn: `$0.0004 · 3.8 s · 输出 330 token`.
 * @param {ReturnType<typeof import('./costs.js').rowOfCall>} row
 */
export function callText(row) {
  if (!row) return '';
  const parts = [usdText(row.costUsd)];
  if (row.latency !== null) parts.push(`${row.latency} s`);
  if (row.outputTokens !== null) parts.push(`输出 ${countText(row.outputTokens)} token`);
  if (row.promptTokens !== null) parts.push(`上下文 ${countText(row.promptTokens)}`);
  return parts.join(' · ');
}

/**
 * The line about the whole run from summary.json.
 * @param {NonNullable<ReturnType<typeof import('../format/harness-run.js').parseRunSummary>>} s
 */
export function summaryText(s) {
  const parts = [];
  if (s.model) parts.push(s.model);
  if (s.over) parts.push(`结束：${s.over}${s.detail ? `（${s.detail}）` : ''}`);
  if (s.decisions !== null) parts.push(`${countText(s.decisions)} 个决策`);
  if (s.modelCalls !== null) parts.push(`${countText(s.modelCalls)} 次调用`);
  if (s.costUsd !== null) parts.push(usdText(s.costUsd));
  return parts.join(' · ');
}
