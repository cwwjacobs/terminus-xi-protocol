"""The standard-library schema validator, cross-checked where possible.

If the ``jsonschema`` package happens to be installed, every case here is run
through it as well so that drift between the two is caught rather than assumed
away. When it is not installed those assertions are skipped, and the local
validator is still exercised on its own.
"""

from __future__ import annotations

import json
import unittest

import _support  # noqa: F401
from _support import REPO_ROOT  # noqa: E402

from terminus_xi.jsonschema_lite import SchemaError, iter_errors, validate  # noqa: E402
import terminus_proof  # noqa: E402,F401  (registers the proof schema ids)
from terminus_xi.schemas import (  # noqa: E402
    SCHEMA_FILES,
    XI_SCHEMA_FILES,
    get_schema,
    register_schema,
    schema_path,
    spec_dir,
)

try:  # pragma: no cover - depends on the environment
    import jsonschema as _jsonschema
except ImportError:  # pragma: no cover
    _jsonschema = None


CASES = [
    ("type ok", {"type": "string"}, "x", True),
    ("type wrong", {"type": "string"}, 1, False),
    ("bool is not a number", {"type": "number"}, True, False),
    ("int is a number", {"type": "number"}, 3, True),
    ("float is not an integer", {"type": "integer"}, 3.5, False),
    ("union type", {"type": ["string", "null"]}, None, True),
    ("const", {"const": "a"}, "a", True),
    ("const mismatch", {"const": "a"}, "b", False),
    ("enum", {"enum": ["a", "b"]}, "b", True),
    ("enum miss", {"enum": ["a", "b"]}, "c", False),
    ("required", {"type": "object", "required": ["a"]}, {"a": 1}, True),
    ("required missing", {"type": "object", "required": ["a"]}, {}, False),
    (
        "additionalProperties false",
        {"type": "object", "properties": {"a": {}}, "additionalProperties": False},
        {"a": 1, "b": 2},
        False,
    ),
    (
        "patternProperties",
        {
            "type": "object",
            "patternProperties": {"^[a-z]+$": {"type": "integer"}},
            "additionalProperties": False,
        },
        {"abc": 1},
        True,
    ),
    (
        "patternProperties value wrong",
        {
            "type": "object",
            "patternProperties": {"^[a-z]+$": {"type": "integer"}},
            "additionalProperties": False,
        },
        {"abc": "no"},
        False,
    ),
    ("minLength", {"type": "string", "minLength": 2}, "a", False),
    ("maxLength", {"type": "string", "maxLength": 2}, "abc", False),
    ("pattern", {"type": "string", "pattern": "^[0-9a-f]{4}$"}, "abcd", True),
    ("pattern miss", {"type": "string", "pattern": "^[0-9a-f]{4}$"}, "zzzz", False),
    ("minimum", {"type": "integer", "minimum": 0}, -1, False),
    ("maximum", {"type": "integer", "maximum": 10}, 11, False),
    ("minItems", {"type": "array", "minItems": 1}, [], False),
    ("maxItems", {"type": "array", "maxItems": 1}, [1, 2], False),
    ("uniqueItems", {"type": "array", "uniqueItems": True}, [1, 1], False),
    ("uniqueItems objects", {"type": "array", "uniqueItems": True}, [{"a": 1}, {"a": 1}], False),
    ("items", {"type": "array", "items": {"type": "integer"}}, [1, 2], True),
    ("items wrong", {"type": "array", "items": {"type": "integer"}}, [1, "x"], False),
    ("minProperties", {"type": "object", "minProperties": 1}, {}, False),
    ("anyOf", {"anyOf": [{"type": "string"}, {"type": "integer"}]}, 5, True),
    ("anyOf none", {"anyOf": [{"type": "string"}, {"type": "integer"}]}, [], False),
    ("oneOf exactly one", {"oneOf": [{"type": "string"}, {"type": "integer"}]}, "a", True),
    ("oneOf two matches", {"oneOf": [{"type": "integer"}, {"minimum": 0}]}, 5, False),
    ("unknown keyword ignored", {"type": "string", "nonsense": 1}, "a", True),
]


class TestValidatorBehaviour(unittest.TestCase):
    def test_cases(self):
        for name, schema, instance, expected in CASES:
            with self.subTest(case=name):
                errors = list(iter_errors(instance, schema))
                self.assertEqual(not errors, expected, f"{name}: {errors}")

    @unittest.skipIf(_jsonschema is None, "jsonschema package is not installed")
    def test_cases_agree_with_jsonschema(self):  # pragma: no cover
        for name, schema, instance, expected in CASES:
            with self.subTest(case=name):
                reference = _jsonschema.Draft202012Validator(schema)
                self.assertEqual(reference.is_valid(instance), expected, name)

    def test_validate_reports_every_violation(self):
        schema = {"type": "object", "required": ["a", "b", "c"]}
        with self.assertRaises(SchemaError) as ctx:
            validate({}, schema, label="doc")
        message = str(ctx.exception)
        for name in ("'a'", "'b'", "'c'"):
            self.assertIn(name, message)

    def test_relative_ref_resolves_against_the_spec_directory(self):
        errors = list(
            iter_errors(
                {"id": "x", "version": "1", "sha256": "0" * 64},
                {"$ref": "identified-document.schema.json"},
                base_dir=spec_dir(),
            )
        )
        self.assertEqual(errors, [])

    def test_local_defs_pointer_resolves(self):
        schema = {
            "$defs": {"digest": {"type": "string", "pattern": "^[0-9a-f]{4}$"}},
            "type": "object",
            "properties": {"d": {"$ref": "#/$defs/digest"}},
        }
        self.assertEqual(list(iter_errors({"d": "abcd"}, schema)), [])
        self.assertTrue(list(iter_errors({"d": "zzzz"}, schema)))

    def test_an_unresolvable_ref_raises_rather_than_passing_silently(self):
        with self.assertRaises(SchemaError):
            list(iter_errors({}, {"$ref": "#/$defs/absent"}))
        with self.assertRaises(OSError):
            list(iter_errors({}, {"$ref": "no-such-schema.json"}, base_dir=spec_dir()))

    def test_ref_without_a_base_directory_is_refused(self):
        with self.assertRaises(SchemaError):
            list(iter_errors({}, {"$ref": "identified-document.schema.json"}))


class TestSchemaRegistry(unittest.TestCase):
    def test_xi_owns_only_its_own_schema_ids(self):
        self.assertTrue(all(key.startswith("terminus-xi.") for key in XI_SCHEMA_FILES))

    def test_consumer_ids_are_registered_by_the_consumer(self):
        self.assertIn("terminus-proof.proof.v1", SCHEMA_FILES)
        self.assertNotIn("terminus-proof.proof.v1", XI_SCHEMA_FILES)

    def test_re_registering_the_same_binding_is_harmless(self):
        register_schema("terminus-proof.proof.v1", "proof.schema.json")

    def test_rebinding_a_schema_id_is_refused(self):
        with self.assertRaises(ValueError):
            register_schema("terminus-proof.proof.v1", "receipt.schema.json")


class TestShippedSchemas(unittest.TestCase):
    def test_every_registered_schema_exists_and_parses(self):
        for schema_id in sorted(SCHEMA_FILES):
            with self.subTest(schema_id=schema_id):
                path = schema_path(schema_id)
                self.assertTrue(path.exists(), f"{schema_id} -> {path} missing")
                self.assertIsInstance(get_schema(schema_id), dict)

    def test_every_spec_file_is_registered(self):
        registered = {schema_path(schema_id).name for schema_id in SCHEMA_FILES}
        on_disk = {path.name for path in (REPO_ROOT / "spec").glob("*.json")}
        self.assertEqual(on_disk - registered, set(), "unregistered schema files in spec/")

    @unittest.skipIf(_jsonschema is None, "jsonschema package is not installed")
    def test_shipped_schemas_are_valid_json_schema(self):  # pragma: no cover
        for schema_id in sorted(SCHEMA_FILES):
            with self.subTest(schema_id=schema_id):
                _jsonschema.Draft202012Validator.check_schema(get_schema(schema_id))

    def test_shipped_json_documents_all_parse(self):
        roots = ("spec", "contracts", "policies", "demos", "fixtures", "receipts")
        count = 0
        for name in roots:
            for path in sorted((REPO_ROOT / name).rglob("*.json")):
                with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                    json.loads(path.read_text(encoding="utf-8"))
                    count += 1
        self.assertGreater(count, 10)


if __name__ == "__main__":
    unittest.main()
