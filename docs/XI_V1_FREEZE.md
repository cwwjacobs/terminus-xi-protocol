# Terminus XI Protocol v1 — freeze

- Protocol: `terminus-xi/1.0.0`
- Runtime: `terminus-xi-runtime/1.0.0`
- Machine-readable freeze receipt: [`receipts/xi-v1-freeze-receipt.json`](../receipts/xi-v1-freeze-receipt.json)
- Audit-semantics decision: [`AUDIT_SEMANTICS_DECISION.md`](AUDIT_SEMANTICS_DECISION.md)

This document states what v1 *is*, what is inside the frozen boundary and what
is deliberately outside it, and which parts were recovered from the historical
line versus decided here.

## What v1 is

Six mechanisms, and nothing else.

| Mechanism | Module | The one thing it does |
|---|---|---|
| Charter | `CHARTER.md` | Operational law. Not code. |
| Provenance | `terminus_xi.provenance` | Binds a decision to exact inputs by canonical digest. Carries no clock and no random id. |
| Audit | `terminus_xi.audit` | Evaluates one frozen contract against one artifact. One path, one envelope, typed codes. |
| Admission | `terminus_xi.admission` | Decides whether an artifact crosses a named boundary. Fails closed. |
| Receipt | `terminus_xi.receipt` | Canonical, reproducibly serializable, independently verifiable. |
| Recovery | `terminus_xi.recovery` | A budget and a re-validation requirement. Not a planner. |

`terminus_xi.engine.verify_artifact` composes them, and is the only supported
way to take an artifact across a boundary.

## The frozen boundary

**Inside** (bound by digest in the freeze receipt, 29 files):

- `src/terminus_xi/**.py` — the runtime package;
- the nine `terminus-xi.*` schemas under `spec/`, listed in
  `terminus_xi.schemas.XI_SCHEMA_FILES`;
- `contracts/xi-selftest.contracts.json` and `policies/xi-selftest.policy.json`,
  because the determinism probe in the freeze receipt is defined against them.

**Outside, on purpose:**

- `src/terminus_proof/**` and the `terminus-proof.*` schemas. KSL-02 *consumes*
  XI; it is not part of XI. The engine registers its own schema ids through
  `terminus_xi.schemas.register_schema` and its own checks through
  `terminus_xi.checks.register`, so XI has no compile-time knowledge of it.
- `archive/**`. Historical evidence, never imported. The freeze receipt records
  a quarantine scan over every active Python file to keep it that way.
- Anything requiring a network, a model, a clock inside a check, or a
  third-party dependency. XI v1 is standard-library only.

## Versioned replacements

Two bootstrap schemas were replaced rather than edited in place. Both originals
remain valid and loadable.

**`terminus-xi.check-contract.v1` → `.v2`.** v1 had nowhere to say which
implementation evaluates the contract, which part of the artifact it reads, what
configuration it is frozen with, or which WARN codes this boundary escalates.
v2 adds `implementation`, `input_pointers`, `config`, and `escalate_codes`. v1
documents still load: `terminus_xi.contracts.load_contract` upgrades them in
memory by defaulting the implementation to the `check_id`, the input to the
whole artifact, and the configuration to empty.

**`terminus-xi.receipt.v1` → `.v2`.** v1 could not bind provenance, contract-set
identity, the admission rationale, or the receipt's own digest — all of which
KSL-01 requires. v2 adds them. `check_results` still use the unchanged
`terminus-xi.watchdog-result.v1` envelope.

## Two digests, two questions

`stable_core_sha256` covers the receipt minus `created_at_utc` and the two
digest fields. Identical canonical input plus identical contracts and policy
reproduce it exactly; it is the machine-checkable form of the determinism rule.

`receipt_sha256` covers everything except itself, so any edit to any field is
detectable.

Neither is a signature. A receipt proves internal consistency and binds
identity. It does not authenticate the party that produced it.

## Recovered, inferred, new

**Recovered** — directly evidenced in the historical XI material:

- deterministic wrappers at stage boundaries, distinct from the capability;
- provenance attachment by cryptographic fingerprint;
- explicit rejection over silent corruption;
- canonicalized outputs;
- drift surfaced rather than normalized;
- bounded recovery intent (`xiCharter.md`, "Recovery Rule");
- the fixed boundary rule itself.

**Inferred** — implied by the historical material but never implemented there:

- that a check verdict and a boundary admission are different decisions.
  `xiCharter.md` describes both roles; the code had neither;
- that "borderline outputs may be retained with review flags" (Review Rule)
  means an explicit `REVIEW` admission state, not a silent promotion;
- that the contradiction rule requires typed codes, since string matching is
  what `xiPrismAgent_completed.py:441` actually did and it is unreliable.

**New** — decided here, not claimed as history:

- the `terminus-xi.watchdog-result.v1` and `terminus-xi.receipt.v2` envelopes;
- the frozen issue-code vocabulary and its four severity classes;
- one-directional WARN→FAIL escalation declared by contract;
- `stable_core_sha256` as the determinism witness;
- derived, non-random `run_id`;
- the standard-library JSON Schema validator, so XI can establish its own
  invariants without a third-party dependency;
- archive quarantine as a scanned, receipt-recorded property.

## Historical contradictions and how v1 answers them

| Historical defect | v1 response |
|---|---|
| Two incompatible `xiAuditAgent` finding envelopes | One envelope, one audit path. See [`AUDIT_SEMANTICS_DECISION.md`](AUDIT_SEMANTICS_DECISION.md). |
| Audits that found errors and returned the dataset anyway | Verdict and admission are separate and machine-readable; `FAIL` and `ERROR` handling is not policy-configurable. |
| `PAYLOAD_SIZE_UNKNOWN` recorded as a warning | Reclassified `ERROR`. An unestablished invariant is never a soft pass. |
| `uuid4` finding and event ids | Removed. Findings carry no random identifier. |
| A model call inside the deterministic audit | Removed. Nothing in `src/terminus_xi/` calls a model. |
| Promotion-blocking codes chosen by substring matching (`xiPrismAgent_completed.py:441`) | Typed codes only; a check emitting an unknown code yields `CONTRACT_INVALID`. |
| Provenance recording both a raw and a canonical digest of the same JSON, where the raw digest depended on key order | JSON identity *is* canonical identity. One digest. |
| `runtime/tool_router.py` does not parse as Python | Preserved unrepaired as evidence; `tests/test_quarantine_and_cli.py` asserts it still fails to parse, so the defect cannot be quietly "fixed". |

## Declared out of scope for v1

Each of these is absent by decision, with no dangling runtime dependency.

- **The Prism channel/boundary-state model.** `archive/recovered/prism/` carries
  a richer refraction/boundary-event model. It is preserved as evidence and not
  implemented.
- **Multi-boundary release chains.** One receipt admits one artifact at one
  named boundary. Chaining is left to the consumer (the proof engine chains
  three boundaries itself).
- **Signed attestation.** Receipts are integrity documents. Signing is a
  separate concern with separate key-management requirements.
- **Curation-domain checks.** `ROW_COUNT`, `SPARSE_FIELDS`, and friends were
  dataset-curation concerns, not protocol concerns. Consumers register their own.
- **`self.warn()`-style side channels.** A warning that is not a finding is not
  evidence.

## Known limitations

Carried in the freeze receipt under `known_limitations`, and repeated here:

1. Receipts detect edits and incompleteness. They do not authenticate the
   producer.
2. A digest establishes identity of the bytes it covers. It proves nothing about
   truth, safety, authorship, authority, or semantic correctness.
3. Claim-boundary style checks are bounded lexical and structural predicates
   over declared evidence. They cannot determine whether a statement is true.
4. One artifact, one boundary, one receipt. Multi-boundary chains are out of
   scope for v1.
5. `terminus-xi.check-contract.v1` documents are accepted and upgraded in
   memory, but new contracts should be authored as v2.
6. The Prism channel/boundary-state model is archive evidence only.
7. `TERMINUS_XI_NOW` overrides the receipt clock for reproducible builds. It is
   a build convenience and carries no authority.

## Reproducing the freeze

```bash
python tools/run_tests.py --report receipts/test-report.json
python tools/freeze_xi_v1.py --test-report receipts/test-report.json
```

The second command refuses to write a receipt if the suite did not pass, if the
determinism probe produced two different stable cores, or if any active file
references `archive/`.
