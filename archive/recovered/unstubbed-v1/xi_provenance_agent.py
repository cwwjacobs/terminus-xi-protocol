from __future__ import annotations

import datetime as _dt
import hashlib
import json
import uuid
from typing import Any


from agents.base_agent import BaseAgent


def _utc_now() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_json_dumps(x: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":"), default=str)


def _to_bytes(x: Any) -> bytes:
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    if isinstance(x, str):
        return x.encode("utf-8")
    return _safe_json_dumps(x, sort_keys=False).encode("utf-8")


def _canonical_bytes(x: Any) -> bytes:
    return _safe_json_dumps(x, sort_keys=True).encode("utf-8")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _dataset_kind(x: Any) -> str:
    if isinstance(x, list):
        if all(isinstance(i, dict) for i in x):
            return "rows"
        return "list"
    if isinstance(x, dict):
        return "dict"
    if isinstance(x, (bytes, bytearray)):
        return "bytes"
    if x is None:
        return "null"
    return type(x).__name__


class xiProvenanceAgent(BaseAgent):
    """
    Records deterministic provenance for the incoming payload and appends an event
    to `context["provenance"]["events"]`. The dataset is never mutated.

    Stored signals:
    - raw SHA-256
    - canonical SHA-256
    - dataset kind
    - record count (when obvious)
    - run / job / tenant refs when present in context
    """

    def run(self, dataset: Any) -> Any:
        raw_sha = None
        canonical_sha = None

        try:
            raw_sha = _sha256_bytes(_to_bytes(dataset))
        except Exception:
            raw_sha = None

        try:
            canonical_sha = _sha256_bytes(_canonical_bytes(dataset))
        except Exception:
            canonical_sha = None

        kind = _dataset_kind(dataset)
        record_count = len(dataset) if isinstance(dataset, (list, dict)) else None

        event = {
            "event_id": f"prov_{uuid.uuid4().hex[:12]}",
            "ts_utc": _utc_now(),
            "agent": "xiProvenanceAgent",
            "dataset_kind": kind,
            "record_count": record_count,
            "input_sha256_raw": raw_sha,
            "input_sha256_canonical": canonical_sha,
            "job_id": self.context.get("job_id"),
            "tenant_id": self.context.get("tenant_id"),
            "run_id": self.context.get("run_id"),
            "source_label": self.context.get("source_label"),
            "notes": [],
        }

        prov = self.context.setdefault("provenance", {})
        prov.setdefault("events", []).append(event)
        prov["last_event"] = event
        prov["latest_input_sha256_raw"] = raw_sha
        prov["latest_input_sha256_canonical"] = canonical_sha
        prov["latest_dataset_kind"] = kind

        return dataset
