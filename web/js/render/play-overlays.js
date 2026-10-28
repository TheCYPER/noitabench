import { colorOf } from './colors.js';

/**
 * Overlays of the play page, drawn over the material layer: fire, the player, what is in view and
 * the aim. They only draw what the server sent.
 */

/**
 * Burning cells, tinted. `view.burning` has one byte per cell of the window.
 * @param {CanvasRenderingContext2D} ctx
 * @param {import('./view.js').View} cam
 * @param {import('../play/view-data.js').PlayView} v
 */
export function drawBurning(ctx, cam, v) {
  ctx.save();
  ctx.fillStyle = 'rgba(255, 150, 30, 0.6)';
  const size = Math.max(cam.zoom, 1);
  for (let i = 0; i < v.burning.length; i++) {
    if (!v.burning[i]) continue;
    const x = cam.sx(v.origin.x + (i % v.width));
    const y = cam.sy(v.origin.y + Math.floor(i / v.width));
    if (x + size <= 0 || y + size <= 0 || x >= cam.cssW || y >= cam.cssH) continue; // no pixel of it is on the canvas
    ctx.fillRect(x, y, size, size);
  }
  ctx.restore();
}

/**
 * Creatures and items in view: box, kind and id (the id is what `aim(target=…)` and `pickup(item=…)` take).
 * Hostile ones are red, the one aimed at has a bracket. No health bars: an agent does not see them either.
 */
export function drawVisible(ctx, cam, entities) {
  ctx.save();
  ctx.font = '10px ui-monospace, Menlo, monospace';
  ctx.textBaseline = 'bottom';
  for (const e of entities) {
    const x = cam.sx(e.x);
    const y = cam.sy(e.y);
    const w = Math.max(e.w * cam.zoom, 4);
    const h = Math.max(e.h * cam.zoom, 4);
    if (x > cam.cssW || y > cam.cssH || x + w < 0 || y + h < 0) continue;
    ctx.fillStyle = e.hostile ? 'rgba(248,113,113,0.35)' : colorOf(e.kind, 0.35, 55);
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = e.hostile ? '#f87171' : colorOf(e.kind, 1, 70);
    ctx.lineWidth = e.aimed ? 3 : 1.5;
    ctx.strokeRect(x, y, w, h);
    if (cam.zoom >= 2) {
      ctx.fillStyle = '#fff';
      ctx.textAlign = 'left';
      ctx.fillText(`${e.kind}#${e.id}`, x, y - 2);
    }
  }
  ctx.restore();
}

/** The player's hit box. */
export function drawPlayerBox(ctx, cam, p) {
  ctx.save();
  ctx.strokeStyle = '#4ade80';
  ctx.lineWidth = 2;
  ctx.strokeRect(cam.sx(p.x), cam.sy(p.y), p.w * cam.zoom, p.h * cam.zoom);
  ctx.restore();
}

/**
 * A short line from the player along the aim (degrees: 0 right, 90 up) and a dot at its end.
 * @param {number} degrees
 * @param {number} [length]  cells
 */
export function drawAim(ctx, cam, p, degrees, length = 28) {
  const cx = p.x + p.w / 2;
  const cy = p.y + p.h / 2;
  const rad = (degrees * Math.PI) / 180;
  const ex = cx + Math.cos(rad) * length;
  const ey = cy - Math.sin(rad) * length;
  ctx.save();
  ctx.strokeStyle = 'rgba(250, 204, 21, 0.9)';
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(cam.sx(cx), cam.sy(cy));
  ctx.lineTo(cam.sx(ex), cam.sy(ey));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = '#facc15';
  ctx.beginPath();
  ctx.arc(cam.sx(ex), cam.sy(ey), 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}
