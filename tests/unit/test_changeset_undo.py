from pathlib import Path

import pytest

from bluewhale_agent.runtime.changeset import ChangeSet
from bluewhale_agent.runtime.undo import ChangeSetUndoError, undo_changeset, undo_files


def test_undo_changeset_restores_existing_files_and_removes_created_files(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "app.py"
    created = tmp_path / "new.py"
    existing.write_text("after\n", encoding="utf-8")
    created.write_text("created\n", encoding="utf-8")
    changes = ChangeSet()
    changes.record("app.py", "before\n", "after\n")
    changes.record("new.py", None, "created\n")

    result = undo_changeset(tmp_path, changes.snapshot())

    assert result == ("app.py", "new.py")
    assert existing.read_text(encoding="utf-8") == "before\n"
    assert not created.exists()


def test_undo_changeset_rejects_conflicts_without_touching_any_file(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("later edit\n", encoding="utf-8")
    second.write_text("after two\n", encoding="utf-8")
    changes = ChangeSet()
    changes.record("first.py", "before one\n", "after one\n")
    changes.record("second.py", "before two\n", "after two\n")

    with pytest.raises(ChangeSetUndoError, match="first.py.*changed after"):
        undo_changeset(tmp_path, changes.snapshot())

    assert first.read_text(encoding="utf-8") == "later edit\n"
    assert second.read_text(encoding="utf-8") == "after two\n"


def test_undo_files_restores_only_selected_files(tmp_path: Path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("after first\n", encoding="utf-8")
    second.write_text("after second\n", encoding="utf-8")
    changes = ChangeSet()
    changes.record("first.py", "before first\n", "after first\n")
    changes.record("second.py", "before second\n", "after second\n")

    reverted = undo_files(tmp_path, changes.snapshot(), ("second.py",))

    assert reverted == ("second.py",)
    assert first.read_text(encoding="utf-8") == "after first\n"
    assert second.read_text(encoding="utf-8") == "before second\n"


def test_undo_files_rejects_path_outside_changeset(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("after\n", encoding="utf-8")
    changes = ChangeSet()
    changes.record("app.py", "before\n", "after\n")

    with pytest.raises(ChangeSetUndoError, match="not part of this change set"):
        undo_files(tmp_path, changes.snapshot(), ("README.md",))

    assert target.read_text(encoding="utf-8") == "after\n"


def test_undo_files_detects_conflict_without_reverting_other_selection(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("user edit\n", encoding="utf-8")
    second.write_text("after second\n", encoding="utf-8")
    changes = ChangeSet()
    changes.record("first.py", "before first\n", "after first\n")
    changes.record("second.py", "before second\n", "after second\n")

    with pytest.raises(ChangeSetUndoError, match="first.py.*changed after"):
        undo_files(tmp_path, changes.snapshot(), ("first.py", "second.py"))

    assert first.read_text(encoding="utf-8") == "user edit\n"
    assert second.read_text(encoding="utf-8") == "after second\n"
