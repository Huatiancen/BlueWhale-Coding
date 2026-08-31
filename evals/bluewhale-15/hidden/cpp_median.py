import subprocess
import tempfile
from pathlib import Path

harness = r'''
#include <algorithm>
#include <cassert>
#include <stdexcept>
#include <vector>
double median(const std::vector<double>&);
int main() {
  std::vector<double> values{9, 1, 7, 3};
  const auto snapshot = values;
  assert(median(values) == 5.0);
  assert(values == snapshot);
  bool threw = false;
  try { median({}); } catch (const std::invalid_argument&) { threw = true; }
  assert(threw);
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "hidden.cpp").write_text(harness, encoding="utf-8")
    binary = root / "test"
    compiled = subprocess.run(
        [
            "c++", "-std=c++17", "-Wall", "-Wextra", "-pedantic",
            "stats.cpp", str(root / "hidden.cpp"), "-o", str(binary),
        ],
        check=False,
    )
    if compiled.returncode:
        raise SystemExit(compiled.returncode)
    raise SystemExit(subprocess.run([str(binary)], check=False).returncode)
