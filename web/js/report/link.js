/**
 * The optional link from the replay page to the report of the same run: if `<run folder>/profile.json` exists
 * on the page's server, the replay header shows a link to `report.html` that opens it. Existence is all that is
 * checked; the replay page never reads or shows the profile.
 */

/**
 * `report.html?profile=/runs/x/profile.json` for a profile at a same-origin path.
 * @param {string} profilePath  the URL path of the profile, starting with `/`
 * @returns {string}
 */
export function reportHref(profilePath) {
  return `report.html?profile=${encodeURIComponent(profilePath)}`;
}

/**
 * The URL of the profile that would sit in the run folder at `runUrl`.
 * @param {URL} runUrl  the folder, with or without a trailing slash
 * @returns {URL}
 */
export function profileUrlFor(runUrl) {
  const path = runUrl.pathname.endsWith('/') ? runUrl.pathname : `${runUrl.pathname}/`;
  return new URL(`${path}profile.json`, runUrl.origin);
}

/**
 * The report link for a run folder, or null when there is no profile (or the server cannot say).
 * A HEAD request: nothing is downloaded.
 * @param {URL} runUrl
 * @param {typeof fetch} [fetchFn]
 * @returns {Promise<string|null>}
 */
export async function reportLinkFor(runUrl, fetchFn = fetch) {
  const profile = profileUrlFor(runUrl);
  try {
    const res = await fetchFn(profile.href, { method: 'HEAD' });
    return res.ok ? reportHref(profile.pathname) : null;
  } catch {
    return null;
  }
}
