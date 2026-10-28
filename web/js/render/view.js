/** Zoom steps: integers from 1 up, plus 1/2 and 1/4 to see a big world at once. */
export const ZOOM_LEVELS = [0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24];

/**
 * Camera over the world. (ox, oy) is the world coordinate at the top-left of
 * the canvas; sizes are in CSS pixels. Overlays draw through sx/sy.
 */
export class View {
  constructor() {
    this.zoom = 1;
    this.ox = 0;
    this.oy = 0;
    this.cssW = 0;
    this.cssH = 0;
    this.dpr = 1;
    /** world rectangle that may be looked at */
    this.bounds = { x0: 0, y0: 0, x1: 1, y1: 1 };
  }

  /** @param {number} wx world column @returns {number} canvas x in CSS pixels */
  sx(wx) { return (wx - this.ox) * this.zoom; }
  /** @param {number} wy world row @returns {number} canvas y in CSS pixels */
  sy(wy) { return (wy - this.oy) * this.zoom; }
  /** @param {number} px canvas x in CSS pixels @returns {number} world column (fractional) */
  wx(px) { return px / this.zoom + this.ox; }
  /** @param {number} py canvas y in CSS pixels @returns {number} world row (fractional) */
  wy(py) { return py / this.zoom + this.oy; }

  /**
   * Largest zoom level that shows the whole bounds, never above `max`.
   * @param {number} [max]
   */
  fitZoom(max = 8) {
    const w = this.bounds.x1 - this.bounds.x0;
    const h = this.bounds.y1 - this.bounds.y0;
    const want = Math.min(this.cssW / w, this.cssH / h);
    let best = ZOOM_LEVELS[0];
    for (const z of ZOOM_LEVELS) if (z <= want && z <= max) best = z;
    return best;
  }

  /** Keeps the camera on the world: centred when smaller than the canvas, clamped otherwise, snapped to whole device pixels. */
  clamp() {
    const step = 1 / (this.zoom * this.dpr);
    const axis = (o, lo, hi, size) => {
      const span = size / this.zoom;
      const c = hi - lo <= span ? lo - (span - (hi - lo)) / 2 : Math.min(Math.max(o, lo), hi - span);
      return Math.round(c / step) * step;
    };
    this.ox = axis(this.ox, this.bounds.x0, this.bounds.x1, this.cssW);
    this.oy = axis(this.oy, this.bounds.y0, this.bounds.y1, this.cssH);
  }

  /**
   * Changes zoom keeping the world point under (px, py) fixed.
   * @param {number} zoom
   * @param {number} [px]  CSS pixels, default the canvas centre
   * @param {number} [py]
   */
  zoomTo(zoom, px = this.cssW / 2, py = this.cssH / 2) {
    const wx = this.wx(px);
    const wy = this.wy(py);
    this.zoom = zoom;
    this.ox = wx - px / zoom;
    this.oy = wy - py / zoom;
    this.clamp();
  }

  /**
   * One zoom level in (+1) or out (-1).
   * @param {1|-1} dir
   * @param {number} [px]
   * @param {number} [py]
   */
  zoomStep(dir, px, py) {
    let i = ZOOM_LEVELS.findIndex((z) => z >= this.zoom);
    if (i < 0) i = ZOOM_LEVELS.length - 1;
    const next = Math.max(0, Math.min(ZOOM_LEVELS.length - 1, i + dir));
    this.zoomTo(ZOOM_LEVELS[next], px, py);
  }

  /** Moves the camera by a drag distance in CSS pixels. */
  panBy(dxCss, dyCss) {
    this.ox += dxCss / this.zoom;
    this.oy += dyCss / this.zoom;
    this.clamp();
  }

  /** Puts world point (wx, wy) in the middle of the canvas. */
  centerOn(wx, wy) {
    this.ox = wx - this.cssW / 2 / this.zoom;
    this.oy = wy - this.cssH / 2 / this.zoom;
    this.clamp();
  }

  /** Zoom to fit the whole bounds and show them from their top-left corner. */
  fit() {
    this.zoom = this.fitZoom();
    this.ox = this.bounds.x0;
    this.oy = this.bounds.y0;
    this.clamp();
  }
}
