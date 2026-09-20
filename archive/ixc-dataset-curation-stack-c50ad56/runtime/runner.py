import os
from typing import Any, Dict, Optional

from agents.xi_audit_agent import xiAuditAgent
from agents.xi_curate_agent import xiCurateAgent
from agents.xi_provenance_agent import xiProvenanceAgent

from runtime.context_manager import ContextManager
from infra.token_budget import TokenBudgetEnforcer
from infra.job_queue import JobQueue
from infra.dataset_store import DatasetStore, json_bytes
from infra.policy_gates import PolicyGateEnforcer
from infra.metering import MeterEmitter
from infra.graph_registry import GraphRegistry, GraphRegistryError
from runtime.tool_router import ToolRouter


AGENT_CLASS_MAP = {
    "xiProvenanceAgent": xiProvenanceAgent,
    "xiAuditAgent": xiAuditAgent,
    "xiCurateAgent": xiCurateAgent,
}


class RunnerError(Exception):
    pass


def run_pipeline(
    dataset: Any,
    *,
    summary: Optional[str] = None,
    model_overrides: Optional[Dict[str, str]] = None,
    tenant_id: str,
    job_id: str,
    graph_id: str,
    graph_version: str,
    dataset_id: str,
    policy_profile_id: str,
    meter_scope: str,
    execution_mode: str,
    parent_dataset_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a job under the frozen context_contract v1.

    Returns the final persisted context dict.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

    # Context (tenant/job scoped)
    cm = ContextManager(tenant_id=tenant_id, job_id=job_id)
    context = cm.load()

    # Required contract fields
    context.update(
        {
            "tenant_id": tenant_id,
            "job_id": job_id,
            "graph_id": graph_id,
            "graph_version": graph_version,
            "policy_profile_id": policy_profile_id,
            "meter_scope": meter_scope,
            "execution_mode": execution_mode,
        }
    )

    # Optional execution hints (not part of frozen context_contract v1)
    if summary is not None:
        context.setdefault('input', {})['summary'] = summary
    if model_overrides is not None:
        context.setdefault('execution', {})['model_overrides'] = model_overrides

    # Metering (Stage 5)
    meter = MeterEmitter(
        tenant_id=tenant_id,
        job_id=job_id,
        meter_scope=meter_scope,
        graph_id=graph_id,
        graph_version=graph_version,
        policy_profile_id=policy_profile_id,
        execution_mode=execution_mode,
    )
    meter.emit("job_start", count=1)

    # Dataset store (Stage 3)
    store = DatasetStore(tenant_id=tenant_id, dataset_id=dataset_id)

    raw_bytes = json_bytes(dataset)
    raw_blob_sha = store.write_blob(raw_bytes)
    meter.emit("payload_bytes_in", bytes=len(raw_bytes))
    meter.emit("dataset_blob_write", bytes=len(raw_bytes), labels={
        "dataset_id": dataset_id,
        "blob_sha256": raw_blob_sha,
        "stage": "ingest",
    })

    input_manifest = {
        "dataset_id": dataset_id,
        "parent_dataset_version": parent_dataset_version,
        "created_by": {"job_id": job_id, "graph_id": graph_id, "graph_version": graph_version},
        "artifacts": [{"type": "blob", "sha256": raw_blob_sha, "bytes": len(raw_bytes)}],
        "metadata": {"stage": "ingest"},
    }
    input_dataset_version = store.commit_manifest(input_manifest)
    context["dataset_refs"] = [
        {"dataset_id": dataset_id, "dataset_version": input_dataset_version, "access_mode": "read"}
    ]
    meter.emit("dataset_manifest_commit", count=1, labels={
        "dataset_id": dataset_id,
        "dataset_version": input_dataset_version,
        "stage": "ingest",
    })

    # Policy gates (Stage 4)
    policy = PolicyGateEnforcer(repo_root=repo_root, tenant_id=tenant_id, policy_profile_id=policy_profile_id, job_id=job_id)
    policy.pre_exec(context=context, payload_bytes=len(raw_bytes))

    # Context shedding / token budget (optional)
    token_guard = TokenBudgetEnforcer()
    status, used, ratio = token_guard.check(str(context))
    context.setdefault("token_budget", []).append({"status": status, "used": used, "ratio": ratio})
    if status == "critical":
        cm.summarize_if_large()

    # Graph resolution + compatibility (Stage 6)
    registry = GraphRegistry(repo_root=repo_root)
    try:
        graph = registry.load_graph(graph_id=graph_id, graph_version=graph_version)
    except GraphRegistryError as e:
        raise RunnerError(str(e)) from e

    # Execute agents in declared sequence
    current = dataset
    for agent_name in graph.sequence:
        cls = AGENT_CLASS_MAP.get(agent_name)
        if cls is None:
            raise RunnerError(f"Unknown agent in graph {graph_id}@{graph_version}: {agent_name}")

        policy.pre_agent(context=context, agent_name=agent_name)
        meter.emit("agent_run", count=1, labels={"agent_name": agent_name})

        tool_router = ToolRouter(agent_name=agent_name, context=context, policy=policy, meter=meter, repo_root=".")
        agent = cls(context, tool_router=tool_router)
        current = agent.run(current)

        policy.post_agent(context=context, agent_name=agent_name)

    # Commit output dataset version
    out_bytes = json_bytes(current)
    out_blob_sha = store.write_blob(out_bytes)
    meter.emit("payload_bytes_out", bytes=len(out_bytes))
    meter.emit("dataset_blob_write", bytes=len(out_bytes), labels={
        "dataset_id": dataset_id,
        "blob_sha256": out_blob_sha,
        "stage": "output",
    })

    out_manifest = {
        "dataset_id": dataset_id,
        "parent_dataset_version": input_dataset_version,
        "created_by": {"job_id": job_id, "graph_id": graph_id, "graph_version": graph_version},
        "artifacts": [{"type": "blob", "sha256": out_blob_sha, "bytes": len(out_bytes)}],
        "metadata": {"stage": "output"},
    }
    output_dataset_version = store.commit_manifest(out_manifest)

    # Append dataset refs (explicit versions)
    context.setdefault("dataset_refs", []).append(
        {"dataset_id": dataset_id, "dataset_version": output_dataset_version, "access_mode": "write"}
    )
    meter.emit("dataset_manifest_commit", count=1, labels={
        "dataset_id": dataset_id,
        "dataset_version": output_dataset_version,
        "stage": "output",
    })

    # Post-exec policy
    context["output_dataset_version"]=output_dataset_version
    policy.post_exec(context=context)

    cm.save()
    meter.emit("job_complete", count=1, labels={"output_dataset_version": output_dataset_version})
    return context


def process_with_queue(job_queue: JobQueue, tenant_id: str, handler_fn, max_retries: int = 5):
    """Tenant-scoped queue processing."""
    while not job_queue.is_empty():
        job = job_queue.dequeue(tenant_id)
        if not job:
            continue
        try:
            handler_fn(job)
        except Exception as e:
            if job.get("retry_count", 0) < max_retries:
                job_queue.retry(job)
            else:
                job_queue.mark_failed(job, str(e))
