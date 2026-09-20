"""Canonical identity, the rule everything else is built on."""

from __future__ import annotations

import unittest

from _support import FrozenClock  # noqa: E402

from terminus_xi.canonical import (  # noqa: E402
    PointerError,
    canonical_json,
    pointer_exists,
    resolve_pointer,
    sha256_canonical,
    sha256_text,
    utc_now,
)


class TestCanonicalJson(unittest.TestCase):
    def test_key_order_does_not_change_identity(self):
        left = {"b": 1, "a": {"d": 2, "c": 3}}
        right = {"a": {"c": 3, "d": 2}, "b": 1}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(sha256_canonical(left), sha256_canonical(right))

    def test_list_order_does_change_identity(self):
        self.assertNotEqual(sha256_canonical([1, 2]), sha256_canonical([2, 1]))

    def test_non_finite_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            canonical_json({"x": float("nan")})
        with self.assertRaises(ValueError):
            canonical_json({"x": float("inf")})

    def test_unicode_is_not_escaped_but_is_stable(self):
        value = {"note": "café ✓"}
        self.assertIn("café", canonical_json(value))
        self.assertEqual(sha256_canonical(value), sha256_canonical({"note": "café ✓"}))

    def test_digest_is_over_utf8_bytes(self):
        self.assertEqual(sha256_canonical("a"), sha256_text('"a"'))


class TestPointer(unittest.TestCase):
    def setUp(self):
        self.document = {"a": {"b": [10, {"c": "deep"}]}, "": "empty-key", "x/y": "escaped"}

    def test_empty_pointer_is_the_whole_document(self):
        self.assertIs(resolve_pointer(self.document, ""), self.document)

    def test_object_and_array_traversal(self):
        self.assertEqual(resolve_pointer(self.document, "/a/b/1/c"), "deep")
        self.assertEqual(resolve_pointer(self.document, "/a/b/0"), 10)

    def test_escaped_tokens(self):
        self.assertEqual(resolve_pointer(self.document, "/x~1y"), "escaped")
        self.assertEqual(resolve_pointer(self.document, "/"), "empty-key")

    def test_missing_key_raises_rather_than_returning_none(self):
        with self.assertRaises(PointerError):
            resolve_pointer(self.document, "/a/nope")
        self.assertFalse(pointer_exists(self.document, "/a/nope"))

    def test_index_out_of_range_and_scalar_descent_raise(self):
        with self.assertRaises(PointerError):
            resolve_pointer(self.document, "/a/b/9")
        with self.assertRaises(PointerError):
            resolve_pointer(self.document, "/a/b/1/c/deeper")

    def test_pointer_must_be_rooted(self):
        with self.assertRaises(PointerError):
            resolve_pointer(self.document, "a/b")


class TestClock(unittest.TestCase):
    def test_override_is_honoured(self):
        with FrozenClock("2000-01-01T00:00:00Z"):
            self.assertEqual(utc_now(), "2000-01-01T00:00:00Z")

    def test_real_clock_is_utc_second_precision(self):
        stamp = utc_now()
        self.assertTrue(stamp.endswith("Z"), stamp)
        self.assertNotIn(".", stamp)


if __name__ == "__main__":
    unittest.main()
