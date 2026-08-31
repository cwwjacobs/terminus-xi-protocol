"""Applying a redaction policy, and accounting honestly for what it did."""

from __future__ import annotations

import copy
import unittest

import _support  # noqa: F401
from _support import REPO_ROOT  # noqa: E402

from terminus_proof.redaction import (  # noqa: E402
    RedactionError,
    apply_policy,
    load_redaction_policy,
    scan_denied,
)

POLICY_PATH = REPO_ROOT / "policies" / "public-safe.redaction.json"


class TestPolicyLoading(unittest.TestCase):
    def test_the_shipped_policy_loads(self):
        policy = load_redaction_policy(POLICY_PATH)
        self.assertEqual(policy.policy_id, "terminus-proof.public-safe")
        self.assertIn("mask-access-key", policy.rule_ids())

    def test_an_invalid_regex_is_refused_at_load_time(self):
        document = copy.deepcopy(load_redaction_policy(POLICY_PATH).document)
        document["rules"][0]["match"]["expression"] = "([unclosed"
        with self.assertRaises(RedactionError):
            load_redaction_policy_from(document)

    def test_the_artifact_block_carries_patterns_but_not_rule_expressions(self):
        policy = load_redaction_policy(POLICY_PATH)
        block = policy.to_artifact_block()
        self.assertEqual(
            sorted(block),
            sorted(["policy_id", "policy_version", "policy_sha256", "rule_ids", "deny_patterns"]),
        )
        self.assertNotIn("rules", block)
        self.assertEqual(block["rule_ids"], policy.rule_ids())
        # Deny patterns are published on purpose: the XI check reads them, and a
        # shape is not a secret. Rule bodies are not, because a pointer rule
        # describes where in the private document a secret lived.
        pointer_expressions = {
            rule["match"]["expression"]
            for rule in policy.rules
            if rule["match"]["kind"] == "pointer"
        }
        self.assertTrue(pointer_expressions, "the policy no longer exercises pointer rules")
        serialized = repr(block)
        for expression in pointer_expressions:
            with self.subTest(expression=expression):
                self.assertNotIn(expression, serialized)


def load_redaction_policy_from(document):
    """Load a policy from an in-memory document via a temporary file."""
    import json
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return load_redaction_policy(path)


class TestApplyPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = load_redaction_policy(POLICY_PATH)
        self.document = {
            "evidence": [
                {
                    "evidence_id": "EV-1",
                    "summary": "scan of 10.4.0.0/16 including vault-prod-03.internal.acme-grid.example",
                    "detail": "raw detail with AKIA5T7QWERTYUIOPLKJ",
                }
            ],
            "arms": {
                "baseline": {
                    "output": {"claims": [{"statement": "contact soc-oncall@acme-grid.example"}]},
                    "transcript": [{"step": 1, "text": "host vault-prod-03.internal.acme-grid.example"}],
                }
            },
        }

    def test_masking_replaces_every_denied_shape(self):
        outcome = apply_policy(self.policy, self.document)
        text = repr(outcome.value)
        self.assertNotIn("acme-grid.example", text)
        self.assertNotIn("AKIA5T7QWERTYUIOPLKJ", text)
        self.assertNotIn("10.4.0.0", text)
        self.assertIn("[REDACTED:mask-internal-host]", text)

    def test_pointer_rules_drop_the_node(self):
        outcome = apply_policy(self.policy, self.document)
        self.assertNotIn("detail", outcome.value["evidence"][0])
        self.assertIn("summary", outcome.value["evidence"][0])

    def test_the_input_document_is_not_mutated(self):
        before = copy.deepcopy(self.document)
        apply_policy(self.policy, self.document)
        self.assertEqual(self.document, before)

    def test_accounting_records_a_hit_count_per_rule(self):
        outcome = apply_policy(self.policy, self.document)
        by_rule = {rule["rule_id"]: rule["hits"] for rule in outcome.applied_rules}
        self.assertEqual(sorted(by_rule), sorted(self.policy.rule_ids()))
        self.assertGreaterEqual(by_rule["mask-internal-host"], 2)
        self.assertEqual(by_rule["drop-evidence-detail"], 1)
        self.assertEqual(outcome.unapplied_rules, ())

    def test_a_rule_that_never_fires_is_reported_unapplied(self):
        empty = {"evidence": [], "arms": {}}
        outcome = apply_policy(self.policy, empty)
        self.assertEqual(sorted(outcome.unapplied_rules), sorted(self.policy.rule_ids()))

    def test_the_result_survives_its_own_deny_patterns(self):
        outcome = apply_policy(self.policy, self.document)
        self.assertEqual(scan_denied(outcome.value, self.policy.deny_patterns), [])

    def test_a_missing_rule_leaves_the_value_in_place(self):
        document = copy.deepcopy(self.policy.document)
        document["rules"] = [r for r in document["rules"] if r["rule_id"] != "mask-access-key"]
        document["rules"] = [r for r in document["rules"] if r["rule_id"] != "drop-evidence-detail"]
        leaky = load_redaction_policy_from(document)
        outcome = apply_policy(leaky, self.document)
        hits = scan_denied(outcome.value, leaky.deny_patterns)
        self.assertTrue(hits)
        self.assertEqual({hit["pattern_id"] for hit in hits}, {"access-key"})


class TestScan(unittest.TestCase):
    PATTERNS = [{"pattern_id": "digit", "expression": r"\d{4}", "description": "four digits"}]

    def test_scan_reports_location_not_content(self):
        hits = scan_denied({"a": {"b": "1234"}}, self.PATTERNS)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["location"], "/a/b")
        self.assertNotIn("1234", repr(hits))

    def test_scan_walks_lists_and_is_deterministically_ordered(self):
        value = {"z": ["9999"], "a": "8888"}
        hits = scan_denied(value, self.PATTERNS)
        self.assertEqual([hit["location"] for hit in hits], ["/a", "/z/0"])

    def test_clean_content_produces_no_hits(self):
        self.assertEqual(scan_denied({"a": "abc"}, self.PATTERNS), [])


if __name__ == "__main__":
    unittest.main()
