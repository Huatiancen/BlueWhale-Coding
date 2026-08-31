"""Explicit local-tool permission decisions."""

from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bluewhale_agent.domain.models import Action
from bluewhale_agent.runtime.command_plan import CommandPlanError, parse_command_plan
from bluewhale_agent.runtime.paths import PathAccessError, WorkspacePaths


class PermissionDecision(StrEnum):
    """Possible decisions for a requested local action."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionMode(StrEnum):
    """User-selected approval strictness for one agent run."""

    ASK = "ask"
    BALANCED = "balanced"
    FULL = "full"


class PermissionResult(BaseModel):
    """Permission decision plus a user-facing reason."""

    model_config = ConfigDict(frozen=True)

    decision: PermissionDecision
    reason: str
    allow_network: bool = False


class PermissionPolicy:
    """Classify local tool actions before execution."""

    READ_ONLY_TOOLS = frozenset(
        {"get_diff", "list_files", "load_skill", "read_file", "search_text"}
    )
    LOCAL_CONTROL_TOOLS = frozenset({"update_plan"})

    def __init__(
        self,
        paths: WorkspacePaths | None = None,
        mode: PermissionMode = PermissionMode.BALANCED,
    ) -> None:
        self._paths = paths
        self._mode = mode

    def evaluate(self, action: Action) -> PermissionResult:
        if action.tool_name in self.READ_ONLY_TOOLS:
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="Known read-only workspace tool",
            )
        if action.tool_name in self.LOCAL_CONTROL_TOOLS:
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="Local agent control operation",
            )
        if action.tool_name == "apply_patch":
            return self._evaluate_file_mutation(action)
        if action.tool_name == "write_file":
            return self._evaluate_file_mutation(action)
        if action.tool_name == "run_command":
            return self._evaluate_run_command(action)
        return PermissionResult(
            decision=PermissionDecision.DENY,
            reason=f"Tool is not allowed by the current policy: {action.tool_name}",
        )

    def _evaluate_file_mutation(self, action: Action) -> PermissionResult:
        requested = action.arguments.get("path")
        if not isinstance(requested, str) or self._paths is None:
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="File mutation requires a valid workspace path",
            )
        try:
            self._paths.resolve(requested, must_exist=False)
        except PathAccessError as exc:
            return PermissionResult(decision=PermissionDecision.DENY, reason=str(exc))
        if self._mode is PermissionMode.ASK:
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason="Current permission mode requires approval for file changes",
            )
        return PermissionResult(
            decision=PermissionDecision.ALLOW,
            reason="Workspace file mutation is allowed by the current permission mode",
        )

    def _evaluate_run_command(self, action: Action) -> PermissionResult:
        command = action.arguments.get("command")
        if not isinstance(command, str):
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="Command must be a non-empty string",
            )
        try:
            plan = parse_command_plan(command)
        except CommandPlanError as exc:
            if self._mode is not PermissionMode.FULL:
                return PermissionResult(
                    decision=PermissionDecision.ASK,
                    reason=f"命令语法需要确认，执行时将由安全运行时校验：{exc}",
                )
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason=f"命令语法将由安全运行时返回结构化错误：{exc}",
            )

        results = [
            self._evaluate_argv(argv)
            for step in plan.steps
            for argv in step.commands
        ]
        severity = {
            PermissionDecision.ALLOW: 0,
            PermissionDecision.ASK: 1,
            PermissionDecision.DENY: 2,
        }
        selected = max(results, key=lambda item: severity[item.decision])
        return selected.model_copy(
            update={"allow_network": any(item.allow_network for item in results)}
        )

    def _evaluate_argv(self, argv: tuple[str, ...]) -> PermissionResult:
        executable = os.path.basename(argv[0]).lower()
        arguments = [item.lower() for item in argv[1:]]
        if _is_dangerous_command(executable, arguments):
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason=f"命令 {argv[0]} 可能执行破坏性或高权限操作，需要你明确确认",
            )
        if is_interactive_command(executable, arguments):
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason=f"命令 {argv[0]} 需要交互式终端，当前不支持",
            )
        if self._mode is PermissionMode.ASK:
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason=f"当前权限模式要求确认命令 {argv[0]}",
            )
        if self._mode is PermissionMode.FULL:
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason=f"完全访问权限允许非破坏性命令 {argv[0]}",
            )
        if _requires_command_approval(executable, arguments):
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason=f"命令 {argv[0]} 涉及联网、安装、发布或 Git 写入，需要你确认",
                allow_network=_requires_network(executable, arguments),
            )
        if _is_known_safe_command(executable, arguments) and not self._is_trusted_executable(
            argv[0]
        ):
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason=f"可执行路径 {argv[0]} 不在可信工具目录中，需要你确认",
            )
        if _is_known_safe_command(executable, arguments) and not _has_unsafe_path_argument(
            arguments, self._paths
        ):
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason=f"命令 {argv[0]} 已匹配可信开发工具规则",
            )
        return PermissionResult(
            decision=PermissionDecision.ASK,
            reason=f"命令 {argv[0]} 未匹配可信开发工具规则，需要你确认",
        )

    def _is_trusted_executable(self, executable: str) -> bool:
        requested = Path(executable)
        if len(requested.parts) == 1:
            return True
        if requested.is_absolute():
            resolved = requested.resolve(strict=False)
            return any(
                resolved.is_relative_to(root)
                for root in map(Path, ("/bin", "/usr/bin", "/usr/sbin", "/sbin"))
            )
        if self._paths is None:
            return False
        resolved = (self._paths.root / requested).resolve(strict=False)
        return resolved.is_relative_to(self._paths.root / ".venv" / "bin")


def is_interactive_command(executable: str, arguments: list[str]) -> bool:
    if executable in {"bash", "fish", "sh", "zsh", "ssh", "telnet", "vim", "vi", "nano"}:
        return True
    is_repl = _is_python_executable(executable) or executable in {"node", "irb", "ghci"}
    if is_repl and not arguments:
        return True
    return is_repl and ("-i" in arguments or "--interactive" in arguments)


def _is_dangerous_command(executable: str, arguments: list[str]) -> bool:
    if executable in {
        "dd",
        "doas",
        "kill",
        "killall",
        "mkfs",
        "pkill",
        "reboot",
        "rm",
        "rmdir",
        "shutdown",
        "shred",
        "sudo",
        "su",
    }:
        return True
    if executable == "git" and arguments:
        subcommand = arguments[0]
        if subcommand in {"clean", "reset"}:
            return True
        if subcommand in {"checkout", "restore"} and "--" in arguments:
            return True
    return False


def _requires_command_approval(executable: str, arguments: list[str]) -> bool:
    if executable in {"curl", "wget"}:
        return True
    if executable == "git" and arguments:
        return arguments[0] in {"commit", "merge", "push", "rebase", "tag"}
    if executable in {"pip", "pip3"}:
        return bool(arguments and arguments[0] in {"install", "uninstall"})
    if executable in {"npm", "pnpm", "yarn"}:
        return bool(arguments and arguments[0] in {"add", "install", "publish", "remove"})
    if executable in {"brew", "apt", "apt-get", "dnf", "pacman"}:
        return True
    if _is_python_executable(executable) and len(arguments) >= 3:
        return arguments[:3] in (["-m", "pip", "install"], ["-m", "pip", "uninstall"])
    return False


def _requires_network(executable: str, arguments: list[str]) -> bool:
    if executable in {"curl", "wget", "brew", "apt", "apt-get", "dnf", "pacman"}:
        return True
    if executable in {"pip", "pip3"}:
        return bool(arguments and arguments[0] == "install")
    if executable in {"npm", "pnpm", "yarn"}:
        return bool(arguments and arguments[0] in {"add", "install", "publish"})
    return _is_python_executable(executable) and arguments[:3] == ["-m", "pip", "install"]


def _is_known_safe_command(executable: str, arguments: list[str]) -> bool:
    if executable in {
        "cat",
        "diff",
        "file",
        "grep",
        "head",
        "ls",
        "pwd",
        "rg",
        "stat",
        "tail",
        "wc",
        "which",
    }:
        return True
    if executable in {
        "biome",
        "black",
        "eslint",
        "isort",
        "jest",
        "mypy",
        "nox",
        "prettier",
        "pytest",
        "ruff",
        "tox",
        "tsc",
        "vitest",
    }:
        return True
    if executable == "git" and arguments:
        return arguments[0] in {
            "branch",
            "diff",
            "log",
            "ls-files",
            "rev-parse",
            "show",
            "status",
        }
    if _is_python_executable(executable) and len(arguments) >= 2:
        return arguments[0] == "-m" and arguments[1] in {
            "compileall",
            "mypy",
            "pytest",
            "ruff",
            "unittest",
        }
    if executable in {"cargo", "go"} and arguments:
        return arguments[0] in {"build", "check", "clippy", "fmt", "test", "vet"}
    if executable == "swift" and arguments:
        return arguments[0] in {"build", "test"}
    if executable in {"cc", "c++", "gcc", "g++", "clang", "clang++"}:
        return not _compiler_uses_plugin(arguments)
    if executable in {
        "clang-format",
        "clang-tidy",
        "cmake",
        "ctest",
        "gofmt",
        "java",
        "javac",
        "ninja",
        "rustc",
        "rustfmt",
        "swiftc",
    }:
        return True
    if executable in {"npm", "pnpm", "yarn"} and arguments:
        return arguments[0] in {"build", "lint", "test", "typecheck"} or (
            arguments[0] == "run"
            and len(arguments) > 1
            and arguments[1] in {"build", "check", "lint", "test", "typecheck"}
        )
    if executable in {"make", "mvn", "gradle", "gradlew"} and arguments:
        return any(item in {"build", "check", "package", "test", "verify"} for item in arguments)
    return False


def _is_python_executable(executable: str) -> bool:
    return re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", executable) is not None


def _compiler_uses_plugin(arguments: list[str]) -> bool:
    if any(item.startswith(("-fplugin", "-fpass-plugin")) for item in arguments):
        return True
    return any(
        arguments[index : index + 2] == ["-xclang", "-load"]
        for index in range(len(arguments) - 1)
    )


def _has_unsafe_path_argument(
    arguments: list[str], paths: WorkspacePaths | None
) -> bool:
    for argument in arguments:
        candidates = [argument]
        if "=" in argument:
            candidates.append(argument.split("=", 1)[1])
        for prefix in ("-i", "-l", "-o"):
            if argument.startswith(prefix) and len(argument) > len(prefix):
                candidates.append(argument[len(prefix) :])
        for candidate in candidates:
            if candidate.startswith(("/", "~")) or ".." in Path(candidate).parts:
                return True
            if paths is not None and candidate and not candidate.startswith("-"):
                try:
                    paths.resolve(candidate, must_exist=False)
                except PathAccessError:
                    return True
    return False
