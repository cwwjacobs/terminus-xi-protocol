from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List


from agents.base_agent import BaseAgent


def _safe_json(x: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":"), default=str)


def _payload_bytes(x: Any) -> int | None:
    try:
        if isinstance(x, (bytes, bytearray)):
            return len(x)
        return len(_safe_json(x).encode("utf-8"))
    except Exception:
        return None


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


def _exact_duplicate_count(rows: List[Dict[str, Any]]) -> int:
    seen = set()
    dup = 0
    for row in rows:
        key = _safe_json(row, sort_keys=True)
        if key in seen:
            dup += 1
        else:
            seen.add(key)
    return dup


def _field_coverage(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    keys = sorted({k for row in rows for k in row.keys()})
    out: Dict[str, float] = {}
    if not rows:
        return out
    total = len(rows)
    for k in keys:
        present = sum(1 for row in rows if row.get(k) is not None)
        out[k] = round(present / total, 4)
    return out


def _finding(code: str, severity: str, message: str, **details: Any) -> Dict[str, Any]:
    return {
        "finding_id": f"fdg_{uuid.uuid4().hex[:12]}",
        "code": code,
        "severity": severity,
        "message": message,
        "details": details,
    }


class xiAuditAgent(BaseAgent):
    """
    Deterministic audit layer for pre-corpus inspection.
    """

    def run(self, dataset: Any) -> Any:
        findings: List[Dict[str, Any]] = []
        summary: Dict[str, Any] = {}

        kind = _dataset_kind(dataset)
        size = _payload_bytes(dataset)
        summary["dataset_kind"] = kind
        summary["payload_bytes"] = size

        if size is None:
            findings.append(_finding("PAYLOAD_SIZE_UNKNOWN", "warning", "Unable to measure payload size."))
        else:
            findings.append(_finding("PAYLOAD_BYTES", "info", "Measured payload size.", value=size))
            if size > 10_000_000:
                findings.append(_finding("PAYLOAD_LARGE", "warning", "Dataset payload exceeds 10MB; consider chunking.", value=size))
                try:
                    self.warn("Dataset payload exceeds 10MB; consider chunking or compression.")
                except Exception:
                    pass

        if isinstance(dataset, list) and all(isinstance(x, dict) for x in dataset):
            rows: List[Dict[str, Any]] = dataset
            summary["row_count"] = len(rows)
            dup_count = _exact_duplicate_count(rows)
            summary["exact_duplicate_count"] = dup_count
            findings.append(_finding("ROW_COUNT", "info", "Detected row dataset.", value=len(rows)))
            if dup_count:
                findings.append(_finding("EXACT_DUPLICATES_PRESENT", "warning", "Exact duplicate rows detected.", value=dup_count))

            coverage = _field_coverage(rows)
            summary["field_coverage"] = coverage
            sparse_fields = [k for k, v in coverage.items() if v < 0.25]
            if sparse_fields:
                findings.append(_finding("SPARSE_FIELDS", "info", "Some fields are present in less than 25% of rows.", fields=sparse_fields))

            allowed_actions = ((self.context.get("contracts") or {}).get("allowed_actions") or
                               (self.context.get("allowed_actions")))
            if allowed_actions:
                invalid = []
                for i, row in enumerate(rows):
                    action = row.get("action")
                    if action is not None and action not in allowed_actions:
                        invalid.append({"row_index": i, "action": action})
                if invalid:
                    findings.append(_finding("INVALID_ACTIONS", "error", "Rows contain actions outside the allowed vocabulary.", invalid=invalid[:25], total=len(invalid)))
                else:
                    findings.append(_finding("ACTION_VOCAB_OK", "info", "All observed actions are inside the allowed vocabulary.", count=len(rows)))

        audit = self.context.setdefault("audit", {})
        audit_event = {
            "event_id": f"aud_{uuid.uuid4().hex[:12]}",
            "agent": "xiAuditAgent",
            "findings": findings,
            "summary": summary,
        }
        audit.setdefault("events", []).append(audit_event)
        audit["last_event"] = audit_event
        audit["findings"] = findings
        audit["summary"] = summary

        summary_text = ((self.context.get("input") or {}).get("summary"))
        if isinstance(summary_text, str) and summary_text.strip() and getattr(self, "tool_router", None) is not None:
            try:
                res = self.tool_router.invoke_model(
                    model_class="cheap",
                    payload={"task": "audit_notes", "text": summary_text},
                )
                audit["notes"] = res.output
                audit["notes_meta"] = {
                    "model_id": res.model_id,
                    "model_class": res.model_class,
                    "duration_ms": res.duration_ms,
                }
            except Exception as e:
                findings.append(_finding("AUDIT_NOTES_FAILED", "warning", "Optional audit note generation failed.", error=str(e)))

        return dataset
