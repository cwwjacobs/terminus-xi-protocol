from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Dict, List


from agents.base_agent import BaseAgent


def _safe_json(x: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":"), default=str)


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _simhash64(text: str) -> str:
    tokens = _tokenize(text)
    if not tokens:
        return "0" * 16
    weights = [0] * 64
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        for i in range(64):
            weights[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, w in enumerate(weights):
        if w >= 0:
            out |= (1 << i)
    return f"{out:016x}"


def _field_presence_signature(x: Any) -> List[str]:
    if isinstance(x, dict):
        return sorted(list(x.keys()))
    return []


def _schema_name_guess(x: Any) -> str | None:
    if isinstance(x, dict) and isinstance(x.get("schema_name"), str):
        return x["schema_name"]
    return None


def _voxel_signature(x: Any) -> Dict[str, Any]:
    text = _safe_json(x, sort_keys=True)
    token_count = len(_tokenize(text))
    length_bucket = (
        "xs" if token_count < 20 else
        "sm" if token_count < 80 else
        "md" if token_count < 200 else
        "lg"
    )
    return {
        "schema_name": _schema_name_guess(x),
        "field_presence": _field_presence_signature(x),
        "token_count": token_count,
        "length_bucket": length_bucket,
        "simhash64": _simhash64(text),
    }


class ArtifactorAgent(BaseAgent):
    """
    Lightweight artifact fingerprint sidecar.
    """

    def run(self, dataset: Any) -> Any:
        raw_text = _safe_json(dataset, sort_keys=False)
        canonical_text = _safe_json(dataset, sort_keys=True)

        record = {
            "artifact_ref_id": f"art_{uuid.uuid4().hex[:12]}",
            "raw_sha256": _sha256_text(raw_text),
            "canonical_sha256": _sha256_text(canonical_text),
            "voxel_signature": _voxel_signature(dataset),
        }

        art = self.context.setdefault("artifactor", {})
        art.setdefault("records", []).append(record)
        art["last_record"] = record
        return dataset
