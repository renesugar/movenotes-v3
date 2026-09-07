"""Bounded manifest admission for the loose Notrios publication profile.

This is not yet a complete archive verifier. Admitting a manifest does not
verify its index, records or blobs and must not enable conversion by itself.
"""

from __future__ import annotations

from collections.abc import Mapping
import calendar
from dataclasses import dataclass, fields
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
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


def read_bounded_json(stream: BinaryIO, *, max_bytes: int, max_depth: int,
                      require_final_lf: bool = False):
    """Read at most the ceiling plus one byte, including an optional final LF."""
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
    if require_final_lf and not chunks.endswith(b"\n"):
        raise NotriosError("json", "JSON requires a final LF")
    return strict_json_loads(bytes(chunks), max_bytes=max_bytes, max_depth=max_depth)


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


def read_manifest(root: Path, *, limits: ArchiveLimits = DEFAULT_LIMITS) -> Manifest:
    """Admit only manifest.json; do not open or enumerate any archive objects."""
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise NotriosError("platform", "safe manifest opening requires no-follow directory handles")
    directory_fd = file_fd = None
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
        file_fd = os.open("manifest.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise NotriosError("path", "manifest must be a regular file")
        _bounded(info.st_size, 1, limits.max_manifest_bytes, "manifest bytes")
        with os.fdopen(file_fd, "rb") as stream:
            file_fd = None
            value = read_bounded_json(stream, max_bytes=limits.max_manifest_bytes, max_depth=limits.max_json_depth)
        manifest = _manifest_value(value)
        _admit_manifest(manifest, limits)
        return manifest
    except OSError:
        raise NotriosError("io", "cannot open/read a regular publication manifest") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
