# xi agents — unstubbed v1 pack

This pack upgrades the early xi workflow agents into more useful, auditable v1 components.

## Included

- `xi_provenance_agent.py`
  - records raw + canonical SHA-256
  - records dataset kind and run/job refs
  - appends provenance events without mutating the dataset

- `xi_audit_agent.py`
  - records payload size and dataset kind
  - audits row datasets for exact duplicates and sparse fields
  - optionally validates `action` values against a supplied contract

- `xi_curate_agent.py`
  - exact dedup for `list[dict]`
  - schema normalization
  - optional required-field enforcement
  - optional wrapper return mode
  - records artifact refs and canonical hashes

- `archivist_agent.py`
  - cleaner goal/scope separation
  - structured event records with IDs
  - friction and drift-finding heuristics
  - minimal fix suggestions
  - save/load JSON support

- `artifactor_agent.py`
  - sidecar artifact fingerprinting
  - raw/canonical hashes
  - lightweight voxel/structural signature
  - records fingerprints in context instead of bloating runtime schemas

## Why this shape

We want:
- lean runtime schemas
- sidecar auditability
- deterministic curation
- typed provenance/audit events
- a cleaner path from workflow helpers to corpus infrastructure

## Notes

These files keep to the standard library plus the existing `BaseAgent` import path used by the original files:
`from agents.base_agent import BaseAgent`
