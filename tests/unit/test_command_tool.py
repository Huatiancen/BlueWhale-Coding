import asyncio
import os
import shlex
import signal
import sys
from contextlib import suppress
from pathlib import Path

import pytest

from bluewhale_agent.domain.models import Action, ObservationStatus
from bluewhale_agent.runtime.command import RunCommandTool
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.runtime.permissions import (
    PermissionDecision,
    PermissionMode,
    PermissionPolicy,
)
from bluewhale_agent.tools.base import ToolContext, ToolExecutionError
from bluewhale_agent.tools.registry import ToolRegistry


def python_command(source: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


def make_context(tmp_path: Path, *, max_output_bytes: int = 20_000) -> ToolContext:
    return ToolContext(
        paths=WorkspacePaths(tmp_path),
        command_timeout_seconds=2.0,
        max_command_output_bytes=max_output_bytes,
    )


@pytest.mark.asyncio
async def test_run_command_returns_zero_exit_code_and_fixed_cwd(tmp_path: Path) -> None:
    result = await RunCommandTool().invoke(
        {"command": python_command("import os; print(os.getcwd())")},
        make_context(tmp_path),
    )

    assert result.status is ObservationStatus.SUCCESS
    assert result.metadata["exit_code"] == 0
    assert result.metadata["cwd"] == str(tmp_path.resolve())
    assert result.content.strip() == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_run_command_maps_nonzero_exit_to_error(tmp_path: Path) -> None:
    result = await RunCommandTool().invoke(
        {"command": python_command("import sys; print('failed'); sys.exit(3)")},
        make_context(tmp_path),
    )

    assert result.status is ObservationStatus.ERROR
    assert result.metadata["exit_code"] == 3
    assert "failed" in result.content


@pytest.mark.asyncio
async def test_run_command_timeout_terminates_process(tmp_path: Path) -> None:
    source = (
        "import os, pathlib, time; "
        "pathlib.Path('pid.txt').write_text(str(os.getpid())); "
        "time.sleep(10)"
    )
    result = await RunCommandTool().invoke(
        {"command": python_command(source), "timeout_seconds": 0.1},
        make_context(tmp_path),
    )

    pid = int((tmp_path / "pid.txt").read_text(encoding="utf-8"))
    assert result.status is ObservationStatus.TIMEOUT
    assert result.metadata["timed_out"] is True
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_timeout_kills_child_that_ignores_terminate(tmp_path: Path) -> None:
    child_source = (
        "import pathlib, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path('child-ready').write_text('ready'); "
        "time.sleep(10)"
    )
    parent_source = (
        "import pathlib, subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_source!r}]); "
        "pathlib.Path('child-pid').write_text(str(child.pid)); "
        "ready = pathlib.Path('child-ready'); "
        "[(time.sleep(0.01)) for _ in range(100) if not ready.exists()]; "
        "time.sleep(10)"
    )

    result = await RunCommandTool().invoke(
        {"command": python_command(parent_source), "timeout_seconds": 0.2},
        make_context(tmp_path),
    )
    child_pid = int((tmp_path / "child-pid").read_text(encoding="utf-8"))

    try:
        child_gone = False
        for _ in range(20):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                child_gone = True
                break
            await asyncio.sleep(0.05)
        assert result.status is ObservationStatus.TIMEOUT
        assert child_gone is True
    finally:
        with suppress(ProcessLookupError):
            os.kill(child_pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_cancelling_command_kills_process(tmp_path: Path) -> None:
    source = (
        "import os, pathlib, time; "
        "pathlib.Path('cancel-pid').write_text(str(os.getpid())); "
        "time.sleep(10)"
    )
    task = asyncio.create_task(
        RunCommandTool().invoke(
            {"command": python_command(source)},
            make_context(tmp_path),
        )
    )
    pid_path = tmp_path / "cancel-pid"
    for _ in range(100):
        if pid_path.exists():
            break
        await asyncio.sleep(0.01)
    pid = int(pid_path.read_text(encoding="utf-8"))

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    try:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_start_failure_does_not_leave_empty_artifact(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError, match="could not be started"):
        await RunCommandTool().invoke(
            {"command": "bluewhale-command-that-does-not-exist"},
            make_context(tmp_path),
        )

    artifact_directory = tmp_path / ".bluewhale" / "artifacts" / "commands"
    assert list(artifact_directory.iterdir()) == []


@pytest.mark.asyncio
async def test_artifact_directory_cannot_escape_through_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-artifacts"
    outside.mkdir()
    (tmp_path / ".bluewhale").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ToolExecutionError, match="artifact directory"):
        await RunCommandTool().invoke(
            {"command": python_command("print('unsafe')")},
            make_context(tmp_path),
        )

    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_run_command_merges_output_and_keeps_full_artifact(tmp_path: Path) -> None:
    source = (
        "import sys; "
        "print('A' * 40, flush=True); "
        "print('B' * 40, file=sys.stderr, flush=True)"
    )
    result = await RunCommandTool().invoke(
        {"command": python_command(source)},
        make_context(tmp_path, max_output_bytes=32),
    )

    artifact = tmp_path / str(result.metadata["artifact_path"])
    full_output = artifact.read_text(encoding="utf-8")
    assert "A" * 40 in full_output
    assert "B" * 40 in full_output
    assert result.metadata["truncated"] is True
    assert result.metadata["output_bytes"] == len(full_output.encode())
    assert "output truncated" in result.content
    assert len(result.content.encode()) < len(full_output.encode())


@pytest.mark.asyncio
async def test_run_command_does_not_expose_secret_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "should-not-reach-child")

    result = await RunCommandTool().invoke(
        {
            "command": python_command(
                "import os; print(os.environ.get('DEEPSEEK_API_KEY', 'missing'))"
            )
        },
        make_context(tmp_path),
    )

    assert result.content.strip() == "missing"


@pytest.mark.asyncio
async def test_run_command_rejects_interactive_program(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError, match="interactive"):
        await RunCommandTool().invoke(
            {"command": shlex.quote(sys.executable)}, make_context(tmp_path)
        )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("pytest -q", PermissionDecision.ALLOW),
        ("git status --short", PermissionDecision.ALLOW),
        ("pip install example", PermissionDecision.ASK),
        ("npm install", PermissionDecision.ASK),
        ("git commit -m test", PermissionDecision.ASK),
        ("git push origin main", PermissionDecision.ASK),
        ("rm -rf /", PermissionDecision.DENY),
        ("sudo pytest", PermissionDecision.DENY),
        ("bash", PermissionDecision.DENY),
        ("python3.13", PermissionDecision.DENY),
        ("python3.13 -m pytest", PermissionDecision.ALLOW),
    ],
)
def test_command_permission_classification(command: str, expected: PermissionDecision) -> None:
    result = PermissionPolicy().evaluate(
        Action(id="1", tool_name="run_command", arguments={"command": command})
    )

    assert result.decision is expected


@pytest.mark.parametrize(
    ("mode", "command", "expected"),
    [
        (PermissionMode.ASK, "pytest -q", PermissionDecision.ASK),
        (PermissionMode.FULL, "custom-build --release", PermissionDecision.ALLOW),
        (PermissionMode.FULL, "curl https://example.com", PermissionDecision.ALLOW),
        (PermissionMode.ASK, "rm -rf build", PermissionDecision.DENY),
        (PermissionMode.BALANCED, "bash", PermissionDecision.DENY),
        (PermissionMode.FULL, "git reset --hard", PermissionDecision.DENY),
    ],
)
def test_command_permission_modes(
    mode: PermissionMode, command: str, expected: PermissionDecision
) -> None:
    result = PermissionPolicy(mode=mode).evaluate(
        Action(id="1", tool_name="run_command", arguments={"command": command})
    )

    assert result.decision is expected


@pytest.mark.asyncio
async def test_registry_rejects_model_supplied_cwd(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    registry = ToolRegistry(
        tools=[RunCommandTool()],
        context=context,
        permission_policy=PermissionPolicy(paths=context.paths),
    )

    result = await registry.dispatch(
        Action(
            id="1",
            tool_name="run_command",
            arguments={"command": "pytest --version", "cwd": "/tmp"},
        )
    )

    assert result.status is ObservationStatus.ERROR
    assert "Invalid arguments" in result.summary
    schema = registry.schemas()[0]["function"]["parameters"]
    assert schema["additionalProperties"] is False
    assert "cwd" not in schema["properties"]


@pytest.mark.asyncio
async def test_registry_preserves_nonzero_command_status(tmp_path: Path) -> None:
    context = make_context(tmp_path)
    registry = ToolRegistry(
        tools=[RunCommandTool()],
        context=context,
        permission_policy=PermissionPolicy(paths=context.paths),
    )

    result = await registry.dispatch(
        Action(
            id="1",
            tool_name="run_command",
            arguments={
                "command": (
                    f"{shlex.quote(str(Path(sys.executable).with_name('pytest')))} "
                    "file-that-does-not-exist.py -q"
                )
            },
        )
    )

    assert result.status is ObservationStatus.ERROR
    assert result.metadata["exit_code"] != 0
    assert "file or directory not found" in result.content
