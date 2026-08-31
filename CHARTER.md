# Terminus XI Charter v0.1

This is the active operational law for Terminus XI Protocol vNext.

## Authority layers

1. **Capability** performs work or proposes a transformation.
2. **XI Check** evaluates explicit deterministic predicates over bounded inputs.
3. **XI Admission** decides whether an artifact may cross a governed boundary.
4. **XI Receipt** records the exact evidence and decision surface.

Probabilistic output may inform a decision but may not override a deterministic failed invariant.

## Fixed boundary rule

**No unvalidated artifact may cross a governed stage boundary.**

A boundary identifies the artifact/state entering it, the applicable check set and versions, the decision policy, and the resulting receipt.

## Determinism rule

For a declared deterministic check, identical canonical inputs plus identical check version and configuration must yield an identical verdict and findings payload.

## Provenance rule

XI binds a decision to the exact relevant inputs by canonical identity, normally cryptographic digests plus explicit version/configuration identifiers.

A digest proves identity/integrity within its covered bytes. It does not prove truth, safety, authorship, authority, or semantic correctness.

## Failure rule

Failure must be explicit, typed, attributable to a check or boundary, and retained when required for audit.

Unknown, skipped, errored, incomplete, or unverifiable states are never silently converted to PASS.

## Drift rule

Drift must be surfaced rather than normalized away. A changed model, fixture, tool surface, policy, schema, source set, or checker version is a changed evidence surface unless the governing contract explicitly declares otherwise.

## Contradiction rule

Contradictory required evidence is a loud failure condition. XI uses typed machine-stable codes, never free-text string matching, for promotion-blocking conditions.

## Admission rule

XI admission is bounded to a named boundary. PASS at one boundary is not a general certification of safety, correctness, legality, or fitness.

## Recovery rule

A rejection may identify a bounded recovery path. Recovery does not erase the failed receipt. Recovered artifacts must re-enter the applicable boundary and earn a new decision.

## Evidence/authority rule

Observed evidence does not inherit authority merely because it was retrieved by an authorized tool or produced by a trusted model. Authority is supplied by the governing contract.

## Minimality rule

XI prefers small deterministic predicates and composable checks over model-shaped complexity. If a comparison, parser, hash, schema validator, state machine, or finite rule can establish the invariant, use it.

## Historical boundary

Artifacts under `archive/` are historical evidence. They may inform vNext design, but no archived behavior is canonical unless explicitly re-admitted with tests and a recorded design decision.
