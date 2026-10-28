/**
 * Resolves a URL that came from a page's query string (`?src=`, `?world=`)
 * and accepts it only if it points at the page's own origin. The viewer
 * makes no requests to other sites: a crafted link must not be able to make
 * the browser fetch from somewhere else.
 *
 * @param {string} raw  the query value, absolute or relative
 * @param {string} base  the page URL (location.href)
 * @returns {URL}
 * @throws {Error} with a message that can be shown as is
 */
export function sameOriginUrl(raw, base) {
  let url;
  try {
    url = new URL(raw, base);
  } catch {
    throw new Error(`"${raw}" is not a valid URL`);
  }
  const here = new URL(base);
  if (url.origin !== here.origin || url.protocol !== here.protocol) {
    throw new Error(`"${raw}" is on another site (${url.origin}). Only files served by this page's own server can be opened by URL; download them and use the open buttons instead.`);
  }
  return url;
}
