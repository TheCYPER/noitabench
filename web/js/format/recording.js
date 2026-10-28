import { FormatError, check, isObject, isPosInt, isUint, isNum } from './errors.js';
import { zlibInflate } from './inflate.js';

export const REC_FORMAT = 'cogbench-rec/0';
/** u32 frame | u16 x0 | u16 y0 | u16 w | u16 h | u8 codec | u32 nbytes */
export const RECORD_HEADER_BYTES = 17;

/**
 * @typedef {{frame:number,x0:number,y0:number,w:number,h:number,codec:number,nbytes:number,offset:number}} FrameRecord
 * @typedef {{frame:number,first:number,count:number,key:boolean}} Step
 *   One step = all records that share a frame number. `key` = the step alone
 *   repaints the whole viewed area, so playback can start from it.
 * @typedef {{records:FrameRecord[],steps:Step[],bbox:{x0:number,y0:number,x1:number,y1:number}}} FrameIndex
 */

/**
 * Validates meta.json (cogbench-rec/0). Unknown fields are ignored.
 * @param {unknown} json
 * @param {string} [file]
 */
export function parseMeta(json, file = 'meta.json') {
  check(isObject(json), file, 'top level must be an object');
  check(json.format === REC_FORMAT, file, `format is ${JSON.stringify(json.format)}, expected "${REC_FORMAT}"`);
  check(isObject(json.world) && isPosInt(json.world.width) && isPosInt(json.world.height), file, 'world.width and world.height must be positive integers');
  const stride = json.frame_stride === undefined ? 1 : json.frame_stride;
  check(isPosInt(stride), file, 'frame_stride must be a positive integer');
  return {
    runId: typeof json.run_id === 'string' ? json.run_id : '',
    created: json.created,
    width: json.world.width,
    height: json.world.height,
    seed: json.seed,
    ruleSeed: json.rule_seed,
    frameStride: stride,
    notes: typeof json.notes === 'string' ? json.notes : '',
  };
}

/**
 * Walks frames.bin once, reading only the 17-byte headers, and groups the
 * records into steps. Nothing is decompressed here.
 *
 * @param {ArrayBuffer} buffer
 * @param {{width:number,height:number}} world
 * @param {string} [file]
 * @returns {FrameIndex}
 */
export function indexFrames(buffer, world, file = 'frames.bin') {
  const view = new DataView(buffer);
  /** @type {FrameRecord[]} */
  const records = [];
  let pos = 0;
  let prevFrame = -1;
  while (pos < buffer.byteLength) {
    if (pos + RECORD_HEADER_BYTES > buffer.byteLength) {
      throw new FormatError(file, `truncated record header at byte ${pos} (${buffer.byteLength - pos} bytes left, need ${RECORD_HEADER_BYTES})`);
    }
    const rec = {
      frame: view.getUint32(pos, true),
      x0: view.getUint16(pos + 4, true),
      y0: view.getUint16(pos + 6, true),
      w: view.getUint16(pos + 8, true),
      h: view.getUint16(pos + 10, true),
      codec: view.getUint8(pos + 12),
      nbytes: view.getUint32(pos + 13, true),
      offset: pos + RECORD_HEADER_BYTES,
    };
    const at = `record #${records.length} at byte ${pos}`;
    if (rec.codec !== 0 && rec.codec !== 1) throw new FormatError(file, `${at}: unknown codec ${rec.codec} (0 = raw, 1 = zlib)`);
    if (rec.offset + rec.nbytes > buffer.byteLength) throw new FormatError(file, `${at}: payload of ${rec.nbytes} bytes runs past the end of the file`);
    if (rec.codec === 0 && rec.nbytes !== rec.w * rec.h) throw new FormatError(file, `${at}: raw payload is ${rec.nbytes} bytes but ${rec.w}x${rec.h} needs ${rec.w * rec.h}`);
    if (rec.x0 + rec.w > world.width || rec.y0 + rec.h > world.height) {
      throw new FormatError(file, `${at}: rectangle (${rec.x0},${rec.y0},${rec.w},${rec.h}) is outside the ${world.width}x${world.height} world`);
    }
    if (rec.frame < prevFrame) throw new FormatError(file, `${at}: frame ${rec.frame} comes after frame ${prevFrame}; frames must not go backwards`);
    prevFrame = rec.frame;
    records.push(rec);
    pos = rec.offset + rec.nbytes;
  }
  if (records.length === 0) throw new FormatError(file, 'no frame records');
  const bbox = boundingBox(records);
  if (!bbox) throw new FormatError(file, 'every record has zero area');
  return { records, steps: groupSteps(records, bbox), bbox };
}

function boundingBox(records) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const r of records) {
    if (r.w === 0 || r.h === 0) continue;
    x0 = Math.min(x0, r.x0); y0 = Math.min(y0, r.y0);
    x1 = Math.max(x1, r.x0 + r.w); y1 = Math.max(y1, r.y0 + r.h);
  }
  return x0 === Infinity ? null : { x0, y0, x1, y1 };
}

function groupSteps(records, bbox) {
  /** @type {Step[]} */
  const steps = [];
  records.forEach((r, i) => {
    const last = steps[steps.length - 1];
    const covers = r.x0 <= bbox.x0 && r.y0 <= bbox.y0 && r.x0 + r.w >= bbox.x1 && r.y0 + r.h >= bbox.y1;
    if (last && last.frame === r.frame) {
      last.count++;
      last.key = last.key || covers;
    } else {
      steps.push({ frame: r.frame, first: i, count: 1, key: covers });
    }
  });
  return steps;
}

/**
 * Decompresses one record to w*h material indexes.
 * @param {ArrayBuffer} buffer
 * @param {FrameRecord} rec
 * @param {string} [file]
 * @returns {Promise<Uint8Array>}
 */
export async function decodeRecord(buffer, rec, file = 'frames.bin') {
  const payload = new Uint8Array(buffer, rec.offset, rec.nbytes);
  const data = rec.codec === 0 ? payload : await zlibInflate(payload, file);
  if (data.length !== rec.w * rec.h) {
    throw new FormatError(file, `record for frame ${rec.frame}: decoded ${data.length} bytes but ${rec.w}x${rec.h} needs ${rec.w * rec.h}`);
  }
  return data;
}

/**
 * Parses a JSON Lines file. Bad lines are collected, not thrown, because
 * entities/events/decisions are optional overlays: a damaged line must not
 * stop playback, but the page can still tell the user about it.
 *
 * @param {string} text
 * @param {string} file
 * @returns {{items:object[],errors:string[]}}
 */
export function parseJsonl(text, file) {
  const items = [];
  const errors = [];
  text.split('\n').forEach((line, i) => {
    if (line.trim() === '') return;
    try {
      const v = JSON.parse(line);
      if (isObject(v)) items.push(v);
      else errors.push(`${file}: line ${i + 1} is not a JSON object`);
    } catch {
      errors.push(`${file}: line ${i + 1} is not valid JSON`);
    }
  });
  return { items, errors };
}

/**
 * entities.jsonl lines -> [{frame, entities:[{id,kind,x,y,w,h,hp,hp_max}]}] sorted by frame.
 * @param {object[]} items
 */
export function normalizeEntities(items) {
  return items
    .filter((l) => isUint(l.frame) && Array.isArray(l.entities))
    .map((l) => ({ frame: l.frame, entities: l.entities.filter((e) => isObject(e) && isNum(e.x) && isNum(e.y)) }))
    .sort((a, b) => a.frame - b.frame);
}

/**
 * events.jsonl lines -> events sorted by frame (stable). Unknown types and
 * extra fields are kept as they are.
 * @param {object[]} items
 */
export function normalizeEvents(items) {
  return items
    .filter((e) => isUint(e.frame) && typeof e.type === 'string')
    .map((e, i) => ({ e, i }))
    .sort((a, b) => a.e.frame - b.e.frame || a.i - b.i)
    .map(({ e }) => e);
}

/**
 * Index of the last element with `frame <= target`, or -1 if none.
 * Works on any array sorted by a numeric `frame` property.
 * @param {{frame:number}[]} sorted
 * @param {number} target
 */
export function lastAtOrBefore(sorted, target) {
  let lo = 0;
  let hi = sorted.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (sorted[mid].frame <= target) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}
