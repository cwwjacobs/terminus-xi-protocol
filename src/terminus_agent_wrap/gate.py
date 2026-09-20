"""Wrap-side pre-tool kill-switch. Default-deny allowlist. Not a planner.

``evaluate_tool_proposal`` is an online halt. It is not XI admission. The
sealed policy never enters prompts, events, or receipts: callers may inspect
``args_redacted`` in-process and must not serialize this module's policy text,
raw args, or a gate reason.

Return values are ``ALLOW`` or ``HALT`` only. No disable flag lives here;
skipping the gate is a test-only concern of the plan runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "ALLOW",
    "DEFAULT_ALLOWED_NAMES",
    "HALT",
    "HALT_CODE",
    "SealedToolPolicy",
    "default_sealed_policy",
    "evaluate_tool_proposal",
]

ALLOW = "ALLOW"
HALT = "HALT"
HALT_CODE = "gate_halt"

# Explicit allowlist. Unknown names HALT. This is not a deny-list.
DEFAULT_ALLOWED_NAMES: frozenset[str] = frozenset({"search", "fetch"})


@dataclass(frozen=True)
class SealedToolPolicy:
    """In-process allowlist. Repr is sealed so accidental logs do not dump names."""

    allowed_names: frozenset[str]

    def __repr__(self) -> str:
        return "SealedToolPolicy(<sealed>)"

    def __str__(self) -> str:
        return "SealedToolPolicy(<sealed>)"


def default_sealed_policy() -> SealedToolPolicy:
    return SealedToolPolicy(allowed_names=DEFAULT_ALLOWED_NAMES)


def evaluate_tool_proposal(
    name: str,
    *,
    args_redacted: Mapping[str, Any] | None = None,
    policy: SealedToolPolicy | None = None,
) -> str:
    """Return ``ALLOW`` or ``HALT`` for one proposed tool name.

    Default-deny: HALT unless ``name`` is on the sealed allowlist. The gate may
    inspect ``args_redacted`` locally and must not return policy text or a
    reason string.
    """
    if args_redacted is not None and not isinstance(args_redacted, Mapping):
        return HALT
    if not isinstance(name, str) or not name:
        return HALT
    sealed = policy or default_sealed_policy()
    if name in sealed.allowed_names:
        return ALLOW
    return HALT
