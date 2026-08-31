const test = require('node:test');
const assert = require('node:assert/strict');
const { retry } = require('./retry');

test('retries until the operation succeeds', async () => {
  let calls = 0;
  const value = await retry(async () => {
    calls += 1;
    if (calls < 2) throw new Error('temporary');
    return 42;
  }, 2);
  assert.equal(value, 42);
  assert.equal(calls, 2);
});
