import { describeError } from '../ui/dom.js';
import { sameOriginUrl } from '../ui/same-origin.js';
import { MAX_PROFILES } from './chart-data.js';
import { parseProfileText } from './profile.js';

/** JSON files of a run folder that are certainly not a profile. */
const RUN_FILES = /^(meta|summary|family|materials)\.json$/i;
/** A profile is some tens of kilobytes; anything much larger is not one and is not read. */
const MAX_BYTES = 5 * 1024 * 1024;

/**
 * Which of the opened paths are profiles. `profile.json` and `<name>.profile.json` anywhere in what was
 * opened; if nothing is named like that, any `.json` file picked by itself (not inside a folder).
 * @param {string[]} paths  paths with `/`, as a FileSet holds them
 * @returns {string[]}
 */
export function profilePaths(paths) {
  const base = (p) => p.slice(p.lastIndexOf('/') + 1);
  const named = paths.filter((p) => /(^|\.)profile\.json$/i.test(base(p)));
  if (named.length > 0) return named.sort();
  return paths.filter((p) => !p.includes('/') && /\.json$/i.test(p) && !RUN_FILES.test(p)).sort();
}

/**
 * Reads the profiles among the files the user opened or dropped.
 * @param {import('../ui/file-set.js').FileSet} files
 * @returns {Promise<{profiles: import('./profile.js').Profile[], warnings: string[]}>}
 */
export async function loadFromFiles(files) {
  const profiles = [];
  const warnings = [];
  const paths = profilePaths(files.paths());
  if (paths.length === 0) warnings.push(`在你打开的 ${files.size} 个文件里没有找到 profile.json（用 python -m noitabench eval <录像文件夹> 生成）。`);
  for (const path of paths) {
    try {
      const size = files.entries.get(path)?.size;
      if (typeof size === 'number' && size > MAX_BYTES) throw new Error(`${path}: file is ${size} bytes, too large for a profile`);
      profiles.push(parseProfileText(await files.text(path), path));
    } catch (err) {
      warnings.push(describeError(err));
    }
  }
  return { profiles, warnings };
}

/**
 * Fetches `?profile=` URLs. Each must be on the page's own origin; a failure names the URL and the others still load.
 * @param {string[]} values  the query values, absolute or relative to the page
 * @param {string} base  the page URL
 * @param {typeof fetch} [fetchFn]
 * @returns {Promise<{profiles: import('./profile.js').Profile[], warnings: string[]}>}
 */
export async function loadFromUrls(values, base, fetchFn = fetch) {
  const profiles = [];
  const warnings = [];
  for (const raw of values.slice(0, MAX_PROFILES)) {
    try {
      const url = sameOriginUrl(raw, base);
      const res = await fetchFn(url.href);
      if (!res.ok) throw new Error(`${raw}: HTTP ${res.status}${res.status === 404 ? '（没有这个文件；先用 python -m noitabench eval 生成）' : ''}`);
      profiles.push(parseProfileText(await res.text(), nameOf(url)));
    } catch (err) {
      warnings.push(describeError(err));
    }
  }
  if (values.length > MAX_PROFILES) warnings.push(`最多同时看 ${MAX_PROFILES} 份，其余 ${values.length - MAX_PROFILES} 份没有打开。`);
  return { profiles, warnings };
}

/** `descend-42/profile.json`: the last two parts of the path, for messages and as the label of last resort. */
function nameOf(url) {
  return decodeURIComponent(url.pathname).split('/').filter(Boolean).slice(-2).join('/');
}
