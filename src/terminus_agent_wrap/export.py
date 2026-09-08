"""Drive archive protocol and the spike's local-only stub.

Drive is the durable archive. Local scratch is ephemeral and may be pruned
only after a real export ack whose sha256 matches the admitted run-artifact.

This module does not call a cloud storage API. The stub writes
``drive_export.json`` with ``"status": "stubbed"``, which prune refuses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from terminus_xi.canonical import write_json

__all__ = [
    "DRIVE_EXPORT_NAME",
    "STATUS_EXPORTED",
    "STATUS_STUBBED",
    "DriveExporter",
    "LocalOnlyExporter",
]

DRIVE_EXPORT_NAME = "drive_export.json"
STATUS_STUBBED = "stubbed"
STATUS_EXPORTED = "exported"


class DriveExporter(Protocol):
    """Upload one run directory to Drive and return the ack document."""

    def export(
        self,
        run_dir: Path,
        *,
        sha256: str,
        run_id: str,
    ) -> Mapping[str, Any]:
        """Write ``drive_export.json`` into ``run_dir`` and return it."""


class LocalOnlyExporter:
    """Spike stub. Not a verified Drive ack. Prune must refuse this status."""

    def export(
        self,
        run_dir: Path,
        *,
        sha256: str,
        run_id: str,
    ) -> dict[str, Any]:
        document = {
            "schema": "terminus-agent-wrap.drive-export.v1",
            "status": STATUS_STUBBED,
            "run_id": run_id,
            "sha256": sha256,
            "detail": (
                "LocalOnlyExporter does not upload. Drive remains the durable "
                "archive; this stub is not a verified ack."
            ),
        }
        write_json(Path(run_dir) / DRIVE_EXPORT_NAME, document)
        return document
