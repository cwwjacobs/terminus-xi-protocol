"""Write a proof directory, and verify one independently of the writer.

``write_package`` is the only place that turns a :class:`ProofBuild` into files,
and it refuses to write documentation or media unless XI admitted the package.

``verify_package`` never imports the build. It re-reads the directory from
scratch, re-derives every identity it can, re-runs the frozen contract sets, and
re-checks each receipt against its own recorded findings. A missing file, an
extra file, an edited byte, a swapped receipt, a widened admission, or a
surviving sensitive value all make it fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from terminus_xi import PROTOCOL_VERSION, RUNTIME_VERSION
from terminus_xi.admission import decide, is_admitted, load_policy
from terminus_xi.audit import run_contract_set
from terminus_xi.canonical import (
    read_json,
    sha256_canonical,
    sha256_file,
    utc_now,
    write_json,
    write_text,
)
from terminus_xi.contracts import ContractSet, load_contract_set
from terminus_xi.receipt import verify_receipt
from terminus_xi.schemas import SchemaError, validate_against

from . import ENGINE_VERSION, REQUIRED_PACKAGE_FILES
from . import checks as _domain_checks  # noqa: F401  (registers the proof checks)
from .docs_render import (
    render_findings,
    render_listing_assets,
    render_not_admitted,
    render_readme,
    render_transcript,
)
from .engine import ProofBuild
from .media import MediaError, probe_mp4, probe_png, render_media
from .redaction import scan_denied

__all__ = ["PackageResult", "VerifyReport", "write_package", "verify_package"]

MANIFEST_NAME = "proof-manifest.json"
NOT_ADMITTED_DIR = "not-admitted"
_MEDIA_TYPES = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".mp4": "video/mp4",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
    ".concat": "text/plain",
}


@dataclass(frozen=True)
class PackageResult:
    proof_id: str
    directory: Path
    admitted: bool
    admission: str
    files: tuple[str, ...]


@dataclass
class VerifyReport:
    directory: Path
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    proof_id: str | None = None
    admission: str | None = None

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def passed(self, message: str) -> None:
        self.checks.append(message)

    def raise_for_status(self) -> None:
        if not self.ok:
            raise ValueError(
                f"proof verification failed for {self.directory}:\n  - "
                + "\n  - ".join(self.errors)
            )


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def _relative_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    )


def _manifest(directory: Path, proof_id: str, admission: str, required: Sequence[str]) -> dict[str, Any]:
    entries = []
    for path in _relative_files(directory):
        entries.append(
            {
                "path": str(path.relative_to(directory)),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "media_type": _MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
            }
        )
    entries.sort(key=lambda entry: entry["path"])
    return {
        "schema": "terminus-proof.manifest.v1",
        "proof_id": proof_id,
        "state": "ADMITTED" if admission == "ADMIT" else "NOT_ADMITTED",
        "admission": admission,
        "engine_version": ENGINE_VERSION,
        "created_at_utc": utc_now(),
        "required_files": sorted(required),
        "files": entries,
        "files_sha256": sha256_canonical(entries),
    }


def _boundaries(build: ProofBuild) -> list[dict[str, Any]]:
    rows = []
    for arm_id in ("baseline", "augmented"):
        receipt = build.arms[arm_id].receipt
        rows.append(
            {
                "boundary_id": receipt["boundary_id"],
                "admission": receipt["admission"],
                "receipt_path": f"receipts/{arm_id}.receipt.json",
                "receipt_sha256": receipt["receipt_sha256"],
                "stable_core_sha256": receipt["stable_core_sha256"],
            }
        )
    package = build.package.receipt
    rows.append(
        {
            "boundary_id": package["boundary_id"],
            "admission": package["admission"],
            "receipt_path": "receipt.json",
            "receipt_sha256": package["receipt_sha256"],
            "stable_core_sha256": package["stable_core_sha256"],
        }
    )
    return rows


def write_package(
    build: ProofBuild,
    *,
    out_root: Path,
    render: bool = True,
) -> PackageResult:
    """Write the proof directory. Media and documentation require ``ADMIT``."""
    admitted = build.admitted
    directory = (
        out_root / build.proof_id if admitted else out_root / NOT_ADMITTED_DIR / build.proof_id
    )
    if directory.exists():
        _clear(directory)
    (directory / "receipts").mkdir(parents=True, exist_ok=True)
    (directory / "contracts").mkdir(parents=True, exist_ok=True)
    (directory / "policies").mkdir(parents=True, exist_ok=True)

    proof = {
        "schema": "terminus-proof.proof.v1",
        "proof_id": build.proof_id,
        "demo_id": build.spec.demo_id,
        "built_at_utc": utc_now(),
        "engine_version": ENGINE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "admitted": admitted,
        "artifact_sha256": build.artifact_sha256,
        "artifact": dict(build.artifact),
        "spec": {
            "demo_id": build.spec.demo_id,
            "path": _spec_path(build),
            "sha256": build.spec.sha256,
        },
        "boundaries": _boundaries(build),
    }
    validate_against(proof, "terminus-proof.proof.v1", label="proof envelope")

    write_json(directory / "proof.json", proof)
    write_json(directory / "receipt.json", build.package.receipt)
    for arm_id in ("baseline", "augmented"):
        write_json(directory / f"{arm_id}.json", build.arm_documents[arm_id])
        write_json(directory / "receipts" / f"{arm_id}.receipt.json", build.arms[arm_id].receipt)

    write_json(directory / "contracts" / "arm-contract-set.json", build.contract_sets["arm"].to_dict())
    write_json(
        directory / "contracts" / "package-contract-set.json", build.contract_sets["package"].to_dict()
    )
    write_json(directory / "policies" / "arm-policy.json", _policy_document(build, "arm"))
    write_json(directory / "policies" / "package-policy.json", _policy_document(build, "package"))

    findings = render_findings(
        build.proof_id,
        [
            (arm_id, build.arms[arm_id].receipt) for arm_id in ("baseline", "augmented")
        ]
        + [("package", build.package.receipt)],
    )
    validate_against(findings, "terminus-proof.findings.v1", label="findings index")
    write_json(directory / "findings.json", findings)
    write_text(directory / "transcript.txt", render_transcript(build.artifact, build.proof_id))

    if not admitted:
        write_text(
            directory / "NOT_ADMITTED.md",
            render_not_admitted(
                artifact=build.artifact,
                receipt=build.package.receipt,
                proof_id=build.proof_id,
                spec_path=_spec_path(build),
            ),
        )
        manifest = _manifest(directory, build.proof_id, build.admission, ("proof.json", "receipt.json"))
        write_json(directory / MANIFEST_NAME, manifest)
        return PackageResult(
            proof_id=build.proof_id,
            directory=directory,
            admitted=False,
            admission=build.admission,
            files=tuple(entry["path"] for entry in manifest["files"]),
        )

    arm_receipts = {arm_id: build.arms[arm_id].receipt for arm_id in ("baseline", "augmented")}
    write_text(
        directory / "README.md",
        render_readme(
            artifact=build.artifact,
            proof=proof,
            receipt=build.package.receipt,
            arm_receipts=arm_receipts,
            spec_path=_spec_path(build),
        ),
    )
    listing = render_listing_assets(
        artifact=build.artifact,
        proof=proof,
        receipt=build.package.receipt,
        arm_receipts=arm_receipts,
    )
    validate_against(listing, "terminus-proof.listing-assets.v1", label="listing assets")
    write_json(directory / "listing-assets.json", listing)

    if render:
        render_media(
            artifact=build.artifact,
            receipt=build.package.receipt,
            out_dir=directory,
            work_dir=directory / "media",
        )

    manifest = _manifest(directory, build.proof_id, build.admission, REQUIRED_PACKAGE_FILES)
    write_json(directory / MANIFEST_NAME, manifest)

    return PackageResult(
        proof_id=build.proof_id,
        directory=directory,
        admitted=True,
        admission=build.admission,
        files=tuple(entry["path"] for entry in manifest["files"]),
    )


def _spec_path(build: ProofBuild) -> str:
    try:
        return str(build.spec.path.relative_to(build.spec.root))
    except ValueError:
        return str(build.spec.path)


def _policy_document(build: ProofBuild, which: str) -> dict[str, Any]:
    path = build.spec.resolve(build.spec.document["checks"][f"{which}_policy"])
    return read_json(path)


def _clear(directory: Path) -> None:
    for path in sorted(directory.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            path.rmdir()


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------


def verify_package(directory: str | Path) -> VerifyReport:
    """Independently establish that a proof directory is complete and honest."""
    base = Path(directory).resolve()
    report = VerifyReport(directory=base)
    if not base.is_dir():
        report.fail(f"{base} is not a directory")
        return report

    manifest_path = base / MANIFEST_NAME
    if not manifest_path.exists():
        report.fail(f"{MANIFEST_NAME} is missing; the package cannot be checked for completeness")
        return report
    manifest = read_json(manifest_path)
    try:
        validate_against(manifest, "terminus-proof.manifest.v1", label="manifest")
    except SchemaError as exc:
        report.fail(str(exc))
        return report
    report.proof_id = str(manifest["proof_id"])
    report.admission = str(manifest.get("admission", ""))

    if not _verify_files(base, manifest, report):
        return report
    if manifest["state"] != "ADMITTED":
        report.fail(
            f"package state is {manifest['state']}; a non-admitted attempt is not a proof and "
            "must not be presented as one"
        )
        return report

    proof = read_json(base / "proof.json")
    try:
        validate_against(proof, "terminus-proof.proof.v1", label="proof envelope")
    except SchemaError as exc:
        report.fail(str(exc))
        return report
    report.passed("proof.json validates against terminus-proof.proof.v1")

    artifact = proof["artifact"]
    artifact_sha256 = sha256_canonical(artifact)
    if artifact_sha256 != proof["artifact_sha256"]:
        report.fail(
            f"proof.json records artifact_sha256 {proof['artifact_sha256']} but the embedded "
            f"artifact hashes to {artifact_sha256}"
        )
    expected_id = f"{artifact['demo_id']}-{artifact_sha256[:12]}"
    if proof["proof_id"] != expected_id:
        report.fail(
            f"proof id {proof['proof_id']!r} is not the one this artifact derives ({expected_id!r})"
        )
    if manifest["proof_id"] != proof["proof_id"]:
        report.fail("manifest and proof.json disagree about the proof id")
    if artifact_sha256 == proof["artifact_sha256"] and proof["proof_id"] == expected_id:
        report.passed("artifact digest and proof id re-derive from the artifact itself")

    receipt = read_json(base / "receipt.json")
    _verify_receipt_document(receipt, artifact_sha256, "package", report)
    if not is_admitted(str(receipt.get("admission", ""))):
        report.fail(
            f"package receipt admission is {receipt.get('admission')!r}; only ADMIT is admitted"
        )
    if not proof.get("admitted"):
        report.fail("proof.json does not record the package as admitted")

    _verify_arms(base, artifact, report)
    _verify_boundaries(base, proof, report)
    package_contracts = _verify_recheck(base, artifact, receipt, report)
    _verify_arm_recheck(base, artifact, report)
    _verify_redaction(base, artifact, report)
    _verify_projections(base, proof, artifact, receipt, report)
    _verify_media(base, report)

    if package_contracts is not None:
        report.passed(
            f"package contract set {package_contracts.set_id} re-evaluated to the recorded verdicts"
        )
    return report


def _verify_files(base: Path, manifest: Mapping[str, Any], report: VerifyReport) -> bool:
    listed = {entry["path"]: entry for entry in manifest["files"]}
    present = {str(path.relative_to(base)) for path in _relative_files(base)}

    missing_required = [name for name in manifest["required_files"] if name not in listed]
    if missing_required:
        report.fail(f"manifest does not list required files {missing_required}")

    absent = sorted(set(listed) - present)
    if absent:
        report.fail(f"files listed in the manifest are missing from the directory: {absent}")
    extra = sorted(present - set(listed))
    if extra:
        report.fail(f"directory contains files the manifest does not list: {extra}")

    for name in sorted(set(listed) & present):
        entry = listed[name]
        path = base / name
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            report.fail(f"{name} has digest {actual[:16]} but the manifest records {entry['sha256'][:16]}")
        size = path.stat().st_size
        if size != entry["bytes"]:
            report.fail(f"{name} is {size} bytes but the manifest records {entry['bytes']}")

    if sha256_canonical(manifest["files"]) != manifest["files_sha256"]:
        report.fail("files_sha256 does not match the manifest file list")

    if report.ok:
        report.passed(f"{len(listed)} files present, complete, and unmodified")
    return report.ok


def _verify_receipt_document(
    receipt: Mapping[str, Any], artifact_sha256: str | None, label: str, report: VerifyReport
) -> None:
    verification = verify_receipt(receipt, artifact_sha256=artifact_sha256)
    if not verification.ok:
        for error in verification.errors:
            report.fail(f"{label} receipt: {error}")
    else:
        report.passed(f"{label} receipt is internally consistent and covers its artifact")


def _verify_arms(base: Path, artifact: Mapping[str, Any], report: VerifyReport) -> None:
    for arm_id in ("baseline", "augmented"):
        arm = artifact["arms"][arm_id]
        document = read_json(base / f"{arm_id}.json")
        digest = sha256_canonical(document)
        if digest != arm["document_sha256"]:
            report.fail(
                f"{arm_id}.json hashes to {digest[:16]} but the artifact binds "
                f"{arm['document_sha256'][:16]}"
            )
            continue
        if sha256_canonical(arm["evidence"]) != digest:
            report.fail(f"{arm_id}.json differs from the evidence embedded in the artifact")
            continue

        receipt_path = base / "receipts" / f"{arm_id}.receipt.json"
        if not receipt_path.exists():
            report.fail(f"arm receipt {receipt_path.name} is missing")
            continue
        arm_receipt = read_json(receipt_path)
        _verify_receipt_document(arm_receipt, digest, f"arm {arm_id}", report)
        if arm_receipt["admission"] != arm["xi"]["admission"]:
            report.fail(
                f"arm {arm_id} receipt records admission {arm_receipt['admission']} but the "
                f"artifact records {arm['xi']['admission']}"
            )
        if arm_receipt["stable_core_sha256"] != arm["xi"]["stable_core_sha256"]:
            report.fail(
                f"arm {arm_id} receipt stable core does not match the digest the artifact binds"
            )
        report.passed(f"arm {arm_id} file, evidence, and receipt agree by digest")


def _verify_boundaries(base: Path, proof: Mapping[str, Any], report: VerifyReport) -> None:
    for boundary in proof["boundaries"]:
        path = base / boundary["receipt_path"]
        if not path.exists():
            report.fail(f"boundary {boundary['boundary_id']} names a missing receipt {path.name}")
            continue
        receipt = read_json(path)
        if receipt["receipt_sha256"] != boundary["receipt_sha256"]:
            report.fail(
                f"boundary {boundary['boundary_id']} records a receipt digest that the file "
                "does not carry"
            )
        if receipt["boundary_id"] != boundary["boundary_id"]:
            report.fail(
                f"{boundary['receipt_path']} is a receipt for {receipt['boundary_id']}, not "
                f"{boundary['boundary_id']}"
            )
        if receipt["admission"] != boundary["admission"]:
            report.fail(f"boundary {boundary['boundary_id']} misreports its admission")
    report.passed(f"{len(proof['boundaries'])} boundary receipts are the ones proof.json names")


def _load_snapshot(
    base: Path, relative: str, expected_sha256: str, label: str, report: VerifyReport
) -> ContractSet | None:
    path = base / relative
    if not path.exists():
        report.fail(f"{label} snapshot {relative} is missing")
        return None
    document = read_json(path)
    if sha256_canonical(document) != expected_sha256:
        report.fail(
            f"{label} snapshot {relative} does not match the digest the artifact binds; "
            "the contracts in this package are not the ones it was judged against"
        )
        return None
    return load_contract_set(document)


def _verify_recheck(
    base: Path, artifact: Mapping[str, Any], receipt: Mapping[str, Any], report: VerifyReport
) -> ContractSet | None:
    contracts = _load_snapshot(
        base,
        "contracts/package-contract-set.json",
        artifact["contract_sets"]["package"]["sha256"],
        "package contract set",
        report,
    )
    if contracts is None:
        return None
    if contracts.sha256() != receipt["contract_set_sha256"]:
        report.fail("the package receipt was produced under a different contract set")
        return None

    policy_path = base / "policies" / "package-policy.json"
    if not policy_path.exists():
        report.fail("policies/package-policy.json is missing")
        return None
    policy = load_policy(policy_path)
    if policy.sha256() != receipt.get("policy_sha256"):
        report.fail("the package receipt was produced under a different admission policy")
        return None

    results = run_contract_set(contracts, artifact)
    recorded = {result["check_id"]: result for result in receipt["check_results"]}
    for result in results:
        stored = recorded.get(result.check_id)
        if stored is None:
            report.fail(f"receipt records no result for {result.check_id}")
            continue
        if stored["verdict"] != result.verdict:
            report.fail(
                f"re-running {result.check_id} gives {result.verdict} but the receipt records "
                f"{stored['verdict']}"
            )
        if sorted({item["code"] for item in stored["findings"]}) != sorted(set(result.codes())):
            report.fail(f"re-running {result.check_id} produces different finding codes")

    decision = decide(results, policy)
    if decision.admission != receipt["admission"]:
        report.fail(
            f"re-deciding admission from the re-run results gives {decision.admission} but the "
            f"receipt records {receipt['admission']}"
        )
    return contracts


def _verify_arm_recheck(base: Path, artifact: Mapping[str, Any], report: VerifyReport) -> None:
    contracts = _load_snapshot(
        base,
        "contracts/arm-contract-set.json",
        artifact["contract_sets"]["arm"]["sha256"],
        "arm contract set",
        report,
    )
    if contracts is None:
        return
    policy_path = base / "policies" / "arm-policy.json"
    if not policy_path.exists():
        report.fail("policies/arm-policy.json is missing")
        return
    policy = load_policy(policy_path)

    for arm_id in ("baseline", "augmented"):
        document = read_json(base / f"{arm_id}.json")
        results = run_contract_set(contracts, document)
        decision = decide(results, policy)
        recorded = artifact["arms"][arm_id]["xi"]
        if decision.admission != recorded["admission"]:
            report.fail(
                f"re-running the arm contract set over {arm_id}.json gives "
                f"{decision.admission} but the artifact records {recorded['admission']}"
            )
        rerun = [
            {
                "check_id": result.check_id,
                "verdict": result.verdict,
                "codes": sorted(set(result.codes())),
            }
            for result in results
        ]
        if rerun != [dict(row) for row in recorded["verdicts"]]:
            report.fail(f"re-running the arm contract set over {arm_id}.json changes the verdicts")
    report.passed("both arm files re-evaluate to the verdicts and admissions the artifact records")


def _verify_redaction(base: Path, artifact: Mapping[str, Any], report: VerifyReport) -> None:
    patterns = artifact["redaction"]["deny_patterns"]
    surfaces: dict[str, Any] = {
        "public_projection": artifact["public_projection"],
        "baseline": read_json(base / "baseline.json"),
        "augmented": read_json(base / "augmented.json"),
    }
    for name in ("README.md", "transcript.txt"):
        path = base / name
        if path.exists():
            surfaces[name] = path.read_text(encoding="utf-8")
    listing = base / "listing-assets.json"
    if listing.exists():
        surfaces["listing-assets.json"] = read_json(listing)

    hits = scan_denied(surfaces, patterns)
    for hit in hits:
        report.fail(
            f"deny pattern {hit['pattern_id']!r} ({hit['description']}) matches published "
            f"content at {hit['location']}"
        )
    if not hits:
        report.passed(
            f"{len(surfaces)} published surfaces scanned against {len(patterns)} deny patterns "
            "with no match"
        )


def _verify_projections(
    base: Path,
    proof: Mapping[str, Any],
    artifact: Mapping[str, Any],
    receipt: Mapping[str, Any],
    report: VerifyReport,
) -> None:
    findings = read_json(base / "findings.json")
    try:
        validate_against(findings, "terminus-proof.findings.v1", label="findings index")
    except SchemaError as exc:
        report.fail(str(exc))
        return
    if findings["proof_id"] != proof["proof_id"]:
        report.fail("findings.json belongs to a different proof")
    receipt_digests = {row["receipt_sha256"] for row in proof["boundaries"]}
    for boundary in findings["boundaries"]:
        if boundary["receipt_sha256"] not in receipt_digests:
            report.fail(
                f"findings.json cites receipt {boundary['receipt_sha256'][:16]} which this "
                "package does not contain"
            )

    listing_path = base / "listing-assets.json"
    if listing_path.exists():
        listing = read_json(listing_path)
        try:
            validate_against(listing, "terminus-proof.listing-assets.v1", label="listing assets")
        except SchemaError as exc:
            report.fail(str(exc))
            return
        if listing["proof_id"] != proof["proof_id"]:
            report.fail("listing-assets.json belongs to a different proof")
        if listing["admitted"] is not (receipt["admission"] == "ADMIT"):
            report.fail("listing-assets.json disagrees with the receipt about admission")
        if listing["claim"]["statement"] != artifact["claim"]["statement"]:
            report.fail("listing copy states a claim the artifact does not carry")
        if listing["not_claimed"] != list(artifact["claim"]["not_claimed"]):
            report.fail("listing copy drops or alters the artifact's not-claimed list")

    readme = base / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        for required in (
            proof["proof_id"],
            receipt["admission"],
            artifact["claim"]["statement"],
            receipt["receipt_sha256"][:16],
        ):
            if required not in text:
                report.fail(f"README.md does not carry {required[:48]!r} from the admitted evidence")
    report.passed("documentation and listing copy derive from the admitted artifact and receipts")


def _verify_media(base: Path, report: VerifyReport) -> None:
    thumbnail = base / "thumbnail.png"
    video = base / "demo.mp4"
    try:
        probed_png = probe_png(thumbnail)
        report.passed(
            f"thumbnail.png is a valid PNG ({probed_png['width']}x{probed_png['height']})"
        )
    except (MediaError, OSError) as exc:
        report.fail(str(exc))
    try:
        probed_mp4 = probe_mp4(video)
        detail = probed_mp4.get("codec_name", probed_mp4.get("prober"))
        report.passed(f"demo.mp4 probes as a valid MP4 ({detail})")
    except (MediaError, OSError) as exc:
        report.fail(str(exc))
