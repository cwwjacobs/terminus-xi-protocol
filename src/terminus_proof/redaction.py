"""Public-safe projection.

Redaction happens once, over one document holding the fixture evidence and both
arms, so a rule's hit count is a fact about the whole proof rather than about
whichever arm happened to be processed first.

This module only *applies* the policy and records what it did. Whether the
result is publishable is decided by ``proof.redaction.v1`` inside XI, which
re-reads the policy and scans the projection itself. The projector never grades
its own work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from terminus_xi.canonical import read_json, sha256_canonical
from terminus_xi.schemas import SchemaError, validate_against

__all__ = [
    "MASK_TEMPLATE",
    "RedactionError",
    "RedactionOutcome",
    "RedactionPolicy",
    "apply_policy",
    "compile_deny_patterns",
    "load_redaction_policy",
    "scan_denied",
]

MASK_TEMPLATE = "[REDACTED:{rule_id}]"


class RedactionError(ValueError):
    """The redaction policy is malformed or could not be applied."""


@dataclass(frozen=True)
class RedactionPolicy:
    document: Mapping[str, Any]
    path: str | None = None

    @property
    def policy_id(self) -> str:
        return str(self.document["policy_id"])

    @property
    def version(self) -> str:
        return str(self.document["version"])

    @property
    def rules(self) -> Sequence[Mapping[str, Any]]:
        return self.document["rules"]

    @property
    def deny_patterns(self) -> Sequence[Mapping[str, Any]]:
        return self.document["deny_patterns"]

    def sha256(self) -> str:
        return sha256_canonical(self.document)

    def rule_ids(self) -> list[str]:
        return [str(rule["rule_id"]) for rule in self.rules]

    def to_artifact_block(self) -> dict[str, Any]:
        """The policy surface recorded in the package artifact.

        Rule expressions are omitted: a rule describes where a secret lived,
        which is itself a hint. Deny patterns are carried in full because the
        XI check needs them and they describe only a shape.
        """
        return {
            "policy_id": self.policy_id,
            "policy_version": self.version,
            "policy_sha256": self.sha256(),
            "rule_ids": self.rule_ids(),
            "deny_patterns": [dict(pattern) for pattern in self.deny_patterns],
        }


def load_redaction_policy(path: str | Path) -> RedactionPolicy:
    document = read_json(path)
    if not isinstance(document, Mapping):
        raise RedactionError("redaction policy must be a JSON object")
    if document.get("schema") != "terminus-proof.redaction-policy.v1":
        raise RedactionError(
            f"unsupported redaction policy schema: {document.get('schema')!r}"
        )
    try:
        validate_against(document, "terminus-proof.redaction-policy.v1", label="redaction policy")
    except SchemaError as exc:
        raise RedactionError(str(exc)) from exc

    for rule in document["rules"]:
        if rule["match"]["kind"] == "regex":
            try:
                re.compile(rule["match"]["expression"])
            except re.error as exc:
                raise RedactionError(
                    f"rule {rule['rule_id']!r} has an invalid regex: {exc}"
                ) from exc
    for pattern in document["deny_patterns"]:
        try:
            re.compile(pattern["expression"])
        except re.error as exc:
            raise RedactionError(
                f"deny pattern {pattern['pattern_id']!r} is an invalid regex: {exc}"
            ) from exc
    return RedactionPolicy(document=document, path=str(path))


@dataclass(frozen=True)
class RedactionOutcome:
    value: Any
    applied_rules: tuple[dict[str, Any], ...]
    unapplied_rules: tuple[str, ...]

    def accounting(self, policy: RedactionPolicy) -> dict[str, Any]:
        return {
            "policy_id": policy.policy_id,
            "policy_version": policy.version,
            "policy_sha256": policy.sha256(),
            "applied_rules": [dict(rule) for rule in self.applied_rules],
            "unapplied_rules": list(self.unapplied_rules),
        }


def _mask_strings(value: Any, expression: re.Pattern[str], replacement: str) -> tuple[Any, int]:
    if isinstance(value, str):
        new, count = expression.subn(replacement, value)
        return new, count
    if isinstance(value, list):
        hits = 0
        items = []
        for item in value:
            replaced, count = _mask_strings(item, expression, replacement)
            hits += count
            items.append(replaced)
        return items, hits
    if isinstance(value, dict):
        hits = 0
        result = {}
        for key, item in value.items():
            replaced, count = _mask_strings(item, expression, replacement)
            hits += count
            result[key] = replaced
        return result, hits
    return value, 0


def _pointer_tokens(expression: str) -> list[str]:
    if not expression.startswith("/"):
        raise RedactionError(f"pointer rule must start with '/': {expression!r}")
    return [token.replace("~1", "/").replace("~0", "~") for token in expression.split("/")[1:]]


def _apply_pointer(value: Any, tokens: Sequence[str], action: str, rule_id: str) -> tuple[Any, int]:
    if not tokens:
        return value, 0
    token, rest = tokens[0], tokens[1:]

    if isinstance(value, dict):
        keys = list(value) if token == "*" else ([token] if token in value else [])
        hits = 0
        result = dict(value)
        for key in keys:
            if rest:
                child, count = _apply_pointer(result[key], rest, action, rule_id)
                result[key] = child
                hits += count
            elif action == "drop":
                del result[key]
                hits += 1
            else:
                result[key] = MASK_TEMPLATE.format(rule_id=rule_id)
                hits += 1
        return result, hits

    if isinstance(value, list):
        if token == "*":
            indices = range(len(value))
        elif token.isdigit() and int(token) < len(value):
            indices = [int(token)]
        else:
            return value, 0
        hits = 0
        result = list(value)
        dropped: list[int] = []
        for index in indices:
            if rest:
                child, count = _apply_pointer(result[index], rest, action, rule_id)
                result[index] = child
                hits += count
            elif action == "drop":
                dropped.append(index)
                hits += 1
            else:
                result[index] = MASK_TEMPLATE.format(rule_id=rule_id)
                hits += 1
        for index in sorted(dropped, reverse=True):
            del result[index]
        return result, hits

    return value, 0


def apply_policy(policy: RedactionPolicy, document: Any) -> RedactionOutcome:
    """Apply every rule in declared order and record what each one did."""
    current = document
    applied: list[dict[str, Any]] = []
    unapplied: list[str] = []

    for rule in policy.rules:
        rule_id = str(rule["rule_id"])
        action = str(rule["action"])
        match = rule["match"]
        if match["kind"] == "regex":
            expression = re.compile(match["expression"])
            replacement = MASK_TEMPLATE.format(rule_id=rule_id)
            if action == "drop":
                raise RedactionError(
                    f"rule {rule_id!r} declares action 'drop' with a regex match; "
                    "dropping is only defined for pointer rules"
                )
            current, hits = _mask_strings(current, expression, replacement)
        else:
            tokens = _pointer_tokens(match["expression"])
            current, hits = _apply_pointer(current, tokens, action, rule_id)

        applied.append({"rule_id": rule_id, "hits": hits})
        if hits < int(rule.get("required_hits", 0)):
            unapplied.append(rule_id)

    return RedactionOutcome(
        value=current,
        applied_rules=tuple(applied),
        unapplied_rules=tuple(unapplied),
    )


def compile_deny_patterns(
    patterns: Sequence[Mapping[str, Any]],
) -> list[tuple[str, re.Pattern[str], str]]:
    compiled = []
    for pattern in patterns:
        compiled.append(
            (
                str(pattern["pattern_id"]),
                re.compile(str(pattern["expression"])),
                str(pattern.get("description", "")),
            )
        )
    return compiled


def scan_denied(
    value: Any,
    patterns: Sequence[Mapping[str, Any]],
    *,
    path: str = "",
) -> list[dict[str, str]]:
    """Return every place a deny pattern matches, deterministically ordered.

    The match text itself is never returned. A leak report that quotes the leak
    is a second leak.
    """
    compiled = compile_deny_patterns(patterns)
    hits: list[dict[str, str]] = []
    _scan(value, compiled, path, hits)
    return sorted(hits, key=lambda hit: (hit["pattern_id"], hit["location"]))


def _scan(
    value: Any,
    compiled: Sequence[tuple[str, re.Pattern[str], str]],
    path: str,
    hits: list[dict[str, str]],
) -> None:
    if isinstance(value, str):
        for pattern_id, expression, description in compiled:
            if expression.search(value):
                hits.append(
                    {
                        "pattern_id": pattern_id,
                        "location": path or "<root>",
                        "description": description,
                    }
                )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan(item, compiled, f"{path}/{index}", hits)
        return
    if isinstance(value, dict):
        for key in sorted(value):
            _scan(value[key], compiled, f"{path}/{key}", hits)
