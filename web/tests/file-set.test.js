import test from 'node:test';
import assert from 'node:assert/strict';
import { FileSet } from '../js/ui/file-set.js';
import { NotFoundError } from '../js/format/errors.js';

const file = (name, text = '') => new File([text], name);
const withPath = (f, path) => Object.defineProperty(f, 'webkitRelativePath', { value: path });

test('finds run directories at any depth and narrows to one', async () => {
  const fs = FileSet.fromFiles([
    withPath(file('meta.json', '{"x":1}'), 'runs/a/meta.json'),
    withPath(file('frames.bin'), 'runs/a/frames.bin'),
    withPath(file('meta.json'), 'runs/b/meta.json'),   // no frames.bin: not a run
    withPath(file('meta.json'), 'runs/c/meta.json'),
    withPath(file('frames.bin'), 'runs/c/frames.bin'),
    withPath(file('events.jsonl', 'hi'), 'runs/c/events.jsonl'),
  ]);
  assert.deepEqual(fs.runDirs(), ['runs/a', 'runs/c']);
  const c = fs.within('runs/c');
  assert.deepEqual(c.paths().sort(), ['events.jsonl', 'frames.bin', 'meta.json']);
  assert.equal(await c.text('events.jsonl'), 'hi');
  assert.equal(await fs.within('runs/a').json('meta.json').then((j) => j.x), 1);
});

test('loose files (no folder) form a run at the top level', () => {
  const fs = FileSet.fromFiles([file('meta.json'), file('frames.bin'), file('materials.json')]);
  assert.deepEqual(fs.runDirs(), ['']);
  assert.equal(fs.within(''), fs);
});

test('optionalText returns null for a missing file, other errors propagate', async () => {
  const fs = FileSet.fromFiles([file('a.txt', 'A')]);
  assert.equal(await fs.optionalText('a.txt'), 'A');
  assert.equal(await fs.optionalText('b.txt'), null);
  await assert.rejects(fs.text('b.txt'), NotFoundError);
});

test('pairs .png with .json of the same stem', () => {
  const fs = FileSet.fromFiles([file('w1.png'), file('w1.json'), file('w2.png'), file('other.json'), file('W3.png'), file('W3.json')]);
  assert.deepEqual(fs.worldPairs().map((p) => p.stem), ['w1', 'W3']);
});

test('windows-style relative paths are normalised', () => {
  const fs = FileSet.fromFiles([withPath(file('meta.json'), 'runs\\a\\meta.json'), withPath(file('frames.bin'), 'runs\\a\\frames.bin')]);
  assert.deepEqual(fs.runDirs(), ['runs/a']);
});

test('fromUrls adds a trailing slash and maps 404 to NotFoundError', async () => {
  const seen = [];
  globalThis.fetch = async (url) => {
    seen.push(String(url));
    return String(url).endsWith('events.jsonl') ? new Response('', { status: 404 }) : new Response('{"ok":true}');
  };
  const fs = FileSet.fromUrls('http://x.test/runs/a', ['meta.json', 'events.jsonl']);
  assert.deepEqual(await fs.json('meta.json'), { ok: true });
  assert.equal(await fs.optionalText('events.jsonl'), null);
  assert.deepEqual(seen, ['http://x.test/runs/a/meta.json', 'http://x.test/runs/a/events.jsonl']);
});

// ---- drag and drop of a folder (webkitGetAsEntry), with fake entries

function fakeFile(name, text = '') {
  return { isFile: true, isDirectory: false, name, file: (ok) => ok(new File([text], name)) };
}
function fakeDir(name, children, batch = 2) {
  return {
    isFile: false, isDirectory: true, name,
    createReader() {
      let i = 0;
      // like browsers: readEntries returns a few entries per call and [] at the end
      return { readEntries: (ok) => { const out = children.slice(i, i + batch); i += batch; ok(out); } };
    },
  };
}
const item = (entry) => ({ kind: 'file', webkitGetAsEntry: () => entry });

test('a dropped folder is walked recursively, in batches, skipping dot files', async () => {
  const run = fakeDir('run_7', [fakeFile('meta.json', '{}'), fakeFile('frames.bin'), fakeFile('.DS_Store'), fakeFile('events.jsonl'), fakeDir('sub', [fakeFile('x.txt', 'x')])]);
  const fs = await FileSet.fromDataTransfer({ items: [item(run)], files: [] });
  assert.deepEqual(fs.paths().sort(), ['run_7/events.jsonl', 'run_7/frames.bin', 'run_7/meta.json', 'run_7/sub/x.txt']);
  assert.deepEqual(fs.runDirs(), ['run_7']);
  assert.equal(await fs.within('run_7/sub').text('x.txt'), 'x');
});

test('several dropped runs are all found', async () => {
  const mk = (n) => fakeDir(n, [fakeFile('meta.json'), fakeFile('frames.bin')]);
  const fs = await FileSet.fromDataTransfer({ items: [item(mk('a')), item(mk('b'))], files: [] });
  assert.deepEqual(fs.runDirs(), ['a', 'b']);
});

test('without directory entries the plain file list is used', async () => {
  const fs = await FileSet.fromDataTransfer({ items: [{ kind: 'file', webkitGetAsEntry: () => null }], files: [file('w.png'), file('w.json')] });
  assert.deepEqual(fs.worldPairs().map((p) => p.stem), ['w']);
});
