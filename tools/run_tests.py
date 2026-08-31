#!/usr/bin/env python3
"""Run the active test suite and emit a machine-readable report.

The freeze receipt and the UKSL receipt both record a test result. They record
this report, produced by actually running the suite, so that "tests pass" is an
observation rather than a claim.

    python tools/run_tests.py --report receipts/test-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for entry in (REPO_ROOT / "src", REPO_ROOT / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

COMMAND = "python tools/run_tests.py"


def run(pattern: str = "test_*.py", verbosity: int = 1) -> tuple[dict, unittest.TestResult]:
    loader = unittest.TestLoader()
    suite = loader.discover(str(REPO_ROOT / "tests"), pattern=pattern, top_level_dir=str(REPO_ROOT / "tests"))
    if loader.errors:
        for error in loader.errors:
            print(error, file=sys.stderr)
        raise SystemExit(f"test discovery failed with {len(loader.errors)} errors")

    runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stderr)
    result = runner.run(suite)

    report = {
        "command": COMMAND,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "passed": result.wasSuccessful(),
    }
    return report, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Terminus test suite.")
    parser.add_argument("--report", help="write the JSON report to this path")
    parser.add_argument("--pattern", default="test_*.py")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args(argv)

    report, _ = run(pattern=args.pattern, verbosity=1 + args.verbose)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
