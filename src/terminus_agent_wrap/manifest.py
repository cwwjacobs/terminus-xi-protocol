"""Write ``MANIFEST.json`` for one agent-run wrap directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from terminus_xi.canonical import sha256_file, write_json

from . import WRAPPER_ID, WRAPPER_VERSION

__all__ = ["MANIFEST_NAME", "build_manifest", "write_manifest"]

MANIFEST_NAME = "MANIFEST.json"


def _file_entry(directory: Path, relative: str) -> dict[str, Any]:
    path = directory / relative
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def build_manifest(
    directory: Path,
    *,
    run_id: str,
    boundary_id: str,
    admission: str,
    events_sha256: str,
    artifact_sha256: str,
    receipt_sha256: str,
    files: Iterable[str],
) -> dict[str, Any]:
    return {
        "schema": "terminus-agent-wrap.manifest.v1",
        "wrapper": WRAPPER_ID,
        "wrapper_version": WRAPPER_VERSION,
        "run_id": run_id,
        "boundary_id": boundary_id,
        "admission": admission,
        "events_sha256": events_sha256,
        "artifact_sha256": artifact_sha256,
        "receipt_sha256": receipt_sha256,
        "files": [_file_entry(directory, name) for name in files],
    }


def write_manifest(directory: Path, document: Mapping[str, Any]) -> Path:
    path = Path(directory) / MANIFEST_NAME
    write_json(path, document)
    return path
