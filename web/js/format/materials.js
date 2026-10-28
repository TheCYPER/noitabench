import { check, isObject, isUint } from './errors.js';

export const MATERIALS_FORMAT = 'cogbench-materials/0';
const UNKNOWN_RGB = [255, 0, 255];

/**
 * @typedef {{index:number,key:string,name_zh:string,name_en:string,kind:string,color:string}} Material
 * @typedef {{list:Material[], byIndex:(Material|undefined)[], rgb:Uint8Array, kinds:string[]}} MaterialTable
 */

/**
 * Parses content/materials.json (cogbench-materials/0).
 * `rgb` holds 256 x 3 bytes; indexes with no material are magenta so a bad
 * recording is visible instead of silently black.
 *
 * @param {unknown} json
 * @param {string} [file]
 * @returns {MaterialTable}
 */
export function parseMaterials(json, file = 'materials.json') {
  check(isObject(json), file, 'top level must be an object');
  check(json.format === MATERIALS_FORMAT, file, `format is ${JSON.stringify(json.format)}, expected "${MATERIALS_FORMAT}"`);
  check(Array.isArray(json.materials) && json.materials.length > 0, file, '"materials" must be a non-empty array');
  const byIndex = new Array(256);
  const rgb = new Uint8Array(256 * 3);
  const kinds = new Array(256).fill('');
  for (let i = 0; i < 256; i++) rgb.set(UNKNOWN_RGB, i * 3);
  for (const [n, m] of json.materials.entries()) {
    check(isObject(m), file, `materials[${n}] must be an object`);
    check(isUint(m.index) && m.index < 256, file, `materials[${n}].index must be an integer 0..255`);
    check(!byIndex[m.index], file, `materials[${n}]: index ${m.index} is used twice`);
    const hex = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(m.color));
    check(hex, file, `materials[${n}] (${m.key}): color must look like #RRGGBB`);
    rgb.set([parseInt(hex[1], 16), parseInt(hex[2], 16), parseInt(hex[3], 16)], m.index * 3);
    kinds[m.index] = String(m.kind ?? '');
    byIndex[m.index] = m;
  }
  return { list: json.materials, byIndex, rgb, kinds };
}

/**
 * Display name of a material index for the hover readout.
 * @param {MaterialTable} table
 * @param {number} index
 */
export function materialLabel(table, index) {
  const m = table.byIndex[index];
  return m ? `${m.name_zh || m.key} (${m.key})` : `unknown #${index}`;
}
