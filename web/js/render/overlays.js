import { colorOf } from './colors.js';

/**
 * Overlay draw passes. Each takes the 2D context (already scaled so one unit
 * is one CSS pixel) and the View, and draws on top of the material layer.
 * All of them only read data; none of them knows any game rule.
 */

const FONT = '600 11px ui-monospace, SFMono-Regular, Menlo, monospace';

/**
 * Biome cell boundaries, an optional tint per biome and the biome key as a label.
 * @param {CanvasRenderingContext2D} ctx
 * @param {import('./view.js').View} view
 * @param {import('../format/world.js').WorldMeta} world
 * @param {{tint?:boolean,labels?:boolean}} [opts]
 */
export function drawBiomeGrid(ctx, view, world, { tint = true, labels = true } = {}) {
  const cs = world.cellSize;
  const rows = world.biomeMap.length;
  ctx.save();
  ctx.font = FONT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let r = 0; r < rows; r++) {
    const cols = world.biomeMap[r].length;
    for (let c = 0; c < cols; c++) {
      const x = view.sx(c * cs);
      const y = view.sy(r * cs);
      const size = cs * view.zoom;
      if (x > view.cssW || y > view.cssH || x + size < 0 || y + size < 0) continue;
      const key = world.biomeMap[r][c];
      if (tint) {
        ctx.fillStyle = colorOf(key, 0.16);
        ctx.fillRect(x, y, size, size);
      }
      ctx.strokeStyle = 'rgba(255,255,255,0.55)';
      ctx.lineWidth = 1;
      ctx.strokeRect(Math.round(x) + 0.5, Math.round(y) + 0.5, size, size);
      if (labels && size >= 56) {
        const lx = Math.min(Math.max(x + size / 2, 36), view.cssW - 36);
        const ly = Math.min(Math.max(y + 12, 12), view.cssH - 12);
        if (lx > x && lx < x + size) label(ctx, key, lx, Math.max(ly, y + 12));
      }
    }
  }
  ctx.restore();
}

function label(ctx, text, x, y) {
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(0,0,0,0.75)';
  ctx.strokeText(text, x, y);
  ctx.fillStyle = '#fff';
  ctx.fillText(text, x, y);
}

const MARK_STYLE = {
  spawn_player: { glyph: 'P', color: '#4ade80' },
  spawn_enemy: { glyph: 'E', color: '#f87171' },
  item: { glyph: 'I', color: '#facc15' },
  rest_area: { glyph: 'R', color: '#60a5fa' },
  seal: { glyph: 'S', color: '#c084fc' },
  encounter: { glyph: '!', color: '#fb923c' },
};
const UNKNOWN_STYLE = { glyph: '?', color: '#9ca3af' };

/**
 * Letter and colour a marker type is drawn with; unknown types get a grey "?".
 * @param {string} type
 * @returns {{glyph:string,color:string}}
 */
export const markerStyle = (type) => MARK_STYLE[type] ?? UNKNOWN_STYLE;

/**
 * Point markers (a letter in a coloured disc) and, when a marker has w and h,
 * its rectangle. Encounters are drawn by drawEncounters instead.
 * @param {CanvasRenderingContext2D} ctx
 * @param {import('./view.js').View} view
 * @param {object[]} markers
 * @param {Set<string>|null} [types]  limit to these marker types
 */
export function drawMarkers(ctx, view, markers, types = null) {
  ctx.save();
  ctx.font = FONT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const m of markers) {
    if (m.type === 'encounter' || (types && !types.has(m.type))) continue;
    const st = markerStyle(m.type);
    const x = view.sx(m.x);
    const y = view.sy(m.y);
    if (m.w > 0 && m.h > 0) {
      ctx.strokeStyle = st.color;
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 3]);
      ctx.strokeRect(x, y, m.w * view.zoom, m.h * view.zoom);
      ctx.setLineDash([]);
    }
    disc(ctx, x, y, st, view.zoom);
  }
  ctx.restore();
}

/** Marker discs shrink when the map is zoomed out, so a whole world is not buried under them; the letter only fits in the big ones. */
function disc(ctx, x, y, st, zoom) {
  const r = Math.max(2.5, Math.min(7, 2 + zoom * 2.5));
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = st.color;
  ctx.fill();
  ctx.lineWidth = r < 5 ? 1 : 1.5;
  ctx.strokeStyle = '#000';
  ctx.stroke();
  if (r >= 5) {
    ctx.fillStyle = '#000';
    ctx.fillText(st.glyph, x, y + 0.5);
  }
}

/**
 * Encounter trigger rectangles. must_pass encounters are solid gold and
 * thick; optional ones are dashed cyan.
 * @param {CanvasRenderingContext2D} ctx
 * @param {import('./view.js').View} view
 * @param {object[]} markers  the world's markers (other types are skipped)
 * @param {object|null} [highlight]  one of `markers` to emphasise
 */
export function drawEncounters(ctx, view, markers, highlight = null) {
  ctx.save();
  ctx.font = FONT;
  for (const m of markers) {
    if (m.type !== 'encounter') continue;
    const t = m.trigger;
    const x = view.sx(t.x);
    const y = view.sy(t.y);
    const w = t.w * view.zoom;
    const h = t.h * view.zoom;
    const must = m.must_pass === true;
    const hot = highlight !== null && m === highlight;
    const color = must ? '#fbbf24' : '#22d3ee';
    ctx.fillStyle = must ? 'rgba(251,191,36,0.16)' : 'rgba(34,211,238,0.10)';
    ctx.fillRect(x, y, w, h);
    ctx.setLineDash(must ? [] : [6, 4]);
    ctx.lineWidth = hot ? 4 : must ? 3 : 1.5;
    ctx.strokeStyle = hot ? '#fff' : color;
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    label(ctx, `${m.encounter_id ?? 'encounter'}${m.variant !== undefined ? `·v${m.variant}` : ''}${must ? ' ★' : ''}`, x + 3, y + 3);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    disc(ctx, view.sx(m.x), view.sy(m.y), markerStyle('encounter'), view.zoom);
  }
  ctx.restore();
}

/**
 * Optional polyline (world.mainPath).
 * @param {CanvasRenderingContext2D} ctx
 * @param {import('./view.js').View} view
 * @param {{x:number,y:number}[]|null} path
 */
export function drawMainPath(ctx, view, path) {
  if (!path || path.length < 2) return;
  ctx.save();
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(255,255,255,0.8)';
  ctx.setLineDash([2, 6]);
  ctx.lineCap = 'round';
  ctx.beginPath();
  path.forEach((p, i) => (i === 0 ? ctx.moveTo(view.sx(p.x), view.sy(p.y)) : ctx.lineTo(view.sx(p.x), view.sy(p.y))));
  ctx.stroke();
  ctx.restore();
}

/**
 * Entities of the current frame: outlined box (x, y = top-left corner),
 * hit-point bar, and a label when zoomed in.
 * @param {CanvasRenderingContext2D} ctx
 * @param {import('./view.js').View} view
 * @param {object[]} entities  entities.jsonl items; fields other than x and y are optional
 */
export function drawEntities(ctx, view, entities) {
  ctx.save();
  ctx.font = '10px ui-monospace, Menlo, monospace';
  ctx.textBaseline = 'bottom';
  for (const e of entities) {
    const kind = String(e.kind ?? 'entity');
    const w = Math.max((e.w ?? 1) * view.zoom, 4);
    const h = Math.max((e.h ?? 1) * view.zoom, 4);
    const x = view.sx(e.x);
    const y = view.sy(e.y);
    if (x > view.cssW || y > view.cssH || x + w < 0 || y + h < 0) continue;
    ctx.fillStyle = colorOf(kind, 0.35, 55);
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = colorOf(kind, 1, 70);
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x, y, w, h);
    if (e.hp_max > 0 && typeof e.hp === 'number') {
      const frac = Math.max(0, Math.min(1, e.hp / e.hp_max));
      const bw = Math.max(w, 14);
      ctx.fillStyle = 'rgba(0,0,0,0.7)';
      ctx.fillRect(x, y - 5, bw, 3);
      ctx.fillStyle = frac > 0.5 ? '#4ade80' : frac > 0.25 ? '#facc15' : '#f87171';
      ctx.fillRect(x, y - 5, bw * frac, 3);
    }
    if (view.zoom >= 3) {
      ctx.fillStyle = '#fff';
      ctx.textAlign = 'left';
      ctx.fillText(`${kind}#${e.id ?? '?'}`, x, y - 7);
    }
  }
  ctx.restore();
}

/**
 * Expanding rings where events with a position happened in the last
 * `windowFrames` frames; older ones are fainter. Events without x/y are skipped.
 * @param {CanvasRenderingContext2D} ctx
 * @param {import('./view.js').View} view
 * @param {{frame:number,type:string,x?:number,y?:number,radius?:number,r?:number}[]} events  already filtered to the window
 * @param {number} frame  the frame being shown
 * @param {number} windowFrames
 */
export function drawEventMarks(ctx, view, events, frame, windowFrames) {
  ctx.save();
  for (const e of events) {
    if (typeof e.x !== 'number' || typeof e.y !== 'number') continue;
    const age = Math.max(0, frame - e.frame);
    const fade = 1 - age / windowFrames;
    if (fade <= 0) continue;
    const base = typeof e.radius === 'number' ? e.radius : typeof e.r === 'number' ? e.r : 2;
    const radius = Math.max(4, base * view.zoom) * (1 + 0.6 * (1 - fade));
    ctx.beginPath();
    ctx.arc(view.sx(e.x), view.sy(e.y), radius, 0, Math.PI * 2);
    ctx.lineWidth = 2;
    ctx.strokeStyle = colorOf(e.type, fade, 65);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(view.sx(e.x), view.sy(e.y), 2, 0, Math.PI * 2);
    ctx.fillStyle = colorOf(e.type, fade, 75);
    ctx.fill();
  }
  ctx.restore();
}
