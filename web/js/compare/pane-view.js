import { h } from '../ui/dom.js';

/**
 * The DOM of one compare pane: title, canvas, zoom buttons, a line about the
 * current decision and a collapsed decision panel. No state, no game logic.
 *
 * @param {{title:string, sub:string, onRemove:()=>void}} o
 */
export function buildPaneView(o) {
  const root = h('div', { className: 'pane' });
  const canvas = /** @type {HTMLCanvasElement} */ (h('canvas', { tabIndex: 0 }));
  canvas.setAttribute('aria-label', `${o.title} 的画面`);
  const zoomOut = h('button', { type: 'button', title: '缩小' }, '−');
  const zoomIn = h('button', { type: 'button', title: '放大' }, '+');
  const zoomFit = h('button', { type: 'button', title: '适应窗口' }, '适应');
  const zoomLabel = h('span', { className: 'mono' });
  const remove = h('button', { type: 'button', title: '去掉这个录像' }, '✕');
  remove.setAttribute('aria-label', `去掉 ${o.title}`);
  remove.addEventListener('click', o.onRemove);

  const tools = h('span', { className: 'pane-tools' });
  tools.append(zoomOut, zoomLabel, zoomIn, zoomFit, remove);
  const head = h('div', { className: 'pane-head' });
  head.append(h('span', { className: 'pane-title' }, o.title), h('span', { className: 'pane-sub' }, o.sub), tools);
  const stage = h('div', { className: 'stage' });
  stage.append(canvas);
  const readout = h('div', { className: 'readout' }, '移动指针查看格子');
  const now = h('div', { className: 'pane-now mono' });
  const details = h('details', { className: 'pane-decision' });
  const box = h('div', { className: 'dp dp-box' });
  details.append(h('summary', {}, '这一步的内容'), box);
  root.append(head, stage, readout, now, details);
  return { root, canvas, zoomOut, zoomIn, zoomFit, zoomLabel, readout, now, details, box };
}

/**
 * Writes the "now" line of a pane.
 * @param {HTMLElement} el
 * @param {{text:string, ended:boolean}} info
 */
export function showNow(el, info) {
  el.textContent = info.text;
  if (info.ended) el.append(h('span', { className: 'ended' }, '  · 已结束'));
}
