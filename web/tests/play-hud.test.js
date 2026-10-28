import test from 'node:test';
import assert from 'node:assert/strict';
import {
  aimText, bottleRows, budgetLine, commandSignature, endBanner, eventRows, latestInspect, overText, resultRows, spellRows, stopText, vitals, wandRows,
} from '../js/play/hud.js';
import { fixtureJson } from './helpers.js';

const { response } = fixtureJson('play_state.json');
const answer = response.answer;
const state = answer.observation.state;

test('vitals from a real answer', () => {
  const v = vitals(state);
  assert.equal(v.hp.pct, 100);
  assert.equal(v.hp.max, 100);
  assert.match(v.position, /^x=\d+ y=\d+$/);
  assert.ok(['在地面', '在空中'].includes(v.ground));
  assert.deepEqual(v.statuses, []);
});

test('statuses, aim and percentages', () => {
  const v = vitals({ ...state, hp: 25, hp_max: 100, levitation: 0.5, breath: 1.4, statuses: { on_fire: 2.5, wet: 12 }, aim: { degrees: -45, follows: 3 } });
  assert.equal(v.hp.pct, 25);
  assert.equal(v.levitation, 50);
  assert.equal(v.breath, 100, 'clamped');
  assert.deepEqual(v.statuses.map((s) => s.text), ['on_fire 2.5s', 'wet 12s']);
  assert.equal(v.aim, '-45°（跟着 #3）');
  assert.equal(aimText({ degrees: 90, follows: null }), '90°');
});

test('wands list their slots, mana and stats', () => {
  const rows = wandRows(state);
  assert.equal(rows.length, state.wands.length);
  assert.equal(rows.filter((w) => w.active).length, 1);
  const w = rows[0];
  assert.match(w.manaText, /^\d+(\.\d)?\/\d+(\.\d)?$/);
  assert.ok(w.slots.length > 0);
  assert.equal(w.slots[0].text.startsWith(state.wands[0].slots[0].spell), true);
  const synthetic = wandRows({ wands: [{ index: 0, active: false, mana: 5, mana_max: 20, cast_delay: 3, recharge: 4, spells_per_cast: 1, capacity: 2, shuffle: true, cooldown: 0, slots: [{ slot: 0, spell: null }, { slot: 1, spell: 'BOMB', uses: 3 }] }] });
  assert.deepEqual(synthetic[0].slots.map((s) => s.text), ['（空）', 'BOMB ×3']);
  assert.equal(synthetic[0].manaPct, 25);
  assert.match(synthetic[0].statsText, /乱序/);
});

test('bottles and carried spells', () => {
  const rows = bottleRows({ bottles: [{ index: 0, active: true, amount: 120, capacity: 400, contents: [{ material: 'water', amount: 100 }, { material: 'oil', amount: 20 }] }, { index: 1, active: false, amount: 0, capacity: 400, contents: [] }] });
  assert.equal(rows[0].text, 'water 100，oil 20');
  assert.equal(rows[1].text, '空');
  assert.deepEqual(spellRows({ spells: [{ index: 0, spell: 'BOMB', uses: 3 }, { index: 1, spell: 'DAMAGE', uses: null }] }).map((s) => s.text), ['BOMB ×3', 'DAMAGE']);
});

test('the decision line, the stop line, results and events', () => {
  assert.equal(budgetLine({ decision: 12, decisions_left: 988 }, 1), '第 12 个决策 · 还剩 988 · 上一步花了 1');
  assert.equal(budgetLine({ decision: 1, decisions_left: 1000 }, null), '第 1 个决策 · 还剩 1000');
  assert.equal(stopText({ reason: 'interrupted', detail: 'damage', ticks: 3, frames: 30, also: ['new_enemy'] }), 'interrupted (damage)，同时 new_enemy · 3 tick，30 帧');
  assert.equal(stopText({ reason: 'start', ticks: 0, frames: 0 }), 'start');
  assert.match(stopText({ reason: 'invalid', code: 'x', message: 'no such thing', ticks: 0, frames: 0 }), /no such thing/);
  const rows = resultRows({ results: [{ command: 'move', ok: true, stop: { reason: 'completed', detail: 'blocked' } }, { command: 'wait', ok: false, code: 'no_time_left', message: 'No time.' }, { command: 'inspect', ok: true, result: { a: 1 } }] });
  assert.deepEqual(rows.map((r) => r.ok), [true, false, true]);
  assert.equal(rows[0].text, 'move：completed (blocked)');
  assert.match(rows[1].text, /失败（no_time_left）No time\./);
  assert.match(rows[2].text, /\{"a":1\}/);
  assert.deepEqual(eventRows({ events: [{ tick: 2, text: 'You are hit.' }], events_omitted: 3 }), ['tick 2：You are hit.', '…还有 3 条没有显示']);
});

test('the real answer: inspect result is found, the episode is not over', () => {
  const seen = latestInspect(answer);
  assert.equal(seen.result.what, 'cell');
  assert.equal(seen.result.material, 'wood');
  assert.equal(overText(answer), null);
  assert.match(overText({ over: 'dead' }), /你死了/);
  assert.match(overText({ over: 'decision_limit' }), /决策次数/);
  assert.equal(latestInspect({ results: [{ command: 'move', ok: true }] }), null);
  assert.equal(latestInspect({ results: [{ command: 'inspect', ok: false, code: 'x', message: 'y' }] }), null);
});

test('command signatures for the help list: required arguments plain, the others in brackets', () => {
  const sig = commandSignature({ name: 'move', arguments: [{ name: 'direction', required: true }, { name: 'until', required: false }] });
  assert.equal(sig, 'move(direction, [until])');
  assert.equal(commandSignature({ name: 'kick', arguments: [] }), 'kick()');
});

test('the end banner: nothing while the episode runs, the reason once it is over, the recording noted', () => {
  assert.equal(endBanner({ over: null }, false, false), '');
  assert.match(endBanner({ over: 'dead' }, true, true), /你死了.*录像已保存/);
  assert.match(endBanner({ over: 'decision_limit' }, true, false), /决策次数用完了/);
  assert.doesNotMatch(endBanner({ over: 'decision_limit' }, true, false), /录像/);
  assert.match(endBanner({ over: null }, true, true), /这一局已经结束.*录像已保存/, 'ended with the button');
  assert.match(endBanner({ over: 'dead' }, false, false), /你死了/, 'dead but not closed yet');
});
