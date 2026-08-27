from pathlib import Path

import pytest

from bluewhale_agent.domain.models import Action
from bluewhale_agent.runtime.paths import PathAccessError, WorkspacePaths
from bluewhale_agent.runtime.permissions import PermissionDecision, PermissionPolicy


def test_resolve_returns_canonical_path_inside_workspace(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('ok')\n", encoding="utf-8")

    resolved = WorkspacePaths(tmp_path).resolve("src/app.py")

    assert resolved == source.resolve()


@pytest.mark.parametrize("requested", ["../outside.py", "/tmp/outside.py"])
def test_resolve_rejects_paths_outside_workspace(tmp_path: Path, requested: str) -> None:
    with pytest.raises(PathAccessError, match="outside the workspace|absolute"):
        WorkspacePaths(tmp_path).resolve(requested)


def test_resolve_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(outside)

    with pytest.raises(PathAccessError, match="outside the workspace"):
        WorkspacePaths(tmp_path).resolve("linked.txt")


@pytest.mark.parametrize("name", [".env", ".env.local"])
def test_resolve_rejects_credential_files(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("DEEPSEEK_API_KEY=secret", encoding="utf-8")

    with pytest.raises(PathAccessError, match="protected"):
        WorkspacePaths(tmp_path).resolve(name)


@pytest.mark.parametrize("name", [".bluewhale/state.json", ".git/config"])
def test_resolve_rejects_runtime_metadata(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.parent.mkdir()
    path.write_text("internal", encoding="utf-8")

    with pytest.raises(PathAccessError, match="protected"):
        WorkspacePaths(tmp_path).resolve(name)


def test_iter_files_skips_runtime_and_dependency_directories(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass\n", encoding="utf-8")
    for ignored in (".git", ".bluewhale", ".venv", "node_modules", "__pycache__"):
        directory = tmp_path / ignored
        directory.mkdir()
        (directory / "ignored.py").write_text("secret\n", encoding="utf-8")

    files = WorkspacePaths(tmp_path).iter_files(".")

    assert [path.relative_to(tmp_path).as_posix() for path in files] == ["src/app.py"]


def test_permission_policy_allows_only_known_read_tools() -> None:
    policy = PermissionPolicy()

    allowed = policy.evaluate(Action(id="1", tool_name="read_file", arguments={}))
    denied = policy.evaluate(Action(id="2", tool_name="delete_file", arguments={}))

    assert allowed.decision is PermissionDecision.ALLOW
    assert denied.decision is PermissionDecision.DENY
