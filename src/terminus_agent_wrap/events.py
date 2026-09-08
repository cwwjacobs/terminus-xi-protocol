"""Tool Trace observation: digest-only JSONL event lines.

Event timestamps are supplied by the caller. The spike demo uses fixture-fixed
timestamps so ``events_sha256`` does not depend on a wall clock. This module
does not read ``utc_now`` or ``TERMINUS_XI_NOW``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from terminus_xi.canonical import canonical_json, sha256_bytes, sha256_canonical

__all__ = [
    "ALLOWED_KINDS",
    "EVENT_FIELDS",
    "PAYLOAD_KEYS",
    "events_sha256",
    "make_event",
    "normalize_event",
    "normalize_events",
    "write_events_jsonl",
]

ALLOWED_KINDS = frozenset(
    {"run_start", "tool_call", "tool_result", "decision", "run_end", "error"}
)
EVENT_FIELDS = (
    "seq",
    "ts_utc",
    "kind",
    "name",
    "args_sha256",
    "result_sha256",
    "status",
    "codes",
)
PAYLOAD_KEYS = frozenset({"args", "result", "payload", "content", "raw"})
_SHA256_HEX = 64


def _sha256_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != _SHA256_HEX or any(
        char not in "0123456789abcdef" for char in value
    ):
        # Preserve the supplied value so XI's digest check can fail closed.
        return value if isinstance(value, str) else str(value)
    return value


def payload_digest(value: Any | None) -> str | None:
    """Canonical digest of a payload, or ``None`` when no payload was supplied."""
    if value is None:
        return None
    return sha256_canonical(value)


def make_event(
    *,
    seq: int,
    ts_utc: str,
    kind: str,
    name: str,
    status: str,
    codes: Sequence[str] = (),
    args: Any | None = None,
    result: Any | None = None,
    args_sha256: str | None = None,
    result_sha256: str | None = None,
) -> dict[str, Any]:
    """Build one digest-only event line. Raw payloads are hashed, never stored."""
    if args is not None and args_sha256 is not None:
        raise ValueError("pass args or args_sha256, not both")
    if result is not None and result_sha256 is not None:
        raise ValueError("pass result or result_sha256, not both")
    return normalize_event(
        {
            "seq": seq,
            "ts_utc": ts_utc,
            "kind": kind,
            "name": name,
            "status": status,
            "codes": list(codes),
            "args_sha256": payload_digest(args) if args is not None else args_sha256,
            "result_sha256": payload_digest(result) if result is not None else result_sha256,
        }
    )


def normalize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return the required event fields. Payload keys are dropped, not serialized."""
    if not isinstance(event, Mapping):
        raise TypeError("event must be a JSON object")
    raw = {key: value for key, value in event.items() if key not in PAYLOAD_KEYS}
    missing = [field for field in EVENT_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"event is missing required fields: {missing}")
    kind = raw["kind"]
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unsupported event kind: {kind!r}")
    seq = raw["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise ValueError(f"event seq must be a positive integer, not {seq!r}")
    codes = raw["codes"]
    if not isinstance(codes, list) or any(not isinstance(item, str) for item in codes):
        raise ValueError("event codes must be an array of strings")
    for field in ("ts_utc", "kind", "name", "status"):
        if not isinstance(raw[field], str) or not raw[field]:
            raise ValueError(f"event {field} must be a non-empty string")
    return {
        "seq": seq,
        "ts_utc": raw["ts_utc"],
        "kind": kind,
        "name": raw["name"],
        "args_sha256": _sha256_or_none(raw["args_sha256"]),
        "result_sha256": _sha256_or_none(raw["result_sha256"]),
        "status": raw["status"],
        "codes": list(codes),
    }


def normalize_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_event(event) for event in events]
    seqs = [event["seq"] for event in normalized]
    if len(seqs) != len(set(seqs)):
        raise ValueError("event seq values must be unique")
    return normalized


def events_sha256(events: Sequence[Mapping[str, Any]]) -> str:
    """Canonical identity of the event list (not the JSONL file bytes)."""
    return sha256_canonical(list(events))


def write_events_jsonl(path: str | Path, events: Sequence[Mapping[str, Any]]) -> str:
    """Write one canonical JSON object per line. Returns the file sha256."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(canonical_json(event) + "\n" for event in events)
    data = text.encode("utf-8")
    destination.write_bytes(data)
    return sha256_bytes(data)
