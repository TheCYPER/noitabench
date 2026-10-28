import { lastAtOrBefore } from '../format/recording.js';
import { ZOOM_LEVELS } from '../render/view.js';

/**
 * Following the player with the camera. Pure functions, no DOM.
 */

/** Cells the view should span when following: about the 256-wide window the player sees. */
const FOLLOW_VIEW_CELLS = 256;

/**
 * The player's centre per recorded frame, from entities.jsonl.
 * @param {{frame:number, entities:{kind?:string,x:number,y:number,w?:number,h?:number}[]}[]} entities
 * @returns {{frame:number,x:number,y:number}[]}  sorted by frame, empty if the recording has no player
 */
export function playerTrack(entities) {
  const out = [];
  for (const line of entities) {
    const p = line.entities.find((e) => e.kind === 'player');
    if (p) out.push({ frame: line.frame, x: p.x + (p.w ?? 0) / 2, y: p.y + (p.h ?? 0) / 2 });
  }
  return out;
}

/**
 * Where the player was at game frame `frame` (the last record at or before it).
 * @param {{frame:number,x:number,y:number}[]} track
 * @param {number} frame
 * @returns {{x:number,y:number}|null}
 */
export function playerAt(track, frame) {
  const i = lastAtOrBefore(track, frame);
  return i < 0 ? null : track[i];
}

/**
 * Zoom level for a canvas `cssWidth` pixels wide: the largest level that still
 * shows about 256 cells across.
 * @param {number} cssWidth
 */
export function followZoom(cssWidth) {
  const want = Math.max(ZOOM_LEVELS[0], cssWidth / FOLLOW_VIEW_CELLS);
  let best = ZOOM_LEVELS[0];
  for (const z of ZOOM_LEVELS) if (z <= want) best = z;
  return best;
}
