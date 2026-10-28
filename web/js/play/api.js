import { sameOriginUrl } from '../ui/same-origin.js';

/**
 * The play server's JSON API (play/app.py). Every URL is resolved against the page and must stay
 * on the page's own origin; the page talks to no other site.
 */
export class ApiError extends Error {
  /**
   * @param {string} code  machine word (`no_server`, `closed`, `bad_request`, ...)
   * @param {string} message  text for the player
   * @param {number} [status]  HTTP status, 0 when the server could not be reached
   */
  constructor(code, message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

/**
 * @param {string} pageUrl  the page's own URL (location.href)
 * @param {typeof fetch} [fetchImpl]
 */
export function createApi(pageUrl, fetchImpl = globalThis.fetch?.bind(globalThis)) {
  const urlOf = (path) => sameOriginUrl(new URL(`../api/${path}`, pageUrl).href, pageUrl).href;

  async function call(path, body) {
    const init = body === undefined
      ? { method: 'GET', cache: 'no-store' }
      : { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    let res;
    try {
      res = await fetchImpl(urlOf(path), init);
    } catch (err) {
      throw new ApiError('no_server', `Cannot reach the play server (${err.message}). Start it with: python -m noitabench play serve --world-seed 3`);
    }
    let data = null;
    try {
      data = await res.json();
    } catch {
      /* not JSON: reported below */
    }
    if (!res.ok || data === null) {
      const e = data?.error;
      throw new ApiError(e?.code ?? 'http', e?.message ?? `The server answered HTTP ${res.status}. Is this page served by "python -m noitabench play serve"?`, res.status);
    }
    return data;
  }

  return {
    hello: () => call('hello'),
    state: () => call('state'),
    /** @param {{text?:string, commands?:object[]}} request */
    decide: (request) => call('decide', request),
    /** @param {{op:'list'|'read'|'write'|'edit'|'search'} & Record<string, any>} request */
    notes: (request) => call('notes', request),
    close: () => call('close', {}),
  };
}
