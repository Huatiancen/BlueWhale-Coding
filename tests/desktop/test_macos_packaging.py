from __future__ import annotations

import plistlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]


def test_demo_project_starts_with_a_reproducible_failure(tmp_path: Path) -> None:
    source = REPOSITORY / "demo" / "bluewhale-repair-demo"
    workspace = tmp_path / "demo"
    shutil.copytree(source, workspace)

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "FAILED" in result.stderr
    assert (workspace / "验证指令.md").is_file()


def test_packaging_script_builds_finder_launchable_app(tmp_path: Path) -> None:
    output = tmp_path / "BlueWhale.app"

    result = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY / "scripts" / "build_macos_app.py"),
            "--output",
            str(output),
            "--source-root",
            str(REPOSITORY),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    info_path = output / "Contents" / "Info.plist"
    launcher = output / "Contents" / "MacOS" / "BlueWhale"
    resources = output / "Contents" / "Resources"
    assert info_path.is_file()
    assert launcher.is_file()
    assert resources.is_dir()
    assert launcher.stat().st_mode & stat.S_IXUSR
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleExecutable"] == "BlueWhale"
    assert info["CFBundleIdentifier"] == "com.bluewhale.coding-agent"
    assert (resources / "source-root.txt").read_text(encoding="utf-8").strip() == str(
        REPOSITORY.resolve()
    )


def test_packaging_refuses_to_overwrite_an_unrelated_directory(tmp_path: Path) -> None:
    output = tmp_path / "BlueWhale.app"
    output.mkdir()
    (output / "user-file.txt").write_text("keep", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY / "scripts" / "build_macos_app.py"),
            "--output",
            str(output),
            "--source-root",
            str(REPOSITORY),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert (output / "user-file.txt").read_text(encoding="utf-8") == "keep"
