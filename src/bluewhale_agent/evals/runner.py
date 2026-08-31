"""Execute isolated evaluation cases and run hidden verification afterward."""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import shlex
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from uuid import uuid4

from bluewhale_agent.agent.loop import AgentLoop
from bluewhale_agent.domain.models import RunStatus
from bluewhale_agent.evals.models import EvalAttempt, EvalCase, EvalReport, EvalSuite
from bluewhale_agent.providers.base import ModelProvider
from bluewhale_agent.runtime.permissions import PermissionMode


class EvalRunner:
    def __init__(self, provider_factory: Callable[[], ModelProvider], *, model: str) -> None:
        self._provider_factory = provider_factory
        self._model = model

    async def run(
        self,
        suite: EvalSuite,
        *,
        suite_directory: Path,
        repeats: int = 1,
        output_directory: Path | None = None,
    ) -> EvalReport:
        if repeats < 1:
            raise ValueError("repeats must be at least 1")
        attempts: list[EvalAttempt] = []
        for attempt_index in range(1, repeats + 1):
            for case in suite.cases:
                attempts.append(
                    await self._run_case(
                        case,
                        suite_directory,
                        attempt_index=attempt_index,
                        output_directory=output_directory,
                    )
                )
        return EvalReport(suite=suite.name, model=self._model, attempts=tuple(attempts))

    async def _run_case(
        self,
        case: EvalCase,
        suite_directory: Path,
        *,
        attempt_index: int,
        output_directory: Path | None,
    ) -> EvalAttempt:
        started = monotonic()
        case_id = str(case.id)
        with tempfile.TemporaryDirectory(prefix=f"bluewhale-eval-{case_id}-") as temporary:
            workspace = Path(temporary) / "workspace"
            source = (suite_directory / str(case.workspace)).resolve()
            shutil.copytree(source, workspace)
            before = self._snapshot(workspace)
            result = await AgentLoop(
                run_id=f"eval-{case_id}-{uuid4().hex}",
                workspace=workspace,
                provider=self._provider_factory(),
                permission_mode=PermissionMode.FULL,
                allowed_change_paths=case.expected_paths,
            ).run(str(case.task))
            hidden = (suite_directory / str(case.hidden_test)).resolve()
            hidden_verification = await self._hidden_test(hidden, workspace)
            after = self._snapshot(workspace)
            changed_paths = tuple(
                sorted(
                    path
                    for path in set(before) | set(after)
                    if before.get(path) != after.get(path)
                )
            )
            expected = set(case.expected_paths)
            unrelated = sorted(
                path
                for path in changed_paths
                if path not in expected
            )
            failures: list[str] = []
            if unrelated:
                failures.append("unrelated_file_change")
            if result.status is RunStatus.COMPLETED and not hidden_verification:
                failures.append("false_completion")
            if any(observation.status.value == "denied" for observation in result.observations):
                failures.append("boundary_violation")
            public_verification = bool(
                result.verification is not None and result.verification.passed
            )
            trajectory_path: str | None = None
            diff_path: str | None = None
            artifact_directory: Path | None = None
            if output_directory is not None:
                artifact_directory = output_directory / case_id / str(attempt_index)
                artifact_directory.mkdir(parents=True, exist_ok=True)
                trajectory_target = artifact_directory / "trajectory.jsonl"
                shutil.copyfile(result.trajectory.events_path, trajectory_target)
                diff_target = artifact_directory / "changes.diff"
                diff_target.write_text(
                    self._render_diff(before, after, changed_paths),
                    encoding="utf-8",
                )
                trajectory_path = trajectory_target.relative_to(output_directory).as_posix()
                diff_path = diff_target.relative_to(output_directory).as_posix()
            attempt = EvalAttempt(
                case_id=case_id,
                attempt_index=attempt_index,
                completed=result.status is RunStatus.COMPLETED,
                public_verification=public_verification,
                hidden_verification=hidden_verification,
                repair_attempts=result.repair_attempts,
                duration_ms=max(0, round((monotonic() - started) * 1000)),
                changed_paths=changed_paths,
                trajectory_path=trajectory_path,
                diff_path=diff_path,
                failure_types=tuple(failures),
            )
            if artifact_directory is not None:
                (artifact_directory / "attempt.json").write_text(
                    json.dumps(
                        attempt.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            return attempt

    @staticmethod
    async def _hidden_test(script: Path, workspace: Path) -> bool:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(workspace)
        process = await asyncio.create_subprocess_exec(
            *shlex.split(f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"),
            cwd=workspace,
            env=environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            return await asyncio.wait_for(process.wait(), timeout=30) == 0
        except TimeoutError:
            process.kill()
            await process.wait()
            return False

    @staticmethod
    def _snapshot(workspace: Path) -> dict[str, bytes]:
        return {
            path.relative_to(workspace).as_posix(): path.read_bytes()
            for path in workspace.rglob("*")
            if path.is_file()
            and ".bluewhale" not in path.parts
            and "__pycache__" not in path.parts
            and not EvalRunner._is_executable_binary(path)
        }

    @staticmethod
    def _is_executable_binary(path: Path) -> bool:
        if not os.access(path, os.X_OK):
            return False
        try:
            return b"\x00" in path.read_bytes()[:4096]
        except OSError:
            return False

    @staticmethod
    def _render_diff(
        before: dict[str, bytes],
        after: dict[str, bytes],
        changed_paths: tuple[str, ...],
    ) -> str:
        chunks: list[str] = []
        for path in changed_paths:
            old = before.get(path)
            new = after.get(path)
            old_lines = (old or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
            new_lines = (new or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
            chunks.extend(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{path}" if old is not None else "/dev/null",
                    tofile=f"b/{path}" if new is not None else "/dev/null",
                )
            )
        return "".join(chunks)
