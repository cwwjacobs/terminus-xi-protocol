"""The domain checks, exercised directly on their declared inputs."""

from __future__ import annotations

import unittest

import _support  # noqa: F401

from terminus_proof.checks import (  # noqa: E402
    arm_binding,
    claim_citations,
    claim_limitations,
    claim_overbroad,
    claim_scope,
    claim_supported,
    evidence_complete,
    parity_config,
    parity_identity,
    redaction_public_safe,
    spec_faithful,
)
from terminus_xi.canonical import sha256_canonical  # noqa: E402
from terminus_xi.checks import is_registered  # noqa: E402


def codes(findings):
    return sorted({f.code for f in findings})


SCOPE = {"asset_scope": "42 hosts", "time_window": "2026-08", "surface": "scan"}
LEXICON = {"lexicon": ["fully secure", "no vulnerabilities"]}


class TestRegistration(unittest.TestCase):
    def test_every_domain_check_is_registered_with_xi(self):
        for name in (
            "proof.claim_scope.v1",
            "proof.claim_overbroad.v1",
            "proof.claim_citations.v1",
            "proof.claim_limitations.v1",
            "proof.parity_identity.v1",
            "proof.parity_config.v1",
            "proof.spec_faithful.v1",
            "proof.arm_binding.v1",
            "proof.evidence_complete.v1",
            "proof.claim_supported.v1",
            "proof.redaction.v1",
        ):
            with self.subTest(name=name):
                self.assertTrue(is_registered(name))


class TestClaimChecks(unittest.TestCase):
    def test_scope_present_passes_and_absent_fails(self):
        good = claim_scope({"claims": [{"claim_id": "C1", "scope": SCOPE}]}, {})
        self.assertEqual(codes(good), ["MEASUREMENT"])

        bad = claim_scope({"claims": [{"claim_id": "C1", "scope": None}]}, {})
        self.assertEqual(codes(bad), ["CLAIM_SCOPE_MISSING"])

    def test_a_partial_scope_is_still_missing(self):
        partial = dict(SCOPE)
        partial["time_window"] = "  "
        findings = claim_scope({"claims": [{"claim_id": "C1", "scope": partial}]}, {})
        self.assertEqual(codes(findings), ["CLAIM_SCOPE_MISSING"])

    def test_overbroad_language_is_caught_case_insensitively(self):
        findings = claim_overbroad(
            {"claims": [{"claim_id": "C1", "statement": "The network is FULLY   SECURE."}]},
            LEXICON,
        )
        self.assertEqual(codes(findings), ["CLAIM_OVERBROAD"])

    def test_bounded_language_passes(self):
        findings = claim_overbroad(
            {"claims": [{"claim_id": "C1", "statement": "No critical finding was open."}]},
            LEXICON,
        )
        self.assertEqual(codes(findings), ["MEASUREMENT"])

    def test_an_empty_lexicon_is_a_contract_defect_not_a_pass(self):
        findings = claim_overbroad({"claims": []}, {"lexicon": []})
        self.assertEqual(codes(findings), ["CONTRACT_INVALID"])

    def test_uncited_and_dangling_citations_are_distinguished(self):
        evidence = [{"evidence_id": "EV-1"}]
        uncited = claim_citations(
            {"claims": [{"claim_id": "C1", "evidence_refs": []}], "evidence": evidence}, {}
        )
        self.assertEqual(codes(uncited), ["EVIDENCE_CITATION_MISSING"])

        dangling = claim_citations(
            {"claims": [{"claim_id": "C1", "evidence_refs": ["EV-9"]}], "evidence": evidence}, {}
        )
        self.assertEqual(codes(dangling), ["EVIDENCE_REF_UNRESOLVED"])

        good = claim_citations(
            {"claims": [{"claim_id": "C1", "evidence_refs": ["EV-1"]}], "evidence": evidence}, {}
        )
        self.assertEqual(codes(good), ["MEASUREMENT"])

    def test_limitations_absent_and_gap_undeclared_are_distinguished(self):
        absent = claim_limitations({"limitations": [], "gaps": ["a gap"]}, {})
        self.assertEqual(codes(absent), ["LIMITATIONS_ABSENT"])

        undeclared = claim_limitations(
            {"limitations": ["something else"], "gaps": ["OT segment was out of scope"]}, {}
        )
        self.assertEqual(codes(undeclared), ["EVIDENCE_GAP_UNDECLARED"])

        covered = claim_limitations(
            {
                "limitations": ["Note: the OT segment was out of scope for this engagement."],
                "gaps": ["OT segment was out of scope"],
            },
            {},
        )
        self.assertEqual(codes(covered), ["MEASUREMENT"])

    def test_shape_problems_are_typed(self):
        self.assertEqual(codes(claim_scope({"claims": "nope"}, {})), ["INPUT_SHAPE_INVALID"])
        self.assertEqual(
            codes(claim_citations({"claims": [], "evidence": "nope"}, {})), ["INPUT_SHAPE_INVALID"]
        )


class TestParityChecks(unittest.TestCase):
    def test_identical_identities_pass(self):
        value = {"provider": "p", "model_id": "m"}
        findings = parity_identity(
            {"baseline": value, "augmented": dict(value)},
            {"mismatch_code": "MODEL_IDENTITY_MISMATCH", "subject": "model identity"},
        )
        self.assertEqual(codes(findings), ["MEASUREMENT"])

    def test_differing_identities_emit_the_contract_declared_code(self):
        findings = parity_identity(
            {"baseline": {"model_id": "a"}, "augmented": {"model_id": "b"}},
            {"mismatch_code": "TOOL_SURFACE_MISMATCH", "subject": "tool surface"},
        )
        self.assertEqual(codes(findings), ["TOOL_SURFACE_MISMATCH"])

    def test_key_order_does_not_count_as_a_difference(self):
        findings = parity_identity(
            {"baseline": {"a": 1, "b": 2}, "augmented": {"b": 2, "a": 1}},
            {"mismatch_code": "MODEL_IDENTITY_MISMATCH"},
        )
        self.assertEqual(codes(findings), ["MEASUREMENT"])

    def test_only_the_declared_variable_may_differ(self):
        changed = {"name": "cap", "baseline_value": "off", "augmented_value": "on"}
        good = parity_config(
            {"baseline": {"cap": "off", "t": 0}, "augmented": {"cap": "on", "t": 0}, "changed_variable": changed}
        , {})
        self.assertEqual(codes(good), ["MEASUREMENT"])

        drifted = parity_config(
            {
                "baseline": {"cap": "off", "t": 0},
                "augmented": {"cap": "on", "t": 1},
                "changed_variable": changed,
            },
            {},
        )
        self.assertEqual(codes(drifted), ["CONFIG_DRIFT_UNDECLARED"])

    def test_a_variable_that_did_not_move_is_caught(self):
        changed = {"name": "cap", "baseline_value": "off", "augmented_value": "on"}
        findings = parity_config(
            {"baseline": {"cap": "off"}, "augmented": {"cap": "off"}, "changed_variable": changed}, {}
        )
        self.assertEqual(codes(findings), ["CHANGED_VARIABLE_ABSENT"])

    def test_a_variable_that_moved_to_the_wrong_value_is_caught(self):
        changed = {"name": "cap", "baseline_value": "off", "augmented_value": "on"}
        findings = parity_config(
            {"baseline": {"cap": "off"}, "augmented": {"cap": "maybe"}, "changed_variable": changed}, {}
        )
        self.assertEqual(codes(findings), ["CHANGED_VARIABLE_ABSENT"])

    def test_a_key_present_in_one_arm_only_is_drift(self):
        changed = {"name": "cap", "baseline_value": "off", "augmented_value": "on"}
        findings = parity_config(
            {
                "baseline": {"cap": "off"},
                "augmented": {"cap": "on", "extra": 1},
                "changed_variable": changed,
            },
            {},
        )
        self.assertEqual(codes(findings), ["CONFIG_DRIFT_UNDECLARED"])


class TestPackageChecks(unittest.TestCase):
    def _arm(self, arm_id="baseline", **overrides):
        evidence = {
            "arm_id": arm_id,
            "model": {"provider": "p", "model_id": "m", "params_sha256": sha256_canonical({})},
            "tool_surface": {"tools": ["t"], "sha256": "0" * 64},
            "config": {"cap": "off"},
            "evidence_available": [{"evidence_id": "EV-1"}],
            "transcript": [{"step": 1}, {"step": 2}, {"step": 3}],
            "raw_sha256": "1" * 64,
            "output": {"claims": [{"claim_id": "C1"}], "limitations": []},
        }
        evidence.update(overrides)
        return {
            "arm_id": arm_id,
            "document_sha256": sha256_canonical(evidence),
            "evidence": evidence,
            "xi": {"admission": "REJECT", "verdicts": [{"check_id": "x"}], "blocking_codes": ["CLAIM_OVERBROAD"]},
        }

    def test_arm_binding_detects_an_edited_evidence_bundle(self):
        arm = self._arm()
        self.assertEqual(codes(arm_binding({"arms": {"baseline": arm}}, {})), ["MEASUREMENT"])
        arm["evidence"]["config"]["cap"] = "tampered"
        self.assertEqual(codes(arm_binding({"arms": {"baseline": arm}}, {})), ["HASH_MISMATCH"])

    def test_arm_binding_detects_a_swapped_arm(self):
        arm = self._arm(arm_id="baseline")
        arm["arm_id"] = "augmented"
        self.assertIn("CONTRADICTION_DETECTED", codes(arm_binding({"arms": {"a": arm}}, {})))

    def test_evidence_completeness_requires_a_real_transcript(self):
        good = self._arm()
        self.assertEqual(
            codes(evidence_complete({"arms": {"baseline": good}}, {"min_transcript_steps": 3})),
            ["MEASUREMENT"],
        )
        thin = self._arm(transcript=[{"step": 1}])
        self.assertEqual(
            codes(evidence_complete({"arms": {"baseline": thin}}, {"min_transcript_steps": 3})),
            ["EVIDENCE_INCOMPLETE"],
        )

    def test_spec_faithfulness_catches_a_swapped_recording(self):
        declared = {
            "model": {"provider": "p", "model_id": "m", "params": {}},
            "tool_surface": {"tools": ["t"]},
            "arms": {"baseline": {"config": {"cap": "off"}}, "augmented": {"config": {"cap": "on"}}},
        }
        baseline = self._arm("baseline")["evidence"]
        augmented = self._arm("augmented", config={"cap": "on"})["evidence"]
        ok = spec_faithful(
            {"declared": declared, "baseline": baseline, "augmented": augmented}, {}
        )
        self.assertEqual(codes(ok), ["MEASUREMENT"])

        augmented["model"]["model_id"] = "other"
        bad = spec_faithful(
            {"declared": declared, "baseline": baseline, "augmented": augmented}, {}
        )
        self.assertEqual(codes(bad), ["CONTRADICTION_DETECTED"])


class TestClaimSupported(unittest.TestCase):
    CONFIG = {
        "required_baseline_admission": ["REJECT"],
        "required_augmented_admission": ["ADMIT"],
        "require_blocking_codes_cleared": True,
        "require_baseline_blocking_codes": True,
    }

    def test_a_real_delta_is_supported(self):
        findings = claim_supported(
            {
                "baseline_xi": {"admission": "REJECT", "blocking_codes": ["CLAIM_OVERBROAD"]},
                "augmented_xi": {"admission": "ADMIT", "blocking_codes": []},
            },
            self.CONFIG,
        )
        self.assertEqual(codes(findings), ["MEASUREMENT"])

    def test_an_augmented_arm_that_also_fails_is_unsupported(self):
        findings = claim_supported(
            {
                "baseline_xi": {"admission": "REJECT", "blocking_codes": ["CLAIM_OVERBROAD"]},
                "augmented_xi": {"admission": "REJECT", "blocking_codes": ["CLAIM_OVERBROAD"]},
            },
            self.CONFIG,
        )
        self.assertEqual(codes(findings), ["CLAIM_UNSUPPORTED"])

    def test_a_baseline_that_never_failed_leaves_nothing_to_claim(self):
        findings = claim_supported(
            {
                "baseline_xi": {"admission": "ADMIT", "blocking_codes": []},
                "augmented_xi": {"admission": "ADMIT", "blocking_codes": []},
            },
            self.CONFIG,
        )
        self.assertEqual(codes(findings), ["CLAIM_UNSUPPORTED"])

    def test_a_residual_blocking_code_is_unsupported(self):
        findings = claim_supported(
            {
                "baseline_xi": {"admission": "REJECT", "blocking_codes": ["A", "B"]},
                "augmented_xi": {"admission": "ADMIT", "blocking_codes": ["B"]},
            },
            self.CONFIG,
        )
        self.assertEqual(codes(findings), ["CLAIM_UNSUPPORTED"])
        self.assertIn("['B']", findings[0].message)


class TestRedactionCheck(unittest.TestCase):
    POLICY = {
        "policy_sha256": "a" * 64,
        "rule_ids": ["mask-key"],
        "deny_patterns": [
            {"pattern_id": "key", "expression": r"\bAKIA[0-9A-Z]{8}\b", "description": "key"}
        ],
    }

    def _accounting(self, **overrides):
        base = {
            "policy_sha256": "a" * 64,
            "applied_rules": [{"rule_id": "mask-key", "hits": 1}],
            "unapplied_rules": [],
        }
        base.update(overrides)
        return base

    def test_a_clean_projection_passes(self):
        findings = redaction_public_safe(
            {
                "policy": self.POLICY,
                "projection": {"text": "[REDACTED:mask-key]"},
                "baseline": {"redaction": self._accounting()},
            },
            {},
        )
        self.assertEqual(codes(findings), ["MEASUREMENT"])

    def test_a_surviving_denied_value_fails(self):
        findings = redaction_public_safe(
            {
                "policy": self.POLICY,
                "projection": {"text": "key AKIA12345678 here"},
                "baseline": {"redaction": self._accounting()},
            },
            {},
        )
        self.assertEqual(codes(findings), ["SENSITIVE_VALUE_PRESENT"])

    def test_the_leak_report_does_not_quote_the_leak(self):
        findings = redaction_public_safe(
            {
                "policy": self.POLICY,
                "projection": {"text": "key AKIA12345678 here"},
                "baseline": {"redaction": self._accounting()},
            },
            {},
        )
        for item in findings:
            self.assertNotIn("AKIA12345678", item.message)

    def test_a_rule_that_did_not_fire_is_a_policy_violation(self):
        findings = redaction_public_safe(
            {
                "policy": self.POLICY,
                "projection": {"text": "clean"},
                "baseline": {"redaction": self._accounting(unapplied_rules=["mask-key"])},
            },
            {},
        )
        self.assertEqual(codes(findings), ["REDACTION_POLICY_VIOLATION"])

    def test_projection_under_a_different_policy_is_a_violation(self):
        findings = redaction_public_safe(
            {
                "policy": self.POLICY,
                "projection": {"text": "clean"},
                "baseline": {"redaction": self._accounting(policy_sha256="b" * 64)},
            },
            {},
        )
        self.assertEqual(codes(findings), ["REDACTION_POLICY_VIOLATION"])

    def test_a_policy_with_no_deny_patterns_cannot_establish_safety(self):
        findings = redaction_public_safe(
            {"policy": {"deny_patterns": [], "rule_ids": []}, "projection": {}}, {}
        )
        self.assertEqual(codes(findings), ["REDACTION_POLICY_VIOLATION"])


if __name__ == "__main__":
    unittest.main()
