"""Stdlib predicates registered into XI for the agent-run wrap spike.

No I/O, no clock, no model, no socket. Each function is a pure predicate over
the submitted run-artifact.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from terminus_xi.canonical import sha256_canonical
from terminus_xi.checks import register
from terminus_xi.results import Finding, finding

from .events import ALLOWED_KINDS

__all__ = [
    "REQUIRED_KINDS",
    "digests_well_formed",
    "event_count",
    "required_kinds",
]

_SHA256 = 64
_HEX = frozenset("0123456789abcdef")
# Observation envelope only. ``decision`` is allowed on a fixture line but is
# not a protocol invariant (that would soft-creep toward a planner/agent).
REQUIRED_KINDS = ("run_start", "tool_call", "tool_result", "run_end")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA256 and set(value) <= _HEX


def _artifact(inputs: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, list[Finding]]:
    artifact = inputs.get("artifact")
    if not isinstance(artifact, Mapping):
        return None, [finding("INPUT_SHAPE_INVALID", "submitted artifact is not an object")]
    return artifact, []


def event_count(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """``event_count`` is a non-boolean integer at or above ``config.min_count``."""
    artifact, errors = _artifact(inputs)
    if artifact is None:
        return errors
    min_count = int(config.get("min_count", 1))
    count = artifact.get("event_count")
    events = artifact.get("events")
    findings: list[Finding] = []
    if not isinstance(count, int) or isinstance(count, bool):
        return [finding("INPUT_SHAPE_INVALID", "event_count is not an integer", "event_count")]
    if not isinstance(events, list):
        return [finding("INPUT_SHAPE_INVALID", "events is not an array", "events")]
    if count != len(events):
        findings.append(
            finding(
                "CONTRADICTION_DETECTED",
                f"event_count {count} does not match events length {len(events)}",
                "event_count",
            )
        )
    if count < min_count:
        code = "EVIDENCE_MISSING" if count < 1 else "EVIDENCE_INCOMPLETE"
        findings.append(
            finding(code, f"event_count {count} is below required minimum {min_count}", "event_count")
        )
    if findings:
        return findings
    return [finding("MEASUREMENT", f"event_count={count}", "event_count")]


def required_kinds(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """Every configured kind appears at least once in ``events``."""
    artifact, errors = _artifact(inputs)
    if artifact is None:
        return errors
    events = artifact.get("events")
    if not isinstance(events, list):
        return [finding("INPUT_SHAPE_INVALID", "events is not an array", "events")]
    required = list(config.get("kinds", REQUIRED_KINDS))
    present = {
        event.get("kind")
        for event in events
        if isinstance(event, Mapping)
    }
    missing = [kind for kind in required if kind not in present]
    if missing:
        return [
            finding(
                "EVIDENCE_INCOMPLETE",
                f"required event kinds absent: {missing}",
                "events",
            )
        ]
    return [finding("MEASUREMENT", "all required event kinds are present", "events")]


def digests_well_formed(inputs: Mapping[str, Any], config: Mapping[str, Any]) -> Sequence[Finding]:
    """``events_sha256`` is bound to the event list; per-event digests are 64-hex or null."""
    del config
    artifact, errors = _artifact(inputs)
    if artifact is None:
        return errors
    events = artifact.get("events")
    findings: list[Finding] = []
    if not isinstance(events, list):
        return [finding("INPUT_SHAPE_INVALID", "events is not an array", "events")]

    declared = artifact.get("events_sha256")
    if not _is_sha256(declared):
        findings.append(
            finding(
                "INPUT_SHAPE_INVALID",
                "events_sha256 is not a lowercase 64-hex digest",
                "events_sha256",
            )
        )
    else:
        actual = sha256_canonical(events)
        if actual != declared:
            findings.append(
                finding(
                    "HASH_MISMATCH",
                    f"declared events_sha256 {declared} but canonical events hash to {actual}",
                    "events_sha256",
                )
            )

    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            findings.append(
                finding("INPUT_SHAPE_INVALID", f"events[{index}] is not an object", f"events/{index}")
            )
            continue
        kind = event.get("kind")
        if kind not in ALLOWED_KINDS:
            findings.append(
                finding(
                    "INPUT_SHAPE_INVALID",
                    f"events[{index}].kind {kind!r} is not an allowed kind",
                    f"events/{index}/kind",
                )
            )
        for field in ("args_sha256", "result_sha256"):
            value = event.get(field)
            if value is None:
                continue
            if not _is_sha256(value):
                findings.append(
                    finding(
                        "INPUT_SHAPE_INVALID",
                        f"events[{index}].{field} is not a lowercase 64-hex digest or null",
                        f"events/{index}/{field}",
                    )
                )
    if findings:
        return findings
    return [finding("MEASUREMENT", "event digests are well-formed and bound", "events_sha256")]


register("agent_wrap.event_count.v1", event_count)
register("agent_wrap.required_kinds.v1", required_kinds)
register("agent_wrap.digests_well_formed.v1", digests_well_formed)
