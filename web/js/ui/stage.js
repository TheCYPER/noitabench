import { GridRenderer } from '../render/grid-renderer.js';
import { attachViewportControls } from './viewport-controls.js';

/**
 * The canvas area every page shares: renderer, pan/zoom, zoom buttons, the
 * hover readout and redraw scheduling.
 *
 * @param {{
 *   canvas: HTMLCanvasElement,
 *   table: import('../format/materials.js').MaterialTable,
 *   zoomOut: HTMLElement, zoomIn: HTMLElement, zoomFit: HTMLElement, zoomLabel: HTMLElement,
 *   readout: HTMLElement,
 *   overlays: () => Array<(ctx:CanvasRenderingContext2D, view:any)=>void>,
 *   describeCell: (cell:{x:number,y:number,material:number}) => string,
 * }} o
 */
export function createStage(o) {
  const renderer = new GridRenderer(o.canvas, o.table);
  const idleText = o.readout.textContent;
  let raf = 0;

  function drawNow() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    renderer.resize();
    renderer.render(o.overlays());
    const z = renderer.view.zoom;
    o.zoomLabel.textContent = `${z < 1 ? `1/${1 / z}` : z}×`;
  }
  function requestDraw() {
    if (!raf) raf = requestAnimationFrame(drawNow);
  }

  new ResizeObserver(requestDraw).observe(o.canvas);
  attachViewportControls(o.canvas, renderer, {
    onChange: requestDraw,
    onHover: (px, py) => {
      const cell = renderer.cellAt(px, py);
      o.readout.textContent = cell ? o.describeCell(cell) : idleText;
    },
    onLeave: () => { o.readout.textContent = idleText; },
  });
  const zoom = (dir) => { renderer.view.zoomStep(dir); requestDraw(); };
  o.zoomOut.addEventListener('click', () => zoom(-1));
  o.zoomIn.addEventListener('click', () => zoom(1));
  const fit = () => { renderer.resize(); renderer.view.fit(); requestDraw(); };
  o.zoomFit.addEventListener('click', fit);

  return { renderer, drawNow, requestDraw, zoom, fit };
}
