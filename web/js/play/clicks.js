import { aimPoint, aimTarget, fire, inspectCell, inspectEntity, walkTo } from './commands.js';

/**
 * What a mouse click on the picture asks for:
 *  - left click on a hostile creature: aim at it and fire until it is dead;
 *  - left click anywhere else: walk to that column (there is no path finding, as for agents);
 *  - Shift + left click: aim at the point and fire for one step;
 *  - right click: `inspect` the creature or item there, or the cell (costs a decision).
 *
 * @param {{button:number, shiftKey?:boolean}} ev  button 0 = left, 2 = right
 * @param {{x:number, y:number, entity:object|null}} hit  the cell and the thing under the pointer
 * @param {{stepTicks:number}} ctx
 * @returns {import('./commands.js').Command[]|null}
 */
export function commandsForClick(ev, hit, ctx) {
  if (ev.button === 2) {
    return [hit.entity ? inspectEntity(hit.entity.id) : inspectCell(hit.x, hit.y)];
  }
  if (ev.button !== 0) return null;
  if (ev.shiftKey) return [aimPoint(hit.x, hit.y), fire({ ticks: ctx.stepTicks })];
  if (hit.entity?.hostile) return [aimTarget(hit.entity.id), fire({ target_dead: true })];
  const x = hit.entity ? Math.floor(hit.entity.x + hit.entity.w / 2) : hit.x;
  return [walkTo(x)];
}
