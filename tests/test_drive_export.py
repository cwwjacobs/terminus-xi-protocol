"""Google Drive export adapter: FakeTransport, fail-closed ack, never-delete."""

from __future__ import annotations

import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path

import _support  # noqa: F401
from _support import FrozenClock, REPO_ROOT  # noqa: E402

from terminus_xi.canonical import read_json, sha256_bytes, sha256_file  # noqa: E402

from terminus_agent_wrap.export import (  # noqa: E402
    DRIVE_ARCHIVE_FOLDER,
    DRIVE_EXPORT_NAME,
    DRIVE_EXPORT_SCHEMA,
    DRIVE_ROOT_PARENT,
    DRIVE_TRACES_FOLDER,
    EXPORT_UPLOAD_FILES,
    FOLDER_MIME_TYPE,
    PACKAGE_CONTENT_FILES,
    STATUS_EXPORTED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_STUBBED,
    DriveTransport,
    FakeDriveTransport,
    GoogleDriveExporter,
    LocalOnlyExporter,
)
from terminus_agent_wrap.prune import PruneRefused, prune_run_dir  # noqa: E402
from terminus_agent_wrap.wrap import wrap_run  # noqa: E402

from test_agent_run_wrap import CLOCK, WRAP_ROOT, failing_events  # noqa: E402

_FORBIDDEN_DRIVE_MUTATORS = frozenset({"trash_file", "update_file"})


def _protocol_methods(cls: type) -> set[str]:
    names: set[str] = set()
    for name, value in cls.__dict__.items():
        if name.startswith("_"):
            continue
        if callable(value):
            names.add(name)
    return names


def _wrap(scratch: Path, exporter) -> object:
    with FrozenClock(CLOCK):
        return wrap_run(failing_events(), scratch_root=scratch, exporter=exporter)


class TestDriveExportAdapter(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix="agent-wrap-drive-"))

    def test_transport_protocol_is_search_and_create_only(self):
        self.assertEqual(_protocol_methods(DriveTransport), {"search_files", "create_file"})
        for name in _FORBIDDEN_DRIVE_MUTATORS:
            self.assertFalse(hasattr(DriveTransport, name), name)
            self.assertFalse(hasattr(GoogleDriveExporter, name), name)
            self.assertFalse(hasattr(FakeDriveTransport, name), name)
        create = inspect.signature(DriveTransport.create_file)
        self.assertNotIn("fileId", create.parameters)
        self.assertIn("title", create.parameters)
        self.assertIn("content", create.parameters)
        self.assertIn("disable_conversion", create.parameters)

    def test_wrapper_call_path_never_names_drive_mutators(self):
        for path in sorted(WRAP_ROOT.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            defs = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            overlap = (attrs | defs) & _FORBIDDEN_DRIVE_MUTATORS
            self.assertEqual(overlap, set(), f"{path} references {sorted(overlap)}")

    def test_fake_transport_satisfies_the_protocol(self):
        fake = FakeDriveTransport()
        self.assertIsInstance(fake, DriveTransport)

    def test_happy_path_exported_ack_and_prune(self):
        fake = FakeDriveTransport()
        wrapped = _wrap(self.scratch, GoogleDriveExporter(fake))
        ack = wrapped.drive_export
        self.assertEqual(ack["schema"], DRIVE_EXPORT_SCHEMA)
        self.assertEqual(ack["status"], STATUS_EXPORTED)
        self.assertEqual(ack["run_id"], wrapped.run_id)
        self.assertEqual(ack["sha256"], wrapped.artifact_sha256)
        self.assertNotIn("errors", ack)

        folders = fake.created(folders=True)
        self.assertEqual(
            [record["title"] for record in folders],
            [DRIVE_ARCHIVE_FOLDER, DRIVE_TRACES_FOLDER, wrapped.run_id],
        )
        self.assertEqual(folders[0]["parentId"], DRIVE_ROOT_PARENT)
        self.assertEqual(ack["folder_id"], fake.file_by_title(wrapped.run_id)["id"])

        by_title = {entry["title"]: entry for entry in ack["files"]}
        self.assertEqual(tuple(by_title), EXPORT_UPLOAD_FILES)
        for name in PACKAGE_CONTENT_FILES:
            local_digest = sha256_file(wrapped.directory / name)
            self.assertEqual(by_title[name]["sha256"], local_digest)
            self.assertEqual(by_title[name]["id"], fake.file_by_title(name)["id"])
            self.assertTrue(by_title[name]["id"])
            uploaded = fake.file_by_title(name)
            self.assertEqual(sha256_bytes(uploaded["content"]), local_digest)
            self.assertTrue(uploaded["disable_conversion"])

        manifest_remote = fake.file_by_title("MANIFEST.json")
        self.assertEqual(by_title["MANIFEST.json"]["sha256"], sha256_bytes(manifest_remote["content"]))
        self.assertNotEqual(
            by_title["MANIFEST.json"]["sha256"],
            sha256_file(wrapped.directory / "MANIFEST.json"),
        )
        remote_manifest = json.loads(manifest_remote["content"].decode("utf-8"))
        self.assertTrue(remote_manifest.get("export_pending"))
        self.assertEqual(
            [entry["path"] for entry in remote_manifest["files"]],
            list(PACKAGE_CONTENT_FILES),
        )
        self.assertNotIn(DRIVE_EXPORT_NAME, [entry["path"] for entry in remote_manifest["files"]])

        local_manifest = read_json(wrapped.directory / "MANIFEST.json")
        self.assertNotIn("export_pending", local_manifest)
        self.assertEqual(
            [entry["path"] for entry in local_manifest["files"]],
            list(PACKAGE_CONTENT_FILES) + [DRIVE_EXPORT_NAME],
        )

        file_creates = [
            call for call in fake.calls if call[0] == "create_file" and call[4] is not None
        ]
        self.assertTrue(file_creates)
        self.assertTrue(all(call[5] is True for call in file_creates))
        self.assertEqual(set(fake.method_names()), {"search_files", "create_file"})

        prune_run_dir(wrapped.directory, expected_sha256=wrapped.artifact_sha256)
        self.assertFalse(wrapped.directory.exists())

    def test_partial_upload_is_not_exported_and_prune_refuses(self):
        fake = FakeDriveTransport(fail_titles=("receipt.json", "MANIFEST.json"))
        wrapped = _wrap(self.scratch, GoogleDriveExporter(fake))
        ack = wrapped.drive_export
        self.assertNotEqual(ack["status"], STATUS_EXPORTED)
        self.assertEqual(ack["status"], STATUS_PARTIAL)
        self.assertEqual(ack["sha256"], wrapped.artifact_sha256)
        self.assertEqual(len(ack["files"]), 2)
        self.assertEqual(
            [entry["title"] for entry in ack["files"]],
            ["events.jsonl", "run-artifact.json"],
        )
        self.assertTrue(ack.get("errors"))
        self.assertTrue((wrapped.directory / DRIVE_EXPORT_NAME).is_file())
        with self.assertRaises(PruneRefused) as refused:
            prune_run_dir(wrapped.directory)
        self.assertIn("not a verified ack", str(refused.exception))
        self.assertTrue(wrapped.directory.is_dir())
        self.assertEqual(set(fake.method_names()), {"search_files", "create_file"})

    def test_title_collision_uses_unique_name_and_does_not_overwrite(self):
        fake = FakeDriveTransport(collide_titles=("events.jsonl",))
        wrapped = _wrap(self.scratch, GoogleDriveExporter(fake))
        ack = wrapped.drive_export
        self.assertEqual(ack["status"], STATUS_EXPORTED)
        events_entry = next(entry for entry in ack["files"] if "events.jsonl" in entry["title"])
        self.assertNotEqual(events_entry["title"], "events.jsonl")
        self.assertTrue(events_entry["title"].startswith("events.jsonl."))
        self.assertEqual(len(events_entry["title"].rsplit(".", 1)[-1]), 8)
        self.assertEqual(
            events_entry["sha256"],
            sha256_file(wrapped.directory / "events.jsonl"),
        )

        upload_titles = [
            call[1] for call in fake.calls if call[0] == "create_file" and call[4] is not None
        ]
        self.assertNotIn("events.jsonl", upload_titles)
        self.assertIn(events_entry["title"], upload_titles)
        self.assertEqual(set(fake.method_names()), {"search_files", "create_file"})
        with self.assertRaises(FileExistsError):
            fake.create_file(
                title="events.jsonl",
                parent_id=ack["folder_id"],
                content=b"nope",
                content_mime_type="application/x-ndjson",
                disable_conversion=True,
            )

    def test_wrap_writes_manifest_before_export_runs(self):
        seen: dict[str, object] = {}

        class RecordingExporter:
            def export(self, run_dir, *, sha256, run_id):
                names = sorted(path.name for path in Path(run_dir).iterdir() if path.is_file())
                seen["names"] = names
                seen["has_drive_export"] = (Path(run_dir) / DRIVE_EXPORT_NAME).is_file()
                manifest = read_json(Path(run_dir) / "MANIFEST.json")
                seen["manifest_files"] = [entry["path"] for entry in manifest["files"]]
                seen["export_pending"] = manifest.get("export_pending")
                return LocalOnlyExporter().export(run_dir, sha256=sha256, run_id=run_id)

        wrapped = _wrap(self.scratch, RecordingExporter())
        self.assertEqual(
            seen["names"],
            ["MANIFEST.json", "events.jsonl", "receipt.json", "run-artifact.json"],
        )
        self.assertFalse(seen["has_drive_export"])
        self.assertEqual(seen["manifest_files"], list(PACKAGE_CONTENT_FILES))
        self.assertTrue(seen["export_pending"])
        self.assertEqual(wrapped.drive_export["status"], STATUS_STUBBED)
        self.assertTrue((wrapped.directory / DRIVE_EXPORT_NAME).is_file())

    def test_missing_local_package_is_failed_not_exported(self):
        fake = FakeDriveTransport()
        empty = self.scratch / "empty"
        empty.mkdir()
        ack = GoogleDriveExporter(fake).export(empty, sha256="a" * 64, run_id="run_missing")
        self.assertEqual(ack["status"], STATUS_FAILED)
        self.assertEqual(ack["files"], [])
        self.assertTrue(ack.get("errors"))
        self.assertEqual(fake.created(), [])
        with self.assertRaises(PruneRefused):
            prune_run_dir(empty, expected_sha256="a" * 64)

    def test_local_only_exporter_still_stubbed(self):
        wrapped = _wrap(self.scratch, LocalOnlyExporter())
        self.assertEqual(wrapped.drive_export["status"], STATUS_STUBBED)
        with self.assertRaises(PruneRefused):
            prune_run_dir(wrapped.directory)

    def test_folder_mime_is_used_for_the_archive_chain(self):
        fake = FakeDriveTransport()
        _wrap(self.scratch, GoogleDriveExporter(fake))
        folder_creates = [
            call for call in fake.calls if call[0] == "create_file" and call[3] == FOLDER_MIME_TYPE
        ]
        self.assertEqual(len(folder_creates), 3)
        self.assertEqual(
            [call[1] for call in folder_creates][:2],
            [DRIVE_ARCHIVE_FOLDER, DRIVE_TRACES_FOLDER],
        )


if __name__ == "__main__":
    unittest.main()
