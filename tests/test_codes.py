"""The frozen issue-code vocabulary and the single audit semantic it encodes."""

from __future__ import annotations

import unittest

import _support  # noqa: F401  (path setup)

from terminus_xi.codes import (  # noqa: E402
    ISSUE_CODES,
    SEVERITIES,
    escalate,
    is_known_code,
    severity_of,
    verdict_from_severities,
    worst_severity,
)

# Codes the downstream contracts, policies, and tests depend on. Adding a code
# is a v1-compatible change; removing one or changing its severity class is not.
LOAD_BEARING = {
    "CHANGED_VARIABLE_ABSENT": "FAIL",
    "CHECK_ERROR": "ERROR",
    "CHECK_NOT_FOUND": "ERROR",
    "CLAIM_OVERBROAD": "FAIL",
    "CLAIM_SCOPE_MISSING": "FAIL",
    "CLAIM_UNSUPPORTED": "FAIL",
    "CONFIG_DRIFT_UNDECLARED": "FAIL",
    "CONTRACT_INVALID": "ERROR",
    "CONTRADICTION_DETECTED": "FAIL",
    "DRIFT_DETECTED": "WARN",
    "EVIDENCE_CITATION_MISSING": "FAIL",
    "EVIDENCE_GAP_UNDECLARED": "FAIL",
    "EVIDENCE_INCOMPLETE": "FAIL",
    "EVIDENCE_MISSING": "FAIL",
    "EVIDENCE_REF_UNRESOLVED": "FAIL",
    "FIXTURE_IDENTITY_MISMATCH": "FAIL",
    "HASH_MISMATCH": "FAIL",
    "INPUT_POINTER_MISSING": "ERROR",
    "INPUT_SHAPE_INVALID": "FAIL",
    "LIMITATIONS_ABSENT": "FAIL",
    "MEASUREMENT": "INFO",
    "MODEL_IDENTITY_MISMATCH": "FAIL",
    "PAYLOAD_LARGE": "WARN",
    "PAYLOAD_SIZE_UNKNOWN": "ERROR",
    "RECOVERY_BUDGET_EXHAUSTED": "FAIL",
    "RECOVERY_NOT_REVALIDATED": "FAIL",
    "REDACTION_POLICY_VIOLATION": "FAIL",
    "REQUIRED_CHECK_MISSING": "FAIL",
    "SCHEMA_VIOLATION": "FAIL",
    "SENSITIVE_VALUE_PRESENT": "FAIL",
    "TOOL_SURFACE_MISMATCH": "FAIL",
}


class TestVocabulary(unittest.TestCase):
    def test_load_bearing_codes_are_stable(self):
        for code, severity in sorted(LOAD_BEARING.items()):
            with self.subTest(code=code):
                self.assertTrue(is_known_code(code), f"{code} left the vocabulary")
                self.assertEqual(severity_of(code), severity)

    def test_every_code_has_one_severity_from_the_frozen_set(self):
        for code, entry in ISSUE_CODES.items():
            with self.subTest(code=code):
                self.assertEqual(entry.code, code)
                self.assertIn(entry.severity, SEVERITIES)
                self.assertTrue(entry.description.strip())
                self.assertTrue(entry.category.strip())

    def test_code_names_are_machine_stable_shapes(self):
        for code in ISSUE_CODES:
            with self.subTest(code=code):
                self.assertRegex(code, r"^[A-Z][A-Z0-9_]*$")

    def test_unknown_code_raises_rather_than_defaulting(self):
        self.assertFalse(is_known_code("PROBABLY_FINE"))
        with self.assertRaises(KeyError):
            severity_of("PROBABLY_FINE")


class TestSeverityAlgebra(unittest.TestCase):
    def test_verdict_is_the_worst_severity_present(self):
        self.assertEqual(verdict_from_severities([]), "PASS")
        self.assertEqual(verdict_from_severities(["INFO"]), "PASS")
        self.assertEqual(verdict_from_severities(["INFO", "WARN"]), "WARN")
        self.assertEqual(verdict_from_severities(["WARN", "FAIL"]), "FAIL")
        self.assertEqual(verdict_from_severities(["FAIL", "ERROR"]), "ERROR")

    def test_unknown_severity_is_refused(self):
        with self.assertRaises(ValueError):
            worst_severity(["SORT_OF_BAD"])

    def test_warn_may_escalate_to_fail(self):
        self.assertEqual(escalate("PAYLOAD_LARGE", ()), "WARN")
        self.assertEqual(escalate("PAYLOAD_LARGE", ["PAYLOAD_LARGE"]), "FAIL")

    def test_fail_and_error_never_de_escalate(self):
        self.assertEqual(escalate("HASH_MISMATCH", ["HASH_MISMATCH"]), "FAIL")
        self.assertEqual(escalate("CHECK_ERROR", ["CHECK_ERROR"]), "ERROR")
        self.assertEqual(escalate("MEASUREMENT", ["MEASUREMENT"]), "INFO")


if __name__ == "__main__":
    unittest.main()
