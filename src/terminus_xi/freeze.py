"""Build the machine-readable Terminus XI v1 freeze receipt.

The freeze receipt records what was frozen (files and digests), the frozen
issue-code vocabulary, the frozen schemas, the result of the active test suite,
a determinism probe, an archive-quarantine scan, and the known limitations of
v1. It is evidence, not decoration: every field is recomputable from the tree.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import PROTOCOL_VERSION, RUNTIME_VERSION
from .admission import AdmissionPolicy
from .canonical import read_json, sha256_canonical, sha256_file, utc_now
from .checks import registered_names
from .codes import ISSUE_CODES
from .contracts import load_contract_set
from .engine import verify_artifact
from .schemas import XI_SCHEMA_FILES, schema_path, spec_dir

__all__ = ["build_freeze_receipt", "repo_root", "frozen_files"]

# The XI v1 boundary: the runtime package, the machine-readable protocol
# contracts, and the self-check contract set and policy the determinism probe
# depends on. The proof engine (src/terminus_proof) and its domain contracts are
# deliberately outside it: KSL-02 consumes XI, it is not part of XI.
FROZEN_GLOBS = (
    "src/terminus_xi/*.py",
    "src/terminus_xi/checks/*.py",
    "contracts/xi-selftest.contracts.json",
    "policies/xi-selftest.policy.json",
)

KNOWN_LIMITATIONS = [
    "Receipts are integrity documents, not signed attestations. They detect "
    "edits and incompleteness; they do not authenticate the producer.",
    "A digest establishes identity of the covered bytes only. It proves nothing "
    "about truth, safety, authorship, authority, or semantic correctness.",
    "Claim-boundary style checks are bounded lexical and structural predicates "
    "over declared evidence. They cannot determine whether a statement is true.",
    "XI v1 admits exactly one artifact at one named boundary per receipt. "
    "Multi-boundary release chains are out of scope for v1.",
    "terminus-xi.check-contract.v1 documents are accepted and upgraded in "
    "memory, but new contracts should be authored as v2.",
    "The historical Prism channel/boundary-state model is preserved as archive "
    "evidence and is deliberately not implemented in v1.",
    "TERMINUS_XI_NOW overrides the receipt clock for reproducible builds. It is "
    "a build convenience and carries no authority.",
]

_ARCHIVE_IMPORT = re.compile(r"^\s*(?:from|import)\s+.*\barchive\b", re.MULTILINE)
_ARCHIVE_PATH = re.compile(r"""["']archive/""")


def repo_root() -> Path:
    override = os.environ.get("TERMINUS_XI_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return spec_dir().parent


def frozen_files(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or repo_root()
    seen: dict[str, Path] = {}
    for pattern in FROZEN_GLOBS:
        for path in sorted(base.glob(pattern)):
            if "__pycache__" in path.parts:
                continue
            seen[str(path.relative_to(base))] = path
    for filename in sorted(set(XI_SCHEMA_FILES.values())):
        path = base / "spec" / filename
        if path.exists():
            seen[str(path.relative_to(base))] = path
    return [
        {
            "path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for relative, path in sorted(seen.items())
    ]


def _quarantine_scan(root: Path, extra_globs: Iterable[str] = ()) -> dict[str, Any]:
    """Confirm no active runtime file imports or reads archived material."""
    offenders: list[str] = []
    checked = 0
    patterns = ("src/**/*.py", "tools/*.py", "tests/*.py", *extra_globs)
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if "__pycache__" in path.parts:
                continue
            checked += 1
            text = path.read_text(encoding="utf-8")
            if _ARCHIVE_IMPORT.search(text) or _ARCHIVE_PATH.search(text):
                offenders.append(str(path.relative_to(root)))
    return {"active_imports_of_archive": offenders, "checked_files": checked}


def _determinism_probe(root: Path) -> dict[str, Any]:
    """Verify the same artifact and contract set twice under different clocks."""
    contract_set = load_contract_set(root / "contracts" / "xi-selftest.contracts.json")
    policy = AdmissionPolicy(policy_id="terminus-xi.selftest", version="1.0.0", on_warn="REVIEW")
    artifact = {"kind": "selftest", "records": [{"id": "a"}, {"id": "b"}]}

    previous = os.environ.get("TERMINUS_XI_NOW")
    try:
        os.environ["TERMINUS_XI_NOW"] = "2000-01-01T00:00:00Z"
        first = verify_artifact(
            artifact, boundary_id="xi.selftest", contract_set=contract_set, policy=policy
        ).receipt
        os.environ["TERMINUS_XI_NOW"] = "2031-12-31T23:59:59Z"
        second = verify_artifact(
            artifact, boundary_id="xi.selftest", contract_set=contract_set, policy=policy
        ).receipt
    finally:
        if previous is None:
            os.environ.pop("TERMINUS_XI_NOW", None)
        else:
            os.environ["TERMINUS_XI_NOW"] = previous

    return {
        "boundary_id": "xi.selftest",
        "stable_core_sha256": first["stable_core_sha256"],
        "repeat_stable_core_sha256": second["stable_core_sha256"],
        "stable": first["stable_core_sha256"] == second["stable_core_sha256"],
    }


def build_freeze_receipt(
    *,
    test_report: Mapping[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    base = root or repo_root()
    files = frozen_files(base)
    vocabulary = [
        {"code": code.code, "severity": code.severity, "category": code.category}
        for code in sorted(ISSUE_CODES.values(), key=lambda item: item.code)
    ]
    schemas = []
    for schema_id in sorted(XI_SCHEMA_FILES):
        path = schema_path(schema_id)
        if not path.exists():
            continue
        schemas.append(
            {
                "schema_id": schema_id,
                "path": str(path.relative_to(base)),
                "sha256": sha256_file(path),
            }
        )

    receipt: dict[str, Any] = {
        "schema": "terminus-xi.freeze-receipt.v1",
        "protocol_version": PROTOCOL_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "created_at_utc": utc_now(),
        "frozen_tree_sha256": sha256_canonical(files),
        "files": files,
        "issue_codes": vocabulary,
        "issue_code_vocabulary_sha256": sha256_canonical(vocabulary),
        "schemas": schemas,
        "registered_checks": registered_names(),
        "tests": {
            "command": str(test_report["command"]),
            "tests_run": int(test_report["tests_run"]),
            "failures": int(test_report["failures"]),
            "errors": int(test_report["errors"]),
            "skipped": int(test_report["skipped"]),
            "passed": bool(test_report["passed"]),
        },
        "determinism_probe": _determinism_probe(base),
        "archive_quarantine": _quarantine_scan(base),
        "known_limitations": list(KNOWN_LIMITATIONS),
    }
    return receipt


def load_test_report(path: str | Path) -> Mapping[str, Any]:
    return read_json(path)
