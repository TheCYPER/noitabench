import { FormatError } from '../format/errors.js';
import { parseMaterials } from '../format/materials.js';

const SERVED_NAME = 'content/materials.json';

/**
 * Finds materials.json: first next to the served repo (../content/materials.json
 * relative to the page, same origin), then among the files the user opened.
 *
 * @param {import('./file-set.js').FileSet|null} files
 * @returns {Promise<import('../format/materials.js').MaterialTable>}
 * @throws {FormatError} when no copy is found or a copy is not valid
 */
export async function loadMaterials(files) {
  const url = new URL('../content/materials.json', document.baseURI).href;
  let fetchProblem = '';
  try {
    const res = await fetch(url);
    if (res.ok) return parseServed(await res.text());
    fetchProblem = `HTTP ${res.status}`;
  } catch (err) {
    if (err instanceof FormatError) throw err;
    fetchProblem = err.message;
  }
  const own = files?.paths().find((p) => p === 'materials.json' || p.endsWith('/materials.json'));
  if (own) return parseMaterials(await files.json(own), own);
  throw new FormatError(
    'materials.json',
    `not found (${url}: ${fetchProblem}). Serve the repository root over http (see web/README.md) or open materials.json together with your files.`,
  );
}

function parseServed(text) {
  let json;
  try {
    json = JSON.parse(text);
  } catch (err) {
    throw new FormatError(SERVED_NAME, `not valid JSON (${err.message})`);
  }
  return parseMaterials(json, SERVED_NAME);
}
