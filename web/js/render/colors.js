/** Stable colour for any string key (biome, entity kind, event type). */
export function hueOf(key) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  return (h >>> 0) % 360;
}

/**
 * @param {string} key
 * @param {number} [alpha]
 * @param {number} [light]  lightness in percent
 */
export function colorOf(key, alpha = 1, light = 60) {
  return `hsla(${hueOf(key)}, 65%, ${light}%, ${alpha})`;
}
