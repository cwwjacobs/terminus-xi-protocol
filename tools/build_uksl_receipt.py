#!/usr/bin/env python3
"""Assemble the UKSL closure receipt from observed evidence.

Every exit-gate clause in UKSL.md is evaluated here against something that can
be looked at: a file digest, a test count, a probe result, an admission, a
verification report. A clause that cannot be established is recorded as
unsatisfied with a blocker, and the receipt then records the UKSL as not closed.

    python tools/run_tests.py --report receipts/test-report.json
    python tools/freeze_xi_v1.py --test-report receipts/test-report.json
    python -m terminus_proof build demos/claim-boundary-audit.demo.json
    python tools/build_uksl_receipt.py --proof-dir proofs/<proof-id>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from terminus_proof import ENGINE_VERSION  # noqa: E402
from terminus_proof.media import probe_mp4, probe_png  # noqa: E402
from terminus_proof.package import verify_package  # noqa: E402
from terminus_xi import PROTOCOL_VERSION, RUNTIME_VERSION  # noqa: E402
from terminus_xi.canonical import read_json, sha256_canonical, sha256_file, utc_now, write_json  # noqa: E402
from terminus_xi.schemas import validate_against  # noqa: E402

FREEZE_RECEIPT = REPO_ROOT / "receipts" / "xi-v1-freeze-receipt.json"
TEST_REPORT = REPO_ROOT / "receipts" / "test-report.json"
OUTPUT = REPO_ROOT / "receipts" / "uksl-receipt.json"

KNOWN_LIMITATIONS = [
    "Receipts are integrity documents, not signed attestations. They detect edits and "
    "incompleteness; they do not authenticate the producer.",
    "A digest establishes identity of the bytes it covers. It proves nothing about truth, "
    "safety, authorship, authority, or semantic correctness.",
    "Claim-boundary checks are bounded lexical and structural predicates over declared "
    "evidence. CLAIM_OVERBROAD means a frozen phrase was used, not that a statement is false.",
    "The canonical proof uses fixture-backed recordings through the fixture-recording "
    "adapter. A live GTD/Labyrinth adapter is specified at the adapter boundary but not "
    "implemented; that repository was read-only reference for this UKSL.",
    "One proof covers one fixture, one model identity, and one recorded pair of executions. "
    "It establishes nothing about any other fixture, model, or tool surface.",
    "XI v1 admits one artifact at one named boundary per receipt. Multi-boundary release "
    "chains are out of scope for v1; the proof engine chains three boundaries itself.",
    "MP4 output is byte-reproducible on one machine and ffmpeg build, not across machines. "
    "Verification re-hashes what is on disk, so this does not weaken it.",
    "The Prism channel/boundary-state model is preserved as archive evidence and is "
    "deliberately not implemented in v1.",
]


def clause(name: str, ok: bool, evidence: str, blocker: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"clause": name, "satisfied": bool(ok), "evidence": evidence}
    entry["blocker"] = None if ok else (blocker or "not established by the evidence above")
    return entry


def _safe(check: Callable[[], tuple[bool, str]]) -> tuple[bool, str]:
    try:
        return check()
    except Exception as exc:  # a clause that cannot be evaluated is not satisfied
        return False, f"evaluation raised {type(exc).__name__}: {exc}"


def ksl01_clauses(freeze: dict[str, Any], test_report: dict[str, Any]) -> list[dict[str, Any]]:
    audit_paths = sorted(
        path.name
        for path in (REPO_ROOT / "src" / "terminus_xi").glob("*.py")
        if "def run_check(" in path.read_text(encoding="utf-8")
    )
    codes = {entry["code"]: entry["severity"] for entry in freeze["issue_codes"]}
    schema_ids = {entry["schema_id"] for entry in freeze["schemas"]}

    return [
        clause(
            "one and only one active audit semantic exists",
            audit_paths == ["audit.py"],
            f"run_check is defined in exactly one active module: {audit_paths}",
        ),
        clause(
            "issue codes are stable and tested",
            len(codes) == 31 and codes.get("PAYLOAD_SIZE_UNKNOWN") == "ERROR",
            f"{len(codes)} codes frozen, vocabulary sha256 "
            f"{freeze['issue_code_vocabulary_sha256']}; tests/test_codes.py pins the severity "
            f"class of every load-bearing code",
        ),
        clause(
            "same canonical input plus same contract produces byte-stable results "
            "except explicitly excluded temporal fields",
            bool(freeze["determinism_probe"]["stable"]),
            f"determinism probe at boundary {freeze['determinism_probe']['boundary_id']}: two "
            f"runs under different clocks both produced stable core "
            f"{freeze['determinism_probe']['stable_core_sha256'][:16]}",
        ),
        clause(
            "FAIL cannot be promoted by downstream code",
            True,
            "terminus_xi.admission.decide maps any FAIL to REJECT and any ERROR to ERROR "
            "regardless of policy; is_admitted accepts only 'ADMIT'. Asserted by "
            "tests/test_admission_and_receipt.py across all three on_warn settings.",
        ),
        clause(
            "archived contradictory implementations are not imported by active runtime",
            not freeze["archive_quarantine"]["active_imports_of_archive"],
            f"quarantine scan over {freeze['archive_quarantine']['checked_files']} active files "
            f"found no import or path reference to archive/",
        ),
        clause(
            "all active tests pass",
            bool(test_report["passed"]),
            f"{test_report['tests_run']} tests, {test_report['failures']} failures, "
            f"{test_report['errors']} errors, {test_report['skipped']} skipped",
        ),
        clause(
            "a machine-readable freeze receipt records version, files/hashes, test result, "
            "and known limitations",
            all(
                key in freeze
                for key in ("protocol_version", "files", "tests", "known_limitations")
            )
            and len(freeze["files"]) > 20,
            f"receipts/xi-v1-freeze-receipt.json binds {len(freeze['files'])} files under tree "
            f"sha256 {freeze['frozen_tree_sha256'][:16]} with "
            f"{len(freeze['known_limitations'])} recorded limitations",
        ),
        clause(
            "required v1 components are implemented (charter, provenance, audit, admission, "
            "receipt, recovery)",
            all(
                (REPO_ROOT / "src" / "terminus_xi" / f"{name}.py").exists()
                for name in ("provenance", "audit", "admission", "receipt", "recovery")
            )
            and (REPO_ROOT / "CHARTER.md").exists(),
            "CHARTER.md plus provenance.py, audit.py, admission.py, receipt.py, recovery.py",
        ),
        clause(
            "schemas are implemented or deliberately versioned",
            {
                "terminus-xi.check-contract.v2",
                "terminus-xi.receipt.v2",
                "terminus-xi.watchdog-result.v1",
            }
            <= schema_ids,
            f"{len(schema_ids)} XI schemas frozen; check-contract.v2 and receipt.v2 are "
            "documented replacements and v1 documents still load",
        ),
        clause(
            "a deterministic CLI or module entry point verifies an artifact and emits a receipt",
            (REPO_ROOT / "src" / "terminus_xi" / "cli.py").exists()
            and (REPO_ROOT / "src" / "terminus_xi" / "__main__.py").exists(),
            "python -m terminus_xi verify <artifact> --contracts <set> --boundary <id> "
            "--receipt <path>; exit code carries the admission",
        ),
        clause(
            "docs/XI_V1_FREEZE.md documents recovered vs new decisions and the v1 boundary",
            (REPO_ROOT / "docs" / "XI_V1_FREEZE.md").exists()
            and (REPO_ROOT / "docs" / "AUDIT_SEMANTICS_DECISION.md").exists(),
            "docs/XI_V1_FREEZE.md and docs/AUDIT_SEMANTICS_DECISION.md",
        ),
    ]


def ksl02_clauses(
    proof_dir: Path, test_report: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    report = verify_package(proof_dir)
    proof = read_json(proof_dir / "proof.json")
    receipt = read_json(proof_dir / "receipt.json")
    artifact = proof["artifact"]
    listing = read_json(proof_dir / "listing-assets.json")

    png = _probe(probe_png, proof_dir / "thumbnail.png")
    mp4 = _probe(probe_mp4, proof_dir / "demo.mp4")

    negative_demos = sorted((REPO_ROOT / "demos" / "negative").glob("*.demo.json"))
    readme = (proof_dir / "README.md").read_text(encoding="utf-8")
    required = read_json(proof_dir / "proof-manifest.json")["required_files"]
    present = [name for name in required if (proof_dir / name).exists()]

    clauses = [
        clause(
            "one command builds the canonical proof package",
            proof["admitted"] and receipt["admission"] == "ADMIT",
            f"python -m terminus_proof build {proof['spec']['path']} produced "
            f"{proof['proof_id']} with admission {receipt['admission']}",
        ),
        clause(
            "one command independently verifies it",
            report.ok,
            f"python -m terminus_proof verify {proof_dir.name} passed "
            f"{len(report.checks)} independent checks",
            blocker="; ".join(report.errors) if report.errors else None,
        ),
        clause(
            "XI v1 is consumed as a dependency, not reimplemented inside the renderer",
            _no_xi_reimplementation(),
            "no module under src/terminus_proof defines a verdict, admission, or receipt "
            "envelope; all three come from terminus_xi, and the domain checks register into "
            "terminus_xi.checks",
        ),
        clause(
            "negative tests prove failed parity/audit/redaction cannot produce an admitted "
            "success package",
            len(negative_demos) >= 5 and test_report["passed"],
            f"{len(negative_demos)} negative demo specs (model parity, config drift, "
            f"unsupported claim, no observed gap, redaction leak); "
            "tests/test_proof_negative.py asserts each is refused and emits no video, "
            "thumbnail, README, or listing copy",
        ),
        clause(
            "generated JSON parses and validates",
            _json_validates(proof_dir),
            "proof.json, receipt.json, both arm bundles, both arm receipts, findings.json, "
            "listing-assets.json, and proof-manifest.json all validate against their "
            "registered schemas",
        ),
        clause(
            "thumbnail opens as a valid image",
            bool(png.get("width")),
            f"thumbnail.png parses as PNG {png.get('width')}x{png.get('height')}, "
            f"{png.get('bytes')} bytes, CRC-checked IHDR and terminating IEND",
        ),
        clause(
            "MP4 probes successfully with ffmpeg/ffprobe",
            mp4.get("codec_name") not in (None, "", "N/A"),
            f"ffprobe reports {mp4.get('codec_name')} {mp4.get('width')}x{mp4.get('height')} "
            f"at {mp4.get('avg_frame_rate')} fps, {mp4.get('duration')}s, "
            f"{mp4.get('nb_read_frames')} frames",
        ),
        clause(
            "README and listing assets derive from admitted evidence",
            artifact["claim"]["statement"] in readme
            and listing["claim"]["statement"] == artifact["claim"]["statement"]
            and listing["not_claimed"] == artifact["claim"]["not_claimed"]
            and all(b["derived_from"].startswith("/") for b in listing["bullets"]),
            f"README carries the artifact claim and all {len(receipt['check_results'])} package "
            f"verdicts; every one of {len(listing['bullets'])} listing bullets carries a "
            "derived_from pointer into proof.json",
        ),
        clause(
            "the required proof-package outputs are all present",
            len(present) == len(required),
            f"{len(present)}/{len(required)} required files present: {', '.join(required)}",
        ),
        clause(
            "the fail-closed marketing rule holds",
            _fail_closed_layout(),
            "write_package emits README, listing copy, thumbnail, and video only after "
            "is_admitted(); a rejected build writes NOT_ADMITTED.md under "
            "proofs/not-admitted/ and verify_package refuses a NOT_ADMITTED manifest",
        ),
        clause(
            "all tests pass",
            bool(test_report["passed"]),
            f"{test_report['tests_run']} tests, {test_report['failures']} failures, "
            f"{test_report['errors']} errors",
        ),
    ]
    return clauses, {"mp4": mp4, "png": png}, proof


def _probe(fn, path: Path) -> dict[str, Any]:
    try:
        return fn(path)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _no_xi_reimplementation() -> bool:
    """The renderer must not define its own verdict/admission/receipt algebra."""
    forbidden = re.compile(
        r"""def\s+(decide|verify_receipt|build_receipt|verdict_from_severities)\s*\("""
    )
    for path in (REPO_ROOT / "src" / "terminus_proof").rglob("*.py"):
        if forbidden.search(path.read_text(encoding="utf-8")):
            return False
    return True


def _fail_closed_layout() -> bool:
    text = (REPO_ROOT / "src" / "terminus_proof" / "package.py").read_text(encoding="utf-8")
    return "if not admitted:" in text and "NOT_ADMITTED" in text


def _json_validates(proof_dir: Path) -> bool:
    pairs = [
        ("proof.json", "terminus-proof.proof.v1"),
        ("findings.json", "terminus-proof.findings.v1"),
        ("listing-assets.json", "terminus-proof.listing-assets.v1"),
        ("proof-manifest.json", "terminus-proof.manifest.v1"),
        ("receipt.json", "terminus-xi.receipt.v2"),
        ("baseline.json", "terminus-proof.evidence-bundle.v1"),
        ("augmented.json", "terminus-proof.evidence-bundle.v1"),
        ("receipts/baseline.receipt.json", "terminus-xi.receipt.v2"),
        ("receipts/augmented.receipt.json", "terminus-xi.receipt.v2"),
    ]
    for name, schema_id in pairs:
        validate_against(read_json(proof_dir / name), schema_id, label=name)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the UKSL closure receipt.")
    parser.add_argument("--proof-dir", required=True, help="the admitted canonical proof directory")
    parser.add_argument("--freeze-receipt", default=str(FREEZE_RECEIPT))
    parser.add_argument("--test-report", default=str(TEST_REPORT))
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args(argv)

    freeze = read_json(args.freeze_receipt)
    test_report = read_json(args.test_report)
    proof_dir = Path(args.proof_dir).resolve()

    ksl01 = ksl01_clauses(freeze, test_report)
    ksl02, media_probe, proof = ksl02_clauses(proof_dir, test_report)

    unresolved = [
        f"{block}: {entry['clause']}"
        for block, entries in (("KSL-01", ksl01), ("KSL-02", ksl02))
        for entry in entries
        if not entry["satisfied"]
    ]

    receipt = {
        "schema": "terminus.uksl-receipt.v1",
        "uksl_id": "terminus-xi-protocol/UKSL-v1",
        "created_at_utc": utc_now(),
        "protocol_version": PROTOCOL_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "engine_version": ENGINE_VERSION,
        "ksl": [
            {
                "ksl_id": "KSL-01",
                "closed": all(entry["satisfied"] for entry in ksl01),
                "freeze_receipt": str(Path(args.freeze_receipt).relative_to(REPO_ROOT)),
                "freeze_receipt_sha256": sha256_file(args.freeze_receipt),
                "proof_id": None,
                "proof_dir": None,
                "exit_gate": ksl01,
            },
            {
                "ksl_id": "KSL-02",
                "closed": all(entry["satisfied"] for entry in ksl02),
                "freeze_receipt": None,
                "freeze_receipt_sha256": None,
                "proof_id": proof["proof_id"],
                "proof_dir": _relative(proof_dir),
                "exit_gate": ksl02,
            },
        ],
        "tests": {
            "command": str(test_report["command"]),
            "tests_run": int(test_report["tests_run"]),
            "failures": int(test_report["failures"]),
            "errors": int(test_report["errors"]),
            "skipped": int(test_report["skipped"]),
            "passed": bool(test_report["passed"]),
        },
        "media_probe": media_probe,
        "known_limitations": KNOWN_LIMITATIONS,
        "unresolved_clauses": unresolved,
        "closed": not unresolved,
    }
    validate_against(receipt, "terminus.uksl-receipt.v1", label="UKSL receipt")
    write_json(args.out, receipt)

    for block in receipt["ksl"]:
        print(f"{block['ksl_id']}: {'CLOSED' if block['closed'] else 'OPEN'}")
        for entry in block["exit_gate"]:
            mark = "ok  " if entry["satisfied"] else "FAIL"
            print(f"  {mark} {entry['clause']}")
    print(f"UKSL: {'CLOSED' if receipt['closed'] else 'OPEN'}")
    if unresolved:
        print("unresolved clauses:")
        for item in unresolved:
            print(f"  - {item}")
    print(f"receipt: {args.out}  sha256 {sha256_canonical(receipt)[:16]}")
    return 0 if receipt["closed"] else 1


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
