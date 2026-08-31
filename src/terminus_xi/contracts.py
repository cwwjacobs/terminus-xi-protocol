"""Frozen check contracts and contract sets.

Two contract envelopes are accepted:

* ``terminus-xi.check-contract.v1`` - the original bootstrap schema. It carries
  no implementation binding, no input pointers, and no configuration, so it is
  upgraded in memory: the implementation defaults to ``<check_id>``, the input
  is the whole artifact, and configuration is empty.
* ``terminus-xi.check-contract.v2`` - the active envelope.

A contract is refused outright if it is not marked deterministic or if it names
an issue code outside the frozen vocabulary. XI never evaluates a contract it
cannot fully interpret.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import read_json, sha256_canonical
from .codes import ISSUE_CODES, severity_of
from .schemas import SchemaError, validate_against

__all__ = ["CheckContract", "ContractSet", "ContractError", "load_contract", "load_contract_set"]


class ContractError(ValueError):
    """The check contract is malformed, non-deterministic, or unknown."""


@dataclass(frozen=True)
class CheckContract:
    check_id: str
    version: str
    implementation: str
    input_contract: str
    input_pointers: Mapping[str, str]
    pass_condition: str
    failure_codes: tuple[str, ...] = ()
    escalate_codes: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)
    title: str | None = None
    category: str | None = None
    source_schema: str = "terminus-xi.check-contract.v2"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "terminus-xi.check-contract.v2",
            "check_id": self.check_id,
            "version": self.version,
            "deterministic": True,
            "implementation": self.implementation,
            "input_contract": self.input_contract,
            "input_pointers": dict(self.input_pointers),
            "pass_condition": self.pass_condition,
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.category is not None:
            payload["category"] = self.category
        if self.failure_codes:
            payload["failure_codes"] = list(self.failure_codes)
        if self.escalate_codes:
            payload["escalate_codes"] = list(self.escalate_codes)
        if self.config:
            payload["config"] = dict(self.config)
        return payload

    def sha256(self) -> str:
        return sha256_canonical(self.to_dict())


def _validate_codes(contract_id: str, codes: Sequence[str], escalated: Sequence[str]) -> None:
    for code in codes:
        if code not in ISSUE_CODES:
            raise ContractError(
                f"contract {contract_id!r} declares failure code {code!r} which is "
                "not in the frozen XI v1 issue-code vocabulary"
            )
    for code in escalated:
        if code not in ISSUE_CODES:
            raise ContractError(
                f"contract {contract_id!r} escalates unknown code {code!r}"
            )
        if severity_of(code) != "WARN":
            raise ContractError(
                f"contract {contract_id!r} escalates {code!r} whose severity class is "
                f"{severity_of(code)!r}; only WARN codes may be escalated"
            )


def load_contract(document: Mapping[str, Any]) -> CheckContract:
    """Validate and normalize one check contract document."""
    if not isinstance(document, Mapping):
        raise ContractError("check contract must be a JSON object")
    schema_id = document.get("schema")
    if schema_id not in ("terminus-xi.check-contract.v1", "terminus-xi.check-contract.v2"):
        raise ContractError(f"unsupported check contract schema: {schema_id!r}")
    try:
        validate_against(document, schema_id, label=f"check contract {document.get('check_id')!r}")
    except SchemaError as exc:
        raise ContractError(str(exc)) from exc

    if document.get("deterministic") is not True:
        raise ContractError(
            f"contract {document.get('check_id')!r} is not marked deterministic; "
            "XI v1 evaluates deterministic contracts only"
        )

    failure_codes = tuple(document.get("failure_codes", ()))
    escalate_codes = tuple(document.get("escalate_codes", ()))
    _validate_codes(str(document.get("check_id")), failure_codes, escalate_codes)

    if schema_id == "terminus-xi.check-contract.v1":
        return CheckContract(
            check_id=document["check_id"],
            version=document["version"],
            implementation=document["check_id"],
            input_contract=document["input_contract"],
            input_pointers={"artifact": ""},
            pass_condition=document["pass_condition"],
            failure_codes=failure_codes,
            escalate_codes=(),
            config={},
            source_schema=schema_id,
        )

    return CheckContract(
        check_id=document["check_id"],
        version=document["version"],
        implementation=document["implementation"],
        input_contract=document["input_contract"],
        input_pointers=dict(document["input_pointers"]),
        pass_condition=document["pass_condition"],
        failure_codes=failure_codes,
        escalate_codes=escalate_codes,
        config=dict(document.get("config", {})),
        title=document.get("title"),
        category=document.get("category"),
        source_schema=schema_id,
    )


@dataclass(frozen=True)
class ContractSet:
    set_id: str
    version: str
    contracts: tuple[CheckContract, ...]
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "terminus-xi.check-contract-set.v1",
            "set_id": self.set_id,
            "version": self.version,
            "contracts": [c.to_dict() for c in self.contracts],
        }
        if self.description is not None:
            payload["description"] = self.description
        return payload

    def sha256(self) -> str:
        return sha256_canonical(self.to_dict())

    def check_ids(self) -> list[str]:
        return [c.check_id for c in self.contracts]


def load_contract_set(document: Mapping[str, Any] | str | Path) -> ContractSet:
    """Load a contract set from a document or a path."""
    if isinstance(document, (str, Path)):
        document = read_json(document)
    if not isinstance(document, Mapping):
        raise ContractError("contract set must be a JSON object")
    if document.get("schema") != "terminus-xi.check-contract-set.v1":
        raise ContractError(f"unsupported contract set schema: {document.get('schema')!r}")
    try:
        validate_against(document, "terminus-xi.check-contract-set.v1", label="contract set")
    except SchemaError as exc:
        raise ContractError(str(exc)) from exc

    contracts = tuple(load_contract(item) for item in document["contracts"])
    seen: set[str] = set()
    for contract in contracts:
        if contract.check_id in seen:
            raise ContractError(f"duplicate check_id in contract set: {contract.check_id!r}")
        seen.add(contract.check_id)
    return ContractSet(
        set_id=document["set_id"],
        version=document["version"],
        contracts=contracts,
        description=document.get("description"),
    )
