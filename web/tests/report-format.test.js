import test from 'node:test';
import assert from 'node:assert/strict';
import { barLabel, compositeNoteText, countText, gameTimeText, isRoutineNote, outcomeParts, outcomeText, parseReason, percent, scoreText, shareText, splitSnippet, unitText, usdText } from '../js/report/format.js';
import { load } from './report-helpers.js';

test('scores: whole numbers stay whole, others get one decimal, nothing is —', () => {
  assert.equal(scoreText(100), '100');
  assert.equal(scoreText(54.24), '54.2');
  assert.equal(scoreText(0), '0');
  assert.equal(scoreText(98.96), '99');
  assert.equal(scoreText(null), '—');
  assert.equal(scoreText(undefined), '—');
  assert.equal(scoreText(NaN), '—');
  assert.equal(unitText(0.1819), '18.2');
  assert.equal(unitText(1), '100');
  assert.equal(unitText(null), '—');
});

test('money, counts and game time', () => {
  assert.equal(usdText(0.051279), '$0.0513');
  assert.equal(usdText(12.5), '$12.50');
  assert.equal(usdText(0), '$0.0000');
  assert.equal(usdText(null), '—');
  assert.equal(countText(16580), '16,580');
  assert.equal(countText(null), '—');
  assert.equal(gameTimeText(600), '10.0 s');
  assert.equal(gameTimeText(16580), '4 分 36 秒');
  assert.equal(gameTimeText(null), '—');
});

test('how a run ended', () => {
  assert.equal(outcomeText(load('agent')), '死亡');
  assert.equal(outcomeText(load('bot')), '到达封印室');
  assert.equal(outcomeText(load('human')), '录像结束，没有死亡');
  const reachedAndDied = structuredClone(load('agent'));
  reachedAndDied.depth.reachedSealedRoom = true;
  assert.deepEqual(outcomeParts(reachedAndDied), ['到达封印室', '死亡']);
  const limit = structuredClone(load('human'));
  limit.outcome.over = 'decision_limit';
  assert.deepEqual(outcomeParts(limit), ['决策用完']);
  const unknown = structuredClone(load('human'));
  unknown.outcome = { over: '', died: false, deathFrame: null, frames: null };
  assert.deepEqual(outcomeParts(unknown), ['—'], 'no outcome in the profile: no claim about the ending');
  limit.outcome.over = 'something_new';
  assert.deepEqual(outcomeParts(limit), ['结束（something_new）']);
});

test('evaluator reasons are split into criterion, points and detail', () => {
  const r = parseReason('crossed: +0.25 of 0.25 (reached the far ledge)');
  assert.deepEqual([r.criterion, r.earned, r.max, r.detail], ['crossed', 25, 25, 'reached the far ledge']);
  const partial = parseReason('unhurt: +0.09 of 0.5 (lost 50 HP to contact)');
  assert.equal(Math.round(partial.earned), 9);
  assert.equal(partial.max, 50);
  const zero = parseReason('filled: +0.00 of 0.15 (never filled)');
  assert.deepEqual([zero.earned, zero.max], [0, 15]);
  const unmeasured = parseReason('inspected: not measured (needs decisions.jsonl)');
  assert.deepEqual([unmeasured.criterion, unmeasured.earned, unmeasured.detail], ['inspected', null, '未测：needs decisions.jsonl']);
  const free = parseReason('no lava river was tackled after the ruin: nothing to apply it to');
  assert.deepEqual([free.criterion, free.earned, free.detail], ['', null, 'no lava river was tackled after the ruin: nothing to apply it to']);
  assert.equal(parseReason('x: +1 of 2 (a\nb)').detail, 'a\nb', 'a detail may span lines');
  assert.equal(parseReason('').detail, '');
});

test('every reason of the real fixtures parses to something', () => {
  for (const name of ['bot', 'agent', 'human']) {
    for (const e of load(name).encounters) for (const v of e.visits) for (const text of v.reasons) {
      const r = parseReason(text);
      assert.ok(r.detail !== '' || r.criterion !== '', text);
      if (r.earned !== null) assert.ok(r.earned >= 0 && r.earned <= r.max + 1e-9, text);
    }
  }
});

test('a snippet is cut around its phrase, whatever the case', () => {
  assert.deepEqual(splitSnippet('so This Is A Test, fine', 'this is a test'), { before: 'so ', match: 'This Is A Test', after: ', fine' });
  assert.deepEqual(splitSnippet('nothing here', 'missing'), { before: 'nothing here', match: '', after: '' });
  assert.deepEqual(splitSnippet('abc', ''), { before: 'abc', match: '', after: '' });
});

test('the screen-reader label of a bar', () => {
  const cell = { present: true, score: 72.7, discounted: 43.6, discount: 0.6, opportunities: 3, thin: false };
  assert.equal(barLabel(cell), '72.7，打折后 43.6，机会 3 次');
  assert.equal(barLabel({ ...cell, discounted: null, thin: true }), '72.7，机会 3 次，覆盖不足');
  assert.equal(barLabel({ ...cell, score: null }), '没有遇到');
  assert.equal(barLabel({ ...cell, present: false }), '没有数据');
});

test('routine capability notes are recognised, others are not', () => {
  assert.ok(isRoutineNote('no encounter met and no metric measured'));
  assert.ok(isRoutineNote('coverage too low (1 opportunities, need 2)'));
  assert.ok(!isRoutineNote('something a newer evaluator says'));
});

test('the evaluator\'s composite warnings are translated, others pass through', () => {
  assert.match(compositeNoteText('thin: only 2 of 11 capabilities were covered (2 or more opportunities); the others count at a discount'), /^只有 2 \/ 11 项能力/);
  assert.match(compositeNoteText('no capability was scored: the ability share counts as 0'), /^没有任何一项能力/);
  assert.equal(compositeNoteText('something else'), 'something else');
});

test('a tie rounds up, whatever the binary noise of x100 says', () => {
  // 0.0295 * 100 is 2.9499999999999997 in floating point, so a plain multiplication rounds this tie down
  assert.equal(percent(0.0295), 2.95);
  assert.equal(unitText(0.0295), '3');
  assert.equal(unitText(0.0055), '0.6');
  assert.equal(unitText(0.0705), '7.1');
  assert.equal(unitText(0.2865), '28.7');
  assert.equal(parseReason('x: +0.0295 of 0.0705 (d)').earned, 2.95);
  // every 4-decimal value of 0..1 shows as its 2-decimal percent rounded half up
  for (let k = 0; k <= 10000; k++) {
    const expected = Math.floor((k + 5) / 10) / 10;
    assert.equal(unitText(k / 10000), Number.isInteger(expected) ? String(expected) : expected.toFixed(1), String(k / 10000));
  }
  assert.ok(Math.abs(percent(1e-7) - 1e-5) < 1e-15, 'exponent forms fall back to a plain product');
  assert.equal(unitText(1e-7), '0');
});

test('shares of the composite keep two decimals so the parts add up', () => {
  assert.equal(shareText(0.8 * 24.68), '19.74');
  assert.equal(shareText(0.2 * 54.24), '10.85');
  assert.equal(shareText(20), '20');
  assert.equal(shareText(10.8), '10.8');
  assert.equal(shareText(null), '—');
});

test('numbers too large to round are not printed as Infinity', () => {
  assert.equal(scoreText(1e308), '—');
  assert.equal(shareText(1e308), '—');
  assert.equal(unitText(1e308), '—');
});

test('the label of a plain value has no opportunities, and an absent value is not "never met"', () => {
  assert.equal(barLabel({ present: true, score: 45.26, discounted: null, opportunities: null, thin: false }), '45.3');
  assert.equal(barLabel({ present: true, score: null, discounted: null, opportunities: null, thin: false }), '没有数据');
});
