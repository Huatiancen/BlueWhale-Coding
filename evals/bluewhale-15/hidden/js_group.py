import subprocess

script = """
const assert = require('node:assert/strict');
const { groupBy } = require('./group');
const items = [{team:'b',id:1},{team:'a',id:2},{team:'b',id:3}];
const snapshot = JSON.stringify(items);
assert.deepEqual(groupBy(items, 'team'), {b:[items[0],items[2]], a:[items[1]]});
assert.equal(JSON.stringify(items), snapshot);
"""
raise SystemExit(subprocess.run(["node", "-e", script], check=False).returncode)
