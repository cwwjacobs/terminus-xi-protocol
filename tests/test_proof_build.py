"""The canonical Claim Boundary Audit build, end to end."""

from __future__ import annotations

import json
import unittest

import _support  # noqa: F401
from _support import DEMO_SPEC, FrozenClock, REPO_ROOT, build_canonical_proof  # noqa: E402

from terminus_proof import REQUIRED_PACKAGE_FILES  # noqa: E402
from terminus_proof.adapters import AdapterError, get_adapter, registered_kinds  # noqa: E402
from terminus_proof.engine import build_proof  # noqa: E402
from terminus_proof.spec import SpecError, load_spec  # noqa: E402
from terminus_xi.canonical import read_json, sha256_canonical  # noqa: E402
from terminus_xi.schemas import validate_against  # noqa: E402


class TestSpecLoading(unittest.TestCase):
    def test_the_canonical_spec_loads_and_validates(self):
        spec = load_spec(DEMO_SPEC)
        self.assertEqual(spec.demo_id, "claim-boundary-audit")
        validate_against(spec.document, "terminus-proof.demo-spec.v1")
        self.assertEqual(spec.root, REPO_ROOT)

    def test_every_shipped_spec_loads(self):
        specs = [DEMO_SPEC, *sorted((REPO_ROOT / "demos" / "negative").glob("*.demo.json"))]
        for path in specs:
            with self.subTest(path=path.name):
                load_spec(path)

    def test_a_changed_variable_that_does_not_change_is_refused(self):
        document = json.loads(DEMO_SPEC.read_text())
        document["changed_variable"]["augmented_value"] = document["changed_variable"]["baseline_value"]
        with self.assertRaises(SpecError) as ctx:
            self._load_inline(document)
        self.assertIn("changed variable", str(ctx.exception))

    def test_a_missing_referenced_file_is_refused(self):
        document = json.loads(DEMO_SPEC.read_text())
        document["fixture"]["path"] = "fixtures/does-not-exist.json"
        spec = self._load_inline(document)
        with self.assertRaises(SpecError):
            spec.resolve(document["fixture"]["path"])

    def _load_inline(self, document):
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / "inline.demo.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return load_spec(path, root=REPO_ROOT)


class TestAdapters(unittest.TestCase):
    def test_the_fixture_adapter_is_registered(self):
        self.assertIn("fixture-recording", registered_kinds())

    def test_an_unknown_adapter_kind_is_refused(self):
        with self.assertRaises(AdapterError):
            get_adapter("gtd-run")

    def test_a_recording_bound_to_the_wrong_arm_is_refused(self):
        adapter = get_adapter("fixture-recording")
        with self.assertRaises(AdapterError) as ctx:
            adapter.execute(
                arm_spec={
                    "arm_id": "augmented",
                    "adapter": {
                        "kind": "fixture-recording",
                        "path": "fixtures/claim-boundary-audit/baseline.recording.json",
                    },
                },
                fixture={},
                root=REPO_ROOT,
            )
        self.assertIn("binds it to arm", str(ctx.exception))

    def test_a_missing_recording_is_refused(self):
        adapter = get_adapter("fixture-recording")
        with self.assertRaises(AdapterError):
            adapter.execute(
                arm_spec={"arm_id": "baseline", "adapter": {"kind": "fixture-recording", "path": "nope.json"}},
                fixture={},
                root=REPO_ROOT,
            )


class TestCanonicalBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build, cls.result, _ = build_canonical_proof(render=False)

    def test_the_baseline_arm_is_rejected_at_the_claim_boundary(self):
        outcome = self.build.arms["baseline"]
        self.assertEqual(outcome.admission, "REJECT")
        self.assertEqual(
            sorted(outcome.decision.blocking_codes),
            [
                "CLAIM_OVERBROAD",
                "CLAIM_SCOPE_MISSING",
                "EVIDENCE_CITATION_MISSING",
                "EVIDENCE_REF_UNRESOLVED",
                "LIMITATIONS_ABSENT",
            ],
        )

    def test_the_augmented_arm_is_admitted_under_the_same_contract_set(self):
        outcome = self.build.arms["augmented"]
        self.assertEqual(outcome.admission, "ADMIT")
        self.assertEqual(outcome.decision.blocking_codes, ())
        self.assertEqual(
            self.build.artifact["arms"]["baseline"]["xi"]["contract_set_sha256"],
            self.build.artifact["arms"]["augmented"]["xi"]["contract_set_sha256"],
        )

    def test_the_package_boundary_admits(self):
        self.assertTrue(self.build.admitted)
        self.assertEqual(self.build.admission, "ADMIT")
        self.assertEqual(len(self.build.package.results), 10)
        self.assertTrue(all(r.verdict == "PASS" for r in self.build.package.results))

    def test_the_artifact_validates_against_its_frozen_schema(self):
        validate_against(self.build.artifact, "terminus-proof.proof-artifact.v1")

    def test_both_arm_bundles_validate(self):
        for arm_id in ("baseline", "augmented"):
            with self.subTest(arm=arm_id):
                validate_against(
                    self.build.arm_documents[arm_id], "terminus-proof.evidence-bundle.v1"
                )

    def test_the_artifact_carries_no_clock_reading(self):
        with FrozenClock("2000-01-01T00:00:00Z"):
            first = build_proof(load_spec(DEMO_SPEC))
        with FrozenClock("2031-12-31T23:59:59Z"):
            second = build_proof(load_spec(DEMO_SPEC))
        self.assertEqual(first.artifact_sha256, second.artifact_sha256)
        self.assertEqual(first.proof_id, second.proof_id)
        self.assertEqual(
            first.package.receipt["stable_core_sha256"],
            second.package.receipt["stable_core_sha256"],
        )
        self.assertNotEqual(
            first.package.receipt["created_at_utc"], second.package.receipt["created_at_utc"]
        )

    def test_the_proof_id_derives_from_the_artifact(self):
        expected = f"claim-boundary-audit-{sha256_canonical(self.build.artifact)[:12]}"
        self.assertEqual(self.build.proof_id, expected)

    def test_every_required_file_was_written(self):
        directory = self.result.directory
        for name in REQUIRED_PACKAGE_FILES:
            if name in ("demo.mp4", "thumbnail.png"):
                continue  # this build was made with render=False
            with self.subTest(name=name):
                self.assertTrue((directory / name).exists(), f"{name} missing")

    def test_the_arm_files_are_bound_to_the_artifact_by_digest(self):
        directory = self.result.directory
        for arm_id in ("baseline", "augmented"):
            with self.subTest(arm=arm_id):
                document = read_json(directory / f"{arm_id}.json")
                self.assertEqual(
                    sha256_canonical(document),
                    self.build.artifact["arms"][arm_id]["document_sha256"],
                )

    def test_provenance_binds_every_governing_document(self):
        roles = {
            item["role"] for item in self.build.package.receipt["provenance"]["inputs"]
        }
        self.assertEqual(
            roles,
            {
                "demo-spec",
                "fixture",
                "arm-contract-set",
                "package-contract-set",
                "arm-policy",
                "package-policy",
                "redaction-policy",
                "recording/baseline",
                "recording/augmented",
            },
        )

    def test_the_public_surface_carries_no_denied_value(self):
        from terminus_proof.redaction import scan_denied

        patterns = self.build.artifact["redaction"]["deny_patterns"]
        for surface in ("public_projection", "arms"):
            with self.subTest(surface=surface):
                self.assertEqual(scan_denied(self.build.artifact[surface], patterns), [])

    def test_the_raw_execution_is_bound_but_not_published(self):
        for arm_id in ("baseline", "augmented"):
            bundle = self.build.arm_documents[arm_id]
            self.assertRegex(bundle["raw_sha256"], r"^[0-9a-f]{64}$")
            # the published bundle is the redacted one, so its own digest differs
            self.assertNotEqual(bundle["raw_sha256"], sha256_canonical(bundle))


if __name__ == "__main__":
    unittest.main()
