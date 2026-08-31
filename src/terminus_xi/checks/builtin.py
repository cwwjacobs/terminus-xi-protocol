"""Builtin deterministic checks shipped with XI v1.

These are intentionally generic. Domain checks (claim boundary, parity,
redaction) are registered by the consuming engine; XI supplies the substrate,
not the domain vocabulary.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..canonical import canonical_bytes, sha256_canonical
from ..results import Finding, finding
from . import register

__all__ = [
    "not_empty",
    "payload_size",
    "required_keys",
    "hash_binding",
    "schema_conformance",
]


def not_empty(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Every declared input must be a non-empty value."""
    findings: list[Finding] = []
    for role in sorted(inputs):
        value = inputs[role]
        if value is None or value == "" or value == [] or value == {}:
            findings.append(
                finding("EVIDENCE_MISSING", f"input {role!r} is empty", evidence_ref=role)
            )
    return findings


def payload_size(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Measure canonical payload size and surface an oversized payload.

    Historical ``xiAuditAgent`` recorded an unmeasurable payload as a warning.
    XI v1 records it as ``PAYLOAD_SIZE_UNKNOWN`` (ERROR): an unestablished
    invariant is never a soft pass.
    """
    max_bytes = int(config.get("max_bytes", 10_000_000))
    findings: list[Finding] = []
    for role in sorted(inputs):
        try:
            size = len(canonical_bytes(inputs[role]))
        except (TypeError, ValueError) as exc:
            findings.append(
                finding("PAYLOAD_SIZE_UNKNOWN", f"input {role!r} is not measurable: {exc}", role)
            )
            continue
        findings.append(finding("MEASUREMENT", f"input {role!r} canonical bytes = {size}", role))
        if size > max_bytes:
            findings.append(
                finding("PAYLOAD_LARGE", f"input {role!r} is {size} bytes (limit {max_bytes})", role)
            )
    return findings


def required_keys(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Each declared input object must carry every configured key."""
    keys: list[str] = list(config.get("keys", []))
    findings: list[Finding] = []
    for role in sorted(inputs):
        value = inputs[role]
        if not isinstance(value, Mapping):
            findings.append(
                finding("INPUT_SHAPE_INVALID", f"input {role!r} is not an object", role)
            )
            continue
        for key in keys:
            if key not in value:
                findings.append(
                    finding("EVIDENCE_INCOMPLETE", f"input {role!r} is missing key {key!r}", role)
                )
    return findings


def hash_binding(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """The ``value`` input must hash to the digest recorded in ``declared``."""
    if "value" not in inputs or "declared" not in inputs:
        return [
            finding(
                "INPUT_SHAPE_INVALID",
                "hash_binding requires input roles 'value' and 'declared'",
            )
        ]
    actual = sha256_canonical(inputs["value"])
    declared = inputs["declared"]
    if not isinstance(declared, str):
        return [finding("INPUT_SHAPE_INVALID", "declared digest is not a string", "declared")]
    if actual != declared:
        return [
            finding(
                "HASH_MISMATCH",
                f"declared sha256 {declared} but canonical value hashes to {actual}",
                "declared",
            )
        ]
    return [finding("MEASUREMENT", f"hash binding confirmed: {actual}", "declared")]


def schema_conformance(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Validate an input against a registered frozen schema id."""
    from ..schemas import SchemaError, validate_against

    schema_id = config.get("schema_id")
    if not isinstance(schema_id, str):
        return [finding("INPUT_SHAPE_INVALID", "config.schema_id is required")]
    findings: list[Finding] = []
    for role in sorted(inputs):
        try:
            validate_against(inputs[role], schema_id, label=f"input {role!r}")
        except SchemaError as exc:
            findings.append(finding("SCHEMA_VIOLATION", str(exc), role))
        except KeyError as exc:
            findings.append(finding("INPUT_SHAPE_INVALID", f"unknown schema id: {exc}", role))
    return findings


register("xi.not_empty.v1", not_empty)
register("xi.payload_size.v1", payload_size)
register("xi.required_keys.v1", required_keys)
register("xi.hash_binding.v1", hash_binding)
register("xi.schema_conformance.v1", schema_conformance)
