"""Deterministic domain checks registered into the frozen XI v1 registry.

XI supplies the substrate: pointer resolution, the issue-code vocabulary,
verdict derivation, admission, and receipts. This module supplies the domain
predicates for baseline-vs-capability proofs. Every function here is a pure
function of its resolved inputs and its frozen configuration. None of them
performs I/O, reads a clock, or calls a model.

The engine imports this module for its side effect of registration, exactly as
``terminus_xi.checks.builtin`` is imported by the XI registry itself.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from terminus_xi.canonical import sha256_canonical
from terminus_xi.checks import register
from terminus_xi.results import Finding, finding

from .redaction import scan_denied

__all__ = [
    "arm_binding",
    "claim_citations",
    "claim_limitations",
    "claim_overbroad",
    "claim_scope",
    "claim_supported",
    "evidence_complete",
    "parity_config",
    "parity_identity",
    "redaction_public_safe",
    "spec_faithful",
]

_MISSING = object()
_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().lower()


def _shape(role: str, message: str) -> Finding:
    return finding("INPUT_SHAPE_INVALID", message, role)


# --------------------------------------------------------------------------
# claim-boundary checks (evaluated per execution arm)
# --------------------------------------------------------------------------


def claim_scope(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Every claim must state the bound it is made within."""
    claims = inputs.get("claims")
    if not isinstance(claims, list):
        return [_shape("claims", "claims input is not an array")]
    required = list(config.get("required_scope_fields", ["asset_scope", "time_window", "surface"]))

    findings: list[Finding] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            findings.append(_shape("claims", "a claim entry is not an object"))
            continue
        claim_id = str(claim.get("claim_id", "<unidentified>"))
        scope = claim.get("scope")
        if not isinstance(scope, Mapping) or not scope:
            findings.append(
                finding("CLAIM_SCOPE_MISSING", f"claim {claim_id} declares no scope", claim_id)
            )
            continue
        absent = [
            field
            for field in required
            if not isinstance(scope.get(field), str) or not scope.get(field, "").strip()
        ]
        if absent:
            findings.append(
                finding(
                    "CLAIM_SCOPE_MISSING",
                    f"claim {claim_id} scope is missing {absent}",
                    claim_id,
                )
            )
    if not findings:
        findings.append(
            finding("MEASUREMENT", f"{len(claims)} claims each declare a complete scope")
        )
    return findings


def claim_overbroad(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """No claim may use language the evidence cannot reach.

    This is a bounded lexical predicate over a frozen lexicon. It establishes
    that a statement does not use unbounded certification language. It does not
    and cannot establish that a statement is true.
    """
    claims = inputs.get("claims")
    if not isinstance(claims, list):
        return [_shape("claims", "claims input is not an array")]
    lexicon = [str(phrase) for phrase in config.get("lexicon", ())]
    if not lexicon:
        return [finding("CONTRACT_INVALID", "claim_overbroad requires a non-empty config.lexicon")]

    findings: list[Finding] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            findings.append(_shape("claims", "a claim entry is not an object"))
            continue
        claim_id = str(claim.get("claim_id", "<unidentified>"))
        statement = _normalize(str(claim.get("statement", "")))
        hits = sorted({phrase for phrase in lexicon if _normalize(phrase) in statement})
        if hits:
            findings.append(
                finding(
                    "CLAIM_OVERBROAD",
                    f"claim {claim_id} uses unbounded language {hits}",
                    claim_id,
                )
            )
    if not findings:
        findings.append(
            finding(
                "MEASUREMENT",
                f"{len(claims)} claims checked against {len(lexicon)} unbounded phrases",
            )
        )
    return findings


def claim_citations(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Every claim must cite evidence, and every citation must resolve."""
    claims = inputs.get("claims")
    evidence = inputs.get("evidence")
    if not isinstance(claims, list):
        return [_shape("claims", "claims input is not an array")]
    if not isinstance(evidence, list):
        return [_shape("evidence", "evidence input is not an array")]

    available = {
        str(item.get("evidence_id"))
        for item in evidence
        if isinstance(item, Mapping) and item.get("evidence_id") is not None
    }

    findings: list[Finding] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            findings.append(_shape("claims", "a claim entry is not an object"))
            continue
        claim_id = str(claim.get("claim_id", "<unidentified>"))
        refs = claim.get("evidence_refs") or []
        if not isinstance(refs, list):
            findings.append(_shape(claim_id, f"claim {claim_id} evidence_refs is not an array"))
            continue
        if not refs:
            findings.append(
                finding(
                    "EVIDENCE_CITATION_MISSING",
                    f"claim {claim_id} cites no evidence",
                    claim_id,
                )
            )
            continue
        unresolved = sorted({str(ref) for ref in refs if str(ref) not in available})
        if unresolved:
            findings.append(
                finding(
                    "EVIDENCE_REF_UNRESOLVED",
                    f"claim {claim_id} cites {unresolved}, absent from the evidence set "
                    f"{sorted(available)}",
                    claim_id,
                )
            )
    if not findings:
        findings.append(
            finding(
                "MEASUREMENT",
                f"{len(claims)} claims cite only identifiers present in the evidence set",
            )
        )
    return findings


def claim_limitations(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Limitations must exist and must cover every gap the fixture declares."""
    limitations = inputs.get("limitations")
    gaps = inputs.get("gaps") or []
    if not isinstance(limitations, list):
        return [_shape("limitations", "limitations input is not an array")]
    if not isinstance(gaps, list):
        return [_shape("gaps", "gaps input is not an array")]

    stated = [_normalize(str(item)) for item in limitations if str(item).strip()]
    if not stated:
        return [finding("LIMITATIONS_ABSENT", "the claim set states no limitations")]

    findings: list[Finding] = []
    for index, gap in enumerate(gaps):
        needle = _normalize(str(gap))
        if not any(needle in item for item in stated):
            findings.append(
                finding(
                    "EVIDENCE_GAP_UNDECLARED",
                    f"declared coverage gap {index} is not stated in the limitations",
                    f"gap[{index}]",
                )
            )
    if not findings:
        findings.append(
            finding(
                "MEASUREMENT",
                f"{len(stated)} limitations stated, covering all {len(gaps)} declared gaps",
            )
        )
    return findings


# --------------------------------------------------------------------------
# parity and package-level checks
# --------------------------------------------------------------------------


def parity_identity(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Two recorded identities must be canonically identical."""
    code = str(config.get("mismatch_code", "CONTRADICTION_DETECTED"))
    subject = str(config.get("subject", "identity"))
    if "baseline" not in inputs or "augmented" not in inputs:
        return [_shape("baseline", "parity_identity requires roles 'baseline' and 'augmented'")]

    left = sha256_canonical(inputs["baseline"])
    right = sha256_canonical(inputs["augmented"])
    if left != right:
        return [
            finding(
                code,
                f"{subject} differs between arms: baseline sha256 {left[:16]} "
                f"vs augmented sha256 {right[:16]}",
                subject,
            )
        ]
    return [finding("MEASUREMENT", f"{subject} identical across arms: sha256 {left[:16]}", subject)]


def parity_config(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Configuration may differ only by the declared changed variable."""
    baseline = inputs.get("baseline")
    augmented = inputs.get("augmented")
    changed = inputs.get("changed_variable")
    if not isinstance(baseline, Mapping) or not isinstance(augmented, Mapping):
        return [_shape("baseline", "both arm configurations must be objects")]
    if not isinstance(changed, Mapping) or "name" not in changed:
        return [_shape("changed_variable", "changed_variable must declare a name")]

    name = str(changed["name"])
    keys = sorted(set(baseline) | set(augmented))
    differing = [
        key
        for key in keys
        if sha256_canonical(baseline.get(key, None)) != sha256_canonical(augmented.get(key, None))
        or (key in baseline) != (key in augmented)
    ]

    findings: list[Finding] = []
    if name not in differing:
        findings.append(
            finding(
                "CHANGED_VARIABLE_ABSENT",
                f"declared changed variable {name!r} does not differ between the arms; "
                "the runs are not a controlled comparison of it",
                name,
            )
        )
    else:
        expected_baseline = changed.get("baseline_value", _MISSING)
        expected_augmented = changed.get("augmented_value", _MISSING)
        if expected_baseline is not _MISSING and baseline.get(name) != expected_baseline:
            findings.append(
                finding(
                    "CHANGED_VARIABLE_ABSENT",
                    f"baseline recorded {name}={baseline.get(name)!r} but the spec declares "
                    f"{expected_baseline!r}",
                    name,
                )
            )
        if expected_augmented is not _MISSING and augmented.get(name) != expected_augmented:
            findings.append(
                finding(
                    "CHANGED_VARIABLE_ABSENT",
                    f"augmented recorded {name}={augmented.get(name)!r} but the spec declares "
                    f"{expected_augmented!r}",
                    name,
                )
            )

    for key in differing:
        if key == name:
            continue
        findings.append(
            finding(
                "CONFIG_DRIFT_UNDECLARED",
                f"configuration key {key!r} differs between the arms but is not the declared "
                f"changed variable {name!r}",
                key,
            )
        )

    if not findings:
        findings.append(
            finding(
                "MEASUREMENT",
                f"{len(keys)} configuration keys compared; only {name!r} differs "
                f"({baseline.get(name)!r} -> {augmented.get(name)!r})",
                name,
            )
        )
    return findings


def spec_faithful(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """The recorded executions must be the ones the specification describes."""
    declared = inputs.get("declared")
    if not isinstance(declared, Mapping):
        return [_shape("declared", "declared surface must be an object")]

    findings: list[Finding] = []
    declared_model = declared.get("model") or {}
    declared_tools = declared.get("tool_surface") or {}
    declared_arms = declared.get("arms") or {}
    params_sha = sha256_canonical(declared_model.get("params", {}))

    for role in ("baseline", "augmented"):
        arm = inputs.get(role)
        if not isinstance(arm, Mapping):
            findings.append(_shape(role, f"arm {role!r} evidence must be an object"))
            continue
        recorded_model = arm.get("model") or {}
        for field in ("provider", "model_id"):
            if recorded_model.get(field) != declared_model.get(field):
                findings.append(
                    finding(
                        "CONTRADICTION_DETECTED",
                        f"arm {role} recorded model {field} {recorded_model.get(field)!r} but the "
                        f"spec declares {declared_model.get(field)!r}",
                        role,
                    )
                )
        if recorded_model.get("params_sha256") != params_sha:
            findings.append(
                finding(
                    "CONTRADICTION_DETECTED",
                    f"arm {role} recorded model parameters that do not match the spec",
                    role,
                )
            )
        recorded_tools = (arm.get("tool_surface") or {}).get("tools")
        if recorded_tools != declared_tools.get("tools"):
            findings.append(
                finding(
                    "CONTRADICTION_DETECTED",
                    f"arm {role} recorded tool surface {recorded_tools!r} but the spec declares "
                    f"{declared_tools.get('tools')!r}",
                    role,
                )
            )
        declared_config = (declared_arms.get(role) or {}).get("config")
        if sha256_canonical(arm.get("config")) != sha256_canonical(declared_config):
            findings.append(
                finding(
                    "CONTRADICTION_DETECTED",
                    f"arm {role} recorded a configuration that differs from the one the spec "
                    f"declares for it",
                    role,
                )
            )

    if not findings:
        findings.append(
            finding("MEASUREMENT", "both arms match the model, tools, and configuration the spec declares")
        )
    return findings


def arm_binding(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Each arm record must be bound to its own evidence by canonical digest."""
    arms = inputs.get("arms")
    if not isinstance(arms, Mapping) or not arms:
        return [_shape("arms", "arms input must be a non-empty object")]

    findings: list[Finding] = []
    for arm_id in sorted(arms):
        arm = arms[arm_id]
        if not isinstance(arm, Mapping):
            findings.append(_shape(arm_id, f"arm {arm_id!r} is not an object"))
            continue
        evidence = arm.get("evidence")
        declared = arm.get("document_sha256")
        if not isinstance(evidence, Mapping) or not isinstance(declared, str):
            findings.append(_shape(arm_id, f"arm {arm_id!r} is missing evidence or its digest"))
            continue
        actual = sha256_canonical(evidence)
        if actual != declared:
            findings.append(
                finding(
                    "HASH_MISMATCH",
                    f"arm {arm_id!r} declares document_sha256 {declared} but its embedded "
                    f"evidence hashes to {actual}",
                    arm_id,
                )
            )
        if arm.get("arm_id") != evidence.get("arm_id"):
            findings.append(
                finding(
                    "CONTRADICTION_DETECTED",
                    f"arm record {arm.get('arm_id')!r} embeds evidence for arm "
                    f"{evidence.get('arm_id')!r}",
                    arm_id,
                )
            )
    if not findings:
        findings.append(
            finding("MEASUREMENT", f"{len(arms)} arm records bound to their evidence by digest")
        )
    return findings


def evidence_complete(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Both arms must have submitted evidence complete enough to reason about."""
    arms = inputs.get("arms")
    if not isinstance(arms, Mapping) or not arms:
        return [_shape("arms", "arms input must be a non-empty object")]
    minimum_steps = int(config.get("min_transcript_steps", 1))

    findings: list[Finding] = []
    for arm_id in sorted(arms):
        arm = arms[arm_id]
        if not isinstance(arm, Mapping):
            findings.append(_shape(arm_id, f"arm {arm_id!r} is not an object"))
            continue
        evidence = arm.get("evidence")
        if not isinstance(evidence, Mapping):
            findings.append(
                finding("EVIDENCE_MISSING", f"arm {arm_id!r} carries no evidence bundle", arm_id)
            )
            continue

        transcript = evidence.get("transcript") or []
        if len(transcript) < minimum_steps:
            findings.append(
                finding(
                    "EVIDENCE_INCOMPLETE",
                    f"arm {arm_id!r} transcript has {len(transcript)} steps, fewer than the "
                    f"{minimum_steps} the contract requires",
                    arm_id,
                )
            )
        if not (evidence.get("evidence_available") or []):
            findings.append(
                finding(
                    "EVIDENCE_INCOMPLETE",
                    f"arm {arm_id!r} records no available evidence",
                    arm_id,
                )
            )
        if not isinstance(evidence.get("raw_sha256"), str):
            findings.append(
                finding(
                    "EVIDENCE_INCOMPLETE",
                    f"arm {arm_id!r} does not bind the unredacted execution by digest",
                    arm_id,
                )
            )
        claims = (evidence.get("output") or {}).get("claims")
        if not claims:
            findings.append(
                finding("EVIDENCE_INCOMPLETE", f"arm {arm_id!r} produced no claims", arm_id)
            )

        xi = arm.get("xi")
        if not isinstance(xi, Mapping) or not xi.get("verdicts"):
            findings.append(
                finding(
                    "EVIDENCE_INCOMPLETE",
                    f"arm {arm_id!r} carries no XI arm-boundary outcome",
                    arm_id,
                )
            )

    if not findings:
        findings.append(
            finding("MEASUREMENT", f"{len(arms)} arms submitted complete evidence")
        )
    return findings


def claim_supported(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """The proof's own claim must be established by the arms' XI outcomes.

    This is the check that stops the engine from advertising a difference it did
    not observe. The claim is a delta claim, so it is established only when the
    baseline arm was actually blocked, the augmented arm was actually admitted,
    and none of the codes that blocked the baseline arm survive into the
    augmented one.
    """
    baseline = inputs.get("baseline_xi")
    augmented = inputs.get("augmented_xi")
    if not isinstance(baseline, Mapping) or not isinstance(augmented, Mapping):
        return [_shape("baseline_xi", "both arm XI outcomes must be objects")]

    allowed_baseline = list(config.get("required_baseline_admission", ["REJECT"]))
    allowed_augmented = list(config.get("required_augmented_admission", ["ADMIT"]))

    findings: list[Finding] = []
    baseline_admission = str(baseline.get("admission"))
    augmented_admission = str(augmented.get("admission"))

    if baseline_admission not in allowed_baseline:
        findings.append(
            finding(
                "CLAIM_UNSUPPORTED",
                f"the baseline arm was {baseline_admission}, not one of {allowed_baseline}; "
                "there is no observed gap for the changed variable to close",
                "baseline",
            )
        )
    if augmented_admission not in allowed_augmented:
        findings.append(
            finding(
                "CLAIM_UNSUPPORTED",
                f"the augmented arm was {augmented_admission}, not one of {allowed_augmented}; "
                "the capability-enabled run did not itself clear the boundary",
                "augmented",
            )
        )

    baseline_blocking = sorted({str(code) for code in baseline.get("blocking_codes", [])})
    augmented_blocking = sorted({str(code) for code in augmented.get("blocking_codes", [])})

    if config.get("require_baseline_blocking_codes", True) and not baseline_blocking:
        findings.append(
            finding(
                "CLAIM_UNSUPPORTED",
                "the baseline arm produced no blocking codes, so no claim-boundary defect was "
                "observed to be fixed",
                "baseline",
            )
        )
    if config.get("require_blocking_codes_cleared", True):
        residual = sorted(set(baseline_blocking) & set(augmented_blocking))
        if residual:
            findings.append(
                finding(
                    "CLAIM_UNSUPPORTED",
                    f"codes {residual} blocked the baseline arm and still block the augmented arm",
                    "augmented",
                )
            )

    if not findings:
        findings.append(
            finding(
                "MEASUREMENT",
                f"baseline {baseline_admission} with blocking codes {baseline_blocking}; "
                f"augmented {augmented_admission} with blocking codes {augmented_blocking}",
            )
        )
    return findings


def redaction_public_safe(
    inputs: Mapping[str, Any], config: Mapping[str, Any]
) -> Sequence[Finding]:
    """No denied value may survive, and every declared rule must have fired."""
    policy = inputs.get("policy")
    if not isinstance(policy, Mapping):
        return [_shape("policy", "policy input must be the artifact's redaction block")]
    patterns = policy.get("deny_patterns")
    if not isinstance(patterns, list) or not patterns:
        return [
            finding(
                "REDACTION_POLICY_VIOLATION",
                "the redaction policy declares no deny patterns, so nothing establishes that "
                "the projection is public-safe",
                "policy",
            )
        ]

    findings: list[Finding] = []
    surfaces = {role: inputs[role] for role in sorted(inputs) if role != "policy"}
    for role, surface in surfaces.items():
        for hit in scan_denied(surface, patterns, path=f"/{role}"):
            findings.append(
                finding(
                    "SENSITIVE_VALUE_PRESENT",
                    f"deny pattern {hit['pattern_id']!r} ({hit['description']}) matches the "
                    f"public surface at {hit['location']}",
                    hit["location"],
                )
            )

    declared_rules = sorted({str(rule) for rule in policy.get("rule_ids", [])})
    for role, surface in surfaces.items():
        if not isinstance(surface, Mapping):
            continue
        accounting = surface.get("redaction")
        if not isinstance(accounting, Mapping):
            continue
        if accounting.get("policy_sha256") != policy.get("policy_sha256"):
            findings.append(
                finding(
                    "REDACTION_POLICY_VIOLATION",
                    f"{role} was projected under a different redaction policy than the one the "
                    "artifact records",
                    role,
                )
            )
        unapplied = sorted({str(rule) for rule in accounting.get("unapplied_rules", [])})
        if unapplied:
            findings.append(
                finding(
                    "REDACTION_POLICY_VIOLATION",
                    f"redaction rules {unapplied} did not fire the number of times they declare, "
                    f"so {role} was not cleaned by the whole policy",
                    role,
                )
            )
        applied = sorted({str(rule.get("rule_id")) for rule in accounting.get("applied_rules", [])})
        if declared_rules and applied != declared_rules:
            findings.append(
                finding(
                    "REDACTION_POLICY_VIOLATION",
                    f"{role} records rules {applied} but the policy declares {declared_rules}",
                    role,
                )
            )

    if not findings:
        findings.append(
            finding(
                "MEASUREMENT",
                f"{len(surfaces)} public surfaces scanned against {len(patterns)} deny patterns "
                f"with no match; {len(declared_rules)} policy rules all applied",
            )
        )
    return findings


register("proof.claim_scope.v1", claim_scope)
register("proof.claim_overbroad.v1", claim_overbroad)
register("proof.claim_citations.v1", claim_citations)
register("proof.claim_limitations.v1", claim_limitations)
register("proof.parity_identity.v1", parity_identity)
register("proof.parity_config.v1", parity_config)
register("proof.spec_faithful.v1", spec_faithful)
register("proof.arm_binding.v1", arm_binding)
register("proof.evidence_complete.v1", evidence_complete)
register("proof.claim_supported.v1", claim_supported)
register("proof.redaction.v1", redaction_public_safe)
