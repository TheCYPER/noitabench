import { FormatError, NotFoundError } from '../format/errors.js';

/**
 * A set of files the user gave us (folder picker, file picker, drag and drop)
 * or that a web server serves (`?src=`). Paths use `/` and are relative to
 * whatever the user picked, e.g. `run_0001/meta.json`.
 *
 * Entries are anything with `arrayBuffer()` and `text()`: a File, or the lazy
 * URL entries made by `fromUrls`. Nothing is read until a page asks for it.
 */
export class FileSet {
  /** @param {Map<string,{arrayBuffer():Promise<ArrayBuffer>,text():Promise<string>}>} entries */
  constructor(entries) {
    this.entries = entries;
  }

  /** @param {Iterable<File>} files  from <input type=file> */
  static fromFiles(files) {
    const m = new Map();
    for (const f of files) m.set(normalize(f.webkitRelativePath || f.name), f);
    return new FileSet(m);
  }

  /**
   * Reads a drop. Directory entries must be collected synchronously inside the
   * drop event, so call this directly from the handler.
   * @param {DataTransfer} dt
   */
  static async fromDataTransfer(dt) {
    const roots = [];
    for (const item of dt.items ?? []) {
      const entry = item.kind === 'file' && item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry) roots.push(entry);
    }
    if (roots.length === 0) return FileSet.fromFiles(dt.files);
    const m = new Map();
    for (const e of roots) await walk(e, '', m, { left: 20000 });
    return new FileSet(m);
  }

  /**
   * Files served over HTTP. `names` are paths under the directory URL
   * `baseUrl`; a 404 turns into NotFoundError, which readers treat as
   * "file absent". A name that would leave the directory (an absolute URL,
   * `//host/x`) is refused, so nothing but files below `baseUrl` is fetched.
   * @param {string} baseUrl
   * @param {string[]} names
   */
  static fromUrls(baseUrl, names) {
    const base = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`;
    const m = new Map();
    for (const n of names) {
      const href = new URL(n, base).href;
      if (!href.startsWith(base)) throw new Error(`${n}: not inside ${base}`);
      m.set(n, urlEntry(href, n));
    }
    return new FileSet(m);
  }

  /** @returns {string[]} every path in the set */
  paths() { return [...this.entries.keys()]; }
  /** @param {string} path @returns {boolean} */
  has(path) { return this.entries.has(path); }
  /** @returns {number} how many files the set holds */
  get size() { return this.entries.size; }

  /** @returns {string[]} directories that hold both meta.json and frames.bin ('' = top level) */
  runDirs() {
    const dirs = [];
    for (const p of this.entries.keys()) {
      if (basename(p) !== 'meta.json') continue;
      const d = dirname(p);
      if (this.entries.has(join(d, 'frames.bin'))) dirs.push(d);
    }
    return dirs.sort();
  }

  /** @returns {{stem:string,png:string,json:string}[]} files that have both a .png and a .json of the same name */
  worldPairs() {
    const out = [];
    for (const p of this.entries.keys()) {
      if (!p.toLowerCase().endsWith('.png')) continue;
      const stem = p.slice(0, -4);
      const json = [stem + '.json', stem + '.JSON'].find((j) => this.entries.has(j));
      if (json) out.push({ stem, png: p, json });
    }
    return out.sort((a, b) => a.stem.localeCompare(b.stem));
  }

  /**
   * The same files seen from inside `dir`.
   * @param {string} dir  '' = the whole set
   * @returns {FileSet}
   */
  within(dir) {
    if (dir === '') return this;
    const m = new Map();
    for (const [p, e] of this.entries) if (p.startsWith(dir + '/')) m.set(p.slice(dir.length + 1), e);
    return new FileSet(m);
  }

  /** @returns {Promise<ArrayBuffer>} @throws {NotFoundError} */
  async buffer(path) { return this._entry(path).arrayBuffer(); }
  /** @returns {Promise<string>} @throws {NotFoundError} */
  async text(path) { return this._entry(path).text(); }
  /**
   * @returns {Promise<any>}
   * @throws {NotFoundError} when absent
   * @throws {FormatError} when the text is not JSON
   */
  async json(path) {
    const text = await this.text(path);
    try {
      return JSON.parse(text);
    } catch (err) {
      throw new FormatError(path, `not valid JSON (${err.message})`);
    }
  }

  /** Like text() but null when the file is not there. */
  async optionalText(path) {
    try {
      return await this.text(path);
    } catch (err) {
      if (err instanceof NotFoundError) return null;
      throw err;
    }
  }

  _entry(path) {
    const e = this.entries.get(path);
    if (!e) throw new NotFoundError(path);
    return e;
  }
}

function urlEntry(url, path) {
  const get = async () => {
    let res;
    try {
      res = await fetch(url);
    } catch (err) {
      throw new Error(`${path}: could not fetch ${url} (${err.message}). Open the page through a web server, not file://`);
    }
    if (res.status === 404) throw new NotFoundError(path);
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status} from ${url}`);
    return res;
  };
  return {
    arrayBuffer: async () => (await get()).arrayBuffer(),
    text: async () => (await get()).text(),
  };
}

async function walk(entry, prefix, out, budget) {
  if (budget.left <= 0 || entry.name.startsWith('.')) return;
  if (entry.isFile) {
    budget.left--;
    out.set(normalize(prefix + entry.name), await new Promise((res, rej) => entry.file(res, rej)));
  } else if (entry.isDirectory) {
    const reader = entry.createReader();
    for (;;) {
      const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
      if (batch.length === 0) break;
      for (const child of batch) await walk(child, `${prefix}${entry.name}/`, out, budget);
    }
  }
}

const normalize = (p) => p.replace(/\\/g, '/').replace(/^\.?\//, '');
const basename = (p) => p.slice(p.lastIndexOf('/') + 1);
const dirname = (p) => (p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '');
const join = (d, n) => (d === '' ? n : `${d}/${n}`);
