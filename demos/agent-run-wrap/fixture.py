"""Fixture-synthetic failing multi-step tool trace.

Event timestamps are fixture-fixed (a constant epoch plus seq seconds), not a
wall-clock read and not ``TERMINUS_XI_NOW``. Receipt ``created_at_utc`` still
follows XI's clock / ``TERMINUS_XI_NOW``.

The single ``kind: decision`` line is canned. It is not produced by a model or
a live tool surface.

The injected hostile plan is a fixture-supplied call list. It is not a
planner output. Raw args stay in this module; events only get digests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from terminus_agent_wrap.events import make_event

# Fixture-fixed origin. Independent of the receipt clock.
FIXTURE_T0 = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

# The spike's only decision event. Do not replace with a live hook.
CANNED_DECISION_NAME = "fixture.synthetic.halt_after_tool_error"
CANNED_DECISION_STATUS = "stop"


def fixture_ts(seq: int) -> str:
    """Deterministic timestamp from seq. Not ``datetime.now``."""
    return (FIXTURE_T0 + timedelta(seconds=seq - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def synthesize_failing_multi_step_trace() -> list[dict[str, Any]]:
    """Short failing tool trace: search succeeds, fetch errors, canned halt."""
    return [
        make_event(
            seq=1,
            ts_utc=fixture_ts(1),
            kind="run_start",
            name="fixture.failing_multi_step",
            status="started",
        ),
        make_event(
            seq=2,
            ts_utc=fixture_ts(2),
            kind="tool_call",
            name="search",
            status="ok",
            args={"query": "terminus xi verify_artifact"},
        ),
        make_event(
            seq=3,
            ts_utc=fixture_ts(3),
            kind="tool_result",
            name="search",
            status="ok",
            result={"hits": 1, "ok": True},
        ),
        make_event(
            seq=4,
            ts_utc=fixture_ts(4),
            kind="tool_call",
            name="fetch",
            status="ok",
            args={"url": "https://example.invalid/missing"},
        ),
        make_event(
            seq=5,
            ts_utc=fixture_ts(5),
            kind="tool_result",
            name="fetch",
            status="error",
            codes=["not_found"],
            result={"error": "not_found"},
        ),
        make_event(
            seq=6,
            ts_utc=fixture_ts(6),
            kind="error",
            name="fetch",
            status="error",
            codes=["not_found"],
        ),
        make_event(
            seq=7,
            ts_utc=fixture_ts(7),
            kind="decision",
            name=CANNED_DECISION_NAME,
            status=CANNED_DECISION_STATUS,
            codes=["fixture_synthetic"],
        ),
        make_event(
            seq=8,
            ts_utc=fixture_ts(8),
            kind="run_end",
            name="fixture.failing_multi_step",
            status="failed",
        ),
    ]


HOSTILE_TOOL_NAME = "injected.exec"
HOSTILE_RAW_ARGS = {"command": "rm -rf /workspace/xi-traces", "injected": True}
HOSTILE_ARGS_REDACTED = {"command": "<redacted>"}


def synthesize_injected_hostile_plan() -> list[dict[str, object]]:
    """One would-be harmful tool call. Used by the wrap-side pre-tool gate."""
    return [
        {
            "name": HOSTILE_TOOL_NAME,
            "args": dict(HOSTILE_RAW_ARGS),
            "args_redacted": dict(HOSTILE_ARGS_REDACTED),
        }
    ]
