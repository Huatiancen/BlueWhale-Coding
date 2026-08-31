from __future__ import annotations

from pathlib import Path

from bluewhale_agent.desktop.preflight import (
    CheckStatus,
    PreflightRunner,
)
from bluewhale_agent.desktop.secrets import MemorySecretStore


def test_preflight_reports_missing_key_workspace_and_seatbelt(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    runner = PreflightRunner(
        secrets=MemorySecretStore(),
        platform="darwin",
        which=lambda name: None,
        writable=lambda path: False,
    )

    report = runner.run(workspace)

    assert report.ready is False
    assert report.by_key("deepseek_api_key").status is CheckStatus.ERROR
    assert report.by_key("workspace_write").status is CheckStatus.ERROR
    assert report.by_key("macos_sandbox").status is CheckStatus.ERROR
    assert "API Key" in report.by_key("deepseek_api_key").summary


def test_preflight_checks_only_toolchains_implied_by_project(tmp_path: Path) -> None:
    workspace = tmp_path / "mixed"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (workspace / "package.json").write_text("{}", encoding="utf-8")
    (workspace / "main.cpp").write_text("int main() {}\n", encoding="utf-8")
    store = MemorySecretStore()
    store.set_api_key("sk-test-preflight-key")
    available = {
        "sandbox-exec": "/usr/bin/sandbox-exec",
        "python3": "/usr/bin/python3",
        "node": "/usr/local/bin/node",
        "npm": "/usr/local/bin/npm",
        "c++": "/usr/bin/c++",
    }
    runner = PreflightRunner(
        secrets=store,
        platform="darwin",
        which=available.get,
        writable=lambda path: True,
    )

    report = runner.run(workspace)

    assert report.ready is True
    assert report.by_key("python_toolchain").status is CheckStatus.PASS
    assert report.by_key("node_toolchain").status is CheckStatus.PASS
    assert report.by_key("cpp_toolchain").status is CheckStatus.PASS
    assert "cmake_toolchain" not in {check.key for check in report.checks}


def test_preflight_marks_optional_project_tool_as_warning(tmp_path: Path) -> None:
    workspace = tmp_path / "cmake-project"
    workspace.mkdir()
    (workspace / "CMakeLists.txt").write_text("project(demo)\n", encoding="utf-8")
    store = MemorySecretStore()
    store.set_api_key("sk-test-preflight-key")
    runner = PreflightRunner(
        secrets=store,
        platform="darwin",
        which=lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None,
        writable=lambda path: True,
    )

    report = runner.run(workspace)

    assert report.ready is True
    assert report.by_key("cmake_toolchain").status is CheckStatus.WARNING

