/**
 * Material index -> colour. Pure functions, no DOM, so they run under node --test.
 *
 * Static terrain gets a fixed per-cell brightness variation (position based,
 * within the +-12 % allowed by contracts.md section 2) so rock and ground do
 * not look like flat paint. Moving materials keep one flat colour; position
 * based noise on a falling grain would only flicker.
 */
export const VARIANTS = 8;
const SHADE = [1, 0.95, 1.06, 0.9, 1.1, 0.97, 1.03, 0.92];

/**
 * @param {{rgb:Uint8Array,kinds:string[]}} table  from parseMaterials
 * @param {{shade?:boolean}} [opts]
 * @returns {Uint8Array} 256 * VARIANTS * 3 bytes, index (m * VARIANTS + v) * 3
 */
export function buildPalette(table, { shade = true } = {}) {
  const pal = new Uint8Array(256 * VARIANTS * 3);
  for (let m = 0; m < 256; m++) {
    const shadable = shade && table.kinds[m] === 'static';
    for (let v = 0; v < VARIANTS; v++) {
      const f = shadable ? SHADE[v] : 1;
      for (let c = 0; c < 3; c++) {
        pal[(m * VARIANTS + v) * 3 + c] = Math.min(255, Math.round(table.rgb[m * 3 + c] * f));
      }
    }
  }
  return pal;
}

/**
 * Per-cell variant numbers 0..VARIANTS-1, a function of the cell position
 * only (so a cell keeps its shade when the picture scrolls or replays).
 * @param {number} width
 * @param {number} height
 */
export function buildVariantMap(width, height) {
  const out = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let h = Math.imul(x + 0x9e37, 0x85ebca6b) ^ Math.imul(y + 0x7f4a, 0xc2b2ae35);
      h ^= h >>> 13;
      h = Math.imul(h, 0x27d4eb2f);
      out[y * width + x] = (h ^ (h >>> 15)) & (VARIANTS - 1);
    }
  }
  return out;
}

/**
 * Writes RGBA pixels for a grid of material indexes.
 * @param {Uint8Array} indices  width*height material indexes
 * @param {Uint8Array} palette  from buildPalette
 * @param {Uint8Array|null} variants  from buildVariantMap, or null for no shading
 * @param {Uint8ClampedArray|Uint8Array} out  length >= indices.length * 4
 */
export function paintRgba(indices, palette, variants, out) {
  for (let i = 0, o = 0; i < indices.length; i++, o += 4) {
    const p = (indices[i] * VARIANTS + (variants ? variants[i] : 0)) * 3;
    out[o] = palette[p];
    out[o + 1] = palette[p + 1];
    out[o + 2] = palette[p + 2];
    out[o + 3] = 255;
  }
}
