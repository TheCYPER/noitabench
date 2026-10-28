import test from 'node:test';
import assert from 'node:assert/strict';
import { profileUrlFor, reportHref, reportLinkFor } from '../js/report/link.js';

test('the profile of a run folder sits at <folder>/profile.json, with or without the trailing slash', () => {
  assert.equal(profileUrlFor(new URL('http://localhost:8000/runs/a/')).href, 'http://localhost:8000/runs/a/profile.json');
  assert.equal(profileUrlFor(new URL('http://localhost:8000/runs/a')).href, 'http://localhost:8000/runs/a/profile.json');
  assert.equal(profileUrlFor(new URL('http://localhost:8000/runs/a/?x=1#y')).href, 'http://localhost:8000/runs/a/profile.json');
});

test('the report link carries the profile path, encoded', () => {
  assert.equal(reportHref('/runs/a b/profile.json'), 'report.html?profile=%2Fruns%2Fa%20b%2Fprofile.json');
  const link = new URL(reportHref('/runs/a&b=1/profile.json'), 'http://h/web/replay.html');
  assert.deepEqual(link.searchParams.getAll('profile'), ['/runs/a&b=1/profile.json']);
});

test('a link appears only when a HEAD request finds the file; the file is not downloaded', async () => {
  const calls = [];
  const found = async (url, init) => { calls.push([url, init?.method]); return { ok: true, status: 200 }; };
  assert.equal(await reportLinkFor(new URL('http://localhost:8000/runs/a/'), found), 'report.html?profile=%2Fruns%2Fa%2Fprofile.json');
  assert.deepEqual(calls, [['http://localhost:8000/runs/a/profile.json', 'HEAD']]);
  assert.equal(await reportLinkFor(new URL('http://localhost:8000/runs/b/'), async () => ({ ok: false, status: 404 })), null);
  assert.equal(await reportLinkFor(new URL('http://localhost:8000/runs/c/'), async () => { throw new TypeError('offline'); }), null);
});
