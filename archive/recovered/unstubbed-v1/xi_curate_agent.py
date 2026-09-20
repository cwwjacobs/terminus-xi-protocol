from __future__ import annotations

import json
import time
import uuid
import hashlib
from typing import Any, Dict, List, Tuple

from agents.base_agent import BaseAgent


def _is_jsonable(x: Any) -> bool:
    try:
        json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)
        return True
    except Exception:
        return False


def _canonical_record(rec: Any) -> str:
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


def _sha256_obj(x: Any) -> str | None:
    try:
        b = json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(b).hexdigest()
    except Exception:
        return None


class xiCurateAgent(BaseAgent):
    """
    Deterministic curation for dataset-shaped artifacts.
    """

    def run(self, dataset: Any) -> Any:
        started = time.time()
        self.context.setdefault("curation", {})
        options = self.context.get("curation_options") or {}
        required_fields = list(options.get("required_fields") or [])
        return_wrapper = bool(options.get("return_wrapper", False))

        if not _is_jsonable(dataset):
            self.context["curation"].update(
                {
                    "status": "failed",
                    "reason": "dataset_not_json_serializable",
                }
            )
            raise ValueError("xiCurateAgent: dataset is not JSON-serializable")

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
            for field in required_fields:
                if field not in schema_keys:
                    schema_keys.append(field)
            schema_keys = sorted(set(schema_keys))

            normalized: List[Dict[str, Any]] = []
            dropped_for_missing_required = 0
            for r in deduped:
                nr = {k: r.get(k, None) for k in schema_keys}
                if required_fields and any(nr.get(f) is None for f in required_fields):
                    dropped_for_missing_required += 1
                    continue
                normalized.append(nr)

            out: Any = normalized
            after = len(out)
            self.context["curation"].update(
                {
                    "status": "ok",
                    "mode": "dedup+schema_normalize",
                    "records_before": before,
                    "records_after": after,
                    "deduped": before - len(deduped),
                    "dropped_for_missing_required": dropped_for_missing_required,
                    "schema_keys": schema_keys,
                    "required_fields": required_fields,
                }
            )
        else:
            out = dataset
            self.context["curation"].update(
                {
                    "status": "ok",
                    "mode": "metadata_only",
                    "required_fields": required_fields,
                }
            )

        meta = {
            "artifact_ref_id": f"art_{uuid.uuid4().hex[:12]}",
            "curated_at_unix": int(time.time()),
            "agent": "xiCurateAgent",
            "duration_ms": int((time.time() - started) * 1000),
            "canonical_sha256": _sha256_obj(out),
        }
        self.context["curation"].setdefault("meta", {}).update(meta)
        self.context["curation"]["last_artifact_ref_id"] = meta["artifact_ref_id"]

        if return_wrapper:
            return {
                "dataset": out,
                "xi_envelope": {
                    "curation": dict(self.context["curation"]),
                },
            }

        if isinstance(out, dict):
            out = dict(out)
            existing = out.get("_xi_meta")
            if not isinstance(existing, dict):
                existing = {}
            existing.update(meta)
            out["_xi_meta"] = existing

        return out
