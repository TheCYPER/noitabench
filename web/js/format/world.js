import { FormatError, check, isObject, isNum, isPosInt } from './errors.js';
import { decodeIndexedPng } from './png.js';

export const WORLD_FORMAT = 'cogbench-world/0';

/**
 * @typedef {{type:string,x:number,y:number,[k:string]:any}} Marker
 * @typedef {{
 *   seed:any, ruleSeed:any, width:number, height:number, cellSize:number,
 *   biomeMap:string[][], markers:Marker[], mainPath:{x:number,y:number}[]|null
 * }} WorldMeta
 */

/**
 * Validates the JSON half of a world file pair (cogbench-world/0).
 * Unknown fields and unknown marker types are kept, never rejected.
 *
 * @param {unknown} json
 * @param {string} [file]
 * @returns {WorldMeta}
 */
export function parseWorldJson(json, file = 'world.json') {
  check(isObject(json), file, 'top level must be an object');
  check(json.format === WORLD_FORMAT, file, `format is ${JSON.stringify(json.format)}, expected "${WORLD_FORMAT}"`);
  check(isPosInt(json.width) && isPosInt(json.height), file, 'width and height must be positive integers');
  check(isPosInt(json.biome_cell_size), file, 'biome_cell_size must be a positive integer');
  check(Array.isArray(json.biome_map) && json.biome_map.every((r) => Array.isArray(r)), file, 'biome_map must be an array of rows (arrays of biome keys)');
  check(Array.isArray(json.markers), file, 'markers must be an array');
  const markers = json.markers.map((m, i) => parseMarker(m, i, file));
  return {
    seed: json.seed,
    ruleSeed: json.rule_seed,
    width: json.width,
    height: json.height,
    cellSize: json.biome_cell_size,
    biomeMap: json.biome_map.map((r) => r.map(String)),
    markers,
    mainPath: parseMainPath(json.main_path ?? (isObject(json.meta) ? json.meta.main_path : undefined), file),
  };
}

/** @returns {Marker} the marker itself, once checked */
function parseMarker(m, i, file) {
  const where = `markers[${i}]`;
  check(isObject(m), file, `${where} must be an object`);
  check(typeof m.type === 'string' && m.type !== '', file, `${where}.type must be a string`);
  check(isNum(m.x) && isNum(m.y), file, `${where} (${m.type}) needs numeric x and y`);
  if (m.type === 'encounter') {
    const t = m.trigger;
    check(isObject(t) && isNum(t.x) && isNum(t.y) && isNum(t.w) && isNum(t.h), file, `${where} (encounter ${m.encounter_id}) needs trigger {x,y,w,h} with numbers`);
  }
  return m;
}

/**
 * main_path is not in the contract; it is an optional extra that the world
 * generator may add: a list of [x, y] pairs or {x, y} objects. It is read from
 * the top level, or from `meta.main_path` where cogbench's own generator
 * writes it.
 */
function parseMainPath(raw, file) {
  if (raw === undefined || raw === null) return null;
  check(Array.isArray(raw), file, 'main_path must be an array of [x, y] points');
  return raw.map((p, i) => {
    const pt = Array.isArray(p) ? { x: p[0], y: p[1] } : p;
    check(isObject(pt) && isNum(pt.x) && isNum(pt.y), file, `main_path[${i}] must be [x, y] or {x, y}`);
    return { x: pt.x, y: pt.y };
  });
}

/**
 * Loads a world file pair into one object: the validated JSON plus the
 * material-index grid decoded from the PNG.
 *
 * @param {ArrayBuffer} pngBuffer
 * @param {unknown} json
 * @param {{png?:string,json?:string}} [names]
 * @returns {Promise<WorldMeta & {cells:Uint8Array}>}
 */
export async function loadWorld(pngBuffer, json, names = {}) {
  const jsonName = names.json ?? 'world.json';
  const pngName = names.png ?? 'world.png';
  const meta = parseWorldJson(json, jsonName);
  const img = await decodeIndexedPng(pngBuffer, pngName);
  if (img.width !== meta.width || img.height !== meta.height) {
    throw new FormatError(pngName, `PNG is ${img.width}x${img.height} but ${jsonName} says ${meta.width}x${meta.height}`);
  }
  return { ...meta, cells: img.pixels };
}

/**
 * Biome key at a world cell, or null outside the biome map.
 * @param {WorldMeta} world
 * @param {number} x  cell column
 * @param {number} y  cell row
 * @returns {string|null}
 */
export function biomeAt(world, x, y) {
  const row = world.biomeMap[Math.floor(y / world.cellSize)];
  return row ? row[Math.floor(x / world.cellSize)] ?? null : null;
}
