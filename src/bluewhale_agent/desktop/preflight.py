"""Deterministic first-run checks for the macOS desktop application."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bluewhale_agent.desktop.secrets import SecretStore, SecretStoreError


class CheckStatus(StrEnum):
    """Severity of one preflight check."""

    PASS = "pass"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class PreflightCheck:
    """One user-facing, secret-free readiness result."""

    key: str
    label: str
    status: CheckStatus
    summary: str


@dataclass(frozen=True)
class PreflightReport:
    """Aggregate desktop readiness report."""

    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.status is not CheckStatus.ERROR for check in self.checks)

    def by_key(self, key: str) -> PreflightCheck:
        for check in self.checks:
            if check.key == key:
                return check
        raise KeyError(key)

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "checks": [
                {
                    "key": check.key,
                    "label": check.label,
                    "status": check.status.value,
                    "summary": check.summary,
                }
                for check in self.checks
            ],
        }


ExecutableLookup = Callable[[str], str | None]
WritableCheck = Callable[[Path], bool]


class PreflightRunner:
    """Check only capabilities relevant to the currently opened project."""

    def __init__(
        self,
        *,
        secrets: SecretStore,
        platform: str | None = None,
        which: ExecutableLookup = shutil.which,
        writable: WritableCheck | None = None,
    ) -> None:
        self._secrets = secrets
        self._platform = platform or sys.platform
        self._which = which
        self._writable = writable or _workspace_is_writable

    def run(self, workspace: Path | None = None) -> PreflightReport:
        checks = [self._api_key_check()]
        if workspace is not None:
            checks.append(self._workspace_check(workspace))
        checks.append(self._sandbox_check())
        if workspace is not None and workspace.is_dir():
            checks.extend(self._toolchain_checks(workspace))
        return PreflightReport(tuple(checks))

    def _api_key_check(self) -> PreflightCheck:
        try:
            configured = self._secrets.has_api_key()
        except SecretStoreError:
            return PreflightCheck(
                "deepseek_api_key",
                "DeepSeek API",
                CheckStatus.ERROR,
                "无法读取系统钥匙串中的 API Key",
            )
        if configured:
            return PreflightCheck(
                "deepseek_api_key", "DeepSeek API", CheckStatus.PASS, "API Key 已配置"
            )
        return PreflightCheck(
            "deepseek_api_key",
            "DeepSeek API",
            CheckStatus.ERROR,
            "尚未配置 DeepSeek API Key",
        )

    def _workspace_check(self, workspace: Path) -> PreflightCheck:
        if workspace.is_dir() and self._writable(workspace):
            return PreflightCheck(
                "workspace_write", "项目权限", CheckStatus.PASS, "项目目录可读写"
            )
        return PreflightCheck(
            "workspace_write",
            "项目权限",
            CheckStatus.ERROR,
            "项目目录不存在或不可写",
        )

    def _sandbox_check(self) -> PreflightCheck:
        if self._platform != "darwin":
            return PreflightCheck(
                "macos_sandbox",
                "macOS 沙箱",
                CheckStatus.ERROR,
                "桌面版当前只支持 macOS Seatbelt",
            )
        if self._which("sandbox-exec"):
            return PreflightCheck(
                "macos_sandbox", "macOS 沙箱", CheckStatus.PASS, "Seatbelt 可用"
            )
        return PreflightCheck(
            "macos_sandbox",
            "macOS 沙箱",
            CheckStatus.ERROR,
            "未找到 sandbox-exec，无法提供命令隔离",
        )

    def _toolchain_checks(self, workspace: Path) -> list[PreflightCheck]:
        names = {entry.name for entry in workspace.iterdir()}
        checks: list[PreflightCheck] = []
        has_python = bool({"pyproject.toml", "setup.py", "requirements.txt"} & names) or any(
            workspace.glob("*.py")
        )
        has_node = "package.json" in names
        has_cpp = "CMakeLists.txt" in names or any(workspace.glob("*.c")) or any(
            workspace.glob("*.cpp")
        )
        if has_python:
            checks.append(
                self._tool_check(
                    "python_toolchain", "Python", ("python3", "python"), "Python 解释器"
                )
            )
        if has_node:
            checks.append(
                self._tool_check("node_toolchain", "Node.js", ("node", "npm"), "Node.js 与 npm")
            )
        if has_cpp:
            checks.append(
                self._tool_check("cpp_toolchain", "C/C++", ("c++", "clang++", "g++"), "C++ 编译器")
            )
        if "CMakeLists.txt" in names:
            checks.append(self._tool_check("cmake_toolchain", "CMake", ("cmake",), "CMake"))
        return checks

    def _tool_check(
        self,
        key: str,
        label: str,
        alternatives: tuple[str, ...],
        description: str,
    ) -> PreflightCheck:
        if key == "node_toolchain":
            available = all(self._which(name) for name in alternatives)
        else:
            available = any(self._which(name) for name in alternatives)
        if available:
            return PreflightCheck(key, label, CheckStatus.PASS, f"{description}可用")
        return PreflightCheck(
            key,
            label,
            CheckStatus.WARNING,
            f"未找到{description}；相关验证命令将不可用",
        )


def _workspace_is_writable(workspace: Path) -> bool:
    return os.access(workspace, os.R_OK | os.W_OK | os.X_OK)

