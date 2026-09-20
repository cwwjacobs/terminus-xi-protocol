"""Slides, media, and generated documentation.

Slides and documentation are assertions about the world, so the tests check that
every assertion they make is one the artifact already carries, and that the same
renderers report a rejection as a rejection.
"""

from __future__ import annotations

import copy
import re
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import _support  # noqa: F401
from _support import build_canonical_proof, ffmpeg_available  # noqa: E402

from terminus_proof.docs_render import (  # noqa: E402
    render_listing_assets,
    render_not_admitted,
    render_readme,
    render_transcript,
)
from terminus_proof.media import MediaError, probe_mp4, probe_png  # noqa: E402
from terminus_proof.slides import build_slides, build_thumbnail, slide_svg  # noqa: E402
from terminus_xi.canonical import read_json  # noqa: E402
from terminus_xi.schemas import validate_against  # noqa: E402


class TestSlides(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build, cls.result, _ = build_canonical_proof(render=False)
        cls.artifact = cls.build.artifact
        cls.receipt = cls.build.package.receipt
        cls.slides = build_slides(cls.artifact, cls.receipt)

    def test_every_slide_is_well_formed_xml(self):
        for slide in self.slides:
            with self.subTest(slide=slide.slide_id):
                ElementTree.fromstring(slide_svg(slide.body))

    def test_the_deck_covers_the_required_subjects(self):
        ids = [slide.slide_id.split("-", 1)[1] for slide in self.slides]
        for required in ("contract", "arms", "changed-variable", "verdict", "receipt"):
            self.assertIn(required, ids)

    def test_every_slide_has_a_positive_duration(self):
        for slide in self.slides:
            with self.subTest(slide=slide.slide_id):
                self.assertGreater(slide.seconds, 0)

    def test_the_verdict_slide_shows_the_real_verdicts(self):
        body = next(s.body for s in self.slides if s.slide_id.endswith("verdict"))
        for result in self.receipt["check_results"]:
            self.assertIn(result["check_id"], body)
        self.assertIn(self.receipt["admission"], body)

    def test_the_arms_slide_shows_the_real_blocking_codes(self):
        body = next(s.body for s in self.slides if s.slide_id.endswith("arms"))
        for code in self.artifact["arms"]["baseline"]["xi"]["blocking_codes"]:
            self.assertIn(code, body)

    def test_a_rejected_proof_renders_as_rejected(self):
        """The renderer reads the receipt; it has no way to draw a green check."""
        rejected = copy.deepcopy(self.receipt)
        rejected["admission"] = "REJECT"
        for result in rejected["check_results"]:
            result["verdict"] = "FAIL"
        body = "".join(slide.body for slide in build_slides(self.artifact, rejected))
        self.assertIn("REJECT", body)
        self.assertNotIn("ADMISSION ADMIT", body)

    def test_slide_text_is_xml_escaped(self):
        artifact = copy.deepcopy(self.artifact)
        artifact["public_projection"]["title"] = 'Ampersand & <script>alert("x")</script>'
        deck = build_slides(artifact, self.receipt)
        for slide in deck:
            ElementTree.fromstring(slide_svg(slide.body))
        self.assertNotIn("<script>", "".join(s.body for s in deck))

    def test_the_thumbnail_is_well_formed_and_states_both_admissions(self):
        svg = build_thumbnail(self.artifact, self.receipt)
        ElementTree.fromstring(svg)
        self.assertIn("REJECT", svg)
        self.assertIn("ADMIT", svg)

    def test_slides_are_byte_reproducible(self):
        again = build_slides(self.artifact, self.receipt)
        self.assertEqual([s.body for s in self.slides], [s.body for s in again])


@unittest.skipUnless(ffmpeg_available(), "ffmpeg is not available")
class TestRenderedMedia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.result, _ = build_canonical_proof(render=True)
        cls.directory = cls.result.directory

    def test_the_thumbnail_is_a_real_png_of_the_declared_size(self):
        probed = probe_png(self.directory / "thumbnail.png")
        self.assertEqual((probed["width"], probed["height"]), (1280, 720))
        self.assertGreater(probed["bytes"], 1000)

    def test_the_video_probes_as_h264_at_the_declared_geometry(self):
        probed = probe_mp4(self.directory / "demo.mp4")
        if probed.get("prober") == "ffprobe":
            self.assertEqual(probed["codec_name"], "h264")
            self.assertEqual((probed["width"], probed["height"]), ("1920", "1080"))
            self.assertGreater(float(probed["duration"]), 20.0)

    def test_every_slide_frame_was_written_and_is_a_real_png(self):
        frames = sorted((self.directory / "media").glob("slide-*.png"))
        self.assertEqual(len(frames), 7)
        for frame in frames:
            with self.subTest(frame=frame.name):
                probed = probe_png(frame)
                self.assertEqual((probed["width"], probed["height"]), (1920, 1080))

    def test_the_svg_sources_ship_alongside_the_frames(self):
        sources = sorted((self.directory / "media").glob("slide-*.svg"))
        self.assertEqual(len(sources), 7)
        for source in sources:
            with self.subTest(source=source.name):
                ElementTree.fromstring(source.read_text(encoding="utf-8"))

    def test_probes_reject_files_that_are_not_what_they_claim(self):
        bogus = self.directory / "media" / "bogus"
        bogus.write_bytes(b"nope")
        self.addCleanup(bogus.unlink)
        with self.assertRaises(MediaError):
            probe_png(bogus)
        with self.assertRaises(MediaError):
            probe_mp4(bogus)


class TestGeneratedDocumentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build, cls.result, _ = build_canonical_proof(render=False)
        cls.directory = cls.result.directory
        cls.artifact = cls.build.artifact
        cls.receipt = cls.build.package.receipt
        cls.proof = read_json(cls.directory / "proof.json")
        cls.arm_receipts = {
            arm_id: cls.build.arms[arm_id].receipt for arm_id in ("baseline", "augmented")
        }

    def test_the_readme_states_the_admission_and_the_claim_verbatim(self):
        text = (self.directory / "README.md").read_text(encoding="utf-8")
        self.assertIn(self.artifact["claim"]["statement"], text)
        self.assertIn(self.receipt["admission"], text)
        self.assertIn(self.build.proof_id, text)

    def test_the_readme_lists_every_check_the_receipt_records(self):
        text = (self.directory / "README.md").read_text(encoding="utf-8")
        for result in self.receipt["check_results"]:
            with self.subTest(check=result["check_id"]):
                self.assertIn(result["check_id"], text)

    def test_the_readme_carries_the_not_claimed_list(self):
        text = (self.directory / "README.md").read_text(encoding="utf-8")
        for item in self.artifact["claim"]["not_claimed"]:
            with self.subTest(item=item[:32]):
                self.assertIn(item, text)

    def test_the_readme_reports_a_rejection_as_a_rejection(self):
        rejected = copy.deepcopy(self.receipt)
        rejected["admission"] = "REJECT"
        text = render_readme(
            artifact=self.artifact,
            proof=self.proof,
            receipt=rejected,
            arm_receipts=self.arm_receipts,
            spec_path="demos/claim-boundary-audit.demo.json",
        )
        self.assertIn("**REJECT**", text)

    def test_listing_bullets_all_point_at_evidence(self):
        listing = read_json(self.directory / "listing-assets.json")
        validate_against(listing, "terminus-proof.listing-assets.v1")
        for bullet in listing["bullets"]:
            with self.subTest(bullet=bullet["text"][:32]):
                self.assertTrue(bullet["derived_from"].startswith("/"))
        self.assertEqual(listing["claim"]["statement"], self.artifact["claim"]["statement"])
        self.assertTrue(listing["admitted"])

    def test_listing_copy_never_invents_a_number(self):
        listing = render_listing_assets(
            artifact=self.artifact,
            proof=self.proof,
            receipt=self.receipt,
            arm_receipts=self.arm_receipts,
        )
        baseline = self.artifact["public_projection"]["arms"]["baseline"]
        joined = listing["headline"] + listing["summary"] + "".join(b["text"] for b in listing["bullets"])
        for number in re.findall(r"\b\d+\b", joined):
            with self.subTest(number=number):
                self.assertIn(
                    int(number),
                    {
                        baseline["claim_count"],
                        len(baseline["blocking_codes"]),
                        self.artifact["public_projection"]["arms"]["augmented"]["claim_count"],
                        len(self.artifact["public_projection"]["arms"]["augmented"]["blocking_codes"]),
                        len(self.receipt["check_results"]),
                        len(
                            set(baseline["blocking_codes"])
                            - set(self.artifact["public_projection"]["arms"]["augmented"]["blocking_codes"])
                        ),
                    },
                )

    def test_the_transcript_marks_redacted_spans_and_keeps_both_arms(self):
        text = (self.directory / "transcript.txt").read_text(encoding="utf-8")
        self.assertIn("ARM: baseline", text)
        self.assertIn("ARM: augmented", text)
        self.assertIn("[REDACTED:", text)

    def test_the_transcript_reproduces_every_recorded_step(self):
        text = render_transcript(self.artifact, self.build.proof_id)
        for arm_id in ("baseline", "augmented"):
            for step in self.artifact["arms"][arm_id]["evidence"]["transcript"]:
                with self.subTest(arm=arm_id, step=step["step"]):
                    self.assertIn(step["text"], text)

    def test_findings_index_matches_the_receipts(self):
        findings = read_json(self.directory / "findings.json")
        validate_against(findings, "terminus-proof.findings.v1")
        self.assertEqual(len(findings["boundaries"]), 3)
        recorded = {b["boundary_id"]: b for b in findings["boundaries"]}
        self.assertEqual(recorded["proof.package"]["admission"], self.receipt["admission"])
        self.assertEqual(
            len(recorded["proof.package"]["results"]), len(self.receipt["check_results"])
        )

    def test_the_not_admitted_document_refuses_to_advertise(self):
        rejected = copy.deepcopy(self.receipt)
        rejected["admission"] = "REJECT"
        rejected["admission_rationale"]["blocking_codes"] = ["CLAIM_UNSUPPORTED"]
        text = render_not_admitted(
            artifact=self.artifact,
            receipt=rejected,
            proof_id=self.build.proof_id,
            spec_path="demos/negative/unsupported-claim.demo.json",
        )
        self.assertIn("NOT ADMITTED", text)
        self.assertIn("CLAIM_UNSUPPORTED", text)
        self.assertIn("must not be presented as a demonstration", text)


if __name__ == "__main__":
    unittest.main()
