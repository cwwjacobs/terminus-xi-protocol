# Decision: one audit semantic for Terminus XI v1

Status: **decided**, frozen into XI v1.
Applies to: KSL-01 clause "resolve the old divergent xiAudit semantics into one
stable issue-code and PASS/WARN/FAIL system".

## The contradiction in the historical line

Three `xiAuditAgent` implementations survive under `archive/`, and they do not
agree about what an audit *is*.

| Evidence | Finding shape | Severity | Blocking |
|---|---|---|---|
| `archive/ixc-dataset-curation-stack-c50ad56/agents/xi_audit_agent.py` | `{"check": "payload_bytes", "value": 12}` | none | none |
| `archive/recovered/xi_audit_agent_top_level.py` | identical to the above, different import path | none | none |
| `archive/recovered/unstubbed-v1/xi_audit_agent.py` | `{"finding_id": "fdg_<uuid4>", "code": ..., "severity": ..., "message": ..., "details": {...}}` | `info` / `warning` / `error` | none |

Six concrete defects follow from that table.

1. **Two incompatible finding envelopes.** One emits untyped dictionaries keyed
   by `check`; the other emits coded findings. Downstream code cannot read both,
   so whether a contradiction is *visible* depends on which implementation ran.
   This is the defect recorded in `docs/KNOWN_HISTORICAL_DEFECTS.md`.
2. **No verdict at all.** Both implementations end with `return dataset`
   regardless of what they found. `INVALID_ACTIONS` is raised at severity
   `"error"` and the dataset is still returned unchanged. Nothing in the audit
   layer can stop a promotion.
3. **A soft pass for an unestablished invariant.** When payload size could not
   be measured, `unstubbed-v1` recorded `PAYLOAD_SIZE_UNKNOWN` at severity
   `"warning"`; the older implementation swallowed the exception into
   `{"check": ..., "error": str(e)}`. Either way, "we could not check this" was
   treated as milder than "we checked this and it was bad".
4. **Non-determinism inside a deterministic layer.** `_finding()` mints a
   `uuid4` per finding and the surrounding event gets another. Two identical
   runs over identical input produce different audit records, so no two runs are
   comparable and no audit record has a stable identity.
5. **A model inside the audit.** Both implementations call
   `tool_router.invoke_model(model_class="cheap", ...)` to generate audit notes,
   and `unstubbed-v1` converts a failure of that call into an
   `AUDIT_NOTES_FAILED` warning *in the audit's own finding list*. A probabilistic
   call is thereby inside the deterministic evidence surface.
6. **Free-text severity routing elsewhere in the line.**
   `archive/recovered/prism/xiPrismAgent_completed.py:441` selects an error code
   with `"PRISM_NODE_NOT_FOUND" if "not found" in reason.lower() else
   "PRISM_ERROR"`. A promotion-relevant code is chosen by substring matching on
   a human-readable string.

## The decision

XI v1 has **exactly one** audit path: `terminus_xi.audit.run_check`. There is no
second implementation, no alternate envelope, and no configuration that selects
between semantics.

1. **One finding envelope.** A finding is `{code, severity, message,
   evidence_ref?}`. `code` must be a member of the frozen vocabulary in
   `terminus_xi.codes.ISSUE_CODES`.

2. **Severity is a property of the code, not of the caller.** Check
   implementations return a code and a message; they never choose a severity.
   `Finding.to_dict()` derives it. This removes the case where the same
   condition is a `warning` in one implementation and an `error` in another.

3. **Four severity classes, four verdicts, one derivation.**
   `INFO | WARN | FAIL | ERROR` map to `PASS | WARN | FAIL | ERROR` by taking the
   worst severity present (`verdict_from_severities`). A result with no findings
   is `PASS`. A receipt verifier re-derives the verdict from the recorded
   findings, so a verdict that does not follow from its own evidence is caught.

4. **Escalation is one-directional and contract-declared.** A check contract may
   list `escalate_codes` to turn a `WARN` code into `FAIL` at that boundary. It
   may never de-escalate `FAIL` or `ERROR`, and `terminus_xi.contracts` refuses
   at load time to build a contract that tries.

5. **Unestablished is `ERROR`, never `WARN`.** `PAYLOAD_SIZE_UNKNOWN` is `ERROR`
   in v1, reversing the historical `warning`. Any `ERROR` result yields an
   `ERROR` admission, which is never admitted. The same rule covers a pointer
   that did not resolve (`INPUT_POINTER_MISSING`), a check with no registered
   implementation (`CHECK_NOT_FOUND`), and a check that raised (`CHECK_ERROR`).

6. **A check that leaves the vocabulary invalidates its own contract.** If an
   implementation emits a code outside `ISSUE_CODES`, `run_check` discards its
   findings and returns `CONTRACT_INVALID` (`ERROR`). A checker cannot widen the
   vocabulary at runtime, which is what makes "typed codes, never free-text"
   enforceable rather than aspirational.

7. **Verdict is separated from admission.** A check says whether an invariant
   held. `terminus_xi.admission.decide` says whether the artifact may cross the
   boundary. `ERROR` and `FAIL` handling is not configurable; only `WARN`
   handling is a policy choice, and the policy must state it explicitly. This is
   the mechanism the historical line lacked entirely.

8. **No model in the loop.** Nothing under `src/terminus_xi/` imports a client,
   opens a socket, reads a clock inside a check, or calls a model. Audit notes
   are not an XI concern.

9. **Determinism is machine-checked.** Findings carry no random identifier.
   `created_at_utc` is the single temporal field, lives on the receipt envelope,
   and is excluded from `stable_core_sha256`. The freeze receipt records a
   determinism probe that verifies the same artifact under two different clocks
   produces the same stable core.

## What was not carried forward, and why

- **`uuid4` finding identifiers.** A finding is identified by its code, its
  message, and the input digest of the check that produced it. Adding a random
  id destroys comparability and buys nothing.
- **The `details` payload.** Historical findings carried an open-ended
  `details` dict. v1 uses a typed code plus a human-readable `message` and an
  optional `evidence_ref`. An open payload inside a canonical document is a
  place for undeclared semantics to accumulate.
- **Domain findings in the XI vocabulary.** `ROW_COUNT`, `SPARSE_FIELDS`,
  `EXACT_DUPLICATES_PRESENT`, and `INVALID_ACTIONS` were dataset-curation
  concerns. XI v1 ships `MEASUREMENT` for observations and lets consumers
  register their own checks; what it does not allow is a consumer inventing a
  *code*.
- **`self.warn()` side channels.** A warning that goes somewhere other than the
  finding list is a finding that the receipt does not record.

## Consequences a reader should know about

- This decision is enforced by `tests/test_codes.py`, which pins the severity
  class of every load-bearing code, and by `tests/test_contracts_and_audit.py`,
  which asserts each typed failure mode.
- Adding a code to the vocabulary is a compatible change. Removing one, or
  changing its severity class, is not: it changes what gets admitted.
- The archived implementations remain on disk, unrepaired. They are evidence of
  what was decided against.
