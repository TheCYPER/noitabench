import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, createApi } from '../js/play/api.js';

const PAGE = 'http://127.0.0.1:8765/web/play.html';

function fake(responses) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const r = responses.shift();
    if (r instanceof Error) throw r;
    return { ok: r.status < 400, status: r.status, json: async () => { if (r.body === undefined) throw new Error('no json'); return r.body; } };
  };
  return { fetchImpl, calls };
}

test('requests go to ../api/ of the page, GET without a body, POST with JSON', async () => {
  const { fetchImpl, calls } = fake([{ status: 200, body: { ok: true } }, { status: 200, body: { ok: true, cost: 1 } }]);
  const api = createApi(PAGE, fetchImpl);
  await api.state();
  const res = await api.decide({ commands: [{ name: 'kick', args: {} }] });
  assert.equal(res.cost, 1);
  assert.equal(calls[0].url, 'http://127.0.0.1:8765/api/state');
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[1].url, 'http://127.0.0.1:8765/api/decide');
  assert.equal(calls[1].init.method, 'POST');
  assert.equal(calls[1].init.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[1].init.body), { commands: [{ name: 'kick', args: {} }] });
});

test('notes and close are POSTs of their own', async () => {
  const { fetchImpl, calls } = fake([{ status: 200, body: { ok: true, result: {} } }, { status: 200, body: { ok: true, summary: {} } }]);
  const api = createApi(PAGE, fetchImpl);
  await api.notes({ op: 'list' });
  await api.close();
  assert.equal(calls[0].url, 'http://127.0.0.1:8765/api/notes');
  assert.deepEqual(JSON.parse(calls[0].init.body), { op: 'list' });
  assert.equal(calls[1].url, 'http://127.0.0.1:8765/api/close');
});

test('a game-level refusal (ok:false, HTTP 200) is data, not an exception', async () => {
  const { fetchImpl } = fake([{ status: 200, body: { ok: false, answer: { stop: { reason: 'invalid' } } } }]);
  const res = await createApi(PAGE, fetchImpl).decide({ text: 'nonsense()' });
  assert.equal(res.ok, false);
});

test('a transport error carries the code and message of the server', async () => {
  const { fetchImpl } = fake([{ status: 409, body: { ok: false, error: { code: 'closed', message: 'The session has ended.' } } }]);
  await assert.rejects(createApi(PAGE, fetchImpl).decide({ text: 'wait' }), (e) => e instanceof ApiError && e.code === 'closed' && e.status === 409 && /ended/.test(e.message));
});

test('a server that is not the play server is explained', async () => {
  const { fetchImpl } = fake([{ status: 404 }]);
  await assert.rejects(createApi(PAGE, fetchImpl).state(), (e) => e.code === 'http' && /play serve/.test(e.message));
});

test('no server at all is explained with the command to start one', async () => {
  const { fetchImpl } = fake([new TypeError('fetch failed')]);
  await assert.rejects(createApi(PAGE, fetchImpl).state(), (e) => e.code === 'no_server' && /python -m noitabench play serve/.test(e.message));
});

test('every request stays on the origin of the page, whatever the page URL carries', async () => {
  const ok = { status: 200, body: { ok: true } };
  const { fetchImpl, calls } = fake([ok, ok, ok, ok, ok]);
  const api = createApi('http://localhost:8765/web/play.html?src=http://evil.example/&x=//evil.example/#//evil', fetchImpl);
  await api.hello();
  await api.state();
  await api.decide({ text: 'wait' });
  await api.notes({ op: 'list' });
  await api.close();
  assert.equal(calls.length, 5);
  for (const c of calls) assert.equal(new URL(c.url).origin, 'http://localhost:8765', c.url);
});
