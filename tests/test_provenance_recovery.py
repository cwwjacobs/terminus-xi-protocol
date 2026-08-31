"""Deterministic provenance, and bounded recovery that cannot launder a failure."""

from __future__ import annotations

import unittest

import _support  # noqa: F401
from _support import FrozenClock, selftest_artifact, selftest_contracts, selftest_policy  # noqa: E402

from terminus_xi.canonical import sha256_canonical  # noqa: E402
from terminus_xi.engine import verify_artifact  # noqa: E402
from terminus_xi.provenance import build_provenance  # noqa: E402
from terminus_xi.recovery import RecoveryController  # noqa: E402
from terminus_xi.schemas import validate_against  # noqa: E402


class TestProvenance(unittest.TestCase):
    def test_run_id_is_derived_not_random(self):
        first = build_provenance(boundary_id="b", artifact={"a": 1})
        second = build_provenance(boundary_id="b", artifact={"a": 1})
        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(first.sha256(), second.sha256())

    def test_a_different_artifact_gets_a_different_run_id(self):
        first = build_provenance(boundary_id="b", artifact={"a": 1})
        second = build_provenance(boundary_id="b", artifact={"a": 2})
        self.assertNotEqual(first.run_id, second.run_id)

    def test_provenance_carries_no_clock_reading(self):
        with FrozenClock("2000-01-01T00:00:00Z"):
            first = build_provenance(boundary_id="b", artifact={"a": 1}).sha256()
        with FrozenClock("2031-12-31T23:59:59Z"):
            second = build_provenance(boundary_id="b", artifact={"a": 1}).sha256()
        self.assertEqual(first, second)

    def test_full_envelope_validates(self):
        provenance = build_provenance(
            boundary_id="proof.package",
            artifact={"a": 1},
            job_id="job-1",
            model={"provider": "p", "model_id": "m", "params_sha256": "0" * 64},
            fixture={"fixture_id": "f", "sha256": "1" * 64},
            tool_surface={"tools": ["t"], "sha256": "2" * 64},
            capability={"capability_id": "c", "version": "1.0.0", "sha256": None, "source": None},
            inputs=[{"ref": "x.json", "sha256": "3" * 64, "role": "fixture"}],
            notes=["note"],
        )
        validate_against(provenance.to_dict(), "terminus-xi.provenance.v1")

    def test_byte_artifacts_require_an_explicit_digest(self):
        with self.assertRaises(ValueError):
            build_provenance(boundary_id="b", artifact=None, artifact_kind="bytes")


class TestRecovery(unittest.TestCase):
    def _validate(self, parent: str | None):
        def run(artifact):
            return verify_artifact(
                artifact,
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
                parent_receipt_sha256=parent,
            ).receipt

        return run

    def setUp(self):
        self.broken = {"records": [{"id": "a"}]}  # 'kind' missing -> FAIL
        self.failed = verify_artifact(
            self.broken,
            boundary_id="xi.selftest",
            contract_set=selftest_contracts(),
            policy=selftest_policy(),
        ).receipt
        self.assertEqual(self.failed["admission"], "REJECT")

    def test_a_successful_repair_must_re_enter_validation(self):
        ledger: list = []
        controller = RecoveryController(budget=2)

        def repair(artifact, receipt):
            return selftest_artifact()

        state = {"parent": self.failed["receipt_sha256"]}

        def validate(artifact):
            receipt = verify_artifact(
                artifact,
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
                parent_receipt_sha256=state["parent"],
            ).receipt
            state["parent"] = receipt["receipt_sha256"]
            return receipt

        outcome = controller.run(
            artifact=self.broken,
            failed_receipt=self.failed,
            repair=repair,
            validate=validate,
            ledger=ledger,
        )
        self.assertTrue(outcome.admitted)
        self.assertEqual(len(outcome.attempts), 1)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(
            ledger[0]["parent_receipt_sha256"], self.failed["receipt_sha256"]
        )

    def test_the_failed_receipt_is_never_edited_or_removed(self):
        before = sha256_canonical(self.failed)
        controller = RecoveryController(budget=1)
        state = {"parent": self.failed["receipt_sha256"]}

        def validate(artifact):
            receipt = verify_artifact(
                artifact,
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
                parent_receipt_sha256=state["parent"],
            ).receipt
            state["parent"] = receipt["receipt_sha256"]
            return receipt

        controller.run(
            artifact=self.broken,
            failed_receipt=self.failed,
            repair=lambda artifact, receipt: selftest_artifact(),
            validate=validate,
        )
        self.assertEqual(sha256_canonical(self.failed), before)

    def test_an_exhausted_budget_is_a_typed_failure_not_a_pass(self):
        controller = RecoveryController(budget=2)
        state = {"parent": self.failed["receipt_sha256"]}

        def validate(artifact):
            receipt = verify_artifact(
                artifact,
                boundary_id="xi.selftest",
                contract_set=selftest_contracts(),
                policy=selftest_policy(),
                parent_receipt_sha256=state["parent"],
            ).receipt
            state["parent"] = receipt["receipt_sha256"]
            return receipt

        outcome = controller.run(
            artifact=self.broken,
            failed_receipt=self.failed,
            repair=lambda artifact, receipt: artifact,  # repairs nothing
            validate=validate,
        )
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.blocking_code, "RECOVERY_BUDGET_EXHAUSTED")
        self.assertEqual(len(outcome.attempts), 2)

    def test_a_zero_budget_attempts_nothing(self):
        outcome = RecoveryController(budget=0).run(
            artifact=self.broken,
            failed_receipt=self.failed,
            repair=lambda artifact, receipt: selftest_artifact(),
            validate=self._validate(None),
        )
        self.assertFalse(outcome.admitted)
        self.assertEqual(outcome.attempts, [])
        self.assertEqual(outcome.blocking_code, "RECOVERY_BUDGET_EXHAUSTED")

    def test_a_repair_that_skips_validation_is_refused(self):
        controller = RecoveryController(budget=1)
        with self.assertRaises(ValueError) as ctx:
            controller.run(
                artifact=self.broken,
                failed_receipt=self.failed,
                repair=lambda artifact, receipt: selftest_artifact(),
                validate=lambda artifact: {"admission": "ADMIT"},  # not a receipt
            )
        self.assertIn("re-entering validation", str(ctx.exception))

    def test_a_recovered_receipt_must_link_to_the_failure(self):
        controller = RecoveryController(budget=1)
        with self.assertRaises(ValueError) as ctx:
            controller.run(
                artifact=self.broken,
                failed_receipt=self.failed,
                repair=lambda artifact, receipt: selftest_artifact(),
                validate=self._validate(None),  # no parent link
            )
        self.assertIn("parent_receipt_sha256", str(ctx.exception))

    def test_recovery_cannot_be_invoked_on_an_admitted_receipt(self):
        admitted = verify_artifact(
            selftest_artifact(),
            boundary_id="xi.selftest",
            contract_set=selftest_contracts(),
            policy=selftest_policy(),
        ).receipt
        with self.assertRaises(ValueError):
            RecoveryController(budget=1).run(
                artifact=selftest_artifact(),
                failed_receipt=admitted,
                repair=lambda artifact, receipt: artifact,
                validate=self._validate(None),
            )

    def test_a_negative_budget_is_refused(self):
        with self.assertRaises(ValueError):
            RecoveryController(budget=-1)


if __name__ == "__main__":
    unittest.main()
