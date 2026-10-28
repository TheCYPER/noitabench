import { FormatError } from '../format/errors.js';

/**
 * Decoding the picture the server sends (`view` of /api/state, see play/view.py): a window of
 * material indices, a packed bit mask of burning cells, the player's box and the creatures and
 * items in view. Pure functions; nothing here knows a game rule.
 */

/** @param {string} text base64 @returns {Uint8Array} */
export function base64ToBytes(text) {
  const bin = atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * Bits of a packed mask (first cell = top bit of the first byte) as one byte per cell.
 * @param {Uint8Array} packed
 * @param {number} count  number of cells
 */
export function unpackBits(packed, count) {
  const out = new Uint8Array(count);
  for (let i = 0; i < count; i++) out[i] = (packed[i >> 3] >> (7 - (i & 7))) & 1;
  return out;
}

/**
 * @typedef {{id:number, kind:string, x:number, y:number, w:number, h:number, hostile?:boolean, aimed?:boolean}} Entity
 * @typedef {{index:number, name:string}} LegendEntry  a material the page may name, and its name
 * @typedef {{
 *   frame:number, origin:{x:number,y:number}, width:number, height:number, outside:number,
 *   materials:Uint8Array, burning:Uint8Array, legend:LegendEntry[],
 *   player:{x:number,y:number,w:number,h:number,position:{x:number,y:number}},
 *   entities:Entity[],
 * }} PlayView
 */

/**
 * The materials the server lets the page name: `{index, name}` pairs. The names come only with
 * the legend (the materials file the page loads has colours and nothing else). Entries that are
 * not a material index (outside is 255) or have no text name drop out.
 * @param {any} raw
 * @returns {LegendEntry[]}
 */
export function decodeLegend(raw) {
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  const out = [];
  for (const e of raw) {
    if (!e || !Number.isInteger(e.index) || e.index < 0 || e.index >= 255 || typeof e.name !== 'string' || !e.name) continue;
    if (seen.has(e.index)) continue;
    seen.add(e.index);
    out.push({ index: e.index, name: e.name });
  }
  return out;
}

/**
 * @param {any} raw  the `view` object of the server
 * @returns {PlayView}
 */
export function decodeView(raw) {
  const where = 'view';
  const { width, height } = raw ?? {};
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1) {
    throw new FormatError(where, 'width and height must be positive integers');
  }
  const n = width * height;
  const materials = base64ToBytes(String(raw.materials));
  if (materials.length !== n) throw new FormatError(where, `materials has ${materials.length} bytes, expected ${n}`);
  const packed = base64ToBytes(String(raw.burning));
  if (packed.length !== Math.ceil(n / 8)) throw new FormatError(where, `burning has ${packed.length} bytes, expected ${Math.ceil(n / 8)}`);
  return {
    frame: raw.frame,
    origin: { x: raw.origin.x, y: raw.origin.y },
    width,
    height,
    outside: raw.outside ?? 255,
    materials,
    burning: unpackBits(packed, n),
    legend: decodeLegend(raw.legend),
    player: raw.player,
    entities: Array.isArray(raw.entities) ? raw.entities : [],
  };
}

/**
 * The creature or item under a world point. A box is a few cells wide, so it is grown by `pad`
 * cells to be easy to hit; among several the one whose centre is nearest wins, and a hostile one
 * beats an item.
 * @param {Entity[]} entities
 * @param {number} wx  world column (may be fractional)
 * @param {number} wy
 * @param {number} [pad]
 * @returns {Entity|null}
 */
export function entityAt(entities, wx, wy, pad = 2) {
  let best = null;
  let bestScore = Infinity;
  for (const e of entities) {
    if (wx < e.x - pad || wx > e.x + e.w + pad || wy < e.y - pad || wy > e.y + e.h + pad) continue;
    const d = Math.hypot(wx - (e.x + e.w / 2), wy - (e.y + e.h / 2));
    const score = d - (e.hostile ? 1000 : 0);
    if (score < bestScore) {
      best = e;
      bestScore = score;
    }
  }
  return best;
}

/** Material index at a world cell, or null outside the window (or outside the world). */
export function materialAt(view, x, y) {
  const gx = x - view.origin.x;
  const gy = y - view.origin.y;
  if (gx < 0 || gy < 0 || gx >= view.width || gy >= view.height) return null;
  const m = view.materials[gy * view.width + gx];
  return m === view.outside ? null : m;
}
