"""The single deterministic XI verification entry point.

``verify_artifact`` is the only supported way to take an artifact across a
boundary: identify it, evaluate the frozen contract set, apply the admission
policy, and emit a canonical receipt. There is no second path and no way to
promote a FAIL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .admission import AdmissionDecision, AdmissionPolicy, DEFAULT_POLICY, decide, is_admitted
from .audit import run_contract_set
from .canonical import sha256_canonical
from .contracts import ContractSet
from .provenance import Provenance, build_provenance
from .receipt import build_receipt
from .results import WatchdogResult

__all__ = ["VerificationOutcome", "verify_artifact"]


@dataclass(frozen=True)
class VerificationOutcome:
    receipt: Mapping[str, Any]
    results: Sequence[WatchdogResult]
    decision: AdmissionDecision

    @property
    def admitted(self) -> bool:
        return is_admitted(self.decision)

    @property
    def admission(self) -> str:
        return self.decision.admission


def verify_artifact(
    artifact: Any,
    *,
    boundary_id: str,
    contract_set: ContractSet,
    policy: AdmissionPolicy = DEFAULT_POLICY,
    provenance: Provenance | None = None,
    artifact_id: str = "artifact",
    recovery_ref: str | None = None,
    parent_receipt_sha256: str | None = None,
    **provenance_fields: Any,
) -> VerificationOutcome:
    artifact_sha256 = sha256_canonical(artifact)
    results = run_contract_set(contract_set, artifact)
    decision = decide(results, policy)
    resolved_provenance = provenance or build_provenance(
        boundary_id=boundary_id,
        artifact=artifact,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha256,
        **provenance_fields,
    )
    receipt = build_receipt(
        boundary_id=boundary_id,
        artifact_sha256=artifact_sha256,
        contract_set=contract_set,
        results=results,
        provenance=resolved_provenance,
        policy=policy,
        decision=decision,
        recovery_ref=recovery_ref,
        parent_receipt_sha256=parent_receipt_sha256,
    )
    return VerificationOutcome(receipt=receipt, results=results, decision=decision)
