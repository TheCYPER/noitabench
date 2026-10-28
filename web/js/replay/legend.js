import { h } from '../ui/dom.js';
import { STOP_REASONS, stopStyle } from './timeline.js';

/**
 * Fills a box with the colour key of the decision timeline.
 * @param {HTMLElement} box
 */
export function fillLegend(box) {
  for (const r of STOP_REASONS) {
    const item = h('span', { className: 'legend-item' });
    const sw = h('span', { className: 'swatch' });
    sw.style.background = stopStyle(r).color;
    item.append(sw, `${r} ${stopStyle(r).label}`);
    box.append(item);
  }
  box.append(
    h('span', { className: 'legend-item legend-dead' }, '白柱：死亡'),
    h('span', { className: 'legend-item legend-brief' }, '▼ 新简报'),
  );
}
