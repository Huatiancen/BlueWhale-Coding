from bluewhale_agent.runtime.changeset import ChangeSet


def test_snapshot_reports_stable_file_and_line_counts() -> None:
    changeset = ChangeSet()
    changeset.record("src/new.py", None, "one\ntwo\n")
    changeset.record("src/app.py", "old\nkeep\n", "new\nkeep\nextra\n")

    snapshot = changeset.snapshot()

    assert [item.path for item in snapshot.files] == ["src/app.py", "src/new.py"]
    assert snapshot.additions == 4
    assert snapshot.deletions == 1
    app = snapshot.files[0]
    assert app.created is False
    assert (app.additions, app.deletions) == (2, 1)
    assert app.after == "new\nkeep\nextra\n"
    assert "--- a/src/app.py" in app.diff
    assert "+new" in app.diff


def test_snapshot_marks_created_empty_file_and_contains_aggregate_diff() -> None:
    changeset = ChangeSet()
    changeset.record("empty.txt", None, "")

    snapshot = changeset.snapshot()

    assert len(snapshot.files) == 1
    assert snapshot.files[0].created is True
    assert snapshot.files[0].additions == 0
    assert snapshot.diff.startswith("--- /dev/null")
