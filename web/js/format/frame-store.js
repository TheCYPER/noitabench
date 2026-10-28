import { decodeRecord } from './recording.js';

/**
 * Rebuilds the world picture at any step of a recording.
 *
 * `state` is the material-index grid of the viewed area (the bounding box of
 * all records; the whole world for a normal recording). Records are decoded
 * lazily and kept in a byte-bounded LRU, so a long run cannot exhaust memory.
 * Seeking forward applies the steps in between (or jumps to the nearest key
 * step); seeking backward restarts from the nearest key step at or before the
 * target. A recording made of full-area frames therefore costs one decode per
 * seek, whatever the distance.
 */
export class FrameStore {
  /**
   * @param {ArrayBuffer} buffer  contents of frames.bin
   * @param {import('./recording.js').FrameIndex} index
   * @param {{file?:string,cacheBytes?:number}} [opts]
   */
  constructor(buffer, index, opts = {}) {
    this.buffer = buffer;
    this.index = index;
    this.file = opts.file ?? 'frames.bin';
    this.cacheBytes = opts.cacheBytes ?? 64 * 1024 * 1024;
    const { x0, y0, x1, y1 } = index.bbox;
    /** world coordinate of state[0] */
    this.origin = { x: x0, y: y0 };
    this.width = x1 - x0;
    this.height = y1 - y0;
    this.state = new Uint8Array(this.width * this.height);
    /** index of the step currently drawn into `state`, -1 = nothing yet */
    this.applied = -1;
    /** bumps whenever `state` changes, so a renderer knows to repaint */
    this.version = 0;
    this._cache = new Map();
    this._cacheUsed = 0;
    this._pending = new Map();
    this._queue = Promise.resolve();
  }

  /** Number of steps. */
  get length() { return this.index.steps.length; }

  /**
   * Makes `state` show step `target`. Calls are serialised; if several are
   * queued, each one still ends exactly on its own target.
   * @param {number} target
   * @returns {Promise<number>}  the applied step index
   */
  seek(target) {
    const t = Math.max(0, Math.min(this.length - 1, Math.trunc(target)));
    const run = this._queue.then(() => this._moveTo(t));
    this._queue = run.catch(() => {});
    return run;
  }

  /**
   * Fire-and-forget decode of the next few steps while playing.
   * @param {number} from  first step to decode
   * @param {number} [count]
   */
  prefetch(from, count = 3) {
    const { steps } = this.index;
    for (let s = from; s < Math.min(steps.length, from + count); s++) {
      const step = steps[s];
      for (let r = step.first; r < step.first + step.count; r++) this._decode(r).catch(() => {});
    }
  }

  async _moveTo(target) {
    if (target < this.applied) this._reset();
    // The key step is looked up once: it does not change while stepping towards `target`,
    // and looking it up per step would make a long forward seek quadratic.
    const key = this._keyAtOrBefore(target);
    while (this.applied !== target) {
      await this._apply(key > this.applied ? key : this.applied + 1);
    }
    return this.applied;
  }

  _reset() {
    this.state.fill(0);
    this.applied = -1;
  }

  /** Latest key step <= target, or -1. */
  _keyAtOrBefore(target) {
    const { steps } = this.index;
    for (let s = target; s >= 0; s--) if (steps[s].key) return s;
    return -1;
  }

  async _apply(stepIndex) {
    const step = this.index.steps[stepIndex];
    try {
      for (let r = step.first; r < step.first + step.count; r++) {
        const rec = this.index.records[r];
        if (rec.w === 0 || rec.h === 0) continue;
        this._blit(rec, await this._decode(r));
      }
    } catch (err) {
      this._reset(); // a half-applied step would leave a picture that matches no frame
      this.version++;
      throw err;
    }
    this.applied = stepIndex;
    this.version++;
  }

  _blit(rec, data) {
    const dx = rec.x0 - this.origin.x;
    const dy = rec.y0 - this.origin.y;
    if (dx === 0 && rec.w === this.width) {
      this.state.set(data, dy * this.width);
      return;
    }
    for (let row = 0; row < rec.h; row++) {
      this.state.set(data.subarray(row * rec.w, (row + 1) * rec.w), (dy + row) * this.width + dx);
    }
  }

  /** Decoded record through the LRU. @returns {Promise<Uint8Array>} */
  _decode(i) {
    const hit = this._cache.get(i);
    if (hit) {
      this._cache.delete(i);
      this._cache.set(i, hit);
      return Promise.resolve(hit);
    }
    let p = this._pending.get(i);
    if (!p) {
      p = decodeRecord(this.buffer, this.index.records[i], this.file)
        .then((data) => { this._remember(i, data); return data; })
        .finally(() => this._pending.delete(i));
      this._pending.set(i, p);
    }
    return p;
  }

  _remember(i, data) {
    this._cache.set(i, data);
    this._cacheUsed += data.length;
    for (const [k, v] of this._cache) {
      if (this._cacheUsed <= this.cacheBytes || this._cache.size <= 1) break;
      this._cache.delete(k);
      this._cacheUsed -= v.length;
    }
  }

  /** For tests and the status line. */
  get cachedRecords() { return this._cache.size; }
}
