import subprocess

script = """
const assert = require('node:assert/strict');
const { slugify } = require('./slug');
assert.equal(slugify('  Blue___Whale!!! Agent  '), 'blue-whale-agent');
assert.equal(slugify('---Already clean---'), 'already-clean');
"""
raise SystemExit(subprocess.run(["node", "-e", script], check=False).returncode)
