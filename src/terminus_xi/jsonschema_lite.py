"""A small standard-library JSON Schema validator.

XI runtime must not require a third-party validator to establish its own
invariants, so this module implements the exact keyword subset used by the
schemas under ``spec/``:

``$ref`` (relative file, and local ``#/$defs/...`` pointers), ``type``, ``const``,
``enum``, ``required``, ``properties``, ``patternProperties``,
``additionalProperties``, ``minProperties``, ``items``, ``minItems``, ``maxItems``,
``uniqueItems``, ``minLength``, ``maxLength``, ``pattern``, ``minimum``,
``maximum``, ``anyOf``, ``oneOf``.

Unknown keywords are ignored, exactly as JSON Schema requires. ``tests/
test_schema_lite.py`` cross-checks this validator against the ``jsonschema``
package when it is installed, so drift between the two is caught rather than
assumed away.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

__all__ = ["SchemaError", "iter_errors", "validate", "load_schema"]


class SchemaError(ValueError):
    """The instance did not satisfy the schema."""


_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def load_schema(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _type_ok(value: Any, name: str) -> bool:
    if name == "boolean":
        return isinstance(value, bool)
    if name in ("number", "integer") and isinstance(value, bool):
        return False
    expected = _TYPES.get(name)
    if expected is None:
        return True
    return isinstance(value, expected)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _pointer(document: Any, fragment: str) -> Any:
    current = document
    for raw in fragment.split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise SchemaError(f"unresolvable $ref fragment: {fragment!r}")
        current = current[token]
    return current


def _resolve_ref(
    ref: str, base_dir: Path | None, root: Any
) -> tuple[Any, Path | None, Any]:
    file_part, _, fragment = ref.partition("#")
    if not file_part:
        return _pointer(root, fragment), base_dir, root
    if base_dir is None:
        raise SchemaError(f"cannot resolve $ref without a base directory: {ref!r}")
    target = (base_dir / file_part).resolve()
    document = load_schema(target)
    resolved = _pointer(document, fragment) if fragment else document
    return resolved, target.parent, document


def iter_errors(
    instance: Any,
    schema: Any,
    *,
    base_dir: str | Path | None = None,
    path: str = "",
) -> Iterable[str]:
    """Yield human-readable validation errors, deterministically ordered."""
    directory = Path(base_dir) if base_dir is not None else None
    yield from _iter(instance, schema, directory, path, schema)


def _iter(
    instance: Any, schema: Any, base_dir: Path | None, path: str, root: Any
) -> Iterable[str]:
    where = path or "<root>"
    if schema is True or schema == {}:
        return
    if schema is False:
        yield f"{where}: schema forbids any value"
        return
    if not isinstance(schema, dict):
        yield f"{where}: invalid schema node"
        return

    if "$ref" in schema:
        target, next_dir, next_root = _resolve_ref(schema["$ref"], base_dir, root)
        yield from _iter(instance, target, next_dir, path, next_root)
        return

    if "type" in schema:
        declared = schema["type"]
        names = declared if isinstance(declared, list) else [declared]
        if not any(_type_ok(instance, name) for name in names):
            yield f"{where}: expected type {declared!r}, got {type(instance).__name__}"
            return

    if "const" in schema and _canonical(instance) != _canonical(schema["const"]):
        yield f"{where}: expected const {schema['const']!r}, got {instance!r}"
    if "enum" in schema:
        allowed = [_canonical(item) for item in schema["enum"]]
        if _canonical(instance) not in allowed:
            yield f"{where}: {instance!r} is not one of {schema['enum']!r}"

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            yield f"{where}: shorter than minLength {schema['minLength']}"
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            yield f"{where}: longer than maxLength {schema['maxLength']}"
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            yield f"{where}: does not match pattern {schema['pattern']!r}"

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            yield f"{where}: below minimum {schema['minimum']}"
        if "maximum" in schema and instance > schema["maximum"]:
            yield f"{where}: above maximum {schema['maximum']}"

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            yield f"{where}: fewer than minItems {schema['minItems']}"
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            yield f"{where}: more than maxItems {schema['maxItems']}"
        if schema.get("uniqueItems") is True:
            seen = [_canonical(item) for item in instance]
            if len(set(seen)) != len(seen):
                yield f"{where}: items are not unique"
        if "items" in schema:
            for index, item in enumerate(instance):
                yield from _iter(item, schema["items"], base_dir, f"{path}/{index}", root)

    if isinstance(instance, dict):
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            yield f"{where}: fewer than minProperties {schema['minProperties']}"
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            yield f"{where}: more than maxProperties {schema['maxProperties']}"
        for name in schema.get("required", []):
            if name not in instance:
                yield f"{where}: missing required property {name!r}"
        properties = schema.get("properties", {})
        pattern_properties = schema.get("patternProperties", {})
        additional = schema.get("additionalProperties", True)
        for key in sorted(instance):
            child_path = f"{path}/{key}"
            matched = False
            if key in properties:
                matched = True
                yield from _iter(instance[key], properties[key], base_dir, child_path, root)
            for expression, subschema in pattern_properties.items():
                if re.search(expression, key):
                    matched = True
                    yield from _iter(instance[key], subschema, base_dir, child_path, root)
            if matched:
                continue
            if additional is False:
                yield f"{where}: additional property {key!r} is not allowed"
            elif isinstance(additional, dict):
                yield from _iter(instance[key], additional, base_dir, child_path, root)

    for keyword in ("anyOf", "oneOf"):
        if keyword not in schema:
            continue
        matches = 0
        for subschema in schema[keyword]:
            if not list(_iter(instance, subschema, base_dir, path, root)):
                matches += 1
        if keyword == "anyOf" and matches == 0:
            yield f"{where}: matches no anyOf branch"
        if keyword == "oneOf" and matches != 1:
            yield f"{where}: matches {matches} oneOf branches, expected exactly 1"


def validate(
    instance: Any,
    schema: Any,
    *,
    base_dir: str | Path | None = None,
    label: str = "document",
) -> None:
    """Raise :class:`SchemaError` listing every violation, or return None."""
    errors = list(iter_errors(instance, schema, base_dir=base_dir))
    if errors:
        joined = "\n  - ".join(errors)
        raise SchemaError(f"{label} failed schema validation:\n  - {joined}")
