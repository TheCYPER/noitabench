import {
  dropBottle, dropWand, drink, fill, fire, fly, jump, kick, move, pickup, pour, swapWand, throwBottle, wait,
} from './commands.js';

/** Ticks a plain step lasts (10 frames each); Shift asks for the longest a command may run. */
export const LONG_TICKS = 30;
export const STEP_CHOICES = [1, 2, 3, 5, 10];

/** W / Up pressed for less than this many milliseconds is a tap (a jump); longer is a hold (levitation). */
export const TAP_MS = 200;
/** A tick is 10 frames of a 60 fps game: this much held key time is one tick of game time. */
export const TICK_MS = (10 / 60) * 1000;
/** Ticks one hold may ask for: a decision lasts at most 300 frames. */
export const MAX_FLY_TICKS = LONG_TICKS;

/**
 * What a key press asks for. Each binding builds the commands of one decision from the
 * player's settings (`ctx`) and whether Shift is held. A held key does not repeat: one press
 * is one decision, and decisions are what the budget counts.
 *
 * W / Up is the one key that is not decided on the press: a tap is a jump, a hold is levitation
 * for as long as the key stays down, so it waits for the release (`Gestures` below), and A/D
 * pressed meanwhile only steer it. Its binding carries `hold: true` and builds nothing.
 *
 * ctx: `stepTicks` (length of a plain step), `bottle` (index of the chosen bottle, or
 * undefined for the game's active one), `wandCount`, and the indices of the bottle and the wand
 * in hand (`activeBottle`, `activeWand`), which a drop needs.
 *
 * @typedef {{stepTicks:number, bottle?:number, wandCount?:number, activeBottle?:number, activeWand?:number}} KeyContext
 * @typedef {{keys:string[], label:string, text:string, hold?:boolean, build?:(ctx:KeyContext, long:boolean)=>import('./commands.js').Command[]}} Binding
 */

/** @type {Binding[]} */
export const BINDINGS = [
  { keys: ['ArrowLeft', 'a'], label: '← A', text: '向左走（Shift：走到底）', build: (c, l) => [move('left', l ? LONG_TICKS : c.stepTicks)] },
  { keys: ['ArrowRight', 'd'], label: '→ D', text: '向右走（Shift：走到底）', build: (c, l) => [move('right', l ? LONG_TICKS : c.stepTicks)] },
  { keys: ['ArrowUp', 'w'], label: '↑ W', text: '轻点：原地跳；按住：悬浮上升，按多久飞多久（最多 5 秒）。按住时再按 A/D：斜着飞，轻点时按住 A/D：向那边跳', hold: true },
  { keys: ['q'], label: 'Q', text: '向左跳', build: () => [jump('left')] },
  { keys: ['e'], label: 'E', text: '向右跳', build: () => [jump('right')] },
  { keys: ['ArrowDown', 's'], label: '↓ S', text: '原地等待（Shift：久等）', build: (c, l) => [wait(l ? LONG_TICKS : c.stepTicks)] },
  { keys: [' '], label: '空格', text: '朝当前瞄准方向施法（Shift：久按）', build: (c, l) => [fire({ ticks: l ? LONG_TICKS : c.stepTicks })] },
  { keys: ['k'], label: 'K', text: '踢', build: () => [kick()] },
  { keys: ['f'], label: 'F', text: '捡起身边最近的东西', build: () => [pickup()] },
  { keys: ['b'], label: 'B', text: '喝瓶子', build: (c) => [drink(c.bottle)] },
  { keys: ['p'], label: 'P', text: '倒出瓶子', build: (c) => [pour(c.bottle)] },
  { keys: ['l'], label: 'L', text: '把脚边的液体装进瓶子', build: (c) => [fill(c.bottle)] },
  { keys: ['t'], label: 'T', text: '扔瓶子', build: (c) => [throwBottle(c.bottle)] },
  { keys: ['x'], label: 'X', text: '丢下瓶子（Shift：丢下手里的法杖）', build: (c, l) => dropOf(c, l) },
];

/** `drop` needs an index: the chosen bottle (or the one in hand), or with Shift the wand in hand. */
function dropOf(c, long) {
  if (long) return c.activeWand === undefined ? [] : [dropWand(c.activeWand)];
  const bottle = c.bottle ?? c.activeBottle;
  return bottle === undefined ? [] : [dropBottle(bottle)];
}

const BY_KEY = new Map();
for (const b of BINDINGS) for (const k of b.keys) BY_KEY.set(k, b);

const normal = (e) => (e.key.length === 1 ? e.key.toLowerCase() : e.key);
const ignorable = (e) => Boolean(e.ctrlKey || e.metaKey || e.altKey);

/**
 * The commands for a key press, or null when the key means nothing here (W / Up included: that
 * one is decided by `Gestures` when it is let go).
 * @param {{key:string, shiftKey?:boolean, repeat?:boolean, ctrlKey?:boolean, metaKey?:boolean, altKey?:boolean}} e
 * @param {KeyContext} ctx
 * @returns {import('./commands.js').Command[]|null}
 */
export function commandsForKey(e, ctx) {
  if (e.repeat || ignorable(e)) return null;
  const long = Boolean(e.shiftKey);
  const key = normal(e);
  if (/^[1-9]$/.test(key)) {
    const wand = Number(key) - 1;
    if (ctx.wandCount !== undefined && wand >= ctx.wandCount) return null;
    return [swapWand(wand)];
  }
  const binding = BY_KEY.get(key);
  const commands = binding?.build ? binding.build(ctx, long) : null;
  return commands && commands.length ? commands : null; // nothing to drop: no decision
}

/** Keys that stop the page from scrolling or clicking a focused button. */
export function isGameKey(e) {
  const key = normal(e);
  return BY_KEY.has(key) || /^[1-9]$/.test(key);
}

// ------------------------------------------------------------------ W: a tap jumps, a hold levitates

const SIDE = { ArrowLeft: 'left', a: 'left', ArrowRight: 'right', d: 'right' };
const isLift = (key) => key === 'w' || key === 'ArrowUp';

/**
 * Ticks of game time for a key held `ms` milliseconds: 10 frames (one tick) per 1/6 s, at least
 * one, at most what one decision may last.
 * @param {number} ms
 */
export function holdTicks(ms) {
  return Math.max(1, Math.min(MAX_FLY_TICKS, Math.round(ms / TICK_MS)));
}

/**
 * The gesture of W / Up. The key goes down: nothing is sent, the time is noted. The key comes up:
 * under `TAP_MS` it is `jump` (up, or to the side whose key is held), otherwise `fly` for
 * `holdTicks` ticks (up, or sideways). While W is down A/D do not walk: they only choose the side,
 * so the whole gesture is one decision. A/D pressed before W are ordinary decisions already made;
 * if they are still down when W goes up they steer the jump or the flight. Auto-repeat of a held
 * key is ignored; `reset` (the window lost focus) drops a gesture without a decision.
 */
export class Gestures {
  constructor() {
    /** side keys that are down now (A, D, Left, Right as the page names them), oldest first */
    this.keys = [];
    /** @type {{at:number, side:'left'|'right'|null}|null} */
    this.lift = null;
  }

  /** @returns {'left'|'right'|null} the side whose key was pressed last and is still down */
  side() {
    const last = this.keys[this.keys.length - 1];
    return last === undefined ? null : SIDE[last];
  }

  /**
   * @param {{key:string, shiftKey?:boolean, repeat?:boolean, ctrlKey?:boolean, metaKey?:boolean, altKey?:boolean}} e
   * @param {KeyContext} ctx
   * @param {number} now  time of the event in milliseconds
   * @returns {import('./commands.js').Command[]|null} commands to send now, if any
   */
  down(e, ctx, now) {
    if (ignorable(e)) return null;
    const key = normal(e);
    if (isLift(key)) {
      if (!e.repeat && !this.lift) this.lift = { at: now, side: this.side() };
      return null;
    }
    if (SIDE[key]) {
      if (e.repeat) return null;
      this.keys = [...this.keys.filter((k) => k !== key), key];
      if (this.lift) {
        this.lift.side = SIDE[key];
        return null; // steers the jump or the flight, not a step of its own
      }
    }
    return commandsForKey(e, ctx);
  }

  /**
   * @param {{key:string}} e
   * @param {number} now  time of the event in milliseconds
   * @returns {import('./commands.js').Command[]|null}
   */
  up(e, now) {
    const key = normal(e);
    if (SIDE[key]) {
      this.keys = this.keys.filter((k) => k !== key);
      return null;
    }
    if (!isLift(key) || !this.lift) return null;
    const { at, side: pressedWith } = this.lift;
    this.lift = null;
    const dir = this.side() ?? pressedWith ?? 'up';
    const held = now - at;
    return held < TAP_MS ? [jump(dir)] : [fly(dir, holdTicks(held))];
  }

  /** The window lost focus: key-up events will not come. */
  reset() {
    this.keys = [];
    this.lift = null;
  }
}
