#!/usr/bin/env python3
"""Build a Finder-launchable BlueWhale.app using only the Python standard library."""

from __future__ import annotations

import argparse
import plistlib
import stat
from pathlib import Path

LAUNCHER = """#!/bin/sh
set -eu

APP_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SOURCE_FILE="$APP_ROOT/Contents/Resources/source-root.txt"

if [ -f "$SOURCE_FILE" ]; then
    SOURCE_ROOT=$(sed -n '1p' "$SOURCE_FILE")
    if [ -x "$SOURCE_ROOT/.venv/bin/bluewhale" ]; then
        exec "$SOURCE_ROOT/.venv/bin/bluewhale" desktop
    fi
fi

for CANDIDATE in \
    "$HOME/.local/bin/bluewhale" \
    /opt/homebrew/bin/bluewhale \
    /usr/local/bin/bluewhale; do
    if [ -x "$CANDIDATE" ]; then
        exec "$CANDIDATE" desktop
    fi
done

if command -v bluewhale >/dev/null 2>&1; then
    exec bluewhale desktop
fi

/usr/bin/osascript -e \
    'display dialog "找不到 BlueWhale 运行环境。请先安装 desktop 依赖。" \
buttons {"好"} default button "好" with title "BlueWhale"' \
    >/dev/null 2>&1 || true
exit 1
"""


def build_app(output: Path, source_root: Path) -> Path:
    """Create a new app bundle without overwriting an existing directory."""
    output = output.resolve(strict=False)
    source_root = source_root.resolve(strict=True)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing path: {output}")
    contents = output / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir()

    info = {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleDisplayName": "BlueWhale",
        "CFBundleExecutable": "BlueWhale",
        "CFBundleIdentifier": "com.bluewhale.coding-agent",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "BlueWhale",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream, sort_keys=True)
    launcher = macos / "BlueWhale"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (resources / "source-root.txt").write_text(f"{source_root}\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/BlueWhale.app"))
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = build_app(args.output, args.source_root)
    except (FileExistsError, NotADirectoryError) as error:
        parser.error(str(error))
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
