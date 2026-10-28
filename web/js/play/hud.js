/**
 * Turning an answer (contracts section 15) into the lines and numbers the HUD shows. Pure
 * functions over the answer; the DOM is built elsewhere. Everything shown is something an
 * agent is told too: the page adds no information.
 */

const pct = (v) => Math.round(Math.max(0, Math.min(1, v)) * 100);
const num = (v) => (Number.isInteger(v) ? String(v) : String(Math.round(v * 10) / 10));

/** @param {any} state  answer.observation.state */
export function vitals(state) {
  return {
    hp: { value: state.hp, max: state.hp_max, pct: state.hp_max > 0 ? pct(state.hp / state.hp_max) : 0 },
    levitation: pct(state.levitation),
    breath: pct(state.breath),
    position: `x=${state.position.x} y=${state.position.y}`,
    ground: state.on_ground ? '在地面' : '在空中',
    facing: state.facing === 'left' ? '朝左' : '朝右',
    aim: aimText(state.aim),
    statuses: Object.entries(state.statuses ?? {}).map(([name, seconds]) => ({ name, seconds, text: `${name} ${num(seconds)}s` })),
  };
}

export function aimText(aim) {
  const base = `${num(aim.degrees)}°`;
  return aim.follows === null || aim.follows === undefined ? base : `${base}（跟着 #${aim.follows}）`;
}

/** @param {any} state */
export function wandRows(state) {
  return state.wands.map((w) => ({
    index: w.index,
    active: Boolean(w.active),
    manaText: `${num(w.mana)}/${num(w.mana_max)}`,
    manaPct: w.mana_max > 0 ? pct(w.mana / w.mana_max) : 0,
    statsText: `施法间隔 ${w.cast_delay} 充能 ${w.recharge} 每次 ${w.spells_per_cast} 个 容量 ${w.capacity}${w.shuffle ? ' 乱序' : ''}`,
    cooldown: w.cooldown,
    slots: w.slots.map((s) => ({
      slot: s.slot,
      spell: s.spell,
      text: s.spell ? `${s.spell}${s.uses === null || s.uses === undefined ? '' : ` ×${s.uses}`}` : '（空）',
    })),
  }));
}

/** @param {any} state */
export function bottleRows(state) {
  return state.bottles.map((b) => ({
    index: b.index,
    active: Boolean(b.active),
    amount: b.amount,
    capacity: b.capacity,
    text: b.contents.length ? b.contents.map((c) => `${c.material} ${c.amount}`).join('，') : '空',
  }));
}

/** @param {any} state */
export function spellRows(state) {
  return state.spells.map((s) => ({
    index: s.index,
    spell: s.spell,
    text: `${s.spell}${s.uses === null || s.uses === undefined ? '' : ` ×${s.uses}`}`,
  }));
}

/** "第 12 步 · 还剩 988 · 上一步花了 1" */
export function budgetLine(answer, cost) {
  const last = cost === undefined || cost === null ? '' : ` · 上一步花了 ${cost}`;
  return `第 ${answer.decision} 个决策 · 还剩 ${answer.decisions_left}${last}`;
}

/** "interrupted (damage) after 3 tick(s), 30 frames" */
export function stopText(stop) {
  const detail = stop.detail ? ` (${stop.detail})` : '';
  const also = stop.also?.length ? `，同时 ${stop.also.join('、')}` : '';
  const run = stop.frames ? ` · ${stop.ticks} tick，${stop.frames} 帧` : '';
  const msg = stop.message ? ` — ${stop.message}` : '';
  return `${stop.reason}${detail}${also}${run}${msg}`;
}

/** One line per command of the last decision. */
export function resultRows(answer) {
  return answer.results.map((r) => {
    if (!r.ok) return { ok: false, text: `${r.command}：失败（${r.code}）${r.message}` };
    const stop = r.stop ? `${r.stop.reason}${r.stop.detail ? ` (${r.stop.detail})` : ''}` : '';
    const result = r.result === undefined ? '' : ` ${JSON.stringify(r.result)}`;
    return { ok: true, text: `${r.command}：${stop}${result}`.trim() };
  });
}

/** @param {any} answer */
export function eventRows(answer) {
  const rows = answer.events.map((e) => `tick ${e.tick}：${e.text}`);
  if (answer.events_omitted) rows.push(`…还有 ${answer.events_omitted} 条没有显示`);
  return rows;
}

/**
 * The newest successful `inspect` result of an answer, or null.
 * @returns {{command:string, result:any}|null}
 */
export function latestInspect(answer) {
  for (let i = answer.results.length - 1; i >= 0; i--) {
    const r = answer.results[i];
    if (r.ok && r.command === 'inspect' && r.result !== undefined) return { command: r.command, result: r.result };
  }
  return null;
}

/** Why the episode ended, for the banner; null while it goes on. */
export function overText(answer) {
  if (!answer.over) return null;
  const why = { dead: '你死了', decision_limit: '决策次数用完了' }[answer.over] ?? answer.over;
  return `本局结束：${why}。`;
}

/**
 * The banner under the picture. While the episode runs: nothing. When it is over (death, no
 * decisions left) or closed: why, and whether the recording was saved. The server closes the
 * session by itself when the episode is over, so both usually arrive together.
 * @param {any} answer
 * @param {boolean} closed
 * @param {boolean} recorded
 * @returns {string}
 */
export function endBanner(answer, closed, recorded) {
  const why = overText(answer);
  if (!why && !closed) return '';
  return `${why ?? '这一局已经结束。'}${closed && recorded ? '录像已保存。' : ''}`;
}

/**
 * `move(direction, [until])`-style signature of a command from /api/hello, for the help list.
 * @param {{name:string, arguments:{name:string, required:boolean}[]}} c
 */
export function commandSignature(c) {
  const args = c.arguments.map((a) => (a.required ? a.name : `[${a.name}]`));
  return `${c.name}(${args.join(', ')})`;
}
