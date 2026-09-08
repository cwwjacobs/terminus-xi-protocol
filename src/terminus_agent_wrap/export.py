"""Drive archive protocol, local stub, and Google Drive export adapter.

Drive is the durable archive (save/backup only). Local scratch is ephemeral
and may be pruned only after a verified export ack whose ``sha256`` matches
the admitted run-artifact.

Transport injection
-------------------
``GoogleDriveExporter`` talks only to a ``DriveTransport`` with two methods:
``search_files`` and ``create_file``. It never trash-es or overwrites in place.

* Tests and local wiring: ``FakeDriveTransport`` (in-memory, no network).
* Real Drive: inject a thin adapter that maps those two methods onto the
  Drive MCP/API (``search_files`` / ``create_file`` with conversion off).
  MCP is not imported here.

Never-delete rule: title collisions get a unique title (short content hash)
or fail closed. Existing remote objects are left in place.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from terminus_xi.canonical import sha256_bytes, write_json

from .manifest import MANIFEST_NAME

__all__ = [
    "DRIVE_ARCHIVE_FOLDER",
    "DRIVE_EXPORT_NAME",
    "DRIVE_EXPORT_SCHEMA",
    "DRIVE_ROOT_PARENT",
    "DRIVE_TRACES_FOLDER",
    "EXPORT_UPLOAD_FILES",
    "FOLDER_MIME_TYPE",
    "PACKAGE_CONTENT_FILES",
    "STATUS_EXPORTED",
    "STATUS_FAILED",
    "STATUS_PARTIAL",
    "STATUS_STUBBED",
    "DriveExportError",
    "DriveExporter",
    "DriveTransport",
    "FakeDriveTransport",
    "GoogleDriveExporter",
    "LocalOnlyExporter",
]

DRIVE_EXPORT_NAME = "drive_export.json"
DRIVE_EXPORT_SCHEMA = "terminus-agent-wrap.drive-export.v1"
STATUS_STUBBED = "stubbed"
STATUS_EXPORTED = "exported"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

DRIVE_ARCHIVE_FOLDER = "Terminus"
DRIVE_TRACES_FOLDER = "XI-Traces"
DRIVE_ROOT_PARENT = "root"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"

PACKAGE_CONTENT_FILES = (
    "events.jsonl",
    "run-artifact.json",
    "receipt.json",
)
EXPORT_UPLOAD_FILES = PACKAGE_CONTENT_FILES + (MANIFEST_NAME,)

_EQ_CLAUSE = re.compile(r"(title|mimeType|parentId)\s*=\s*'((?:\\'|[^'])*)'")
_TITLE_HASH_LEN = 8


class DriveExportError(RuntimeError):
    """Export could not finish without overwriting or inventing a success ack."""


class DriveExporter(Protocol):
    """Upload one run directory to Drive and return the ack document."""

    def export(
        self,
        run_dir: Path,
        *,
        sha256: str,
        run_id: str,
    ) -> Mapping[str, Any]:
        """Write ``drive_export.json`` into ``run_dir`` and return it."""


@runtime_checkable
class DriveTransport(Protocol):
    """Search and create only. Durable archive surface: no in-place mutation."""

    def search_files(self, query: str) -> list[Mapping[str, Any]]:
        """Return file records. Each record has at least ``id`` and ``title``."""

    def create_file(
        self,
        *,
        title: str,
        parent_id: str | None = None,
        mime_type: str | None = None,
        content: bytes | None = None,
        content_mime_type: str | None = None,
        disable_conversion: bool = True,
    ) -> Mapping[str, Any]:
        """Create a folder (``mime_type`` folder, no bytes) or upload bytes.

        Uploads keep conversion off. Must not trash or update an existing file.
        """


class LocalOnlyExporter:
    """Spike stub. Not a verified Drive ack. Prune must refuse this status."""

    def export(
        self,
        run_dir: Path,
        *,
        sha256: str,
        run_id: str,
    ) -> dict[str, Any]:
        document = {
            "schema": DRIVE_EXPORT_SCHEMA,
            "status": STATUS_STUBBED,
            "run_id": run_id,
            "sha256": sha256,
            "detail": (
                "LocalOnlyExporter does not upload. Drive remains the durable "
                "archive; this stub is not a verified ack."
            ),
        }
        write_json(Path(run_dir) / DRIVE_EXPORT_NAME, document)
        return document


def _drive_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _unescape_drive(value: str) -> str:
    return value.replace("\\'", "'").replace("\\\\", "\\")


def _content_mime_type(name: str) -> str:
    if name.endswith(".jsonl"):
        return "application/x-ndjson"
    if name.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


def _unique_title(title: str, content_sha256: str) -> str:
    return f"{title}.{content_sha256[:_TITLE_HASH_LEN]}"


def _record_id(record: Mapping[str, Any] | None) -> str | None:
    if not isinstance(record, Mapping):
        return None
    value = record.get("id")
    if value is None:
        return None
    text = str(value)
    return text or None


class GoogleDriveExporter:
    """Upload one wrap package under ``Terminus/XI-Traces/<run_id>/``.

    Fail-closed: ``status`` is ``exported`` only when every intended file is
    created with a remote id. Partial success is recorded as ``partial`` or
    ``failed``; prune still refuses. Drive objects are never deleted.
    """

    def __init__(self, transport: DriveTransport) -> None:
        self._transport = transport

    def export(
        self,
        run_dir: Path,
        *,
        sha256: str,
        run_id: str,
    ) -> dict[str, Any]:
        directory = Path(run_dir)
        try:
            document = self._export(directory, sha256=sha256, run_id=run_id)
        except Exception as exc:
            document = _ack(
                status=STATUS_FAILED,
                run_id=run_id,
                sha256=sha256,
                folder_id=None,
                files=[],
                errors=[{"error": f"{type(exc).__name__}: {exc}"}],
            )
        write_json(directory / DRIVE_EXPORT_NAME, document)
        return document

    def _export(
        self,
        run_dir: Path,
        *,
        sha256: str,
        run_id: str,
    ) -> dict[str, Any]:
        missing = [name for name in EXPORT_UPLOAD_FILES if not (run_dir / name).is_file()]
        if missing:
            return _ack(
                status=STATUS_FAILED,
                run_id=run_id,
                sha256=sha256,
                folder_id=None,
                files=[],
                errors=[
                    {"title": name, "error": "local file missing; refusing export"}
                    for name in missing
                ],
            )

        folder_id: str | None = None
        uploaded: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        try:
            folder_id = self._ensure_run_folder(run_id)
        except Exception as exc:
            errors.append({"error": f"{type(exc).__name__}: {exc}"})
            return _ack(
                status=STATUS_FAILED,
                run_id=run_id,
                sha256=sha256,
                folder_id=None,
                files=[],
                errors=errors,
            )

        for name in EXPORT_UPLOAD_FILES:
            try:
                uploaded.append(self._upload_file(run_dir, name, folder_id))
            except Exception as exc:
                errors.append({"title": name, "error": f"{type(exc).__name__}: {exc}"})

        complete = (
            not errors
            and len(uploaded) == len(EXPORT_UPLOAD_FILES)
            and all(item.get("id") for item in uploaded)
        )
        if complete:
            return _ack(
                status=STATUS_EXPORTED,
                run_id=run_id,
                sha256=sha256,
                folder_id=folder_id,
                files=uploaded,
            )
        return _ack(
            status=STATUS_PARTIAL if uploaded else STATUS_FAILED,
            run_id=run_id,
            sha256=sha256,
            folder_id=folder_id,
            files=uploaded,
            errors=errors,
        )

    def _ensure_run_folder(self, run_id: str) -> str:
        parent_id = DRIVE_ROOT_PARENT
        for title in (DRIVE_ARCHIVE_FOLDER, DRIVE_TRACES_FOLDER, run_id):
            parent_id = self._ensure_folder(title, parent_id)
        return parent_id

    def _ensure_folder(self, title: str, parent_id: str) -> str:
        query = (
            f"title = {_drive_quote(title)} and "
            f"mimeType = {_drive_quote(FOLDER_MIME_TYPE)} and "
            f"parentId = {_drive_quote(parent_id)}"
        )
        matches = self._transport.search_files(query)
        for record in matches:
            file_id = _record_id(record)
            if file_id:
                return file_id
        created = self._transport.create_file(
            title=title,
            parent_id=parent_id,
            mime_type=FOLDER_MIME_TYPE,
        )
        file_id = _record_id(created)
        if not file_id:
            raise DriveExportError(f"create_file returned no id for folder {title!r}")
        return file_id

    def _title_exists(self, title: str, parent_id: str) -> bool:
        query = (
            f"title = {_drive_quote(title)} and parentId = {_drive_quote(parent_id)}"
        )
        return any(_record_id(record) for record in self._transport.search_files(query))

    def _allocate_title(self, title: str, parent_id: str, content_sha256: str) -> str:
        if not self._title_exists(title, parent_id):
            return title
        candidate = _unique_title(title, content_sha256)
        if candidate == title or self._title_exists(candidate, parent_id):
            raise DriveExportError(
                f"title {title!r} collides on Drive; refusing to overwrite"
            )
        return candidate

    def _upload_file(self, run_dir: Path, name: str, folder_id: str) -> dict[str, str]:
        content = (run_dir / name).read_bytes()
        digest = sha256_bytes(content)
        remote_title = self._allocate_title(name, folder_id, digest)
        created = self._transport.create_file(
            title=remote_title,
            parent_id=folder_id,
            content=content,
            content_mime_type=_content_mime_type(name),
            disable_conversion=True,
        )
        file_id = _record_id(created)
        if not file_id:
            raise DriveExportError(f"create_file returned no id for {remote_title!r}")
        remote_title = str(created.get("title") or remote_title)
        return {"title": remote_title, "id": file_id, "sha256": digest}


def _ack(
    *,
    status: str,
    run_id: str,
    sha256: str,
    folder_id: str | None,
    files: list[dict[str, str]],
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": DRIVE_EXPORT_SCHEMA,
        "status": status,
        "run_id": run_id,
        "sha256": sha256,
        "folder_id": folder_id,
        "files": files,
    }
    if errors:
        document["errors"] = errors
    return document


class FakeDriveTransport:
    """In-memory ``DriveTransport`` for tests. Not a verified Drive backend.

    Wire ``GoogleDriveExporter(FakeDriveTransport())`` in unit tests. A real
    MCP/API wrapper can implement the same two methods later.
    """

    def __init__(
        self,
        *,
        collide_titles: Iterable[str] = (),
        fail_titles: Iterable[str] = (),
    ) -> None:
        self._files: dict[str, dict[str, Any]] = {}
        self._collide_titles = frozenset(collide_titles)
        self._fail_titles = frozenset(fail_titles)
        self._next_id = 0
        self.calls: list[tuple[Any, ...]] = []

    def search_files(self, query: str) -> list[Mapping[str, Any]]:
        self.calls.append(("search_files", query))
        clauses = {
            match.group(1): _unescape_drive(match.group(2))
            for match in _EQ_CLAUSE.finditer(query)
        }
        hits = [
            _public_record(record)
            for record in self._files.values()
            if _record_matches(record, clauses)
        ]
        title = clauses.get("title")
        if title in self._collide_titles and not any(hit.get("title") == title for hit in hits):
            hits.append(
                {
                    "id": f"existing-{title}",
                    "title": title,
                    "parentId": clauses.get("parentId", DRIVE_ROOT_PARENT),
                }
            )
        return hits

    def create_file(
        self,
        *,
        title: str,
        parent_id: str | None = None,
        mime_type: str | None = None,
        content: bytes | None = None,
        content_mime_type: str | None = None,
        disable_conversion: bool = True,
    ) -> Mapping[str, Any]:
        resolved_parent = parent_id or DRIVE_ROOT_PARENT
        self.calls.append(
            (
                "create_file",
                title,
                resolved_parent,
                mime_type,
                content_mime_type,
                disable_conversion,
            )
        )
        if content is not None and title in self._fail_titles:
            raise DriveExportError(f"injected upload failure for {title}")
        if title in self._collide_titles:
            raise FileExistsError(f"title already exists: {title}")
        for record in self._files.values():
            if record["title"] == title and record["parentId"] == resolved_parent:
                raise FileExistsError(f"title already exists: {title}")
        self._next_id += 1
        file_id = f"gdrive-{self._next_id}"
        record = {
            "id": file_id,
            "title": title,
            "parentId": resolved_parent,
            "mimeType": mime_type or content_mime_type,
            "content": content,
            "content_mime_type": content_mime_type,
            "disable_conversion": disable_conversion,
        }
        self._files[file_id] = record
        return _public_record(record)

    def created(self, *, folders: bool | None = None) -> list[dict[str, Any]]:
        records = list(self._files.values())
        if folders is True:
            return [record for record in records if record.get("mimeType") == FOLDER_MIME_TYPE]
        if folders is False:
            return [record for record in records if record.get("content") is not None]
        return records

    def method_names(self) -> list[str]:
        return [str(call[0]) for call in self.calls]

    def file_by_title(self, title: str) -> dict[str, Any]:
        matches = [record for record in self._files.values() if record["title"] == title]
        if len(matches) != 1:
            raise KeyError(f"expected one file titled {title!r}, found {len(matches)}")
        return matches[0]


def _public_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("id", "title", "mimeType", "parentId")
        if key in record and record[key] is not None
    }


def _record_matches(record: Mapping[str, Any], clauses: Mapping[str, str]) -> bool:
    for field, expected in clauses.items():
        if field == "title" and record.get("title") != expected:
            return False
        if field == "mimeType" and record.get("mimeType") != expected:
            return False
        if field == "parentId":
            actual = record.get("parentId") or DRIVE_ROOT_PARENT
            if actual != expected:
                return False
    return True
