# ixC Dataset Curation Stack (v1)

**Deterministic, auditable dataset curation for teams that cannot afford data ambiguity.**

This repository contains the ixC dataset curation stack: a prototype pipeline for ingesting, validating, normalizing, and curating datasets with design goals around reproducibility, provenance, and explicit failure behavior.

This is infrastructure for local or internal workflows, not a black-box SaaS. It is designed for teams who need to trace and understand how a dataset was constructed.

---

## What this is

A deployable pipeline designed to support:

* AI / ML teams preparing training data
* Data vendors and consultancies delivering datasets to clients
* Organizations operating under internal review or quality constraints

The stack prioritizes correctness before judgment and preserves lineage by construction.

---

## What this is not

* ❌ A hosted SaaS (by default)
* ❌ A chat assistant
* ❌ An autonomous agent making authoritative decisions
* ❌ A data labeling platform

Optional model-based decision support exists, but deterministic agents take precedence.

---

## Core design goals

* **Determinism**: identical inputs produce identical curated outputs
* **Auditability**: every transformation is recorded in context
* **Provenance**: cryptographic hashes, timestamps, job + tenant attribution
* **Non-destructive transforms**: original semantics preserved
* **Explicit failure**: invalid inputs fail loudly and early
* **Silence as success**: no output is a valid outcome

---

## Architecture overview

```
raw dataset
  → xiProvenanceAgent   (identity & lineage)
  → xiAuditAgent        (bounded checks & warnings)
  → xiCurateAgent       (deduplication & schema normalization)
  → [optional] decision-support model (non-authoritative)
  → selector / storage / dispatch
```

All agents are pure functions over `(dataset, context)` with side effects restricted to context updates.

---

## Included agents

### xiProvenanceAgent

* Computes SHA-256 fingerprint of inputs
* Attaches timestamps, job IDs, tenant IDs
* Never mutates the dataset

### xiAuditAgent

* Performs bounded, deterministic checks (e.g. payload size)
* Emits structured findings and warnings
* Optional deterministic summarization

### xiCurateAgent

* Enforces JSON-serializability
* Stable record deduplication
* Schema normalization across rows
* Attaches curation metadata and fingerprints

---

## Infrastructure features

* Token budget enforcement
* Parallel chunk workers
* Job queue + retry orchestration
* Azure Blob / S3 adapters
* Webhook / email dispatch
* Context-injection driven execution
* Fault-aware design

---

## Typical outputs

* Curated dataset (schema-stable, deduplicated)
* Provenance metadata (hashes, timestamps)
* Audit findings and warnings
* Curation metrics (before/after counts)

These artifacts are suitable for:

* downstream training
* internal review
* external audit
* long-term storage

---

## Deployment model

This stack is intended to be:

* run **inside your infrastructure**, or
* used as part of an **assisted dataset curation engagement**

No data is sent to third-party services unless explicitly configured.

---

## Current status

* Active prototype / v1
* Used for internal curation workflows
* Model-based decision support is optional and gated

---

## Commercial use

This repository supports a paid dataset curation and provenance offering.

For licensing, deployment support, or dataset curation consulting, contact:
**cwwjacobs@ixcore.io**

Commercial use requires written permission unless a future license states otherwise.

---

## Philosophy

**ixC = Intelligence by Clarity.**

We design systems that reduce ambiguity rather than amplify it.

> The model is not the product.
> The product is selectively saved, high-value decision artifacts produced during controlled simulation.

Determinism first. Judgment second. Silence is allowed.

---

## License

Copyright (c) 2026 Corey Jacobs.

All rights reserved.

This source is published for review and evaluation. Commercial use, redistribution, sublicensing, or incorporation into commercial products requires prior written permission.

For licensing inquiries, contact cwwjacobs@ixcore.io.
