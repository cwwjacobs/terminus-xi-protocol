"""Admission fails closed, and receipts detect tampering."""

from __future__ import annotations

import copy
import unittest

import _support  # noqa: F401
from _support import (  # noqa: E402
    FrozenClock,
    REPO_ROOT,
    selftest_artifact,
    selftest_contracts,
    selftest_policy,
)

from terminus_xi.admission import (  # noqa: E402
    DEFAULT_POLICY,
    AdmissionPolicy,
    PolicyError,
    decide,
    is_admitted,
    load_policy,
)
from terminus_xi.canonical import sha256_canonical  # noqa: E402
from terminus_xi.engine import verify_artifact  # noqa: E402
from terminus_xi.receipt import stable_core_sha256, verify_receipt  # noqa: E402
from terminus_xi.results import Finding, WatchdogResult  # noqa: E402


def result(check_id: str, verdict: str, *codes: str) -> WatchdogResult:
    severity = {"PASS": "INFO", "WARN": "WARN", "FAIL": "FAIL", "ERROR": "ERROR"}[verdict]
    findings = [Finding(code=code, message=code, severity=severity) for code in codes]
    return WatchdogResult(
        check_id=check_id,
        check_version="1.0.0",
        verdict=verdict,
        input_sha256="0" * 64,
        findings=findings,
    )


class TestAdmission(unittest.TestCase):
    def test_all_pass_is_admitted(self):
        decision = decide([result("a", "PASS")], DEFAULT_POLICY)
        self.assertEqual(decision.admission, "ADMIT")
        self.assertTrue(is_admitted(decision))

    def test_any_fail_rejects_regardless_of_policy(self):
        for on_warn in ("ADMIT", "REVIEW", "REJECT"):
            with self.subTest(on_warn=on_warn):
                policy = AdmissionPolicy("p", "1.0.0", on_warn=on_warn)
                decision = decide([result("a", "PASS"), result("b", "FAIL", "HASH_MISMATCH")], policy)
                self.assertEqual(decision.admission, "REJECT")
                self.assertFalse(is_admitted(decision))
                self.assertIn("HASH_MISMATCH", decision.blocking_codes)

    def test_any_error_is_error_and_outranks_fail(self):
        decision = decide(
            [result("a", "FAIL", "HASH_MISMATCH"), result("b", "ERROR", "CHECK_ERROR")],
            DEFAULT_POLICY,
        )
        self.assertEqual(decision.admission, "ERROR")
        self.assertFalse(is_admitted(decision))

    def test_warn_follows_the_declared_policy(self):
        for on_warn in ("ADMIT", "REVIEW", "REJECT"):
            with self.subTest(on_warn=on_warn):
                policy = AdmissionPolicy("p", "1.0.0", on_warn=on_warn)
                decision = decide([result("a", "WARN", "DRIFT_DETECTED")], policy)
                self.assertEqual(decision.admission, on_warn)

    def test_no_results_at_all_is_a_rejection(self):
        decision = decide([], DEFAULT_POLICY)
        self.assertEqual(decision.admission, "REJECT")
        self.assertEqual(decision.blocking_codes, ("EVIDENCE_MISSING",))

    def test_a_required_check_that_did_not_run_is_a_rejection(self):
        policy = AdmissionPolicy("p", "1.0.0", required_checks=("must_run",))
        decision = decide([result("something_else", "PASS")], policy)
        self.assertEqual(decision.admission, "REJECT")
        self.assertIn("REQUIRED_CHECK_MISSING", decision.blocking_codes)

    def test_is_admitted_accepts_only_the_admit_string(self):
        for value in ("ADMIT",):
            self.assertTrue(is_admitted(value))
        for value in ("REVIEW", "REJECT", "ERROR", "admit", "", "PASS"):
            self.assertFalse(is_admitted(value))

    def test_shipped_policies_load(self):
        for path in sorted((REPO_ROOT / "policies").glob("*.policy.json")):
            with self.subTest(path=path.name):
                self.assertTrue(load_policy(path).policy_id)

    def test_malformed_policy_is_refused(self):
        with self.assertRaises(PolicyError):
            load_policy({"schema": "terminus-xi.admission-policy.v1", "policy_id": "x"})


class TestReceipt(unittest.TestCase):
    def setUp(self):
        with FrozenClock("2026-01-01T00:00:00Z"):
            self.outcome = verify_artifact(
                selftest_artifact(),
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
            )
        self.receipt = self.outcome.receipt

    def test_a_clean_receipt_verifies(self):
        verification = verify_receipt(self.receipt)
        self.assertTrue(verification.ok, verification.errors)
        self.assertEqual(verification.admission, "ADMIT")

    def test_receipt_covers_the_artifact_it_names(self):
        digest = sha256_canonical(selftest_artifact())
        self.assertTrue(verify_receipt(self.receipt, artifact_sha256=digest).ok)
        self.assertFalse(verify_receipt(self.receipt, artifact_sha256="f" * 64).ok)

    def test_editing_any_field_breaks_the_receipt_digest(self):
        tampered = copy.deepcopy(self.receipt)
        tampered["boundary_id"] = "xi.somewhere-else"
        verification = verify_receipt(tampered)
        self.assertFalse(verification.ok)
        self.assertTrue(any("sha256" in error for error in verification.errors))

    def test_a_verdict_that_does_not_follow_from_its_findings_is_caught(self):
        tampered = copy.deepcopy(self.receipt)
        tampered["check_results"][0]["findings"] = [
            {"code": "HASH_MISMATCH", "severity": "FAIL", "message": "planted"}
        ]
        tampered["stable_core_sha256"] = stable_core_sha256(tampered)
        body = {k: v for k, v in tampered.items() if k != "receipt_sha256"}
        tampered["receipt_sha256"] = sha256_canonical(body)
        verification = verify_receipt(tampered)
        self.assertFalse(verification.ok)
        self.assertTrue(any("findings imply" in error for error in verification.errors))

    def test_widening_an_admission_beyond_the_verdicts_is_caught(self):
        with FrozenClock("2026-01-01T00:00:00Z"):
            rejected = verify_artifact(
                {"kind": "selftest"},
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
            ).receipt
        self.assertNotEqual(rejected["admission"], "ADMIT")

        forged = copy.deepcopy(rejected)
        forged["admission"] = "ADMIT"
        forged["stable_core_sha256"] = stable_core_sha256(forged)
        body = {k: v for k, v in forged.items() if k != "receipt_sha256"}
        forged["receipt_sha256"] = sha256_canonical(body)

        verification = verify_receipt(forged)
        self.assertFalse(verification.ok)
        self.assertTrue(any("more permissive" in error for error in verification.errors))

    def test_only_the_timestamp_is_excluded_from_the_stable_core(self):
        with FrozenClock("2000-01-01T00:00:00Z"):
            first = verify_artifact(
                selftest_artifact(),
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
            ).receipt
        with FrozenClock("2031-12-31T23:59:59Z"):
            second = verify_artifact(
                selftest_artifact(),
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
            ).receipt
        self.assertNotEqual(first["created_at_utc"], second["created_at_utc"])
        self.assertNotEqual(first["receipt_sha256"], second["receipt_sha256"])
        self.assertEqual(first["stable_core_sha256"], second["stable_core_sha256"])

    def test_a_different_contract_set_changes_the_stable_core(self):
        contracts = selftest_contracts()
        trimmed = type(contracts)(
            set_id=contracts.set_id,
            version=contracts.version,
            contracts=contracts.contracts[:2],
            description=contracts.description,
        )
        with FrozenClock("2000-01-01T00:00:00Z"):
            other = verify_artifact(
                selftest_artifact(),
                boundary_id="xi.selftest",
                contract_set=trimmed,
                policy=AdmissionPolicy("terminus-xi.selftest", "1.0.0"),
            ).receipt
        self.assertNotEqual(self.receipt["stable_core_sha256"], other["stable_core_sha256"])


class TestFailIsNotPromotable(unittest.TestCase):
    def test_a_failing_artifact_never_reaches_admit(self):
        # 'kind' is absent, so selftest.required_keys FAILs while the other two
        # checks pass: a pure FAIL, with nothing else to blame it on.
        outcome = verify_artifact(
            {"records": [{"id": "a"}]},
            boundary_id="xi.selftest",
            contract_set=selftest_contracts(),
            policy=selftest_policy(),
        )
        verdicts = {r.check_id: r.verdict for r in outcome.results}
        self.assertEqual(verdicts["selftest.required_keys"], "FAIL")
        self.assertEqual(verdicts["selftest.payload_size"], "PASS")
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.admission, "REJECT")
        self.assertIn("EVIDENCE_INCOMPLETE", outcome.decision.blocking_codes)
        self.assertTrue(verify_receipt(outcome.receipt).ok)

    def test_an_admitting_warn_policy_still_cannot_admit_a_fail(self):
        permissive = AdmissionPolicy("permissive", "1.0.0", on_warn="ADMIT")
        outcome = verify_artifact(
            {"records": [{"id": "a"}]},
            boundary_id="xi.selftest",
            contract_set=selftest_contracts(),
            policy=permissive,
        )
        self.assertEqual(outcome.admission, "REJECT")


if __name__ == "__main__":
    unittest.main()
