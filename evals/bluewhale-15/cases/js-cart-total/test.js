const test = require('node:test');
const assert = require('node:assert/strict');
const { cartTotal } = require('./cart');

test('multiplies price by quantity', () => {
  assert.equal(cartTotal([{ price: 5, quantity: 3 }]), 15);
});
