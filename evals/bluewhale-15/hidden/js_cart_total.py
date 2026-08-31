import subprocess

script = """
const assert = require('node:assert/strict');
const { cartTotal } = require('./cart');
const items = [{price: 2.5, quantity: 4}, {price: 3, quantity: 0}];
const snapshot = JSON.stringify(items);
assert.equal(cartTotal(items), 10);
assert.equal(JSON.stringify(items), snapshot);
"""
raise SystemExit(subprocess.run(["node", "-e", script], check=False).returncode)
