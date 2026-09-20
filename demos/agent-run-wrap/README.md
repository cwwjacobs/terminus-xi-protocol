# Agent-run wrap spike

Thin wrapper around one fixture-synthetic agent run. XI admits a canonical
`run-artifact.json`; this directory is the demo, not a persona agent.

## How to run

From the repository root:

```bash
PYTHONPATH=src python demos/agent-run-wrap/run.py
```

Writes a scratch package under `runs/agent-wrap/<run_id>/`:

```
events.jsonl
run-artifact.json
receipt.json
drive_export.json   # LocalOnlyExporter stub (status=stubbed) unless a Drive exporter is injected
MANIFEST.json       # written before export, then refreshed to include drive_export.json
```

The fixture is a short **failing** multi-step tool trace (search ok, fetch
error, canned halt). The *trace* can still be `ADMIT`ted when observation is
well-formed: admission is about the package, not agent success.

Pre-tool kill-switch: `evaluate_tool_proposal(...)` returns `ALLOW` or `HALT`
before a fixture tool runs. Default-deny allowlist (`search`, `fetch`);
unknown names HALT. The sealed policy never enters events or prompts. Online
HALT is not XI admission — the halted package is still submitted to
`verify_artifact` and is non-`ADMIT`. `gate_disabled` is test-only (no demo
CLI flag) and defaults to off on `wrap_run` / `wrap_plan`.

```bash
PYTHONPATH=src python demos/agent-run-wrap/run.py --hostile
```

Event timestamps are **fixture-fixed** (`2026-09-08T12:00:00Z` plus seq
seconds). They do not read the wall clock. Receipt `created_at_utc` still uses
XI's clock; the demo sets `TERMINUS_XI_NOW=2026-09-08T12:00:00Z` so receipts
are reproducible.

## Admit path

`terminus_xi.engine.verify_artifact` is the only admit path. The wrapper does
not call `build_receipt` or `decide`. Equivalent CLI:

```bash
python -m terminus_xi verify runs/agent-wrap/<run_id>/run-artifact.json \
    --contracts src/terminus_agent_wrap/contracts/agent-run.contracts.json \
    --boundary agent.run.v1 \
    --policy src/terminus_agent_wrap/policies/agent-run.policy.json \
    --receipt /tmp/replay-receipt.json
```

Spike contracts (stdlib predicates, no model/socket/clock): `event_count >= 1`,
required kinds present (`run_start`, `tool_call`, `tool_result`, `run_end`),
digests well-formed. `decision` is an **allowed** kind (the fixture still
emits one canned line) but is **not** required for ADMIT.

`run-artifact.json` carries a digest-only `events` projection of the JSONL
(no raw payloads). The XI receipt covers that artifact; it does not embed the JSONL.

## Prune rule

Local `runs/agent-wrap/` (or `TERMINUS_AGENT_WRAP_SCRATCH`, or
`/workspace/xi-traces/<run_id>/`) is **scratch**. Drive is the durable archive.

`LocalOnlyExporter` writes `drive_export.json` with `"status": "stubbed"`.
Prune **refuses** stubbed, partial, and failed exports, and sha256 mismatches.
It deletes scratch only for `"status": "exported"` with a sha256 equal to the
run-artifact's canonical digest.

Drive is save/backup only: the adapter never deletes remote objects. Title
collisions get a unique title (short content hash) or fail closed — never
overwrite-in-place.

### FakeTransport vs real transport

`GoogleDriveExporter` does not import MCP. Inject a `DriveTransport` with only
`search_files(query)` and `create_file(...)` (create folder or upload bytes,
conversion off):

- Tests: `GoogleDriveExporter(FakeDriveTransport())`.
- Real Drive: a thin wrapper around the Drive MCP/API `search_files` /
  `create_file` tools. Do not expose trash or update on that protocol.

Remote layout is `Terminus/XI-Traces/<run_id>/`. `status: "exported"` requires
every intended upload (`events.jsonl`, `run-artifact.json`, `receipt.json`,
`MANIFEST.json`) to succeed with a remote id. Each ack `files[].sha256` is
the local bytes hash of what was uploaded.

## Freeze

Zero edits under `src/terminus_xi/**`. Wrapper code lives in
`src/terminus_agent_wrap/`. Contracts live next to the wrapper, not beside
`contracts/xi-selftest.*`.
