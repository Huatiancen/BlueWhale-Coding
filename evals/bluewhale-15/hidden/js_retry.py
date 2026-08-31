import subprocess

script = """
const assert = require('node:assert/strict');
const { retry } = require('./retry');
(async () => {
  let calls = 0;
  const result = await retry(async () => {
    calls += 1;
    if (calls < 3) throw new Error(`failure-${calls}`);
    return 'ok';
  }, 2);
  assert.equal(result, 'ok');
  assert.equal(calls, 3);
  calls = 0;
  await assert.rejects(() => retry(async () => {
    calls += 1;
    throw new Error(`final-${calls}`);
  }, 1), /final-2/);
  assert.equal(calls, 2);
})().catch(error => { console.error(error); process.exit(1); });
"""
raise SystemExit(subprocess.run(["node", "-e", script], check=False).returncode)
