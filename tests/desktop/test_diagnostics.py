from __future__ import annotations

import json
import zipfile
from pathlib import Path

from bluewhale_agent.desktop.diagnostics import DiagnosticExporter


def test_diagnostic_zip_contains_only_sanitized_summary(tmp_path: Path) -> None:
    destination = tmp_path / "BlueWhale-Diagnostics.zip"
    exporter = DiagnosticExporter(version="0.1.0", platform_name="macOS-15")

    result = exporter.export(
        destination,
        preflight={"checks": [{"key": "api", "authorization": "Bearer secret-token"}]},
        trajectory_summary={
            "run_id": "run-1",
            "error": "DEEPSEEK_API_KEY=sk-super-secret-value",
            "token": "private-token",
        },
        verification={"level": "failed", "output": "Authorization: Bearer abcdefgh"},
    )

    assert result == destination
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == ["diagnostics.json"]
        payload = json.loads(archive.read("diagnostics.json"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == 1
    assert payload["app"]["version"] == "0.1.0"
    assert "super-secret" not in rendered
    assert "private-token" not in rendered
    assert "abcdefgh" not in rendered
    assert "[REDACTED]" in rendered


def test_diagnostic_export_refuses_non_zip_and_replaces_atomically(tmp_path: Path) -> None:
    exporter = DiagnosticExporter(version="0.1.0", platform_name="test")

    invalid = tmp_path / "diagnostics.json"
    try:
        exporter.export(invalid, preflight={}, trajectory_summary={}, verification={})
    except ValueError as error:
        assert ".zip" in str(error)
    else:
        raise AssertionError("non-ZIP diagnostics should be rejected")

    destination = tmp_path / "diagnostics.zip"
    destination.write_bytes(b"old")
    exporter.export(destination, preflight={}, trajectory_summary={}, verification={})
    assert zipfile.is_zipfile(destination)
    assert not list(tmp_path.glob("*.tmp"))


def test_diagnostic_payload_does_not_accept_source_or_environment_inputs() -> None:
    exporter = DiagnosticExporter(version="0.1.0", platform_name="test")

    assert "source" not in exporter.export.__annotations__
    assert "environment" not in exporter.export.__annotations__
