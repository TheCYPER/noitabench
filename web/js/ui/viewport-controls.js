/**
 * Mouse, touch and wheel control of a GridRenderer's view:
 * drag = pan, wheel = zoom at the pointer, two fingers = pinch zoom.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {{view:import('../render/view.js').View}} renderer
 * @param {{onChange:()=>void, onHover?:(px:number,py:number)=>void, onLeave?:()=>void}} cb
 */
export function attachViewportControls(canvas, renderer, cb) {
  const pointers = new Map();
  let pinchBase = 0;
  let wheelAcc = 0;
  const local = (e) => {
    const r = canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, local(e));
    pinchBase = pointers.size === 2 ? distance(pointers) : 0;
    canvas.classList.add('grabbing');
  });

  canvas.addEventListener('pointermove', (e) => {
    const p = local(e);
    if (!pointers.has(e.pointerId)) {
      cb.onHover?.(p.x, p.y);
      return;
    }
    const prev = pointers.get(e.pointerId);
    pointers.set(e.pointerId, p);
    if (pointers.size === 1) {
      renderer.view.panBy(prev.x - p.x, prev.y - p.y);
      cb.onChange();
    } else if (pointers.size === 2 && pinchBase > 0) {
      const d = distance(pointers);
      const mid = midpoint(pointers);
      if (d / pinchBase > 1.35) { renderer.view.zoomStep(1, mid.x, mid.y); pinchBase = d; cb.onChange(); }
      else if (d / pinchBase < 0.74) { renderer.view.zoomStep(-1, mid.x, mid.y); pinchBase = d; cb.onChange(); }
    }
  });

  const release = (e) => {
    const was = pointers.get(e.pointerId);
    pointers.delete(e.pointerId);
    pinchBase = 0;
    if (pointers.size === 0) canvas.classList.remove('grabbing');
    // a tap (touch) shows the cell readout, like hovering does
    if (e.type === 'pointerup' && e.pointerType !== 'mouse' && was) cb.onHover?.(was.x, was.y);
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('pointerleave', (e) => { if (!pointers.has(e.pointerId)) cb.onLeave?.(); });

  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    wheelAcc += e.deltaMode === 0 ? e.deltaY : e.deltaY * 40;
    while (Math.abs(wheelAcc) >= 80) {
      const p = local(e);
      renderer.view.zoomStep(wheelAcc < 0 ? 1 : -1, p.x, p.y);
      wheelAcc -= Math.sign(wheelAcc) * 80;
      cb.onChange();
    }
  }, { passive: false });
}

function distance(pointers) {
  const [a, b] = [...pointers.values()];
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function midpoint(pointers) {
  const [a, b] = [...pointers.values()];
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}
