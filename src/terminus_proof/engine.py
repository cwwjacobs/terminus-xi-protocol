"""Build a proof from a demo specification.

The build is a straight line with three XI boundaries in it:

1. run both arms through their adapters;
2. redact once, over both arms together;
3. submit each arm to the XI *arm* boundary and keep the receipt;
4. assemble the package artifact from what the arms recorded and what XI said;
5. submit the artifact to the XI *package* boundary;
6. only then render documentation and media.

Step 6 is reachable only from an ``ADMIT`` at step 5. A rejected build writes a
clearly-marked diagnostic package instead, and writes no video, no thumbnail,
no README, and no listing copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from terminus_xi import PROTOCOL_VERSION, RUNTIME_VERSION
from terminus_xi.admission import AdmissionPolicy, is_admitted, load_policy
from terminus_xi.canonical import read_json, sha256_canonical
from terminus_xi.contracts import ContractSet, load_contract_set
from terminus_xi.engine import VerificationOutcome, verify_artifact
from terminus_xi.provenance import build_provenance
from terminus_xi.schemas import SchemaError, validate_against

from . import ENGINE_VERSION
from . import checks as _domain_checks  # noqa: F401  (registers the proof checks)
from .adapters import RawExecution, get_adapter
from .redaction import RedactionOutcome, RedactionPolicy, apply_policy, load_redaction_policy
from .spec import DemoSpec

__all__ = ["BuildError", "ProofBuild", "build_proof"]

ARM_BOUNDARY = "proof.arm.{arm_id}"
PACKAGE_BOUNDARY = "proof.package"


class BuildError(RuntimeError):
    """The proof could not be assembled at all."""


@dataclass(frozen=True)
class ProofBuild:
    """Everything one build produced, admitted or not."""

    proof_id: str
    spec: DemoSpec
    artifact: Mapping[str, Any]
    artifact_sha256: str
    package: VerificationOutcome
    arms: Mapping[str, VerificationOutcome]
    arm_documents: Mapping[str, Mapping[str, Any]]
    transcripts: Mapping[str, Sequence[Mapping[str, Any]]]
    contract_sets: Mapping[str, ContractSet]

    @property
    def admitted(self) -> bool:
        return is_admitted(self.package.decision)

    @property
    def admission(self) -> str:
        return self.package.admission


def _identified(document_id: str, version: str, value: Any, path: str | None) -> dict[str, Any]:
    return {
        "id": document_id,
        "version": version,
        "sha256": sha256_canonical(value),
        "path": path,
    }


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _pre_redaction_document(
    fixture: Mapping[str, Any],
    executions: Mapping[str, RawExecution],
) -> dict[str, Any]:
    """One document holding everything that must be cleaned, cleaned once."""
    return {
        "evidence": [dict(item) for item in fixture.get("evidence", [])],
        "arms": {
            arm_id: {
                "output": dict(execution.output),
                "transcript": [dict(step) for step in execution.transcript],
            }
            for arm_id, execution in executions.items()
        },
    }


def _evidence_bundle(
    *,
    execution: RawExecution,
    redacted_arm: Mapping[str, Any],
    redacted_evidence: Sequence[Mapping[str, Any]],
    raw_evidence: Sequence[Mapping[str, Any]],
    fixture_id: str,
    fixture_sha256: str,
    declared_gaps: Sequence[str],
    capability: Mapping[str, Any] | None,
    accounting: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble one public-safe ``terminus-proof.evidence-bundle.v1``."""
    raw_by_id = {
        str(item.get("evidence_id")): item for item in raw_evidence if isinstance(item, Mapping)
    }
    available = []
    for item in redacted_evidence:
        evidence_id = str(item.get("evidence_id"))
        available.append(
            {
                "evidence_id": evidence_id,
                "sha256": sha256_canonical(raw_by_id.get(evidence_id, item)),
                "summary": str(item.get("summary", "")),
            }
        )

    tools = list(execution.tool_surface.get("tools", []))
    bundle = {
        "schema": "terminus-proof.evidence-bundle.v1",
        "arm_id": execution.arm_id,
        "capability_enabled": execution.capability_enabled,
        "capability": dict(capability) if capability and execution.capability_enabled else None,
        "model": {
            "provider": str(execution.model["provider"]),
            "model_id": str(execution.model["model_id"]),
            "params_sha256": sha256_canonical(execution.model.get("params", {})),
        },
        "fixture": {"fixture_id": fixture_id, "sha256": fixture_sha256},
        "tool_surface": {"tools": tools, "sha256": sha256_canonical(tools)},
        "config": dict(execution.config),
        "evidence_available": available,
        "declared_gaps": [str(gap) for gap in declared_gaps],
        "output": dict(redacted_arm["output"]),
        "transcript": [dict(step) for step in redacted_arm["transcript"]],
        "raw_sha256": execution.raw_sha256(),
        "redaction": dict(accounting),
    }
    try:
        validate_against(
            bundle,
            "terminus-proof.evidence-bundle.v1",
            label=f"arm {execution.arm_id!r} evidence bundle",
        )
    except SchemaError as exc:
        raise BuildError(str(exc)) from exc
    return bundle


def _arm_xi_summary(outcome: VerificationOutcome, contract_set: ContractSet, boundary: str) -> dict[str, Any]:
    """The clock-free XI outcome that the package artifact carries."""
    return {
        "boundary_id": boundary,
        "admission": outcome.admission,
        "stable_core_sha256": outcome.receipt["stable_core_sha256"],
        "contract_set_sha256": contract_set.sha256(),
        "verdicts": [
            {
                "check_id": result.check_id,
                "verdict": result.verdict,
                "codes": sorted({f.code for f in result.findings}),
            }
            for result in outcome.results
        ],
        "finding_codes": sorted({f.code for result in outcome.results for f in result.findings}),
        "blocking_codes": list(outcome.decision.blocking_codes),
    }


def _projected_arm(
    *,
    bundle: Mapping[str, Any],
    summary: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    claims = bundle["output"]["claims"]
    blocking = list(summary["blocking_codes"])
    admission = str(summary["admission"])
    if admission == "ADMIT":
        headline = f"{len(claims)} claims admitted, no blocking code"
    else:
        headline = f"{admission}: {len(blocking)} blocking codes across {len(claims)} claims"
    return {
        "arm_id": str(bundle["arm_id"]),
        "label": label,
        "capability_enabled": bool(bundle["capability_enabled"]),
        "admission": admission,
        "claim_count": len(claims),
        "blocking_codes": blocking,
        "headline": headline,
        "sample_claim": str(claims[0]["statement"]) if claims else None,
    }


def build_proof(spec: DemoSpec) -> ProofBuild:
    """Execute, redact, verify, and assemble. Rendering happens elsewhere."""
    root = spec.root
    document = spec.document

    fixture_path = spec.resolve(document["fixture"]["path"])
    fixture = read_json(fixture_path)
    if not isinstance(fixture, Mapping):
        raise BuildError(f"fixture {fixture_path} is not a JSON object")
    fixture_sha256 = sha256_canonical(fixture)
    declared_fixture_id = str(document["fixture"]["fixture_id"])
    if str(fixture.get("fixture_id", declared_fixture_id)) != declared_fixture_id:
        raise BuildError(
            f"fixture file declares fixture_id {fixture.get('fixture_id')!r} but the spec "
            f"names {declared_fixture_id!r}"
        )

    arm_contracts = load_contract_set(spec.resolve(document["checks"]["arm_contract_set"]))
    package_contracts = load_contract_set(spec.resolve(document["checks"]["package_contract_set"]))
    arm_policy = load_policy(spec.resolve(document["checks"]["arm_policy"]))
    package_policy = load_policy(spec.resolve(document["checks"]["package_policy"]))
    redaction_policy = load_redaction_policy(spec.resolve(document["redaction"]["policy"]))

    executions: dict[str, RawExecution] = {}
    for arm_id in ("baseline", "augmented"):
        arm_spec = spec.arm(arm_id)
        adapter = get_adapter(arm_spec["adapter"]["kind"])
        executions[arm_id] = adapter.execute(arm_spec=arm_spec, fixture=fixture, root=root)

    redaction: RedactionOutcome = apply_policy(
        redaction_policy, _pre_redaction_document(fixture, executions)
    )
    accounting = redaction.accounting(redaction_policy)
    redacted_evidence = redaction.value["evidence"]
    declared_gaps = [str(gap) for gap in fixture.get("declared_gaps", [])]
    capability = document.get("capability")

    bundles: dict[str, Mapping[str, Any]] = {}
    arm_outcomes: dict[str, VerificationOutcome] = {}
    arm_summaries: dict[str, Mapping[str, Any]] = {}

    for arm_id, execution in executions.items():
        bundle = _evidence_bundle(
            execution=execution,
            redacted_arm=redaction.value["arms"][arm_id],
            redacted_evidence=redacted_evidence,
            raw_evidence=fixture.get("evidence", []),
            fixture_id=declared_fixture_id,
            fixture_sha256=fixture_sha256,
            declared_gaps=declared_gaps,
            capability=capability,
            accounting=accounting,
        )
        boundary = ARM_BOUNDARY.format(arm_id=arm_id)
        outcome = verify_artifact(
            bundle,
            boundary_id=boundary,
            contract_set=arm_contracts,
            policy=arm_policy,
            artifact_id=f"{spec.demo_id}/{arm_id}",
            fixture={"fixture_id": declared_fixture_id, "sha256": fixture_sha256},
            model={
                "provider": bundle["model"]["provider"],
                "model_id": bundle["model"]["model_id"],
                "params_sha256": bundle["model"]["params_sha256"],
            },
            tool_surface=bundle["tool_surface"],
            capability=(
                {
                    "capability_id": str(capability["capability_id"]),
                    "version": str(capability["version"]),
                    "sha256": None,
                    "source": capability.get("source"),
                }
                if capability and bundle["capability_enabled"]
                else None
            ),
            inputs=[
                {"ref": _relative(spec.path, root), "sha256": spec.sha256, "role": "demo-spec"},
                {"ref": _relative(fixture_path, root), "sha256": fixture_sha256, "role": "fixture"},
                {"ref": execution.source, "sha256": execution.raw_sha256(), "role": "recording"},
            ],
        )
        bundles[arm_id] = bundle
        arm_outcomes[arm_id] = outcome
        arm_summaries[arm_id] = _arm_xi_summary(outcome, arm_contracts, boundary)

    render = document["render"]
    labels = render["labels"]
    projection = {
        "title": str(render["title"]),
        "subtitle": str(render["subtitle"]),
        "accent": str(render.get("accent", "#7ee787")),
        "labels": dict(labels),
        "claim_statement": str(document["claim"]["statement"]),
        "claim_scope": str(document["claim"]["scope"]),
        "changed_variable": {
            "name": str(document["changed_variable"]["name"]),
            "baseline": document["changed_variable"]["baseline_value"],
            "augmented": document["changed_variable"]["augmented_value"],
        },
        "arms": {
            arm_id: _projected_arm(
                bundle=bundles[arm_id],
                summary=arm_summaries[arm_id],
                label=str(labels[arm_id]),
            )
            for arm_id in ("baseline", "augmented")
        },
        "contract_checks": [
            {"check_id": contract.check_id, "title": contract.title or contract.check_id}
            for contract in arm_contracts.contracts
        ],
    }

    artifact = {
        "schema": "terminus-proof.proof-artifact.v1",
        "demo_id": spec.demo_id,
        "title": str(document["title"]),
        "spec_sha256": spec.sha256,
        "capability": dict(capability) if capability else None,
        "claim": {
            "statement": str(document["claim"]["statement"]),
            "scope": str(document["claim"]["scope"]),
            "kind": str(document["claim"]["kind"]),
            "not_claimed": [str(item) for item in document["claim"].get("not_claimed", [])],
        },
        "changed_variable": dict(document["changed_variable"]),
        "declared_gaps": declared_gaps,
        "declared": {
            "model": dict(document["model"]),
            "tool_surface": dict(document["tool_surface"]),
            "arms": {
                arm_id: {
                    "arm_id": arm_id,
                    "config": dict(spec.arm(arm_id)["config"]),
                }
                for arm_id in ("baseline", "augmented")
            },
        },
        "arms": {
            arm_id: {
                "arm_id": arm_id,
                "document_sha256": sha256_canonical(bundles[arm_id]),
                "evidence": bundles[arm_id],
                "xi": arm_summaries[arm_id],
            }
            for arm_id in ("baseline", "augmented")
        },
        "contract_sets": {
            "arm": _identified(
                arm_contracts.set_id,
                arm_contracts.version,
                arm_contracts.to_dict(),
                document["checks"]["arm_contract_set"],
            ),
            "package": _identified(
                package_contracts.set_id,
                package_contracts.version,
                package_contracts.to_dict(),
                document["checks"]["package_contract_set"],
            ),
        },
        "policies": {
            "arm": _identified(
                arm_policy.policy_id,
                arm_policy.version,
                arm_policy.to_dict(),
                document["checks"]["arm_policy"],
            ),
            "package": _identified(
                package_policy.policy_id,
                package_policy.version,
                package_policy.to_dict(),
                document["checks"]["package_policy"],
            ),
        },
        "redaction": redaction_policy.to_artifact_block(),
        "public_projection": projection,
    }

    artifact_sha256 = sha256_canonical(artifact)
    proof_id = f"{spec.demo_id}-{artifact_sha256[:12]}"

    provenance = build_provenance(
        boundary_id=PACKAGE_BOUNDARY,
        artifact=artifact,
        artifact_id=proof_id,
        artifact_sha256=artifact_sha256,
        run_id=f"run_{artifact_sha256[:24]}",
        model={
            "provider": bundles["augmented"]["model"]["provider"],
            "model_id": bundles["augmented"]["model"]["model_id"],
            "params_sha256": bundles["augmented"]["model"]["params_sha256"],
        },
        fixture={"fixture_id": declared_fixture_id, "sha256": fixture_sha256},
        tool_surface=bundles["augmented"]["tool_surface"],
        capability=(
            {
                "capability_id": str(capability["capability_id"]),
                "version": str(capability["version"]),
                "sha256": None,
                "source": capability.get("source"),
            }
            if capability
            else None
        ),
        inputs=[
            {"ref": _relative(spec.path, root), "sha256": spec.sha256, "role": "demo-spec"},
            {"ref": _relative(fixture_path, root), "sha256": fixture_sha256, "role": "fixture"},
            {
                "ref": document["checks"]["arm_contract_set"],
                "sha256": arm_contracts.sha256(),
                "role": "arm-contract-set",
            },
            {
                "ref": document["checks"]["package_contract_set"],
                "sha256": package_contracts.sha256(),
                "role": "package-contract-set",
            },
            {
                "ref": document["checks"]["arm_policy"],
                "sha256": arm_policy.sha256(),
                "role": "arm-policy",
            },
            {
                "ref": document["checks"]["package_policy"],
                "sha256": package_policy.sha256(),
                "role": "package-policy",
            },
            {
                "ref": document["redaction"]["policy"],
                "sha256": redaction_policy.sha256(),
                "role": "redaction-policy",
            },
            *[
                {
                    "ref": executions[arm_id].source,
                    "sha256": executions[arm_id].raw_sha256(),
                    "role": f"recording/{arm_id}",
                }
                for arm_id in ("baseline", "augmented")
            ],
        ],
        notes=[
            "XI decides admission. This engine renders only what XI admitted.",
            f"protocol {PROTOCOL_VERSION}, runtime {RUNTIME_VERSION}, engine {ENGINE_VERSION}",
        ],
    )

    package = verify_artifact(
        artifact,
        boundary_id=PACKAGE_BOUNDARY,
        contract_set=package_contracts,
        policy=package_policy,
        provenance=provenance,
    )

    return ProofBuild(
        proof_id=proof_id,
        spec=spec,
        artifact=artifact,
        artifact_sha256=artifact_sha256,
        package=package,
        arms=arm_outcomes,
        arm_documents=bundles,
        transcripts={
            arm_id: bundles[arm_id]["transcript"] for arm_id in ("baseline", "augmented")
        },
        contract_sets={"arm": arm_contracts, "package": package_contracts},
    )
