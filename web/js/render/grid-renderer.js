import { buildPalette, buildVariantMap, paintRgba } from './palette.js';
import { View } from './view.js';

/**
 * Draws a material-index grid to a canvas with nearest-neighbour scaling at
 * integer zoom. Every page uses this one class; overlays are separate draw
 * functions passed to render().
 *
 * The grid is painted once into an offscreen canvas at 1 cell = 1 pixel and
 * only the visible part is scaled onto the visible canvas, so huge worlds at
 * high zoom never need a huge canvas.
 */
export class GridRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {import('../format/materials.js').MaterialTable} table
   */
  constructor(canvas, table) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false });
    this.table = table;
    this.view = new View();
    this.shade = true;
    this.palette = buildPalette(table, { shade: true });
    this.off = document.createElement('canvas');
    this.offCtx = this.off.getContext('2d');
    this.image = null;
    this.variants = null;
    /** @type {Uint8Array|null} */
    this.grid = null;
    this.width = 0;
    this.height = 0;
    this.origin = { x: 0, y: 0 };
    this.dirty = false;
  }

  /**
   * Shows `indices` (width*height) whose top-left cell is world cell `origin`.
   * The array is read at the next render, so it may be updated in place;
   * call markDirty() after changing it.
   * @param {Uint8Array} indices
   * @param {number} width
   * @param {number} height
   * @param {{x:number,y:number}} [origin]
   */
  setGrid(indices, width, height, origin = { x: 0, y: 0 }) {
    if (width !== this.width || height !== this.height) {
      this.width = width;
      this.height = height;
      this.off.width = width;
      this.off.height = height;
      this.image = this.offCtx.createImageData(width, height);
      this.variants = this.shade ? buildVariantMap(width, height) : null;
    }
    this.grid = indices;
    this.origin = origin;
    this.view.bounds = { x0: origin.x, y0: origin.y, x1: origin.x + width, y1: origin.y + height };
    this.dirty = true;
  }

  /** Tells the renderer that the grid array changed. */
  markDirty() { this.dirty = true; }

  /**
   * Turns the per-cell brightness variation of static terrain on or off.
   * @param {boolean} on
   */
  setShading(on) {
    this.shade = on;
    this.palette = buildPalette(this.table, { shade: on });
    this.variants = on && this.width ? buildVariantMap(this.width, this.height) : null;
    this.dirty = true;
  }

  /** Matches the canvas bitmap to its CSS size. Returns true if the size changed. */
  resize() {
    const dpr = window.devicePixelRatio || 1;
    const cssW = Math.max(1, Math.floor(this.canvas.clientWidth));
    const cssH = Math.max(1, Math.floor(this.canvas.clientHeight));
    const v = this.view;
    if (cssW === v.cssW && cssH === v.cssH && dpr === v.dpr) return false;
    v.cssW = cssW;
    v.cssH = cssH;
    v.dpr = dpr;
    this.canvas.width = Math.round(cssW * dpr);
    this.canvas.height = Math.round(cssH * dpr);
    v.clamp();
    return true;
  }

  /**
   * @param {Array<(ctx:CanvasRenderingContext2D, view:View)=>void>} [overlays]  drawn in order, in CSS pixels
   */
  render(overlays = []) {
    const { ctx, view } = this;
    if (this.dirty && this.grid) {
      paintRgba(this.grid, this.palette, this.variants, this.image.data);
      this.offCtx.putImageData(this.image, 0, 0);
      this.dirty = false;
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#0b0907';
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (this.grid) this._drawBase();
    ctx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
    for (const draw of overlays) draw(ctx, view);
  }

  _drawBase() {
    const { ctx, view, origin } = this;
    const gx0 = Math.max(0, Math.floor(view.ox - origin.x));
    const gy0 = Math.max(0, Math.floor(view.oy - origin.y));
    const gx1 = Math.min(this.width, Math.ceil(view.ox + view.cssW / view.zoom - origin.x));
    const gy1 = Math.min(this.height, Math.ceil(view.oy + view.cssH / view.zoom - origin.y));
    if (gx1 <= gx0 || gy1 <= gy0) return;
    const k = view.zoom * view.dpr;
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(
      this.off, gx0, gy0, gx1 - gx0, gy1 - gy0,
      Math.round((origin.x + gx0 - view.ox) * k), Math.round((origin.y + gy0 - view.oy) * k),
      Math.round((gx1 - gx0) * k), Math.round((gy1 - gy0) * k),
    );
  }

  /**
   * World cell under a point in CSS pixels relative to the canvas, or null
   * outside the grid.
   * @returns {{x:number,y:number,material:number}|null}
   */
  cellAt(px, py) {
    if (!this.grid) return null;
    const x = Math.floor(this.view.wx(px));
    const y = Math.floor(this.view.wy(py));
    const gx = x - this.origin.x;
    const gy = y - this.origin.y;
    if (gx < 0 || gy < 0 || gx >= this.width || gy >= this.height) return null;
    return { x, y, material: this.grid[gy * this.width + gx] };
  }
}
