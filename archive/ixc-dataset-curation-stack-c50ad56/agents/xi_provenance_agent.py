import datetime
import hashlib
import json
from typing import Any, Dict

from agents.base_agent import BaseAgent


class xiProvenanceAgent(BaseAgent):
    """Attaches provenance metadata to context; does not modify dataset."""

    def run(self, dataset: Any) -> Any:
        # Best-effort digest of the incoming dataset (bytes if possible, else JSON repr).
        try:
            if isinstance(dataset, (bytes, bytearray)):
                b = bytes(dataset)
            else:
                b = json.dumps(dataset, sort_keys=True, default=str).encode("utf-8")
            sha = hashlib.sha256(b).hexdigest()
        except Exception:
            sha = None

        self.context.setdefault("provenance", {})
        self.context["provenance"].update(
            {
                "input_sha256": sha,
                "ts_utc": datetime.datetime.utcnow().isoformat() + "Z",
                "job_id": self.context.get("job_id"),
                "tenant_id": self.context.get("tenant_id"),
            }
        )
        return dataset
