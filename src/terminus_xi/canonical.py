"""Canonical serialization, identity, and JSON Pointer resolution.

Canonical form is the single identity rule for XI v1:

* JSON-typed values are identified by ``sha256`` over ``canonical_bytes``
  (sorted keys, compact separators, UTF-8, ``NaN``/``Infinity`` rejected).
* Byte-typed values (files, media) are identified by ``sha256`` over raw bytes.

Historical XI code recorded both a "raw" and a "canonical" digest for the same
JSON payload, where the raw digest depended on incidental key order. XI v1
resolves that: JSON identity is canonical identity. See
``docs/XI_V1_FREEZE.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "PointerError",
    "canonical_bytes",
    "canonical_json",
    "json_write_bytes",
    "pointer_exists",
    "read_json",
    "resolve_pointer",
    "sha256_bytes",
    "sha256_canonical",
    "sha256_file",
    "sha256_text",
    "utc_now",
    "write_json",
    "write_text",
]


class PointerError(LookupError):
    """A JSON Pointer did not resolve inside the supplied document."""


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text for ``value``."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_canonical(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_write_bytes(value: Any) -> bytes:
    """Deterministic on-disk JSON encoding (readable, sorted, newline ended)."""
    text = json.dumps(
        value,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def write_json(path: str | os.PathLike[str], value: Any) -> bytes:
    data = json_write_bytes(value)
    Path(path).write_bytes(data)
    return data


def write_text(path: str | os.PathLike[str], text: str) -> bytes:
    data = text.encode("utf-8")
    Path(path).write_bytes(data)
    return data


def read_json(path: str | os.PathLike[str]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer. ``""`` is the whole document."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise PointerError(f"pointer must start with '/': {pointer!r}")
    current = document
    for raw in pointer.split("/")[1:]:
        token = _unescape(raw)
        if isinstance(current, dict):
            if token not in current:
                raise PointerError(f"pointer {pointer!r} missing key {token!r}")
            current = current[token]
        elif isinstance(current, list):
            if not token.lstrip("-").isdigit():
                raise PointerError(f"pointer {pointer!r} bad array index {token!r}")
            index = int(token)
            if index < 0 or index >= len(current):
                raise PointerError(f"pointer {pointer!r} index out of range")
            current = current[index]
        else:
            raise PointerError(f"pointer {pointer!r} descends into a scalar")
    return current


def pointer_exists(document: Any, pointer: str) -> bool:
    try:
        resolve_pointer(document, pointer)
    except PointerError:
        return False
    return True


def utc_now() -> str:
    """Current UTC timestamp, second precision.

    ``TERMINUS_XI_NOW`` overrides the clock so build outputs can be made
    byte-reproducible in tests. The override is a build convenience only; it
    carries no authority and receipts are not authenticated documents.
    """
    override = os.environ.get("TERMINUS_XI_NOW")
    if override:
        return override
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
