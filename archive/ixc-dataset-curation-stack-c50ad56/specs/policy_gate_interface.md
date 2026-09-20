# Live Policy Gates (v1)

This repo implements a minimal, deterministic policy-gate layer (Stage 4) that enforces the frozen `context_contract` at runtime.

## Insertion points

Events are evaluated in this order:

1. `pre_exec` — after the runner has constructed/updated the job context, before any agent runs.
2. `pre_agent` — before each agent stage (`xiProvenanceAgent`, `xiAuditAgent`, `xiCurateAgent`).
3. `post_agent` — after each agent stage.
4. `post_exec` — after pipeline output has been committed.

Policy evaluation MUST occur before the first agent stage (`pre_exec`).

## Policy profile resolution order

Given `policy_profile_id`:

1. Tenant override:
   `.tenants/<tenant_id>/policies/<policy_profile_id>.json`
2. Repo built-in:
   `specs/policies/<policy_profile_id>.json`
3. Repo default fallback:
   `specs/policies/default.json`

## Policy format (v1)

A policy profile is JSON:

```json
{
  "id": "free",
  "version": "1",
  "rules": [
    {"id":"require_contract_fields","type":"require_fields","fields":["tenant_id","job_id","graph_id","graph_version","policy_profile_id","meter_scope","execution_mode","dataset_refs"]},
    {"id":"allow_execution_modes","type":"allow_execution_modes","modes":["batch","scheduled"]},
    {"id":"max_pre_exec_payload","type":"max_payload_bytes","event":"pre_exec","max":10000000},
    {"id":"allow_model_classes","type":"allow_model_classes","classes":["cheap","transform"]},
    {"id":"allow_all_rest","type":"allow_all"}
  ]
}
```

Rule types supported by the engine:

- `require_fields` — denies if any required field is missing/empty.
- `allow_execution_modes` — denies if `execution_mode` is not in `modes`.
- `deny_execution_modes` — denies if `execution_mode` is in `modes`.
- `allow_graph_ids` — denies if `graph_id` is not in `graph_ids`.
- `allow_model_classes` — enforced during tool/model dispatch; at `pre_exec` only validates `requested_model_class` if present.
- `allow_model_ids` — denies if `model_id` is not in `model_ids` (enforced at tool/model dispatch).
- `allow_tools` — denies if `tool_name` is not in `tools` (enforced at tool dispatch).
- `deny_tools` — denies if `tool_name` is in `tools` (enforced at tool dispatch).
- `max_payload_bytes` — for the given `event` (usually `pre_exec`), denies if `payload_bytes_in` exceeds `max`.
- `allow_all` — terminal allow.

Unknown `type` values are treated as no-ops for forward compatibility.


## Decision recording

Each checkpoint appends a structured record into the job context under:

`context["policy_decisions"][]`

Records include:
- gate
- allow
- reason
- policy_profile_id
- details

## Failure behavior

If a gate denies, the runner raises `PolicyViolation` and the job fails fast.

## Failure semantics

If a policy decision is `allowed=false`, the runner raises `PolicyViolation` and the job is considered failed/retriable depending on queue policy.


## Tool/Model call gates (v1)
- `pre_tool_call`: before any model/tool invocation via ToolRouter
- `post_tool_call`: after invocation (duration, metadata)
ToolRouter supplies context fields: `call_type`, `tool_name` or `model_id`/`model_class`, `agent_name`.
