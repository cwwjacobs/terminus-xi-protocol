"""Findings and the canonical watchdog result envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .canonical import sha256_canonical
from .codes import escalate, severity_of, verdict_from_severities

__all__ = ["Finding", "WatchdogResult", "finding"]


@dataclass(frozen=True)
class Finding:
    """One typed observation from one check.

    ``severity`` is never supplied by the caller: it is derived from the frozen
    code vocabulary, optionally escalated by the check contract.
    """

    code: str
    message: str
    evidence_ref: str | None = None
    severity: str = field(default="")

    def with_severity(self, escalate_codes: Iterable[str] = ()) -> "Finding":
        return Finding(
            code=self.code,
            message=self.message,
            evidence_ref=self.evidence_ref,
            severity=escalate(self.code, escalate_codes),
        )

    def to_dict(self) -> dict[str, Any]:
        severity = self.severity or severity_of(self.code)
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": severity,
            "message": self.message,
        }
        if self.evidence_ref is not None:
            payload["evidence_ref"] = self.evidence_ref
        return payload


def finding(code: str, message: str, evidence_ref: str | None = None) -> Finding:
    """Convenience constructor used by check implementations."""
    return Finding(code=code, message=message, evidence_ref=evidence_ref)


@dataclass(frozen=True)
class WatchdogResult:
    """``terminus-xi.watchdog-result.v1``."""

    check_id: str
    check_version: str
    verdict: str
    input_sha256: str
    findings: Sequence[Finding]
    config_sha256: str | None = None

    @classmethod
    def build(
        cls,
        *,
        check_id: str,
        check_version: str,
        input_value: Any,
        findings: Sequence[Finding],
        config: Any = None,
        escalate_codes: Iterable[str] = (),
        input_sha256: str | None = None,
    ) -> "WatchdogResult":
        resolved = [f.with_severity(escalate_codes) for f in findings]
        verdict = verdict_from_severities(f.severity for f in resolved)
        return cls(
            check_id=check_id,
            check_version=check_version,
            verdict=verdict,
            input_sha256=input_sha256 or sha256_canonical(input_value),
            findings=resolved,
            config_sha256=None if config in (None, {}) else sha256_canonical(config),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "terminus-xi.watchdog-result.v1",
            "check_id": self.check_id,
            "check_version": self.check_version,
            "verdict": self.verdict,
            "input_sha256": self.input_sha256,
            "findings": [f.to_dict() for f in self.findings],
        }
        if self.config_sha256 is not None:
            payload["config_sha256"] = self.config_sha256
        return payload

    def codes(self) -> list[str]:
        return [f.code for f in self.findings]
