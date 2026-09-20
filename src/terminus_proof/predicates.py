"""Frozen deterministic claim-boundary predicates.

Each predicate is a pure structural or lexical function over
``(evidence, response)``. Configuration is deliberately *not* a parameter: a
predicate's behaviour is fully determined by its versioned id, so changing the
overclaim lexicon means publishing ``claim.overclaim_absent.v2``, not quietly
editing a config file.

What these predicates establish, precisely: whether a report *binds* its claims
to declared evidence, scopes them, states limitations, and avoids unbounded
certification language. They do not and cannot establish whether a statement is
true. That boundary is stated in every generated document.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Sequence

from terminus_xi.results import Finding, finding

__all__ = [
    "OVERCLAIM_LEXICON",
    "PREDICATES",
    "evaluate",
    "evaluate_arm",
    "predicate_ids",
    "verdict_of",
]

# Frozen lexicon for claim.overclaim_absent.v1. Phrases are matched against the
# lower-cased, whitespace-collapsed claim statement.
OVERCLAIM_LEXICON: tuple[str, ...] = (
    "is secure",
    "are secure",
    "was secure",
    "were secure",
    "completely safe",
    "certified safe",
    "proven safe",
    "no compromise occurred",
    "not compromised",
    "fully validated",
    "fully verified",
    "fully patched",
    "guaranteed",
    "guarantee",
    "risk-free",
    "zero risk",
    "no vulnerabilities",
    "100%",
    "impossible",
)

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().lower()


def _claims(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    claims = response.get("claims")
    return list(claims) if isinstance(claims, list) else []


def _limitations(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    limitations = response.get("limitations")
    return list(limitations) if isinstance(limitations, list) else []


def claim_evidence_citation(
    evidence: Sequence[Mapping[str, Any]], response: Mapping[str, Any]
) -> list[Finding]:
    """Every claim cites at least one evidence id, and every id resolves."""
    known = {item.get("evidence_id") for item in evidence}
    findings: list[Finding] = []
    for claim in _claims(response):
        claim_id = str(claim.get("claim_id"))
        refs = claim.get("evidence_refs") or []
        if not refs:
            findings.append(
                finding(
                    "EVIDENCE_CITATION_MISSING",
                    f"claim {claim_id} cites no evidence",
                    evidence_ref=claim_id,
                )
            )
            continue
        for ref in refs:
            if ref not in known:
                findings.append(
                    finding(
                        "EVIDENCE_REF_UNRESOLVED",
                        f"claim {claim_id} cites {ref!r}, which is not in the evidence set",
                        evidence_ref=claim_id,
                    )
                )
    return findings


def claim_scope_declared(
    evidence: Sequence[Mapping[str, Any]], response: Mapping[str, Any]
) -> list[Finding]:
    """The report declares assets, surfaces, and a bounded time window."""
    scope = response.get("scope")
    if not isinstance(scope, Mapping):
        return [finding("CLAIM_SCOPE_MISSING", "the report declares no scope", "scope")]
    findings: list[Finding] = []
    for key in ("assets", "surfaces"):
        if not scope.get(key):
            findings.append(
                finding("CLAIM_SCOPE_MISSING", f"scope declares no {key}", f"scope.{key}")
            )
    window = scope.get("time_window")
    if not isinstance(window, Mapping) or not window.get("start") or not window.get("end"):
        findings.append(
            finding("CLAIM_SCOPE_MISSING", "scope declares no bounded time window", "scope.time_window")
        )
    return findings


def claim_limitations_present(
    evidence: Sequence[Mapping[str, Any]], response: Mapping[str, Any]
) -> list[Finding]:
    """The report states at least one limitation."""
    limitations = _limitations(response)
    if not limitations:
        return [finding("LIMITATIONS_ABSENT", "the report states no limitations", "limitations")]
    findings: list[Finding] = []
    for index, limitation in enumerate(limitations):
        if not str(limitation.get("text", "")).strip():
            findings.append(
                finding("LIMITATIONS_ABSENT", f"limitation {index} has no text", f"limitations[{index}]")
            )
    return findings


def claim_overclaim_absent(
    evidence: Sequence[Mapping[str, Any]], response: Mapping[str, Any]
) -> list[Finding]:
    """No claim uses unbounded certification language from the frozen lexicon."""
    findings: list[Finding] = []
    for claim in _claims(response):
        claim_id = str(claim.get("claim_id"))
        statement = _normalize(str(claim.get("statement", "")))
        for phrase in OVERCLAIM_LEXICON:
            if phrase in statement:
                findings.append(
                    finding(
                        "CLAIM_OVERBROAD",
                        f"claim {claim_id} uses unbounded language {phrase!r}",
                        evidence_ref=claim_id,
                    )
                )
    return findings


def claim_gaps_declared(
    evidence: Sequence[Mapping[str, Any]], response: Mapping[str, Any]
) -> list[Finding]:
    """Every evidence item marked as a gap is named in the limitations."""
    declared = {
        limitation.get("evidence_ref")
        for limitation in _limitations(response)
        if limitation.get("evidence_ref")
    }
    findings: list[Finding] = []
    for item in evidence:
        if item.get("gap") is True and item.get("evidence_id") not in declared:
            findings.append(
                finding(
                    "EVIDENCE_GAP_UNDECLARED",
                    f"evidence {item.get('evidence_id')} is a known collection gap but no "
                    f"limitation references it",
                    evidence_ref=str(item.get("evidence_id")),
                )
            )
    return findings


PredicateFn = Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], list[Finding]]

PREDICATES: Mapping[str, PredicateFn] = {
    "claim.evidence_citation.v1": claim_evidence_citation,
    "claim.scope_declared.v1": claim_scope_declared,
    "claim.limitations_present.v1": claim_limitations_present,
    "claim.overclaim_absent.v1": claim_overclaim_absent,
    "claim.gaps_declared.v1": claim_gaps_declared,
}


def predicate_ids() -> list[str]:
    return sorted(PREDICATES)


def evaluate(
    predicate_id: str,
    evidence: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
) -> list[Finding]:
    try:
        predicate = PREDICATES[predicate_id]
    except KeyError:
        raise KeyError(f"unknown claim predicate: {predicate_id!r}") from None
    return list(predicate(evidence, response))


def verdict_of(findings: Sequence[Finding]) -> str:
    from terminus_xi.codes import verdict_from_severities

    severities = [f.severity or f.with_severity(()).severity for f in findings]
    return verdict_from_severities(severities) if severities else "PASS"


def evaluate_arm(
    evidence: Sequence[Mapping[str, Any]],
    response: Mapping[str, Any],
    predicate_list: Sequence[str],
) -> list[dict[str, Any]]:
    """Deterministic per-arm predicate evaluation recorded in the bundle."""
    records: list[dict[str, Any]] = []
    for predicate_id in predicate_list:
        findings = [f.with_severity(()) for f in evaluate(predicate_id, evidence, response)]
        records.append(
            {
                "predicate": predicate_id,
                "verdict": verdict_of(findings),
                "findings": [f.to_dict() for f in findings],
            }
        )
    return records
