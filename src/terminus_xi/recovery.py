"""Bounded recovery base.

This is an interface with a budget, not a planner and not a persona. It does
four things and nothing else:

1. holds an explicit attempt budget;
2. calls a caller-supplied repair function that returns a *new* artifact;
3. forces the repaired artifact back through the caller's normal validation
   path before any admission is possible;
4. appends receipts to an append-only ledger, linking each new receipt to the
   receipt that caused the recovery.

A failed receipt is never edited or removed. Exhausting the budget is a typed
failure (``RECOVERY_BUDGET_EXHAUSTED``), not a fallback to success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .admission import is_admitted

__all__ = ["RecoveryBudgetExhausted", "RecoveryAttempt", "RecoveryOutcome", "RecoveryController"]

RepairFn = Callable[[Any, Mapping[str, Any]], Any]
ValidateFn = Callable[[Any], Mapping[str, Any]]


class RecoveryBudgetExhausted(RuntimeError):
    """The bounded recovery budget was spent without earning admission."""


@dataclass(frozen=True)
class RecoveryAttempt:
    attempt: int
    artifact_sha256: str
    receipt_sha256: str
    admission: str


@dataclass
class RecoveryOutcome:
    admitted: bool
    attempts: list[RecoveryAttempt] = field(default_factory=list)
    final_receipt: Mapping[str, Any] | None = None
    final_artifact: Any = None
    blocking_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "terminus-xi.recovery-outcome.v1",
            "admitted": self.admitted,
            "budget_used": len(self.attempts),
            "blocking_code": self.blocking_code,
            "attempts": [
                {
                    "attempt": attempt.attempt,
                    "artifact_sha256": attempt.artifact_sha256,
                    "receipt_sha256": attempt.receipt_sha256,
                    "admission": attempt.admission,
                }
                for attempt in self.attempts
            ],
        }


class RecoveryController:
    """Bounded retry around an existing validation path."""

    def __init__(self, budget: int) -> None:
        if budget < 0:
            raise ValueError("recovery budget must be >= 0")
        self.budget = budget

    def run(
        self,
        *,
        artifact: Any,
        failed_receipt: Mapping[str, Any],
        repair: RepairFn,
        validate: ValidateFn,
        ledger: list[Mapping[str, Any]] | None = None,
    ) -> RecoveryOutcome:
        """Attempt bounded recovery. ``validate`` must return a full XI receipt."""
        if is_admitted(failed_receipt.get("admission", "")):
            raise ValueError("recovery invoked on an already-admitted receipt")

        history: list[Mapping[str, Any]] = ledger if ledger is not None else []
        outcome = RecoveryOutcome(admitted=False)
        current_receipt: Mapping[str, Any] = failed_receipt
        current_artifact = artifact

        for attempt in range(1, self.budget + 1):
            current_artifact = repair(current_artifact, current_receipt)
            new_receipt = validate(current_artifact)
            if not isinstance(new_receipt, Mapping) or "receipt_sha256" not in new_receipt:
                raise ValueError(
                    "recovery validate() must return a full XI receipt; a recovered "
                    "artifact cannot be admitted without re-entering validation"
                )
            if new_receipt.get("parent_receipt_sha256") != current_receipt.get("receipt_sha256"):
                raise ValueError(
                    "recovered receipt must link to the receipt that caused recovery "
                    "via parent_receipt_sha256"
                )
            history.append(new_receipt)
            outcome.attempts.append(
                RecoveryAttempt(
                    attempt=attempt,
                    artifact_sha256=new_receipt["artifact_sha256"],
                    receipt_sha256=new_receipt["receipt_sha256"],
                    admission=new_receipt["admission"],
                )
            )
            current_receipt = new_receipt
            if is_admitted(new_receipt["admission"]):
                outcome.admitted = True
                outcome.final_receipt = new_receipt
                outcome.final_artifact = current_artifact
                return outcome

        outcome.final_receipt = current_receipt if outcome.attempts else failed_receipt
        outcome.blocking_code = "RECOVERY_BUDGET_EXHAUSTED"
        return outcome
