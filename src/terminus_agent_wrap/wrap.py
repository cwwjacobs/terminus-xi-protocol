"""Thin wrap: observe → package → admit via XI → archive stub.

The only admit path is ``terminus_xi.engine.verify_artifact``. This module
does not call ``build_receipt`` or ``decide``. Pre-tool HALT is
``evaluate_tool_proposal`` in ``gate.py``; it is not a second admission engine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from terminus_xi.admission import AdmissionPolicy, is_admitted, load_policy
from terminus_xi.canonical import sha256_canonical, write_json
from terminus_xi.contracts import ContractSet, load_contract_set
from terminus_xi.engine import VerificationOutcome, verify_artifact

from . import BOUNDARY_ID, WRAPPER_ID, WRAPPER_VERSION
from . import checks as _checks  # noqa: F401
from .artifact import build_run_artifact
from .events import events_sha256, write_events_jsonl
from .export import DriveExporter, LocalOnlyExporter
from .manifest import MANIFEST_NAME, build_manifest, write_manifest
from .plan import PlanExecution, execute_plan

__all__ = [
    "PACKAGE_FILES",
    "WrappedRun",
    "admit_run_artifact",
    "default_contract_set",
    "default_policy",
    "default_scratch_root",
    "package_dir",
    "wrap_plan",
    "wrap_run",
]

PACKAGE_FILES = (
    "events.jsonl",
    "run-artifact.json",
    "receipt.json",
    "drive_export.json",
    MANIFEST_NAME,
)

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parents[1]


def package_dir() -> Path:
    return _PACKAGE_DIR


def default_scratch_root() -> Path:
    """Repo-local scratch that works in CI. Drive is the durable archive.

    Override with ``TERMINUS_AGENT_WRAP_SCRATCH``. ``/workspace/xi-traces`` is
    an equivalent local path on the cloud-agent VM; both are scratch, not archive.
    """
    override = os.environ.get("TERMINUS_AGENT_WRAP_SCRATCH")
    if override:
        return Path(override)
    return _REPO_ROOT / "runs" / "agent-wrap"


def default_contract_set() -> ContractSet:
    return load_contract_set(_PACKAGE_DIR / "contracts" / "agent-run.contracts.json")


def default_policy() -> AdmissionPolicy:
    return load_policy(_PACKAGE_DIR / "policies" / "agent-run.policy.json")


def admit_run_artifact(
    artifact: Mapping[str, Any],
    *,
    contract_set: ContractSet | None = None,
    policy: AdmissionPolicy | None = None,
    boundary_id: str | None = None,
) -> VerificationOutcome:
    """Submit one run-artifact to XI. This is the only supported admit path."""
    resolved_boundary = boundary_id or str(artifact.get("boundary_id") or BOUNDARY_ID)
    resolved_contracts = contract_set or default_contract_set()
    resolved_policy = policy or default_policy()
    tool_surface = artifact.get("tool_surface")
    provenance_surface = None
    if isinstance(tool_surface, Mapping) and "tools" in tool_surface:
        provenance_surface = {
            "tools": list(tool_surface["tools"]),
            "sha256": sha256_canonical(tool_surface),
        }
    config = artifact.get("config") if isinstance(artifact.get("config"), Mapping) else {}
    fixture_id = config.get("fixture_id") if isinstance(config, Mapping) else None
    provenance_fixture = None
    if isinstance(fixture_id, str) and fixture_id:
        provenance_fixture = {
            "fixture_id": fixture_id,
            "sha256": sha256_canonical(config),
        }
    return verify_artifact(
        artifact,
        boundary_id=resolved_boundary,
        contract_set=resolved_contracts,
        policy=resolved_policy,
        artifact_id=str(artifact.get("run_id") or "run-artifact"),
        run_id=str(artifact["run_id"]) if artifact.get("run_id") else None,
        fixture=provenance_fixture,
        tool_surface=provenance_surface,
        capability={
            "capability_id": WRAPPER_ID,
            "version": WRAPPER_VERSION,
            "source": "src/terminus_agent_wrap",
        },
        notes=(
            "agent-run wrap spike: observe, package, admit, archive; not a persona agent",
        ),
    )


@dataclass(frozen=True)
class WrappedRun:
    run_id: str
    directory: Path
    events: tuple[Mapping[str, Any], ...]
    events_sha256: str
    artifact: Mapping[str, Any]
    artifact_sha256: str
    outcome: VerificationOutcome
    manifest: Mapping[str, Any]
    drive_export: Mapping[str, Any]
    halted: bool = False
    side_effects: tuple[Mapping[str, Any], ...] = ()

    @property
    def admission(self) -> str:
        return self.outcome.admission

    @property
    def admitted(self) -> bool:
        return is_admitted(self.outcome.decision)

    @property
    def receipt(self) -> Mapping[str, Any]:
        return self.outcome.receipt


def wrap_plan(
    proposals: Sequence[Any],
    *,
    gate_disabled: bool = False,
    **kwargs: Any,
) -> WrappedRun:
    """Execute a fixture plan through the pre-tool gate, then ``wrap_run``.

    ``gate_disabled`` defaults to False. Passing True is test-only.
    """
    return wrap_run(plan=proposals, gate_disabled=gate_disabled, **kwargs)


def wrap_run(
    events: Sequence[Mapping[str, Any]] | None = None,
    *,
    plan: Sequence[Any] | None = None,
    gate_disabled: bool = False,
    scratch_root: str | Path | None = None,
    agent: Mapping[str, Any] | None = None,
    tool_surface: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
    outcome: Mapping[str, Any] | None = None,
    claim: Mapping[str, Any] | None = None,
    exporter: DriveExporter | None = None,
    contract_set: ContractSet | None = None,
    policy: AdmissionPolicy | None = None,
    boundary_id: str = BOUNDARY_ID,
) -> WrappedRun:
    """Package one tool trace, admit it through XI, and write the run directory.

    Pass ``events`` to package an already-observed trace (no tool execution).
    Pass ``plan`` to execute fixture proposals through ``evaluate_tool_proposal``
    first. ``gate_disabled`` applies only to ``plan`` and defaults to False.
    """
    execution: PlanExecution | None = None
    if plan is not None:
        if events is not None:
            raise ValueError("pass events or plan, not both")
        execution = execute_plan(plan, gate_disabled=gate_disabled)
        observed: Sequence[Mapping[str, Any]] = execution.events
    elif events is None:
        raise TypeError("wrap_run requires events or plan")
    else:
        observed = events
    if gate_disabled and plan is None:
        raise ValueError("gate_disabled is test-only and only valid with plan=")

    artifact = build_run_artifact(
        observed,
        boundary_id=boundary_id,
        agent=agent,
        tool_surface=tool_surface,
        config=config,
        outcome=outcome,
        claim=claim,
    )
    run_id = str(artifact["run_id"])
    root = Path(scratch_root) if scratch_root is not None else default_scratch_root()
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=True)

    recorded_events = tuple(artifact["events"])
    write_events_jsonl(directory / "events.jsonl", recorded_events)
    write_json(directory / "run-artifact.json", artifact)

    verification = admit_run_artifact(
        artifact,
        contract_set=contract_set,
        policy=policy,
        boundary_id=boundary_id,
    )
    write_json(directory / "receipt.json", verification.receipt)

    artifact_digest = sha256_canonical(artifact)
    drive_export = (exporter or LocalOnlyExporter()).export(
        directory, sha256=artifact_digest, run_id=run_id
    )

    manifest = build_manifest(
        directory,
        run_id=run_id,
        boundary_id=boundary_id,
        admission=verification.admission,
        events_sha256=events_sha256(recorded_events),
        artifact_sha256=artifact_digest,
        receipt_sha256=str(verification.receipt["receipt_sha256"]),
        files=("events.jsonl", "run-artifact.json", "receipt.json", "drive_export.json"),
    )
    write_manifest(directory, manifest)

    return WrappedRun(
        run_id=run_id,
        directory=directory,
        events=recorded_events,
        events_sha256=str(artifact["events_sha256"]),
        artifact=artifact,
        artifact_sha256=artifact_digest,
        outcome=verification,
        manifest=manifest,
        drive_export=dict(drive_export),
        halted=False if execution is None else execution.halted,
        side_effects=() if execution is None else execution.side_effects,
    )
