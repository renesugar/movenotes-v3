"""Bounded manifest and object checks for the loose Notrios publication profile.

This is not yet a complete archive verifier. Admitting a manifest does not
verify its index, records or blobs and must not enable conversion by itself.
"""

from __future__ import annotations

from collections.abc import Mapping
import calendar
from contextlib import contextmanager
from dataclasses import dataclass, fields
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
from types import MappingProxyType
from typing import BinaryIO


class NotriosError(ValueError):
    def __init__(self, code: str, message: str, *, object_sha256: str | None = None,
                 record_type: str | None = None, record_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.object_sha256 = object_sha256
        self.record_type = record_type
        self.record_id = record_id


@dataclass(frozen=True)
class ArchiveLimits:
    max_manifest_bytes: int = 4194304
    max_objects: int = 8000000
    max_index_objects: int = 1000
    max_index_entries_per_object: int = 10000
    max_index_entry_bytes: int = 4096
    max_index_object_bytes: int = 67108864
    max_records: int = 64000000
    max_records_per_object: int = 10000
    max_record_bytes: int = 1048576
    max_record_object_bytes: int = 16777216
    max_blob_bytes: int = 17179869184
    max_total_bytes: int = 4398046511104
    max_path_bytes: int = 255
    max_path_depth: int = 8
    max_json_depth: int = 32
    max_collections: int = 1000
    max_notebooks: int = 1000000
    max_notebook_depth: int = 32
    max_capabilities: int = 64
    max_capability_name_bytes: int = 128

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 0 < value <= field.default:
                raise NotriosError("limit", f"invalid archive limit: {field.name}")


DEFAULT_LIMITS = ArchiveLimits()
REQUIRED_CAPABILITIES = (
    "identity.database-replica.v1", "objects.index.v1", "objects.sha256.v1",
    "records.jsonl.v1", "revisions.complete.v1",
)
INDEX_MEDIA_TYPE = "application/vnd.notrios.archive-v2-index+jsonl"
_ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{1,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.[0-9]{1,9})?(?:Z|\+00:00|-00:00)\Z", re.ASCII)


def _json_error(message="invalid JSON"):
    raise NotriosError("json", message) from None


def _integer_token(token: str) -> int:
    if len(token.lstrip("-")) > 19:
        _json_error("JSON integer exceeds signed 64-bit range")
    value = int(token)
    if not -(1 << 63) <= value < (1 << 63):
        _json_error("JSON integer exceeds signed 64-bit range")
    return value


def _float_token(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        _json_error("nonfinite JSON number")
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _json_error("duplicate JSON object key")
        result[key] = value
    return result


def strict_json_loads(raw: bytes, *, max_bytes: int, max_depth: int):
    """Decode one bounded JSON value; schema-specific types are checked later."""
    if type(max_bytes) is not int or max_bytes <= 0 or type(max_depth) is not int or not 0 < max_depth <= 32:
        raise NotriosError("limit", "invalid JSON decoding limits")
    if len(raw) > max_bytes:
        raise NotriosError("limit", "JSON byte limit exceeded")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _json_error("JSON is not valid UTF-8")
    # Check nesting before json.loads can allocate nested containers. Brackets
    # in strings and escaped quotes are not structural characters.
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > max_depth:
                raise NotriosError("limit", "JSON nesting limit exceeded")
        elif char in "]}":
            depth -= 1
    try:
        value = json.loads(text, object_pairs_hook=_unique_pairs,
                           parse_int=_integer_token, parse_float=_float_token,
                           parse_constant=lambda _: _json_error("nonfinite JSON number"))
    except (json.JSONDecodeError, RecursionError):
        raise NotriosError("json", "invalid JSON syntax") from None
    # json.loads preserves lone surrogate escapes; strict UTF-8 output cannot.
    def check_strings(item):
        if isinstance(item, str):
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _json_error("unpaired JSON surrogate")
        elif isinstance(item, dict):
            for key, child in item.items():
                check_strings(key)
                check_strings(child)
        elif isinstance(item, list):
            for child in item:
                check_strings(child)
    check_strings(value)
    return value


def _read_bounded_bytes(stream: BinaryIO, max_bytes: int) -> bytes:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise NotriosError("limit", "invalid JSON byte limit")
    # A regular binary stream's read(n) may return fewer than n bytes.
    chunks = bytearray()
    while len(chunks) <= max_bytes:
        try:
            chunk = stream.read(min(65536, max_bytes + 1 - len(chunks)))
        except OSError:
            raise NotriosError("io", "cannot read JSON input") from None
        if not chunk:
            break
        chunks.extend(chunk)
    if len(chunks) > max_bytes:
        raise NotriosError("limit", "JSON byte limit exceeded")
    return bytes(chunks)


def read_bounded_json(stream: BinaryIO, *, max_bytes: int, max_depth: int,
                      require_final_lf: bool = False):
    """Read at most the ceiling plus one byte, including an optional final LF."""
    raw = _read_bounded_bytes(stream, max_bytes)
    if require_final_lf and not raw.endswith(b"\n"):
        raise NotriosError("json", "JSON requires a final LF")
    return strict_json_loads(raw, max_bytes=max_bytes, max_depth=max_depth)


# Insertion order here is the pinned Go struct order, not alphabetical order.
_SNAPSHOT = dict.fromkeys(("id", "created_at", "target", "database_id",
                          "source_replica_id", "consistency"), str)
_SNAPSHOT.update(collection_ids=[str], selection_manifest_sha256=str)
_COMPATIBILITY = dict.fromkeys(("minimum_reader_version", "source_schema_version",
                               "minimum_schema_version", "maximum_schema_version"), int)
_COMPATIBILITY.update(required_capabilities=[str], optional_capabilities=[str])
_LOCATION = ({"layout": str}, {"path": str, "pack_sha256": str, "offset": int, "length": int})
_INDEX = {"sha256": str, "size_bytes": int, "entries": int, "media_type": str,
          "location": _LOCATION}
_TOTALS = (dict.fromkeys(("objects", "bytes", "record_chunks", "blobs"), int), {"packs": int})
_COUNTS = dict.fromkeys(("collections", "notebooks", "search_notebooks", "tags",
                        "documents", "revisions", "document_tags", "resources",
                        "document_resources", "links", "provenance", "source_bundles"), int)
_MANIFEST = {"format": str, "version": int, "commit_sha256": str,
             "snapshot": _SNAPSHOT, "compatibility": _COMPATIBILITY,
             "index": [_INDEX], "totals": _TOTALS, "counts": _COUNTS}


def _shaped(value, schema):
    """Check exact field/type shape and return independent immutable containers."""
    if schema is str:
        if type(value) is not str:
            _json_error("manifest string field has wrong type")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            _json_error("unpaired JSON surrogate")
        return value
    if schema is int:
        if type(value) is not int or not -(1 << 63) <= value < (1 << 63):
            _json_error("manifest integer field requires a signed 64-bit integer token")
        return value
    if isinstance(schema, list):
        if not isinstance(value, (list, tuple)):
            _json_error("manifest array field has wrong type")
        return tuple(_shaped(item, schema[0]) for item in value)
    required, optional = schema if isinstance(schema, tuple) else (schema, {})
    if not isinstance(value, Mapping):
        _json_error("manifest object field has wrong type")
    if not required.keys() <= value.keys() or value.keys() - (required.keys() | optional.keys()):
        _json_error("manifest has missing or unknown fields")
    return MappingProxyType({key: _shaped(value[key], kind)
                             for key, kind in (required | optional).items() if key in value})


@dataclass(frozen=True)
class Manifest:
    """Immutable typed shape, not proof of admission or object verification.

    Construction is also useful for testing Go semantic serialization of fields
    (e.g. Unicode and packed locations) that this consumer does not admit.
    """
    format: str
    version: int
    commit_sha256: str
    snapshot: Mapping
    compatibility: Mapping
    index: tuple
    totals: Mapping
    counts: Mapping

    def __post_init__(self):
        shaped = _shaped({field.name: getattr(self, field.name) for field in fields(self)}, _MANIFEST)
        for name, value in shaped.items():
            object.__setattr__(self, name, value)

    @classmethod
    def from_dict(cls, value: Mapping) -> Manifest:
        return cls(**_shaped(value, _MANIFEST))


def canonical_manifest_bytes(manifest: Manifest) -> bytes:
    """Go json.Marshal representation with CommitSHA256 omitted, no final LF."""
    def plain(value):
        if isinstance(value, Mapping):
            return {key: plain(child) for key, child in value.items()}
        if isinstance(value, tuple):
            return [plain(child) for child in value]
        return value
    data = {name: plain(getattr(manifest, name)) for name in _MANIFEST if name != "commit_sha256"}
    for descriptor in data["index"]:
        location = descriptor["location"]
        for name in ("path", "pack_sha256", "offset", "length"):
            if not location.get(name):
                location.pop(name, None)
    if not data["totals"].get("packs"):
        data["totals"].pop("packs", None)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for char, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                          ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        text = text.replace(char, escaped)
    return text.encode("utf-8")


def compute_commit_sha256(manifest: Manifest) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def _bounded(value: int, minimum: int, maximum: int, label: str):
    if not minimum <= value <= maximum:
        raise NotriosError("limit", f"{label} outside admitted range")


def _admit_manifest(manifest: Manifest, limits: ArchiveLimits):
    if manifest.format != "notrios-archive" or manifest.version != 2:
        raise NotriosError("format", "a loose archive-v2 publication is required")
    snapshot, compat = manifest.snapshot, manifest.compatibility
    if snapshot["target"] != "publication_handoff":
        raise NotriosError("publication", "only publication_handoff is supported")
    if compat["minimum_reader_version"] != 2:
        raise NotriosError("format", "unsupported minimum reader version")
    if not (12 <= compat["minimum_schema_version"] <= 27 and
            compat["minimum_schema_version"] <= compat["source_schema_version"] <= compat["maximum_schema_version"]):
        raise NotriosError("format", "unsupported schema bounds")
    required, optional = compat["required_capabilities"], compat["optional_capabilities"]
    _bounded(len(required) + len(optional), 0, limits.max_capabilities, "capability count")
    for names in (required, optional):
        if tuple(sorted(set(names))) != names:
            raise NotriosError("capability", "capabilities must be sorted and unique")
        for name in names:
            if not _ID.fullmatch(name):
                raise NotriosError("capability", "invalid capability name")
            _bounded(len(name.encode("utf-8")), 1, limits.max_capability_name_bytes, "capability name")
    if "objects.pack.v1" in required:
        raise NotriosError("capability", "packed archives are unsupported; produce a loose publication")
    if required != REQUIRED_CAPABILITIES or set(required) & set(optional):
        raise NotriosError("capability", "missing, unknown or overlapping required capabilities")
    if not _SHA256.fullmatch(manifest.commit_sha256) or not _SHA256.fullmatch(snapshot["selection_manifest_sha256"]):
        raise NotriosError("format", "manifest digests must be lowercase SHA-256")
    for name in ("id", "database_id", "source_replica_id"):
        if not _ID.fullmatch(snapshot[name]):
            raise NotriosError("format", "invalid snapshot identity")
    timestamp = snapshot["created_at"]
    if not _UTC.fullmatch(timestamp):
        raise NotriosError("format", "snapshot created_at must be RFC3339 UTC")
    # Go admits year 0000, whereas datetime's lower bound is year 0001.
    # Calendar arithmetic also avoids losing the admitted nanosecond spelling.
    year, month, day = int(timestamp[:4]), int(timestamp[5:7]), int(timestamp[8:10])
    hour, minute, second = int(timestamp[11:13]), int(timestamp[14:16]), int(timestamp[17:19])
    if not (1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]
            and hour <= 23 and minute <= 59 and second <= 59):
        raise NotriosError("format", "invalid snapshot calendar timestamp")
    if snapshot["consistency"] != "sqlite_read_transaction":
        raise NotriosError("format", "unsupported snapshot consistency")
    collections = snapshot["collection_ids"]
    _bounded(len(collections), 1, limits.max_collections, "collection scope")
    if tuple(sorted(set(collections))) != collections or any(not _ID.fullmatch(value) for value in collections):
        raise NotriosError("format", "collection IDs must be sorted, unique and valid")
    for count in manifest.counts.values():
        _bounded(count, 0, limits.max_records, "record count")
    _bounded(sum(manifest.counts.values()), 0, limits.max_records, "total records")
    _bounded(manifest.counts["collections"], 1, limits.max_collections, "collection count")
    _bounded(manifest.counts["notebooks"], 0, limits.max_notebooks, "notebook count")
    if manifest.counts["collections"] != len(collections):
        raise NotriosError("integrity", "collection count differs from snapshot scope")
    if any(manifest.counts[name] for name in ("search_notebooks", "provenance", "source_bundles")):
        raise NotriosError("publication", "publication declares forbidden record types")
    _bounded(len(manifest.index), 1, limits.max_index_objects, "index count")
    seen = set()
    declared = 0
    for descriptor in manifest.index:
        digest, location = descriptor["sha256"], descriptor["location"]
        if not _SHA256.fullmatch(digest):
            raise NotriosError("format", "invalid index hash")
        if digest in seen:
            raise NotriosError("integrity", "duplicate index descriptor")
        seen.add(digest)
        if location["layout"] != "fanout" or set(location) & {"pack_sha256", "offset", "length"}:
            raise NotriosError("capability", "packed locations are unsupported; produce a loose publication")
        path = f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}"
        if location.get("path") != path:
            raise NotriosError("path", "index path does not match its hash")
        _bounded(len(path.encode("utf-8")), 1, limits.max_path_bytes, "index path bytes")
        _bounded(len(path.split("/")), 1, limits.max_path_depth, "index path depth")
        if descriptor["media_type"] != INDEX_MEDIA_TYPE:
            raise NotriosError("format", "unsupported index media type")
        _bounded(descriptor["size_bytes"], 1, limits.max_index_object_bytes, "index bytes")
        _bounded(descriptor["entries"], 1, limits.max_index_entries_per_object, "index entries")
        declared += descriptor["entries"]
        _bounded(declared, 1, limits.max_objects, "declared object count")
    totals = manifest.totals
    if totals.get("packs", 0) != 0:
        raise NotriosError("capability", "packed archives are unsupported; produce a loose publication")
    _bounded(totals["objects"], 1, limits.max_objects, "object total")
    _bounded(totals["bytes"], 0, limits.max_total_bytes, "byte total")
    _bounded(totals["record_chunks"], 1, limits.max_records, "record chunks")
    _bounded(totals["blobs"], 0, limits.max_objects, "blob total")
    if totals["objects"] != declared or totals["record_chunks"] + totals["blobs"] != declared:
        raise NotriosError("integrity", "manifest totals do not account for declared objects")
    if compute_commit_sha256(manifest) != manifest.commit_sha256:
        raise NotriosError("integrity", "manifest commit checksum mismatch")


def parse_manifest(raw: bytes, *, limits: ArchiveLimits = DEFAULT_LIMITS) -> Manifest:
    value = strict_json_loads(raw, max_bytes=limits.max_manifest_bytes, max_depth=limits.max_json_depth)
    manifest = _manifest_value(value)
    _admit_manifest(manifest, limits)
    return manifest


def _manifest_value(value) -> Manifest:
    # Other formats have different schemas: explain the required input rather
    # than reporting their different field sets as a broken v2 manifest.
    if isinstance(value, Mapping):
        if type(value.get("format")) is str and value["format"] != "notrios-archive":
            raise NotriosError("format", "a loose archive-v2 publication is required")
        if type(value.get("version")) is int and value["version"] != 2:
            raise NotriosError("format", "a loose archive-v2 publication is required")
    return Manifest.from_dict(value)


@contextmanager
def _open_root_directory(root: Path):
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise NotriosError("platform", "safe manifest opening requires no-follow directory handles")
    directory_fd = None
    try:
        # Walk using held descriptors so symlink parents cannot redirect reads.
        # Do not collapse '..' before walking: a preceding symlink component
        # must refuse even if lexical normalization would erase it.
        root = Path(root)
        absolute = root if root.is_absolute() else Path.cwd() / root
        directory_fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
        for part in absolute.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        yield directory_fd
    except OSError:
        raise NotriosError("io", "cannot read archive directory") from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


@contextmanager
def _open_regular_file(root_fd: int, relative: str):
    parts = relative.split("/")
    if "\\" in relative or any(part in ("", ".", "..") for part in parts):
        raise NotriosError("path", "invalid archive-relative path")
    directory_fd = os.dup(root_fd)
    file_fd = None
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise NotriosError("path", "archive object must be a regular file")
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None
            yield stream
    except OSError:
        raise NotriosError("io", "cannot read regular archive object") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _read_manifest_at(root_fd: int, limits: ArchiveLimits) -> tuple[Manifest, bytes]:
    with _open_regular_file(root_fd, "manifest.json") as stream:
        _bounded(os.fstat(stream.fileno()).st_size, 1, limits.max_manifest_bytes, "manifest bytes")
        raw = _read_bounded_bytes(stream, limits.max_manifest_bytes)
    return parse_manifest(raw, limits=limits), raw


def read_manifest(root: Path, *, limits: ArchiveLimits = DEFAULT_LIMITS) -> Manifest:
    """Admit only manifest.json; do not open or enumerate any archive objects."""
    with _open_root_directory(root) as root_fd:
        manifest, _raw = _read_manifest_at(root_fd, limits)
        return manifest


RECORDS_MEDIA_TYPE = "application/vnd.notrios.archive-v2-records+jsonl"
_COPY_BYTES = 1 << 20
_BATCH_ROWS = 1000
_BATCH_BYTES = 32 << 20
_ENTRY = ({"sha256": str, "kind": str, "media_type": str, "size_bytes": int,
           "location": _LOCATION}, {"records": int, "record_counts": _COUNTS})
_RECORD_NAMES = dict(zip(
    ("collection", "notebook", "search_notebook", "tag", "document", "revision",
     "document_tag", "resource", "document_resource", "link", "provenance", "source_bundle"),
    _COUNTS,
))
_HEX_PAIR = re.compile(r"[0-9a-f]{2}\Z")
_MIME_SPACE = "\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
_MIME_SPECIAL = '()<>@,;:\\"/[]?='


def _validate_storage_mime(value: str):
    """Go ParseMediaType syntax checks; no semantic MIME normalization yet.

    Storage hints need not be canonical. RFC2231 continuation decoding cannot
    make Go parsing fail, so it is unnecessary for this syntax-only check.
    Canonical record/reference MIME equality belongs to the typed-record phase.
    """
    if not 0 < len(value.encode("utf-8")) <= 255:
        raise NotriosError("format", "invalid storage MIME length")

    def token(text):
        end = 0
        while end < len(text) and 32 < ord(text[end]) < 127 and text[end] not in _MIME_SPECIAL:
            end += 1
        return text[:end], text[end:]

    def invalid():
        raise NotriosError("format", "invalid storage MIME syntax")

    base, separator, tail = value.partition(";")
    # Go lowercases by rune; U+0130's simple lowercase is ASCII i.
    base = base.replace("\u0130", "i").lower().strip(_MIME_SPACE)
    first, rest = token(base)
    if not first:
        invalid()
    if rest:
        if not rest.startswith("/"):
            invalid()
        subtype, rest = token(rest[1:])
        if not subtype or rest:
            invalid()
    remaining = separator + tail
    parameters = {}
    while remaining:
        remaining = remaining.lstrip(_MIME_SPACE)
        if not remaining or remaining.strip(_MIME_SPACE) == ";":
            break
        if not remaining.startswith(";"):
            invalid()
        key, remaining = token(remaining[1:].lstrip(_MIME_SPACE))
        key = key.lower()
        remaining = remaining.lstrip(_MIME_SPACE)
        if not key or not remaining.startswith("="):
            invalid()
        remaining = remaining[1:].lstrip(_MIME_SPACE)
        if remaining.startswith('"'):
            decoded = []
            index = 1
            while index < len(remaining) and remaining[index] != '"':
                char = remaining[index]
                if char in "\r\n":
                    invalid()
                if char == "\\" and index + 1 < len(remaining) and remaining[index + 1] in _MIME_SPECIAL:
                    index += 1
                    char = remaining[index]
                decoded.append(char)
                index += 1
            if index == len(remaining):
                invalid()
            parameter, remaining = "".join(decoded), remaining[index + 1:]
        else:
            parameter, remaining = token(remaining)
            if not parameter:
                invalid()
        if key in parameters and parameters[key] != parameter:
            invalid()
        parameters[key] = parameter


def _index_entry(value, limits: ArchiveLimits):
    entry = _shaped(value, _ENTRY)
    digest, location = entry["sha256"], entry["location"]
    if not _SHA256.fullmatch(digest):
        raise NotriosError("format", "invalid indexed object hash")
    if location["layout"] != "fanout" or set(location) & {"pack_sha256", "offset", "length"}:
        raise NotriosError("capability", "packed locations are unsupported; produce a loose publication")
    expected = f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}"
    if location.get("path") != expected:
        raise NotriosError("path", "indexed object path does not match its hash")
    _bounded(len(expected), 1, limits.max_path_bytes, "object path bytes")
    _bounded(5, 1, limits.max_path_depth, "object path depth")
    _bounded(entry["size_bytes"], 0, limits.max_blob_bytes, "object bytes")
    counts = entry.get("record_counts", {})
    for count in counts.values():
        _bounded(count, 0, limits.max_records_per_object, "indexed record count")
    if entry["kind"] == "records":
        if entry["media_type"] != RECORDS_MEDIA_TYPE:
            raise NotriosError("format", "unsupported records media type")
        _bounded(entry["size_bytes"], 1, limits.max_record_object_bytes, "record object bytes")
        _bounded(entry.get("records", 0), 1, limits.max_records_per_object, "records per object")
        if "record_counts" not in entry or sum(counts.values()) != entry["records"]:
            raise NotriosError("integrity", "indexed record counts do not agree")
    elif entry["kind"] == "blob":
        if entry.get("records", 0) != 0 or any(counts.values()):
            raise NotriosError("integrity", "blob entry declares records")
        _validate_storage_mime(entry["media_type"])
    elif entry["kind"] == "pack":
        raise NotriosError("capability", "packed objects are unsupported; produce a loose publication")
    else:
        raise NotriosError("format", "unknown indexed object kind")
    return entry


def _jsonl_values(path: Path, *, line_bytes: int, line_count: int, limits: ArchiveLimits):
    """Read private checked copies, keeping one byte-bounded line at a time."""
    with path.open("rb") as stream:
        number = 0
        while True:
            raw = stream.readline(line_bytes + 1)
            if not raw:
                return
            _bounded(len(raw), 1, line_bytes, "JSONL line bytes")
            if not raw.endswith(b"\n"):
                raise NotriosError("json", "JSONL requires a final LF")
            if not raw.strip():
                raise NotriosError("json", "blank JSONL line")
            number += 1
            _bounded(number, 1, line_count, "JSONL line count")
            yield number, raw, strict_json_loads(raw, max_bytes=line_bytes, max_depth=limits.max_json_depth)


class _InsertBatch:
    """Bound SQLite insert buffers by row count AND encoded value bytes."""
    def __init__(self, connection, sql):
        self.connection, self.sql = connection, sql
        self.rows = []
        self.size = 0

    def add(self, row):
        size = sum(len(value.encode("utf-8")) if isinstance(value, str) else
                   len(value) if isinstance(value, bytes) else 8 for value in row)
        if self.rows and (len(self.rows) >= _BATCH_ROWS or self.size + size > _BATCH_BYTES):
            self.flush()
        self.rows.append(row)
        self.size += size
        if self.size >= _BATCH_BYTES:
            self.flush()

    def flush(self):
        if self.rows:
            self.connection.executemany(self.sql, self.rows)
            self.connection.commit()
            self.rows.clear()
            self.size = 0


@dataclass(frozen=True)
class _ObjectSpool:
    """Internal 2b checkpoint: checked bytes/envelopes, NOT checked semantics.

    The connection and copies are owned by _stage_archive_objects. They may
    not outlive its context. Only a later complete verifier can promote this
    state to VerifiedArchive after typed-record/reference/publication checks.
    """
    directory: Path
    manifest: Manifest
    connection: sqlite3.Connection


def _copy_checked_object(root_fd: int, destination: Path, entry):
    relative = entry["location"]["path"]
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_size = entry["size_bytes"]
    with _open_regular_file(root_fd, relative) as source:
        if os.fstat(source.fileno()).st_size != expected_size:
            raise NotriosError("integrity", "archive object size mismatch", object_sha256=entry["sha256"])
        digest, total = hashlib.sha256(), 0
        with target.open("xb") as output:
            while True:
                raw = source.read(min(_COPY_BYTES, expected_size + 1 - total))
                if not raw:
                    break
                total += len(raw)
                if total > expected_size:
                    raise NotriosError("integrity", "archive object grew during read", object_sha256=entry["sha256"])
                digest.update(raw)
                output.write(raw)
        if total != expected_size or digest.hexdigest() != entry["sha256"]:
            raise NotriosError("integrity", "archive object checksum mismatch", object_sha256=entry["sha256"])
    target.chmod(0o400)


def _scan_source_inventory(root_fd: int, connection, manifest_bytes: int, expected_files: int):
    batch = _InsertBatch(connection, "INSERT INTO source_files(path,size_bytes) VALUES (?,?)")
    count = 0

    def walk(directory_fd, parts):
        nonlocal count
        # scandir(fd) streams directory entries and does not follow links.
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                current = (*parts, entry.name)
                relative = "/".join(current)
                info = entry.stat(follow_symlinks=False)
                mode = info.st_mode
                if stat.S_ISDIR(mode):
                    valid = (current == ("objects",) or current == ("objects", "sha256") or
                             (len(current) in (3, 4) and current[:2] == ("objects", "sha256")
                              and all(_HEX_PAIR.fullmatch(part) for part in current[2:])))
                    if not valid:
                        raise NotriosError("path", "unexpected archive directory shape")
                    child_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        walk(child_fd, current)
                    finally:
                        os.close(child_fd)
                else:
                    if not stat.S_ISREG(mode):
                        raise NotriosError("path", "archive contains a symlink or special file")
                    if current != ("manifest.json",):
                        if not (len(current) == 5 and current[:2] == ("objects", "sha256")
                                and _SHA256.fullmatch(current[4]) and current[2] == current[4][:2]
                                and current[3] == current[4][2:4]):
                            raise NotriosError("path", "unexpected archive file path")
                    count += 1
                    if count > expected_files:
                        raise NotriosError("integrity", "archive contains extra files")
                    batch.add((relative, info.st_size))

    walk(root_fd, ())
    batch.flush()
    if count != expected_files or connection.execute(
        "SELECT size_bytes FROM source_files WHERE path='manifest.json'"
    ).fetchone() != (manifest_bytes,):
        raise NotriosError("integrity", "archive file inventory is incomplete or changed")
    if connection.execute(
        "SELECT 1 FROM source_files f LEFT JOIN objects o ON o.path=f.path "
        "WHERE f.path!='manifest.json' AND (o.path IS NULL OR o.size_bytes!=f.size_bytes) LIMIT 1"
    ).fetchone() or connection.execute(
        "SELECT 1 FROM objects o LEFT JOIN source_files f ON f.path=o.path WHERE f.path IS NULL LIMIT 1"
    ).fetchone():
        raise NotriosError("integrity", "archive files differ from the declared inventory")


def _stage_index(root_fd, spool, limits):
    manifest, connection = spool.manifest, spool.connection
    insert = _InsertBatch(connection, "INSERT INTO objects VALUES (?,?,?,?,?,?,?)")
    index_hashes = {entry["sha256"] for entry in manifest.index}  # At most 1000.
    for descriptor in manifest.index:
        insert.add((descriptor["sha256"], "index", descriptor["media_type"], descriptor["size_bytes"],
                    descriptor["location"]["path"], 0, "{}"))
    insert.flush()
    previous = ""
    totals = {"objects": 0, "bytes": 0, "record_chunks": 0, "blobs": 0}
    counts = dict.fromkeys(_COUNTS, 0)
    for descriptor in manifest.index:
        _copy_checked_object(root_fd, spool.directory, descriptor)
        number = 0
        for number, _raw, value in _jsonl_values(
            spool.directory / descriptor["location"]["path"], line_bytes=limits.max_index_entry_bytes,
            line_count=descriptor["entries"], limits=limits,
        ):
            entry = _index_entry(value, limits)
            if entry["sha256"] <= previous or entry["sha256"] in index_hashes:
                raise NotriosError("integrity", "index hashes must be globally ordered, unique and distinct from index chunks")
            previous = entry["sha256"]
            totals["objects"] += 1
            totals["bytes"] += entry["size_bytes"]
            totals["record_chunks" if entry["kind"] == "records" else "blobs"] += 1
            for key in totals:
                if totals[key] > manifest.totals[key]:
                    raise NotriosError("integrity", "indexed totals exceed manifest declaration")
            for key, count in entry.get("record_counts", {}).items():
                counts[key] += count
                if counts[key] > manifest.counts[key]:
                    raise NotriosError("integrity", "indexed record counts exceed manifest declaration")
            insert.add((entry["sha256"], entry["kind"], entry["media_type"], entry["size_bytes"],
                        entry["location"]["path"], entry.get("records", 0),
                        json.dumps(dict(entry.get("record_counts", {})), separators=(",", ":"))))
        if number != descriptor["entries"]:
            raise NotriosError("integrity", "index chunk entry count mismatch")
    insert.flush()
    if totals != {key: manifest.totals[key] for key in totals} or counts != dict(manifest.counts):
        raise NotriosError("integrity", "indexed totals/counts differ from manifest")


def _stage_data_objects(root_fd, spool, limits):
    records = _InsertBatch(spool.connection,
                           "INSERT INTO records(object_sha256,line_number,record_type,raw) VALUES (?,?,?,?)")
    for digest, kind, size, path, expected_count, counts_json in spool.connection.execute(
        "SELECT sha256,kind,size_bytes,path,records,counts_json FROM objects WHERE kind!='index' ORDER BY sha256"
    ):
        _copy_checked_object(root_fd, spool.directory, {
            "sha256": digest, "size_bytes": size, "location": {"path": path},
        })
        if kind == "records":
            counts = dict.fromkeys(_COUNTS, 0)
            number = 0
            for number, raw, value in _jsonl_values(
                spool.directory / path, line_bytes=limits.max_record_bytes,
                line_count=expected_count, limits=limits,
            ):
                if not isinstance(value, dict) or set(value) != {"type", "payload"}:
                    raise NotriosError("json", "record envelope requires exactly type and payload")
                if type(value["type"]) is not str or not isinstance(value["payload"], dict):
                    raise NotriosError("json", "record envelope has invalid field types")
                if value["type"] not in _RECORD_NAMES:
                    raise NotriosError("format", "unknown archive record type")
                counts[_RECORD_NAMES[value["type"]]] += 1
                records.add((digest, number, value["type"], raw))
            if number != expected_count or counts != json.loads(counts_json):
                raise NotriosError("integrity", "decoded record counts differ from index")
    records.flush()


@contextmanager
def _stage_archive_objects(root: Path, *, work_dir: Path, limits: ArchiveLimits = DEFAULT_LIMITS):
    """Internal byte/index checkpoint; deliberately not verify_archive.

    Strict record envelopes are spooled, but payload schemas, identities,
    references, blob usage and publication semantics still require slice 2d.
    No caller may treat this context as authorization to publish or convert.
    """
    with _open_root_directory(root) as root_fd:
        manifest, raw = _read_manifest_at(root_fd, limits)
        root_real, work_real = Path(os.path.realpath(root)), Path(os.path.realpath(work_dir))
        if work_real == root_real or root_real in work_real.parents:
            raise NotriosError("path", "verification work directory must be outside the archive")
        # Refuse symlink work parents too; only newly owned temporary state is
        # ever removed.
        with _open_root_directory(work_dir):
            pass
        with tempfile.TemporaryDirectory(prefix=".notrios-objects-", dir=work_dir) as temporary:
            directory = Path(temporary)
            (directory / "manifest.json").write_bytes(raw)
            (directory / "manifest.json").chmod(0o400)
            connection = None
            try:
                connection = sqlite3.connect(directory / "spool.sqlite")
                connection.execute("PRAGMA cache_size=-8192")
                connection.execute("PRAGMA temp_store=FILE")
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.executescript(
                    "CREATE TABLE objects(sha256 TEXT PRIMARY KEY,kind TEXT NOT NULL,media_type TEXT NOT NULL,"
                    "size_bytes INTEGER NOT NULL,path TEXT UNIQUE NOT NULL,records INTEGER NOT NULL,counts_json TEXT NOT NULL);"
                    "CREATE TABLE records(seq INTEGER PRIMARY KEY,object_sha256 TEXT NOT NULL,line_number INTEGER NOT NULL,"
                    "record_type TEXT NOT NULL,raw BLOB NOT NULL,UNIQUE(object_sha256,line_number));"
                    "CREATE INDEX records_by_type ON records(record_type,seq);"
                    "CREATE TABLE source_files(path TEXT PRIMARY KEY,size_bytes INTEGER NOT NULL);"
                )
                spool = _ObjectSpool(directory, manifest, connection)
                _stage_index(root_fd, spool, limits)
                _stage_data_objects(root_fd, spool, limits)
                _scan_source_inventory(root_fd, connection, len(raw), manifest.totals["objects"] + len(manifest.index) + 1)
                yield spool
            except sqlite3.Error:
                raise NotriosError("io", "temporary object spool database failed") from None
            finally:
                if connection is not None:
                    connection.close()
