# Known Historical XI Defects

These are preserved defects, not active Terminus XI behavior.

## Divergent audit semantics

Recovered XI material contains more than one `xiAuditAgent` implementation with incompatible contradiction signaling. Historical downstream code could therefore fail to reject a contradiction depending on which implementation produced the finding.

vNext response: promotion-blocking conditions use typed machine-stable finding codes defined by contract, not free-text matching.

## Historical runtime parse failure

The minimal snapshot of `cwwjacobs/ixC-Dataset-Curation-Stack` at commit `c50ad56` contains `runtime/tool_router.py` that does not parse as Python due to an indentation error around line 204.

The historical file is preserved unchanged. It is not active runtime code and was not repaired during import.

See `archive/HISTORICAL_PARSE_CHECKS.tsv` for the machine-generated parse receipt.

## Incomplete charter enforcement

Historical audits indicate some charter concepts were specified more strongly than they were implemented, including retry/escalation/recovery/drift behavior. vNext must admit each mechanism separately through explicit tests rather than assuming charter text proves implementation.

## Status in v1

Each defect above is answered in [`XI_V1_FREEZE.md`](XI_V1_FREEZE.md) under
"Historical contradictions and how v1 answers them". The divergent audit
semantics are resolved in [`AUDIT_SEMANTICS_DECISION.md`](AUDIT_SEMANTICS_DECISION.md),
with the specific evidence for each contradiction.

The historical files themselves are unchanged. `tests/test_quarantine_and_cli.py`
asserts that `runtime/tool_router.py` still fails to parse, so the preserved
defect cannot be quietly repaired to make anything pass.
