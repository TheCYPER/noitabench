import { FormatError } from './errors.js';

/**
 * Inflates a zlib stream (RFC 1950, deflate with a zlib header) with the
 * browser's built-in DecompressionStream, so no third-party library is needed.
 * 'deflate' in the Compression Streams spec means zlib-wrapped; raw deflate is
 * 'deflate-raw'.
 *
 * Only ReadableStream + getReader() are used (no Response/Blob stream
 * helpers) because those work in every browser that has DecompressionStream.
 *
 * @param {Uint8Array} bytes
 * @param {string} file  name used in error messages
 * @returns {Promise<Uint8Array>}
 */
export async function zlibInflate(bytes, file) {
  if (typeof DecompressionStream === 'undefined') {
    throw new FormatError(file, 'this browser has no DecompressionStream (need Chrome 80+, Safari 16.4+ or Firefox 113+)');
  }
  try {
    const source = new ReadableStream({
      start(controller) {
        controller.enqueue(bytes);
        controller.close();
      },
    });
    const reader = source.pipeThrough(new DecompressionStream('deflate')).getReader();
    const chunks = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      total += value.length;
    }
    const out = new Uint8Array(total);
    let at = 0;
    for (const c of chunks) {
      out.set(c, at);
      at += c.length;
    }
    return out;
  } catch (err) {
    throw new FormatError(file, `zlib data is corrupt (${err && err.message ? err.message : err})`);
  }
}
