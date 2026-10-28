import { clear, h } from '../ui/dom.js';
import { stopStyle } from './timeline.js';
import { callText, countText, programText, resultText, usdText } from './text.js';

/**
 * Lays out the view model of one decision (model.js `detailFor`) in a box.
 * Everything goes in as text, never as HTML. No game logic here.
 */

const NO_TRANSCRIPT = '这个录像没有 transcript.jsonl：没有保存玩家当时看到的文字，只有指令和停下的原因（画面在左边的图里）。';

/** A <details> with a summary line; `open` decides the first state. */
function section(title, open, ...children) {
  const d = h('details', { className: 'dp-sec', open });
  d.append(h('summary', {}, title), ...children);
  return d;
}

const MAX_SHOWN_OUTPUT = 4000;
/** A long print-out is cut for the panel; the whole text is in "工具的返回". */
const clip = (text) => (text.length > MAX_SHOWN_OUTPUT ? `${text.slice(0, MAX_SHOWN_OUTPUT)}\n…（共 ${countText(text.length)} 字，完整内容在“工具的返回”里）` : text);

const pre = (text, cls = '') => h('pre', { className: `dp-pre ${cls}`.trim() }, text);
const line = (text, cls = '') => h('div', { className: `dp-line ${cls}`.trim() }, text);

/**
 * @param {HTMLElement} box
 * @param {ReturnType<typeof import('./model.js').detailFor>|null} d
 * @param {{compact?:boolean}} [opts]  compact = the compare page's small panel (no cost line, fewer open sections)
 */
export function renderDecision(box, d, opts = {}) {
  clear(box);
  if (!d) {
    box.append(line('还没有决策', 'empty'));
    return;
  }
  box.append(...[
    head(d),
    d.hasTranscript ? null : line(NO_TRANSCRIPT, 'empty'),
    opts.compact ? null : costLine(d),
    d.briefing ? briefing(d.briefing) : null,
    observation(d, opts),
    commands(d),
  ].filter(Boolean));
  if (d.turn) box.append(...turnSections(d, opts));
  if (d.end) box.append(line(`游戏结束：${d.end.over}${d.end.detail ? `（${d.end.detail}）` : ''}`, 'dp-end'));
}

function head(d) {
  const m = d.mark;
  const wrap = h('div', { className: 'dp-head' });
  const style = stopStyle(m.stopReason);
  const tag = h('span', { className: 'dp-tag' }, m.stopReason || 'start');
  tag.style.background = style.color;
  // #N is the number the player saw; it runs ahead of the count of lines once an `inspect` has cost extra
  const of = m.view === m.pos + 1 ? ` / ${d.total}` : ` · 第 ${m.pos + 1}/${d.total} 个`;
  wrap.append(
    h('strong', {}, `决策 #${m.view}`),
    h('span', { className: 'mono' }, `${of} · 帧 ${m.frame}${m.frames ? ` → ${m.endFrame}（+${m.frames}）` : ''} `),
    tag,
  );
  if (m.stopDetail) wrap.append(h('span', { className: 'dp-detail mono' }, ` ${m.stopDetail}`));
  if (m.died) wrap.append(h('span', { className: 'dp-flag dp-dead' }, '死亡'));
  if (!m.ok) wrap.append(h('span', { className: 'dp-flag dp-bad' }, '指令有误'));
  if (m.briefing) wrap.append(h('span', { className: 'dp-flag dp-brief' }, '新简报'));
  return wrap;
}

function costLine(d) {
  if (!d.cost && !d.call) return null;
  const parts = [];
  if (d.cost) {
    parts.push(`累计 ${usdText(d.cost.usd)}`, `${countText(d.cost.calls)} 次模型调用`);
    if (d.cost.helperCalls) parts.push(`其中帮手 ${d.cost.helperCalls} 次`);
  }
  const call = callText(d.call);
  if (call) parts.push(`这一轮 ${call}`);
  return line(parts.join(' · '), 'dp-cost');
}

function briefing(b) {
  return section('新一段对话从这份简报开始（模型自己写的）', false, pre(b.text));
}

function observation(d, opts) {
  const v = d.observation;
  if (v) {
    const title = v.complete ? '玩家看到的画面' : '玩家看到的画面（程序打印的片段，不完整）';
    return section(title, v.complete && !opts.compact, pre(v.text, 'dp-obs'));
  }
  if (!d.hasTranscript) return null;
  return line('这一步的画面没有记录（它是程序中间的一步，程序只打印了一部分）。', 'empty');
}

function commands(d) {
  const m = d.mark;
  const wrap = h('div', { className: 'dp-block' });
  wrap.append(h('h3', {}, '玩家的指令'));
  if (m.commands.length === 0) wrap.append(line('（没有指令）', 'empty'));
  const list = h('ol', { className: 'dp-cmds mono' });
  for (const c of m.commands) list.append(h('li', {}, c));
  wrap.append(list);
  const result = resultText(m.result);
  if (result) wrap.append(line(`结果：${result}`, `mono ${m.ok ? '' : 'dp-bad-text'}`));
  if (m.cost !== null && m.cost !== 1) wrap.append(line(`算 ${m.cost} 次决策`, 'mono'));
  return wrap;
}

function turnSections(d, opts) {
  const t = d.turn;
  const out = [];
  const where = d.inTurn && d.inTurn.count > 1 ? `（程序的第 ${d.inTurn.k}/${d.inTurn.count} 步）` : '';
  const model = h('div', { className: 'dp-model' });
  if (t.thinking.trim()) model.append(section('思考摘要', false, pre(t.thinking)));
  if (t.text.trim()) model.append(pre(t.text, 'dp-text'));
  model.append(...t.toolCalls.map(toolCall));
  if (!t.thinking.trim() && !t.text.trim() && t.toolCalls.length === 0) model.append(line('（这一轮什么也没说）', 'empty'));
  out.push(section(`模型这一轮${where}`, !opts.compact, model));
  if (t.notes.length) out.push(section('框架的提示', false, ...t.notes.map((n) => line(n))));
  if (t.programs.length) out.push(programs(t));
  if (t.installs.length) out.push(section('安装库', false, ...t.installs.map((i) => line(`${i.name}：${i.ok ? '成功' : '失败'} ${i.detail}`, 'mono'))));
  if (t.helpers.length) out.push(helpers(t, opts));
  if (t.results?.length) out.push(section('工具的返回', false, ...t.results.map(toolResult)));
  return out;
}

function toolCall(tc) {
  const wrap = h('div', { className: 'dp-call' });
  wrap.append(h('code', {}, tc.text));
  if (tc.code !== null) wrap.append(section('程序', false, pre(tc.code, 'dp-code')));
  return wrap;
}

function toolResult(r) {
  const wrap = h('div', { className: 'dp-result' });
  wrap.append(h('div', { className: `dp-rname mono ${r.isError ? 'dp-bad-text' : ''}` }, `${r.name || '回复'}${r.isError ? '（出错）' : ''}`), pre(r.content));
  return wrap;
}

function programs(t) {
  const items = t.programs.map((p) => {
    const row = h('div', { className: `dp-program ${p.ok ? '' : 'dp-bad-text'}` });
    row.append(line(programText(p), 'mono'));
    if (p.error) row.append(pre(p.error));
    if (p.output) row.append(section('它打印的内容', false, pre(clip(p.output))));
    return row;
  });
  return section(`程序和钩子（${t.programs.length}）`, false, ...items);
}

function helpers(t, opts) {
  const items = t.helpers.map((hp) => {
    const box = h('div', { className: 'dp-helper' });
    const kind = hp.kind === 'fork' ? '分身' : '帮手';
    box.append(h('strong', {}, `${kind} ${hp.id}`), h('span', { className: 'mono' }, `  上级 ${hp.parent || '玩家'} · 第 ${hp.depth} 层`));
    for (const e of hp.events) box.append(line(`${eventName(e.event)}：${e.text}${e.state ? `（${e.state}）` : ''}`, 'dp-hevent'));
    const turns = hp.turns.map((ht, i) => section(`它的第 ${i + 1} 轮`, false, ...helperTurn(ht)));
    if (turns.length) box.append(section(`它自己的几轮（${turns.length}）`, false, ...turns));
    return box;
  });
  return section(`帮手（${t.helpers.length}）`, !opts.compact, ...items);
}

const EVENT_NAMES = { spawn: '派出，任务', fork: '分身，任务', message: '玩家对它说', answer: '它回答' };
const eventName = (e) => EVENT_NAMES[e] ?? e;

function helperTurn(ht) {
  const out = [];
  if (ht.thinking.trim()) out.push(section('思考摘要', false, pre(ht.thinking)));
  if (ht.text.trim()) out.push(pre(ht.text, 'dp-text'));
  out.push(...ht.toolCalls.map(toolCall));
  if (ht.results?.length) out.push(...ht.results.map(toolResult));
  return out;
}
