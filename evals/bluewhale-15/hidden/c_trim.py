import subprocess
import tempfile
from pathlib import Path

harness = r'''
#include <assert.h>
#include <string.h>
void trim_in_place(char *);
int main(void) {
  char a[] = "\t  blue whale \n";
  char b[] = "   ";
  trim_in_place(a);
  trim_in_place(b);
  assert(strcmp(a, "blue whale") == 0);
  assert(strcmp(b, "") == 0);
  return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "hidden.c").write_text(harness, encoding="utf-8")
    binary = root / "test"
    compiled = subprocess.run(
        [
            "cc", "-std=c11", "-Wall", "-Wextra", "-pedantic",
            "trim.c", str(root / "hidden.c"), "-o", str(binary),
        ],
        check=False,
    )
    if compiled.returncode:
        raise SystemExit(compiled.returncode)
    raise SystemExit(subprocess.run([str(binary)], check=False).returncode)
