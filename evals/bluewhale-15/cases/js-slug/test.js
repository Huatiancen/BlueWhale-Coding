const test = require('node:test');
const assert = require('node:assert/strict');
const { slugify } = require('./slug');

test('collapses separators', () => {
  assert.equal(slugify(' Blue   Whale! '), 'blue-whale');
});
