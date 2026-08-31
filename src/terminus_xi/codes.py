"""Frozen Terminus XI v1 issue-code vocabulary.

One vocabulary, one severity class per code. Promotion-blocking conditions are
typed codes, never free-text matching (CHARTER.md, "Contradiction rule").

Severity classes
----------------
``INFO``   observation only; never blocks.
``WARN``   surfaced deviation; boundary policy decides (never silently PASS).
``FAIL``   invariant violated; the artifact cannot be admitted.
``ERROR``  the check itself could not establish anything; fail closed.

A check contract may *escalate* a WARN code to FAIL. It may never de-escalate a
FAIL or ERROR code. See ``docs/AUDIT_SEMANTICS_DECISION.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

__all__ = [
    "ISSUE_CODES",
    "IssueCode",
    "SEVERITIES",
    "SEVERITY_RANK",
    "VERDICTS",
    "escalate",
    "is_known_code",
    "severity_of",
    "verdict_from_severities",
    "worst_severity",
]

SEVERITIES = ("INFO", "WARN", "FAIL", "ERROR")
VERDICTS = ("PASS", "WARN", "FAIL", "ERROR")
SEVERITY_RANK: Mapping[str, int] = {"INFO": 0, "WARN": 1, "FAIL": 2, "ERROR": 3}
VERDICT_RANK: Mapping[str, int] = {"PASS": 0, "WARN": 1, "FAIL": 2, "ERROR": 3}


@dataclass(frozen=True)
class IssueCode:
    code: str
    severity: str
    category: str
    description: str


def _c(code: str, severity: str, category: str, description: str) -> tuple[str, IssueCode]:
    assert severity in SEVERITIES, severity
    return code, IssueCode(code, severity, category, description)


ISSUE_CODES: Mapping[str, IssueCode] = dict(
    [
        # --- observation -------------------------------------------------
        _c("MEASUREMENT", "INFO", "observation",
           "A deterministic measurement recorded for the record; not a defect."),
        # --- evidence ----------------------------------------------------
        _c("EVIDENCE_MISSING", "FAIL", "evidence",
           "Required evidence was not supplied at the boundary."),
        _c("EVIDENCE_INCOMPLETE", "FAIL", "evidence",
           "Supplied evidence exists but does not cover what the contract requires."),
        _c("EVIDENCE_CITATION_MISSING", "FAIL", "evidence",
           "A material claim cites no supporting evidence item."),
        _c("EVIDENCE_REF_UNRESOLVED", "FAIL", "evidence",
           "A claim cites an evidence identifier that is not present in the evidence set."),
        _c("EVIDENCE_GAP_UNDECLARED", "FAIL", "evidence",
           "A known evidence gap is not declared in the artifact's limitations."),
        # --- input handling ----------------------------------------------
        _c("INPUT_POINTER_MISSING", "ERROR", "input",
           "A contract input pointer did not resolve in the submitted artifact."),
        _c("INPUT_SHAPE_INVALID", "FAIL", "input",
           "A resolved input did not match the shape the contract declares."),
        _c("SCHEMA_VIOLATION", "FAIL", "input",
           "A document failed validation against its declared schema."),
        # --- parity / drift ----------------------------------------------
        _c("MODEL_IDENTITY_MISMATCH", "FAIL", "parity",
           "Compared arms did not use the same model identity."),
        _c("FIXTURE_IDENTITY_MISMATCH", "FAIL", "parity",
           "Compared arms did not use the same fixture identity."),
        _c("TOOL_SURFACE_MISMATCH", "FAIL", "parity",
           "Compared arms did not expose the same tool surface."),
        _c("CONFIG_DRIFT_UNDECLARED", "FAIL", "parity",
           "Configuration differs outside the declared changed variable."),
        _c("CHANGED_VARIABLE_ABSENT", "FAIL", "parity",
           "The declared changed variable does not actually differ between arms."),
        _c("DRIFT_DETECTED", "WARN", "parity",
           "A non-blocking evidence-surface change was observed and surfaced."),
        # --- claim boundary ----------------------------------------------
        _c("CLAIM_OVERBROAD", "FAIL", "claim",
           "A claim uses unbounded certification language outside the evidence scope."),
        _c("CLAIM_SCOPE_MISSING", "FAIL", "claim",
           "A claim set declares no asset scope, time window, or surface bound."),
        _c("CLAIM_UNSUPPORTED", "FAIL", "claim",
           "The asserted claim is not established by the submitted evidence."),
        _c("LIMITATIONS_ABSENT", "FAIL", "claim",
           "A claim set states no limitations."),
        # --- integrity ---------------------------------------------------
        _c("CONTRADICTION_DETECTED", "FAIL", "integrity",
           "Required evidence contradicts itself or a recomputation."),
        _c("HASH_MISMATCH", "FAIL", "integrity",
           "A recorded digest does not match the bytes it claims to identify."),
        # --- redaction ---------------------------------------------------
        _c("SENSITIVE_VALUE_PRESENT", "FAIL", "redaction",
           "A public-safe projection still contains a value the policy denies."),
        _c("REDACTION_POLICY_VIOLATION", "FAIL", "redaction",
           "A declared redaction rule was not applied to the projection."),
        # --- runtime -----------------------------------------------------
        _c("CHECK_ERROR", "ERROR", "runtime",
           "The check implementation raised while evaluating the artifact."),
        _c("CHECK_NOT_FOUND", "ERROR", "runtime",
           "No registered implementation exists for the contract."),
        _c("CONTRACT_INVALID", "ERROR", "runtime",
           "The check contract itself is malformed or not deterministic."),
        _c("REQUIRED_CHECK_MISSING", "FAIL", "runtime",
           "A check required by the admission policy produced no result."),
        _c("PAYLOAD_SIZE_UNKNOWN", "ERROR", "runtime",
           "Payload size could not be measured, so size invariants are unestablished."),
        _c("PAYLOAD_LARGE", "WARN", "runtime",
           "Payload exceeds the size the contract considers routine."),
        # --- recovery ----------------------------------------------------
        _c("RECOVERY_BUDGET_EXHAUSTED", "FAIL", "recovery",
           "The bounded recovery budget was spent without earning admission."),
        _c("RECOVERY_NOT_REVALIDATED", "FAIL", "recovery",
           "A recovered artifact did not re-enter validation before admission."),
    ]
)


def is_known_code(code: str) -> bool:
    return code in ISSUE_CODES


def severity_of(code: str) -> str:
    try:
        return ISSUE_CODES[code].severity
    except KeyError:
        raise KeyError(f"unknown XI issue code: {code!r}") from None


def escalate(code: str, escalated: Iterable[str]) -> str:
    """Contract-declared escalation. WARN may become FAIL; nothing de-escalates."""
    base = severity_of(code)
    if base == "WARN" and code in set(escalated):
        return "FAIL"
    return base


def worst_severity(severities: Iterable[str]) -> str:
    worst = "INFO"
    for severity in severities:
        if severity not in SEVERITY_RANK:
            raise ValueError(f"unknown severity: {severity!r}")
        if SEVERITY_RANK[severity] > SEVERITY_RANK[worst]:
            worst = severity
    return worst


def verdict_from_severities(severities: Iterable[str]) -> str:
    """Deterministic PASS/WARN/FAIL/ERROR from finding severities."""
    worst = worst_severity(severities)
    return {"INFO": "PASS", "WARN": "WARN", "FAIL": "FAIL", "ERROR": "ERROR"}[worst]
