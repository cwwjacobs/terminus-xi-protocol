"""The archive boundary, XI determinism end to end, and the XI command line."""

from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from pathlib import Path

import _support  # noqa: F401
from _support import FrozenClock, REPO_ROOT, selftest_artifact  # noqa: E402

from terminus_xi import cli  # noqa: E402
from terminus_xi.canonical import read_json  # noqa: E402

ACTIVE_TREES = ("src", "tools", "tests")
ARCHIVE_IMPORT = re.compile(r"^\s*(?:from|import)\s+\S*\barchive\b", re.MULTILINE)
ARCHIVE_PATH = re.compile(r"""["']archive/""")


def active_python_files() -> list[Path]:
    files: list[Path] = []
    for tree in ACTIVE_TREES:
        for path in sorted((REPO_ROOT / tree).rglob("*.py")):
            if "__pycache__" not in path.parts:
                files.append(path)
    return files


class TestArchiveQuarantine(unittest.TestCase):
    """Archived material is evidence. Active runtime must not depend on it."""

    def test_no_active_module_imports_or_reads_archived_material(self):
        files = active_python_files()
        self.assertGreater(len(files), 15, "quarantine scan found suspiciously few files")
        offenders = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            if ARCHIVE_IMPORT.search(text) or ARCHIVE_PATH.search(text):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [], f"active code touches archive/: {offenders}")

    def test_the_historically_broken_file_is_preserved_unrepaired(self):
        """docs/KNOWN_HISTORICAL_DEFECTS.md records this. It must stay true."""
        import ast

        path = REPO_ROOT / "archive" / "ixc-dataset-curation-stack-c50ad56" / "runtime" / "tool_router.py"
        self.assertTrue(path.exists(), "historical evidence was deleted")
        with self.assertRaises(SyntaxError):
            ast.parse(path.read_text(encoding="utf-8"))

    def test_no_archived_agent_was_promoted_into_the_active_package(self):
        active = {path.name for path in (REPO_ROOT / "src").rglob("*.py")}
        archived = {path.name for path in (REPO_ROOT / "archive").rglob("*.py")}
        self.assertEqual(active & archived, set())


class TestDeterminism(unittest.TestCase):
    def test_same_input_and_contract_gives_the_same_stable_core(self):
        from terminus_xi.engine import verify_artifact

        from _support import selftest_contracts, selftest_policy

        digests = set()
        for stamp in ("2000-01-01T00:00:00Z", "2031-12-31T23:59:59Z", "2026-06-06T06:06:06Z"):
            with FrozenClock(stamp):
                outcome = verify_artifact(
                    selftest_artifact(),
                    boundary_id="xi.selftest",
                    contract_set=selftest_contracts(),
                    policy=selftest_policy(),
                )
            digests.add(outcome.receipt["stable_core_sha256"])
        self.assertEqual(len(digests), 1)


class TestXiCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="xi-cli-"))
        self.contracts = str(REPO_ROOT / "contracts" / "xi-selftest.contracts.json")
        self.policy = str(REPO_ROOT / "policies" / "xi-selftest.policy.json")

    def _artifact(self, value) -> str:
        path = self.tmp / "artifact.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def _run(self, argv):
        buffer = io.StringIO()
        code = cli.main(argv, out=buffer)
        return code, buffer.getvalue()

    def test_admitted_artifact_exits_zero_and_writes_a_receipt(self):
        receipt_path = self.tmp / "receipt.json"
        code, _ = self._run(
            [
                "verify",
                self._artifact(selftest_artifact()),
                "--contracts",
                self.contracts,
                "--boundary",
                "xi.selftest",
                "--policy",
                self.policy,
                "--receipt",
                str(receipt_path),
                "--quiet",
            ]
        )
        self.assertEqual(code, 0)
        receipt = read_json(receipt_path)
        self.assertEqual(receipt["admission"], "ADMIT")

    def test_rejected_artifact_exits_three(self):
        code, _ = self._run(
            [
                "verify",
                self._artifact({"records": [{"id": "a"}]}),
                "--contracts",
                self.contracts,
                "--boundary",
                "xi.selftest",
                "--policy",
                self.policy,
                "--quiet",
            ]
        )
        self.assertEqual(code, cli.EXIT_CODES["REJECT"])

    def test_errored_artifact_exits_four(self):
        code, _ = self._run(
            [
                "verify",
                self._artifact({"kind": "selftest"}),
                "--contracts",
                self.contracts,
                "--boundary",
                "xi.selftest",
                "--policy",
                self.policy,
                "--quiet",
            ]
        )
        self.assertEqual(code, cli.EXIT_CODES["ERROR"])

    def test_a_bad_contract_path_is_a_usage_failure_not_a_pass(self):
        code, _ = self._run(
            [
                "verify",
                self._artifact(selftest_artifact()),
                "--contracts",
                str(self.tmp / "nope.json"),
                "--boundary",
                "xi.selftest",
                "--quiet",
            ]
        )
        self.assertEqual(code, cli.EXIT_USAGE)

    def test_verify_receipt_subcommand_detects_tampering(self):
        receipt_path = self.tmp / "receipt.json"
        self._run(
            [
                "verify",
                self._artifact(selftest_artifact()),
                "--contracts",
                self.contracts,
                "--boundary",
                "xi.selftest",
                "--policy",
                self.policy,
                "--receipt",
                str(receipt_path),
                "--quiet",
            ]
        )
        code, _ = self._run(["verify-receipt", str(receipt_path)])
        self.assertEqual(code, 0)

        receipt = read_json(receipt_path)
        receipt["boundary_id"] = "somewhere.else"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        code, _ = self._run(["verify-receipt", str(receipt_path)])
        self.assertEqual(code, cli.EXIT_CODES["ERROR"])

    def test_codes_and_version_are_machine_readable(self):
        code, output = self._run(["codes", "--json"])
        self.assertEqual(code, 0)
        vocabulary = json.loads(output)
        self.assertTrue(any(item["code"] == "CLAIM_OVERBROAD" for item in vocabulary))

        code, output = self._run(["version"])
        self.assertEqual(code, 0)
        self.assertIn("protocol_version", json.loads(output))

    def test_contracts_subcommand_prints_digests(self):
        code, output = self._run(["contracts", self.contracts])
        self.assertEqual(code, 0)
        self.assertIn("xi.selftest", output)
        self.assertRegex(output, r"sha256=[0-9a-f]{64}")


if __name__ == "__main__":
    unittest.main()
