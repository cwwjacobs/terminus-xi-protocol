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
