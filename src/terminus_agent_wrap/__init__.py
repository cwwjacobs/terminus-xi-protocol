"""Thin wrapper that packages one agent-run tool trace for XI admission.

XI is the admission substrate. This package observes a fixture-synthetic run,
writes a durable training-trace directory, and submits the canonical
``run-artifact.json`` to ``terminus_xi.engine.verify_artifact``. XI never
imports this package.

This is not a persona agent, planner, or live tool hook. Pre-tool gating
lives in ``evaluate_tool_proposal`` (ALLOW | HALT). That online halt is not
XI admission; packaged traces still go through ``verify_artifact``.
"""

from __future__ import annotations

from . import checks as _checks  # noqa: F401  (registers wrapper predicates)

BOUNDARY_ID = "agent.run.v1"
RUN_ARTIFACT_SCHEMA = "terminus-agent-wrap.run-artifact.v1"
WRAPPER_ID = "terminus-agent-wrap"
WRAPPER_VERSION = "0.2.0-spike"

from .gate import ALLOW, HALT, evaluate_tool_proposal  # noqa: E402
from .prune import PruneRefused, prune_run_dir  # noqa: E402
from .wrap import WrappedRun, admit_run_artifact, wrap_plan, wrap_run  # noqa: E402

__all__ = [
    "ALLOW",
    "BOUNDARY_ID",
    "HALT",
    "PruneRefused",
    "RUN_ARTIFACT_SCHEMA",
    "WRAPPER_ID",
    "WRAPPER_VERSION",
    "WrappedRun",
    "admit_run_artifact",
    "evaluate_tool_proposal",
    "prune_run_dir",
    "wrap_plan",
    "wrap_run",
]
