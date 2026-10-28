import test from 'node:test';
import assert from 'node:assert/strict';
import { createSync } from '../js/replay/sync.js';

/** A store whose seeks can be held back and made to fail. */
function fakeStore({ failAt = new Set() } = {}) {
  const store = {
    applied: -1,
    seeks: [],
    pending: [],
    seek(step) {
      store.seeks.push(step);
      return new Promise((resolve, reject) => {
        store.pending.push(() => {
          if (failAt.has(step)) { store.applied = -1; reject(new Error(`bad record at ${step}`)); } else { store.applied = step; resolve(step); }
        });
      });
    },
    finish() { store.pending.shift()(); },
  };
  return store;
}
const flush = () => new Promise((r) => setImmediate(r));

function hooked(store) {
  const log = [];
  const sync = createSync(store, {
    onShown: (s) => log.push(['shown', s]),
    onError: (e, s) => log.push(['error', s, e.message]),
    onSettled: () => log.push(['settled']),
  });
  return { sync, log };
}

test('one seek at a time; the wanted step is shown when it ends', async () => {
  const store = fakeStore();
  const { sync, log } = hooked(store);
  assert.equal(sync.pump(3), true);
  assert.equal(sync.pump(4), true, 'busy: the second call does nothing');
  assert.deepEqual(store.seeks, [3]);
  store.finish();
  await flush();
  assert.deepEqual([sync.shown, sync.busy], [3, false]);
  assert.deepEqual(log, [['shown', 3], ['settled']]);
  assert.equal(sync.pump(3), false, 'already shown');
  assert.equal(sync.pump(4), true);
  assert.deepEqual(store.seeks, [3, 4]);
});

test('a failed seek is reported once and not retried for the same step', async () => {
  const store = fakeStore({ failAt: new Set([5]) });
  const { sync, log } = hooked(store);
  sync.pump(5);
  store.finish();
  await flush();
  assert.deepEqual(log, [['error', 5, 'bad record at 5'], ['settled']]);
  // a page calls pump(5) on every animation frame while the clock sits on step 5
  for (let i = 0; i < 100; i++) sync.pump(5);
  await flush();
  assert.deepEqual(store.seeks, [5], 'no retry loop');
  assert.equal(sync.busy, false);
});

test('after a failure another step is tried, and the failed one can be tried again later', async () => {
  const store = fakeStore({ failAt: new Set([5]) });
  const { sync, log } = hooked(store);
  sync.pump(5); store.finish(); await flush();
  sync.pump(6); store.finish(); await flush();
  assert.equal(sync.shown, 6);
  sync.pump(5); store.finish(); await flush();
  assert.deepEqual(store.seeks, [5, 6, 5]);
  assert.deepEqual(log.filter((l) => l[0] === 'error').length, 2);
});

test('an exception in onShown is reported through onError, not lost', async () => {
  const store = fakeStore();
  const log = [];
  const sync = createSync(store, {
    onShown: () => { throw new Error('draw failed'); },
    onError: (e) => log.push(e.message),
    onSettled: () => log.push('settled'),
  });
  sync.pump(1); store.finish(); await flush();
  assert.deepEqual(log, ['draw failed', 'settled']);
  assert.equal(sync.busy, false);
});
