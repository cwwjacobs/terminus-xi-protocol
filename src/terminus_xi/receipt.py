"""Canonical XI receipts: build, serialize, and independently verify.

Two digests are carried, and they answer different questions:

``stable_core_sha256``
    Digest over the receipt with ``created_at_utc``, ``stable_core_sha256`` and
    ``receipt_sha256`` removed. Identical canonical input plus identical
    contracts and policy must reproduce this value exactly. This is the
    machine-checkable form of the determinism rule.

``receipt_sha256``
    Digest over the whole receipt except that field. Any edit to any other
    field is detectable.

Neither digest is a signature. A receipt proves internal consistency and binds
identity; it does not authenticate the party that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import PROTOCOL_VERSION, RUNTIME_VERSION
from .admission import AdmissionDecision, AdmissionPolicy, decide
from .canonical import read_json, sha256_canonical, utc_now
from .codes import verdict_from_severities
from .contracts import ContractSet
from .provenance import Provenance
from .results import WatchdogResult
from .schemas import SchemaError, validate_against

__all__ = [
    "VOLATILE_FIELDS",
    "ReceiptVerification",
    "build_receipt",
    "stable_core",
    "stable_core_sha256",
    "verify_receipt",
    "verify_receipt_file",
]

VOLATILE_FIELDS = ("created_at_utc", "stable_core_sha256", "receipt_sha256")


def stable_core(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in receipt.items() if key not in VOLATILE_FIELDS}


def stable_core_sha256(receipt: Mapping[str, Any]) -> str:
    return sha256_canonical(stable_core(receipt))


def _receipt_sha256(receipt: Mapping[str, Any]) -> str:
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return sha256_canonical(body)


def build_receipt(
    *,
    boundary_id: str,
    artifact_sha256: str,
    contract_set: ContractSet,
    results: Sequence[WatchdogResult],
    provenance: Provenance,
    policy: AdmissionPolicy,
    decision: AdmissionDecision | None = None,
    recovery_ref: str | None = None,
    parent_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    """Assemble, hash, and validate a ``terminus-xi.receipt.v2`` document."""
    resolved = decision if decision is not None else decide(results, policy)

    receipt: dict[str, Any] = {
        "schema": "terminus-xi.receipt.v2",
        "boundary_id": boundary_id,
        "protocol_version": PROTOCOL_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "created_at_utc": utc_now(),
        "artifact_sha256": artifact_sha256,
        "policy_sha256": policy.sha256(),
        "contract_set_sha256": contract_set.sha256(),
        "provenance": provenance.to_dict(),
        "check_results": [result.to_dict() for result in results],
        "admission": resolved.admission,
        "admission_rationale": resolved.rationale(),
        "recovery_ref": recovery_ref,
        "parent_receipt_sha256": parent_receipt_sha256,
    }
    receipt["stable_core_sha256"] = stable_core_sha256(receipt)
    receipt["receipt_sha256"] = _receipt_sha256(receipt)

    try:
        validate_against(receipt, "terminus-xi.receipt.v2", label="receipt")
    except SchemaError as exc:
        raise ValueError(str(exc)) from exc
    return receipt


@dataclass(frozen=True)
class ReceiptVerification:
    ok: bool
    errors: tuple[str, ...]
    admission: str | None = None

    def raise_for_status(self) -> None:
        if not self.ok:
            raise ValueError("receipt verification failed:\n  - " + "\n  - ".join(self.errors))


def verify_receipt(
    receipt: Mapping[str, Any],
    *,
    artifact_sha256: str | None = None,
) -> ReceiptVerification:
    """Independently re-derive every internal claim the receipt makes.

    This does not re-run the checks; it establishes that the receipt document
    is well formed, internally consistent, self-consistent with its digests,
    and that its admission decision follows from its own recorded results.
    """
    errors: list[str] = []

    if not isinstance(receipt, Mapping):
        return ReceiptVerification(False, ("receipt is not a JSON object",))

    try:
        validate_against(receipt, "terminus-xi.receipt.v2", label="receipt")
    except SchemaError as exc:
        return ReceiptVerification(False, (str(exc),))
    except KeyError as exc:
        return ReceiptVerification(False, (f"schema unavailable: {exc}",))

    if receipt["stable_core_sha256"] != stable_core_sha256(receipt):
        errors.append("stable_core_sha256 does not match the receipt body")
    if receipt["receipt_sha256"] != _receipt_sha256(receipt):
        errors.append("receipt_sha256 does not match the receipt body")

    provenance_artifact = receipt["provenance"]["artifact"]["sha256"]
    if provenance_artifact != receipt["artifact_sha256"]:
        errors.append(
            "provenance artifact digest does not match the receipt artifact digest"
        )
    if receipt["provenance"]["boundary_id"] != receipt["boundary_id"]:
        errors.append("provenance boundary_id does not match the receipt boundary_id")
    if artifact_sha256 is not None and artifact_sha256 != receipt["artifact_sha256"]:
        errors.append(
            f"receipt covers artifact {receipt['artifact_sha256']} but the supplied "
            f"artifact hashes to {artifact_sha256}"
        )

    # Every recorded verdict must follow from its own recorded findings.
    for result in receipt["check_results"]:
        severities = [f["severity"] for f in result["findings"]]
        expected = verdict_from_severities(severities) if severities else "PASS"
        if result["verdict"] != expected:
            errors.append(
                f"check {result['check_id']} records verdict {result['verdict']} but its "
                f"findings imply {expected}"
            )

    # The admission decision must follow from the recorded verdicts.
    verdicts = {result["verdict"] for result in receipt["check_results"]}
    admission = receipt["admission"]
    on_warn = receipt["admission_rationale"]["on_warn"]
    if "ERROR" in verdicts:
        expected_admission = "ERROR"
    elif "FAIL" in verdicts:
        expected_admission = "REJECT"
    elif "WARN" in verdicts:
        expected_admission = on_warn
    else:
        expected_admission = "ADMIT"
    # A receipt may be stricter than its verdicts require (for example a
    # required check produced no result at all), but it may never be more
    # permissive than they allow.
    strictness = {"ADMIT": 0, "REVIEW": 1, "REJECT": 2, "ERROR": 3}
    if strictness[admission] < strictness[expected_admission]:
        errors.append(
            f"admission {admission!r} is more permissive than the recorded verdicts "
            f"allow (expected at least {expected_admission!r})"
        )

    return ReceiptVerification(not errors, tuple(errors), admission=receipt.get("admission"))


def verify_receipt_file(path: str | Path, **kwargs: Any) -> ReceiptVerification:
    return verify_receipt(read_json(path), **kwargs)
