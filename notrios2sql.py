"""Verify and import a loose Notrios publication into a fresh notesdb directory."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, redirect_stdout
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import sys
import time
from collections.abc import Callable

import notesdb
import notrios_archive as archive_api
from notrios_archive import ArchiveLimits, DEFAULT_LIMITS, NotriosError, BlobRef
import notrios_mapping as mapping
from notrios_receipt import RECEIPT_KEY
from notrios_links import ConversionLimits, DEFAULT_CONVERSION_LIMITS
from notrios_links import validate_links, project_body, Attachment

__version__ = "3.37"

INVENTORY = "notrios-inventory.jsonl"
COMPLETE = "notrios-complete.json"
OWNER = "owner.json"
KINDS = ("collection", "notebook", "document", "revision", "tag", "resource",
         "document_tag", "document_resource", "link")
_RESOURCE = re.compile(r"[0-9a-f]{32}\.(?:" + "|".join(sorted(set(mapping._EXTENSIONS.values()) | {"bin"})) + r")\Z")


@dataclass(frozen=True)
class ImportResult:
    status: str
    destination: Path
    commit_sha256: str
    selection_manifest_sha256: str
    row_count: int
    resource_count: int

    def summary(self) -> dict[str, object]:
        """Return the content-free result fields emitted by the successful CLI."""
        return {
            "status": self.status,
            "commit_sha256": self.commit_sha256,
            "selection_manifest_sha256": self.selection_manifest_sha256,
            "row_count": self.row_count,
            "resource_count": self.resource_count,
        }


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


@contextmanager
def _conversion_errors():
    # Preserve the conversion failure before unwinding verifier filesystem
    # contexts, whose diagnostics deliberately describe only archive reads.
    try:
        yield
    except (OSError, sqlite3.Error) as exc:
        raise NotriosError("io", f"publication I/O failed: {exc}") from exc


def _receipt(manifest):
    return dict(version=1, contract="notrios-archive-v2", contract_schema_version=1,
                reader_profile="movenotes-publication-loose-v1", mapper=mapping.MAPPER_NAME,
                commit_sha256=manifest.commit_sha256,
                selection_manifest_sha256=manifest.snapshot["selection_manifest_sha256"],
                snapshot_id=manifest.snapshot["id"], database_id=manifest.snapshot["database_id"],
                target="publication_handoff")


def _rename_noreplace(parent_fd, source, destination):
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError):
        raise NotriosError("platform", "publication requires renameat2(RENAME_NOREPLACE)") from None
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EOPNOTSUPP, errno.EINVAL):
            raise NotriosError("platform", "filesystem does not support no-replace publication")
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise NotriosError("destination", "destination already exists")
        raise OSError(error, "no-replace publication failed")


def _write_file(directory_fd, name, raw):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read_json(directory_fd, name, limit):
    with archive_api._open_regular_file(directory_fd, name) as stream:
        return archive_api.read_bounded_json(stream, max_bytes=limit, max_depth=8)


@dataclass
class _OwnedDirectory:
    name: str
    fd: int
    identity: tuple
    token: str
    has_owner: bool = True

    def check(self, parent_fd):
        current = os.stat(self.name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != self.identity or not stat.S_ISDIR(current.st_mode):
            raise NotriosError("io", f"cleanup ownership changed: {self.name}")
        if self.has_owner and _read_json(self.fd, OWNER, 16384).get("token") != self.token:
            raise NotriosError("io", f"cleanup token changed: {self.name}")

    def remove(self, parent_fd):
        self.check(parent_fd)
        if not shutil.rmtree.avoids_symlink_attacks:
            raise NotriosError("platform", "safe directory cleanup is unavailable")
        shutil.rmtree(self.name, dir_fd=parent_fd)


def _make_owned(parent_fd, name, token, **extra):
    os.mkdir(name, 0o700, dir_fd=parent_fd)
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    info = os.fstat(fd)
    owned = _OwnedDirectory(name, fd, (info.st_dev, info.st_ino), token)
    try:
        _write_file(fd, OWNER, _json(dict(token=token, pid=os.getpid(), created_at=time.time(), **extra)))
        os.fsync(fd)
    except BaseException as exc:
        # We created and still hold this inode; initialization has not returned
        # it to a caller. Avoid trusting an incomplete owner record here.
        owned.has_owner = False
        try:
            owned.remove(parent_fd)
        except Exception as cleanup:
            exc.add_note(f"cleanup failed for {name}: {cleanup}")
        finally:
            os.close(fd)
        raise
    return owned


def _body(archive, revision, limits):
    ref = BlobRef(**revision.payload["body"])
    if ref.size_bytes > limits.max_body_bytes or ref.size_bytes > limits.max_projected_body_bytes:
        raise NotriosError("limit", "current body exceeds conversion byte limit")
    mime, params = archive_api._parse_storage_mime(ref.media_type)
    if mime.lower() != "text/markdown" or any(k != "charset" or v.lower() != "utf-8" for k, v in params.items()):
        raise NotriosError("conversion", "current body requires UTF-8 Markdown MIME")
    with archive.open_blob(ref) as stream:
        data = bytearray()
        while chunk := stream.read(limits.copy_chunk_bytes):
            data.extend(chunk)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise NotriosError("conversion", "current body is not UTF-8") from None
    # Body text is opaque UTF-8 Markdown. Non-NUL C0 bytes are preserved exactly;
    # link destinations, fragments, identities, and filenames retain their own
    # stricter validation in their respective parsers.
    if text.startswith("\ufeff") or "\x00" in text:
        raise NotriosError("conversion", "current body contains unsupported control characters")
    return text


def _project_note(archive, document, revision, limits, resolve):
    body = _body(archive, revision, limits).encode("utf-8")
    attachments = []
    for relation in archive.iter_relations("document_resource", document.key[0]):
        if len(attachments) >= limits.max_resource_relations_per_note:
            raise NotriosError("limit", "resource relation count exceeds limit")
        p = relation.payload
        resource = archive.get_record("resource", (p["resource_id"],))
        item_id = resolve("resource", p["resource_id"])
        mime = resource.payload["blob"]["media_type"]
        row = mapping.build_resource_row(resource, item_id=item_id, mime=mime,
                                          extension=mapping.resource_extension(mime))
        attachments.append(Attachment(item_id, row["joplin_filename"], p["relation_type"], p["ordinal"]))
    plan = validate_links(body, archive.iter_relations("link", document.key[0]), resolve=resolve, limits=limits,
                          resource_ids=(a.resource_id for a in attachments))
    return project_body(body, plan, related_resources=attachments)


def _preflight(archive, limits):
    def resolve(kind, source_id):
        archive.get_record(kind, (source_id,))
        return mapping.mapped_id(archive.manifest.snapshot["database_id"], kind, (source_id,))
    for document in archive.iter_records("document"):
        revision = archive.get_record("revision", (document.payload["current_revision_id"],))
        _project_note(archive, document, revision, limits, resolve)


class _RowBatch:
    def __init__(self, connection, limits):
        self.connection, self.limits = connection, limits
        self.rows, self.size = [], 0

    def add(self, row):
        size = sum(len(v.encode("utf-8")) if isinstance(v, str) else len(v) if isinstance(v, bytes)
                   else 0 if v is None else 8 for v in row.values())
        if self.rows and (len(self.rows) >= self.limits.batch_rows or self.size + size > self.limits.batch_bytes):
            self.flush()
        self.rows.append(row)
        self.size += size
        if self.size >= self.limits.batch_bytes or len(self.rows) >= self.limits.batch_rows:
            self.flush()

    def flush(self):
        if self.rows:
            notesdb.add_joplin_notes(self.connection, self.rows)
            self.rows, self.size = [], 0


def _register_ids(connection, archive):
    database_id = archive.manifest.snapshot["database_id"]
    connection.execute("CREATE TABLE notrios_ids (mapped_id TEXT PRIMARY KEY, source_key BLOB NOT NULL UNIQUE)")
    for kind in KINDS:
        for record in archive.iter_records(kind):
            key = mapping.source_key(database_id, kind, record.key)
            ident = mapping.mapped_id(database_id, kind, record.key)
            try:
                connection.execute("INSERT INTO notrios_ids VALUES (?,?)", (ident, key))
            except sqlite3.IntegrityError:
                raise NotriosError("collision", "mapped identity collision; refusing import") from None


def _lookup(connection, database_id, kind, key):
    row = connection.execute("SELECT mapped_id FROM notrios_ids WHERE source_key=?",
                             (mapping.source_key(database_id, kind, key),)).fetchone()
    if row is None:
        raise NotriosError("integrity", "missing mapped identity")
    return row[0]


def _copy_resource(archive, ref, directory_fd, filename, limits):
    """Copy authenticated opaque bytes into a new, exclusively owned file."""
    try:
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
    except FileExistsError:
        raise NotriosError("collision", "resource destination already exists") from None
    digest, size = hashlib.sha256(), 0
    with os.fdopen(fd, "wb") as output:
        with archive.open_blob(ref) as source:
            while chunk := source.read(limits.copy_chunk_bytes):
                size += len(chunk)
                if size > ref.size_bytes:
                    raise NotriosError("integrity", "resource exceeds declared size")
                if output.write(chunk) != len(chunk):
                    raise OSError("short resource write")
                digest.update(chunk)
        if size != ref.size_bytes or digest.hexdigest() != ref.sha256:
            raise NotriosError("integrity", "resource copy hash or size differs")
        output.flush()
        os.fsync(output.fileno())


def _write_resources(archive, connection, stage, batch, limits):
    database_id = archive.manifest.snapshot["database_id"]
    directory_fd = os.open(stage / "resources", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for record in archive.iter_records("resource"):
            item_id = _lookup(connection, database_id, "resource", record.key)
            ref = BlobRef(**record.payload["blob"])
            extension = mapping.resource_extension(ref.media_type)
            row = mapping.build_resource_row(record, item_id=item_id,
                                             mime=ref.media_type, extension=extension)
            _copy_resource(archive, ref, directory_fd, item_id + "." + extension, limits)
            batch.add(row)
    finally:
        os.close(directory_fd)


def _finalize_database(connection, expected_counts, expected_relations=0):
    notesdb.ensure_indexes(connection)
    connection.execute("CREATE UNIQUE INDEX notrios_item_id ON notes(joplin_id)")
    connection.execute("CREATE UNIQUE INDEX notrios_note_tag_pair ON notes(joplin_note_id,joplin_tag_id) WHERE joplin_type_=6")
    actual_counts = dict(connection.execute("SELECT joplin_type_,count(*) FROM notes GROUP BY joplin_type_"))
    if actual_counts != {kind: count for kind, count in expected_counts.items() if count}:
        raise NotriosError("integrity", "staged item-type counts differ")
    if connection.execute("SELECT 1 FROM notes n LEFT JOIN notrios_ids i ON i.mapped_id=n.joplin_id "
                          "WHERE i.mapped_id IS NULL OR n.note_uuid IS NOT n.joplin_id "
                          "OR n.note_parent_uuid IS NOT n.joplin_parent_id "
                          "OR n.note_note_uuid IS NOT n.joplin_note_id "
                          "OR n.note_tag_uuid IS NOT n.joplin_tag_id LIMIT 1").fetchone():
        raise NotriosError("integrity", "staged identity or alias differs")
    if connection.execute("SELECT 1 FROM notes n LEFT JOIN notes p ON p.joplin_id=n.joplin_parent_id "
                          "WHERE n.joplin_parent_id<>'' AND (p.joplin_id IS NULL OR p.joplin_type_<>2) LIMIT 1").fetchone():
        raise NotriosError("integrity", "staged parent has no folder")
    if connection.execute("SELECT 1 FROM notes r "
                          "LEFT JOIN notes n ON n.joplin_id=r.joplin_note_id "
                          "LEFT JOIN notes t ON t.joplin_id=r.joplin_tag_id "
                          "WHERE r.joplin_type_=6 AND "
                          "(n.joplin_type_ IS NOT 1 OR t.joplin_type_ IS NOT 5) LIMIT 1").fetchone():
        raise NotriosError("integrity", "staged tag membership has no note or tag target")
    if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise NotriosError("integrity", "staged SQLite integrity check failed")
    if connection.execute("SELECT count(*) FROM notrios_document_resources").fetchone()[0] != expected_relations:
        raise NotriosError("integrity", "staged resource relation count differs")
    if connection.execute("SELECT 1 FROM notrios_document_resources r "
                          "LEFT JOIN notes n ON n.joplin_id=r.note_id "
                          "LEFT JOIN notes a ON a.joplin_id=r.resource_id "
                          "LEFT JOIN notrios_ids i ON i.mapped_id=r.relation_id "
                          "WHERE n.joplin_type_ IS NOT 1 OR a.joplin_type_ IS NOT 4 "
                          "OR i.mapped_id IS NULL LIMIT 1").fetchone():
        raise NotriosError("integrity", "staged resource relation target differs")
    connection.commit()


def _build_payload(archive, stage, receipt, limits):
    (stage / "resources").mkdir(mode=0o700)
    connection = sqlite3.connect(stage / "notesdb.sqlite")
    try:
        notesdb.create_database(connection, create_indexes=False)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA cache_size=-8192")
        connection.execute("PRAGMA temp_store=FILE")
        _register_ids(connection, archive)
        connection.execute("CREATE TABLE notrios_document_resources (relation_id TEXT PRIMARY KEY, note_id TEXT NOT NULL, "
                           "resource_id TEXT NOT NULL, relation_type TEXT NOT NULL, ordinal INTEGER NOT NULL, "
                           "UNIQUE(note_id,resource_id,relation_type,ordinal))")
        connection.execute("CREATE INDEX notrios_resource_notes ON notrios_document_resources(resource_id)")
        connection.execute("CREATE INDEX notrios_note_resources ON notrios_document_resources(note_id)")
        connection.execute("INSERT INTO settings VALUES (?,?)", (RECEIPT_KEY, _json(receipt).decode()))
        database_id = receipt["database_id"]
        def lookup(kind, value):
            return _lookup(connection, database_id, kind, (value,))
        batch = _RowBatch(connection, limits)
        for record in archive.iter_records("notebook"):
            parent = record.payload.get("parent_id")
            batch.add(mapping.build_notebook_row(record, item_id=lookup("notebook", record.key[0]),
                      parent_id=lookup("notebook", parent) if parent else ""))
        for document in archive.iter_records("document"):
            revision = archive.get_record("revision", (document.payload["current_revision_id"],))
            batch.add(mapping.build_note_row(document, revision, item_id=lookup("document", document.key[0]),
                      parent_id=lookup("notebook", document.payload["notebook_id"]),
                      body=_project_note(archive, document, revision, limits, lookup)))
        for tag in archive.iter_records("tag"):
            batch.add(mapping.build_tag_row(tag, item_id=lookup("tag", tag.key[0])))
        for relation in archive.iter_records("document_tag"):
            document_id, tag_id = relation.key
            document = archive.get_record("document", (document_id,))
            batch.add(mapping.build_note_tag_row(
                item_id=_lookup(connection, database_id, "document_tag", relation.key),
                note_id=lookup("document", document_id), tag_id=lookup("tag", tag_id),
                timestamp=document.payload["created_at"],
            ))
        _write_resources(archive, connection, stage, batch, limits)
        batch.flush()
        for relation in archive.iter_records("document_resource"):
            p = relation.payload
            connection.execute("INSERT INTO notrios_document_resources VALUES (?,?,?,?,?)",
                               (_lookup(connection, database_id, "document_resource", relation.key),
                                lookup("document", p["document_id"]), lookup("resource", p["resource_id"]),
                                p["relation_type"], p["ordinal"]))
        expected_counts = {2: archive.counts["notebooks"], 1: archive.counts["documents"],
                           5: archive.counts["tags"], 6: archive.counts["document_tags"],
                           4: archive.counts["resources"]}
        _finalize_database(connection, expected_counts, archive.counts["document_resources"])
        return sum(expected_counts.values()), archive.counts["resources"]
    finally:
        connection.close()


def _hash_file(directory_fd, name, chunk_bytes, *, sync=False):
    digest, size = hashlib.sha256(), 0
    with archive_api._open_regular_file(directory_fd, name) as stream:
        while chunk := stream.read(chunk_bytes):
            digest.update(chunk)
            size += len(chunk)
        if sync:
            os.fsync(stream.fileno())
    return size, digest.hexdigest()


def _scan_payload(directory_fd, connection, limits, *, completed, sync=False):
    connection.execute("CREATE TABLE actual (path TEXT PRIMARY KEY, size_bytes INTEGER, sha256 TEXT)")
    allowed = {"notesdb.sqlite", "resources"} | ({INVENTORY, COMPLETE} if completed else set())
    seen = set()
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            if entry.name not in allowed or entry.is_symlink():
                raise NotriosError("destination", "unexpected completed payload entry")
            seen.add(entry.name)
            if entry.name == "resources":
                if not entry.is_dir(follow_symlinks=False):
                    raise NotriosError("destination", "resources must be a real directory")
                resource_fd = os.open("resources", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                try:
                    with os.scandir(resource_fd) as resources:
                        for resource in resources:
                            if not _RESOURCE.fullmatch(resource.name) or not resource.is_file(follow_symlinks=False):
                                raise NotriosError("destination", "invalid resource payload entry")
                            size, digest = _hash_file(resource_fd, resource.name, limits.copy_chunk_bytes, sync=sync)
                            connection.execute("INSERT INTO actual VALUES (?,?,?)", ("resources/" + resource.name, size, digest))
                    if sync:
                        os.fsync(resource_fd)
                finally:
                    os.close(resource_fd)
            elif not entry.is_file(follow_symlinks=False):
                raise NotriosError("destination", "payload must contain only real files")
            elif entry.name == "notesdb.sqlite":
                size, digest = _hash_file(directory_fd, entry.name, limits.copy_chunk_bytes, sync=sync)
                connection.execute("INSERT INTO actual VALUES (?,?,?)", (entry.name, size, digest))
    if seen != allowed:
        raise NotriosError("destination", "incomplete payload tree")


def _inventory_database(work):
    connection = sqlite3.connect(work / "inventory.sqlite")
    connection.execute("PRAGMA cache_size=-8192")
    connection.execute("PRAGMA temp_store=FILE")
    return connection


def _complete(stage_fd, work, receipt, limits):
    connection = _inventory_database(work)
    try:
        _scan_payload(stage_fd, connection, limits, completed=False, sync=True)
        fd = os.open(INVENTORY, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=stage_fd)
        digest, size, count = hashlib.sha256(), 0, 0
        with os.fdopen(fd, "wb") as stream:
            for path, length, sha in connection.execute("SELECT * FROM actual ORDER BY path"):
                raw = _json(dict(path=path, size_bytes=length, sha256=sha)) + b"\n"
                if len(raw) > 4096:
                    raise NotriosError("limit", "inventory line too large")
                stream.write(raw)
                digest.update(raw)
                size += len(raw)
                count += 1
            stream.flush()
            os.fsync(stream.fileno())
        marker = _json(dict(version=1, receipt=receipt, inventory_sha256=digest.hexdigest(),
                            inventory_size_bytes=size, file_count=count))
        if len(marker) > 16384:
            raise NotriosError("limit", "completion marker too large")
        _write_file(stage_fd, COMPLETE, marker)
        os.fsync(stage_fd)
    finally:
        connection.close()


def _check_existing(destination, work, receipt, limits):
    connection = _inventory_database(work)
    try:
        with archive_api._open_root_directory(destination) as directory_fd:
            marker = _read_json(directory_fd, COMPLETE, 16384)
            if (type(marker) is not dict or set(marker) != {"version", "receipt", "inventory_sha256", "inventory_size_bytes", "file_count"}
                    or type(marker["version"]) is not int or marker["version"] != 1
                    or json.dumps(marker["receipt"], sort_keys=True) != json.dumps(receipt, sort_keys=True)
                    or type(marker["inventory_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", marker["inventory_sha256"])
                    or any(type(marker[k]) is not int or marker[k] < 1 for k in ("inventory_size_bytes", "file_count"))):
                raise NotriosError("destination", "completion receipt or shape differs")
            _scan_payload(directory_fd, connection, limits, completed=True)
            actual_count = connection.execute("SELECT count(*) FROM actual").fetchone()[0]
            if marker["file_count"] != actual_count or marker["inventory_size_bytes"] > actual_count * 4096:
                raise NotriosError("destination", "inventory declarations exceed actual payload")
            connection.execute("CREATE TABLE expected (path TEXT PRIMARY KEY, size_bytes INTEGER, sha256 TEXT)")
            count, size, digest, previous = 0, 0, hashlib.sha256(), ""
            with archive_api._open_regular_file(directory_fd, INVENTORY) as stream:
                for raw in iter(lambda: stream.readline(4097), b""):
                    if len(raw) > 4096 or not raw.endswith(b"\n"):
                        raise NotriosError("destination", "invalid inventory line")
                    row = archive_api.strict_json_loads(raw, max_bytes=4096, max_depth=4)
                    if (type(row) is not dict or set(row) != {"path", "size_bytes", "sha256"}
                            or type(row["path"]) is not str or row["path"] <= previous
                            or type(row["size_bytes"]) is not int or row["size_bytes"] < 0
                            or type(row["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                        raise NotriosError("destination", "invalid inventory record")
                    previous = row["path"]
                    connection.execute("INSERT INTO expected VALUES (?,?,?)", (row["path"], row["size_bytes"], row["sha256"]))
                    digest.update(raw)
                    count += 1
                    size += len(raw)
                    if count > actual_count or size > marker["inventory_size_bytes"]:
                        raise NotriosError("destination", "inventory exceeds declared bounds")
            if (count != marker["file_count"] or size != marker["inventory_size_bytes"] or digest.hexdigest() != marker["inventory_sha256"]
                    or connection.execute("SELECT * FROM actual EXCEPT SELECT * FROM expected").fetchone()
                    or connection.execute("SELECT * FROM expected EXCEPT SELECT * FROM actual").fetchone()):
                raise NotriosError("destination", "completed payload inventory differs")
            # Immutable prevents SQLite sidecars, including with a malicious WAL
            # mode header. No general notesdb opener is safe on this read path.
            database = sqlite3.connect((destination / "notesdb.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True)
            try:
                saved = database.execute("SELECT value FROM settings WHERE name=?", (RECEIPT_KEY,)).fetchone()
                if saved is None or saved[0] != _json(receipt).decode():
                    raise NotriosError("destination", "SQLite receipt differs")
                rows = database.execute("SELECT count(*) FROM notes").fetchone()[0]
                resources = database.execute("SELECT count(*) FROM notes WHERE joplin_type_=4").fetchone()[0]
                return rows, resources
            finally:
                database.close()
    finally:
        connection.close()


def _report_progress(progress: Callable[..., None] | None, phase: str, *,
                     row_count: int | None = None, resource_count: int | None = None) -> None:
    """Report a fixed, content-free import phase for an optional caller callback."""
    if progress is not None:
        progress(phase, row_count=row_count, resource_count=resource_count)


def import_publication(source: Path, destination: Path, *, expected_selection_sha256: str | None = None,
                       archive_limits: ArchiveLimits = DEFAULT_LIMITS,
                       conversion_limits: ConversionLimits = DEFAULT_CONVERSION_LIMITS,
                       progress: Callable[..., None] | None = None) -> ImportResult:
    """Verify, stage and atomically publish an import, or verify an exact rerun.

    `progress`, when supplied, receives only fixed phase names plus completed
    SQLite row/resource counts. It never receives paths, digests, or content.
    """
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if destination.name in ("", ".", ".."):
        raise NotriosError("destination", "invalid destination basename")
    with ExitStack() as stack:
        stack.enter_context(archive_api._open_root_directory(source))
        parent_fd = stack.enter_context(archive_api._open_root_directory(destination.parent))
        source, destination = source.resolve(), destination.parent.resolve() / destination.name
        if source == destination or source in destination.parents or destination in source.parents:
            raise NotriosError("destination", "source and destination trees must be disjoint")
        if destination.is_symlink():
            raise NotriosError("destination", "destination must not be a symlink")
        token = secrets.token_hex(24)
        lock_name = ".movenotes-notrios-lock-" + hashlib.sha256(destination.name.encode("utf-8")).hexdigest()
        work_name, stage_name = ".movenotes-notrios-work-" + token, ".movenotes-notrios-stage-" + token
        owned, published, failure = [], False, None
        try:
            try:
                lock = _make_owned(parent_fd, lock_name, token, work=work_name, stage=stage_name)
            except FileExistsError:
                raise NotriosError("destination", f"import lock exists; inspect before manual recovery: {destination.parent / lock_name}") from None
            owned.append(lock)
            work = _make_owned(parent_fd, work_name, token)
            owned.append(work)
            stage = _make_owned(parent_fd, stage_name, token)
            owned.append(stage)
            work_path, stage_path = destination.parent / work_name, destination.parent / stage_name
            _report_progress(progress, "verify")
            with archive_api.verify_archive(source, work_dir=work_path, limits=archive_limits) as archive, _conversion_errors():
                receipt = _receipt(archive.manifest)
                if expected_selection_sha256 is not None and (
                        type(expected_selection_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_selection_sha256)
                        or expected_selection_sha256 != receipt["selection_manifest_sha256"]):
                    raise NotriosError("selection", "expected selection digest is malformed or differs")
                _report_progress(progress, "preflight")
                _preflight(archive, conversion_limits)
                if os.path.lexists(destination):
                    _report_progress(progress, "verify-existing")
                    rows, resources = _check_existing(destination, work_path, receipt, conversion_limits)
                    status = "unchanged"
                    _report_progress(progress, "verified-existing", row_count=rows, resource_count=resources)
                else:
                    _report_progress(progress, "stage")
                    rows, resources = _build_payload(archive, stage_path, receipt, conversion_limits)
                    status = "created"
                    _report_progress(progress, "staged", row_count=rows, resource_count=resources)
            if status == "created":
                stage.check(parent_fd)
                os.unlink(OWNER, dir_fd=stage.fd)
                stage.has_owner = False
                _report_progress(progress, "seal")
                _complete(stage.fd, work_path, receipt, conversion_limits)
                # Ensure path-based staging and the held publication descriptor
                # still name the same parent before the final operation.
                info, held = destination.parent.stat(), os.fstat(parent_fd)
                if (info.st_dev, info.st_ino) != (held.st_dev, held.st_ino):
                    raise NotriosError("io", "destination parent identity changed")
                _report_progress(progress, "publish")
                _rename_noreplace(parent_fd, stage.name, destination.name)
                published = True
                try:
                    os.fsync(parent_fd)
                except OSError:
                    raise NotriosError("io", "publication completed but parent fsync failed; durability is uncertain") from None
            return ImportResult(status, destination, receipt["commit_sha256"], receipt["selection_manifest_sha256"], rows, resources)
        except (OSError, sqlite3.Error) as exc:
            failure = NotriosError("io", f"publication I/O failed: {exc}")
            raise failure from exc
        except BaseException as exc:
            failure = exc
            raise
        finally:
            cleanup_errors = []
            for entry in reversed(owned):
                try:
                    if not (published and entry.name == stage_name):
                        # The lock preserves ownership of a sealed stage.
                        if not entry.has_owner:
                            lock.check(parent_fd)
                        entry.remove(parent_fd)
                except Exception as exc:
                    cleanup_errors.append(f"{destination.parent / entry.name}: {exc}")
                finally:
                    os.close(entry.fd)
            if cleanup_errors:
                message = "owned cleanup failed: " + "; ".join(cleanup_errors)
                if failure is not None:
                    failure.add_note(message)
                else:
                    raise NotriosError("io", message)


def _selection_digest(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("expected 64 lowercase hexadecimal characters")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notrios2sql.py", description=__doc__, allow_abbrev=False,
        epilog="Output must be absent or an identical completed import. No overwrite or merge. "
               "The output parent must exist. Atomic publication requires Linux "
               "renameat2(RENAME_NOREPLACE) and filesystem fsync support. On success, stdout "
               "contains one JSON summary line; phase/count progress and errors use stderr. "
               "Usage errors exit 2 and import errors exit 1.",
    )
    parser.add_argument("--version", action="version", version=f"notrios2sql {__version__}")
    parser.add_argument("--input", required=True, type=Path, dest="input_path",
                        help="Loose Notrios publication archive directory")
    parser.add_argument("--output", required=True, type=Path, dest="output_path",
                        help="Fresh notesdb destination, or an identical completed import")
    parser.add_argument("--expected-selection-sha256", type=_selection_digest, metavar="HEX",
                        help="Require this reviewed selection digest, including on unchanged reruns")
    return parser


def _cli_progress(phase: str, *, row_count: int | None = None,
                  resource_count: int | None = None) -> None:
    """Write bounded CLI progress without archive identifiers or local paths."""
    if row_count is None:
        print(f"phase: {phase}", file=sys.stderr, flush=True)
    else:
        print(f"phase: {phase} rows={row_count} resources={resource_count}",
              file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        # Existing notesdb helpers print progress. Keep stdout reserved for the
        # successful content-free result, including when construction fails.
        with redirect_stdout(sys.stderr):
            result = import_publication(args.input_path, args.output_path,
                                        expected_selection_sha256=args.expected_selection_sha256,
                                        progress=_cli_progress)
    except (NotriosError, OSError, sqlite3.Error) as exc:
        code = exc.code if isinstance(exc, NotriosError) else "io"
        print(f"error [{code}]: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: import interrupted", file=sys.stderr)
        return 1
    _cli_progress("complete", row_count=result.row_count, resource_count=result.resource_count)
    print(_json(result.summary()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
