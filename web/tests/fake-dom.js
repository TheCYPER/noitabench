/**
 * A very small stand-in for the DOM, enough for code that only builds elements
 * with `h()` and fills them with text. Installs `globalThis.document`.
 */
class FakeText {
  constructor(text) { this.text = String(text); }
  get textContent() { return this.text; }
}

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.className = '';
    this.hidden = false;
  }

  append(...nodes) {
    for (const n of nodes) this.children.push(typeof n === 'string' ? new FakeText(n) : n);
  }

  appendChild(n) { this.children.push(n); return n; }
  removeChild(n) { this.children.splice(this.children.indexOf(n), 1); return n; }
  get firstChild() { return this.children[0] ?? null; }
  get lastChild() { return this.children[this.children.length - 1] ?? null; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  addEventListener() {}

  set textContent(v) { this.children = v === '' ? [] : [new FakeText(v)]; }

  // Anything that would parse a string as markup is a bug for the replay pages: fail loudly.
  set innerHTML(v) { throw new Error(`innerHTML set on <${this.tag}>: ${String(v).slice(0, 40)}`); }
  set outerHTML(v) { throw new Error(`outerHTML set on <${this.tag}>: ${String(v).slice(0, 40)}`); }
  insertAdjacentHTML(where, v) { throw new Error(`insertAdjacentHTML on <${this.tag}>: ${String(v).slice(0, 40)}`); }
  get textContent() { return this.children.map((c) => c.textContent).join(''); }

  /** every element below (and including) this one for which `test` is true */
  find(test, out = []) {
    if (test(this)) out.push(this);
    for (const c of this.children) if (c instanceof FakeElement) c.find(test, out);
    return out;
  }
}

export function installFakeDom() {
  globalThis.document = { createElement: (tag) => new FakeElement(tag) };
  return globalThis.document;
}

/** Every element tag below `root` (and `root` itself), for checks that nothing unexpected was created. */
export const allTags = (root) => root.find(() => true).map((e) => e.tag);
/** Every text node below `root`, in order. */
export function allTexts(root, out = []) {
  for (const c of root.children) {
    if (c instanceof FakeText) out.push(c.text);
    else allTexts(c, out);
  }
  return out;
}
/** Elements whose class list contains `cls`. */
export const byClass = (root, cls) => root.find((e) => e.className.split(/\s+/).includes(cls));
/** Elements with this tag. */
export const byTag = (root, tag) => root.find((e) => e.tag === tag);
export const makeBox = () => new FakeElement('div');
