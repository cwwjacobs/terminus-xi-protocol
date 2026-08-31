from typing import Any
import json

from agents.base_agent import BaseAgent


class xiAuditAgent(BaseAgent):
    """Performs lightweight checks and records findings in context."""

    def run(self, dataset: Any) -> Any:
        findings = []
        try:
            if isinstance(dataset, (bytes, bytearray)):
                size = len(dataset)
            else:
                size = len(json.dumps(dataset, default=str).encode("utf-8"))
            findings.append({"check": "payload_bytes", "value": size})
            if size > 10_000_000:
                self.warn("Dataset payload exceeds 10MB; consider chunking or compression.")
        except Exception as e:
            findings.append({"check": "payload_bytes", "error": str(e)})

        self.context.setdefault("audit", {})
        self.context["audit"]["findings"] = findings

        # Optional: generate compact audit notes via ToolRouter (deterministic mock model by default).
        summary = ((self.context.get("input") or {}).get("summary"))
        if isinstance(summary, str) and summary.strip() and self.tool_router is not None:
            res = self.tool_router.invoke_model(model_class="cheap", payload={"task": "audit_notes", "text": summary})
            self.context["audit"]["notes"] = res.output
            self.context["audit"]["notes_meta"] = {"model_id": res.model_id, "model_class": res.model_class, "duration_ms": res.duration_ms}

        return dataset
