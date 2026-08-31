from __future__ import annotations

import json
from pathlib import Path

from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.verification.discovery import discover_verification_commands


def commands(root: Path):
    return discover_verification_commands(WorkspacePaths(root))


def test_discovers_pytest_with_argv_and_workspace_cwd(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    discovered = commands(tmp_path)

    assert discovered[0].argv == ("python", "-m", "pytest", "-q")
    assert discovered[0].cwd == "."
    assert discovered[0].source == "pytest.ini"


def test_discovers_unittest_when_pytest_is_not_declared(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_store.py").write_text("import unittest\n", encoding="utf-8")

    discovered = commands(tmp_path)

    assert [item.argv for item in discovered] == [
        ("python", "-m", "unittest", "discover", "-s", "tests", "-v")
    ]
    assert discovered[0].source == "tests/test*.py"


def test_discovers_unittest_modules_at_project_root(tmp_path: Path) -> None:
    (tmp_path / "test_range_tools.py").write_text("import unittest\n", encoding="utf-8")

    discovered = commands(tmp_path)

    assert [item.argv for item in discovered] == [
        ("python", "-m", "unittest", "discover", "-s", ".", "-p", "test*.py", "-v")
    ]
    assert discovered[0].source == "test*.py"


def test_discovers_node_scripts_in_stable_priority_order(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"build": "vite build", "test": "node --test"}}),
        encoding="utf-8",
    )

    discovered = commands(tmp_path)

    assert [item.argv for item in discovered] == [
        ("npm", "run", "test"),
        ("npm", "run", "build"),
    ]


def test_discovers_make_test_target(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        "build:\n\tcc app.c -o app\n\ntest:\n\t./app\n",
        encoding="utf-8",
    )

    discovered = commands(tmp_path)

    assert [item.argv for item in discovered] == [("make", "test")]
    assert discovered[0].source == "Makefile:test"


def test_discovers_cmake_configure_build_and_ctest(tmp_path: Path) -> None:
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n"
        "project(example)\n"
        "enable_testing()\n"
        "add_test(NAME example COMMAND example_test)\n",
        encoding="utf-8",
    )

    discovered = commands(tmp_path)

    assert [item.argv for item in discovered] == [
        ("cmake", "-S", ".", "-B", ".bluewhale/cmake-build"),
        ("cmake", "--build", ".bluewhale/cmake-build"),
        ("ctest", "--test-dir", ".bluewhale/cmake-build", "--output-on-failure"),
    ]
    assert all(item.source == "CMakeLists.txt" for item in discovered)


def test_pytest_declaration_prevents_duplicate_unittest_command(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("import unittest\n", encoding="utf-8")

    assert [item.argv for item in commands(tmp_path)] == [
        ("python", "-m", "pytest", "-q")
    ]
