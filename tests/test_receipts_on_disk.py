"""The receipts committed to the tree must stay honest documents.

These tests deliberately do not compare file digests against the freeze
receipt: the suite runs *before* the freeze step, so a digest comparison would
be testing the previous freeze against the current tree. What they do check is
that the receipts are well formed, that they cover the files that exist now, and
that neither one records a closure it did not establish.
"""

from __future__ import annotations

import unittest

import _support  # noqa: F401
from _support import REPO_ROOT  # noqa: E402

import terminus_proof  # noqa: E402,F401  (registers the proof schema ids)
from terminus_xi.canonical import read_json  # noqa: E402
from terminus_xi.freeze import frozen_files  # noqa: E402
from terminus_xi.schemas import validate_against  # noqa: E402

FREEZE = REPO_ROOT / "receipts" / "xi-v1-freeze-receipt.json"
UKSL = REPO_ROOT / "receipts" / "uksl-receipt.json"


@unittest.skipUnless(FREEZE.exists(), "freeze receipt has not been produced yet")
class TestFreezeReceipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = read_json(FREEZE)

    def test_it_validates_against_its_own_schema(self):
        validate_against(self.receipt, "terminus-xi.freeze-receipt.v1")

    def test_every_frozen_file_still_exists(self):
        for entry in self.receipt["files"]:
            with self.subTest(path=entry["path"]):
                self.assertTrue((REPO_ROOT / entry["path"]).exists())

    def test_it_covers_exactly_the_current_xi_v1_boundary(self):
        recorded = {entry["path"] for entry in self.receipt["files"]}
        current = {entry["path"] for entry in frozen_files(REPO_ROOT)}
        self.assertEqual(recorded, current, "the freeze receipt is stale; re-run the freeze")

    def test_it_does_not_record_a_broken_freeze(self):
        self.assertTrue(self.receipt["determinism_probe"]["stable"])
        self.assertEqual(self.receipt["archive_quarantine"]["active_imports_of_archive"], [])
        self.assertTrue(self.receipt["tests"]["passed"])

    def test_the_frozen_boundary_excludes_the_proof_engine(self):
        recorded = {entry["path"] for entry in self.receipt["files"]}
        self.assertFalse(
            any(path.startswith("src/terminus_proof") for path in recorded),
            "KSL-02 code leaked into the XI v1 freeze boundary",
        )
        self.assertFalse(
            any("proof" in path for path in recorded if path.startswith("spec/")),
            "KSL-02 schemas leaked into the XI v1 freeze boundary",
        )

    def test_it_records_its_limitations(self):
        self.assertGreaterEqual(len(self.receipt["known_limitations"]), 5)


@unittest.skipUnless(UKSL.exists(), "UKSL receipt has not been produced yet")
class TestUkslReceipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = read_json(UKSL)

    def test_it_validates_against_its_own_schema(self):
        validate_against(self.receipt, "terminus.uksl-receipt.v1")

    def test_closure_agrees_with_the_clauses_it_records(self):
        unsatisfied = [
            entry["clause"]
            for block in self.receipt["ksl"]
            for entry in block["exit_gate"]
            if not entry["satisfied"]
        ]
        self.assertEqual(sorted(unsatisfied), sorted(
            clause.split(": ", 1)[1] for clause in self.receipt["unresolved_clauses"]
        ))
        self.assertEqual(self.receipt["closed"], not unsatisfied)
        for block in self.receipt["ksl"]:
            with self.subTest(ksl=block["ksl_id"]):
                self.assertEqual(
                    block["closed"], all(e["satisfied"] for e in block["exit_gate"])
                )

    def test_every_unsatisfied_clause_carries_a_blocker(self):
        for block in self.receipt["ksl"]:
            for entry in block["exit_gate"]:
                if not entry["satisfied"]:
                    with self.subTest(clause=entry["clause"]):
                        self.assertTrue(entry["blocker"])

    def test_both_ksl_blocks_are_present(self):
        self.assertEqual(
            [block["ksl_id"] for block in self.receipt["ksl"]], ["KSL-01", "KSL-02"]
        )


if __name__ == "__main__":
    unittest.main()
