import test from 'node:test';
import assert from 'node:assert/strict';
import { sameOriginUrl } from '../js/ui/same-origin.js';
import { FileSet } from '../js/ui/file-set.js';

const PAGE = 'http://localhost:8000/web/replay.html?src=x';

test('relative and same-origin absolute URLs are accepted', () => {
  assert.equal(sameOriginUrl('../runs/a/', PAGE).href, 'http://localhost:8000/runs/a/');
  assert.equal(sameOriginUrl('tests/fixtures/rec_synthetic/', PAGE).href, 'http://localhost:8000/web/tests/fixtures/rec_synthetic/');
  assert.equal(sameOriginUrl('http://localhost:8000/runs/b', PAGE).pathname, '/runs/b');
  assert.equal(sameOriginUrl('/runs/c/', PAGE).pathname, '/runs/c/');
});

test('another host, port, scheme or a protocol-relative URL is refused', () => {
  for (const raw of ['https://evil.example/runs/', 'http://localhost:9999/runs/', 'https://localhost:8000/runs/', '//evil.example/runs/', 'http://127.0.0.1:8000/runs/', 'data:text/plain,hi']) {
    assert.throws(() => sameOriginUrl(raw, PAGE), /another site/, raw);
  }
  assert.throws(() => sameOriginUrl('http://', PAGE), /not a valid URL/);
});

test('fromUrls refuses names that leave the directory', () => {
  assert.throws(() => FileSet.fromUrls('http://x.test/runs/a', ['https://evil.example/x']), /not inside/);
  assert.throws(() => FileSet.fromUrls('http://x.test/runs/a', ['//evil.example/x']), /not inside/);
  assert.throws(() => FileSet.fromUrls('http://x.test/runs/a', ['../b/meta.json']), /not inside/);
  assert.doesNotThrow(() => FileSet.fromUrls('http://x.test/runs/a', ['meta.json', 'sub/dir.bin']));
});
