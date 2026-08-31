"""Boundary admission.

Admission is separate from check verdicts. A check says whether an invariant
held; admission says whether the artifact may cross a named boundary.

The rules are frozen and fail closed:

1. any ERROR result            -> ``ERROR``   (never admitted)
2. any FAIL result             -> ``REJECT``
3. any required check missing  -> ``REJECT`` (``REQUIRED_CHECK_MISSING``)
4. no results at all           -> ``REJECT`` (``EVIDENCE_MISSING``)
5. any WARN result             -> policy ``on_warn`` (``ADMIT``/``REVIEW``/``REJECT``)
6. otherwise                   -> ``ADMIT``

Only ``ADMIT`` is admitted. Downstream code must call :func:`is_admitted`
rather than comparing strings, so no promotion path can be widened by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import read_json, sha256_canonical
from .results import WatchdogResult
from .schemas import SchemaError, validate_against

__all__ = [
    "AdmissionDecision",
    "AdmissionPolicy",
    "DEFAULT_POLICY",
    "decide",
    "is_admitted",
    "load_policy",
]


class PolicyError(ValueError):
    """The admission policy is malformed."""


@dataclass(frozen=True)
class AdmissionPolicy:
    policy_id: str
    version: str
    on_warn: str = "REVIEW"
    required_checks: tuple[str, ...] = ()
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "terminus-xi.admission-policy.v1",
            "policy_id": self.policy_id,
            "version": self.version,
            "on_warn": self.on_warn,
        }
        if self.required_checks:
            payload["required_checks"] = list(self.required_checks)
        if self.description is not None:
            payload["description"] = self.description
        return payload

    def sha256(self) -> str:
        return sha256_canonical(self.to_dict())


DEFAULT_POLICY = AdmissionPolicy(
    policy_id="terminus-xi.default",
    version="1.0.0",
    on_warn="REVIEW",
    description="Default XI v1 boundary policy: WARN requires human review.",
)


def load_policy(document: Mapping[str, Any] | str | Path) -> AdmissionPolicy:
    if isinstance(document, (str, Path)):
        document = read_json(document)
    if not isinstance(document, Mapping):
        raise PolicyError("admission policy must be a JSON object")
    if document.get("schema") != "terminus-xi.admission-policy.v1":
        raise PolicyError(f"unsupported admission policy schema: {document.get('schema')!r}")
    try:
        validate_against(document, "terminus-xi.admission-policy.v1", label="admission policy")
    except SchemaError as exc:
        raise PolicyError(str(exc)) from exc
    return AdmissionPolicy(
        policy_id=document["policy_id"],
        version=document["version"],
        on_warn=document["on_warn"],
        required_checks=tuple(document.get("required_checks", ())),
        description=document.get("description"),
    )


@dataclass(frozen=True)
class AdmissionDecision:
    admission: str
    policy: AdmissionPolicy
    blocking_codes: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return self.admission == "ADMIT"

    def rationale(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy.policy_id,
            "policy_version": self.policy.version,
            "on_warn": self.policy.on_warn,
            "blocking_codes": list(self.blocking_codes),
            "reasons": list(self.reasons),
        }


def is_admitted(decision: AdmissionDecision | str) -> bool:
    """The one promotion predicate. ``ADMIT`` and nothing else."""
    if isinstance(decision, AdmissionDecision):
        return decision.admission == "ADMIT"
    return decision == "ADMIT"


def decide(
    results: Sequence[WatchdogResult],
    policy: AdmissionPolicy = DEFAULT_POLICY,
) -> AdmissionDecision:
    """Apply the frozen admission rules to a set of watchdog results."""
    reasons: list[str] = []
    blocking: list[str] = []

    seen = {result.check_id for result in results}
    missing_required = [c for c in policy.required_checks if c not in seen]

    errored = [r for r in results if r.verdict == "ERROR"]
    failed = [r for r in results if r.verdict == "FAIL"]
    warned = [r for r in results if r.verdict == "WARN"]

    for result in errored:
        blocking.extend(f.code for f in result.findings if f.severity == "ERROR")
        reasons.append(f"check {result.check_id} returned ERROR")
    for result in failed:
        blocking.extend(f.code for f in result.findings if f.severity == "FAIL")
        reasons.append(f"check {result.check_id} returned FAIL")
    for check_id in missing_required:
        blocking.append("REQUIRED_CHECK_MISSING")
        reasons.append(f"required check {check_id} produced no result")

    ordered_blocking = tuple(sorted(set(blocking)))

    if errored:
        return AdmissionDecision("ERROR", policy, ordered_blocking, tuple(reasons))
    if failed or missing_required:
        return AdmissionDecision("REJECT", policy, ordered_blocking, tuple(reasons))
    if not results:
        return AdmissionDecision(
            "REJECT",
            policy,
            ("EVIDENCE_MISSING",),
            ("no check results were submitted to the boundary",),
        )
    if warned:
        for result in warned:
            reasons.append(f"check {result.check_id} returned WARN")
        warn_codes = tuple(
            sorted({f.code for r in warned for f in r.findings if f.severity == "WARN"})
        )
        admission = policy.on_warn
        codes = warn_codes if admission != "ADMIT" else ()
        reasons.append(f"policy {policy.policy_id} maps WARN to {admission}")
        return AdmissionDecision(admission, policy, codes, tuple(reasons))

    reasons.append(f"all {len(results)} checks passed")
    return AdmissionDecision("ADMIT", policy, (), tuple(reasons))
