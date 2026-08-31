from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from bluewhale_agent.domain.models import ModelResponse
from bluewhale_agent.evals.models import EvalCase, EvalSuite
from bluewhale_agent.evals.runner import EvalRunner
from tests.fakes import FakeModelProvider


def test_snapshot_ignores_executable_build_artifacts_but_keeps_source(tmp_path: Path) -> None:
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    binary = tmp_path / "test_main"
    binary.write_bytes(b"\x00compiled-binary")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

    snapshot = EvalRunner._snapshot(tmp_path)

    assert "main.c" in snapshot
    assert "test_main" not in snapshot


@pytest.mark.asyncio
async def test_runner_repeats_cases_and_persists_each_attempt(tmp_path: Path) -> None:
    suite_directory = tmp_path / "suite"
    workspace = suite_directory / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "value.txt").write_text("original\n", encoding="utf-8")
    hidden_test = suite_directory / "hidden_test.py"
    hidden_test.write_text("raise SystemExit(0)\n", encoding="utf-8")
    suite = EvalSuite(
        name="repeatable",
        cases=(
            EvalCase(
                id="read-only",
                task="Describe the project without changing it",
                workspace="workspace",
                hidden_test="hidden_test.py",
                expected_paths=(),
            ),
        ),
    )

    def provider_factory() -> FakeModelProvider:
        return FakeModelProvider(
            [ModelResponse(content="No changes required.", finish_reason="stop")]
        )

    output = tmp_path / "results"
    report = await EvalRunner(provider_factory, model="fake-model").run(
        suite,
        suite_directory=suite_directory,
        repeats=2,
        output_directory=output,
    )

    assert [attempt.attempt_index for attempt in report.attempts] == [1, 2]
    assert all(attempt.hidden_verification for attempt in report.attempts)
    assert all(not attempt.public_verification for attempt in report.attempts)
    assert all(attempt.changed_paths == () for attempt in report.attempts)
    for attempt in report.attempts:
        assert attempt.trajectory_path is not None
        assert attempt.diff_path is not None
        assert (output / attempt.trajectory_path).is_file()
        assert (output / attempt.diff_path).read_text(encoding="utf-8") == ""
        attempt_path = output / attempt.case_id / str(attempt.attempt_index) / "attempt.json"
        payload = json.loads(attempt_path.read_text(encoding="utf-8"))
        assert payload["attempt_index"] == attempt.attempt_index
