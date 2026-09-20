# Terminus XI Protocol

**Deterministic runtime watchdogs for probabilistic systems.**

XI is pronounced **eleven**. This repository establishes the canonical Terminus
form of the historical XI line, freezes it as v1, and builds an automated
documentation-and-proof engine on top of it.

## Purpose

Probabilistic systems may propose, reason, generate, and repair. XI sits beside
them as a bounded deterministic enforcement layer.

XI answers:
- What exact artifact entered this boundary?
- Which frozen invariants apply?
- Did an invariant fail?
- Is the evidence complete enough to admit the artifact?
- What receipt proves the decision?
- What bounded recovery path exists after rejection?

XI is not a general agent, planner, persona, or model-based critic. Nothing
under `src/terminus_xi/` calls a model, opens a socket, or reads a clock inside
a check.


## Positioning

Terminus XI is a deterministic admission protocol for probabilistic artifacts. It binds exact inputs, frozen contracts, typed findings, provenance, and a named boundary decision into a reproducible receipt. The goal is not to make a probabilistic system deterministic; it is to make the rules governing what may cross a boundary explicit, replayable, and independently checkable.

XI is not claimed to invent policy engines, provenance, admission control, or cryptographic digests. Its differentiation is the composition of those ideas around probabilistic outputs and evidence: generation does not grant authority, provenance does not imply correctness, and an artifact does not cross a governed boundary merely because the system that produced it reported success.

In the canonical Terminus stack, XI is the proof and admission substrate beneath release tooling. Observation establishes what happened; XI establishes what evidence is admissible at a named boundary; downstream systems may then render or publish only what that admitted evidence supports.

## The XI line

The historical XI line explored a family of narrow operational roles around curation, validation, provenance, adjudication, archival continuity, and orchestration. Names such as `xiCurate`, `xiAudit`, `xiProvenance`, `Prism`, `Archivist`, and `Goldmine` survive in the archive as lineage evidence.

XI v1 does not revive those historical components as autonomous agents. Instead, it preserves the durable principle underneath them: probabilistic work may be proposed elsewhere, while boundary enforcement remains bounded, deterministic, evidence-bearing, and fail-closed. Historical material is prior art for the protocol, not executable authority.

## Core rule

> No unvalidated artifact may cross a governed stage boundary.

## Two layers

**Terminus XI v1** (`src/terminus_xi/`) — the protocol runtime. Canonical
identity, one audit semantic, a frozen issue-code vocabulary, fail-closed
admission, verifiable receipts, and a bounded recovery base. Standard library
only. Frozen: [`docs/XI_V1_FREEZE.md`](docs/XI_V1_FREEZE.md).

**Terminus Proof** (`src/terminus_proof/`) — the proof engine. Turns a
controlled baseline-vs-capability pair into documentation, a thumbnail, and a
video, and emits them *only* for what XI admitted.
[`docs/PROOF_ENGINE.md`](docs/PROOF_ENGINE.md).

## Try it

```bash
# XI: verify an artifact against a frozen contract set and emit a receipt
python -m terminus_xi verify artifact.json \
    --contracts contracts/xi-selftest.contracts.json \
    --boundary xi.selftest \
    --policy policies/xi-selftest.policy.json \
    --receipt receipt.json
# exit 0 ADMIT · 2 REVIEW · 3 REJECT · 4 ERROR · 5 usage

# Proof: build the canonical Claim Boundary Audit demo, then verify it
python -m terminus_proof build demos/claim-boundary-audit.demo.json
python -m terminus_proof verify proofs/<proof-id>
```

Run from the repository root with `src/` on the path (`PYTHONPATH=src`), or
`pip install -e .` for the `terminus-xi` and `terminus-proof` commands.

Requirements: Python 3.11+ and, for media rendering, `ffmpeg` built with
librsvg and libx264. No Python dependencies.

## The canonical example

One assessment fixture, one model, one tool surface, two runs. The only thing
that changes is whether the Claim Boundary Audit capability is enabled.

| Arm | XI admission | Blocking codes |
|---|---|---|
| baseline — capability disabled | `REJECT` | `CLAIM_OVERBROAD`, `CLAIM_SCOPE_MISSING`, `EVIDENCE_CITATION_MISSING`, `EVIDENCE_REF_UNRESOLVED`, `LIMITATIONS_ABSENT` |
| augmented — capability enabled | `ADMIT` | none |

Parity across model, fixture, tool surface, and every other configuration key is
*checked*, not assumed. The package boundary then admits — or refuses — the
proof itself. Five negative demo specs under `demos/negative/` break parity,
drift the configuration, leave the improvement unmade, and disable a redaction
rule; each is refused, and none produces a video, thumbnail, README, or listing
copy.

## Repository map

| Path | What it holds |
|---|---|
| `CHARTER.md` | Active operational law. |
| `spec/` | Machine-readable protocol contracts. |
| `src/terminus_xi/` | XI v1 runtime. |
| `src/terminus_proof/` | The proof engine. |
| `contracts/`, `policies/` | Frozen check contracts and admission policies. |
| `demos/`, `fixtures/` | Demo specifications and recorded executions. |
| `tests/` | Unit and negative tests (`python tools/run_tests.py`). |
| `tools/` | Test report, XI freeze receipt, UKSL closure receipt. |
| `receipts/` | Machine-readable receipts. |
| `docs/` | Freeze, decisions, lineage, historical defects. |
| `archive/` | Historical evidence only. Never active runtime code. |

## Receipts

| Receipt | What it records |
|---|---|
| [`receipts/xi-v1-freeze-receipt.json`](receipts/xi-v1-freeze-receipt.json) | The XI v1 boundary: files and digests, issue-code vocabulary, schemas, test result, determinism probe, archive quarantine, known limitations. |
| [`receipts/uksl-receipt.json`](receipts/uksl-receipt.json) | KSL-01 and KSL-02 closure, clause by clause, with the evidence for each. |
| [`receipts/bootstrap-receipt.json`](receipts/bootstrap-receipt.json) | The original provenance binding of the historical import. |

Reproduce all of them:

```bash
python tools/run_tests.py --report receipts/test-report.json
python tools/freeze_xi_v1.py --test-report receipts/test-report.json
python -m terminus_proof build demos/claim-boundary-audit.demo.json
python tools/build_uksl_receipt.py --proof-dir proofs/<proof-id>
```

Each step refuses to record a success it did not observe: the freeze will not
write a receipt if the suite failed, the determinism probe drifted, or an active
file references `archive/`.

## What a receipt does not prove

A digest establishes identity of the bytes it covers. It does not prove truth,
safety, authorship, authority, or semantic correctness. An XI receipt is an
integrity document, not a signed attestation: it detects edits and
incompleteness, but it does not authenticate who produced it. `ADMIT` is bounded
to one named boundary and is not a certification of anything beyond it.

## Status

Public source-available research and reference implementation. XI v1 is frozen; the proof
engine is at `terminus-proof/1.0.0`. No production-readiness claim is made.


## License

Terminus XI Protocol is source-available under the **PolyForm Noncommercial License 1.0.0**. Noncommercial use is permitted under the included license; commercial use requires a separate written license from Corey Jacobs. See `LICENSE` and `COMMERCIAL_LICENSE.md`.
