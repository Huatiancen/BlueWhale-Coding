from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from bluewhale_agent.evals.models import EvalSuite


def test_bluewhale_15_suite_has_fixed_language_distribution() -> None:
    root = Path(__file__).parents[2] / "evals" / "bluewhale-15"
    suite = EvalSuite.load(root / "suite.json")

    assert len(suite.cases) == 15
    assert len({case.id for case in suite.cases}) == 15
    assert Counter(case.language for case in suite.cases) == {
        "python": 7,
        "javascript": 4,
        "c_cpp": 4,
    }
    for case in suite.cases:
        workspace = (root / case.workspace).resolve()
        hidden_test = (root / case.hidden_test).resolve()
        assert workspace.is_dir()
        assert hidden_test.is_file()
        assert not hidden_test.is_relative_to(workspace)
        assert case.expected_paths
        assert all((workspace / path).is_file() for path in case.expected_paths)


def test_every_unmodified_workspace_fails_its_hidden_test(tmp_path: Path) -> None:
    root = Path(__file__).parents[2] / "evals" / "bluewhale-15"
    suite = EvalSuite.load(root / "suite.json")

    for case in suite.cases:
        workspace = tmp_path / case.id
        shutil.copytree(root / case.workspace, workspace)
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(workspace)
        completed = subprocess.run(
            [sys.executable, str(root / case.hidden_test)],
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert completed.returncode != 0, (
            f"{case.id} unexpectedly passed before repair:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
