/**
 * JSON.parse rounds integers above 2^53, and seeds are u64. Finds such
 * integer fields by key in the raw text and returns their exact digits, so a
 * page can show the seed a user needs to reproduce a run. Display only; best
 * effort (first occurrence of the key in the file).
 *
 * @param {string} text
 * @param {string[]} keys
 * @returns {Record<string,string>}  only the keys whose value does not fit a double exactly
 */
export function exactBigInts(text, keys) {
  /** @type {Record<string,string>} */
  const out = {};
  for (const key of keys) {
    const m = new RegExp(`"${key}"\\s*:\\s*(-?\\d{16,})`).exec(text);
    if (m && !Number.isSafeInteger(Number(m[1]))) out[key] = m[1];
  }
  return out;
}
