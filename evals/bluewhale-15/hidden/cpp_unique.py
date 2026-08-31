import subprocess
import tempfile
from pathlib import Path

harness = r'''
#include <cassert>
#include <vector>
std::vector<int> unique_preserving_order(const std::vector<int>&);
int main() {
  std::vector<int> values{3, 1, 3, 2, 1, 2};
  const auto snapshot = values;
  assert((unique_preserving_order(values) == std::vector<int>{3, 1, 2}));
  assert(values == snapshot);
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "hidden.cpp").write_text(harness, encoding="utf-8")
    binary = root / "test"
    compiled = subprocess.run(
        [
            "c++", "-std=c++17", "-Wall", "-Wextra", "-pedantic",
            "unique.cpp", str(root / "hidden.cpp"), "-o", str(binary),
        ],
        check=False,
    )
    if compiled.returncode:
        raise SystemExit(compiled.returncode)
    raise SystemExit(subprocess.run([str(binary)], check=False).returncode)
