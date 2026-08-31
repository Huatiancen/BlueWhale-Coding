"""Operating-system command isolation for local tool execution."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
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

    def __init__(
        self,
        *,
        workspace: Path,
        allow_network: bool = False,
        executable_lookup: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._workspace = workspace.resolve()
        self._allow_network = allow_network
        self._executable_lookup = executable_lookup
        self.profile = self._build_profile()

    def wrap(self, argv: tuple[str, ...]) -> tuple[str, ...]:
        profile = self._build_profile(self._toolchain_read_roots(argv[0]))
        return (self.executable, "-p", profile, *argv)

    def _build_profile(self, extra_readable_roots: tuple[str, ...] = ()) -> str:
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
            sys.prefix,
            sys.base_prefix,
        )
        allowed_subpaths = (*readable_roots, *extra_readable_roots, str(self._workspace))
        ancestor_literals = sorted(
            {
                str(parent)
                for root in allowed_subpaths
                for parent in (Path(root), *Path(root).parents)
            }
        )
        read_exceptions = "\n".join(
            f'  (require-not (subpath "{self._escape(path)}"))'
            for path in allowed_subpaths
        )
        read_exceptions += "\n" + "\n".join(
            f'  (require-not (literal "{self._escape(path)}"))'
            for path in ancestor_literals
        )
        network = "(allow network*)" if self._allow_network else "(deny network*)"
        return f"""(version 1)
(allow default)
(deny file-read-data
 (require-all
{read_exceptions}))
(deny file-write*
 (require-all
  (require-not (subpath "{workspace}"))
  (require-not (literal "/dev/null"))))
{network}
"""

    def _toolchain_read_roots(self, executable: str) -> tuple[str, ...]:
        located = self._executable_lookup(executable)
        if located is None:
            return ()
        requested = Path(located).expanduser().absolute()
        roots: set[Path] = {requested.resolve(strict=False)}
        if requested.parent.name == "bin":
            roots.add(requested.parent.parent.resolve(strict=False))
        return tuple(sorted(map(str, roots)))

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
