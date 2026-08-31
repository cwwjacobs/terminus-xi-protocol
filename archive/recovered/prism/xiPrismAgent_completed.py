"""
xiPrismAgent
=============

Spatial / angle-based refraction agent for layout-aware retrieval.

Design goals
------------
- Keep the runtime contract structured and auditable
- Refract one spatial node through an explicit angle/lens
- Preserve provenance (document, page, bounding box, nearby visuals)
- Stay lightweight: no heavy vision stack required for v1
- Make it easy for the Operator to invoke Prism as a specialized tool actor

This implementation is intentionally deterministic-first.
It can be upgraded later to call OCR / vision / multimodal models,
but the v1 contract stays stable.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def overlap_score(query: str, text: str) -> float:
    q = set(tokenize(query))
    t = set(tokenize(text))
    if not q:
        return 0.0
    return round(len(q & t) / max(1, len(q)), 4)


def bbox_area(bbox: Optional[List[int]]) -> Optional[int]:
    if not bbox or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def sha256_json(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AngleProfile:
    canonical_name: str
    visual_alert_rules: Dict[str, str] = field(default_factory=dict)
    preferred_keywords: List[str] = field(default_factory=list)
    caution_keywords: List[str] = field(default_factory=list)


class PrismAgent:
    """
    Angle-aware spatial retrieval/refraction tool actor.

    Expected spatial_manifest shape:
    {
        "node_id": {
            "doc_id": "string",
            "page": 42,
            "text_content": "string",
            "bbox": [x1, y1, x2, y2],
            "nearby_visuals": ["icon_a", "symbol_b"],
            "metadata": {... optional ...}
        }
    }
    """

    SCHEMA_NAME = "prism_action"
    SCHEMA_VERSION = "gts.v1"

    def __init__(
        self,
        model_version: str = "prism-vision-1.0",
        default_window_px: int = 50,
        angle_aliases: Optional[Dict[str, str]] = None,
    ) -> None:
        self.model_version = model_version
        self.default_window_px = default_window_px
        self.angle_aliases = {
            "safety": "Safety Engineer",
            "safety engineer": "Safety Engineer",
            "compliance": "Compliance Auditor",
            "compliance auditor": "Compliance Auditor",
            "research": "Research Analyst",
            "research analyst": "Research Analyst",
            "maintenance": "Maintenance Technician",
            "maintenance technician": "Maintenance Technician",
            "legal": "Legal Analyst",
            "legal analyst": "Legal Analyst",
        }
        if angle_aliases:
            self.angle_aliases.update({k.lower(): v for k, v in angle_aliases.items()})

        self.angle_profiles: Dict[str, AngleProfile] = {
            "Safety Engineer": AngleProfile(
                canonical_name="Safety Engineer",
                visual_alert_rules={
                    "high_voltage_symbol": "CRITICAL: High Voltage Warning detected near target.",
                    "flammable_symbol": "CRITICAL: Flammable Hazard detected near target.",
                    "laser_warning": "WARNING: Laser hazard marker detected near target.",
                    "do_not_overtighten_icon": "CAUTION: Do-not-overtighten marker detected near target.",
                },
                preferred_keywords=["warning", "hazard", "torque", "voltage", "caution", "safety"],
                caution_keywords=["ignore", "override"],
            ),
            "Compliance Auditor": AngleProfile(
                canonical_name="Compliance Auditor",
                visual_alert_rules={
                    "approval_stamp": "NOTICE: Approval stamp present near target.",
                    "revision_triangle": "NOTICE: Revision marker present near target.",
                },
                preferred_keywords=["policy", "shall", "must", "requirement", "revision", "approval"],
                caution_keywords=["draft", "unapproved"],
            ),
            "Research Analyst": AngleProfile(
                canonical_name="Research Analyst",
                visual_alert_rules={},
                preferred_keywords=["method", "result", "specification", "finding", "evidence"],
                caution_keywords=[],
            ),
            "Maintenance Technician": AngleProfile(
                canonical_name="Maintenance Technician",
                visual_alert_rules={
                    "wrench_icon": "NOTICE: Tooling indicator present near target.",
                    "do_not_overtighten_icon": "CAUTION: Torque handling marker present near target.",
                },
                preferred_keywords=["torque", "replace", "service", "interval", "maintenance"],
                caution_keywords=["obsolete", "deprecated"],
            ),
            "Legal Analyst": AngleProfile(
                canonical_name="Legal Analyst",
                visual_alert_rules={
                    "signature_block": "NOTICE: Signature or execution block is near target.",
                },
                preferred_keywords=["shall", "terminate", "notice", "clause", "obligation"],
                caution_keywords=["sample", "draft"],
            ),
        }

    # -----------------------------
    # Public API
    # -----------------------------
    def validate_spatial_manifest(self, spatial_manifest: Dict[str, Any]) -> Dict[str, Any]:
        """Validate manifest shape and return a structured report."""
        required = {"doc_id", "page", "text_content", "bbox"}
        findings: List[Dict[str, Any]] = []
        valid_count = 0

        for node_id, node in spatial_manifest.items():
            missing = sorted(list(required - set(node.keys())))
            if missing:
                findings.append(
                    {
                        "node_id": node_id,
                        "severity": "error",
                        "issue": "missing_required_fields",
                        "details": missing,
                    }
                )
                continue
            if not isinstance(node.get("bbox"), list) or len(node["bbox"]) != 4:
                findings.append(
                    {
                        "node_id": node_id,
                        "severity": "error",
                        "issue": "invalid_bbox",
                        "details": node.get("bbox"),
                    }
                )
                continue
            valid_count += 1

        return {
            "schema_name": "prism_manifest_validation",
            "schema_version": self.SCHEMA_VERSION,
            "validated_at_utc": utc_now_iso(),
            "total_nodes": len(spatial_manifest),
            "valid_nodes": valid_count,
            "findings": findings,
            "ok": valid_count == len(spatial_manifest),
        }

    def refract_node(
        self,
        node_id: str,
        query: str,
        spatial_manifest: Dict[str, Any],
        angle: str,
        context_window_px: Optional[int] = None,
        run_id: Optional[str] = None,
        actor_id: str = "prism",
    ) -> Dict[str, Any]:
        """
        Refract a specific node through an angle/lens and return a structured,
        schema-compliant tool action / observation object.
        """
        target_data = spatial_manifest.get(node_id)
        if not target_data:
            return self._generate_error_action(
                reason="Node not found in spatial manifest.",
                node_id=node_id,
                query=query,
                angle=angle,
                run_id=run_id,
                actor_id=actor_id,
            )

        canonical_angle = self._normalize_angle(angle)
        profile = self._get_angle_profile(canonical_angle)
        window_px = context_window_px or self.default_window_px

        text_content = normalize_text(target_data.get("text_content"))
        nearby_visuals = list(target_data.get("nearby_visuals", []))
        metadata = dict(target_data.get("metadata", {}))
        bbox = target_data.get("bbox")
        provenance = {
            "source_document": target_data.get("doc_id"),
            "page_number": target_data.get("page"),
            "bounding_box": bbox,
            "bounding_box_area": bbox_area(bbox),
            "context_window_px": window_px,
            "nearby_visuals": nearby_visuals,
        }

        visual_alerts = self._derive_visual_alerts(profile, nearby_visuals)
        angle_keywords = self._extract_angle_keyword_matches(profile, text_content)
        query_overlap = overlap_score(query, text_content)
        angle_overlap = overlap_score(" ".join(profile.preferred_keywords), text_content)

        observation = {
            "extracted_text": text_content,
            "refraction_summary": self._build_refraction_summary(
                canonical_angle=canonical_angle,
                query=query,
                query_overlap=query_overlap,
                angle_overlap=angle_overlap,
                visual_alerts=visual_alerts,
                angle_keywords=angle_keywords,
            ),
            "relevance_scores": {
                "query_overlap": query_overlap,
                "angle_overlap": angle_overlap,
                "visual_alert_count": len(visual_alerts),
            },
            "angle_keyword_hits": angle_keywords,
            "provenance": provenance,
            "visual_proximity_alerts": visual_alerts,
            "metadata": metadata,
        }

        tool_input = {
            "node_id": node_id,
            "query": query,
            "angle_requested": angle,
            "angle_applied": canonical_angle,
            "context_window_px": window_px,
        }

        action = {
            "schema_name": self.SCHEMA_NAME,
            "schema_version": self.SCHEMA_VERSION,
            "action_id": f"prm_{uuid.uuid4().hex}",
            "created_at_utc": utc_now_iso(),
            "run_id": run_id,
            "actor_id": actor_id,
            "tool_name": "refract_spatial_context",
            "tool_input": tool_input,
            "observation": observation,
            "status": "ok",
            "model_version": self.model_version,
        }
        action["fingerprint"] = self._fingerprint_action(action)
        return action

    def batch_refract(
        self,
        node_ids: List[str],
        query: str,
        spatial_manifest: Dict[str, Any],
        angle: str,
        context_window_px: Optional[int] = None,
        run_id: Optional[str] = None,
        actor_id: str = "prism",
    ) -> Dict[str, Any]:
        """
        Batch refract multiple nodes.
        Useful when the Operator wants to compare several spatial candidates.
        """
        outputs = [
            self.refract_node(
                node_id=node_id,
                query=query,
                spatial_manifest=spatial_manifest,
                angle=angle,
                context_window_px=context_window_px,
                run_id=run_id,
                actor_id=actor_id,
            )
            for node_id in node_ids
        ]

        return {
            "schema_name": "prism_batch_result",
            "schema_version": self.SCHEMA_VERSION,
            "batch_id": f"pb_{uuid.uuid4().hex}",
            "created_at_utc": utc_now_iso(),
            "run_id": run_id,
            "actor_id": actor_id,
            "angle_applied": self._normalize_angle(angle),
            "query": query,
            "node_count": len(node_ids),
            "results": outputs,
        }

    # -----------------------------
    # Internal helpers
    # -----------------------------
    def _normalize_angle(self, angle: str) -> str:
        angle_clean = normalize_text(angle)
        if not angle_clean:
            return "Research Analyst"
        return self.angle_aliases.get(angle_clean.lower(), angle_clean)

    def _get_angle_profile(self, canonical_angle: str) -> AngleProfile:
        return self.angle_profiles.get(
            canonical_angle,
            AngleProfile(canonical_name=canonical_angle),
        )

    def _derive_visual_alerts(self, profile: AngleProfile, nearby_visuals: List[str]) -> List[str]:
        alerts: List[str] = []
        for visual in nearby_visuals:
            if visual in profile.visual_alert_rules:
                alerts.append(profile.visual_alert_rules[visual])
        return alerts

    def _extract_angle_keyword_matches(self, profile: AngleProfile, text_content: str) -> List[str]:
        text_tokens = set(tokenize(text_content))
        hits = [kw for kw in profile.preferred_keywords if kw.lower() in text_tokens]
        return sorted(list(set(hits)))

    def _build_refraction_summary(
        self,
        canonical_angle: str,
        query: str,
        query_overlap: float,
        angle_overlap: float,
        visual_alerts: List[str],
        angle_keywords: List[str],
    ) -> str:
        parts = [
            f"Angle '{canonical_angle}' applied to query '{normalize_text(query)}'.",
            f"Query overlap={query_overlap:.2f}.",
            f"Angle overlap={angle_overlap:.2f}.",
        ]
        if angle_keywords:
            parts.append(f"Angle keyword hits: {', '.join(angle_keywords)}.")
        if visual_alerts:
            parts.append(f"Visual alerts: {len(visual_alerts)} detected.")
        else:
            parts.append("No angle-specific visual alerts detected.")
        return " ".join(parts)

    def _fingerprint_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        # raw hash includes everything
        raw_hash = sha256_json(action)

        # canonical hash strips volatile IDs/timestamps
        canonical = json.loads(json.dumps(action))
        canonical.pop("action_id", None)
        canonical.pop("created_at_utc", None)
        canonical_hash = sha256_json(canonical)

        structural_signature = {
            "schema_name": action.get("schema_name"),
            "tool_name": action.get("tool_name"),
            "angle_applied": action.get("tool_input", {}).get("angle_applied"),
            "has_visual_alerts": bool(action.get("observation", {}).get("visual_proximity_alerts")),
            "has_bbox": bool(action.get("observation", {}).get("provenance", {}).get("bounding_box")),
        }

        return {
            "raw_sha256": raw_hash,
            "canonical_sha256": canonical_hash,
            "structural_signature": structural_signature,
        }

    def _generate_error_action(
        self,
        reason: str,
        node_id: Optional[str],
        query: str,
        angle: str,
        run_id: Optional[str],
        actor_id: str,
    ) -> Dict[str, Any]:
        action = {
            "schema_name": self.SCHEMA_NAME,
            "schema_version": self.SCHEMA_VERSION,
            "action_id": f"prm_{uuid.uuid4().hex}",
            "created_at_utc": utc_now_iso(),
            "run_id": run_id,
            "actor_id": actor_id,
            "tool_name": "refract_spatial_context",
            "tool_input": {
                "node_id": node_id,
                "query": query,
                "angle_requested": angle,
                "angle_applied": self._normalize_angle(angle),
                "context_window_px": self.default_window_px,
            },
            "observation": None,
            "status": "error",
            "error_flag": True,
            "error_details": {
                "reason": reason,
                "error_code": "PRISM_NODE_NOT_FOUND" if "not found" in reason.lower() else "PRISM_ERROR",
            },
            "model_version": self.model_version,
        }
        action["fingerprint"] = self._fingerprint_action(action)
        return action


if __name__ == "__main__":
    mock_spatial_manifest = {
        "doc123_table4": {
            "doc_id": "engine_schematic_v2",
            "page": 42,
            "text_content": "Torque specifications for main thruster: 450 Nm. Warning: isolate circuit before service.",
            "bbox": [150, 300, 600, 450],
            "nearby_visuals": ["high_voltage_symbol", "do_not_overtighten_icon"],
            "metadata": {"section": "thruster_maintenance"},
        },
        "doc123_clause8": {
            "doc_id": "contract_alpha",
            "page": 7,
            "text_content": "Either party may terminate with 30 days written notice.",
            "bbox": [90, 210, 650, 310],
            "nearby_visuals": ["signature_block"],
            "metadata": {"section": "termination"},
        },
    }

    prism = PrismAgent()
    print("== Validation ==")
    print(json.dumps(prism.validate_spatial_manifest(mock_spatial_manifest), indent=2))

    print("\n== Safety refraction ==")
    safety_action = prism.refract_node(
        "doc123_table4",
        "What is the torque and are there any nearby safety warnings?",
        mock_spatial_manifest,
        "Safety Engineer",
        run_id="run_demo_001",
    )
    print(json.dumps(safety_action, indent=2))

    print("\n== Legal refraction ==")
    legal_action = prism.refract_node(
        "doc123_clause8",
        "What is the termination notice requirement?",
        mock_spatial_manifest,
        "Legal Analyst",
        run_id="run_demo_001",
    )
    print(json.dumps(legal_action, indent=2))
