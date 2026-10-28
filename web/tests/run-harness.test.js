import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderDecision } from '../js/replay/decision-panel.js';
import { normalizeTranscript } from '../js/format/harness-run.js';
import { buildModel, detailFor } from '../js/replay/model.js';
import { metaRows } from '../js/replay/panels.js';
import { HIDDEN_EVENT_TYPES, loadRun, visibleEvents } from '../js/replay/run.js';
import { eventsInWindow } from '../js/replay/clock.js';
import { updateSidePanels } from '../js/replay/panels.js';
import { FileSet } from '../js/ui/file-set.js';
import { allTags, allTexts, byClass, byTag, installFakeDom, makeBox } from './fake-dom.js';
import { fixtureBytes, fixtureFileSet } from './helpers.js';

installFakeDom();

const text = (...p) => fixtureBytes(...p).toString('utf8');
const harnessFiles = {
  'decisions.jsonl': text('harness_run', 'decisions.jsonl'),
  'transcript.jsonl': text('harness_run', 'transcript.jsonl'),
  'harness.jsonl': text('harness_run', 'harness.jsonl'),
  'summary.json': text('harness_run', 'summary.json'),
};
/** The synthetic recording's frames and meta, with the harness run's other files. */
const loadHarness = (extra = {}) => loadRun(fixtureFileSet('rec_synthetic', { extra: { ...harnessFiles, ...extra } }));
/** All text under an element. */
const all = (box) => box.textContent;

test('loadRun reads transcript, harness log and summary and builds the decision model', async () => {
  const run = await loadHarness();
  assert.deepEqual(run.warnings, []);
  assert.equal(run.decisions.length, 54);
  assert.equal(run.transcript.length, 36);
  assert.equal(run.harness.length, 16);
  assert.equal(run.summary.model, 'claude-haiku-5-5');
  assert.equal(run.model.marks.length, 54);
  assert.equal(run.model.hasTranscript, true);
});

test('missing optional files are not an error and not a warning', async () => {
  const run = await loadRun(fixtureFileSet('rec_synthetic_delta'));
  assert.deepEqual(run.warnings, []);
  assert.deepEqual([run.transcript, run.harness, run.summary], [[], [], null]);
  assert.deepEqual(run.model.marks, []);
  assert.equal(run.model.hasTranscript, false);
  const human = await loadRun(fixtureFileSet('rec_synthetic', { extra: { 'decisions.jsonl': text('human_run', 'decisions.jsonl') } }));
  assert.equal(human.model.marks.length, 14);
  assert.equal(human.model.hasTranscript, false);
  assert.deepEqual(human.warnings, []);
});

test('damaged harness files are warnings, the run still loads', async () => {
  const run = await loadHarness({
    'transcript.jsonl': 'not json\n{"kind":"end","over":"dead"}\n',
    'harness.jsonl': '{"call":1,"decision":0}\n[1]\n',
    'summary.json': '{oops',
  });
  assert.equal(run.transcript.length, 1);
  assert.equal(run.harness.length, 1);
  assert.equal(run.summary, null);
  const warnings = run.warnings.join('\n');
  assert.match(warnings, /transcript\.jsonl: line 1 is not valid JSON/);
  assert.match(warnings, /harness\.jsonl: line 2 is not a JSON object/);
  assert.match(warnings, /summary\.json: not valid JSON/);
});

test('a transcript with unrelated records does not break the model', async () => {
  const run = await loadHarness({ 'transcript.jsonl': '{"kind":"mystery"}\n{"kind":"assistant","purpose":"play","call":"x","decision":"y","tool_calls":"no"}\n' });
  assert.equal(run.model.marks.length, 54);
  assert.doesNotThrow(() => detailFor(run.model, 3));
});

// ------------------------------------------------------------ what the panels may show

test('the recording panel shows neither the world seed nor the rule seed', async () => {
  const meta = text('rec_synthetic', 'meta.json').replace('"seed": 42', '"seed": 18446744073709551615').replace('"rule_seed": 7', '"rule_seed": 9007199254740993');
  const run = await loadHarness({ 'meta.json': meta });
  assert.equal(run.meta.seed, '18446744073709551615', 'the reader keeps the exact seeds');
  const shown = metaRows(run).flat().join('\n');
  assert.equal(shown.includes('18446744073709551615'), false);
  assert.equal(shown.includes('9007199254740993'), false);
  assert.equal(/seed/i.test(shown), false);
  assert.equal(shown.includes('424242'), false);
  assert.equal(shown.includes('717171'), false);
  assert.match(shown, /claude-haiku-5-5/);
});

test('no decision panel text contains a seed, whatever the decision', async () => {
  const run = await loadHarness();
  for (let pos = 0; pos < run.model.marks.length; pos++) {
    const box = makeBox();
    renderDecision(box, detailFor(run.model, pos));
    renderDecision(box, detailFor(run.model, pos), { compact: true });
    const shown = all(box);
    assert.equal(/424242|717171|rule_seed|world_seed/.test(shown), false, `decision ${run.model.marks[pos].index}`);
  }
});

test('the replay and compare code never reads the world file or marker data', () => {
  const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'js');
  const files = [
    ...['replay', 'compare'].flatMap((d) => readdirSync(path.join(root, d)).map((f) => path.join(root, d, f))),
    path.join(root, 'pages', 'replay.js'), path.join(root, 'pages', 'compare.js'),
  ];
  assert.ok(files.length > 15);
  for (const f of files) {
    const src = readFileSync(f, 'utf8');
    assert.equal(/format\/world\.js|parseWorldJson|\bmarkers\b|world_\d|['"`]world\//.test(src), false, `${path.basename(f)} touches world data`);
    if (path.basename(f) === 'run.js') continue; // the loader keeps the seeds; nothing that draws may use them
    assert.equal(/\.seed\b|ruleSeed|recipe/i.test(src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '')), false, `${path.basename(f)} reads a seed or a recipe`);
  }
});

// ------------------------------------------------------------ the decision panel

test('the panel of a decision inside a program', async () => {
  const run = await loadHarness();
  const pos = run.model.marks.findIndex((m) => m.index === 12);
  const box = makeBox();
  renderDecision(box, detailFor(run.model, pos));
  const shown = all(box);
  assert.match(shown, /决策 #12/);
  assert.match(shown, /程序的第 8\/35 步/);
  assert.match(shown, /game\.aim\(angle=0\)/, 'the program text is on the panel');
  assert.match(shown, /它打印的内容/);
  assert.match(shown, /The program finished\./);
  assert.match(shown, /不完整/, 'the view is only a fragment of the printout');
  assert.match(shown, /累计 \$0\.0042/);
  assert.match(shown, /5 次模型调用/);
  assert.equal(byTag(box, 'details').length > 3, true);
});

test('the panel of the first decision: full view, thinking, tool calls, cost', async () => {
  const run = await loadHarness();
  const box = makeBox();
  renderDecision(box, detailFor(run.model, 0));
  const shown = all(box);
  assert.match(shown, /玩家看到的画面/);
  assert.match(shown, /Decision 1 \(frame 0, 0 s\)/);
  assert.match(shown, /swap_wand\(wand=1\)/);
  assert.match(shown, /With limited steps/);
  assert.match(shown, /aim\(angle=-90\)/);
  assert.match(shown, /结果：completed \(ticks\) · 20 tick · 200 帧/);
  const open = byTag(box, 'details').filter((d) => d.open).length;
  assert.ok(open >= 2, 'the view and the model turn start open');
});

test('compact mode starts with the sections closed and leaves out the cost line', async () => {
  const run = await loadHarness();
  const box = makeBox();
  renderDecision(box, detailFor(run.model, 0), { compact: true });
  assert.equal(byTag(box, 'details').filter((d) => d.open).length, 0);
  assert.equal(/累计/.test(all(box)), false);
});

test('the panel of the decision after a briefing and of the death', async () => {
  const run = await loadHarness();
  const box = makeBox();
  renderDecision(box, detailFor(run.model, run.model.marks.findIndex((m) => m.index === 174)));
  assert.match(all(box), /新一段对话从这份简报开始/);
  assert.match(all(box), /BRIEFING/);
  assert.equal(byClass(box, 'dp-brief').length, 1);
  renderDecision(box, detailFor(run.model, run.model.marks.length - 1));
  assert.equal(byClass(box, 'dp-dead').length, 1);
  assert.match(all(box), /游戏结束：dead/);
  assert.equal(/BRIEFING/.test(all(box)), false, 'the box was cleared');
});

test('the panel of a run without transcript says what is missing and still lists the command', async () => {
  const human = await loadRun(fixtureFileSet('rec_synthetic', { extra: { 'decisions.jsonl': text('human_run', 'decisions.jsonl') } }));
  const box = makeBox();
  renderDecision(box, detailFor(human.model, 0));
  const shown = all(box);
  assert.match(shown, /决策 #1/);
  assert.match(shown, /move\(direction="right", until=\{ticks: 1\}\)/);
  assert.match(shown, /没有 transcript\.jsonl/);
  assert.equal(/累计/.test(shown), false);
});

test('helpers and hooks are laid out under their turn', () => {
  const detail = {
    mark: { index: 3, frame: 10, frames: 0, endFrame: 10, stopReason: 'completed', stopDetail: '', ok: true, cost: 1, commands: ['wait()'], result: null, died: false, briefing: false },
    total: 5, label: '', observation: null, inTurn: { k: 1, count: 1 }, briefing: null, cost: null, call: null, hasTranscript: true, end: null,
    turn: {
      call: 2, first: 3, last: 3, text: 'asking for help', thinking: '', modelStop: 'tool_use', results: [{ name: 'spawn_agent', isError: false, content: '{"answer":"go left"}' }],
      toolCalls: [{ name: 'spawn_agent', text: 'spawn_agent(task="plan")', code: null }],
      programs: [{ label: 'hook 2', job: 'code', ok: true, limit: null, commands: 4, steps: 4, firstDecision: 4, ended: null, seconds: 0.1, error: '' }],
      installs: [{ name: 'networkx', ok: true, detail: 'installed', via: 'wheelhouse' }], notes: ['no usable command'],
      helpers: [{
        id: 'h1', parent: 'player', depth: 1, kind: 'spawn',
        events: [{ event: 'spawn', text: 'plan', state: '' }, { event: 'answer', text: 'go left', state: 'done' }],
        turns: [{ call: 1, text: 'thinking aloud', thinking: 'hmm', toolCalls: [{ name: 'view', text: 'view()', code: null }], results: [{ name: 'view', isError: false, content: 'Decision 3...' }] }],
      }],
    },
  };
  const box = makeBox();
  renderDecision(box, detail);
  const shown = all(box);
  assert.match(shown, /帮手 h1/);
  assert.match(shown, /派出，任务：plan/);
  assert.match(shown, /它回答：go left（done）/);
  assert.match(shown, /thinking aloud/);
  assert.match(shown, /程序和钩子（1）/);
  assert.match(shown, /hook 2 · 4 条指令 · 4 步 · 0\.1 s/);
  assert.match(shown, /networkx：成功/);
  assert.match(shown, /no usable command/);
});

// ------------------------------------------------------------ hidden events, files never read, model text is text

const events = (...extra) => text('rec_synthetic', 'events.jsonl') + extra.map((e) => `${JSON.stringify(e)}\n`).join('');

test('mix events are dropped from the list, the overlays, the counts and the warnings', async () => {
  const plain = await loadRun(fixtureFileSet('rec_synthetic'));
  const mixes = [
    { frame: 8, type: 'mix', x: 26, y: 60, potion: 'SENTINEL_POTION' },
    { frame: 30, type: 'mix', x: 1, y: 2, potion: 'SENTINEL_POTION', cells: 3, bottle: 1 },
    { frame: 31, type: ' Mix ', potion: 'SENTINEL_POTION' },
  ];
  const run = await loadRun(fixtureFileSet('rec_synthetic', { extra: { 'events.jsonl': events(...mixes) } }));
  assert.deepEqual(run.warnings, [], 'a hidden event is not a damaged line');
  assert.deepEqual(run.events, plain.events);
  assert.equal(JSON.stringify(run.events).includes('SENTINEL_POTION'), false);
  assert.equal(HIDDEN_EVENT_TYPES.has('mix'), true);
  assert.equal(metaRows(run).find(([k]) => k === 'events')[1], metaRows(plain).find(([k]) => k === 'events')[1]);
  // the overlay pass and the side list read run.events only
  for (const frame of [8, 30, 31, 100]) {
    assert.equal(eventsInWindow(run.events, frame, 45).some((e) => /mix/i.test(e.type)), false);
    const el = { entities: makeBox(), events: makeBox() };
    updateSidePanels(el, run, frame);
    assert.equal(/mix|SENTINEL_POTION/i.test(all(el.events)), false, `event list at frame ${frame}`);
  }
  assert.deepEqual(visibleEvents([{ type: 'reaction' }, { type: 'mix' }, { type: 'drink' }]).map((e) => e.type), ['reaction', 'drink'], 'reaction events stay');
});

test('a run with nothing but mix events counts as having no events', async () => {
  const run = await loadRun(fixtureFileSet('rec_synthetic', { extra: { 'events.jsonl': '{"frame":1,"type":"mix","potion":"p"}\n' } }));
  assert.equal(run.events.length, 0);
  const el = { entities: makeBox(), events: makeBox() };
  updateSidePanels(el, run, 50);
  assert.match(all(el.events), /没有 events\.jsonl/);
});

test('an optional file that cannot be read (not just absent) is a warning, and the run still opens', async () => {
  const base = fixtureFileSet('rec_synthetic', { extra: harnessFiles });
  const entries = new Map(base.entries);
  const broken = (why) => ({ arrayBuffer: async () => { throw new Error(why); }, text: async () => { throw new Error(why); } });
  for (const name of ['events.jsonl', 'transcript.jsonl', 'summary.json']) entries.set(name, broken(`HTTP 403 from /runs/x/${name}`));
  const run = await loadRun(new FileSet(entries));
  assert.equal(run.events.length, 0);
  assert.equal(run.transcript.length, 0);
  assert.equal(run.summary, null);
  assert.equal(run.model.marks.length, 54, 'the other optional files still count');
  const warnings = run.warnings.join('\n');
  for (const name of ['events.jsonl', 'transcript.jsonl', 'summary.json']) assert.match(warnings, new RegExp(`${name.replace('.', '\\.')}: could not be read \\(HTTP 403`));
  // a required file is still an error
  const noFrames = new Map(base.entries);
  noFrames.set('frames.bin', broken('HTTP 500'));
  await assert.rejects(loadRun(new FileSet(noFrames)), /HTTP 500/);
});

test('the run folder\'s world files are never opened, whatever they hold', async () => {
  const opened = [];
  const base = fixtureFileSet('rec_synthetic', { extra: harnessFiles });
  const trap = (name) => ({
    arrayBuffer: async () => { opened.push(name); throw new Error(`${name} was read`); },
    text: async () => { opened.push(name); throw new Error(`${name} was read`); },
  });
  const entries = new Map(base.entries);
  for (const name of ['world/world_42.json', 'world/world_42.png', 'workspace/notes/recipe.md', 'workspace/plugins/p.py', 'family.json']) entries.set(name, trap(name));
  const run = await loadRun(new FileSet(entries));
  assert.deepEqual(opened, []);
  assert.deepEqual(run.warnings, []);
  assert.equal(run.model.marks.length, 54);
});

/** Wraps every free-text string of a transcript in a markup payload (names, ids and structure stay as they are). */
const STRUCTURAL = new Set(['kind', 'purpose', 'stop', 'label', 'job', 'event', 'name', 'id', 'agent', 'parent', 'state', 'over', 'via']);
const PAYLOAD = '<img src=x onerror="globalThis.xss=1"><script>globalThis.xss=2</script>';
function poison(v, key = '') {
  if (typeof v === 'string') return STRUCTURAL.has(key) || /^Decision \d+ \(frame/.test(v) ? v : `${PAYLOAD}${v}`;
  if (Array.isArray(v)) return v.map((x) => poison(x, key));
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, poison(x, k)]));
  return v;
}

test('model output goes in as text: thinking, text, tool arguments, results, programs, helpers, briefing, notes', async () => {
  const records = text('harness_run', 'transcript.jsonl').trim().split('\n').map((l) => JSON.parse(l));
  const poisoned = records.map((r) => poison(r)).map((r) => JSON.stringify(r)).join('\n');
  const run = await loadHarness({
    'transcript.jsonl': poisoned,
    'decisions.jsonl': text('harness_run', 'decisions.jsonl').replace(/"stop_reason":"completed"/g, `"stop_reason":${JSON.stringify(PAYLOAD)}`),
  });
  globalThis.xss = undefined;
  let withPayload = 0;
  let bigTag = false;
  for (let pos = 0; pos < run.model.marks.length; pos++) {
    for (const opts of [{}, { compact: true }]) {
      const box = makeBox();
      renderDecision(box, detailFor(run.model, pos), opts); // an innerHTML write would throw in the fake DOM
      const tags = new Set(allTags(box));
      for (const bad of ['img', 'script', 'iframe', 'a', 'style', 'svg']) assert.equal(tags.has(bad), false, `<${bad}> in decision ${pos}`);
      if (allTexts(box).some((t) => t.includes(PAYLOAD))) withPayload++;
      bigTag ||= tags.size > 8;
    }
  }
  assert.ok(withPayload > 40, `the payload reached the panels as text (${withPayload})`);
  assert.ok(bigTag);
  assert.equal(globalThis.xss, undefined);
  const brief = makeBox();
  renderDecision(brief, detailFor(run.model, run.model.marks.findIndex((m) => m.index === 174)));
  assert.ok(allTexts(brief).some((t) => t.includes(PAYLOAD)), 'the briefing text is shown, as text');
});

test('helpers, programs, installs and notes with markup in them are text too', () => {
  const A = (o) => ({ kind: 'assistant', purpose: 'play', stop: 'tool_use', text: '', thinking: '', ...o });
  const records = poison([
    { kind: 'opening', text: 'Decision 1 (frame 0, 0 s).\nStopped: start' },
    A({ call: 1, decision: 0, thinking: 'hm', text: 'spawn one', tool_calls: [{ id: 'a', name: 'spawn_agent', arguments: { task: 'plan' } }, { id: 'b', name: 'run_code', arguments: { code: 'game.wait()' } }] }),
    { kind: 'helper', event: 'spawn', agent: 'h1', parent: 'player', depth: 1, text: 'plan' },
    A({ agent: 'h1', call: 1, purpose: 'helper', decision: 0, text: 'looking', thinking: 'ok', tool_calls: [{ id: 'c', name: 'view', arguments: { q: 'x' } }] }),
    { kind: 'results', agent: 'h1', call: 1, results: [{ id: 'c', name: 'view', is_error: true, content: 'bad' }] },
    { kind: 'helper', event: 'answer', agent: 'h1', parent: 'player', depth: 1, text: 'go', state: 'done' },
    { kind: 'code_run', label: 'run_code', job: 'code', ok: false, commands: 1, steps: 1, first_decision: 1, seconds: 0.1, error: 'Traceback', limit: 'cpu' },
    { kind: 'lib_install', name: 'networkx', ok: false, detail: 'no wheel', via: 'wheelhouse' },
    { kind: 'note', text: 'refused' },
    { kind: 'results', call: 1, decision: 1, results: [{ id: 'b', name: 'run_code', is_error: true, content: 'Decision 2 (frame 10, 1 s).\nStopped: completed' }, { id: 'a', name: 'spawn_agent', is_error: false, content: 'done' }] },
    A({ call: 2, purpose: 'summary', decision: 1, text: 'BRIEFING' }),
    { kind: 'summary', call: 2, text: 'BRIEFING' },
    { kind: 'end', over: 'dead', detail: PAYLOAD },
  ]);
  const model = buildModel({
    decisions: [{ frame: 0, index: 1, cost: 1, stop_reason: 'start', command: [{ name: 'wait', args: { s: PAYLOAD } }], result: { reason: 'completed', detail: PAYLOAD, message: PAYLOAD }, frames: 10, ok: true }],
    transcript: normalizeTranscript(records),
    harness: [],
  });
  const box = makeBox();
  renderDecision(box, detailFor(model, 0));
  const tags = new Set(allTags(box));
  for (const bad of ['img', 'script', 'iframe', 'a']) assert.equal(tags.has(bad), false);
  const texts = allTexts(box).join('\n');
  for (const where of [/帮手 h1/, /Traceback/, /networkx：失败/, /refused/, /游戏结束：dead/]) assert.match(texts, where);
  assert.ok(allTexts(box).filter((t) => t.includes(PAYLOAD)).length >= 8, 'markup shows up as plain text in many places');
});

test('the panel code has no way to write markup', () => {
  const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'js');
  const files = ['replay', 'compare', 'ui'].flatMap((d) => readdirSync(path.join(root, d)).map((f) => path.join(root, d, f)))
    .concat(['replay', 'compare'].map((p) => path.join(root, 'pages', `${p}.js`)));
  for (const f of files) {
    const src = readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment|DOMParser|\beval\(|new Function/.test(src), false, `${path.basename(f)} writes markup`);
  }
});
