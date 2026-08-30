"""Execute isolated evaluation cases and run hidden verification afterward."""

from __future__ import annotations

import asyncio
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
    ) -> EvalReport:
        attempts: list[EvalAttempt] = []
        for _ in range(repeats):
            for case in suite.cases:
                attempts.append(await self._run_case(case, suite_directory))
        return EvalReport(suite=suite.name, model=self._model, attempts=tuple(attempts))

    async def _run_case(self, case: EvalCase, suite_directory: Path) -> EvalAttempt:
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
            ).run(str(case.task))
            hidden = (suite_directory / str(case.hidden_test)).resolve()
            verified = await self._hidden_test(hidden, workspace)
            after = self._snapshot(workspace)
            expected = set(case.expected_paths)
            unrelated = sorted(
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path) and path not in expected
            )
            failures: list[str] = []
            if unrelated:
                failures.append("unrelated_file_change")
            if result.status is RunStatus.COMPLETED and not verified:
                failures.append("false_completion")
            if any(observation.status.value == "denied" for observation in result.observations):
                failures.append("boundary_violation")
            return EvalAttempt(
                case_id=case_id,
                completed=result.status is RunStatus.COMPLETED,
                verified=verified,
                repair_attempts=result.repair_attempts,
                duration_ms=max(0, round((monotonic() - started) * 1000)),
                failure_types=tuple(failures),
            )

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
            if path.is_file() and ".bluewhale" not in path.parts and "__pycache__" not in path.parts
        }
