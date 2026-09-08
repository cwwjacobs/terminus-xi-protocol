"""Retention helper: local scratch may be deleted only after a verified Drive ack.

A stubbed export (``"status": "stubbed"``) is never a verified ack, even when
it records a sha256. A real export must carry ``"status": "exported"`` and a
sha256 that matches the local run-artifact's canonical digest.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from terminus_xi.canonical import read_json, sha256_canonical

from .export import DRIVE_EXPORT_NAME, STATUS_EXPORTED, STATUS_STUBBED

__all__ = ["PruneRefused", "prune_run_dir"]


class PruneRefused(ValueError):
    """Local scratch must be retained until Drive confirms a matching export."""


def prune_run_dir(run_dir: str | Path, *, expected_sha256: str | None = None) -> None:
    """Delete ``run_dir`` only when ``drive_export.json`` is a matching real ack."""
    directory = Path(run_dir)
    export_path = directory / DRIVE_EXPORT_NAME
    if not export_path.is_file():
        raise PruneRefused("drive_export.json is missing; prune refuses")

    export = read_json(export_path)
    if not isinstance(export, dict):
        raise PruneRefused("drive_export.json is not an object; prune refuses")

    status = export.get("status")
    if status == STATUS_STUBBED:
        raise PruneRefused("stubbed Drive export is not a verified ack; prune refuses")
    if status != STATUS_EXPORTED:
        raise PruneRefused(
            f"Drive export status {status!r} is not a verified ack; prune refuses"
        )

    if expected_sha256 is None:
        artifact_path = directory / "run-artifact.json"
        if not artifact_path.is_file():
            raise PruneRefused("run-artifact.json is missing; prune refuses")
        expected_sha256 = sha256_canonical(read_json(artifact_path))

    covered = export.get("sha256")
    if covered != expected_sha256:
        raise PruneRefused(
            "Drive export sha256 does not match the local run-artifact; prune refuses"
        )

    shutil.rmtree(directory)
