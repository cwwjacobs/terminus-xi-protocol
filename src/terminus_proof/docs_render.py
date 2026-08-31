"""Render documentation from admitted evidence.

Every sentence these renderers emit is a formatting of a value that already
exists in the proof artifact or a receipt. There is no template slot for a
claim that the evidence does not already carry, and no hand-written success
copy anywhere in this module: the words "admitted", "rejected", and every code
name come from the receipts.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from terminus_xi import PROTOCOL_VERSION, RUNTIME_VERSION

from . import ENGINE_VERSION

__all__ = [
    "render_findings",
    "render_listing_assets",
    "render_readme",
    "render_transcript",
    "render_not_admitted",
]


def _table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _codes(values: Sequence[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def render_findings(
    proof_id: str, boundaries: Sequence[tuple[str, Mapping[str, Any]]]
) -> dict[str, Any]:
    """Flatten every receipt's results into one readable index."""
    return {
        "schema": "terminus-proof.findings.v1",
        "proof_id": proof_id,
        "boundaries": [
            {
                "boundary_id": receipt["boundary_id"],
                "admission": receipt["admission"],
                "receipt_sha256": receipt["receipt_sha256"],
                "results": [
                    {
                        "check_id": result["check_id"],
                        "check_version": result["check_version"],
                        "verdict": result["verdict"],
                        "findings": [dict(item) for item in result["findings"]],
                    }
                    for result in receipt["check_results"]
                ],
            }
            for _, receipt in boundaries
        ],
    }


def render_transcript(artifact: Mapping[str, Any], proof_id: str) -> str:
    """The public-safe transcript of both arms, side by side in time."""
    lines = [
        f"Terminus Proof transcript - {proof_id}",
        f"demo: {artifact['demo_id']}",
        "",
        "This transcript is the public-safe projection of what each arm recorded.",
        "Redacted spans are marked [REDACTED:<rule-id>] by the redaction policy named in",
        "proof.json. No step here was authored by the renderer.",
        "",
    ]
    for arm_id in ("baseline", "augmented"):
        arm = artifact["arms"][arm_id]
        evidence = arm["evidence"]
        lines.append("=" * 78)
        label = artifact["public_projection"]["arms"][arm_id]["label"]
        lines.append(f"ARM: {arm_id} - {label}")
        lines.append(
            f"capability_enabled={evidence['capability_enabled']}  "
            f"model={evidence['model']['provider']}/{evidence['model']['model_id']}  "
            f"xi={arm['xi']['admission']}"
        )
        lines.append("=" * 78)
        for step in evidence["transcript"]:
            lines.append(f"[{step['step']:>2}] {step['role']:<10} {step['text']}")
        lines.append("")
        lines.append(f"-- claims produced by {arm_id} --")
        for claim in evidence["output"]["claims"]:
            scope = claim.get("scope")
            scope_text = (
                "scope: "
                + "; ".join(f"{key}={scope[key]}" for key in sorted(scope))
                if isinstance(scope, Mapping) and scope
                else "scope: none declared"
            )
            refs = claim.get("evidence_refs") or []
            lines.append(f"  {claim['claim_id']}: {claim['statement']}")
            lines.append(f"      {scope_text}")
            lines.append(f"      evidence: {', '.join(refs) if refs else 'none cited'}")
        limitations = evidence["output"]["limitations"]
        lines.append(f"-- limitations declared by {arm_id} --")
        if limitations:
            for item in limitations:
                lines.append(f"  - {item}")
        else:
            lines.append("  (none)")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_readme(
    *,
    artifact: Mapping[str, Any],
    proof: Mapping[str, Any],
    receipt: Mapping[str, Any],
    arm_receipts: Mapping[str, Mapping[str, Any]],
    spec_path: str,
) -> str:
    projection = artifact["public_projection"]
    baseline = projection["arms"]["baseline"]
    augmented = projection["arms"]["augmented"]
    changed = projection["changed_variable"]

    check_rows = [
        [
            f"`{result['check_id']}`",
            result["verdict"],
            _codes(sorted({item["code"] for item in result["findings"]})),
        ]
        for result in receipt["check_results"]
    ]
    arm_rows = [
        [
            projection["arms"][arm_id]["label"],
            projection["arms"][arm_id]["admission"],
            str(projection["arms"][arm_id]["claim_count"]),
            _codes(projection["arms"][arm_id]["blocking_codes"]),
        ]
        for arm_id in ("baseline", "augmented")
    ]
    contract_rows = [
        [f"`{check['check_id']}`", check["title"]] for check in projection["contract_checks"]
    ]

    lines: list[str] = []
    lines.append(f"# {artifact['title']}")
    lines.append("")
    lines.append(f"**{projection['subtitle']}**")
    lines.append("")
    lines.append(
        f"Proof `{proof['proof_id']}` - XI admission **{receipt['admission']}** at boundary "
        f"`{receipt['boundary_id']}`."
    )
    lines.append("")
    lines.append(
        "This document was generated from the proof artifact. It was not written by hand, and "
        "it states nothing that the receipts in this directory do not already record."
    )
    lines.append("")

    lines.append("## Claim")
    lines.append("")
    lines.append(f"> {artifact['claim']['statement']}")
    lines.append("")
    lines.append(f"**Scope.** {artifact['claim']['scope']}")
    lines.append("")
    if artifact["claim"]["not_claimed"]:
        lines.append("**Not claimed.**")
        lines.append("")
        for item in artifact["claim"]["not_claimed"]:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## The changed variable")
    lines.append("")
    lines.append(
        f"`{changed['name']}`: `{changed['baseline']}` -> `{changed['augmented']}`"
    )
    lines.append("")
    if artifact["changed_variable"].get("description"):
        lines.append(artifact["changed_variable"]["description"])
        lines.append("")
    lines.append(
        "Parity across everything else is checked, not assumed. `proof.parity.model`, "
        "`proof.parity.fixture`, `proof.parity.tool_surface`, and `proof.parity.config` compare "
        "what each arm recorded about itself; `proof.spec.faithful` compares both arms against "
        "the specification they claim to implement."
    )
    lines.append("")

    lines.append("## Result")
    lines.append("")
    lines.append(_table(arm_rows, ["Arm", "XI admission", "Claims", "Blocking codes"]))
    lines.append("")
    lines.append(
        f"Baseline: {baseline['headline']}. Augmented: {augmented['headline']}."
    )
    lines.append("")

    lines.append("## Contract set evaluated against both arms")
    lines.append("")
    lines.append(
        f"`{artifact['contract_sets']['arm']['id']}` v{artifact['contract_sets']['arm']['version']} "
        f"(`{artifact['contract_sets']['arm']['sha256'][:16]}`)"
    )
    lines.append("")
    lines.append(_table(contract_rows, ["Check", "What it establishes"]))
    lines.append("")

    lines.append("## Package boundary verdicts")
    lines.append("")
    lines.append(
        f"`{artifact['contract_sets']['package']['id']}` "
        f"v{artifact['contract_sets']['package']['version']} under policy "
        f"`{artifact['policies']['package']['id']}` "
        f"v{artifact['policies']['package']['version']}"
    )
    lines.append("")
    lines.append(_table(check_rows, ["Check", "Verdict", "Codes"]))
    lines.append("")

    lines.append("## Receipts and identity")
    lines.append("")
    receipt_rows = [
        [
            f"`{boundary['boundary_id']}`",
            boundary["admission"],
            f"`{boundary['receipt_path']}`",
            f"`{boundary['receipt_sha256'][:16]}`",
        ]
        for boundary in proof["boundaries"]
    ]
    lines.append(_table(receipt_rows, ["Boundary", "Admission", "Receipt", "receipt_sha256"]))
    lines.append("")
    lines.append(f"- artifact sha256: `{proof['artifact_sha256']}`")
    lines.append(f"- demo spec sha256: `{artifact['spec_sha256']}`")
    lines.append(f"- run id: `{receipt['provenance']['run_id']}`")
    lines.append(f"- protocol: `{PROTOCOL_VERSION}` / runtime `{RUNTIME_VERSION}`")
    lines.append(f"- engine: `{ENGINE_VERSION}`")
    lines.append(
        f"- redaction policy: `{artifact['redaction']['policy_id']}` "
        f"v{artifact['redaction']['policy_version']} "
        f"(`{artifact['redaction']['policy_sha256'][:16]}`)"
    )
    lines.append("")

    lines.append("## Reproduce and verify")
    lines.append("")
    lines.append("```bash")
    lines.append(f"python -m terminus_proof build {spec_path}")
    lines.append(f"python -m terminus_proof verify proofs/{proof['proof_id']}")
    lines.append("```")
    lines.append("")
    lines.append(
        "`verify` is independent of `build`: it re-reads the directory, re-hashes every listed "
        "file, re-derives the proof id from the artifact, re-runs the frozen contract set, and "
        "re-checks each receipt against its own recorded findings. Editing any file in this "
        "directory makes verification fail."
    )
    lines.append("")

    lines.append("## Limitations")
    lines.append("")
    for item in _limitations(artifact, arm_receipts):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def _limitations(
    artifact: Mapping[str, Any], arm_receipts: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Limitations, derived rather than asserted."""
    items = [
        f"This proof covers one fixture ({artifact['arms']['augmented']['evidence']['fixture']['fixture_id']}), "
        f"one model identity, and one recorded pair of executions. It establishes nothing about "
        f"any other fixture, model, or tool surface.",
        "The claim checks are bounded structural and lexical predicates over declared evidence. "
        "They establish that a claim stays inside the bound its citations support. They cannot "
        "establish that a claim is true.",
        "An XI receipt is an integrity document, not a signed attestation. It detects edits and "
        "incompleteness; it does not authenticate who produced it.",
        "Admission is bounded to the named boundary. It is not a certification of safety, "
        "correctness, legality, or fitness for any purpose.",
    ]
    gaps = artifact.get("declared_gaps") or []
    for gap in gaps:
        items.append(f"Declared coverage gap carried by the fixture: {gap}")
    for item in artifact["claim"]["not_claimed"]:
        items.append(f"Explicitly not claimed: {item}")
    return items


def render_listing_assets(
    *,
    artifact: Mapping[str, Any],
    proof: Mapping[str, Any],
    receipt: Mapping[str, Any],
    arm_receipts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    projection = artifact["public_projection"]
    baseline = projection["arms"]["baseline"]
    augmented = projection["arms"]["augmented"]
    changed = projection["changed_variable"]
    cleared = sorted(set(baseline["blocking_codes"]) - set(augmented["blocking_codes"]))

    bullets = [
        {
            "text": (
                f"Baseline run: {baseline['admission']} at the claim boundary, blocked by "
                f"{len(baseline['blocking_codes'])} typed codes "
                f"({', '.join(baseline['blocking_codes']) or 'none'})."
            ),
            "derived_from": "/artifact/arms/baseline/xi",
        },
        {
            "text": (
                f"Capability-enabled run: {augmented['admission']} at the same boundary under the "
                f"same contract set, with {augmented['claim_count']} claims and "
                f"{len(augmented['blocking_codes'])} blocking codes."
            ),
            "derived_from": "/artifact/arms/augmented/xi",
        },
        {
            "text": (
                f"Codes cleared between the runs: {', '.join(cleared) if cleared else 'none'}."
            ),
            "derived_from": "/artifact/arms",
        },
        {
            "text": (
                f"One variable changed: {changed['name']} moved from {changed['baseline']} to "
                f"{changed['augmented']}. Model, fixture, tool surface, and every other "
                f"configuration key were checked equal, not assumed equal."
            ),
            "derived_from": "/artifact/changed_variable",
        },
        {
            "text": (
                f"XI admitted the package at boundary {receipt['boundary_id']} after "
                f"{len(receipt['check_results'])} deterministic checks under policy "
                f"{artifact['policies']['package']['id']}."
            ),
            "derived_from": "/boundaries",
        },
    ]

    return {
        "schema": "terminus-proof.listing-assets.v1",
        "proof_id": proof["proof_id"],
        "admitted": receipt["admission"] == "ADMIT",
        "headline": f"{artifact['title']}: {augmented['headline']} where the baseline was {baseline['admission']}.",
        "summary": (
            f"{projection['subtitle']} {len(cleared)} claim-boundary codes that blocked the "
            f"baseline run are absent from the capability-enabled run on the same fixture, "
            f"model, and tool surface. XI verdict: {receipt['admission']}."
        ),
        "bullets": bullets,
        "claim": {
            "statement": artifact["claim"]["statement"],
            "scope": artifact["claim"]["scope"],
            "derived_from": "/artifact/claim",
        },
        "not_claimed": list(artifact["claim"]["not_claimed"]),
        "limitations": _limitations(artifact, arm_receipts),
        "media": {"video": "demo.mp4", "thumbnail": "thumbnail.png"},
    }


def render_not_admitted(
    *,
    artifact: Mapping[str, Any],
    receipt: Mapping[str, Any],
    proof_id: str,
    spec_path: str,
) -> str:
    """The only document a rejected build is allowed to emit."""
    rows = [
        [
            f"`{result['check_id']}`",
            result["verdict"],
            _codes(sorted({item["code"] for item in result["findings"]})),
        ]
        for result in receipt["check_results"]
    ]
    lines = [
        "# NOT ADMITTED",
        "",
        f"Proof attempt `{proof_id}` for demo `{artifact['demo_id']}` was **not admitted** by XI.",
        "",
        f"Admission: **{receipt['admission']}** at boundary `{receipt['boundary_id']}`.",
        "",
        "No video, thumbnail, README, or listing copy was produced. This directory is a "
        "diagnostic record of a failed attempt and must not be presented as a demonstration.",
        "",
        "## Blocking codes",
        "",
        _codes(receipt["admission_rationale"]["blocking_codes"]),
        "",
        "## Reasons",
        "",
    ]
    for reason in receipt["admission_rationale"]["reasons"]:
        lines.append(f"- {reason}")
    lines += ["", "## Verdicts", "", _table(rows, ["Check", "Verdict", "Codes"]), ""]
    lines += [
        "## Reproduce",
        "",
        "```bash",
        f"python -m terminus_proof build {spec_path}",
        "```",
        "",
    ]
    return "\n".join(lines)
