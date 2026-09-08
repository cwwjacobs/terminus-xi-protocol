"""Canonical ``terminus-agent-wrap.run-artifact.v1`` builder.

``run_id`` is derived from covered digests. No random identifier is used.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from terminus_xi.canonical import sha256_canonical

from . import BOUNDARY_ID, RUN_ARTIFACT_SCHEMA
from .events import events_sha256, normalize_events

__all__ = [
    "DEFAULT_AGENT",
    "DEFAULT_CLAIM",
    "DEFAULT_CONFIG",
    "DEFAULT_TOOL_SURFACE",
    "build_run_artifact",
    "derive_outcome",
    "derive_run_id",
]

DEFAULT_AGENT: dict[str, Any] = {
    "id": "demos.agent-run-wrap.failing-trace",
    "kind": "fixture-synthetic",
    "version": "1",
}

DEFAULT_TOOL_SURFACE: dict[str, Any] = {
    "id": "fixture.tools.v1",
    "tools": ["search", "fetch"],
}

DEFAULT_CONFIG: dict[str, Any] = {
    "fixture_id": "failing-multi-step-v1",
    "event_timestamps": "fixture-fixed",
    "live_hooks": False,
}

DEFAULT_CLAIM: dict[str, Any] = {
    "statement": "This package records one fixture-synthetic tool trace for admission.",
    "bound": "fixture demo only; not a live agent run and not a certification of agent quality",
}


def derive_run_id(
    *,
    boundary_id: str,
    events_digest: str,
    agent: Mapping[str, Any],
    tool_surface: Mapping[str, Any],
    config: Mapping[str, Any],
) -> str:
    seed = {
        "agent": dict(agent),
        "boundary_id": boundary_id,
        "config": dict(config),
        "events_sha256": events_digest,
        "tool_surface": dict(tool_surface),
    }
    return "run_" + sha256_canonical(seed)[:24]


def derive_outcome(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failed = any(
        event.get("kind") == "error" or event.get("status") == "error" for event in events
    )
    return {
        "status": "failed" if failed else "succeeded",
        "terminal_kind": events[-1]["kind"] if events else None,
    }


def build_run_artifact(
    events: Sequence[Mapping[str, Any]],
    *,
    boundary_id: str = BOUNDARY_ID,
    agent: Mapping[str, Any] | None = None,
    tool_surface: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
    outcome: Mapping[str, Any] | None = None,
    claim: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the canonical admission object. Does not call XI."""
    normalized = normalize_events(events)
    resolved_agent = dict(agent or DEFAULT_AGENT)
    resolved_surface = dict(tool_surface or DEFAULT_TOOL_SURFACE)
    resolved_config = dict(config or DEFAULT_CONFIG)
    digest = events_sha256(normalized)
    run_id = derive_run_id(
        boundary_id=boundary_id,
        events_digest=digest,
        agent=resolved_agent,
        tool_surface=resolved_surface,
        config=resolved_config,
    )
    return {
        "schema": RUN_ARTIFACT_SCHEMA,
        "boundary_id": boundary_id,
        "run_id": run_id,
        "agent": resolved_agent,
        "tool_surface": resolved_surface,
        "config": resolved_config,
        "events_sha256": digest,
        "event_count": len(normalized),
        "events": normalized,
        "outcome": dict(outcome) if outcome is not None else derive_outcome(normalized),
        "claim": dict(claim) if claim is not None else dict(DEFAULT_CLAIM),
    }
