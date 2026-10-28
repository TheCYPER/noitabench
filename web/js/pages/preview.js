import { FormatError } from '../format/errors.js';
import { exactBigInts } from '../format/json.js';
import { materialLabel } from '../format/materials.js';
import { biomeAt, loadWorld } from '../format/world.js';
import { colorOf } from '../render/colors.js';
import { drawBiomeGrid, drawEncounters, drawMainPath, drawMarkers, markerStyle } from '../render/overlays.js';
import { FileSet } from '../ui/file-set.js';
import { $, clear, describeError, h, showMessage } from '../ui/dom.js';
import { shortcutAllowed } from '../ui/keys.js';
import { loadMaterials } from '../ui/load-materials.js';
import { wireOpeners } from '../ui/open-files.js';
import { sameOriginUrl } from '../ui/same-origin.js';
import { createStage } from '../ui/stage.js';

const el = {
  open: $('open'), message: $('message'), viewer: $('viewer'),
  picker: $('world-picker'), select: /** @type {HTMLSelectElement} */ ($('world-select')),
  meta: $('meta'), encounters: $('encounters'), legend: $('legend'),
  chk: {
    grid: /** @type {HTMLInputElement} */ ($('chk-grid')),
    tint: /** @type {HTMLInputElement} */ ($('chk-tint')),
    markers: /** @type {HTMLInputElement} */ ($('chk-markers')),
    encounters: /** @type {HTMLInputElement} */ ($('chk-encounters')),
    path: /** @type {HTMLInputElement} */ ($('chk-path')),
    shade: /** @type {HTMLInputElement} */ ($('chk-shade')),
  },
};

/** One plain state object; `highlight` is the encounter marker picked in the list. */
const state = { files: /** @type {FileSet|null} */ (null), pairs: [], table: null, world: null, stage: null, highlight: null };

wireOpeners({
  drop: el.open,
  folderInput: $('in-folder'), filesInput: $('in-files'),
  folderButton: $('btn-folder'), filesButton: $('btn-files'),
  onFiles: openFiles,
});

async function openFiles(files) {
  const pairs = files.worldPairs();
  if (pairs.length === 0) {
    showMessage(el.message, `No world found in the ${files.size} file(s) you opened: select a .png and a .json with the same name (for example world.png and world.json).`);
    return;
  }
  state.files = files;
  state.pairs = pairs;
  clear(el.select);
  state.pairs.forEach((p, i) => el.select.append(h('option', { value: String(i) }, p.stem)));
  el.picker.hidden = state.pairs.length < 2;
  await openWorld(state.pairs[0]);
}

async function openWorld(pair) {
  showMessage(el.message, 'Loading…', 'info');
  try {
    state.table ??= await loadMaterials(state.files);
    const png = await state.files.buffer(pair.png);
    const text = await state.files.text(pair.json);
    let json;
    try {
      json = JSON.parse(text);
    } catch (err) {
      throw new FormatError(pair.json, `not valid JSON (${err.message})`);
    }
    state.world = await loadWorld(png, json, pair);
    const big = exactBigInts(text, ['seed', 'rule_seed']);
    if (big.seed) state.world.seed = big.seed;
    if (big.rule_seed) state.world.ruleSeed = big.rule_seed;
    start(state.world);
    showMessage(el.message, '');
  } catch (err) {
    showMessage(el.message, describeError(err));
  }
}
el.select.addEventListener('change', () => openWorld(state.pairs[Number(el.select.value)]));

function start(world) {
  el.viewer.hidden = false;
  el.open.classList.add('compact');
  state.highlight = null;
  state.stage ??= createStage({
    canvas: /** @type {HTMLCanvasElement} */ ($('canvas')),
    table: state.table,
    zoomOut: $('zoom-out'), zoomIn: $('zoom-in'), zoomFit: $('zoom-fit'), zoomLabel: $('zoom-label'),
    readout: $('readout'),
    overlays: overlays,
    describeCell: (c) => `(${c.x}, ${c.y})  ${materialLabel(state.table, c.material)}  ·  ${biomeAt(state.world, c.x, c.y) ?? '—'}`,
  });
  state.stage.renderer.setShading(el.chk.shade.checked);
  state.stage.renderer.setGrid(world.cells, world.width, world.height);
  fillPanels(world);
  state.stage.fit();
}

function overlays() {
  const w = state.world;
  if (!w) return [];
  const out = [];
  if (el.chk.grid.checked) out.push((ctx, view) => drawBiomeGrid(ctx, view, w, { tint: el.chk.tint.checked, labels: true }));
  if (el.chk.path.checked) out.push((ctx, view) => drawMainPath(ctx, view, w.mainPath));
  if (el.chk.encounters.checked) out.push((ctx, view) => drawEncounters(ctx, view, w.markers, state.highlight));
  if (el.chk.markers.checked) out.push((ctx, view) => drawMarkers(ctx, view, w.markers));
  return out;
}

function fillPanels(world) {
  clear(el.meta);
  const must = world.markers.filter((m) => m.type === 'encounter' && m.must_pass === true).length;
  const rows = [
    ['size', `${world.width}×${world.height}`], ['seed', world.seed ?? '—'], ['rule_seed', world.ruleSeed ?? '—'],
    ['biome cell', `${world.cellSize} px, ${world.biomeMap[0]?.length ?? 0}×${world.biomeMap.length}`],
    ['markers', world.markers.length], ['must_pass', must], ['main_path', world.mainPath ? `${world.mainPath.length} points` : '—'],
  ];
  for (const [k, v] of rows) el.meta.append(h('dt', {}, k), h('dd', {}, String(v)));

  clear(el.encounters);
  const encs = world.markers.filter((m) => m.type === 'encounter');
  if (encs.length === 0) el.encounters.append(h('li', { className: 'empty' }, '没有遭遇点'));
  for (const m of encs) {
    const li = h('li', { className: 'mono' }, `${m.encounter_id ?? '?'} v${m.variant ?? '?'}  ${m.must_pass === true ? '★ 必经' : '可选'}  (${m.trigger.x}, ${m.trigger.y}) ${m.trigger.w}×${m.trigger.h}`);
    li.dataset.focus = '1';
    li.addEventListener('click', () => {
      state.highlight = m;
      state.stage.renderer.view.centerOn(m.trigger.x + m.trigger.w / 2, m.trigger.y + m.trigger.h / 2);
      state.stage.requestDraw();
    });
    el.encounters.append(li);
  }

  clear(el.legend);
  const counts = new Map();
  for (const m of world.markers) counts.set(m.type, (counts.get(m.type) ?? 0) + 1);
  for (const [type, n] of counts) {
    const st = markerStyle(type);
    const li = h('li', { className: 'mono' });
    const sw = h('span', { className: 'swatch' });
    sw.style.background = st.color;
    li.append(sw, `${st.glyph}  ${type} × ${n}`);
    el.legend.append(li);
  }
  const biomes = new Set(world.biomeMap.flat());
  for (const b of biomes) {
    const li = h('li', { className: 'mono' });
    const sw = h('span', { className: 'swatch' });
    sw.style.background = colorOf(b, 1, 55);
    li.append(sw, b);
    el.legend.append(li);
  }
}

for (const c of Object.values(el.chk)) {
  c.addEventListener('change', () => {
    if (c === el.chk.shade) state.stage?.renderer.setShading(c.checked);
    state.stage?.requestDraw();
  });
}

document.addEventListener('keydown', (e) => {
  if (!state.world || !shortcutAllowed(e)) return;
  const keys = { '+': () => state.stage.zoom(1), '=': () => state.stage.zoom(1), '-': () => state.stage.zoom(-1), 0: () => state.stage.fit() };
  if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
});

// Optional: ?world=<url without extension>, for example tests/fixtures/world_synthetic
const param = new URLSearchParams(location.search).get('world');
if (param) openWorldFromUrl(param);

function openWorldFromUrl(raw) {
  try {
    const url = sameOriginUrl(raw, location.href);
    const cut = url.pathname.lastIndexOf('/');
    const stem = url.pathname.slice(cut + 1);
    const dir = new URL(url.pathname.slice(0, cut + 1), url).href;
    state.files = FileSet.fromUrls(dir, [`${stem}.png`, `${stem}.json`]);
    state.pairs = [{ stem, png: `${stem}.png`, json: `${stem}.json` }];
  } catch (err) {
    showMessage(el.message, describeError(err));
    return;
  }
  openWorld(state.pairs[0]);
}
