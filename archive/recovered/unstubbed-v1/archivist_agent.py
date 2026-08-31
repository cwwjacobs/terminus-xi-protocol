from __future__ import annotations

import datetime as _dt
import json
import re
import uuid
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Iterable, List, Optional


def _utc_now() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _keywords(text: str) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9_]{4,}", text.lower())
    seen = set()
    out = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


@dataclass
class LogEntry:
    event_id: str
    ts_utc: str
    role: str
    content: str
    event_type: str = "message"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftFinding:
    finding_id: str
    ts_utc: str
    code: str
    severity: str
    message: str
    event_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class Archivist:
    """
    Process-memory / project-journaling utility.
    """

    def __init__(self, goal: Optional[str] = None, scope: Optional[str] = None) -> None:
        self.goal = goal
        self.scope_history: List[Dict[str, Any]] = []
        if scope:
            self.set_scope(scope, reason="initial_scope")
        self.logbook: List[LogEntry] = []
        self.findings: List[DriftFinding] = []

    def set_goal(self, goal: str) -> None:
        if self.goal and self.goal != goal:
            raise ValueError("Archivist goal is immutable once set.")
        self.goal = goal

    def set_scope(self, scope: str, *, reason: str = "scope_update") -> None:
        self.scope_history.append(
            {
                "scope_id": f"scp_{uuid.uuid4().hex[:10]}",
                "ts_utc": _utc_now(),
                "scope": scope,
                "reason": reason,
            }
        )

    def record(
        self,
        role: str,
        content: str,
        *,
        event_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        entry = LogEntry(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            ts_utc=_utc_now(),
            role=role,
            content=content,
            event_type=event_type,
            metadata=metadata or {},
        )
        self.logbook.append(entry)
        return entry.event_id

    log = record

    def ingest_transcript(self, items: Iterable[Dict[str, Any]]) -> None:
        for item in items:
            self.record(
                role=str(item.get("role", "unknown")),
                content=str(item.get("content", "")),
                event_type=str(item.get("event_type", "message")),
                metadata=dict(item.get("metadata") or {}),
            )

    def detect_friction(self) -> List[DriftFinding]:
        self.findings = []
        goal_terms = set(_keywords(self.goal or ""))
        latest_scope = self.scope_history[-1]["scope"] if self.scope_history else ""
        scope_terms = set(_keywords(latest_scope))

        for idx, entry in enumerate(self.logbook):
            text = entry.content.lower()
            combined_terms = set(_keywords(text))

            if any(k in text for k in ("error", "failed", "blocked", "friction", "exception")):
                self.findings.append(
                    DriftFinding(
                        finding_id=f"fdg_{uuid.uuid4().hex[:12]}",
                        ts_utc=_utc_now(),
                        code="FRICTION_KEYWORD",
                        severity="warning",
                        message="Possible friction keyword detected.",
                        event_id=entry.event_id,
                        details={"matched_text": entry.content[:180]},
                    )
                )

            if goal_terms and combined_terms and goal_terms.isdisjoint(combined_terms) and idx >= 2:
                self.findings.append(
                    DriftFinding(
                        finding_id=f"fdg_{uuid.uuid4().hex[:12]}",
                        ts_utc=_utc_now(),
                        code="GOAL_DISTANCE",
                        severity="info",
                        message="Event appears weakly aligned to the stated goal.",
                        event_id=entry.event_id,
                        details={"goal_terms": sorted(goal_terms)[:12]},
                    )
                )

            if scope_terms and combined_terms and scope_terms.isdisjoint(combined_terms) and entry.event_type == "decision":
                self.findings.append(
                    DriftFinding(
                        finding_id=f"fdg_{uuid.uuid4().hex[:12]}",
                        ts_utc=_utc_now(),
                        code="SCOPE_MISMATCH",
                        severity="warning",
                        message="Decision event appears weakly aligned to the current scope.",
                        event_id=entry.event_id,
                        details={"scope_terms": sorted(scope_terms)[:12]},
                    )
                )

        return list(self.findings)

    def suggest_minimal_fix(self) -> Dict[str, Any]:
        if not self.findings:
            self.detect_friction()

        top = sorted(self.findings, key=lambda f: {"error": 0, "warning": 1, "info": 2}.get(f.severity, 3))
        strongest = top[:3]
        actions = []
        if strongest:
            actions.append("Re-state the immutable goal in one sentence.")
            actions.append("Compare the latest decision or failed step against the current scope.")
            actions.append("Resume from the last known-good step instead of extending the current drift path.")
        else:
            actions.append("No strong friction detected; continue with current scope.")
        return {
            "goal": self.goal,
            "latest_scope": self.scope_history[-1]["scope"] if self.scope_history else None,
            "strongest_findings": [asdict(f) for f in strongest],
            "minimal_actions": actions,
        }

    def generate_report(self) -> Dict[str, Any]:
        findings = self.detect_friction()
        return {
            "goal": self.goal,
            "scope_history": list(self.scope_history),
            "log_count": len(self.logbook),
            "findings": [asdict(f) for f in findings],
            "minimal_fix": self.suggest_minimal_fix(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "scope_history": self.scope_history,
            "logbook": [asdict(e) for e in self.logbook],
            "findings": [asdict(f) for f in self.findings],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Archivist":
        obj = cls(goal=payload.get("goal"))
        obj.scope_history = list(payload.get("scope_history") or [])
        obj.logbook = [LogEntry(**e) for e in payload.get("logbook") or []]
        obj.findings = [DriftFinding(**f) for f in payload.get("findings") or []]
        return obj

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load_json(cls, path: str) -> "Archivist":
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls.from_dict(payload)
