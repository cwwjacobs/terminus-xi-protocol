"""Deterministic provenance binding.

The provenance envelope carries no clock reading and no random identifier. When
the caller does not supply a ``run_id`` it is derived from the covered
identities, so the same inputs always produce the same run identity.

Historical XI provenance agents used ``uuid4`` event ids and ``utcnow()``
timestamps inside the provenance record itself, which made two identical runs
non-comparable. XI v1 moves the single timestamp to the receipt envelope and
excludes it from the stable core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import PROTOCOL_VERSION, RUNTIME_VERSION
from .canonical import canonical_bytes, sha256_canonical
from .schemas import SchemaError, validate_against

__all__ = ["Provenance", "build_provenance"]


@dataclass(frozen=True)
class Provenance:
    document: Mapping[str, Any]

    @property
    def run_id(self) -> str:
        return str(self.document["run_id"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self.document)

    def sha256(self) -> str:
        return sha256_canonical(self.document)


def _optional(value: Any) -> Any:
    return value if value is not None else None


def build_provenance(
    *,
    boundary_id: str,
    artifact: Any,
    artifact_id: str = "artifact",
    artifact_kind: str = "json",
    artifact_sha256: str | None = None,
    artifact_bytes: int | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    inputs: Sequence[Mapping[str, Any]] = (),
    model: Mapping[str, Any] | None = None,
    fixture: Mapping[str, Any] | None = None,
    tool_surface: Mapping[str, Any] | None = None,
    capability: Mapping[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> Provenance:
    """Build and validate a ``terminus-xi.provenance.v1`` envelope."""
    if artifact_kind == "json":
        digest = artifact_sha256 or sha256_canonical(artifact)
        size = artifact_bytes if artifact_bytes is not None else len(canonical_bytes(artifact))
    else:
        if artifact_sha256 is None:
            raise ValueError("artifact_sha256 is required for non-JSON artifacts")
        digest = artifact_sha256
        size = artifact_bytes

    document: dict[str, Any] = {
        "schema": "terminus-xi.provenance.v1",
        "run_id": run_id or "",
        "boundary_id": boundary_id,
        "protocol_version": PROTOCOL_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "artifact": {
            "artifact_id": artifact_id,
            "kind": artifact_kind,
            "sha256": digest,
            "bytes": size,
        },
        "inputs": [dict(item) for item in inputs],
        "model": _optional(dict(model) if model else None),
        "fixture": _optional(dict(fixture) if fixture else None),
        "tool_surface": _optional(dict(tool_surface) if tool_surface else None),
        "capability": _optional(dict(capability) if capability else None),
        "notes": list(notes),
    }

    if not run_id:
        seed = {key: value for key, value in document.items() if key != "run_id"}
        document["run_id"] = "run_" + sha256_canonical(seed)[:24]
    if job_id is not None:
        document["job_id"] = job_id

    try:
        validate_against(document, "terminus-xi.provenance.v1", label="provenance")
    except SchemaError as exc:
        raise ValueError(str(exc)) from exc
    return Provenance(document)
