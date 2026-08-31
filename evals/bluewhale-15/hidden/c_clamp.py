import subprocess
import tempfile
from pathlib import Path

harness = """
#include <assert.h>
int clamp_int(int, int, int);
int main(void) {
  assert(clamp_int(-100, -5, 7) == -5);
  assert(clamp_int(100, -5, 7) == 7);
  assert(clamp_int(3, -5, 7) == 3);
  return 0;
}
"""
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "hidden.c").write_text(harness, encoding="utf-8")
    binary = root / "test"
    compiled = subprocess.run(
        [
            "cc", "-std=c11", "-Wall", "-Wextra", "-pedantic",
            "clamp.c", str(root / "hidden.c"), "-o", str(binary),
        ],
        check=False,
    )
    if compiled.returncode:
        raise SystemExit(compiled.returncode)
    raise SystemExit(subprocess.run([str(binary)], check=False).returncode)
