from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bluewhale_agent.runtime.sandbox import SeatbeltSandbox


def test_seatbelt_wraps_argv_without_using_a_shell(tmp_path: Path) -> None:
    sandbox = SeatbeltSandbox(workspace=tmp_path)

    wrapped = sandbox.wrap(("python3", "-c", "print('ok')"))

    assert wrapped[:3] == ("/usr/bin/sandbox-exec", "-p", sandbox.profile)
    assert wrapped[3:] == ("python3", "-c", "print('ok')")
    assert "(allow network" not in sandbox.profile


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
