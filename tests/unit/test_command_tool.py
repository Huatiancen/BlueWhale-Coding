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
async def test_run_command_streams_stdout_through_a_pipeline(tmp_path: Path) -> None:
    producer = python_command("print('blue whale')")
    consumer = python_command("import sys; print(sys.stdin.read().upper(), end='')")

    result = await RunCommandTool().invoke(
        {"command": f"{producer} | {consumer}"},
        make_context(tmp_path),
    )

    assert result.status is ObservationStatus.SUCCESS
    assert result.content == "BLUE WHALE\n"
    assert result.metadata["steps"][0]["pipeline"] == [
        [sys.executable, "-c", "print('blue whale')"],
        [sys.executable, "-c", "import sys; print(sys.stdin.read().upper(), end='')"],
    ]


@pytest.mark.asyncio
async def test_run_command_honors_success_and_failure_conditions(tmp_path: Path) -> None:
    command = " ".join(
        [
            python_command("import sys; sys.exit(1)"),
            "&&",
            python_command("print('skipped')"),
            "||",
            python_command("print('recovered')"),
            ";",
            python_command("print('always')"),
        ]
    )

    result = await RunCommandTool().invoke({"command": command}, make_context(tmp_path))

    assert result.status is ObservationStatus.SUCCESS
    assert "recovered" in result.content
    assert "always" in result.content
    assert "skipped" not in result.content
    assert "步骤 1" in result.content
    assert "步骤 3" in result.content
    steps = result.metadata["steps"]
    assert isinstance(steps, list)
    assert [step["skipped"] for step in steps] == [False, True, False, False]
    assert [step["exit_code"] for step in steps] == [1, None, 0, 0]


@pytest.mark.asyncio
async def test_compound_command_uses_one_total_timeout_budget(tmp_path: Path) -> None:
    command = " ; ".join(
        [
            python_command("import time; time.sleep(10)"),
            python_command("from pathlib import Path; Path('late').write_text('bad')"),
        ]
    )

    result = await RunCommandTool().invoke(
        {"command": command, "timeout_seconds": 0.1}, make_context(tmp_path)
    )

    assert result.status is ObservationStatus.TIMEOUT
    assert result.metadata["timed_out"] is True
    assert not (tmp_path / "late").exists()
    assert len(result.metadata["steps"]) == 1


@pytest.mark.asyncio
async def test_pipeline_timeout_terminates_every_process(tmp_path: Path) -> None:
    producer = python_command(
        "import os, pathlib, time; "
        "pathlib.Path('producer-pid').write_text(str(os.getpid())); "
        "time.sleep(10)"
    )
    consumer = python_command(
        "import os, pathlib, sys; "
        "pathlib.Path('consumer-pid').write_text(str(os.getpid())); "
        "sys.stdin.read()"
    )

    result = await RunCommandTool().invoke(
        {"command": f"{producer} | {consumer}", "timeout_seconds": 0.3},
        make_context(tmp_path),
    )

    pids = [
        int((tmp_path / name).read_text(encoding="utf-8"))
        for name in ("producer-pid", "consumer-pid")
    ]
    assert result.status is ObservationStatus.TIMEOUT
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


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
        ("rm -rf /", PermissionDecision.ASK),
        ("sudo pytest", PermissionDecision.ASK),
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
        (PermissionMode.ASK, "rm -rf build", PermissionDecision.ASK),
        (PermissionMode.BALANCED, "bash", PermissionDecision.DENY),
        (PermissionMode.FULL, "git reset --hard", PermissionDecision.ASK),
    ],
)
def test_command_permission_modes(
    mode: PermissionMode, command: str, expected: PermissionDecision
) -> None:
    result = PermissionPolicy(mode=mode).evaluate(
        Action(id="1", tool_name="run_command", arguments={"command": command})
    )

    assert result.decision is expected


def test_unsupported_shell_syntax_becomes_a_tool_error_not_permission_denial() -> None:
    result = PermissionPolicy(mode=PermissionMode.FULL).evaluate(
        Action(
            id="1",
            tool_name="run_command",
            arguments={"command": "printf test > result.txt"},
        )
    )

    assert result.decision is PermissionDecision.ALLOW
    assert "运行时" in result.reason


@pytest.mark.parametrize(
    "command",
    [
        "pwd",
        "ls -la",
        "cat README.md",
        "head -n 5 README.md",
        "tail -n 5 README.md",
        "wc -l README.md",
        "file README.md",
        "which python",
        "stat README.md",
        "rg TODO src",
        "grep -n TODO README.md",
        "diff before.txt after.txt",
        "black --check src",
        "isort --check-only src",
        "eslint src",
        "prettier --check .",
        "tsc --noEmit",
        "biome check src",
        "vitest run",
        "jest --runInBand",
        "g++ -std=c++17 main.cpp -o main",
        "clang++ -Wall main.cpp -o main",
        "gcc main.c -o main",
        "cmake --build build",
        "ctest --test-dir build",
        "ninja -C build",
        "make test",
        "clang-format --dry-run main.cpp",
        "clang-tidy main.cpp",
        "javac Main.java",
        "java Main",
        "go test ./...",
        "gofmt -d .",
        "cargo clippy",
        "rustc main.rs",
        "rustfmt --check main.rs",
        "swift test",
        "swiftc main.swift",
    ],
)
def test_balanced_allows_common_development_commands(command: str) -> None:
    result = PermissionPolicy(mode=PermissionMode.BALANCED).evaluate(
        Action(id="common", tool_name="run_command", arguments={"command": command})
    )

    assert result.decision is PermissionDecision.ALLOW


@pytest.mark.parametrize(
    "command",
    [
        "gcc -fplugin=evil.so main.c",
        "clang -Xclang -load -Xclang evil.so main.c",
        "find . -delete",
        "find . -exec echo {} ;",
        "sed -i backup README.md",
        "curl https://example.com",
        "npm publish",
        "git commit -m test",
        "./main",
        "/tmp/custom-tool",
        "cat /etc/passwd",
        "head ../outside.txt",
        "ls /tmp",
        "rg secret /etc",
    ],
)
def test_balanced_asks_for_risky_or_untrusted_commands(command: str) -> None:
    result = PermissionPolicy(mode=PermissionMode.BALANCED).evaluate(
        Action(id="risky", tool_name="run_command", arguments={"command": command})
    )

    assert result.decision is PermissionDecision.ASK


def test_compound_permission_uses_the_strictest_step() -> None:
    result = PermissionPolicy(mode=PermissionMode.BALANCED).evaluate(
        Action(
            id="compound",
            tool_name="run_command",
            arguments={"command": "g++ main.cpp -o main && ./main"},
        )
    )

    assert result.decision is PermissionDecision.ASK
    assert "./main" in result.reason


def test_pipeline_permission_uses_the_strictest_command() -> None:
    result = PermissionPolicy(mode=PermissionMode.BALANCED).evaluate(
        Action(
            id="pipeline",
            tool_name="run_command",
            arguments={"command": "cat README.md | /tmp/custom-tool"},
        )
    )

    assert result.decision is PermissionDecision.ASK
    assert "/tmp/custom-tool" in result.reason


def test_balanced_does_not_trust_safe_basename_from_untrusted_absolute_path() -> None:
    result = PermissionPolicy(mode=PermissionMode.BALANCED).evaluate(
        Action(
            id="spoofed",
            tool_name="run_command",
            arguments={"command": "/tmp/g++ main.cpp -o main"},
        )
    )

    assert result.decision is PermissionDecision.ASK
    assert "/tmp/g++" in result.reason


def test_balanced_rejects_read_command_through_workspace_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-command-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)
    policy = PermissionPolicy(paths=WorkspacePaths(tmp_path), mode=PermissionMode.BALANCED)

    result = policy.evaluate(
        Action(
            id="symlink-read",
            tool_name="run_command",
            arguments={"command": "cat linked.txt"},
        )
    )

    assert result.decision is PermissionDecision.ASK


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
        permission_policy=PermissionPolicy(
            paths=context.paths, mode=PermissionMode.FULL
        ),
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
