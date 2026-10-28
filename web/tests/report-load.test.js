import test from 'node:test';
import assert from 'node:assert/strict';
import { FileSet } from '../js/ui/file-set.js';
import { loadFromFiles, loadFromUrls, profilePaths } from '../js/report/load.js';
import { fixtureBytes } from './helpers.js';

const agentText = fixtureBytes('profiles', 'agent.profile.json').toString('utf8');
const humanText = fixtureBytes('profiles', 'human.profile.json').toString('utf8');
const fileOf = (name, text) => new File([text], name);
const setOf = (entries) => new FileSet(new Map(entries));

test('profile.json and name.profile.json are found anywhere; without those, loose .json files', () => {
  assert.deepEqual(profilePaths(['runs/a/profile.json', 'runs/a/frames.bin', 'x/y.profile.json', 'meta.json']), ['runs/a/profile.json', 'x/y.profile.json']);
  assert.deepEqual(profilePaths(['PROFILE.JSON', 'a.json']), ['PROFILE.JSON']);
  assert.deepEqual(profilePaths(['mine.json', 'dir/other.json', 'frames.bin']), ['mine.json']);
  assert.deepEqual(profilePaths(['dir/meta.json', 'dir/frames.bin']), []);
  assert.deepEqual(profilePaths(['dir/superprofile.json', 'dir/meta.json']), [], 'only a dot or the start of the name may precede "profile.json"');
  assert.deepEqual(profilePaths(['meta.json', 'summary.json']), [], 'files of a run folder are not tried');
});

test('files: profiles are read, a wrong or broken file is a warning that names it', async () => {
  const files = setOf([
    ['runs/a/profile.json', fileOf('profile.json', agentText)],
    ['runs/b/profile.json', fileOf('profile.json', humanText)],
    ['runs/c/profile.json', fileOf('profile.json', '{"format":"cogbench-rec/0"}')],
    ['runs/d/profile.json', fileOf('profile.json', '{ broken')],
    ['runs/a/frames.bin', fileOf('frames.bin', 'not read')],
  ]);
  const { profiles, warnings } = await loadFromFiles(files);
  assert.deepEqual(profiles.map((p) => [p.file, p.runId]), [['runs/a/profile.json', 'fx-agent'], ['runs/b/profile.json', 'fx-human']]);
  assert.equal(warnings.length, 2);
  assert.match(warnings[0], /^runs\/c\/profile\.json: .*cogbench-rec\/0/);
  assert.match(warnings[1], /^runs\/d\/profile\.json: not valid JSON/);
});

test('files: nothing that looks like a profile says how to make one', async () => {
  const { profiles, warnings } = await loadFromFiles(setOf([['meta.json', fileOf('meta.json', '{}')]]));
  assert.equal(profiles.length, 0);
  assert.match(warnings[0], /没有找到 profile\.json.*noitabench eval/);
});

test('files: a huge file is not read', async () => {
  let read = false;
  const huge = { size: 6 * 1024 * 1024, text: async () => { read = true; return agentText; }, arrayBuffer: async () => new ArrayBuffer(0) };
  const { profiles, warnings } = await loadFromFiles(setOf([['profile.json', huge]]));
  assert.equal(profiles.length, 0);
  assert.equal(read, false);
  assert.match(warnings[0], /too large/);
});

const PAGE = 'http://localhost:8000/web/report.html?profile=x';
const stubFetch = (table, calls = []) => async (url) => {
  calls.push(url);
  const body = table[new URL(url).pathname];
  if (body === undefined) return { ok: false, status: 404, text: async () => '' };
  return { ok: true, status: 200, text: async () => body };
};

test('urls: same-origin profiles are fetched, other sites are refused before any request', async () => {
  const calls = [];
  const fetchFn = stubFetch({ '/runs/a/profile.json': agentText, '/runs/b/profile.json': humanText }, calls);
  const { profiles, warnings } = await loadFromUrls(['../runs/a/profile.json', 'https://evil.example/p.json', '/runs/b/profile.json', '../runs/missing/profile.json'], PAGE, fetchFn);
  assert.deepEqual(profiles.map((p) => [p.file, p.runId]), [['a/profile.json', 'fx-agent'], ['b/profile.json', 'fx-human']]);
  assert.equal(warnings.length, 2);
  assert.match(warnings[0], /another site/);
  assert.match(warnings[1], /missing\/profile\.json: HTTP 404.*noitabench eval/);
  assert.ok(calls.every((u) => u.startsWith('http://localhost:8000/')), calls.join());
  assert.equal(calls.length, 3, 'the refused URL was never requested');
});

test('urls: a damaged file or a network error is a warning, the others still load', async () => {
  const fetchFn = async (url) => {
    if (url.endsWith('/net/profile.json')) throw new TypeError('Failed to fetch');
    return { ok: true, status: 200, text: async () => (url.endsWith('/bad/profile.json') ? '[]' : agentText) };
  };
  const { profiles, warnings } = await loadFromUrls(['/bad/profile.json', '/net/profile.json', '/ok/profile.json'], PAGE, fetchFn);
  assert.equal(profiles.length, 1);
  assert.match(warnings[0], /bad\/profile\.json: not a JSON object/);
  assert.match(warnings[1], /Failed to fetch/);
});

test('urls: at most four are fetched', async () => {
  const calls = [];
  const values = ['/1/p.json', '/2/p.json', '/3/p.json', '/4/p.json', '/5/p.json'];
  const table = Object.fromEntries(values.map((v) => [v, agentText]));
  const { profiles, warnings } = await loadFromUrls(values, PAGE, stubFetch(table, calls));
  assert.equal(profiles.length, 4);
  assert.equal(calls.length, 4);
  assert.match(warnings.at(-1), /最多同时看 4 份/);
});
