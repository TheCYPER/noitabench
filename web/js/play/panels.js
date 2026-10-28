import { clear, h } from '../ui/dom.js';
import { bottleRows, spellRows, vitals, wandRows } from './hud.js';

/**
 * Builders for the side panels. Each takes the element to fill, the part of the state it shows
 * and the functions to call when a button is pressed. Text goes in with textContent only.
 */

function button(text, onClick, title = '') {
  const b = h('button', { type: 'button', className: 'small', title }, text);
  b.addEventListener('click', () => {
    b.blur(); // so the space bar fires the wand instead of pressing this button again
    onClick();
  });
  return b;
}

/** A labelled bar: `percent` wide, `cls` picks the colour. */
function barRow(label, percent, text, cls) {
  const fill = h('div', { className: `fill ${cls}` });
  fill.style.width = `${percent}%`;
  const track = h('div', { className: 'bar' });
  track.append(fill);
  const row = h('div', { className: 'barrow' });
  row.append(h('span', { className: 'barlabel' }, label), track, h('span', { className: 'bartext mono' }, text));
  return row;
}

/** @param {HTMLElement} el @param {any} state */
export function renderVitals(el, state) {
  const v = vitals(state);
  clear(el);
  el.append(
    barRow('生命', v.hp.pct, `${Math.round(v.hp.value)}/${Math.round(v.hp.max)}`, 'hp'),
    barRow('悬浮', v.levitation, `${v.levitation}%`, 'fly'),
    barRow('呼吸', v.breath, `${v.breath}%`, 'air'),
    h('div', { className: 'kv mono' }, `${v.position} · ${v.ground} · ${v.facing} · 瞄准 ${v.aim}`),
    h('div', { className: 'kv' }, v.statuses.length ? `状态：${v.statuses.map((s) => s.text).join('，')}` : '没有状态'),
  );
}

/**
 * @param {HTMLElement} el
 * @param {any} state
 * @param {{
 *   canEdit: boolean, picked: {wand:number, slot:number}|null,
 *   onSwap: (i:number)=>void, onInspect: (i:number)=>void, onDrop: (i:number)=>void,
 *   onSlot: (wand:number, slot:number, filled:boolean)=>void,
 * }} on
 */
export function renderWands(el, state, on) {
  clear(el);
  const rows = wandRows(state);
  if (rows.length === 0) el.append(h('div', { className: 'empty' }, '没有法杖'));
  for (const w of rows) {
    const box = h('div', { className: `wand${w.active ? ' active' : ''}` });
    const head = h('div', { className: 'wandhead' });
    head.append(
      h('strong', {}, `[${w.index}]${w.active ? ' ★' : ''}`),
      h('span', { className: 'mono' }, ` 法力 ${w.manaText}`),
      button('拿起', () => on.onSwap(w.index), `swap_wand(wand=${w.index})`),
      button('查看', () => on.onInspect(w.index), `inspect(wand=${w.index})：算一次决策`),
      button('丢下', () => on.onDrop(w.index), `drop(wand=${w.index})`),
    );
    const slots = h('div', { className: 'slots' });
    for (const s of w.slots) {
      const b = button(s.text, () => on.onSlot(w.index, s.slot, s.spell !== null), on.canEdit ? '点一下选中，或把选中的法术放进来' : '这里不能改法杖');
      b.classList.add('slot');
      if (on.picked && on.picked.wand === w.index && on.picked.slot === s.slot) b.classList.add('picked');
      if (s.spell === null) b.classList.add('emptyslot');
      b.disabled = !on.canEdit;
      slots.append(b);
    }
    box.append(head, slots, h('div', { className: 'kv small' }, w.statsText));
    el.append(box);
  }
}

/**
 * @param {HTMLElement} el
 * @param {any} state
 * @param {{canEdit:boolean, picked:number|null, onPick:(i:number)=>void, onInspect:(i:number)=>void, onDrop:(i:number)=>void}} on
 */
export function renderSpells(el, state, on) {
  clear(el);
  const rows = spellRows(state);
  if (rows.length === 0) el.append(h('div', { className: 'empty' }, '没有带着的法术'));
  for (const s of rows) {
    const line = h('div', { className: 'item' });
    const pick = button(s.text, () => on.onPick(s.index), on.canEdit ? '选中，再点法杖的空位放进去' : '只能在休息区或改杖台放进法杖');
    pick.disabled = !on.canEdit;
    if (on.picked === s.index) pick.classList.add('picked');
    line.append(
      h('span', { className: 'mono' }, `[${s.index}] `),
      pick,
      button('查看', () => on.onInspect(s.index), `inspect(spell=${s.index})：算一次决策`),
      button('丢下', () => on.onDrop(s.index), `drop(spell=${s.index})`),
    );
    el.append(line);
  }
}

/**
 * @param {HTMLElement} el
 * @param {any} state
 * @param {{chosen:number|null, onChoose:(i:number)=>void, onInspect:(i:number)=>void, onDrop:(i:number)=>void}} on
 */
export function renderBottles(el, state, on) {
  clear(el);
  const rows = bottleRows(state);
  if (rows.length === 0) el.append(h('div', { className: 'empty' }, '没有瓶子'));
  for (const b of rows) {
    const using = on.chosen === null ? b.active : on.chosen === b.index;
    const line = h('div', { className: `item${using ? ' chosen' : ''}` });
    line.append(
      button(using ? '●' : '○', () => on.onChoose(b.index), '喝、倒、装、扔都用这个瓶子'),
      h('span', { className: 'mono' }, ` [${b.index}] ${b.text} (${b.amount}/${b.capacity}) `),
      button('查看', () => on.onInspect(b.index), `inspect(bottle=${b.index})：算一次决策`),
      button('丢下', () => on.onDrop(b.index), `drop(bottle=${b.index})`),
    );
    el.append(line);
  }
}

/**
 * Colour key: the materials the server says may be named (the same ones the legend of an agent's
 * ASCII map names), with the name it gave and the colour from the materials file.
 * @param {HTMLElement} el
 * @param {{index:number, name:string}[]} entries  from the view's `legend`
 * @param {{rgb:Uint8Array}} table  colours only: the page has no other material data
 */
export function renderLegend(el, entries, table) {
  clear(el);
  for (const { index, name } of entries) {
    const rgb = table.rgb.slice(index * 3, index * 3 + 3);
    const sw = h('span', { className: 'swatch' });
    sw.style.background = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
    const item = h('span', { className: 'legenditem' });
    item.append(sw, document.createTextNode(name));
    el.append(item);
  }
}
