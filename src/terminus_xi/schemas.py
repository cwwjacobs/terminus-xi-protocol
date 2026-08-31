"""Locate and apply the frozen schemas under ``spec/``."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .jsonschema_lite import SchemaError, load_schema, validate

__all__ = [
    "SCHEMA_FILES",
    "SchemaError",
    "XI_SCHEMA_FILES",
    "get_schema",
    "register_schema",
    "schema_path",
    "spec_dir",
    "validate_against",
]

# Schemas owned by XI v1. This mapping is part of the frozen surface: the
# freeze receipt binds exactly these files. Consumers add their own ids with
# register_schema; XI does not know what they are.
XI_SCHEMA_FILES: Mapping[str, str] = {
    "terminus-xi.check-contract.v1": "check-contract.schema.json",
    "terminus-xi.check-contract.v2": "check-contract.v2.schema.json",
    "terminus-xi.check-contract-set.v1": "check-contract-set.schema.json",
    "terminus-xi.watchdog-result.v1": "watchdog-result.schema.json",
    "terminus-xi.receipt.v1": "receipt.schema.json",
    "terminus-xi.receipt.v2": "receipt.v2.schema.json",
    "terminus-xi.admission-policy.v1": "admission-policy.schema.json",
    "terminus-xi.provenance.v1": "provenance.schema.json",
    "terminus-xi.freeze-receipt.v1": "freeze-receipt.schema.json",
}

#: The live registry: XI's own schemas plus whatever consumers have registered.
SCHEMA_FILES: dict[str, str] = dict(XI_SCHEMA_FILES)


def register_schema(schema_id: str, filename: str) -> None:
    """Register a consumer-owned schema under ``spec/``.

    Re-registering the same file is a no-op so that importing a consumer twice
    is harmless. Rebinding an id to a different file is refused: a schema id is
    an identity, and silently repointing one would change what a check validates
    against without changing the check.
    """
    existing = SCHEMA_FILES.get(schema_id)
    if existing is not None and existing != filename:
        raise ValueError(
            f"schema id {schema_id!r} is already bound to {existing!r}; "
            f"refusing to rebind it to {filename!r}"
        )
    SCHEMA_FILES[schema_id] = filename
    get_schema.cache_clear()


@lru_cache(maxsize=1)
def spec_dir() -> Path:
    """Return the active ``spec/`` directory.

    ``TERMINUS_XI_SPEC_DIR`` overrides discovery; otherwise the directory is
    resolved relative to this source file (``src/terminus_xi/`` -> repo root).
    """
    override = os.environ.get("TERMINUS_XI_SPEC_DIR")
    if override:
        path = Path(override).resolve()
    else:
        path = Path(__file__).resolve().parents[2] / "spec"
    if not path.is_dir():
        raise FileNotFoundError(f"spec directory not found: {path}")
    return path


def schema_path(schema_id: str) -> Path:
    try:
        filename = SCHEMA_FILES[schema_id]
    except KeyError:
        raise KeyError(f"no schema registered for {schema_id!r}") from None
    return spec_dir() / filename


@lru_cache(maxsize=64)
def get_schema(schema_id: str) -> dict:
    return load_schema(schema_path(schema_id))


def validate_against(document: Any, schema_id: str, *, label: str | None = None) -> None:
    """Validate ``document`` against the registered schema. Raises SchemaError."""
    validate(
        document,
        get_schema(schema_id),
        base_dir=spec_dir(),
        label=label or schema_id,
    )
