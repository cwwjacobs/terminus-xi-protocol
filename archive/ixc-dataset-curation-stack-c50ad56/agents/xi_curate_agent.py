from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from agents.base_agent import BaseAgent


def _is_jsonable(x: Any) -> bool:
    try:
        json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)
        return True
    except Exception:
        return False


def _canonical_record(rec: Any) -> str:
    # Stable canonicalization for dedup keys. `default=str` keeps this deterministic-ish for unknown types.
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _schema_keys_for_rows(rows: List[Dict[str, Any]]) -> List[str]:
    keys = set()
    for r in rows:
        keys.update(r.keys())
    return sorted(keys)


def _coerce_rows(dataset: Any) -> Tuple[List[Dict[str, Any]] | None, str]:
    if isinstance(dataset, list) and all(isinstance(x, dict) for x in dataset):
        return dataset, "rows"
    return None, "non_rows"


class xiCurateAgent(BaseAgent):
    """
    Deterministic curation (v1):
    - Validates JSON-serializability
    - If dataset is a list[dict], performs stable dedup and schema normalization
    - Always enriches output with `_xi_meta` describing the transform

    NOTE: This agent intentionally does NOT invoke any external LLM API.
    It may invoke deterministic built-in tools via ToolRouter when available.
    """

    def run(self, dataset: Any) -> Any:
        started = time.time()
        self.context.setdefault("curation", {})

        if not _is_jsonable(dataset):
            self.context["curation"].update(
                {
                    "status": "failed",
                    "reason": "dataset_not_json_serializable",
                }
            )
            raise ValueError("xiCurateAgent: dataset is not JSON-serializable (required for v1 dataset store)")

        rows, kind = _coerce_rows(dataset)

        if kind == "rows" and rows is not None:
            before = len(rows)
            seen = set()
            deduped: List[Dict[str, Any]] = []
            for r in rows:
                key = _canonical_record(r)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(r)

            schema_keys = _schema_keys_for_rows(deduped)
            normalized: List[Dict[str, Any]] = []
            for r in deduped:
                # Normalize: ensure all keys exist (missing -> None) so downstream is stable.
                nr = {k: r.get(k, None) for k in schema_keys}
                normalized.append(nr)

            out = normalized
            after = len(out)
            self.context["curation"].update(
                {
                    "status": "ok",
                    "mode": "dedup+schema_normalize",
                    "records_before": before,
                    "records_after": after,
                    "deduped": before - after,
                    "schema_keys": schema_keys,
                }
            )
        else:
            # For dict/primitive datasets, we do metadata enrichment only.
            out = dataset
            self.context["curation"].update(
                {
                    "status": "ok",
                    "mode": "metadata_only",
                }
            )

        meta = {
            "curated_at_unix": int(time.time()),
            "agent": "xiCurateAgent",
            "duration_ms": int((time.time() - started) * 1000),
        }

        # If ToolRouter is available, compute a deterministic fingerprint for auditing.
        if getattr(self, "tool_router", None) is not None:
            try:
                fp = self.tool_router.invoke_tool(tool_name="hash_sha256", payload={"dataset": out})
                if isinstance(fp, dict) and fp.get("sha256"):
                    self.context["curation"]["fingerprint_sha256"] = fp.get("sha256")
            except Exception:
                # Fingerprint is best-effort; do not fail curation if fingerprinting fails.
                self.context["curation"]["fingerprint_sha256"] = None

        # Attach metadata in a non-invasive way.
        if isinstance(out, dict):
            out = dict(out)  # shallow copy
            out.setdefault("_xi_meta", {})
            if isinstance(out["_xi_meta"], dict):
                out["_xi_meta"].update(meta)
            else:
                out["_xi_meta"] = meta
        elif isinstance(out, list):
            # Attach meta at list-level via context (preferred) and also via wrapper.
            # Keep backward compat: return list, but record meta in context.
            self.context["curation"].setdefault("meta", {}).update(meta)
        else:
            self.context["curation"].setdefault("meta", {}).update(meta)

        return out
