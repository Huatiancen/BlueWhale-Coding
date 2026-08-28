"""Explicit local-tool permission decisions."""

from __future__ import annotations

import os
import re
import shlex
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from bluewhale_agent.domain.models import Action
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


class PermissionPolicy:
    """Classify local tool actions before execution."""

    READ_ONLY_TOOLS = frozenset({"get_diff", "list_files", "read_file", "search_text"})

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
            argv = shlex.split(command)
        except ValueError as exc:
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason=f"Command cannot be parsed: {exc}",
            )
        if not argv:
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="Command must not be empty",
            )

        executable = os.path.basename(argv[0]).lower()
        arguments = [item.lower() for item in argv[1:]]
        if _is_dangerous_command(executable, arguments):
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="Command is blocked by the destructive-command policy",
            )
        if is_interactive_command(executable, arguments):
            return PermissionResult(
                decision=PermissionDecision.DENY,
                reason="Interactive commands are not supported",
            )
        if self._mode is PermissionMode.ASK:
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason="Current permission mode requires approval for commands",
            )
        if self._mode is PermissionMode.FULL:
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="Non-destructive command is allowed by full access mode",
            )
        if _requires_command_approval(executable, arguments):
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason="Command requires explicit user approval",
            )
        if _is_known_safe_command(executable, arguments):
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="Recognized non-interactive development command",
            )
        return PermissionResult(
            decision=PermissionDecision.ASK,
            reason="Unrecognized commands require explicit user approval",
        )


def is_interactive_command(executable: str, arguments: list[str]) -> bool:
    if executable in {"bash", "fish", "sh", "zsh", "ssh", "telnet", "vim", "vi", "nano"}:
        return True
    is_repl = _is_python_executable(executable) or executable in {"node", "irb", "ghci"}
    if is_repl and not arguments:
        return True
    return "-i" in arguments or "--interactive" in arguments


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


def _is_known_safe_command(executable: str, arguments: list[str]) -> bool:
    if executable in {"pytest", "ruff", "mypy", "tox", "nox"}:
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
