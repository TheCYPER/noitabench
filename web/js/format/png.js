import { FormatError } from './errors.js';
import { zlibInflate } from './inflate.js';

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];

/**
 * @typedef {{width:number,height:number,pixels:Uint8Array,palette:Uint8Array}} IndexedImage
 *   pixels: one palette index per pixel, row-major. palette: RGB triples.
 */

/**
 * Decodes an indexed-colour PNG (colour type 3, bit depth 1/2/4/8, not
 * interlaced) and returns the raw palette indexes. A normal <img> decode
 * would hand back RGB and lose the indexes, which here are material ids.
 *
 * @param {ArrayBuffer|Uint8Array} input
 * @param {string} [file]
 * @returns {Promise<IndexedImage>}
 */
export async function decodeIndexedPng(input, file = 'world.png') {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  if (bytes.length < 8 || SIGNATURE.some((b, i) => bytes[i] !== b)) {
    throw new FormatError(file, 'not a PNG file (bad signature)');
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let hdr = null;
  let palette = null;
  const idat = [];
  let pos = 8;
  while (pos + 8 <= bytes.length) {
    const len = view.getUint32(pos);
    const type = String.fromCharCode(bytes[pos + 4], bytes[pos + 5], bytes[pos + 6], bytes[pos + 7]);
    const start = pos + 8;
    if (start + len > bytes.length) throw new FormatError(file, `PNG chunk ${type} is truncated`);
    const body = bytes.subarray(start, start + len);
    if (type === 'IHDR') {
      hdr = { width: view.getUint32(start), height: view.getUint32(start + 4), depth: body[8], colorType: body[9], interlace: body[12] };
    } else if (type === 'PLTE') {
      palette = body.slice();
    } else if (type === 'IDAT') {
      idat.push(body);
    } else if (type === 'IEND') {
      break;
    }
    pos = start + len + 4; // skip the CRC
  }
  if (!hdr) throw new FormatError(file, 'PNG has no IHDR chunk');
  if (hdr.colorType !== 3) throw new FormatError(file, `PNG colour type is ${hdr.colorType}, expected 3 (indexed); the world file must keep material indexes as pixel values`);
  if (![1, 2, 4, 8].includes(hdr.depth)) throw new FormatError(file, `PNG bit depth ${hdr.depth} is not valid for indexed colour`);
  if (hdr.interlace !== 0) throw new FormatError(file, 'interlaced PNG is not supported');
  if (hdr.width === 0 || hdr.height === 0) throw new FormatError(file, 'PNG has zero size');
  if (!palette) throw new FormatError(file, 'PNG has no PLTE chunk');
  if (idat.length === 0) throw new FormatError(file, 'PNG has no IDAT chunk');

  const raw = await zlibInflate(concat(idat), file);
  const stride = Math.ceil((hdr.width * hdr.depth) / 8);
  if (raw.length !== (stride + 1) * hdr.height) {
    throw new FormatError(file, `PNG pixel data is ${raw.length} bytes, expected ${(stride + 1) * hdr.height}`);
  }
  unfilter(raw, stride, hdr.height, file);
  return { width: hdr.width, height: hdr.height, pixels: unpack(raw, stride, hdr), palette };
}

/** @param {Uint8Array[]} parts */
function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

/**
 * Undoes the per-scanline filters in place. For indexed colour a pixel never
 * spans more than one byte, so the "bytes per pixel" of the filters is 1.
 * Each row keeps its filter byte in front; the data starts at row*(stride+1)+1.
 */
function unfilter(raw, stride, height, file) {
  for (let y = 0; y < height; y++) {
    const rowStart = y * (stride + 1);
    const type = raw[rowStart];
    const cur = rowStart + 1;
    const prev = y > 0 ? cur - (stride + 1) : -1;
    for (let i = 0; i < stride; i++) {
      const left = i > 0 ? raw[cur + i - 1] : 0;
      const up = prev >= 0 ? raw[prev + i] : 0;
      const upLeft = prev >= 0 && i > 0 ? raw[prev + i - 1] : 0;
      let add;
      switch (type) {
        case 0: add = 0; break;
        case 1: add = left; break;
        case 2: add = up; break;
        case 3: add = (left + up) >> 1; break;
        case 4: add = paeth(left, up, upLeft); break;
        default: throw new FormatError(file, `PNG row ${y} has unknown filter type ${type}`);
      }
      raw[cur + i] = (raw[cur + i] + add) & 255;
    }
  }
}

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

/** Expands 1/2/4-bit samples to one byte each; 8-bit rows are just copied. */
function unpack(raw, stride, { width, height, depth }) {
  const out = new Uint8Array(width * height);
  const perByte = 8 / depth;
  const mask = (1 << depth) - 1;
  for (let y = 0; y < height; y++) {
    const src = y * (stride + 1) + 1;
    if (depth === 8) {
      out.set(raw.subarray(src, src + width), y * width);
      continue;
    }
    for (let x = 0; x < width; x++) {
      const byte = raw[src + Math.floor(x / perByte)];
      const shift = 8 - depth * ((x % perByte) + 1);
      out[y * width + x] = (byte >> shift) & mask;
    }
  }
  return out;
}
