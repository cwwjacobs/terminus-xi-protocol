"""Independent verification, and every tamper it must catch.

Each tamper test takes a real admitted package, changes exactly one thing, and
asserts that verification stops being satisfied. Verification never re-uses the
build: it reads the directory back from disk.
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

import _support  # noqa: F401
from _support import build_canonical_proof, copy_proof, ffmpeg_available  # noqa: E402

from terminus_proof import cli  # noqa: E402
from terminus_proof.package import verify_package  # noqa: E402
from terminus_xi.canonical import read_json, sha256_canonical, write_json  # noqa: E402
from terminus_xi.receipt import stable_core_sha256  # noqa: E402


def reseal(receipt: dict) -> dict:
    """Recompute a receipt's own digests, as a forger would."""
    receipt["stable_core_sha256"] = stable_core_sha256(receipt)
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = sha256_canonical(body)
    return receipt


def reseal_manifest(directory: Path) -> None:
    """Recompute the manifest, as a forger with the tooling would."""
    from terminus_proof.package import MANIFEST_NAME

    manifest = read_json(directory / MANIFEST_NAME)
    entries = []
    from terminus_xi.canonical import sha256_file

    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != MANIFEST_NAME:
            entries.append(
                {
                    "path": str(path.relative_to(directory)),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "media_type": next(
                        (
                            item["media_type"]
                            for item in manifest["files"]
                            if item["path"] == str(path.relative_to(directory))
                        ),
                        "application/octet-stream",
                    ),
                }
            )
    entries.sort(key=lambda entry: entry["path"])
    manifest["files"] = entries
    manifest["files_sha256"] = sha256_canonical(entries)
    write_json(directory / MANIFEST_NAME, manifest)


@unittest.skipUnless(ffmpeg_available(), "ffmpeg is required to build the media in this package")
class TestVerifyAdmittedPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build, cls.result, _ = build_canonical_proof(render=True)
        cls.directory = cls.result.directory

    def test_the_pristine_package_verifies(self):
        report = verify_package(self.directory)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.proof_id, self.build.proof_id)
        self.assertEqual(report.admission, "ADMIT")

    def test_verification_actually_checked_the_things_it_claims(self):
        report = verify_package(self.directory)
        joined = " | ".join(report.checks)
        for phrase in (
            "files present, complete, and unmodified",
            "re-derive from the artifact itself",
            "package receipt is internally consistent",
            "re-evaluate to the verdicts",
            "deny patterns",
            "thumbnail.png is a valid PNG",
            "demo.mp4 probes as a valid MP4",
            "re-evaluated to the recorded verdicts",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, joined)

    def test_the_cli_verify_exits_zero_and_can_emit_json(self):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["verify", str(self.directory), "--json"], out=buffer)
        self.assertEqual(code, 0)
        report = json.loads(buffer.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])


@unittest.skipUnless(ffmpeg_available(), "ffmpeg is required to build the media in this package")
class TestTamperDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.result, _ = build_canonical_proof(render=True)

    def _tampered(self):
        directory = copy_proof(self.result.directory)
        self.addCleanup(shutil.rmtree, directory.parent, ignore_errors=True)
        return directory

    def _assert_fails(self, directory: Path, needle: str):
        report = verify_package(directory)
        self.assertFalse(report.ok, "verification accepted a tampered package")
        self.assertTrue(
            any(needle in error for error in report.errors),
            f"expected an error mentioning {needle!r}, got {report.errors}",
        )

    def test_an_edited_readme_is_caught(self):
        directory = self._tampered()
        path = directory / "README.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nand it is fully secure.\n", encoding="utf-8")
        self._assert_fails(directory, "digest")

    def test_an_edited_arm_file_is_caught_even_after_resealing_the_manifest(self):
        directory = self._tampered()
        document = read_json(directory / "baseline.json")
        document["output"]["claims"][0]["statement"] = "Everything was fine all along."
        write_json(directory / "baseline.json", document)
        reseal_manifest(directory)
        self._assert_fails(directory, "hashes to")

    def test_a_deleted_file_is_caught(self):
        directory = self._tampered()
        (directory / "transcript.txt").unlink()
        self._assert_fails(directory, "missing from the directory")

    def test_an_added_file_is_caught(self):
        directory = self._tampered()
        (directory / "bonus-claims.md").write_text("extra marketing", encoding="utf-8")
        self._assert_fails(directory, "does not list")

    def test_a_deleted_and_unlisted_required_file_is_still_caught(self):
        directory = self._tampered()
        (directory / "demo.mp4").unlink()
        reseal_manifest(directory)
        self._assert_fails(directory, "required files")

    def test_swapping_the_video_for_something_else_is_caught(self):
        directory = self._tampered()
        (directory / "demo.mp4").write_bytes(b"not a video at all")
        reseal_manifest(directory)
        self._assert_fails(directory, "ftyp")

    def test_a_corrupted_thumbnail_is_caught(self):
        directory = self._tampered()
        data = bytearray((directory / "thumbnail.png").read_bytes())
        del data[-16:]
        (directory / "thumbnail.png").write_bytes(bytes(data))
        reseal_manifest(directory)
        self._assert_fails(directory, "IEND")

    def test_editing_the_artifact_breaks_the_derived_proof_id(self):
        directory = self._tampered()
        proof = read_json(directory / "proof.json")
        proof["artifact"]["claim"]["statement"] = "It works everywhere, always."
        write_json(directory / "proof.json", proof)
        reseal_manifest(directory)
        self._assert_fails(directory, "artifact_sha256")

    def test_forging_the_admission_on_the_package_receipt_is_caught(self):
        directory = self._tampered()
        receipt = read_json(directory / "receipt.json")
        receipt["check_results"][-1]["verdict"] = "FAIL"
        write_json(directory / "receipt.json", reseal(receipt))
        reseal_manifest(directory)
        self._assert_fails(directory, "findings imply")

    def test_swapping_an_arm_receipt_for_the_other_arm_is_caught(self):
        directory = self._tampered()
        shutil.copyfile(
            directory / "receipts" / "augmented.receipt.json",
            directory / "receipts" / "baseline.receipt.json",
        )
        reseal_manifest(directory)
        self._assert_fails(directory, "receipt for")

    def test_weakening_the_contract_snapshot_is_caught(self):
        directory = self._tampered()
        contracts = read_json(directory / "contracts" / "package-contract-set.json")
        contracts["contracts"] = [
            c for c in contracts["contracts"] if c["check_id"] != "proof.redaction.public_safe"
        ]
        write_json(directory / "contracts" / "package-contract-set.json", contracts)
        reseal_manifest(directory)
        self._assert_fails(directory, "not the ones it was judged against")

    def test_loosening_the_policy_snapshot_is_caught(self):
        directory = self._tampered()
        policy = read_json(directory / "policies" / "package-policy.json")
        policy["on_warn"] = "ADMIT"
        write_json(directory / "policies" / "package-policy.json", policy)
        reseal_manifest(directory)
        self._assert_fails(directory, "different admission policy")

    def test_planting_a_sensitive_value_in_the_readme_is_caught(self):
        directory = self._tampered()
        path = directory / "README.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nHost: vault-prod-03.internal.acme-grid.example\n",
            encoding="utf-8",
        )
        reseal_manifest(directory)
        self._assert_fails(directory, "deny pattern")

    def test_rewriting_the_listing_claim_is_caught(self):
        directory = self._tampered()
        listing = read_json(directory / "listing-assets.json")
        listing["claim"]["statement"] = "Claim Boundary Audit makes every claim true."
        write_json(directory / "listing-assets.json", listing)
        reseal_manifest(directory)
        self._assert_fails(directory, "states a claim the artifact does not carry")

    def test_dropping_the_not_claimed_list_is_caught(self):
        directory = self._tampered()
        listing = read_json(directory / "listing-assets.json")
        listing["not_claimed"] = []
        write_json(directory / "listing-assets.json", listing)
        reseal_manifest(directory)
        self._assert_fails(directory, "not-claimed list")

    def test_a_missing_manifest_is_caught(self):
        directory = self._tampered()
        (directory / "proof-manifest.json").unlink()
        self._assert_fails(directory, "cannot be checked for completeness")

    def test_relabelling_a_rejected_package_as_admitted_is_caught(self):
        directory = self._tampered()
        manifest = read_json(directory / "proof-manifest.json")
        manifest["state"] = "ADMITTED"
        manifest["proof_id"] = "someone-elses-proof"
        write_json(directory / "proof-manifest.json", manifest)
        self._assert_fails(directory, "disagree about the proof id")


if __name__ == "__main__":
    unittest.main()
