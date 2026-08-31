"""Privacy-preserving desktop diagnostic bundle export."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from bluewhale_agent.trajectory.redaction import redact


class DiagnosticExporter:
    """Export selected summaries without source files or process environments."""

    def __init__(self, *, version: str, platform_name: str) -> None:
        self._version = version
        self._platform_name = platform_name

    def export(
        self,
        destination: Path,
        *,
        preflight: object,
        trajectory_summary: object,
        verification: object,
    ) -> Path:
        if destination.suffix.lower() != ".zip":
            raise ValueError("Diagnostic destination must use the .zip extension")
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = redact(
            {
                "schema_version": 1,
                "created_at": datetime.now(UTC).isoformat(),
                "app": {"version": self._version, "platform": self._platform_name},
                "preflight": preflight,
                "trajectory_summary": trajectory_summary,
                "verification": verification,
            }
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.stem}-",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.writestr(
                    "diagnostics.json",
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination
