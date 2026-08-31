"""The single Terminus XI v1 audit semantic.

One function evaluates one frozen contract against one artifact and returns one
``terminus-xi.watchdog-result.v1``. There is no second audit path, no free-text
finding, and no model in the loop.

Failure modes are typed, never silent:

* pointer does not resolve -> ``INPUT_POINTER_MISSING`` (ERROR)
* no registered implementation -> ``CHECK_NOT_FOUND`` (ERROR)
* implementation raises -> ``CHECK_ERROR`` (ERROR)
* implementation emits an unknown code -> ``CONTRACT_INVALID`` (ERROR)
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .canonical import PointerError, resolve_pointer, sha256_canonical
from .checks import CheckNotRegistered, get as get_impl
from .codes import ISSUE_CODES
from .contracts import CheckContract, ContractSet
from .results import Finding, WatchdogResult, finding

__all__ = ["run_check", "run_contract_set", "resolve_inputs"]

_MISSING = object()


def resolve_inputs(artifact: Any, contract: CheckContract) -> tuple[dict[str, Any], list[str]]:
    """Resolve every declared pointer. Returns (values, missing_roles)."""
    values: dict[str, Any] = {}
    missing: list[str] = []
    for role in sorted(contract.input_pointers):
        pointer = contract.input_pointers[role]
        try:
            values[role] = resolve_pointer(artifact, pointer)
        except PointerError:
            missing.append(role)
    return values, missing


def _input_identity(values: Mapping[str, Any], contract: CheckContract) -> str:
    """Digest of exactly what this check consumed, with its pointer roles."""
    covered = [
        {"role": role, "pointer": contract.input_pointers[role], "value": values[role]}
        for role in sorted(values)
    ]
    return sha256_canonical(covered)


def _error_result(contract: CheckContract, findings: Sequence[Finding], input_sha: str) -> WatchdogResult:
    return WatchdogResult(
        check_id=contract.check_id,
        check_version=contract.version,
        verdict="ERROR",
        input_sha256=input_sha,
        findings=[f.with_severity(()) for f in findings],
        config_sha256=None if not contract.config else sha256_canonical(dict(contract.config)),
    )


def run_check(contract: CheckContract, artifact: Any) -> WatchdogResult:
    """Evaluate one frozen contract. Never raises for artifact-side problems."""
    values, missing = resolve_inputs(artifact, contract)
    input_sha = _input_identity(values, contract)

    if missing:
        return _error_result(
            contract,
            [
                finding(
                    "INPUT_POINTER_MISSING",
                    f"pointer {contract.input_pointers[role]!r} for role {role!r} "
                    f"did not resolve in the submitted artifact",
                    evidence_ref=role,
                )
                for role in missing
            ],
            input_sha,
        )

    try:
        impl = get_impl(contract.implementation)
    except CheckNotRegistered:
        return _error_result(
            contract,
            [
                finding(
                    "CHECK_NOT_FOUND",
                    f"no registered implementation {contract.implementation!r} "
                    f"for check {contract.check_id!r}",
                )
            ],
            input_sha,
        )

    try:
        raw = impl(values, dict(contract.config))
    except Exception as exc:  # deterministic containment: a raising check is an ERROR
        return _error_result(
            contract,
            [
                finding(
                    "CHECK_ERROR",
                    f"{contract.implementation} raised {type(exc).__name__}: {exc}",
                )
            ],
            input_sha,
        )

    findings = list(raw or [])
    unknown = [f.code for f in findings if f.code not in ISSUE_CODES]
    if unknown:
        return _error_result(
            contract,
            [
                finding(
                    "CONTRACT_INVALID",
                    f"check {contract.check_id!r} emitted codes outside the frozen "
                    f"vocabulary: {sorted(set(unknown))}",
                )
            ],
            input_sha,
        )

    return WatchdogResult.build(
        check_id=contract.check_id,
        check_version=contract.version,
        input_value=None,
        input_sha256=input_sha,
        findings=findings,
        config=dict(contract.config) or None,
        escalate_codes=contract.escalate_codes,
    )


def run_contract_set(contract_set: ContractSet, artifact: Any) -> list[WatchdogResult]:
    """Evaluate every contract in declared order."""
    return [run_check(contract, artifact) for contract in contract_set.contracts]
