import test from 'node:test';
import assert from 'node:assert/strict';
import { installFakeDom } from './fake-dom.js';
import { parseProfile } from '../js/report/profile.js';
import { SEEDS, load, raw } from './report-helpers.js';

installFakeDom();
const { renderReport } = await import('../js/report/report-view.js');
const { contributions } = await import('../js/report/summary-view.js');
const { attributionText } = await import('../js/report/extras-view.js');

const textOf = (sections) => sections.map((s) => s.textContent).join('\n');
const all = (sections, test) => sections.flatMap((s) => s.find(test));
const classes = (el) => String(el.className).split(/\s+/);

test('one profile: headline, capability bars, encounters, metrics, notes, spot-check', () => {
  const sections = renderReport([load('agent')]);
  assert.equal(sections.length, 6);
  const text = textOf(sections);
  for (const want of ['fx-agent', 'claude-haiku-5-5', '30.6', '综合分 / 100', '× 0.8 = 19.74', '× 0.2 = 10.85', '死亡', '235 个决策', '$0.0513', '47 次模型调用', '能力画像', '遭遇点', '全局指标', '「这是测试」自查']) {
    assert.ok(text.includes(want), want);
  }
  assert.ok(!text.includes('较早的评分版本'), 'this profile has the discount');
});

test('the capability chart: eleven rows, discounted and raw bars, hatch for thin, empty for unmet', () => {
  const sections = renderReport([load('agent')]);
  const chart = sections[1];
  const rows = chart.find((e) => classes(e).includes('cap-row'));
  assert.equal(rows.length, 11);
  const bars = chart.find((e) => classes(e).includes('bar'));
  assert.equal(bars.length, 11);
  const n1 = rows[0].find((e) => classes(e).includes('bar'))[0];
  assert.equal(n1.attributes['aria-label'], '72.7，打折后 43.6，机会 3 次');
  const [raw1, fill1] = n1.children;
  assert.equal(raw1.style.width, '72.73%');
  assert.equal(fill1.style.width, '43.64%');
  const n4 = rows[3];
  assert.ok(n4.find((e) => classes(e).includes('hatch')).length === 1, 'N4 had one opportunity');
  assert.ok(n4.textContent.includes('覆盖不足'));
  const n2 = rows[1].find((e) => classes(e).includes('bar'))[0];
  assert.ok(classes(n2).includes('empty'));
  assert.equal(n2.children.length, 0);
  assert.ok(rows[1].textContent.includes('未遇到，按 0 计'));
  assert.ok(chart.textContent.includes('覆盖不足（机会少于 2 次）：N4 物理直觉、N6 主动实验、N7 主动感知、N10 元认知'));
});

test('a profile from before the discount still draws, with one solid bar and a note', () => {
  const legacy = raw('agent');
  for (const c of Object.values(legacy.capabilities)) {
    delete c.discount;
    delete c.discounted_score;
  }
  const sections = renderReport([parseProfile(legacy, 'old.json')]);
  assert.ok(textOf(sections).includes('较早的评分版本'));
  const bars = sections[1].find((e) => classes(e).includes('bar') && !classes(e).includes('empty'));
  assert.ok(bars.length > 0);
  for (const bar of bars) assert.deepEqual(bar.children.map((c) => classes(c).includes('bar-raw')), [false]);
  assert.ok(!sections[1].textContent.includes('打折后的分'), 'the key does not explain a bar that is not there');
});

test('encounter blocks: met ones expanded with reasons, unmet ones on one line', () => {
  const sections = renderReport([load('agent')]);
  const enc = sections[2];
  const blocks = enc.find((e) => classes(e).includes('enc'));
  assert.equal(blocks.length, 12);
  const unmet = enc.find((e) => classes(e).includes('enc-unmet'));
  assert.equal(unmet.length, 6);
  assert.ok(unmet[0].textContent.includes('E02 熔岩河'));
  assert.ok(unmet[0].textContent.includes('没遇到'));
  const met = blocks.filter((b) => b.tag === 'details');
  assert.equal(met.length, 6);
  const e07 = met.find((b) => b.textContent.includes('E07 连环关卡'));
  assert.ok(e07.textContent.includes('第 1 次 · 第 2 层 · 帧 13355–13480 · 必经'));
  assert.ok(e07.textContent.includes('filled0 / 15never filled'));
  assert.ok(e07.textContent.includes('平均 18.2'));
  const e04 = met.find((b) => b.textContent.includes('E04'));
  assert.ok(e04.textContent.includes('未计分'));
  assert.ok(e04.textContent.includes('no lava river was tackled'));
});

test('metrics: measured with a value, the others with the reason', () => {
  const text = renderReport([load('agent')])[3].textContent;
  assert.ok(text.includes('已测 7 个，未测 11 个'));
  assert.ok(text.includes('回头路'));
  assert.ok(text.includes('climbed back 50 cells in a descent of 844'));
  assert.ok(text.includes('whether the notes were found and used'));
});

test('the headline shows the sum only when the numbers add up', () => {
  const p = load('agent');
  const sum = contributions(p);
  assert.ok(Math.abs(sum.ability - 19.744) < 1e-9 && Math.abs(sum.depth - 10.848) < 1e-9);
  assert.equal(contributions({ ...p, composite: 99 }), null);
  assert.equal(contributions({ ...p, ability: null }), null);
  const odd = structuredClone(raw('agent'));
  odd.composite = 70;
  assert.ok(!textOf(renderReport([parseProfile(odd, 'odd.json')])).includes('× 0.8 ='));
});

test('thin composites carry the evaluator\'s warning; sealed-room runs say so', () => {
  assert.ok(textOf(renderReport([load('human')])).includes('只有 2 / 11 项能力有 2 次以上的机会'));
  assert.ok(!textOf(renderReport([load('human')])).includes('thin:'), 'translated');
  const newer = raw('human');
  newer.composite_note = 'a note a newer evaluator writes';
  assert.ok(textOf(renderReport([parseProfile(newer, 'n.json')])).includes('a note a newer evaluator writes'));
  assert.ok(textOf(renderReport([load('bot')])).includes('到达封印室'));
  assert.ok(!textOf(renderReport([load('agent')])).includes('只有'));
});

test('no page shows a seed, the world file or a seed quoted in a note', () => {
  const noisy = raw('agent');
  noisy.evaluator.notes.push('the world file has seed 424242 but the recording seed 717171: the scenes may differ');
  for (const set of [[load('bot')], [load('agent')], [load('human')], [parseProfile(noisy, 'n.json')], [load('agent'), load('bot'), load('human')]]) {
    const text = textOf(renderReport(set));
    for (const seed of SEEDS) assert.ok(!text.includes(seed), seed);
    assert.ok(!text.includes('world_424242'));
    assert.ok(!/seed\W{0,3}\d/i.test(text), 'no "seed 123" on the page (the word alone is in a metric reason)');
  }
});

test('model text goes in as text: nothing is parsed as markup', () => {
  const hostile = raw('agent');
  hostile.run_id = '<b>run</b>';
  hostile.test_awareness = {
    checked_texts: 3, hits: 1, by_category: { test: 1 },
    snippets: [{ seq: 1, field: 'text', category: 'test', phrase: 'a test', snippet: 'oh <img src=x onerror=alert(1)> this is a test </p>' }],
  };
  hostile.encounters[2].visits[0].reasons = ['<script>alert(1)</script>'];
  hostile.metrics[0].reason = '<iframe src=//evil></iframe>';
  hostile.attribution = [{ capability: 'C2', layer: 2, outcome: '<i>died</i>', encounter: 'E22', nodes: ['N9'] }];
  const sections = renderReport([parseProfile(hostile, 'h.json')]); // fake DOM throws on innerHTML
  const text = textOf(sections);
  assert.ok(text.includes('<b>run</b>'));
  assert.ok(text.includes('<img src=x onerror=alert(1)>'));
  assert.ok(text.includes('<script>alert(1)</script>'));
  assert.ok(text.includes('<iframe src=//evil></iframe>'));
  for (const tag of ['img', 'script', 'iframe', 'i']) assert.equal(all(sections, (e) => e.tag === tag).length, 0, tag);
  assert.equal(all(sections, (e) => e.tag === 'b' && e.textContent === 'run').length, 0, 'the <b> in the run name stayed text');
  const marks = all(sections, (e) => e.tag === 'mark');
  assert.equal(marks.length, 1);
  assert.equal(marks[0].textContent, 'a test');
});

test('the spot-check: a count, the categories, snippets folded away', () => {
  const p = raw('agent');
  p.test_awareness = {
    checked_texts: 40, hits: 2, by_category: { test: 1, level: 1 },
    snippets: [
      { seq: 3, field: 'thinking', category: 'test', phrase: 'this is a test', snippet: 'maybe this is a test of caution' },
      { seq: 9, field: 'text', category: 'level', phrase: '关卡', snippet: '这一关卡很难' },
    ],
  };
  const section = renderReport([parseProfile(p, 'a.json')]).at(-1);
  const text = section.textContent;
  assert.ok(text.includes('命中 2 处，查了 40 段模型文字：把游戏当成测试 1 · 提到关卡或谜题 1'));
  const folded = section.find((e) => e.tag === 'details');
  assert.equal(folded.length, 1);
  assert.equal(folded[0].open, false, 'the snippets start folded');
  assert.ok(folded[0].textContent.includes('查看片段（2）'));
  assert.deepEqual(section.find((e) => e.tag === 'mark').map((m) => m.textContent), ['this is a test', '关卡']);
  assert.ok(renderReport([load('bot')]).at(-1).textContent.includes('没有可查的模型文字'));
  assert.ok(renderReport([load('agent')]).at(-1).textContent.includes('命中 0 处，查了 79 段模型文字'));
});

test('a bare profile renders without a crash', () => {
  const bare = parseProfile({ format: 'cogbench-profile/0' }, 'bare.json');
  const sections = renderReport([bare]);
  const text = textOf(sections);
  assert.ok(text.includes('综合分 / 100'));
  assert.ok(text.includes('这份 profile 没有指标'));
  assert.ok(text.includes('没有数据') === false, 'a single profile has no gap to mark');
  assert.equal(renderReport([bare, bare]).length, 6);
});

test('comparison: one table for the headline, one bar per profile in each capability row', () => {
  const sections = renderReport([load('human'), load('agent'), load('bot')]);
  assert.equal(sections.length, 6);
  const text = textOf(sections);
  assert.ok(text.includes('综合分13.7'));
  assert.ok(text.includes('30.6') && text.includes('56.2'));
  const head = sections[0].find((e) => e.tag === 'th' && e.scope === 'col');
  assert.deepEqual(head.map((th) => th.textContent), ['A fx-human', 'B fx-agent', 'C fx-bot']);
  const rows = sections[1].find((e) => classes(e).includes('cap-row'));
  assert.equal(rows.length, 11);
  assert.equal(rows[0].find((e) => classes(e).includes('bar')).length, 3);
  assert.deepEqual(rows[0].find((e) => classes(e).includes('badge')).map((b) => b.textContent), ['A', 'B', 'C']);
  const series = rows[0].find((e) => classes(e).includes('bar')).map((b) => classes(b).find((c) => c.startsWith('series-')));
  assert.deepEqual(series, ['series-1', 'series-2', 'series-3']);
  assert.ok(rows[0].find((e) => e.tag === 'details').length === 0, 'the "how this score was made" folds are single-profile only');
});

test('comparison: encounter and metric matrices, then a fold per run with its own detail', () => {
  const sections = renderReport([load('human'), load('agent')]);
  const enc = sections[2];
  const trs = enc.find((e) => e.tag === 'tr');
  assert.equal(trs.length, 13, 'a header row and one row per encounter');
  const e16 = trs.find((tr) => tr.textContent.includes('E16'));
  assert.ok(e16.textContent.includes('薄酸层'));
  assert.deepEqual(e16.find((e) => e.tag === 'td').map((td) => td.textContent), ['28.7', '70']);
  assert.ok(sections[3].find((e) => e.tag === 'tr').length === 19);
  const folds = sections[5].find((e) => classes(e).includes('run-detail'));
  assert.equal(folds.length, 2);
  assert.ok(folds[1].textContent.includes('E07 连环关卡'), 'the single-profile encounter list is inside the fold');
  assert.ok(folds[1].textContent.includes('climbed back 50 cells'));
});

test('comparison warns when the profiles were not scored by the same version', () => {
  const legacy = raw('human');
  for (const c of Object.values(legacy.capabilities)) {
    delete c.discounted_score;
    delete c.discount;
  }
  const text = textOf(renderReport([parseProfile(legacy, 'old.json'), load('agent')]));
  assert.ok(text.includes('不是同一版评分算出来的'));
  assert.ok(!textOf(renderReport([load('human'), load('agent')])).includes('不是同一版评分'));
});

test('attributions read as sentences, unknown fields are kept', () => {
  const text = attributionText({ capability: 'C2', layer: 2, outcome: 'died', frame: 16570, last_harm: { frame: 16570, source: 'hit', kind: 'hit' }, encounter: 'E22', nodes: ['N9', 'N3'] });
  assert.equal(text, 'C2 生存探索 · 第 2 层 · 死亡 · 帧 16570 · 最后一次受伤：hit / hit（帧 16570） · 所在遭遇点 E22 近路与远路（风险决策、长程规划）');
  assert.equal(attributionText({ capability: 'C3', outcome: 'ended', last_harm: null }), 'C3 获取并组装法杖 · 录像结束时还没通过');
  assert.equal(attributionText({ capability: 'C3', encounter: 'E06', reason: 'a key spell was never picked up' }), 'C3 获取并组装法杖 · 所在遭遇点 E06 封住的最深处 · 原因：a key spell was never picked up');
  assert.equal(attributionText({ outcome: '__proto__' }), '__proto__', 'a name that Object.prototype also has is shown as it is');
  assert.equal(attributionText({ capability: 'C2', x: 1234, y: 5678, seed: 424242, variant: 'v', file: 'world_1.json' }), 'C2 生存探索', 'fields the evaluator does not write are not shown');
  assert.ok(textOf(renderReport([load('agent')])).includes('C2 生存探索 · 第 2 层 · 死亡'));
  assert.ok(textOf(renderReport([load('bot')])).includes('没有需要归因的失败'));
});

test('the attribution never shows a position, a seed, a variant or a file, even when the profile carries them', () => {
  const p = raw('agent');
  p.attribution = [{ capability: 'C2', layer: 2, outcome: 'died', frame: 5, encounter: 'E22', nodes: ['N9'], seed: 424242, x: 8888, y: 9999, variant: 'SENT_VARIANT', file: 'world_SENT.json', last_harm: { frame: 5, source: 'hit', kind: 'hit', x: 7777 } }];
  const text = textOf(renderReport([parseProfile(p, 'a.json')]));
  assert.ok(text.includes('C2 生存探索 · 第 2 层 · 死亡'));
  for (const bad of ['424242', '8888', '9999', '7777', 'SENT_VARIANT', 'world_SENT']) assert.ok(!text.includes(bad), bad);
});

test('names that Object.prototype also has are plain text in the spot-check too', () => {
  const p = raw('agent');
  p.test_awareness = {
    checked_texts: 1, hits: 3, by_category: { constructor: 2, toString: 1 },
    snippets: [{ field: '__proto__', category: 'constructor', phrase: 'x', snippet: 'x' }],
  };
  const text = textOf(renderReport([parseProfile(p, 'a.json')]));
  assert.ok(text.includes('constructor 2 · toString 1'));
  assert.ok(!text.includes('native code') && !text.includes('[object'));
});

test('the bars of plain values read out their value only; capability bars also their opportunities', () => {
  const sections = renderReport([load('agent')]);
  const labels = sections[0].find((e) => classes(e).includes('bar')).map((b) => b.attributes['aria-label']);
  assert.deepEqual(labels, ['24.7', '54.2'], 'the two parts of the composite');
  assert.ok(!labels.some((l) => l.includes('机会')));
  const visit = renderReport([load('agent')])[2].find((e) => classes(e).includes('bar')).map((b) => b.attributes['aria-label']);
  assert.ok(visit.length > 0 && visit.every((l) => !l.includes('机会')));
});

test('the comparison table has a header for its first column', () => {
  const sections = renderReport([load('human'), load('agent')]);
  const first = sections[0].find((e) => e.tag === 'tr')[0].children[0];
  assert.equal(first.tag, 'th');
  assert.equal(first.textContent, '项目');
});
