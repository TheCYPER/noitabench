/**
 * Error raised by every reader when a file does not match its contract.
 * The message always starts with the file name so a page can show it as is.
 */
export class FormatError extends Error {
  /**
   * @param {string} file  name of the offending file, as the user knows it
   * @param {string} detail  what is wrong
   */
  constructor(file, detail) {
    super(`${file}: ${detail}`);
    this.name = 'FormatError';
    this.file = file;
    this.detail = detail;
  }
}

/** Thrown by file sources when an optional file is simply not there. */
export class NotFoundError extends Error {
  /** @param {string} path */
  constructor(path) {
    super(`${path}: file not found`);
    this.name = 'NotFoundError';
    this.path = path;
  }
}

/**
 * Asserts a condition about a parsed JSON value.
 * @param {unknown} cond
 * @param {string} file
 * @param {string} detail
 * @returns {asserts cond}
 */
export function check(cond, file, detail) {
  if (!cond) throw new FormatError(file, detail);
}

/** @param {unknown} v */
export const isObject = (v) => typeof v === 'object' && v !== null && !Array.isArray(v);
/** @param {unknown} v */
export const isUint = (v) => typeof v === 'number' && Number.isInteger(v) && v >= 0;
/** @param {unknown} v */
export const isPosInt = (v) => typeof v === 'number' && Number.isInteger(v) && v > 0;
/** @param {unknown} v */
export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
