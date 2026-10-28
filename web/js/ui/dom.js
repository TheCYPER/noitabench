/** Small DOM helpers shared by the pages. */

/**
 * Element by id; throws if the page does not have it.
 * @param {string} id
 * @returns {HTMLElement}
 */
export function $(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`page is missing the element #${id}`);
  return el;
}

/**
 * Creates an element; `text` goes in as text, never as HTML.
 * @param {string} tag
 * @param {Record<string, any>} [props]  assigned to the element (className, value, ...)
 * @param {string} [text]
 * @returns {HTMLElement}
 */
export function h(tag, props = {}, text = '') {
  const el = document.createElement(tag);
  Object.assign(el, props);
  if (text !== '') el.textContent = text;
  return el;
}

/**
 * Shows a status line. kind: 'error' | 'info' | 'warn'. Empty text hides it.
 * @param {HTMLElement} el
 * @param {string} text
 * @param {'error'|'info'|'warn'} [kind]
 */
export function showMessage(el, text, kind = 'error') {
  el.textContent = text;
  el.className = `message ${kind}`;
  el.hidden = text === '';
}

/**
 * Text of any thrown value, without a stack.
 * @param {unknown} err
 * @returns {string}
 */
export function describeError(err) {
  if (err && typeof err.message === 'string') return err.message;
  return String(err);
}

/**
 * Short, single-line summary of the extra fields of a JSON object.
 * @param {Record<string, any>} obj
 * @param {string[]} [skip]  keys to leave out
 * @returns {string}
 */
export function summarize(obj, skip = []) {
  const parts = [];
  for (const [k, v] of Object.entries(obj)) {
    if (skip.includes(k)) continue;
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`);
  }
  const s = parts.join(' ');
  return s.length > 70 ? `${s.slice(0, 67)}…` : s;
}

/**
 * Clears an element's children.
 * @param {HTMLElement} el
 */
export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}
