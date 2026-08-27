"""Bounded, non-interactive command execution inside one workspace."""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.domain.models import ObservationStatus
from bluewhale_agent.runtime.permissions import is_interactive_command
from bluewhale_agent.tools.base import BaseTool, ToolContext, ToolExecutionError, ToolOutput


class RunCommandArguments(BaseModel):
    """Strict model-facing arguments for one command invocation."""

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    timeout_seconds: float | None = Field(default=None, gt=0)


@dataclass
class _OutputCollector:
    limit: int
    total: int = 0
    head: bytearray = field(default_factory=bytearray)
    tail: bytearray = field(default_factory=bytearray)

    def add(self, chunk: bytes) -> None:
        self.total += len(chunk)
        head_limit = self.limit // 2
        if len(self.head) < head_limit:
            consumed = min(head_limit - len(self.head), len(chunk))
            self.head.extend(chunk[:consumed])
            chunk = chunk[consumed:]
        if chunk:
            tail_limit = self.limit - head_limit
            self.tail.extend(chunk)
            if len(self.tail) > tail_limit:
                del self.tail[: len(self.tail) - tail_limit]

    @property
    def truncated(self) -> bool:
        return self.total > self.limit

    def render(self) -> str:
        if not self.truncated:
            return bytes(self.head + self.tail).decode("utf-8", errors="replace")
        marker = f"\n... output truncated ({self.total} bytes total) ...\n".encode()
        return bytes(self.head + marker + self.tail).decode("utf-8", errors="replace")


class CommandRuntime:
    """Execute argv without a shell and persist complete combined output."""

    TERMINATE_GRACE_SECONDS = 0.5
    SECRET_ENV_FRAGMENTS = ("API_KEY", "AUTHORIZATION", "PASSWORD", "SECRET", "TOKEN")

    def __init__(
        self,
        *,
        workspace: Path,
        artifact_directory: Path,
        max_output_bytes: int,
    ) -> None:
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._workspace = workspace
        self._artifact_directory = artifact_directory
        self._max_output_bytes = max_output_bytes

    async def run(self, command: str, timeout_seconds: float) -> ToolOutput:
        argv = self._parse(command)
        self._reject_interactive(argv)
        self._validate_artifact_directory()
        self._artifact_directory.mkdir(parents=True, exist_ok=True)
        artifact = self._new_artifact_path()
        collector = _OutputCollector(self._max_output_bytes)
        started = monotonic()
        environment = self._sanitized_environment()
        environment["PYTHONPYCACHEPREFIX"] = str(artifact.with_suffix(".pycache"))

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self._workspace,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            artifact.unlink(missing_ok=True)
            raise ToolExecutionError(f"Command could not be started: {exc}") from exc

        if process.stdout is None:
            await self._terminate(process)
            raise ToolExecutionError("Command output pipe was not created")

        capture_task = asyncio.create_task(self._capture(process.stdout, artifact, collector))
        wait_task = asyncio.create_task(process.wait())
        timed_out = False
        try:
            done, _ = await asyncio.wait(
                {capture_task, wait_task},
                timeout=timeout_seconds,
                return_when=asyncio.ALL_COMPLETED,
            )
            if len(done) != 2:
                timed_out = True
                await self._terminate(process)
            await asyncio.wait_for(
                asyncio.gather(capture_task, wait_task),
                timeout=self.TERMINATE_GRACE_SECONDS,
            )
        except TimeoutError:
            await self._kill(process)
            await asyncio.gather(capture_task, wait_task, return_exceptions=True)
        except OSError as exc:
            await self._kill(process)
            await asyncio.gather(capture_task, wait_task, return_exceptions=True)
            raise ToolExecutionError(f"Command output could not be persisted: {exc}") from exc
        except asyncio.CancelledError:
            await self._kill(process)
            await asyncio.gather(capture_task, wait_task, return_exceptions=True)
            raise

        duration_ms = max(0, round((monotonic() - started) * 1000))
        exit_code = process.returncode
        status = (
            ObservationStatus.TIMEOUT
            if timed_out
            else ObservationStatus.SUCCESS
            if exit_code == 0
            else ObservationStatus.ERROR
        )
        relative_artifact = artifact.relative_to(self._workspace).as_posix()
        return ToolOutput(
            summary=self._summary(argv, exit_code, timed_out),
            content=collector.render(),
            metadata={
                "argv": argv,
                "cwd": str(self._workspace),
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_ms": duration_ms,
                "artifact_path": relative_artifact,
                "output_bytes": collector.total,
                "truncated": collector.truncated,
            },
            status=status,
        )

    @staticmethod
    def _parse(command: str) -> list[str]:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ToolExecutionError(f"Command cannot be parsed: {exc}") from exc
        if not argv:
            raise ToolExecutionError("Command must not be empty")
        if any("\x00" in argument for argument in argv):
            raise ToolExecutionError("Command arguments must not contain NUL bytes")
        return argv

    @staticmethod
    def _reject_interactive(argv: list[str]) -> None:
        executable = os.path.basename(argv[0]).lower()
        arguments = [argument.lower() for argument in argv[1:]]
        if is_interactive_command(executable, arguments):
            raise ToolExecutionError("interactive commands are not supported")

    async def _capture(
        self,
        stream: asyncio.StreamReader,
        artifact: Path,
        collector: _OutputCollector,
    ) -> None:
        with artifact.open("wb") as handle:
            while chunk := await stream.read(65_536):
                handle.write(chunk)
                collector.add(chunk)
            handle.flush()
            os.fsync(handle.fileno())

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        self._signal_process(process, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=self.TERMINATE_GRACE_SECONDS)
        except TimeoutError:
            await self._kill(process)

    async def _kill(self, process: asyncio.subprocess.Process) -> None:
        self._signal_process(process, signal.SIGKILL)
        await process.wait()

    @staticmethod
    def _signal_process(
        process: asyncio.subprocess.Process, selected_signal: signal.Signals
    ) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, selected_signal)
            elif process.returncode is not None:
                return
            elif selected_signal is signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            return

    def _new_artifact_path(self) -> Path:
        descriptor, name = tempfile.mkstemp(
            prefix="command-", suffix=".log", dir=self._artifact_directory
        )
        os.close(descriptor)
        return Path(name)

    def _validate_artifact_directory(self) -> None:
        try:
            relative = self._artifact_directory.relative_to(self._workspace)
            self._artifact_directory.resolve(strict=False).relative_to(self._workspace)
        except ValueError as exc:
            raise ToolExecutionError("artifact directory must remain inside the workspace") from exc

        current = self._workspace
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ToolExecutionError("artifact directory must not contain symbolic links")

    @classmethod
    def _sanitized_environment(cls) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if not any(fragment in key.upper() for fragment in cls.SECRET_ENV_FRAGMENTS)
        }

    @staticmethod
    def _summary(argv: list[str], exit_code: int | None, timed_out: bool) -> str:
        executable = os.path.basename(argv[0])
        if timed_out:
            return f"Command timed out: {executable}"
        return f"Command exited with code {exit_code}: {executable}"


class RunCommandTool(BaseTool):
    """Model-facing adapter for the bounded command runtime."""

    name = "run_command"
    description = "Run one bounded, non-interactive command in the workspace."
    arguments_model = RunCommandArguments

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = cast(RunCommandArguments, arguments)
        timeout = request.timeout_seconds or context.command_timeout_seconds
        if timeout > context.command_timeout_seconds:
            raise ToolExecutionError(
                f"timeout_seconds exceeds the configured limit of "
                f"{context.command_timeout_seconds:g}"
            )
        runtime = CommandRuntime(
            workspace=context.paths.root,
            artifact_directory=context.paths.root / ".bluewhale" / "artifacts" / "commands",
            max_output_bytes=context.max_command_output_bytes,
        )
        return await runtime.run(request.command, timeout)
