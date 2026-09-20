# Recovered vs New

This file prevents new architectural choices from being laundered into XI history.

## Recovered

Directly evidenced in historical XI material:
- deterministic wrappers at stage boundaries;
- provenance attachment and cryptographic fingerprints;
- explicit validation and rejection;
- canonicalized/normalized outputs;
- visible failure rather than silent corruption;
- drift surfacing;
- bounded recovery intent;
- a fixed rule forbidding unvalidated artifacts from crossing stage boundaries;
- separation between capability, governance wrappers, and charter/law.

## Recovered problems

Historical material contains contradictions and incompleteness, including divergent xiAudit implementations and mismatched contradiction codes, plus charter behaviors that were not fully enforced in code.

## New vNext decisions

Chosen for Terminus XI Protocol rather than claimed as recovered fact:
- `watchdog-result.v1` canonical per-check result envelope;
- `xi-receipt.v1` canonical boundary receipt envelope;
- typed machine-stable finding codes instead of free-text promotion logic;
- explicit `PASS | WARN | FAIL | ERROR` result states;
- separation of check verdict from boundary admission decision;
- archive quarantine as a hard source/runtime boundary;
- initial focus on deterministic watchdogs underneath probabilistic workers.

Every later major architectural decision should be labeled recovered, inferred, or new.

## Where the v1 decisions live

This file records the bootstrap position. The frozen v1 decisions, labelled
recovered / inferred / new, are in [`XI_V1_FREEZE.md`](XI_V1_FREEZE.md), and the
resolution of the divergent audit semantics is in
[`AUDIT_SEMANTICS_DECISION.md`](AUDIT_SEMANTICS_DECISION.md).
