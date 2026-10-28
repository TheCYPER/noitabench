import test from 'node:test';
import assert from 'node:assert/strict';
import { exactBigInts } from '../js/format/json.js';

test('exactBigInts returns the exact digits of u64 values that JSON.parse would round', () => {
  const text = '{"format":"x","seed": 18446744073709551615,"rule_seed":9007199254740993,"n":5}';
  assert.notEqual(String(JSON.parse(text).seed), '18446744073709551615'); // the problem being solved
  assert.deepEqual(exactBigInts(text, ['seed', 'rule_seed']), { seed: '18446744073709551615', rule_seed: '9007199254740993' });
});

test('exactBigInts ignores values that are exact already, and similarly named keys', () => {
  assert.deepEqual(exactBigInts('{"seed":12345,"rule_seed":7}', ['seed', 'rule_seed']), {});
  assert.deepEqual(exactBigInts('{"rule_seed":18446744073709551615}', ['seed']), {}); // "rule_seed" is not "seed"
  assert.deepEqual(exactBigInts('{"seed":1234567890123456}', ['seed']), {}); // 16 digits but still a safe integer
  assert.deepEqual(exactBigInts('{}', ['seed']), {});
});
