const test = require('node:test');
const assert = require('node:assert/strict');
const { groupBy } = require('./group');

test('keeps every item in a group', () => {
  const items = [{ team: 'a', id: 1 }, { team: 'a', id: 2 }];
  assert.deepEqual(groupBy(items, 'team').a, items);
});
