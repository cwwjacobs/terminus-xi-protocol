"""The execution adapter boundary.

An adapter answers one question: *what did this arm actually do?* It returns a
:class:`RawExecution` describing the model identity, tool surface, effective
configuration, claim report, and transcript that the run actually used. Those
values are then compared across arms by XI, which is why they come from the
execution rather than from the specification.

Two adapter kinds are meaningful:

``fixture-recording``
    Implemented here. Replays a recorded execution from disk. Deterministic,
    offline, and the only kind the tests need.

``gtd-run`` (not implemented)
    The seam for real GTD/Labyrinth execution evidence. A GTD run directory
    already carries the same shape under different names: ``run.json`` holds
    the model and configuration surface, ``manifest.json`` and
    ``evidence/*.json`` hold the evidence set, ``records.jsonl`` holds the
    per-step trace, and ``receipt.json`` holds the run's own checkpoints. An
    adapter for it implements :class:`ExecutionAdapter` and maps those files
    onto ``RawExecution``; nothing else in the engine changes, and no XI
    semantics move. That repository is read-only reference for this UKSL and is
    deliberately not imported here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from terminus_xi.canonical import read_json, sha256_canonical

__all__ = [
    "AdapterError",
    "ExecutionAdapter",
    "FixtureRecordingAdapter",
    "RawExecution",
    "get_adapter",
    "register_adapter",
    "registered_kinds",
]


class AdapterError(ValueError):
    """The adapter could not produce a complete execution record."""


@dataclass(frozen=True)
class RawExecution:
    """Exactly what one arm recorded about itself, before redaction."""

    arm_id: str
    capability_enabled: bool
    model: Mapping[str, Any]
    tool_surface: Mapping[str, Any]
    config: Mapping[str, Any]
    output: Mapping[str, Any]
    transcript: Sequence[Mapping[str, Any]]
    source: str

    def raw_sha256(self) -> str:
        """Digest of the unredacted execution record."""
        return sha256_canonical(
            {
                "arm_id": self.arm_id,
                "capability_enabled": self.capability_enabled,
                "model": dict(self.model),
                "tool_surface": dict(self.tool_surface),
                "config": dict(self.config),
                "output": dict(self.output),
                "transcript": [dict(step) for step in self.transcript],
            }
        )


class ExecutionAdapter(Protocol):
    """Produces one arm's execution record."""

    kind: str

    def execute(
        self,
        *,
        arm_spec: Mapping[str, Any],
        fixture: Mapping[str, Any],
        root: Path,
    ) -> RawExecution:  # pragma: no cover - protocol
        ...


_REQUIRED_RECORDING_KEYS = (
    "arm_id",
    "capability_enabled",
    "model",
    "tool_surface",
    "config",
    "output",
    "transcript",
)


class FixtureRecordingAdapter:
    """Replay a recorded execution held on disk.

    The recording is authoritative for what the arm used. The engine records
    the spec's declared surface separately so that a check, not the engine, can
    establish that the two agree.
    """

    kind = "fixture-recording"

    def execute(
        self,
        *,
        arm_spec: Mapping[str, Any],
        fixture: Mapping[str, Any],
        root: Path,
    ) -> RawExecution:
        relative = arm_spec["adapter"]["path"]
        path = Path(relative)
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            raise AdapterError(f"recording not found: {relative}")

        document = read_json(path)
        if not isinstance(document, Mapping):
            raise AdapterError(f"recording {relative} is not a JSON object")
        if document.get("schema") != "terminus-proof.recording.v1":
            raise AdapterError(
                f"recording {relative} declares schema {document.get('schema')!r}; "
                "expected 'terminus-proof.recording.v1'"
            )
        missing = [key for key in _REQUIRED_RECORDING_KEYS if key not in document]
        if missing:
            raise AdapterError(f"recording {relative} is missing {missing}")
        if document["arm_id"] != arm_spec["arm_id"]:
            raise AdapterError(
                f"recording {relative} is arm {document['arm_id']!r} but the spec "
                f"binds it to arm {arm_spec['arm_id']!r}"
            )
        if not document["transcript"]:
            raise AdapterError(f"recording {relative} has an empty transcript")

        return RawExecution(
            arm_id=str(document["arm_id"]),
            capability_enabled=bool(document["capability_enabled"]),
            model=dict(document["model"]),
            tool_surface=dict(document["tool_surface"]),
            config=dict(document["config"]),
            output=dict(document["output"]),
            transcript=[dict(step) for step in document["transcript"]],
            source=str(relative),
        )


_ADAPTERS: dict[str, Callable[[], ExecutionAdapter]] = {
    FixtureRecordingAdapter.kind: FixtureRecordingAdapter,
}


def register_adapter(kind: str, factory: Callable[[], ExecutionAdapter]) -> None:
    _ADAPTERS[kind] = factory


def registered_kinds() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(kind: str) -> ExecutionAdapter:
    try:
        factory = _ADAPTERS[kind]
    except KeyError:
        raise AdapterError(
            f"no execution adapter registered for kind {kind!r}; "
            f"registered kinds are {registered_kinds()}"
        ) from None
    return factory()
