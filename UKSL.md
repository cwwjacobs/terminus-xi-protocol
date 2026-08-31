# Terminus XI Protocol — UKSL v1

## Ultra Kernel

Complete the Terminus XI line as a coherent deterministic watchdog protocol, freeze it in a usable v1 base form, and implement that frozen XI v1 as the verification/admission substrate of an automated documentation-and-proof engine that can turn controlled baseline-vs-capability executions into reproducible evidence, documentation, thumbnails, and video without manual editing.

The resulting system must preserve the governing distinction:

- probabilistic systems may propose, reason, generate, and repair;
- XI deterministically identifies inputs, evaluates frozen contracts, admits or rejects artifacts, and emits canonical receipts;
- documentation/media may only claim what admitted evidence supports.

No unvalidated artifact may cross a stage boundary.

---

# KSL-01 — Freeze Terminus XI v1 Base

## Kernel

Recover the strongest load-bearing XI mechanisms from the historical line, resolve known contradictions explicitly, implement the smallest complete deterministic runtime, and freeze that runtime as Terminus XI Protocol v1.

## Required v1 components

1. **XI Charter**
   - canonical operational law;
   - deterministic precedence;
   - fixed-boundary rule;
   - explicit failure;
   - no silent normalization of drift;
   - recovery, where implemented, must be bounded and return to normal posture.

2. **XI Provenance**
   - canonical hashing of relevant inputs/artifacts;
   - run/job identity;
   - model identity where applicable;
   - fixture/input identity;
   - tool-surface identity where applicable;
   - capability/skill identity where applicable;
   - immutable lineage event or receipt binding.

3. **XI Audit**
   - evaluates explicit, frozen check contracts only;
   - deterministic PASS/WARN/FAIL semantics;
   - stable issue codes;
   - no duplicate divergent audit implementations;
   - no model judgment hidden inside deterministic checks.

4. **XI Admission**
   - only admitted artifacts cross boundaries;
   - FAIL blocks promotion;
   - WARN behavior is explicit in contract/policy;
   - admission decision is machine-readable and attributable.

5. **XI Receipt**
   - canonical JSON representation;
   - binds provenance, checks, admission, versions, and hashes;
   - reproducibly serializable;
   - independently verifiable.

6. **XI Recovery Base**
   - bounded interface, not a planner/persona;
   - explicit retry/recovery budget if used;
   - recovery cannot rewrite the historical evidence that caused failure;
   - recovery result must re-enter normal validation before admission.

## Historical handling

Historical XI/ixC material under `archive/` is evidence and prior art, not executable authority.

Known historical contradictions/defects must be either:

- resolved in v1 with an explicit decision recorded in documentation, or
- declared out of scope for v1 with a reason and no dangling runtime dependency.

Do not silently repair archived files.

## KSL-01 frozen outputs

At minimum:

- active Python package for XI v1;
- version identifier for the protocol/runtime;
- canonical issue-code vocabulary;
- check-contract implementation matching `spec/check-contract.schema.json` or a deliberately versioned replacement;
- watchdog-result implementation matching its schema or versioned replacement;
- receipt implementation matching its schema or versioned replacement;
- admission implementation;
- provenance implementation;
- recovery base/interface;
- unit tests including negative/failure cases;
- one deterministic CLI or module entry point that verifies an artifact/check set and emits a receipt;
- `docs/XI_V1_FREEZE.md` documenting recovered vs new decisions and the exact v1 boundary.

## KSL-01 exit gate

KSL-01 is complete only when all are true:

- one and only one active audit semantic exists;
- issue codes are stable and tested;
- same canonical input + same contract produces byte-stable canonical result/receipt fields except explicitly excluded temporal fields;
- FAIL cannot be promoted by downstream code;
- archived contradictory implementations are not imported by active runtime;
- all active tests pass;
- a machine-readable freeze receipt records version, files/hashes, test result, and known limitations.

**KSL-01 freezes XI v1. KSL-02 must consume the frozen interface rather than redefining XI semantics.**

---

# KSL-02 — Automated Documentation & Proof Engine

## Kernel

Build a one-command engine that executes or ingests a controlled baseline-vs-capability proof run, submits the evidence to frozen XI v1, and automatically emits human-readable documentation and media only when XI admits the claimed proof.

## Primary command contract

A single command must be able to produce a proof package for one demo specification, with an eventual batch mode for multiple specifications.

Conceptual interface:

```bash
terminus-proof build <demo-spec>
terminus-proof verify <proof-dir>
```

Exact executable/module naming may differ if documented and tested.

## Demo specification

A declarative demo spec must identify at least:

- demo/skill/capability ID;
- claim being tested;
- fixture/input;
- baseline configuration;
- augmented configuration;
- model/provider identity or a deterministic mock fixture for tests;
- tool surface, if relevant;
- checker/check-contract set;
- public-safe redaction policy;
- rendering metadata such as title and concise explanatory labels.

The spec must make the intended changed variable explicit.

## Proof execution contract

The engine must support:

1. **Baseline evidence**
2. **Augmented/capability evidence**
3. **Parity proof**
   - model parity where required;
   - fixture parity;
   - tool-surface parity;
   - configuration parity except declared changed variables.
4. **XI validation/admission**
5. **Public-safe projection/redaction**
6. **Documentation rendering**
7. **Media rendering**
8. **Independent verification of the generated proof package**

The first implementation may use fixture-backed/mock executions for deterministic tests, but architecture must expose an adapter boundary for GTD/Labyrinth execution evidence.

GTD/Labyrinth may be inspected as read-only reference. Do not modify it during this UKSL unless absolutely required and explicitly justified.

## Required proof-package outputs

For each admitted proof, emit a deterministic directory containing at least:

```text
proofs/<proof-id>/
├── demo.mp4
├── thumbnail.png
├── README.md
├── proof.json
├── receipt.json
├── baseline.json
├── augmented.json
├── findings.json
├── transcript.txt
└── listing-assets.json
```

Additional manifests/assets are allowed.

## Media requirements

- no manual video editing required;
- use local deterministic rendering where practical;
- `ffmpeg` is available and may be used;
- Pillow is available and may be used;
- video must be understandable muted;
- show the contract, baseline result, augmented result, changed variable, XI verdict, and receipt/provenance summary;
- do not fabricate conversational steps or results absent from evidence;
- rendering must be driven from proof artifacts, not hand-authored green checks.

## Fail-closed marketing rule

If the proof is not established, the engine must not emit an admitted marketing demo as though it were successful.

Examples:

- parity failure -> no admitted success video;
- XI FAIL -> no admitted success video;
- unsupported claim -> no admitted success video;
- redaction failure/private-data leak -> no public-facing output;
- incomplete receipt -> package fails verification.

A failed attempt may emit diagnostic artifacts in a clearly non-admitted state.

## KSL-02 integration target

Include at least one end-to-end canonical example for **Claim Boundary Audit** or an equivalently narrow skill fixture demonstrating:

- same task/fixture;
- baseline behavior;
- capability-enabled behavior;
- deterministic XI evaluation;
- admitted receipt;
- auto-generated README;
- auto-generated thumbnail;
- auto-generated MP4;
- independent `verify` pass.

The example must be runnable without manual editing.

## KSL-02 exit gate

KSL-02 is complete only when all are true:

- one command builds the canonical proof package;
- one command independently verifies it;
- XI v1 is consumed as a dependency/interface, not reimplemented inside the renderer;
- negative tests prove failed parity/audit/redaction cannot produce an admitted success package;
- generated JSON parses and validates;
- thumbnail opens as a valid image;
- MP4 probes successfully with ffmpeg/ffprobe;
- README/listing assets derive from admitted evidence;
- all tests pass;
- a final machine-readable UKSL receipt records KSL-01 and KSL-02 closure and any known limitations.

---

# Traversal law

1. Complete and freeze KSL-01 before KSL-02 may depend on XI semantics.
2. KSL-02 may begin scaffolding before KSL-01 closure, but must not freeze duplicated XI behavior.
3. If documentation-engine requirements expose a missing XI primitive, route the change back through KSL-01 as an explicit v1 amendment before consuming it.
4. Do not broaden scope into hosted services, marketplace publication, browser automation, or GTD refactoring.
5. Prefer small standard-library-first deterministic components. Add dependencies only when they materially reduce risk or complexity.
6. Every completion claim requires observable receipts/tests.
