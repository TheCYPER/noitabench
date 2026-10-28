/**
 * Commands in the agent grammar (tick-design 4.3), built as plain `{name, args}` objects: the
 * server accepts them as they are (`{"commands": [...]}`) and runs them exactly as it runs an
 * agent's. These builders only shape the arguments the player picked; whether a command is
 * valid, and what it does, is decided by the game.
 */

/**
 * @typedef {{name:string, args:Record<string, any>}} Command
 */

/** Drops `undefined` values so a missing optional argument is simply absent. */
function clean(args) {
  return Object.fromEntries(Object.entries(args).filter(([, v]) => v !== undefined));
}

/** @returns {Command} */
export const cmd = (name, args = {}) => ({ name, args: clean(args) });

export const move = (direction, ticks) => cmd('move', { direction, ticks });
export const walkTo = (x) => cmd('walk_to', { x });
export const jump = (direction = 'up') => cmd('jump', { direction });
export const fly = (direction = 'up', ticks = undefined) => cmd('fly', { direction, ticks });
export const wait = (ticks) => cmd('wait', { ticks });
/** `until` is an object of conditions written beside the arguments: `{ticks: 3}` or `{target_dead: true}`. */
export const fire = (until = {}) => cmd('fire', until);
export const kick = () => cmd('kick');
export const pickup = (item) => cmd('pickup', { item });
export const swapWand = (wand) => cmd('swap_wand', { wand });

export const aimPoint = (x, y) => cmd('aim', { x, y });
export const aimTarget = (id) => cmd('aim', { target: id });

export const drink = (bottle, amount) => cmd('drink', { bottle, amount });
export const pour = (bottle, amount) => cmd('pour', { bottle, amount });
export const fill = (bottle, amount) => cmd('fill', { bottle, amount });
export const throwBottle = (bottle) => cmd('throw', { bottle });

export const inspectCell = (x, y) => cmd('inspect', { x, y });
export const inspectEntity = (id) => cmd('inspect', { entity: id });
export const inspectWand = (wand, slot) => cmd('inspect', { wand, slot });
export const inspectSpell = (spell) => cmd('inspect', { spell });
export const inspectBottle = (bottle) => cmd('inspect', { bottle });

export const dropWand = (wand) => cmd('drop', { wand });
export const dropSpell = (spell) => cmd('drop', { spell });
export const dropBottle = (bottle) => cmd('drop', { bottle });

export const editPlace = (wand, slot, spell) => cmd('edit_wand', { op: 'place', wand, slot, spell });
export const editTake = (wand, slot) => cmd('edit_wand', { op: 'take', wand, slot });
export const editSwap = (wand, a, b) => cmd('edit_wand', { op: 'swap', wand, a, b });

const BARE_WORD = /^[A-Za-z_]\w*$/;

/** One argument value as the text grammar writes it: words bare, other text quoted. */
export function formatValue(v) {
  if (typeof v === 'string') return BARE_WORD.test(v) ? v : JSON.stringify(v);
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (v !== null && typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/**
 * `{name:'move', args:{direction:'left', ticks:1}}` -> `move(direction=left, ticks=1)`, the text
 * a player could type into the command box.
 * @param {Command} c
 */
export function formatCommand(c) {
  const args = Object.entries(c.args ?? {}).map(([k, v]) => `${k}=${formatValue(v)}`);
  return `${c.name}(${args.join(', ')})`;
}

/** @param {Command[]} commands */
export const formatDecision = (commands) => commands.map(formatCommand).join('; ');
