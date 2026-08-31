#!/usr/bin/env python3
"""Freeze Terminus XI v1 and write the machine-readable freeze receipt.

The receipt is refused unless the tests passed, the determinism probe was
stable, and the archive quarantine scan is clean. A freeze receipt that records
a broken freeze would be worse than no receipt at all.

    python tools/run_tests.py --report receipts/test-report.json
    python tools/freeze_xi_v1.py --test-report receipts/test-report.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from terminus_xi.canonical import read_json, write_json  # noqa: E402
from terminus_xi.freeze import build_freeze_receipt  # noqa: E402
from terminus_xi.schemas import validate_against  # noqa: E402

DEFAULT_REPORT = REPO_ROOT / "receipts" / "test-report.json"
DEFAULT_OUTPUT = REPO_ROOT / "receipts" / "xi-v1-freeze-receipt.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Terminus XI v1 freeze receipt.")
    parser.add_argument("--test-report", default=str(DEFAULT_REPORT))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--allow-failing-tests",
        action="store_true",
        help="write the receipt even though the suite did not pass (records the failure)",
    )
    args = parser.parse_args(argv)

    report_path = Path(args.test_report)
    if not report_path.exists():
        print(
            f"freeze: no test report at {report_path}. Run tools/run_tests.py first; a freeze "
            "receipt must record an observed test result, not an assumed one.",
            file=sys.stderr,
        )
        return 2
    test_report = read_json(report_path)

    receipt = build_freeze_receipt(test_report=test_report, root=REPO_ROOT)
    validate_against(receipt, "terminus-xi.freeze-receipt.v1", label="freeze receipt")

    problems: list[str] = []
    if not receipt["tests"]["passed"] and not args.allow_failing_tests:
        problems.append(
            f"the test suite did not pass ({receipt['tests']['failures']} failures, "
            f"{receipt['tests']['errors']} errors)"
        )
    if not receipt["determinism_probe"]["stable"]:
        problems.append("the determinism probe produced two different stable cores")
    offenders = receipt["archive_quarantine"]["active_imports_of_archive"]
    if offenders:
        problems.append(f"active runtime references archived material: {offenders}")

    if problems:
        print("freeze refused:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    write_json(args.out, receipt)
    print(f"frozen: {receipt['protocol_version']}")
    print(f"  files            {len(receipt['files'])}")
    print(f"  tree sha256      {receipt['frozen_tree_sha256']}")
    print(f"  issue codes      {len(receipt['issue_codes'])}")
    print(f"  vocabulary sha   {receipt['issue_code_vocabulary_sha256']}")
    print(f"  schemas          {len(receipt['schemas'])}")
    print(f"  registered       {len(receipt['registered_checks'])}")
    print(
        f"  tests            {receipt['tests']['tests_run']} run, "
        f"{receipt['tests']['failures']} failures, {receipt['tests']['errors']} errors"
    )
    print(f"  determinism      stable={receipt['determinism_probe']['stable']}")
    print(f"  quarantine       {receipt['archive_quarantine']['checked_files']} files clean")
    print(f"  receipt          {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
