"""Fixture plan runner: evaluate each proposal, execute only on ALLOW.

This is not a planner. The sequence of calls is supplied by the fixture.
On HALT, no remaining tool runs and no tool side-effect is recorded.

``gate_disabled`` is test-only. Production ``wrap_run`` / demo must leave it
false so the kill-switch is on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, MutableSequence, Sequence

from .events import make_event
from .gate import HALT, HALT_CODE, SealedToolPolicy, evaluate_tool_proposal

__all__ = [
    "HOSTILE_TOOL_NAME",
    "PlannedCall",
    "PlanExecution",
    "TOOL_GATE_NAME",
    "execute_plan",
]

HOSTILE_TOOL_NAME = "injected.exec"
TOOL_GATE_NAME = "tool_gate"
PLAN_T0 = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

ToolImpl = Callable[["PlannedCall", MutableSequence[dict[str, Any]]], Mapping[str, Any]]


@dataclass(frozen=True)
class PlannedCall:
    """One fixture-supplied tool proposal. Not produced by a model."""

    name: str
    args: Mapping[str, Any] | None = None
    args_redacted: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PlanExecution:
    events: tuple[Mapping[str, Any], ...]
    side_effects: tuple[Mapping[str, Any], ...]
    halted: bool


def plan_ts(seq: int) -> str:
    """Fixture-fixed timestamp. Not a wall-clock read."""
    return (PLAN_T0 + timedelta(seconds=seq - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _search(call: PlannedCall, journal: MutableSequence[dict[str, Any]]) -> dict[str, Any]:
    del call
    journal.append({"name": "search", "harm": False})
    return {"hits": 1, "ok": True}


def _fetch(call: PlannedCall, journal: MutableSequence[dict[str, Any]]) -> dict[str, Any]:
    del call
    journal.append({"name": "fetch", "harm": False})
    return {"ok": True}


def _hostile_exec(call: PlannedCall, journal: MutableSequence[dict[str, Any]]) -> dict[str, Any]:
    journal.append({"name": call.name, "harm": True})
    return {"ok": True, "effect": "would_run"}


def _unregistered(call: PlannedCall, journal: MutableSequence[dict[str, Any]]) -> dict[str, Any]:
    journal.append({"name": call.name, "harm": True})
    return {"ok": True, "effect": "would_run"}


DEFAULT_TOOLS: dict[str, ToolImpl] = {
    "search": _search,
    "fetch": _fetch,
    HOSTILE_TOOL_NAME: _hostile_exec,
}


def _as_call(item: PlannedCall | Mapping[str, Any]) -> PlannedCall:
    if isinstance(item, PlannedCall):
        return item
    name = item.get("name")
    if not isinstance(name, str):
        name = ""
    args = item.get("args")
    redacted = item.get("args_redacted")
    return PlannedCall(
        name=name,
        args=args if isinstance(args, Mapping) else None,
        args_redacted=redacted if isinstance(redacted, Mapping) else None,
    )


def execute_plan(
    proposals: Sequence[PlannedCall | Mapping[str, Any]],
    *,
    gate_disabled: bool = False,
    policy: SealedToolPolicy | None = None,
    tools: Mapping[str, ToolImpl] | None = None,
    run_name: str = "fixture.gated_plan",
) -> PlanExecution:
    """Run a fixture-supplied call list. HALT stops before the blocked tool."""
    registry = dict(DEFAULT_TOOLS if tools is None else tools)
    journal: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seq = 1
    events.append(
        make_event(
            seq=seq,
            ts_utc=plan_ts(seq),
            kind="run_start",
            name=run_name,
            status="started",
        )
    )

    for item in proposals:
        call = _as_call(item)
        if not gate_disabled:
            verdict = evaluate_tool_proposal(
                call.name,
                args_redacted=call.args_redacted,
                policy=policy,
            )
            if verdict == HALT:
                seq += 1
                events.append(
                    make_event(
                        seq=seq,
                        ts_utc=plan_ts(seq),
                        kind="error",
                        name=TOOL_GATE_NAME,
                        status="halted",
                        codes=[HALT_CODE],
                    )
                )
                seq += 1
                events.append(
                    make_event(
                        seq=seq,
                        ts_utc=plan_ts(seq),
                        kind="run_end",
                        name=run_name,
                        status="halted",
                    )
                )
                return PlanExecution(
                    events=tuple(events),
                    side_effects=tuple(journal),
                    halted=True,
                )

        seq += 1
        events.append(
            make_event(
                seq=seq,
                ts_utc=plan_ts(seq),
                kind="tool_call",
                name=call.name,
                status="ok",
                args=call.args,
            )
        )
        impl = registry.get(call.name, _unregistered)
        result = impl(call, journal)
        seq += 1
        events.append(
            make_event(
                seq=seq,
                ts_utc=plan_ts(seq),
                kind="tool_result",
                name=call.name,
                status="ok",
                result=result,
            )
        )

    seq += 1
    events.append(
        make_event(
            seq=seq,
            ts_utc=plan_ts(seq),
            kind="run_end",
            name=run_name,
            status="succeeded",
        )
    )
    return PlanExecution(
        events=tuple(events),
        side_effects=tuple(journal),
        halted=False,
    )
