"""Operating-system command isolation for local tool execution."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CommandSandbox(Protocol):
    """Wrap an argv tuple in an operating-system sandbox launcher."""

    def wrap(self, argv: tuple[str, ...]) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class NoopSandbox:
    """Fallback used on platforms where BlueWhale has no native sandbox yet."""

    def wrap(self, argv: tuple[str, ...]) -> tuple[str, ...]:
        return argv


class SeatbeltSandbox:
    """macOS Seatbelt profile scoped to the selected workspace."""

    executable = "/usr/bin/sandbox-exec"

    def __init__(self, *, workspace: Path, allow_network: bool = False) -> None:
        self._workspace = workspace.resolve()
        self._allow_network = allow_network
        self.profile = self._build_profile()

    def wrap(self, argv: tuple[str, ...]) -> tuple[str, ...]:
        return (self.executable, "-p", self.profile, *argv)

    def _build_profile(self) -> str:
        workspace = self._literal(self._workspace)
        readable_roots = (
            "/System",
            "/usr",
            "/bin",
            "/sbin",
            "/Library",
            "/Applications/Xcode.app",
            "/opt/homebrew",
            "/private/etc",
            "/private/var/db/timezone",
        )
        read_rules = "\n".join(
            f'  (subpath "{self._escape(path)}")' for path in readable_roots
        )
        network = "(allow network*)" if self._allow_network else "(deny network*)"
        return f"""(version 1)
(deny default)
(allow process*)
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm)
(allow file-read-metadata)
(allow file-read*
{read_rules}
  (subpath "{workspace}"))
(allow file-write*
  (subpath "{workspace}")
  (literal "/dev/null"))
{network}
"""

    @classmethod
    def _literal(cls, path: Path) -> str:
        return cls._escape(str(path))

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


def command_sandbox(
    workspace: Path,
    *,
    allow_network: bool = False,
) -> CommandSandbox:
    """Select the strongest native sandbox supported by this platform."""

    if (
        sys.platform == "darwin"
        and Path(SeatbeltSandbox.executable).is_file()
        and not os.environ.get("CODEX_SANDBOX")
    ):
        return SeatbeltSandbox(workspace=workspace, allow_network=allow_network)
    return NoopSandbox()
