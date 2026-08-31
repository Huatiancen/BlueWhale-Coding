from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bluewhale_agent.runtime.sandbox import SeatbeltSandbox


def test_seatbelt_wraps_argv_without_using_a_shell(tmp_path: Path) -> None:
    sandbox = SeatbeltSandbox(workspace=tmp_path)

    wrapped = sandbox.wrap(("python3", "-c", "print('ok')"))

    assert wrapped[:2] == ("/usr/bin/sandbox-exec", "-p")
    assert f'(subpath "{tmp_path.resolve()}")' in wrapped[2]
    assert wrapped[3:] == ("python3", "-c", "print('ok')")
    assert "(allow network" not in sandbox.profile


def test_seatbelt_allows_only_the_selected_user_toolchain_root(tmp_path: Path) -> None:
    npm = tmp_path / "home" / ".nvm" / "versions" / "node" / "v24" / "bin" / "npm"
    sandbox = SeatbeltSandbox(
        workspace=tmp_path / "workspace",
        executable_lookup=lambda name: str(npm) if name == "npm" else None,
    )

    wrapped = sandbox.wrap(("npm", "run", "test"))
    dynamic_profile = wrapped[2]
    home = tmp_path / "home"

    assert f'(subpath "{npm.parent.parent}")' in dynamic_profile
    assert f'(subpath "{home}")' not in dynamic_profile


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is available on macOS")
def test_seatbelt_allows_workspace_writes_and_denies_parent_reads(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("must-not-be-readable", encoding="utf-8")
    sandbox = SeatbeltSandbox(workspace=workspace)

    write = subprocess.run(
        sandbox.wrap(
            (
                sys.executable,
                "-S",
                "-c",
                "from pathlib import Path; Path('inside.txt').write_text('ok')",
            )
        ),
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    read = subprocess.run(
        sandbox.wrap(
            (
                sys.executable,
                "-S",
                "-c",
                f"from pathlib import Path; print(Path({str(secret)!r}).read_text())",
            )
        ),
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    if write.returncode == 71 and "Operation not permitted" in write.stderr:
        pytest.skip("the outer test runner sandbox does not allow nested Seatbelt profiles")

    assert write.returncode == 0, write.stderr
    assert (workspace / "inside.txt").read_text(encoding="utf-8") == "ok"
    assert read.returncode != 0
    assert "must-not-be-readable" not in read.stdout
