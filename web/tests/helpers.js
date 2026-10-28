import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { crc32, deflateSync } from 'node:zlib';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { FileSet } from '../js/ui/file-set.js';

const here = path.dirname(fileURLToPath(import.meta.url));
export const FIXTURES = path.join(here, 'fixtures');
export const MATERIALS_PATH = path.join(here, '..', '..', 'content', 'materials.json');

export const fixtureBytes = (...p) => readFileSync(path.join(FIXTURES, ...p));
/** @returns {ArrayBuffer} exactly the file's bytes */
export const fixtureBuffer = (...p) => {
  const b = fixtureBytes(...p);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
};
/**
 * A fixture folder as the page would get it from a folder picker: a FileSet of File objects.
 * `skip` leaves files out, `extra` adds or replaces files ({name: string|Buffer}).
 */
export function fixtureFileSet(dir, { skip = [], extra = {} } = {}) {
  const files = new Map();
  for (const name of readdirSync(path.join(FIXTURES, dir))) {
    if (!skip.includes(name) && !/\.md$|^expected\.json$/.test(name)) files.set(name, fixtureBytes(dir, name));
  }
  for (const [name, body] of Object.entries(extra)) files.set(name, Buffer.from(body));
  return FileSet.fromFiles([...files].map(([name, body]) => new File([body], name)));
}
export const fixtureJson = (...p) => JSON.parse(fixtureBytes(...p).toString('utf8'));
export const sha256 = (u8) => createHash('sha256').update(u8).digest('hex');

/** frames.bin record, per contracts.md section 5. */
export function record({ frame, x0 = 0, y0 = 0, w, h, data, codec = 1 }) {
  const body = codec === 1 ? deflateSync(Buffer.from(data)) : Buffer.from(data);
  const head = Buffer.alloc(17);
  head.writeUInt32LE(frame, 0);
  head.writeUInt16LE(x0, 4);
  head.writeUInt16LE(y0, 6);
  head.writeUInt16LE(w, 8);
  head.writeUInt16LE(h, 10);
  head.writeUInt8(codec, 12);
  head.writeUInt32LE(body.length, 13);
  return Buffer.concat([head, body]);
}

/** ArrayBuffer holding exactly the concatenated buffers. */
export function toArrayBuffer(...parts) {
  const b = Buffer.concat(parts);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
}

function chunk(type, body) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(body.length, 0);
  head.write(type, 4, 'latin1');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])), 0);
  return Buffer.concat([head, body, crc]);
}

/**
 * Minimal indexed-PNG encoder for tests. `filters[y]` picks the filter type
 * of row y so every filter is exercised.
 * @param {number} depth 1|2|4|8
 * @param {number[][]} rows palette indexes
 */
export function encodePng(rows, depth, palette, filters = [], { interlace = 0, colorType = 3 } = {}) {
  const width = rows[0].length;
  const height = rows.length;
  const stride = Math.ceil((width * depth) / 8);
  const scan = rows.map((r) => {
    const line = Buffer.alloc(stride);
    r.forEach((v, x) => {
      const bit = depth * x;
      line[bit >> 3] |= v << (8 - depth - (bit & 7));
    });
    return line;
  });
  const out = [];
  scan.forEach((line, y) => {
    const type = filters[y] ?? 0;
    const prev = y > 0 ? scan[y - 1] : Buffer.alloc(stride);
    const f = Buffer.alloc(stride + 1);
    f[0] = type;
    for (let i = 0; i < stride; i++) {
      const a = i > 0 ? line[i - 1] : 0;
      const b = prev[i];
      const c = i > 0 ? prev[i - 1] : 0;
      const p = a + b - c;
      const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      const pred = [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][type];
      f[i + 1] = (line[i] - pred) & 255;
    }
    out.push(f);
  });
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = depth; ihdr[9] = colorType; ihdr[12] = interlace;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr),
    chunk('PLTE', Buffer.from(palette)),
    chunk('IDAT', deflateSync(Buffer.concat(out))),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
