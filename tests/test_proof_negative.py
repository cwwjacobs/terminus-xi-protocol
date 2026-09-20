"""The fail-closed gates.

Each case is a real demo specification that the engine will happily run. What
it must not do is emit an admitted marketing package from it. These tests assert
the negative directly: no video, no thumbnail, no README, no listing copy, a
non-admitted manifest state, and a verification failure.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import _support  # noqa: F401
from _support import REPO_ROOT  # noqa: E402

from terminus_proof import cli  # noqa: E402
from terminus_proof.engine import build_proof  # noqa: E402
from terminus_proof.package import verify_package, write_package  # noqa: E402
from terminus_proof.spec import load_spec  # noqa: E402

FORBIDDEN_WHEN_NOT_ADMITTED = ("demo.mp4", "thumbnail.png", "README.md", "listing-assets.json")

CASES = {
    "model-parity-break.demo.json": {"MODEL_IDENTITY_MISMATCH", "CONTRADICTION_DETECTED"},
    "config-drift.demo.json": {"CONFIG_DRIFT_UNDECLARED"},
    "unsupported-claim.demo.json": {"CLAIM_UNSUPPORTED"},
    "no-observed-gap.demo.json": {"CLAIM_UNSUPPORTED"},
    "redaction-leak.demo.json": {"SENSITIVE_VALUE_PRESENT"},
}


class TestFailClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out_root = Path(tempfile.mkdtemp(prefix="terminus-proof-negative-"))
        cls.results = {}
        for name in CASES:
            spec = load_spec(REPO_ROOT / "demos" / "negative" / name)
            build = build_proof(spec)
            result = write_package(build, out_root=cls.out_root, render=True)
            cls.results[name] = (build, result)

    def test_every_negative_demo_is_refused(self):
        for name, (build, _) in self.results.items():
            with self.subTest(demo=name):
                self.assertFalse(build.admitted)
                self.assertNotEqual(build.admission, "ADMIT")

    def test_each_case_is_blocked_by_the_expected_typed_codes(self):
        for name, expected in CASES.items():
            build, _ = self.results[name]
            with self.subTest(demo=name):
                blocking = set(build.package.decision.blocking_codes)
                self.assertTrue(
                    expected <= blocking,
                    f"{name}: expected {sorted(expected)} within {sorted(blocking)}",
                )

    def test_no_media_or_marketing_copy_is_produced(self):
        for name, (_, result) in self.results.items():
            for forbidden in FORBIDDEN_WHEN_NOT_ADMITTED:
                with self.subTest(demo=name, file=forbidden):
                    self.assertFalse(
                        (result.directory / forbidden).exists(),
                        f"{name} produced {forbidden} despite not being admitted",
                    )

    def test_the_package_lands_in_a_clearly_non_admitted_location(self):
        for name, (_, result) in self.results.items():
            with self.subTest(demo=name):
                self.assertIn("not-admitted", result.directory.parts)
                self.assertFalse(result.admitted)

    def test_a_diagnostic_record_is_still_emitted(self):
        for name, (_, result) in self.results.items():
            with self.subTest(demo=name):
                self.assertTrue((result.directory / "NOT_ADMITTED.md").exists())
                self.assertTrue((result.directory / "receipt.json").exists())
                self.assertTrue((result.directory / "findings.json").exists())
                text = (result.directory / "NOT_ADMITTED.md").read_text(encoding="utf-8")
                self.assertIn("NOT ADMITTED", text)

    def test_verification_refuses_a_non_admitted_package(self):
        for name, (_, result) in self.results.items():
            with self.subTest(demo=name):
                report = verify_package(result.directory)
                self.assertFalse(report.ok)
                self.assertTrue(
                    any("NOT_ADMITTED" in error for error in report.errors), report.errors
                )

    def test_the_cli_exits_non_zero_for_every_negative_demo(self):
        import contextlib
        import io

        for name in CASES:
            with self.subTest(demo=name):
                buffer = io.StringIO()
                with contextlib.redirect_stderr(io.StringIO()):
                    code = cli.main(
                        [
                            "build",
                            str(REPO_ROOT / "demos" / "negative" / name),
                            "--out",
                            str(self.out_root / "cli"),
                            "--no-media",
                        ],
                        out=buffer,
                    )
                self.assertEqual(code, cli.EXIT_NOT_ADMITTED)


class TestRedactionGateSpecifically(unittest.TestCase):
    """The leak case deserves its own assertions: it is the one that would ship."""

    @classmethod
    def setUpClass(cls):
        spec = load_spec(REPO_ROOT / "demos" / "negative" / "redaction-leak.demo.json")
        cls.build = build_proof(spec)

    def test_the_credential_actually_survived_the_incomplete_policy(self):
        from terminus_proof.redaction import scan_denied

        patterns = self.build.artifact["redaction"]["deny_patterns"]
        hits = scan_denied(self.build.artifact["arms"], patterns)
        self.assertTrue(hits, "the negative fixture no longer leaks; the gate is untested")
        self.assertIn("access-key", {hit["pattern_id"] for hit in hits})

    def test_xi_caught_it_rather_than_the_engine(self):
        redaction_result = next(
            result
            for result in self.build.package.results
            if result.check_id == "proof.redaction.public_safe"
        )
        self.assertEqual(redaction_result.verdict, "FAIL")
        self.assertIn("SENSITIVE_VALUE_PRESENT", redaction_result.codes())

    def test_the_package_is_not_admitted(self):
        self.assertFalse(self.build.admitted)


if __name__ == "__main__":
    unittest.main()
