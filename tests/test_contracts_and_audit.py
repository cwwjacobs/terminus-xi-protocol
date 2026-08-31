"""Contract loading and the one audit path, including its failure modes."""

from __future__ import annotations

import copy
import unittest

import _support  # noqa: F401
from _support import REPO_ROOT, selftest_artifact, selftest_contracts  # noqa: E402

from terminus_xi import checks as check_registry  # noqa: E402
from terminus_xi.audit import run_check, run_contract_set  # noqa: E402
from terminus_xi.contracts import ContractError, load_contract, load_contract_set  # noqa: E402
from terminus_xi.results import finding  # noqa: E402

V2 = {
    "schema": "terminus-xi.check-contract.v2",
    "check_id": "unit.example",
    "version": "1.0.0",
    "deterministic": True,
    "implementation": "xi.not_empty.v1",
    "input_contract": "the artifact",
    "input_pointers": {"artifact": ""},
    "pass_condition": "the artifact is non-empty",
    "failure_codes": ["EVIDENCE_MISSING"],
}

V1 = {
    "schema": "terminus-xi.check-contract.v1",
    "check_id": "xi.not_empty.v1",
    "version": "1.0.0",
    "deterministic": True,
    "input_contract": "the artifact",
    "pass_condition": "the artifact is non-empty",
    "failure_codes": ["EVIDENCE_MISSING"],
}


class TestContractLoading(unittest.TestCase):
    def test_v2_round_trips_through_its_canonical_form(self):
        contract = load_contract(V2)
        self.assertEqual(contract.implementation, "xi.not_empty.v1")
        reloaded = load_contract(contract.to_dict())
        self.assertEqual(reloaded.sha256(), contract.sha256())

    def test_v1_is_upgraded_losslessly_in_memory(self):
        contract = load_contract(V1)
        self.assertEqual(contract.source_schema, "terminus-xi.check-contract.v1")
        self.assertEqual(contract.implementation, "xi.not_empty.v1")
        self.assertEqual(dict(contract.input_pointers), {"artifact": ""})
        self.assertEqual(dict(contract.config), {})

    def test_non_deterministic_contract_is_refused(self):
        document = copy.deepcopy(V2)
        document["deterministic"] = False
        with self.assertRaises(ContractError):
            load_contract(document)

    def test_code_outside_the_frozen_vocabulary_is_refused(self):
        document = copy.deepcopy(V2)
        document["failure_codes"] = ["SEEMS_BAD"]
        with self.assertRaises(ContractError) as ctx:
            load_contract(document)
        self.assertIn("frozen XI v1 issue-code vocabulary", str(ctx.exception))

    def test_only_warn_codes_may_be_escalated(self):
        document = copy.deepcopy(V2)
        document["escalate_codes"] = ["HASH_MISMATCH"]
        with self.assertRaises(ContractError) as ctx:
            load_contract(document)
        self.assertIn("only WARN codes may be escalated", str(ctx.exception))

    def test_unknown_schema_is_refused(self):
        document = copy.deepcopy(V2)
        document["schema"] = "terminus-xi.check-contract.v9"
        with self.assertRaises(ContractError):
            load_contract(document)

    def test_duplicate_check_ids_in_a_set_are_refused(self):
        document = {
            "schema": "terminus-xi.check-contract-set.v1",
            "set_id": "dup",
            "version": "1.0.0",
            "contracts": [copy.deepcopy(V2), copy.deepcopy(V2)],
        }
        with self.assertRaises(ContractError) as ctx:
            load_contract_set(document)
        self.assertIn("duplicate check_id", str(ctx.exception))

    def test_shipped_contract_sets_all_load(self):
        for path in sorted((REPO_ROOT / "contracts").glob("*.json")):
            with self.subTest(path=path.name):
                contract_set = load_contract_set(path)
                self.assertTrue(contract_set.contracts)


class TestAuditFailureModes(unittest.TestCase):
    """Every way a check can fail to establish something is typed, not silent."""

    def test_missing_pointer_is_an_error_not_a_pass(self):
        document = copy.deepcopy(V2)
        document["input_pointers"] = {"missing": "/nowhere"}
        result = run_check(load_contract(document), {"present": 1})
        self.assertEqual(result.verdict, "ERROR")
        self.assertEqual(result.codes(), ["INPUT_POINTER_MISSING"])

    def test_unregistered_implementation_is_an_error(self):
        document = copy.deepcopy(V2)
        document["implementation"] = "xi.does_not_exist.v1"
        result = run_check(load_contract(document), {"a": 1})
        self.assertEqual(result.verdict, "ERROR")
        self.assertEqual(result.codes(), ["CHECK_NOT_FOUND"])

    def test_a_raising_check_is_contained_as_an_error(self):
        def boom(inputs, config):
            raise RuntimeError("checker exploded")

        document = copy.deepcopy(V2)
        document["implementation"] = "test.boom.v1"
        with check_registry.temporary("test.boom.v1", boom):
            result = run_check(load_contract(document), {"a": 1})
        self.assertEqual(result.verdict, "ERROR")
        self.assertEqual(result.codes(), ["CHECK_ERROR"])
        self.assertIn("checker exploded", result.findings[0].message)
        self.assertFalse(check_registry.is_registered("test.boom.v1"))

    def test_a_check_inventing_a_code_invalidates_the_contract(self):
        def rogue(inputs, config):
            return [finding("TOTALLY_FINE", "trust me")]

        document = copy.deepcopy(V2)
        document["implementation"] = "test.rogue.v1"
        with check_registry.temporary("test.rogue.v1", rogue):
            result = run_check(load_contract(document), {"a": 1})
        self.assertEqual(result.verdict, "ERROR")
        self.assertEqual(result.codes(), ["CONTRACT_INVALID"])

    def test_input_identity_covers_only_what_the_check_consumed(self):
        contract = load_contract(
            {**V2, "input_pointers": {"records": "/records"}, "implementation": "xi.not_empty.v1"}
        )
        first = run_check(contract, {"records": [1, 2], "ignored": "a"})
        second = run_check(contract, {"records": [1, 2], "ignored": "b"})
        self.assertEqual(first.input_sha256, second.input_sha256)

        third = run_check(contract, {"records": [1, 3], "ignored": "a"})
        self.assertNotEqual(first.input_sha256, third.input_sha256)


class TestSelftestSet(unittest.TestCase):
    def test_a_builtin_cannot_be_silently_replaced(self):
        with self.assertRaises(ValueError):
            check_registry.temporary("xi.not_empty.v1", lambda i, c: []).__enter__()
        with self.assertRaises(ValueError):
            check_registry.unregister("xi.not_empty.v1")

    def test_selftest_set_passes_on_its_artifact(self):
        results = run_contract_set(selftest_contracts(), selftest_artifact())
        self.assertEqual([r.verdict for r in results], ["PASS", "PASS", "PASS"])

    def test_selftest_set_fails_loudly_on_a_broken_artifact(self):
        results = run_contract_set(selftest_contracts(), {"kind": "selftest"})
        verdicts = {r.check_id: r.verdict for r in results}
        self.assertEqual(verdicts["selftest.required_keys"], "FAIL")
        self.assertEqual(verdicts["selftest.payload_size"], "ERROR")


if __name__ == "__main__":
    unittest.main()
