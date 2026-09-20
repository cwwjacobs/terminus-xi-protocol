"""Terminus Proof - automated documentation and proof engine.

The engine executes or ingests a controlled baseline-vs-capability pair,
submits the evidence to frozen Terminus XI v1, and emits documentation and
media only for what XI admitted.

XI semantics are consumed, never reimplemented here. Every verdict, admission
decision, and receipt in a proof package is produced by ``terminus_xi``.
"""

from __future__ import annotations

from terminus_xi.schemas import register_schema

ENGINE_VERSION = "terminus-proof/1.0.0"

#: Schemas this engine owns. XI does not know about them; they are registered
#: into XI's loader here so that a proof document can be validated by the same
#: deterministic validator that validates a receipt.
PROOF_SCHEMA_FILES = {
    "terminus-proof.demo-spec.v1": "demo-spec.schema.json",
    "terminus-proof.redaction-policy.v1": "redaction-policy.schema.json",
    "terminus-proof.evidence-bundle.v1": "evidence-bundle.schema.json",
    "terminus-proof.claim-report.v1": "claim-report.schema.json",
    "terminus-proof.proof.v1": "proof.schema.json",
    "terminus-proof.proof-artifact.v1": "proof-artifact.schema.json",
    "terminus-proof.proof-arm.v1": "proof-arm.schema.json",
    "terminus-proof.projected-arm.v1": "projected-arm.schema.json",
    "terminus-proof.identified-document.v1": "identified-document.schema.json",
    "terminus-proof.findings.v1": "findings.schema.json",
    "terminus-proof.listing-assets.v1": "listing-assets.schema.json",
    "terminus-proof.manifest.v1": "proof-manifest.schema.json",
    "terminus.uksl-receipt.v1": "uksl-receipt.schema.json",
}

for _schema_id, _filename in PROOF_SCHEMA_FILES.items():
    register_schema(_schema_id, _filename)

REQUIRED_PACKAGE_FILES = (
    "README.md",
    "augmented.json",
    "baseline.json",
    "demo.mp4",
    "findings.json",
    "listing-assets.json",
    "proof.json",
    "receipt.json",
    "thumbnail.png",
    "transcript.txt",
)

__all__ = ["ENGINE_VERSION", "PROOF_SCHEMA_FILES", "REQUIRED_PACKAGE_FILES"]
