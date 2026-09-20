# Terminus Proof — the documentation and proof engine

Engine: `terminus-proof/1.0.0`. Consumes frozen Terminus XI v1
([`XI_V1_FREEZE.md`](XI_V1_FREEZE.md)) as its admission substrate.

The engine turns a controlled baseline-vs-capability pair into documentation and
media. Its whole design is arranged around one rule: **documentation may only
claim what admitted evidence supports**, and XI decides what is admitted.

## The two commands

```bash
python -m terminus_proof build demos/claim-boundary-audit.demo.json
python -m terminus_proof verify proofs/<proof-id>
```

They share nothing but files. `build` writes a directory; `verify` reads a
directory it did not produce, re-derives what it can, and re-runs the frozen
contracts. Exit codes: `0` admitted/verified, `3` not admitted or verification
failed, `5` specification or adapter failure.

## The three boundaries

A build crosses three XI boundaries, in order. None of them is optional and none
can be skipped by configuration.

```
recordings ──► redact once, over both arms together
                     │
                     ├── proof.arm.baseline   ── XI ──► receipt  (expected: REJECT)
                     ├── proof.arm.augmented  ── XI ──► receipt  (expected: ADMIT)
                     │
               package artifact  ── XI ──► receipt
                     │
                     └── ADMIT? ──► README, listing copy, thumbnail, video
                         else   ──► NOT_ADMITTED.md and nothing else
```

The baseline arm is *expected* to be rejected. That rejection is the evidence
the proof rests on, so it is recorded as a first-class receipt rather than
treated as an error.

## What the package boundary actually checks

`contracts/proof-package.contracts.json`, all ten required by
`policies/proof-package.policy.json`:

| Check | Establishes |
|---|---|
| `proof.artifact_shape` | The artifact matches its frozen schema. |
| `proof.parity.model` | Both arms recorded the same model identity. |
| `proof.parity.fixture` | Both arms ran against the same fixture. |
| `proof.parity.tool_surface` | Both arms exposed the same tools. |
| `proof.parity.config` | The declared variable moved to the declared values, and nothing else differs. |
| `proof.spec.faithful` | The recordings are the ones the specification describes. |
| `proof.arms.bound` | Each arm file hashes to what the artifact says it does. |
| `proof.evidence.complete` | Each arm has a transcript, an evidence set, a raw-execution digest, and an XI outcome. |
| `proof.claim.supported` | The baseline was blocked, the augmented was admitted, and every blocking code was cleared. |
| `proof.redaction.public_safe` | No deny pattern matches any public surface, and every policy rule fired. |

Parity is **proved, not assumed**. Each arm's model, tool surface, and effective
configuration come from what the adapter recorded about the execution, and the
checks compare those recordings. The specification's declared surface is
compared separately, by `proof.spec.faithful`, so swapping a recording for a
different run is a detected contradiction rather than a silent substitution.

## Redaction

Redaction runs **once**, over one document holding the fixture evidence and both
arms, so a rule's hit count is a fact about the whole proof.

A policy carries *rules* (what to remove: regex masks and JSON-pointer drops)
and *deny patterns* (what must never survive). It never carries a secret
literal, because the policy ships inside the published package and is read by a
deterministic check.

The projector does not grade its own work. It applies the policy and records
what it did — per-rule hit counts and any rule that fired fewer times than it
declared. `proof.redaction.v1` inside XI then re-reads the policy, scans the
public surfaces itself, and refuses the package if a deny pattern matches or a
declared rule did not fire. A leak report names the pattern and the JSON path,
never the matched text: a report that quotes the leak is a second leak.

## Media

`proof artifact → SVG → ffmpeg (librsvg) → PNG frames → ffmpeg (libx264) → MP4`

Seven slides: title, claim, contract set, the two arms side by side, the changed
variable, the XI verdict table, and the receipt/provenance summary. Every value
on every slide is read out of the artifact or a receipt — `src/terminus_proof/
slides.py` contains no literal verdict, code, or count. Feeding it a rejected
receipt produces a deck that says `REJECT`, which is what
`tests/test_media_and_docs.py` asserts.

Pillow is not required. The local `ffmpeg` is built with librsvg, so it
rasterizes the slides directly with real font shaping, keeping the whole media
path inside one tool. The SVG sources and every rasterized frame ship in the
package under `media/`, so a reader can check the video against its inputs.

`-fflags +bitexact` stops ffmpeg writing an encoder banner and a wall-clock
creation time into the container.

## The proof directory

```text
proofs/<proof-id>/
├── demo.mp4                     ├── proof.json          the envelope + artifact
├── thumbnail.png                ├── proof-manifest.json completeness + integrity index
├── README.md                    ├── receipt.json        package boundary receipt
├── baseline.json                ├── receipts/
├── augmented.json               │   ├── baseline.receipt.json
├── findings.json                │   └── augmented.receipt.json
├── transcript.txt               ├── contracts/          the contract sets, as judged
└── listing-assets.json          └── policies/           the policies, as applied
                                     media/              SVG sources and PNG frames
```

`<proof-id>` is `<demo-id>-<first 12 hex of the artifact digest>`. The artifact
carries no clock reading and no receipt digest, so the same inputs always
produce the same proof id — and `verify` re-derives it.

A build that is not admitted writes to `proofs/not-admitted/<proof-id>/` and
emits only `NOT_ADMITTED.md`, the receipts, the findings, the arm files, and the
transcript. No video, no thumbnail, no README, no listing copy.

## What `verify` establishes

Independently of the build:

1. every manifest-listed file is present with the listed digest and byte count;
2. every required file is listed, and the directory holds no unlisted file;
3. `proof.json` validates, and the artifact digest and proof id re-derive from
   the artifact itself;
4. each receipt is internally consistent, covers the artifact it names, and its
   admission follows from its own recorded findings;
5. each arm file hashes to what the artifact binds, and its receipt matches;
6. the contract-set and policy snapshots match the digests the artifact binds —
   so the contracts in the package are the ones it was judged against;
7. re-running those contracts over the stored artifact reproduces the recorded
   verdicts, codes, and admission;
8. re-running the arm contracts over each arm file reproduces its verdicts;
9. no deny pattern matches the README, transcript, listing copy, arm files, or
   public projection;
10. the listing copy carries the artifact's claim and its full not-claimed list;
11. `thumbnail.png` parses as a PNG (magic, CRC-checked IHDR, IEND) and
    `demo.mp4` probes with `ffprobe`.

`tests/test_proof_verify.py` tampers with a real admitted package sixteen
different ways — including resealing the manifest afterwards, as a forger with
the tooling would — and asserts that each one is caught.

## The adapter boundary

`terminus_proof.adapters.ExecutionAdapter` answers one question: *what did this
arm actually do?* The shipped `fixture-recording` adapter replays a recorded
execution from disk, which is what makes the tests deterministic and offline.

A GTD/Labyrinth run directory maps onto the same shape under different names —
`run.json` for the model and configuration surface, `manifest.json` and
`evidence/*.json` for the evidence set, `records.jsonl` for the trace. An
adapter for it implements the protocol and returns a `RawExecution`; nothing
else in the engine changes and no XI semantics move. That repository is
read-only reference for this work and is deliberately not imported.

## Limits

- The claim checks are bounded lexical and structural predicates. `CLAIM_OVERBROAD`
  means a statement used a phrase from a frozen lexicon, not that a statement is
  false; `claim.evidence_cited` means an identifier resolves, not that the
  evidence supports the claim.
- A proof covers one fixture, one model identity, and one recorded pair of
  executions. It establishes nothing about any other fixture or model.
- `ADMIT` is bounded to the named boundary. It is not a certification of the
  capability.
- Byte-identical MP4 output is expected from the same machine and ffmpeg build,
  not across machines. Verification re-hashes what is actually on disk, so this
  does not weaken it.
