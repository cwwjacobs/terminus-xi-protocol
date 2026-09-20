#!/usr/bin/env python3
"""Synthesize the failing fixture trace and wrap it for XI admission.

Run from the repository root:

    PYTHONPATH=src python demos/agent-run-wrap/run.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = Path(__file__).resolve().parent
SRC = REPO_ROOT / "src"
for entry in (str(SRC), str(DEMO_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from fixture import (  # noqa: E402
    synthesize_failing_multi_step_trace,
    synthesize_injected_hostile_plan,
)

from terminus_agent_wrap.wrap import default_scratch_root, wrap_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wrap the fixture-synthetic failing agent-run trace."
    )
    parser.add_argument(
        "--scratch",
        default=None,
        help="scratch root (default: runs/agent-wrap/ or TERMINUS_AGENT_WRAP_SCRATCH)",
    )
    parser.add_argument(
        "--hostile",
        action="store_true",
        help="run the injected-tool fixture through the wrap-side pre-tool gate",
    )
    args = parser.parse_args(argv)

    # Receipt clock only. Event timestamps stay fixture-fixed in fixture.py.
    os.environ.setdefault("TERMINUS_XI_NOW", "2026-09-08T12:00:00Z")

    scratch = Path(args.scratch) if args.scratch else default_scratch_root()
    if args.hostile:
        wrapped = wrap_run(
            plan=synthesize_injected_hostile_plan(),
            scratch_root=scratch,
            agent={
                "id": "demos.agent-run-wrap.injected-hostile",
                "kind": "fixture-synthetic",
                "version": "1",
            },
            config={
                "fixture_id": "injected-hostile-plan-v1",
                "event_timestamps": "fixture-fixed",
                "live_hooks": False,
            },
        )
    else:
        wrapped = wrap_run(
            synthesize_failing_multi_step_trace(),
            scratch_root=scratch,
        )
    summary = {
        "run_id": wrapped.run_id,
        "directory": str(wrapped.directory),
        "admission": wrapped.admission,
        "admitted": wrapped.admitted,
        "halted": wrapped.halted,
        "events_sha256": wrapped.events_sha256,
        "artifact_sha256": wrapped.artifact_sha256,
        "stable_core_sha256": wrapped.receipt["stable_core_sha256"],
        "outcome": wrapped.artifact["outcome"],
        "drive_export_status": wrapped.drive_export.get("status"),
        "files": sorted(path.name for path in wrapped.directory.iterdir()),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if wrapped.admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
