#!/usr/bin/env python3
"""Bounded, duplicate-aware comparison for the C7c recipe routes.

The comparison consumes the two pinned Notrios producer databases, the
read-only Joplin RAW source tree, and the read-only Obsidian source tree.  It
keeps per-record facts in a private SQLite spool and writes only aggregate
counts and SHA-256 fingerprints to ``result.json``.  Source paths, IDs, note
titles, bodies, and metadata never leave the private spool.

This is a comparison tool, not an archive verifier.  It deliberately accepts
an incomplete or semantically different route as a completed comparison and
reports the differences.  ``--strict`` changes the process exit status for a
non-equivalent result; it does not hide or filter records.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sqlite3
import sys
import time
import unicodedata
import zlib

# This tool lives in scripts/; the shared modules it imports are at the root.
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import notrios_archive

import joplin2sql


RULES_VERSION = "c7c-recipe-semantic-v6"
SPOOL_SCHEMA_VERSION = 5
DEFAULT_MAX_SOURCE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_COMPRESSED_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_FRONTMATTER_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_TAGS = 10_000
DEFAULT_MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_B64 = re.compile(r"^[A-Za-z0-9_-]*={0,2}$")


class C7CError(RuntimeError):
    """A bounded comparison or checkpoint error."""


class CheckpointMismatch(C7CError):
    """The output checkpoint does not describe the requested inputs."""


class LimitExceeded(C7CError):
    """An input exceeded a per-record safety limit."""


class C7CQueryTimeout(C7CError):
    """A comparison query exceeded its bounded execution deadline."""

    def __init__(self, label: str, elapsed_seconds: float, timeout_seconds: float):
        self.label = label
        self.elapsed_seconds = float(elapsed_seconds)
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"comparison query timed out: {label} after "
            f"{elapsed_seconds:.3f}s (limit {timeout_seconds:.3f}s)"
        )


class _SkipSourceSnapshot(C7CError):
    """A valid Joplin RAW item carrying a folder snapshot, not a note."""


@dataclass(frozen=True)
class Limits:
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    max_compressed_bytes: int = DEFAULT_MAX_COMPRESSED_BYTES
    max_decompressed_bytes: int = DEFAULT_MAX_DECOMPRESSED_BYTES
    max_frontmatter_bytes: int = DEFAULT_MAX_FRONTMATTER_BYTES
    max_tags: int = DEFAULT_MAX_TAGS


@dataclass(frozen=True)
class Snapshot:
    path: PurePosixPath
    raw: bytes
    raw_sha256: str
    joplin_body_sha256: str


class QueryRunner:
    """Run comparison SQL with a progress-handler deadline and durable trace.

    SQLite only invokes a progress handler while executing virtual-machine
    instructions.  That makes the deadline effective for the large joins that
    previously stalled the comparison, while leaving the source/archive scans
    outside this comparison-query budget.  The trace is intentionally an
    aggregate timing ledger: it contains labels and durations, never SQL
    values, paths, document IDs, or note content.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        timeout_seconds: float,
        progress_path: Path | None = None,
    ):
        if timeout_seconds <= 0:
            raise C7CError("query timeout must be positive")
        self.connection = connection
        self.timeout_seconds = float(timeout_seconds)
        self.progress_path = progress_path
        self.started = time.time()
        self.current: dict[str, object] | None = None
        self.completed: list[dict[str, object]] = []
        self.status = "pending"
        self._persist()

    def _persist(self, *, error: dict[str, object] | None = None) -> None:
        if self.progress_path is None:
            return
        value: dict[str, object] = {
            "status": self.status,
            "started": self.started,
            "updated": time.time(),
            "query_timeout_seconds": self.timeout_seconds,
            "current": self.current,
            "completed_queries": self.completed[-256:],
        }
        if error is not None:
            value["error"] = error
        _atomic_json(self.progress_path, value)

    def call(self, label: str, operation):
        if not label or not isinstance(label, str):
            raise C7CError("comparison query label is required")
        started_wall = time.time()
        started_mono = time.monotonic()
        deadline = started_mono + self.timeout_seconds
        timed_out = False
        self.status = "running"
        self.current = {"label": label, "started": started_wall}
        self._persist()

        def progress() -> int:
            nonlocal timed_out
            if time.monotonic() >= deadline:
                timed_out = True
                return 1
            return 0

        self.connection.set_progress_handler(progress, 1_000)
        try:
            value = operation()
        except sqlite3.OperationalError as exc:
            elapsed = time.monotonic() - started_mono
            if timed_out:
                timeout = C7CQueryTimeout(label, elapsed, self.timeout_seconds)
                self.completed.append({
                    "label": label,
                    "started": started_wall,
                    "finished": time.time(),
                    "elapsed_seconds": elapsed,
                    "status": "timed_out",
                })
                self.current = None
                self.status = "failed"
                self._persist(error={
                    "type": type(timeout).__name__,
                    "label": label,
                    "elapsed_seconds": elapsed,
                    "timeout_seconds": self.timeout_seconds,
                })
                raise timeout from exc
            self.completed.append({
                "label": label,
                "started": started_wall,
                "finished": time.time(),
                "elapsed_seconds": elapsed,
                "status": "error",
                "error_type": type(exc).__name__,
            })
            self.current = None
            self.status = "failed"
            self._persist(error={"type": type(exc).__name__, "label": label})
            raise
        except BaseException as exc:
            elapsed = time.monotonic() - started_mono
            self.completed.append({
                "label": label,
                "started": started_wall,
                "finished": time.time(),
                "elapsed_seconds": elapsed,
                "status": "error",
                "error_type": type(exc).__name__,
            })
            self.current = None
            self.status = "failed"
            self._persist(error={"type": type(exc).__name__, "label": label})
            raise
        else:
            elapsed = time.monotonic() - started_mono
            self.completed.append({
                "label": label,
                "started": started_wall,
                "finished": time.time(),
                "elapsed_seconds": elapsed,
                "status": "complete",
            })
            self.current = None
            self.status = "complete"
            self._persist()
            return value
        finally:
            self.connection.set_progress_handler(None, 0)


def _timed_query(runner: QueryRunner | None, label: str, operation):
    """Run one comparison subquery through the optional bounded runner."""

    return runner.call(label, operation) if runner is not None else operation()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(6))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(_canonical_json(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _strict_object(value: str) -> object:
    def pairs(items):
        # ``object_pairs_hook`` is called once for each object.  Keep this set
        # inside the hook: sharing it across nested objects rejects legal
        # repeated names that occur in separate objects.
        seen: set[str] = set()
        result = {}
        for key, item in items:
            if key in seen:
                raise C7CError("duplicate JSON key")
            seen.add(key)
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=pairs)


def _physical_line(text: str, start: int) -> tuple[str, int, bool]:
    """Return one CR/LF-delimited line without treating C0 controls as ends."""

    length = len(text)
    index = start
    while index < length and text[index] not in "\r\n":
        index += 1
    line = text[start:index]
    if index >= length:
        return line, length, False
    if text[index] == "\r" and index + 1 < length and text[index + 1] == "\n":
        return line, index + 2, True
    return line, index + 1, True


def _iter_physical_lines(text: str):
    start = 0
    while start < len(text):
        line, start, had_ending = _physical_line(text, start)
        yield line, had_ending
    if not text:
        return


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _semantic_body_hash(
    value: str, *, drop_leading_lf: bool = False, drop_terminal_lf: bool = False
) -> str:
    value = _normalize_text(value)
    if drop_leading_lf:
        # The Obsidian producer calls TrimLeft(rest, "\n"); that is the only
        # route with a documented leading-LF rule.  Do not apply it to source
        # snapshots or RAW output.
        value = value.lstrip("\n")
    if drop_terminal_lf and value.endswith("\n"):
        # The Joplin producer appends one generated terminal LF.  Remove one
        # and retain any additional source whitespace.
        value = value[:-1]
    return _sha256_text(value)


def _semantic_title(value: str) -> str:
    # Title whitespace is meaningful unless a route-specific parser has
    # already proved that it was trimmed (the RAW source-title parser below
    # does so, matching the pinned Joplin importer).
    return _normalize_text(value)


def _pinned_frontmatter_scalar(frontmatter: str, key: str) -> str:
    """Apply the pinned Notrios ``frontmatterScalar`` rule for one key.

    The importer intentionally uses a line-oriented lookup: it trims the
    whole line, splits on the first colon, trims the value, then removes quote
    characters from the two edges.  Keeping this as a named route rule lets
    title differences be classified from the actual producer behavior rather
    than being silently normalized by the comparator.
    """

    wanted = key.lower()
    for line, _had_ending in _iter_physical_lines(_normalize_text(frontmatter)):
        trimmed = line.strip()
        index = trimmed.find(":")
        if index <= 0 or trimmed[:index].strip().lower() != wanted:
            continue
        # Match the pinned Go helper exactly:
        # strings.TrimSpace(strings.Trim(strings.TrimSpace(value), `"'`)).
        # The second TrimSpace matters for producer titles such as
        # ``"Example Recipe '"``: quote trimming exposes the space
        # before the stray quote.  This is a route-specific scalar rule, not
        # a general whitespace normalization.
        value = trimmed[index + 1 :].strip()
        return value.strip("'\"").strip()
    return ""


def _value_normalize(value: object) -> object:
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list):
        return [_value_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _value_normalize(item) for key, item in value.items()}
    return value


def _value_scalar(value: str) -> object:
    value = value.strip()
    if not value:
        return ""
    if value.startswith('"'):
        if not value.endswith('"'):
            raise C7CError("unsupported quoted scalar")
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise C7CError("unsupported quoted scalar") from exc
        if not isinstance(parsed, str):
            raise C7CError("quoted scalar is not text")
        return parsed
    if value.startswith("'"):
        # Single-quoted YAML has escaping rules that are outside this tiny
        # grammar.  Refuse it until a separately reviewed decoder is added.
        raise C7CError("unsupported single-quoted scalar")
    if value.startswith("[") or value.startswith("{"):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise C7CError("unsupported flow value") from exc
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise C7CError("unsupported mapping value")
        # JSON has already decoded these strings.  Re-parsing ``"true"`` as
        # a YAML boolean changes the scalar meaning and was a source of false
        # matches in the old comparator.
        return [_normalize_text(item) for item in parsed]
    if value[:1] in {"'", "`"} or value[-1:] in {"'", "`"}:
        raise C7CError("ambiguous quoted scalar")
    # The pinned recipe generator delegates scalar decoding to JSON-compatible
    # scalar parsing.  Bounded decimal/integer values are therefore part of
    # the admitted producer grammar; exponent spellings and leading-zero
    # forms remain refused because they are not emitted by the generator and
    # would broaden the YAML surface without a reviewed rule.
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise C7CError("unsupported numeric scalar") from exc
        if isinstance(parsed, (int, float)) and not isinstance(parsed, bool):
            return parsed
        raise C7CError("unsupported numeric scalar")
    lowered = value.lower()
    # The pinned producer's JSON-first scalar helper admits these exact
    # spellings. Other YAML boolean spellings remain ordinary text below;
    # broader YAML coercion would make unknown metadata silently change type.
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    # The pinned recipe generator's JSON-first scalar helper leaves these
    # YAML boolean spellings as ordinary text.  Keep that producer behavior
    # explicit instead of applying a broader YAML decoder.
    # Plain YAML text is retained exactly after the grammar's required edge
    # whitespace.  Unknown syntax is compared as metadata, never discarded.
    if any(character in value for character in ("&", "*", "!", "|", ">", "{", "}")):
        raise C7CError("unsupported scalar syntax")
    return value


def parse_frontmatter(frontmatter: str, *, max_bytes: int = DEFAULT_MAX_FRONTMATTER_BYTES) -> dict[str, object]:
    """Parse the small scalar/list grammar used by the recipe producer.

    This intentionally rejects nested YAML, aliases, multiline values and
    ambiguous flow syntax.  The caller retains the exact frontmatter digest
    even when parsing is rejected.
    """

    if len(frontmatter.encode("utf-8")) > max_bytes:
        raise LimitExceeded("frontmatter exceeds limit")
    values: dict[str, object] = {}
    original_keys: dict[str, str] = {}
    current_key: str | None = None
    empty_pending: set[str] = set()
    for line, _had_ending in _iter_physical_lines(_normalize_text(frontmatter)):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            if current_key is None or not line.lstrip().startswith("-"):
                raise C7CError("unsupported nested frontmatter")
            item = _value_scalar(line.lstrip()[1:])
            if current_key in empty_pending:
                values[current_key] = []
                empty_pending.remove(current_key)
            if not isinstance(values.get(current_key), list):
                raise C7CError("mixed scalar/list frontmatter")
            values[current_key].append(item)
            continue
        match = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)
        if match is None:
            raise C7CError("unsupported frontmatter line")
        raw_key, raw_value = match.groups()
        key = raw_key.lower()
        if key in original_keys:
            raise C7CError("duplicate frontmatter key")
        original_keys[key] = raw_key
        current_key = key
        if raw_value.strip() == "":
            values[key] = ""
            empty_pending.add(key)
        else:
            values[key] = _value_scalar(raw_value)
    return _value_normalize(values)  # type: ignore[return-value]


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return exact leading frontmatter content and the remaining text."""

    first, position, had_ending = _physical_line(text, 0)
    if first != "---" or not had_ending:
        return None, text
    content_start = position
    while position <= len(text):
        line, next_position, had_ending = _physical_line(text, position)
        if line == "---":
            return text[content_start:position], text[next_position:]
        if not had_ending:
            break
        position = next_position
    return None, text


def _remove_outer_obsidian_fields(frontmatter: str, expected_path: str) -> str:
    """Validate and remove the exact fields inserted by the Obsidian producer."""
    expected = {"source_system": "obsidian", "obsidian_path": expected_path}
    parent = PurePosixPath(expected_path).parent.as_posix()
    if parent != ".":
        expected["obsidian_folder"] = parent
    values: dict[str, object] = {}
    # Parse only the three producer-owned lines.  Native recipe frontmatter
    # can contain unsupported YAML; that is checked separately after these
    # fields have been independently validated.
    for line, _had_ending in _iter_physical_lines(frontmatter):
        match = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)
        if match is None:
            continue
        key, raw_value = match.groups()
        key = key.lower()
        if key not in expected:
            continue
        if key in values:
            raise C7CError("duplicate Obsidian wrapper field")
        values[key] = _value_scalar(raw_value)
    for key in ("source_system", "obsidian_path", "obsidian_folder"):
        present = key in values
        if present != (key in expected) or (present and values[key] != expected[key]):
            raise C7CError("Obsidian wrapper metadata mismatch")

    removed: set[str] = set()
    lines: list[str] = []
    for line, had_ending in _iter_physical_lines(frontmatter):
        match = re.match(r"^([A-Za-z0-9_-]+):", line)
        key = match.group(1).lower() if match else None
        if key in expected and key not in removed:
            removed.add(key)
            continue
        lines.append(line + ("\n" if had_ending else ""))
    return "".join(lines)


def _safe_relative(value: object) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    if "\\" in value or value.startswith("/") or "//" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if path.as_posix() != value:
        return None
    return path


def _decode_snapshot(value: str, limits: Limits) -> Snapshot:
    try:
        root = _strict_object(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise C7CError("invalid application_data JSON") from exc
    if not isinstance(root, dict):
        raise C7CError("application_data is not an object")
    envelope = root.get("movenotes_obsidian_v1")
    if isinstance(envelope, dict) and envelope.get("kind") == "folder":
        raise _SkipSourceSnapshot("folder snapshot is not a recipe note")
    if not isinstance(envelope, dict) or envelope.get("kind") != "note":
        raise C7CError("missing Obsidian note snapshot")
    path = _safe_relative(envelope.get("path"))
    encoded = envelope.get("raw_zlib_base64")
    raw_digest = envelope.get("raw_sha256")
    body_digest = envelope.get("joplin_body_sha256")
    if path is None:
        raise C7CError("unsafe snapshot path")
    if not isinstance(encoded, str) or len(encoded) > limits.max_compressed_bytes * 2 or not _B64.fullmatch(encoded):
        raise LimitExceeded("invalid or oversized snapshot encoding")
    if len(encoded) % 4:
        raise C7CError("invalid snapshot base64 padding")
    try:
        compressed = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise C7CError("invalid snapshot base64") from exc
    if len(compressed) > limits.max_compressed_bytes:
        raise LimitExceeded("compressed snapshot exceeds limit")
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(compressed, limits.max_decompressed_bytes + 1)
    if len(raw) > limits.max_decompressed_bytes:
        raise LimitExceeded("decompressed snapshot exceeds limit")
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise C7CError("truncated or concatenated snapshot")
    try:
        raw += decompressor.flush(limits.max_decompressed_bytes + 1 - len(raw))
    except zlib.error as exc:
        raise C7CError("invalid compressed snapshot") from exc
    if len(raw) > limits.max_decompressed_bytes:
        raise LimitExceeded("decompressed snapshot exceeds limit")
    if not isinstance(raw_digest, str) or not _HEX64.fullmatch(raw_digest):
        raise C7CError("invalid snapshot digest")
    if _sha256_bytes(raw) != raw_digest.lower():
        raise C7CError("snapshot digest mismatch")
    if not isinstance(body_digest, str) or not _HEX64.fullmatch(body_digest):
        raise C7CError("invalid generated-body digest")
    return Snapshot(path, raw, raw_digest.lower(), body_digest.lower())


def _deterministic_note_id(relative_path: str) -> str:
    return _sha256_text(f"movenotes\0obsidian\0note\0{relative_path}")[:32]


def _read_bounded(path: Path, maximum: int) -> bytes:
    with path.open("rb") as handle:
        value = handle.read(maximum + 1)
    if len(value) > maximum:
        raise LimitExceeded("source file exceeds limit")
    return value


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(block)
            digest.update(block)
    return digest.hexdigest(), total


def _iter_files(root: Path):
    if root.is_symlink() or not root.is_dir():
        raise C7CError("source root is not a real directory")
    root = root.resolve()
    for base, directories, filenames in os.walk(root, followlinks=False):
        directories.sort()
        for directory in directories:
            if (Path(base) / directory).is_symlink():
                raise C7CError("source tree contains a symlink directory")
        for filename in sorted(filenames):
            path = Path(base) / filename
            if path.is_symlink() or not path.is_file():
                raise C7CError("source tree contains a symlink or special file")
            yield path.relative_to(root).as_posix(), path


def _inventory(root: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    files = 0
    bytes_total = 0
    for relative, path in _iter_files(root):
        file_digest, size = _hash_file(path)
        digest.update(relative.encode("utf-8") + b"\0" + str(size).encode("ascii") + b"\0")
        digest.update(bytes.fromhex(file_digest))
        files += 1
        bytes_total += size
    return {"files": files, "bytes": bytes_total, "sha256": digest.hexdigest()}


def _source_body_after_title(body: str) -> tuple[str, str]:
    title, position, had_ending = _physical_line(body, 0)
    if not had_ending:
        # The pinned Joplin importer uses strings.TrimSpace for the first
        # physical title line before splitting it from the body.
        return _normalize_text(title).strip(), ""
    remainder = body[position:]
    blank, next_position, blank_ending = _physical_line(remainder, 0)
    if blank == "" and blank_ending:
        remainder = remainder[next_position:]
    return _normalize_text(title).strip(), remainder


def _frontmatter_tags(values: dict[str, object], limits: Limits) -> tuple[list[str], str]:
    collected: list[str] = []
    for key in ("tags", "tag"):
        value = values.get(key)
        if value is None:
            continue
        values_to_add = value if isinstance(value, list) else [value]
        for item in values_to_add:
            # The pinned producer parses each list item with its JSON-first
            # scalar helper and stringifies every non-null scalar.  Keep that
            # narrow rule here so numeric and boolean producer tags are not
            # mistaken for unsupported YAML while mappings/sequences remain
            # refused.
            if item is None:
                continue
            if not isinstance(item, (str, int, float, bool)):
                raise C7CError("frontmatter tag is not text")
            collected.append(_normalize_text(str(item)))
            if len(collected) > limits.max_tags:
                raise LimitExceeded("too many tags")
    canonical = sorted(collected)
    return collected, _sha256_text(_canonical_json(canonical))


def _metadata_hash(values: dict[str, object]) -> str:
    metadata = {
        key: value
        for key, value in values.items()
        if key not in {"title", "tag", "tags"}
    }
    return _sha256_text(_canonical_json(_value_normalize(metadata)))


def _parse_raw_source(path: Path, raw: bytes) -> tuple[str, list[tuple[str, str]]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise C7CError("source RAW is not UTF-8") from exc
    try:
        return joplin2sql._split_raw_item(text, path)
    except SystemExit as exc:
        raise C7CError("invalid Joplin RAW property block") from exc


def _parse_source_record(path: Path, raw: bytes, vault_root: Path, prefix: str, limits: Limits) -> dict[str, object] | None:
    if path.suffix.lower() != ".md":
        return None
    body, properties = _parse_raw_source(path, raw)
    app_values = [value for key, value in properties if key.lower() == "application_data"]
    if not app_values:
        return None
    if len(app_values) != 1:
        raise C7CError("duplicate application_data property")
    property_values = dict(properties)
    raw_external_id = str(property_values.get("id") or path.stem)
    try:
        snapshot = _decode_snapshot(app_values[0], limits)
    except _SkipSourceSnapshot:
        return None
    snapshot_path = snapshot.path.as_posix()
    prefix_value = prefix.rstrip("/") + "/"
    if not snapshot_path.startswith(prefix_value):
        return None
    relative = snapshot_path[len(prefix_value):]
    relative_path = _safe_relative(relative)
    if relative_path is None:
        raise C7CError("unsafe declared recipe path")
    source_key = _sha256_text(relative_path.as_posix())
    expected_id = _deterministic_note_id(snapshot_path)
    status: list[str] = []
    if raw_external_id != expected_id:
        status.append("raw_id_deterministic_mismatch")
    source_file = vault_root.joinpath(*relative_path.parts)
    if source_file.is_symlink() or not source_file.is_file():
        status.append("vault_file_missing")
        vault_raw = None
    else:
        resolved_root = vault_root.resolve()
        if not source_file.resolve().is_relative_to(resolved_root):
            raise C7CError("declared recipe path escapes vault root")
        vault_raw = _read_bounded(source_file, limits.max_source_bytes)
        if _sha256_bytes(vault_raw) != snapshot.raw_sha256:
            status.append("snapshot_file_hash_mismatch")
    try:
        snapshot_text = snapshot.raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise C7CError("snapshot is not UTF-8") from exc
    frontmatter, recipe_body = split_frontmatter(snapshot_text)
    pinned_title = ""
    if frontmatter is None:
        values: dict[str, object] = {}
        fm_status = "missing"
        source_recipe_body = snapshot_text
    else:
        pinned_title = _pinned_frontmatter_scalar(frontmatter, "title")
        try:
            values = parse_frontmatter(frontmatter, max_bytes=limits.max_frontmatter_bytes)
            fm_status = "ok"
        except C7CError:
            values = {}
            fm_status = "unsupported"
        source_recipe_body = recipe_body
    source_title, raw_recipe_body = _source_body_after_title(body)
    if _sha256_text(body) != snapshot.joplin_body_sha256:
        status.append("joplin_body_digest_mismatch")
    title_value = values.get("title")
    semantic_title = _normalize_text(title_value) if isinstance(title_value, str) else source_title
    if not semantic_title:
        semantic_title = source_title
    pinned_title = pinned_title or semantic_title
    try:
        _recipe_tags, tags_digest = _frontmatter_tags(values, limits)
    except C7CError:
        tags_digest = None
        status.append("unsupported_tags")
    metadata_digest = _metadata_hash(values) if fm_status == "ok" else None
    if fm_status != "ok":
        status.append("unsupported_frontmatter")
    return {
        "source_key": source_key,
        "raw_external_id": raw_external_id,
        "relative_path": relative_path.as_posix(),
        "title_hash": _sha256_text(semantic_title),
        "pinned_title_hash": _sha256_text(_normalize_text(pinned_title)),
        "raw_title_hash": _sha256_text(source_title),
        # The frozen recipe profile permits one terminal LF in the native
        # snapshot.  This is an explicit source-channel rule, not a generic
        # whitespace trim.
        # Native Obsidian snapshots retain the blank line after the closing
        # YAML fence while both generated producer routes remove it.  The
        # bounded C7a source/route probe proved this route rule over 100 real
        # recipe pairs; keep the exact raw body in ``raw_body_hash``.
        "body_hash": _semantic_body_hash(
            source_recipe_body, drop_leading_lf=True, drop_terminal_lf=True
        ),
        "raw_body_hash": _semantic_body_hash(raw_recipe_body),
        "tags_hash": tags_digest,
        "metadata_hash": metadata_digest,
        "snapshot_hash": snapshot.raw_sha256,
        "vault_hash": _sha256_bytes(vault_raw) if vault_raw is not None else None,
        "status": ",".join(sorted(set(status))) or "ok",
        "frontmatter_status": fm_status,
    }


def _connect_input_database(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise C7CError("producer database is not a regular file")
    connection = sqlite3.connect(path.resolve().as_uri() + "?immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _tag_iterator(connection: sqlite3.Connection):
    cursor = connection.execute(
        "SELECT nt.document_id, t.name FROM note_tags nt "
        "JOIN tags t ON t.id = nt.tag_id ORDER BY nt.document_id, t.name"
    )
    current_id = None
    current: list[str] = []
    for document_id, name in cursor:
        if current_id is not None and document_id != current_id:
            yield current_id, current
            current = []
        current_id = document_id
        current.append(str(name))
    if current_id is not None:
        yield current_id, current


def _tags_hash(values: list[str], limits: Limits) -> tuple[str, int]:
    if len(values) > limits.max_tags:
        raise LimitExceeded("too many route tags")
    normalized = sorted(_normalize_text(value) for value in values)
    return _sha256_text(_canonical_json(normalized)), len(normalized)


def _route_body(
    route: str,
    body: str,
    limits: Limits,
    *,
    expected_path: str | None = None,
) -> dict[str, object]:
    frontmatter, remainder = split_frontmatter(body)
    if frontmatter is None:
        return {
            "body_hash": _semantic_body_hash(
                body,
                drop_leading_lf=route == "vault",
                drop_terminal_lf=route == "raw",
            ),
            "exact_hash": _sha256_text(body),
            "metadata_hash": None,
            "metadata_status": "missing_outer_frontmatter",
            "body_status": "missing_outer_frontmatter",
        }
    try:
        outer = parse_frontmatter(frontmatter, max_bytes=limits.max_frontmatter_bytes)
    except C7CError:
        outer = {}
        outer_status = "unsupported_outer_frontmatter"
    else:
        outer_status = "ok"
    # Frontmatter syntax outside the producer-owned wrapper belongs to the
    # metadata channel.  It must not turn a body into an unexplained body
    # mismatch merely because native YAML is outside the small parser.
    body_status = "ok"
    if route == "raw":
        metadata_hash = None
        metadata_status = "not_projected"
        # Generated RAW bodies retain the same leading blank line as the
        # snapshots, but removing it here yields the shared recipe channel and
        # is harmless because the source rule removes it as well.
        body_rule = {"drop_leading_lf": True, "drop_terminal_lf": True}
    else:
        body_rule = {"drop_leading_lf": True, "drop_terminal_lf": True}
        try:
            if expected_path is None:
                raise C7CError("missing source path for Obsidian wrapper validation")
            inner = _remove_outer_obsidian_fields(frontmatter, expected_path)
        except C7CError:
            metadata_hash = None
            metadata_status = "outer_metadata_mismatch"
            body_status += ";outer_metadata_mismatch"
        else:
            if inner.strip():
                try:
                    inner_values = parse_frontmatter(inner, max_bytes=limits.max_frontmatter_bytes)
                except C7CError:
                    metadata_hash = None
                    metadata_status = "unsupported_inner_frontmatter"
                else:
                    metadata_hash = _metadata_hash(inner_values)
                    metadata_status = "ok"
            else:
                metadata_hash = _metadata_hash({})
                metadata_status = "ok"
    return {
        "body_hash": _semantic_body_hash(remainder, **body_rule),
        "exact_hash": _sha256_text(body),
        "metadata_hash": metadata_hash,
        "metadata_status": metadata_status,
        "body_status": outer_status,
    }


def _route_records(path: Path, route: str, limits: Limits):
    connection = _connect_input_database(path)
    tag_connection = _connect_input_database(path)
    required = {
        "documents", "document_revisions", "document_sources", "note_tags", "tags"
    }
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = required - tables
    if missing:
        raise C7CError("producer database has an incomplete schema")
    tags = iter(_tag_iterator(tag_connection))
    tag_entry = next(tags, None)
    query = (
        "SELECT d.id AS document_id, d.title AS document_title, "
        "r.title AS revision_title, r.body AS body, s.external_id AS external_id, "
        "s.metadata_json AS source_metadata "
        "FROM documents d JOIN document_revisions r ON r.id = d.current_revision_id "
        "JOIN document_sources s ON s.document_id = d.id "
        "WHERE d.deleted_at IS NULL AND s.source_system = ? ORDER BY d.id"
    )
    source_system = "joplin" if route == "raw" else "obsidian"
    try:
        for row in connection.execute(query, (source_system,)):
            document_id = row["document_id"]
            row_tags: list[str] = []
            while tag_entry is not None and tag_entry[0] < document_id:
                tag_entry = next(tags, None)
            while tag_entry is not None and tag_entry[0] == document_id:
                row_tags.extend(tag_entry[1])
                tag_entry = next(tags, None)
            external_id = row["external_id"]
            if not isinstance(external_id, str) or not external_id:
                identity = ""
                identity_status = "missing_external_id"
            else:
                identity = external_id
                identity_status = "ok"
            if route == "vault":
                try:
                    source_metadata = json.loads(row["source_metadata"] or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    source_metadata = {}
                    identity_status = "invalid_source_metadata"
                declared = source_metadata.get("relative_path") if isinstance(source_metadata, dict) else None
                declared_path = _safe_relative(declared)
                if declared_path is None:
                    identity_status = "invalid_relative_path"
                elif identity != declared_path.as_posix():
                    identity_status = "external_id_path_mismatch"
            body = row["body"]
            if not isinstance(body, str):
                body = ""
                body_status = "missing_body"
            else:
                body_status = "ok"
            semantics = _route_body(
                route,
                body,
                limits,
                expected_path=declared_path.as_posix() if route == "vault" and declared_path else None,
            )
            tags_digest, tag_count = _tags_hash(row_tags, limits)
            yield {
                "document_id": str(document_id),
                "identity": identity,
                "identity_status": identity_status,
                "title_hash": _sha256_text(_semantic_title(str(row["revision_title"] or row["document_title"] or ""))),
                "body_hash": semantics["body_hash"],
                "exact_hash": semantics["exact_hash"],
                "tags_hash": tags_digest,
                "tag_count": tag_count,
                "metadata_hash": semantics["metadata_hash"],
                "metadata_status": semantics["metadata_status"],
                "body_status": body_status + ";" + str(semantics["body_status"]),
            }
    finally:
        tag_connection.close()
        connection.close()


def _create_spool(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    if path.exists():
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    connection = sqlite3.connect(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    connection.execute("PRAGMA journal_mode=DELETE")
    existing_meta = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'spool_meta'"
    ).fetchone()
    # An old spool cannot be safely reused after the row-contract changes.
    # The caller's input fingerprint also changes, but fail closed if a stale
    # directory is accidentally paired with a new checkpoint.
    if existing_meta:
        try:
            existing_version = connection.execute(
                "SELECT value FROM spool_meta WHERE name = 'schema_version'"
            ).fetchone()
        except sqlite3.Error:
            existing_version = None
        if existing_version is None or str(existing_version[0]) != str(SPOOL_SCHEMA_VERSION):
            connection.close()
            raise CheckpointMismatch("comparison spool schema changed; use a fresh output directory")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS source_records ("
        "run_id TEXT, source_key TEXT, raw_external_id TEXT, relative_path TEXT, "
        "title_hash TEXT, pinned_title_hash TEXT, raw_title_hash TEXT, body_hash TEXT, raw_body_hash TEXT, "
        "tags_hash TEXT, metadata_hash TEXT, snapshot_hash TEXT, vault_hash TEXT, "
        "status TEXT, frontmatter_status TEXT)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS route_records ("
        "run_id TEXT, route TEXT, document_id TEXT, identity TEXT, identity_status TEXT, title_hash TEXT, "
        "body_hash TEXT, exact_hash TEXT, tags_hash TEXT, tag_count INTEGER, "
        "metadata_hash TEXT, metadata_status TEXT, body_status TEXT)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS publication_records ("
        "run_id TEXT NOT NULL, label TEXT NOT NULL, document_id TEXT NOT NULL, "
        "title_hash TEXT NOT NULL, body_hash TEXT NOT NULL, producer_match INTEGER NOT NULL, "
        "PRIMARY KEY(run_id, label, document_id))"
    )
    # Keep the independently verified archive cohort in the private spool.
    # Publication bodies can be transformed by link privacy rules, so a
    # producer link target must be checked against the reviewed archive's
    # document/resource membership rather than producer import metadata.
    connection.execute(
        "CREATE TABLE IF NOT EXISTS publication_cohort ("
        "run_id TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL, "
        "record_id TEXT NOT NULL, PRIMARY KEY(run_id, label, kind, record_id))"
    )
    connection.execute("CREATE TABLE IF NOT EXISTS spool_meta (name TEXT PRIMARY KEY, value TEXT)")
    connection.execute(
        "INSERT INTO spool_meta(name, value) VALUES('schema_version', ?) "
        "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
        (str(SPOOL_SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


def _index_spool(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE INDEX IF NOT EXISTS source_raw_idx ON source_records(run_id, raw_external_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS source_path_idx ON source_records(run_id, relative_path)")
    connection.execute("CREATE INDEX IF NOT EXISTS route_identity_idx ON route_records(run_id, route, identity)")
    # Publication joins start from the archived document ID and then resolve
    # the route identity.  Keep that lookup covered instead of scanning every
    # route row for a route before filtering the identity.
    connection.execute(
        "CREATE INDEX IF NOT EXISTS route_publication_doc_idx "
        "ON route_records(run_id, route, document_id, identity)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS route_fields_idx ON route_records(run_id, route, identity, title_hash, body_hash, tags_hash, metadata_hash)")
    # Field-group comparisons use one value at a time.  Keep each grouping
    # covered by an index so SQLite does not repeatedly build a large
    # temporary B-tree for a full-library comparison.
    for field in ("title_hash", "body_hash", "tags_hash", "metadata_hash"):
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS source_raw_{field}_idx "
            f"ON source_records(run_id, raw_external_id, {field})"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS source_path_{field}_idx "
            f"ON source_records(run_id, relative_path, {field})"
        )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS route_{field}_idx "
            f"ON route_records(run_id, route, identity, {field})"
        )
    connection.commit()


def _materialize_route_identity_map(
    connection: sqlite3.Connection,
    source_run: str,
    raw_run: str,
    vault_run: str,
) -> None:
    """Materialize only one-to-one source/route identities for cross-route joins.

    A duplicate source or producer identity is ambiguous.  Joining it directly
    to the other route multiplies rows and can manufacture apparent matches,
    so such groups are deliberately excluded from the map and counted by the
    comparison report.
    """

    connection.execute("DROP TABLE IF EXISTS route_identity_map")
    connection.execute(
        "CREATE TABLE route_identity_map ("
        "source_key TEXT NOT NULL, route TEXT NOT NULL, source_identity TEXT NOT NULL, "
        "route_identity TEXT NOT NULL, PRIMARY KEY(source_key, route))"
    )
    temporary_tables = (
        "c7c_source_raw_identity_groups", "c7c_raw_route_identity_groups",
        "c7c_source_vault_identity_groups", "c7c_vault_route_identity_groups",
    )
    _drop_temp_tables(connection, *temporary_tables)
    try:
        for source_table, route_table, source_column, route, route_run in (
            (
                temporary_tables[0], temporary_tables[1],
                "raw_external_id", "raw", raw_run,
            ),
            (
                temporary_tables[2], temporary_tables[3],
                "relative_path", "vault", vault_run,
            ),
        ):
            connection.execute(
                f"CREATE TEMP TABLE {source_table} ("
                "source_key TEXT NOT NULL, identity TEXT NOT NULL, n INTEGER NOT NULL, "
                "PRIMARY KEY(source_key,identity)) WITHOUT ROWID"
            )
            connection.execute(
                f"INSERT INTO {source_table}(source_key,identity,n) "
                f"SELECT source_key,{source_column},COUNT(*) FROM source_records "
                f"WHERE run_id=? AND source_key IS NOT NULL AND {source_column} IS NOT NULL "
                f"GROUP BY source_key,{source_column}",
                (source_run,),
            )
            connection.execute(
                f"CREATE TEMP TABLE {route_table} ("
                "identity TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID"
            )
            connection.execute(
                f"INSERT INTO {route_table}(identity,n) "
                "SELECT identity,COUNT(*) FROM route_records "
                "WHERE run_id=? AND route=? AND identity IS NOT NULL GROUP BY identity",
                (route_run, route),
            )
            connection.execute(
                "INSERT INTO route_identity_map(source_key,route,source_identity,route_identity) "
                f"SELECT s.source_key,?,s.identity,r.identity FROM {source_table} s "
                f"JOIN {route_table} r ON r.identity=s.identity "
                "WHERE s.n=1 AND r.n=1",
                (route,),
            )
    finally:
        _drop_temp_tables(connection, *temporary_tables)
    connection.execute(
        "CREATE INDEX route_identity_map_route ON route_identity_map(route, source_key)"
    )
    connection.execute(
        "CREATE INDEX route_identity_map_route_identity "
        "ON route_identity_map(route, route_identity, source_key)"
    )
    connection.commit()


def _scan_source(connection: sqlite3.Connection, run_id: str, raw_root: Path, vault_root: Path, prefix: str, limits: Limits) -> dict[str, object]:
    counts = Counter()
    insert_sql = (
        "INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    batch: list[tuple[object, ...]] = []
    for relative_file, path in _iter_files(raw_root):
        counts["source_files"] += 1
        try:
            raw = _read_bounded(path, limits.max_source_bytes)
            record = _parse_source_record(path, raw, vault_root, prefix, limits)
        except C7CError:
            counts["source_parse_failures"] += 1
            continue
        if record is None:
            counts["source_without_snapshot"] += 1
            continue
        counts["source_snapshots"] += 1
        counts["source_status_" + str(record["status"])] += 1
        if record["status"] != "ok":
            counts["source_record_failures"] += 1
        batch.append(
            (
                run_id, record["source_key"], record["raw_external_id"], record["relative_path"],
                record["title_hash"], record["pinned_title_hash"], record["raw_title_hash"],
                record["body_hash"], record["raw_body_hash"],
                record["tags_hash"], record["metadata_hash"], record["snapshot_hash"], record["vault_hash"],
                record["status"], record["frontmatter_status"],
            )
        )
        if len(batch) >= 1000:
            connection.executemany(insert_sql, batch)
            connection.commit()
            batch.clear()
    if batch:
        connection.executemany(insert_sql, batch)
        connection.commit()
    result = dict(sorted(counts.items()))
    connection.execute(
        "INSERT INTO spool_meta(name, value) VALUES(?, ?) "
        "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
        ("source_scan:" + run_id, _canonical_json(result)),
    )
    connection.commit()
    return result


def _scan_route(connection: sqlite3.Connection, run_id: str, route: str, path: Path, limits: Limits) -> dict[str, object]:
    counts = Counter()
    batch: list[tuple[object, ...]] = []
    insert_sql = "INSERT INTO route_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
    for record in _route_records(path, route, limits):
        counts["documents"] += 1
        counts["tag_associations"] += int(record["tag_count"])
        if record["identity_status"] != "ok":
            counts["identity_status_" + str(record["identity_status"])] += 1
        batch.append(
            (
                run_id, route, record["document_id"], record["identity"], record["identity_status"], record["title_hash"],
                record["body_hash"], record["exact_hash"], record["tags_hash"], record["tag_count"],
                record["metadata_hash"], record["metadata_status"], record["body_status"],
            )
        )
        if len(batch) >= 1000:
            connection.executemany(insert_sql, batch)
            connection.commit()
            batch.clear()
    if batch:
        connection.executemany(insert_sql, batch)
        connection.commit()
    return dict(sorted(counts.items()))


_COMPARISON_FIELDS = frozenset({
    "title_hash", "body_hash", "tags_hash", "metadata_hash",
})
_NULL_FIELD_SENTINEL = "!c7c-null!"


def _checked_comparison_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    if not fields or any(field not in _COMPARISON_FIELDS for field in fields):
        raise C7CError("comparison field is not allowed")
    if len(set(fields)) != len(fields):
        raise C7CError("comparison fields must be unique")
    return fields


def _row_key_expression(alias: str, fields: tuple[str, ...]) -> str:
    _checked_comparison_fields(fields)
    # These are SHA-256 hex strings or NULL, so the sentinel and separator
    # cannot collide with a stored value.  Encoding NULL explicitly preserves
    # the original SQL ``IS`` semantics for duplicate-sensitive comparisons.
    return " || '|' || ".join(
        f"COALESCE({alias}.{field}, '{_NULL_FIELD_SENTINEL}')"
        for field in fields
    )


def _drop_temp_tables(connection: sqlite3.Connection, *names: str) -> None:
    for name in names:
        try:
            connection.execute(f"DROP TABLE IF EXISTS {name}")
        except sqlite3.Error:
            # Cleanup must not replace the original bounded-query failure.
            pass


def _distinct_missing_extra(
    connection: sqlite3.Connection,
    source_run: str,
    route_run: str,
    route: str,
    source_identity: str,
) -> dict[str, int]:
    """Compare identity sets through indexed temporary primary-key tables.

    SQLite materializes ``SELECT DISTINCT`` CTEs without an identity index in
    the old implementation.  The anti-joins then became nested scans on the
    full source and route cohorts.  These temporary WITHOUT ROWID tables make
    the identity lookup explicit and keep the anti-joins O(n log n).
    """

    if source_identity not in {"raw_external_id", "relative_path"}:
        raise C7CError("source identity is not allowed")
    if route not in {"raw", "vault"}:
        raise C7CError("route is not allowed")
    source_table = "c7c_source_identity_set"
    route_table = "c7c_route_identity_set"
    _drop_temp_tables(connection, source_table, route_table)
    try:
        connection.execute(
            f"CREATE TEMP TABLE {source_table} ("
            "identity_key TEXT NOT NULL, is_null INTEGER NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(is_null,identity_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {source_table}(identity_key,is_null,n) "
            f"SELECT COALESCE({source_identity},''), "
            f"CASE WHEN {source_identity} IS NULL THEN 1 ELSE 0 END, COUNT(*) "
            f"FROM source_records WHERE run_id = ? GROUP BY {source_identity}",
            (source_run,),
        )
        connection.execute(
            f"CREATE TEMP TABLE {route_table} ("
            "identity_key TEXT NOT NULL, is_null INTEGER NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(is_null,identity_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {route_table}(identity_key,is_null,n) "
            "SELECT COALESCE(identity,''), CASE WHEN identity IS NULL THEN 1 ELSE 0 END, COUNT(*) "
            "FROM route_records WHERE run_id = ? AND route = ? GROUP BY identity",
            (route_run, route),
        )
        source_count, source_unique, source_duplicate_rows = connection.execute(
            f"SELECT COALESCE(SUM(n),0), COUNT(*), "
            f"COALESCE(SUM(CASE WHEN n > 1 THEN n - 1 ELSE 0 END),0) "
            f"FROM {source_table}"
        ).fetchone()
        route_count, route_unique, route_duplicate_rows = connection.execute(
            f"SELECT COALESCE(SUM(n),0), COUNT(*), "
            f"COALESCE(SUM(CASE WHEN n > 1 THEN n - 1 ELSE 0 END),0) "
            f"FROM {route_table}"
        ).fetchone()
        missing = connection.execute(
            f"SELECT COUNT(*) FROM {source_table} s "
            f"WHERE s.is_null=1 OR NOT EXISTS (SELECT 1 FROM {route_table} r "
            "WHERE r.is_null=0 AND s.is_null=0 AND r.identity_key = s.identity_key)"
        ).fetchone()[0]
        extra = connection.execute(
            f"SELECT COUNT(*) FROM {route_table} r "
            f"WHERE r.is_null=1 OR NOT EXISTS (SELECT 1 FROM {source_table} s "
            "WHERE s.is_null=0 AND r.is_null=0 AND s.identity_key = r.identity_key)"
        ).fetchone()[0]
        return {
            "source_rows": int(source_count or 0),
            "source_identities": int(source_unique or 0),
            "source_duplicate_rows": int(source_duplicate_rows or 0),
            "route_rows": int(route_count or 0),
            "route_identities": int(route_unique or 0),
            "route_duplicate_rows": int(route_duplicate_rows or 0),
            "missing_identities": int(missing or 0),
            "extra_identities": int(extra or 0),
        }
    finally:
        _drop_temp_tables(connection, source_table, route_table)


def _field_matches(
    connection: sqlite3.Connection,
    source_run: str,
    route_run: str,
    route: str,
    source_identity: str,
    source_field: str,
    route_field: str,
    *,
    comparable_only: bool = False,
) -> int:
    """Count field matches through indexed grouped rows.

    Null values never matched in the former ``r.value = s.value`` join, so
    they are omitted while materializing the groups.  Each temporary table has
    a real primary key on ``(identity,value)``; no automatic index or CTE
    materialization is trusted for the full-library join.
    """

    if source_identity not in {"raw_external_id", "relative_path"}:
        raise C7CError("source identity is not allowed")
    if source_field not in _COMPARISON_FIELDS or route_field not in _COMPARISON_FIELDS:
        raise C7CError("comparison field is not allowed")
    source_table = "c7c_source_field_groups"
    route_table = "c7c_route_field_groups"
    _drop_temp_tables(connection, source_table, route_table)
    try:
        connection.execute(
            f"CREATE TEMP TABLE {source_table} ("
            "identity TEXT NOT NULL, value_key TEXT NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(identity,value_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {source_table}(identity,value_key,n) "
            f"SELECT {source_identity}, {source_field}, COUNT(*) FROM source_records "
            f"WHERE run_id = ? AND {source_identity} IS NOT NULL AND {source_field} IS NOT NULL "
            f"GROUP BY {source_identity}, {source_field}",
            (source_run,),
        )
        connection.execute(
            f"CREATE TEMP TABLE {route_table} ("
            "identity TEXT NOT NULL, value_key TEXT NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(identity,value_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {route_table}(identity,value_key,n) "
            f"SELECT identity, {route_field}, COUNT(*) FROM route_records "
            f"WHERE run_id = ? AND route = ? AND identity IS NOT NULL AND {route_field} IS NOT NULL "
            f"GROUP BY identity, {route_field}",
            (route_run, route),
        )
        return int(connection.execute(
            f"SELECT COALESCE(SUM(CASE WHEN s.n < r.n THEN s.n ELSE r.n END),0) "
            f"FROM {source_table} s JOIN {route_table} r "
            "ON r.identity = s.identity AND r.value_key = s.value_key"
        ).fetchone()[0] or 0)
    finally:
        _drop_temp_tables(connection, source_table, route_table)


def _source_field_matches(connection: sqlite3.Connection, source_run: str, field_a: str, field_b: str) -> int:
    return int(connection.execute(
        f"SELECT COUNT(*) FROM source_records WHERE run_id = ? AND {field_a} IS NOT NULL AND {field_a} = {field_b}",
        (source_run,),
    ).fetchone()[0])


def _title_rule_matches(
    connection: sqlite3.Connection,
    source_run: str,
    route_run: str,
    route: str,
    source_identity: str,
) -> int:
    """Count title mismatches explained by pinned ``frontmatterScalar``."""

    if source_identity not in {"raw_external_id", "relative_path"}:
        raise C7CError("source identity is not allowed")
    source_table = "c7c_source_title_groups"
    route_table = "c7c_route_title_groups"
    _drop_temp_tables(connection, source_table, route_table)
    try:
        connection.execute(
            f"CREATE TEMP TABLE {source_table} ("
            "identity TEXT NOT NULL, title_key TEXT NOT NULL, pinned_key TEXT NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(identity,title_key,pinned_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {source_table}(identity,title_key,pinned_key,n) "
            f"SELECT {source_identity}, title_hash, pinned_title_hash, COUNT(*) "
            "FROM source_records WHERE run_id = ? AND " + source_identity + " IS NOT NULL "
            "AND title_hash IS NOT NULL AND pinned_title_hash IS NOT NULL "
            f"GROUP BY {source_identity}, title_hash, pinned_title_hash",
            (source_run,),
        )
        connection.execute(
            f"CREATE TEMP TABLE {route_table} ("
            "identity TEXT NOT NULL, title_key TEXT NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(identity,title_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {route_table}(identity,title_key,n) "
            f"SELECT identity, title_hash, COUNT(*) FROM route_records "
            "WHERE run_id = ? AND route = ? AND identity IS NOT NULL AND title_hash IS NOT NULL "
            "GROUP BY identity, title_hash",
            (route_run, route),
        )
        return int(connection.execute(
            f"SELECT COALESCE(SUM(CASE WHEN s.n = 1 AND r.n = 1 THEN 1 ELSE 0 END),0) "
            f"FROM {source_table} s JOIN {route_table} r "
            "ON r.identity = s.identity AND r.title_key = s.pinned_key "
            "WHERE s.title_key != r.title_key"
        ).fetchone()[0] or 0)
    finally:
        _drop_temp_tables(connection, source_table, route_table)


def _row_multiset_matches(
    connection: sqlite3.Connection,
    source_run: str,
    route_run: str,
    route: str,
    source_identity: str,
    fields: tuple[str, ...],
) -> int:
    """Count complete duplicate-sensitive rows matched by identity and fields."""

    if source_identity not in {"raw_external_id", "relative_path"}:
        raise C7CError("source identity is not allowed")
    fields = _checked_comparison_fields(fields)
    source_table = "c7c_source_row_groups"
    route_table = "c7c_route_row_groups"
    source_key = _row_key_expression("s", fields)
    route_key = _row_key_expression("r", fields)
    _drop_temp_tables(connection, source_table, route_table)
    try:
        connection.execute(
            f"CREATE TEMP TABLE {source_table} ("
            "identity TEXT NOT NULL, row_key TEXT NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(identity,row_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {source_table}(identity,row_key,n) "
            f"SELECT s.{source_identity}, {source_key}, COUNT(*) FROM source_records s "
            f"WHERE s.run_id = ? AND s.{source_identity} IS NOT NULL "
            f"GROUP BY s.{source_identity}, {source_key}",
            (source_run,),
        )
        connection.execute(
            f"CREATE TEMP TABLE {route_table} ("
            "identity TEXT NOT NULL, row_key TEXT NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(identity,row_key)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {route_table}(identity,row_key,n) "
            f"SELECT r.identity, {route_key}, COUNT(*) FROM route_records r "
            f"WHERE r.run_id = ? AND r.route = ? AND r.identity IS NOT NULL "
            f"GROUP BY r.identity, {route_key}",
            (route_run, route),
        )
        return int(connection.execute(
            f"SELECT COALESCE(SUM(CASE WHEN s.n < r.n THEN s.n ELSE r.n END),0) "
            f"FROM {source_table} s JOIN {route_table} r "
            "ON r.identity = s.identity AND r.row_key = s.row_key"
        ).fetchone()[0] or 0)
    finally:
        _drop_temp_tables(connection, source_table, route_table)


def _route_pair_multiset_matches(
    connection: sqlite3.Connection,
    source_run: str,
    raw_run: str,
    vault_run: str,
    fields: tuple[str, ...],
) -> int:
    return _route_pair_multiset_summary(
        connection, source_run, raw_run, vault_run, fields
    )["matches"]


def _ambiguous_source_route_groups(
    connection: sqlite3.Connection,
    source_run: str,
    route_run: str,
    route: str,
    source_identity: str,
) -> int:
    """Count source keys whose source/route identity pairing is ambiguous.

    The grouped tables have primary-key lookups for route identities.  The
    aggregate deliberately counts duplicate source rows and duplicate route
    rows, preserving the old fail-closed meaning without a many-to-many join.
    """

    if route not in {"raw", "vault"}:
        raise C7CError("route is not allowed")
    if source_identity not in {"raw_external_id", "relative_path"}:
        raise C7CError("source identity is not allowed")
    source_table = f"c7c_{route}_pair_source_groups"
    route_table = f"c7c_{route}_pair_route_groups"
    _drop_temp_tables(connection, source_table, route_table)
    try:
        connection.execute(
            f"CREATE TEMP TABLE {source_table} ("
            "source_key TEXT NOT NULL, identity TEXT NOT NULL, n INTEGER NOT NULL, "
            "PRIMARY KEY(source_key,identity)) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {source_table}(source_key,identity,n) "
            f"SELECT source_key, {source_identity}, COUNT(*) FROM source_records "
            f"WHERE run_id = ? AND source_key IS NOT NULL AND {source_identity} IS NOT NULL "
            f"GROUP BY source_key, {source_identity}",
            (source_run,),
        )
        connection.execute(
            f"CREATE TEMP TABLE {route_table} ("
            "identity TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID"
        )
        connection.execute(
            f"INSERT INTO {route_table}(identity,n) "
            "SELECT identity, COUNT(*) FROM route_records "
            "WHERE run_id = ? AND route = ? AND identity IS NOT NULL "
            "GROUP BY identity",
            (route_run, route),
        )
        return int(connection.execute(
            f"SELECT COUNT(*) FROM ("
            f"SELECT s.source_key FROM {source_table} s "
            f"LEFT JOIN {route_table} r ON r.identity = s.identity "
            "GROUP BY s.source_key "
            "HAVING COALESCE(SUM(s.n),0) != 1 "
            "OR COALESCE(SUM(s.n * COALESCE(r.n,0)),0) != 1)"
        ).fetchone()[0] or 0)
    finally:
        _drop_temp_tables(connection, source_table, route_table)


def _route_pair_multiset_summary(
    connection: sqlite3.Connection,
    source_run: str,
    raw_run: str,
    vault_run: str,
    fields: tuple[str, ...],
) -> dict[str, int]:
    """Compare route rows through the one-to-one identity map.

    ``route_identity_map`` is materialized before this query.  This keeps the
    query linear in the grouped rows and makes duplicate identities visible as
    an explicit fail-closed count instead of allowing a many-to-many join.
    """

    fields = _checked_comparison_fields(fields)
    raw_table = "c7c_raw_route_row_groups"
    vault_table = "c7c_vault_route_row_groups"
    raw_key = _row_key_expression("rr", fields)
    vault_key = _row_key_expression("vv", fields)
    _drop_temp_tables(connection, raw_table, vault_table)
    try:
        for table, run_id, route, alias, expression in (
            (raw_table, raw_run, "raw", "rr", raw_key),
            (vault_table, vault_run, "vault", "vv", vault_key),
        ):
            connection.execute(
                f"CREATE TEMP TABLE {table} ("
                "source_key TEXT NOT NULL, row_key TEXT NOT NULL, n INTEGER NOT NULL, "
                "PRIMARY KEY(source_key,row_key)) WITHOUT ROWID"
            )
            connection.execute(
                f"INSERT INTO {table}(source_key,row_key,n) "
                f"SELECT m.source_key, {expression}, COUNT(*) "
                f"FROM route_identity_map m JOIN route_records {alias} "
                f"ON {alias}.run_id = ? AND {alias}.route = ? "
                f"AND {alias}.identity = m.route_identity "
                f"WHERE m.route = ? GROUP BY m.source_key, {expression}",
                (run_id, route, route),
            )
        matches = int(connection.execute(
            f"SELECT COALESCE(SUM(CASE WHEN r.n < v.n THEN r.n ELSE v.n END),0) "
            f"FROM {raw_table} r JOIN {vault_table} v "
            "ON v.source_key = r.source_key AND v.row_key = r.row_key"
        ).fetchone()[0] or 0)
        raw_ambiguous = _ambiguous_source_route_groups(
            connection, source_run, raw_run, "raw", "raw_external_id"
        )
        vault_ambiguous = _ambiguous_source_route_groups(
            connection, source_run, vault_run, "vault", "relative_path"
        )
        return {"matches": matches, "ambiguous_groups": max(raw_ambiguous, vault_ambiguous)}
    finally:
        _drop_temp_tables(connection, raw_table, vault_table)


def _producer_import_summary(path: Path, route: str) -> dict[str, object]:
    """Read producer import metadata as diagnostics, never archive evidence."""

    connection = _connect_input_database(path)
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "import_checkpoints" not in tables:
            return {"status": "unavailable", "rows": 0, "cohorts": []}
        rows = []
        for row in connection.execute(
            "SELECT source_system, collection_id, inventory_fingerprint, total_items, "
            "processed_items, status FROM import_checkpoints ORDER BY source_system, collection_id"
        ):
            source_system, collection_id, digest, total, processed, status = row
            if not all(isinstance(value, str) for value in (source_system, collection_id, digest, status)):
                return {"status": "invalid", "rows": 0, "cohorts": []}
            rows.append({
                "source_system": source_system,
                "collection_id": collection_id,
                "inventory_sha256": digest,
                "total_items": int(total),
                "processed_items": int(processed),
                "status": status,
            })
        ready = bool(rows) and all(
            row["status"] == "completed" and row["processed_items"] == row["total_items"]
            for row in rows
        )
        return {"status": "complete" if ready else "incomplete", "rows": len(rows), "cohorts": rows}
    finally:
        connection.close()


def _blob_sha256(archive: notrios_archive.VerifiedArchive, ref_value: object) -> str:
    """Consume a verified publication blob in bounded chunks."""

    if not isinstance(ref_value, dict):
        # ``Record`` payloads are immutable mapping proxies.  Mapping is
        # intentionally checked by the archive API; this branch only keeps a
        # malformed test double fail closed.
        try:
            ref_value = dict(ref_value)
        except (TypeError, ValueError) as exc:
            raise C7CError("publication body reference is invalid") from exc
    try:
        ref = notrios_archive.BlobRef(
            sha256=str(ref_value["sha256"]),
            size_bytes=int(ref_value["size_bytes"]),
            media_type=str(ref_value["media_type"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise C7CError("publication body reference is invalid") from exc
    digest = hashlib.sha256()
    with archive.open_blob(ref) as blob:
        while True:
            chunk = blob.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _privacy_plain_text_projection(
    source_body: bytes,
    link_rows: list[tuple[object, ...]],
    target_included,
) -> tuple[bytes, dict[str, int]]:
    """Apply Notrios' verified ``plain_text`` link projection to source bytes.

    ``document_links`` offsets are byte offsets, just like Go's string slice
    coordinates.  The helper validates span identity before replacing it,
    applies later spans first, and reports skipped candidates instead of
    cutting arbitrary source bytes.  It accepts a target-membership callback
    so callers can use a verified archive cohort without copying archive IDs
    into process memory.
    """

    rewrites: list[tuple[int, int, bytes]] = []
    counts = Counter()
    for row in link_rows:
        # source_document_id, target_document_id, target_resource_id,
        # target_uri, resolution_status, relation_type, raw_target,
        # display_text, source_start_byte, source_end_byte
        target_document = str(row[1] or "")
        target_resource = str(row[2] or "")
        status = str(row[4] or "").strip().lower()
        if status == "external":
            continue
        if status == "resolved":
            if target_document:
                needs_rewrite = not bool(target_included("document", target_document))
            elif target_resource:
                needs_rewrite = not bool(target_included("resource", target_resource))
            else:
                # A resolved link with no target is a self-anchor.
                needs_rewrite = False
        else:
            # unresolved, ambiguous, invalid and target_deleted links are
            # rewritten for a reader of the publication.
            needs_rewrite = True
        if not needs_rewrite:
            continue
        counts["candidates"] += 1
        try:
            start = int(row[8])
            end = int(row[9])
        except (TypeError, ValueError):
            counts["invalid_span"] += 1
            continue
        if start < 0 or end <= start or end > len(source_body):
            counts["invalid_span"] += 1
            continue
        span = source_body[start:end]
        if not span.startswith((b"[", b"![")):
            counts["stale_span"] += 1
            continue
        raw_target = str(row[6] or "").encode("utf-8")
        display_text = str(row[7] or "")
        if raw_target:
            if raw_target not in span:
                counts["stale_span"] += 1
                continue
        elif display_text and display_text not in span.decode("utf-8", errors="replace"):
            counts["stale_span"] += 1
            continue
        replacement = (
            display_text.encode("utf-8")
            if display_text.strip()
            else b"[redacted]"
        )
        rewrites.append((start, end, replacement))
    rewrites.sort(key=lambda item: item[0], reverse=True)
    output = source_body
    previous_start = len(source_body) + 1
    for start, end, replacement in rewrites:
        if end > previous_start:
            counts["overlapping_span"] += 1
            continue
        output = output[:start] + replacement + output[end:]
        previous_start = start
        counts["rewrites"] += 1
    return output, dict(sorted(counts.items()))


def _verified_publication_summary(
    connection: sqlite3.Connection,
    run_id: str,
    label: str,
    path: Path,
    producer_path: Path | None,
    work_dir: Path,
) -> dict[str, object]:
    """Verify one actual Notrios archive and spool aggregate-safe joins.

    The verifier is the admission boundary.  Producer ``import_checkpoints``
    are deliberately kept separate because they describe an import process,
    not the bytes and records in a reviewed publication archive.
    """

    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", label):
        return {"status": "invalid", "label": label, "reason": "invalid_label"}
    if path.is_symlink() or not path.is_dir():
        return {"status": "invalid", "label": label, "reason": "archive_unavailable"}
    work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(work_dir, 0o700)
    except OSError:
        pass
    producer = None
    producer_match = 0
    producer_title_match = 0
    producer_body_match = 0
    privacy_plain_text_match = 0
    privacy_plain_text_unexplained = 0
    privacy_plain_text_counts = Counter()
    privacy_link_rows = 0
    document_rows = 0
    revision_rows = 0
    body_rows = 0
    resource_rows = 0
    producer_links_available = False
    try:
        if producer_path is not None:
            producer = _connect_input_database(producer_path)
            producer_links_available = producer.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_links'"
            ).fetchone() is not None
        connection.execute(
            "DELETE FROM publication_records WHERE run_id = ? AND label = ?",
            (run_id, label),
        )
        connection.execute(
            "DELETE FROM publication_cohort WHERE run_id = ? AND label = ?",
            (run_id, label),
        )
        with notrios_archive.verify_archive(path, work_dir=work_dir) as archive:
            counts = {str(key): int(value) for key, value in archive.counts.items()}
            cohort_insert = (
                "INSERT INTO publication_cohort(run_id,label,kind,record_id) "
                "VALUES (?,?,?,?)"
            )
            cohort_batch: list[tuple[object, ...]] = []
            for resource in archive.iter_records("resource"):
                cohort_batch.append((run_id, label, "resource", str(resource.payload["id"])))
                resource_rows += 1
                if len(cohort_batch) >= 512:
                    connection.executemany(cohort_insert, cohort_batch)
                    connection.commit()
                    cohort_batch.clear()
            if cohort_batch:
                connection.executemany(cohort_insert, cohort_batch)
                connection.commit()
                cohort_batch.clear()
            # Populate the complete document cohort before reading any body.
            # A link may point forward to a document whose record appears
            # later in archive order; checking membership during the same pass
            # would otherwise misclassify that retained link as withheld.
            for document in archive.iter_records("document"):
                cohort_batch.append((run_id, label, "document", str(document.payload["id"])))
                if len(cohort_batch) >= 512:
                    connection.executemany(cohort_insert, cohort_batch)
                    connection.commit()
                    cohort_batch.clear()
            if cohort_batch:
                connection.executemany(cohort_insert, cohort_batch)
                connection.commit()
                cohort_batch.clear()
            insert = (
                "INSERT INTO publication_records "
                "(run_id,label,document_id,title_hash,body_hash,producer_match) "
                "VALUES (?,?,?,?,?,?)"
            )
            batch: list[tuple[object, ...]] = []
            for document in archive.iter_records("document"):
                document_id = str(document.payload["id"])
                revision_id = str(document.payload["current_revision_id"])
                revision = archive.get_record("revision", (revision_id,))
                title_hash = _sha256_text(str(revision.payload["title"]))
                body_hash = _blob_sha256(archive, revision.payload["body"])
                body_rows += 1
                if producer is None:
                    matched = 0
                    title_matched = 0
                    body_matched = 0
                else:
                    producer_row = producer.execute(
                        """SELECT r.title, r.body FROM documents d
                           JOIN document_revisions r ON r.id = d.current_revision_id
                           WHERE d.id = ? AND d.deleted_at IS NULL LIMIT 1""",
                        (document_id,),
                    ).fetchone()
                    matched = int(producer_row is not None)
                    title_matched = int(
                        matched and str(producer_row[0] or "") == str(revision.payload["title"])
                    )
                    producer_body = str(producer_row[1] or "").encode("utf-8") if matched else b""
                    body_matched = int(
                        matched and hashlib.sha256(producer_body).hexdigest() == body_hash
                    )
                    if matched and not body_matched and producer_links_available:
                            link_rows = producer.execute(
                                "SELECT source_document_id,target_document_id,target_resource_id,"
                                "target_uri,resolution_status,relation_type,raw_target,display_text,"
                                "source_start_byte,source_end_byte "
                                "FROM document_links WHERE source_document_id=? "
                                "ORDER BY source_start_byte,id",
                                (document_id,),
                            ).fetchall()
                            privacy_link_rows += len(link_rows)
                            projected, privacy_counts = _privacy_plain_text_projection(
                                producer_body,
                                link_rows,
                                lambda kind, record_id: connection.execute(
                                    "SELECT 1 FROM publication_cohort "
                                    "WHERE run_id=? AND label=? AND kind=? AND record_id=?",
                                    (run_id, label, kind, record_id),
                                ).fetchone() is not None,
                            )
                            privacy_plain_text_counts.update(privacy_counts)
                            transformed_match = int(
                                privacy_counts.get("rewrites", 0) > 0
                                and hashlib.sha256(projected).hexdigest() == body_hash
                            )
                            privacy_plain_text_match += transformed_match
                            if not transformed_match:
                                privacy_plain_text_unexplained += 1
                producer_match += matched
                producer_title_match += title_matched
                producer_body_match += body_matched
                batch.append((run_id, label, document_id, title_hash, body_hash, matched))
                document_rows += 1
                if len(batch) >= 512:
                    connection.executemany(insert, batch)
                    connection.commit()
                    batch.clear()
            if batch:
                connection.executemany(insert, batch)
                connection.commit()
            revision_rows = counts.get("revisions", 0)
            snapshot = archive.manifest.snapshot
            return {
                "status": "complete",
                "label": label,
                "manifest": {
                    "commit_sha256": archive.manifest.commit_sha256,
                    "selection_manifest_sha256": str(snapshot["selection_manifest_sha256"]),
                    "collection_count": len(tuple(snapshot["collection_ids"])),
                },
                "counts": counts,
                "document_rows": document_rows,
                "revision_rows": revision_rows,
                "body_rows_verified": body_rows,
                "resource_rows_verified": resource_rows,
                "producer_document_matches": producer_match,
                "producer_title_matches": producer_title_match,
                "producer_body_matches": producer_body_match,
                "producer_body_privacy_plain_text_matches": privacy_plain_text_match,
                "producer_body_privacy_plain_text_unexplained": privacy_plain_text_unexplained,
                "producer_body_equivalent_matches": producer_body_match + privacy_plain_text_match,
                "privacy_plain_text": {
                    "status": "verified" if producer_links_available else "unavailable",
                    "classification_counts": {
                        "exact": producer_body_match,
                        "privacy_plain_text_exact": privacy_plain_text_match,
                        "unexplained": privacy_plain_text_unexplained,
                    },
                    "link_rows": privacy_link_rows,
                    "transform_counts": dict(sorted(privacy_plain_text_counts.items())),
                    "rules_source": "Notrios internal/archivev2/publish.go: publicationLinkNeedsRewrite plus replacementFor(plain_text), with verified archive cohort and producer byte spans",
                },
                "producer_content_ready": bool(
                    producer_path is not None
                    and producer_match == document_rows
                    and producer_title_match == document_rows
                    and producer_body_match == document_rows
                ),
                "producer_equivalence_ready": bool(
                    producer_path is not None
                    and producer_match == document_rows
                    and producer_title_match == document_rows
                    and producer_body_match + privacy_plain_text_match == document_rows
                ),
            }
    except (OSError, sqlite3.Error, notrios_archive.NotriosError, C7CError) as exc:
        connection.execute(
            "DELETE FROM publication_records WHERE run_id = ? AND label = ?",
            (run_id, label),
        )
        connection.execute(
            "DELETE FROM publication_cohort WHERE run_id = ? AND label = ?",
            (run_id, label),
        )
        connection.commit()
        return {
            "status": "invalid",
            "label": label,
            "reason": type(exc).__name__,
            "document_rows": document_rows,
            "revision_rows": revision_rows,
            "body_rows_verified": body_rows,
            "resource_rows_verified": resource_rows,
            "producer_document_matches": producer_match,
            "producer_title_matches": producer_title_match,
            "producer_body_matches": producer_body_match,
            "producer_body_privacy_plain_text_matches": privacy_plain_text_match,
            "producer_body_privacy_plain_text_unexplained": privacy_plain_text_unexplained,
            "producer_body_equivalent_matches": producer_body_match + privacy_plain_text_match,
            "producer_content_ready": False,
            "producer_equivalence_ready": False,
        }
    finally:
        if producer is not None:
            producer.close()


def _publication_comparison(
    connection: sqlite3.Connection,
    publication_run: str,
    source_run: str,
    raw_run: str,
    vault_run: str,
    archives: dict[str, object],
    query_runner: QueryRunner | None = None,
) -> dict[str, object]:
    required = ("joplin", "raw", "vault")
    complete = all(
        isinstance(archives.get(label), dict)
        and archives[label].get("status") == "complete"
        for label in required
    )
    selection = {
        str(value.get("manifest", {}).get("selection_manifest_sha256"))
        for value in archives.values()
        if isinstance(value, dict) and value.get("status") == "complete"
        and isinstance(value.get("manifest"), dict)
    }
    # The original Joplin publication is an independent source cohort.  It is
    # verified against its own producer database above, but is never claimed
    # to join the recipe RAW source cohort.
    source_cohort: dict[str, object] = {
        "joplin": {
            "status": "not_applicable",
            "reason": "independent_source_cohort",
            "body_equivalence": (
                archives.get("joplin", {}).get("privacy_plain_text")
                if isinstance(archives.get("joplin"), dict)
                else None
            ),
        },
    }
    route_selection: dict[str, dict[str, int]] = {}

    def scalar(label: str, query: str, parameters: tuple[object, ...]) -> int:
        return int(_timed_query(
            query_runner,
            label,
            lambda: connection.execute(query, parameters).fetchone()[0] or 0,
        ))

    raw_publication_table = "c7c_publication_raw"
    vault_publication_table = "c7c_publication_vault"
    _drop_temp_tables(connection, raw_publication_table, vault_publication_table)
    for table, route, route_run, label in (
        (raw_publication_table, "raw", raw_run, "raw"),
        (vault_publication_table, "vault", vault_run, "vault"),
    ):
        connection.execute(
            f"CREATE TEMP TABLE {table} ("
            "source_key TEXT PRIMARY KEY, title_hash TEXT, body_hash TEXT) WITHOUT ROWID"
        )
        _timed_query(
            query_runner,
            f"publication.{label}.materialize_source_keys",
            lambda table=table, route=route, route_run=route_run, label=label: connection.execute(
                f"INSERT INTO {table}(source_key,title_hash,body_hash) "
                "SELECT m.source_key,p.title_hash,p.body_hash "
                "FROM publication_records p "
                "JOIN route_records r ON r.run_id=? AND r.route=? AND r.document_id=p.document_id "
                "JOIN route_identity_map m ON m.route=? AND m.route_identity=r.identity "
                "WHERE p.run_id=? AND p.label=?",
                (route_run, route, route, publication_run, label),
            ),
        )
        selected = scalar(
            f"publication.{label}.selected_source_keys",
            f"SELECT COUNT(*) FROM {table}",
            (),
        )
        published = scalar(
            f"publication.{label}.published_rows",
            "SELECT COUNT(*) FROM publication_records WHERE run_id = ? AND label = ?",
            (publication_run, label),
        )
        source_total = scalar(
            f"publication.{label}.source_total",
            "SELECT COUNT(*) FROM route_identity_map WHERE route = ?",
            (route,),
        )
        route_selection[label] = {
            "published": published,
            "selected_source_keys": selected,
            "excluded_publication_rows": max(published - selected, 0),
            "missing_source_keys": max(source_total - selected, 0),
        }
    common = scalar(
        "publication.raw_vault.common_source_keys",
        f"SELECT COUNT(*) FROM {raw_publication_table} r JOIN {vault_publication_table} v USING (source_key)",
        (),
    )
    body_matches = scalar(
        "publication.raw_vault.body_matches",
        f"SELECT COUNT(*) FROM {raw_publication_table} r JOIN {vault_publication_table} v USING (source_key) "
        "WHERE r.body_hash = v.body_hash",
        (),
    )
    title_matches = scalar(
        "publication.raw_vault.title_matches",
        f"SELECT COUNT(*) FROM {raw_publication_table} r JOIN {vault_publication_table} v USING (source_key) "
        "WHERE r.title_hash = v.title_hash",
        (),
    )
    source_cohort["raw_vault"] = {
        "common_selected_source_keys": common,
        "body_digest_matches": body_matches,
        "title_digest_matches": title_matches,
        "raw": route_selection["raw"],
        "vault": route_selection["vault"],
    }
    ready = complete and all(
        isinstance(archives[label], dict)
        and int(archives[label].get("document_rows", 0)) == int(archives[label].get("counts", {}).get("documents", -1))
        and int(archives[label].get("body_rows_verified", 0)) == int(archives[label].get("document_rows", -1))
        and (
            archives[label].get("producer_equivalence_ready") is True
            or archives[label].get("producer_content_ready") is True
        )
        for label in required
    )
    result = {
        "status": "complete" if ready else "incomplete",
        "required_labels": list(required),
        "verified_labels": sum(
            isinstance(archives.get(label), dict) and archives[label].get("status") == "complete"
            for label in required
        ),
        "selection_manifest_digests": len(selection),
        "source_cohort": source_cohort,
        "ready": bool(ready),
    }
    _drop_temp_tables(connection, raw_publication_table, vault_publication_table)
    return result


def _value_counts(connection: sqlite3.Connection, table: str, where: str, params: tuple[object, ...], field: str) -> dict[str, int]:
    return {
        str(key): int(count)
        for key, count in connection.execute(
            f"SELECT {field}, COUNT(*) FROM {table} WHERE {where} GROUP BY {field}", params
        )
        if key is not None
    }


def _compare(
    connection: sqlite3.Connection,
    source_run: str,
    raw_run: str,
    vault_run: str,
    source_scan_counts: dict[str, object],
    publication: dict[str, object],
    query_runner: QueryRunner | None = None,
) -> dict[str, object]:
    def timed(label: str, operation):
        return _timed_query(query_runner, label, operation)

    def count(label: str, query: str, parameters: tuple[object, ...]) -> int:
        return int(timed(
            label,
            lambda: connection.execute(query, parameters).fetchone()[0] or 0,
        ))

    source_total = count(
        "compare.source_total",
        "SELECT COUNT(*) FROM source_records WHERE run_id = ?",
        (source_run,),
    )
    source_status = timed(
        "compare.source_status",
        lambda: _value_counts(connection, "source_records", "run_id = ?", (source_run,), "status"),
    )
    source_fm = timed(
        "compare.source_frontmatter_status",
        lambda: _value_counts(connection, "source_records", "run_id = ?", (source_run,), "frontmatter_status"),
    )
    joins: dict[str, object] = {}
    fields: dict[str, object] = {}
    publication_comparison = publication.get("comparison", {})
    publication_ready = (
        isinstance(publication_comparison, dict)
        and publication_comparison.get("ready") is True
    )
    for route, identity in (("raw", "raw_external_id"), ("vault", "relative_path")):
        route_run = raw_run if route == "raw" else vault_run
        join = timed(
            f"compare.{route}.identity_join",
            lambda: _distinct_missing_extra(connection, source_run, route_run, route, identity),
        )
        joins[route] = join
        values: dict[str, object] = {}
        for label, source_field, route_field, comparable in (
            ("title", "title_hash", "title_hash", False),
            ("body", "body_hash", "body_hash", False),
            ("metadata", "metadata_hash", "metadata_hash", True),
        ):
            values[label + "_matches"] = timed(
                f"compare.{route}.{label}_matches",
                lambda: _field_matches(
                    connection, source_run, route_run, route, identity, source_field, route_field,
                    comparable_only=comparable,
                ),
            )
        # Source recipe frontmatter tags and producer tag relations are
        # separate channels.  The RAW producer reads Joplin note_tags while
        # the inspected Obsidian importer does not extract tags; comparing
        # their hashes would turn every untagged row into a false match and
        # would claim source-tag preservation that this contract forbids.
        values["tags_matches"] = None
        values["tags_comparison_status"] = "separate_producer_channel"
        values["metadata_comparable_rows"] = count(
            f"compare.{route}.metadata_comparable_rows",
            "SELECT COUNT(*) FROM route_records WHERE run_id = ? AND route = ? AND metadata_hash IS NOT NULL",
            (route_run, route),
        )
        values["metadata_unavailable_rows"] = count(
            f"compare.{route}.metadata_unavailable_rows",
            "SELECT COUNT(*) FROM route_records WHERE run_id = ? AND route = ? AND metadata_hash IS NULL",
            (route_run, route),
        )
        values["pinned_title_rule_matches"] = timed(
            f"compare.{route}.pinned_title_rule",
            lambda: _title_rule_matches(connection, source_run, route_run, route, identity),
        )
        values["row_multiset_matches"] = timed(
            f"compare.{route}.row_multiset",
            lambda: _row_multiset_matches(
                connection, source_run, route_run, route, identity,
                ("title_hash", "body_hash", "tags_hash", "metadata_hash"),
            ),
        )
        values["recipe_row_multiset_matches"] = timed(
            f"compare.{route}.recipe_row_multiset",
            lambda: _row_multiset_matches(
                connection, source_run, route_run, route, identity,
                ("title_hash", "body_hash"),
            ),
        )
        values["invalid_identity_rows"] = count(
            f"compare.{route}.invalid_identity_rows",
            "SELECT COUNT(*) FROM route_records WHERE run_id = ? AND route = ? AND identity_status != 'ok'",
            (route_run, route),
        )
        values["body_status_failures"] = count(
            f"compare.{route}.body_status_failures",
            "SELECT COUNT(*) FROM route_records WHERE run_id = ? AND route = ? AND body_status != 'ok;ok'",
            (route_run, route),
        )
        fields[route] = values
    source_channels = {
        "raw_body_matches_vault_body": timed(
            "compare.source.raw_body_matches_vault_body",
            lambda: _source_field_matches(connection, source_run, "raw_body_hash", "body_hash"),
        ),
        "raw_title_matches_vault_title": timed(
            "compare.source.raw_title_matches_vault_title",
            lambda: _source_field_matches(connection, source_run, "raw_title_hash", "title_hash"),
        ),
        "source_recipe_tagged_rows": count(
            "compare.source.recipe_tagged_rows",
            "SELECT COUNT(*) FROM source_records WHERE run_id = ? AND tags_hash IS NOT NULL AND tags_hash != ?",
            (source_run, _sha256_text("[]")),
        ),
        "source_rows_with_snapshot_file_change": count(
            "compare.source.snapshot_file_changes",
            "SELECT COUNT(*) FROM source_records WHERE run_id = ? AND (vault_hash IS NULL OR vault_hash != snapshot_hash)",
            (source_run,),
        ),
    }
    route_tag_channels = {
        route: {
            "tagged_rows": count(
                f"compare.{route}.tagged_rows",
                "SELECT COUNT(*) FROM route_records WHERE run_id = ? AND route = ? AND tag_count > 0",
                (run_id, route),
            ),
            "associations": count(
                f"compare.{route}.tag_associations",
                "SELECT COALESCE(SUM(tag_count),0) FROM route_records WHERE run_id = ? AND route = ?",
                (run_id, route),
            ),
        }
        for route, run_id in (("raw", raw_run), ("vault", vault_run))
    }
    tag_channel_comparison = {
        "status": "separate_channels",
        "source_recipe_tagged_rows": int(source_channels["source_recipe_tagged_rows"]),
        "raw_policy": "joplin_note_tags_relations",
        "raw_tagged_rows": int(route_tag_channels["raw"]["tagged_rows"]),
        "raw_associations": int(route_tag_channels["raw"]["associations"]),
        "vault_policy": "no_tag_extraction_observed",
        "vault_tagged_rows": int(route_tag_channels["vault"]["tagged_rows"]),
        "vault_associations": int(route_tag_channels["vault"]["associations"]),
        "source_route_comparable": False,
        # Absence on every side is the only bounded case where no tag
        # projection claim is needed.  Any populated source or producer
        # channel remains unresolved by design; the source and producer
        # channels are never declared interchangeable.
        "equivalence_established": (
            int(source_channels["source_recipe_tagged_rows"]) == 0
            and int(route_tag_channels["raw"]["associations"]) == 0
            and int(route_tag_channels["vault"]["associations"]) == 0
        ),
    }
    raw_body = int(fields["raw"]["body_matches"])
    vault_body = int(fields["vault"]["body_matches"])
    raw_title = int(fields["raw"]["title_matches"])
    vault_title = int(fields["vault"]["title_matches"])
    raw_meta = int(fields["raw"]["metadata_matches"])
    vault_meta = int(fields["vault"]["metadata_matches"])
    common_raw = min(source_total, int(joins["raw"]["route_rows"]))
    common_vault = min(source_total, int(joins["vault"]["route_rows"]))
    title_known = {
        route: min(
            int(fields[route]["pinned_title_rule_matches"]),
            max(
                (common_raw if route == "raw" else common_vault)
                - int(fields[route]["title_matches"]),
                0,
            ),
        )
        for route in ("raw", "vault")
    }
    unexplained = {
        "source_route_body": {
            "raw": max(common_raw - raw_body, 0),
            "vault": max(common_vault - vault_body, 0),
        },
        "source_route_title": {
            "raw": max(common_raw - raw_title - title_known["raw"], 0),
            "vault": max(common_vault - vault_title - title_known["vault"], 0),
        },
        "source_route_tags": {
            # The RAW count is explained by its reviewed Joplin relation
            # policy, but it is not comparable to source recipe frontmatter
            # tags.  A vault association would violate the reviewed
            # no-tag-extraction policy and therefore remains unexplained.
            "raw": 0,
            "vault": int(route_tag_channels["vault"]["tagged_rows"]),
        },
        "source_route_metadata": {
            # RAW publication metadata is intentionally not projected into
            # the recipe channel; that omission is measured below as a
            # known route difference rather than misreported as unexplained.
            "raw": 0,
            "vault": max(common_vault - vault_meta, 0),
        },
        # RAW retains the source body terminal LF while the vault producer
        # removes it.  When both route bodies independently match the source
        # body under their documented route rules, the cross-route byte
        # difference is fully explained by that rule.
        "source_raw_vs_vault_body": max(source_total - min(raw_body, vault_body), 0),
        "source_raw_vs_vault_title": max(source_total - int(source_channels["raw_title_matches_vault_title"]), 0),
    }
    known_differences = {
        "raw_route_metadata_not_projected": int(fields["raw"]["metadata_unavailable_rows"]),
        "raw_route_tag_channel_separate": int(route_tag_channels["raw"]["associations"]),
        "vault_route_tag_channel_separate": int(route_tag_channels["vault"]["associations"]),
        "source_recipe_tags_not_projected_to_vault": int(source_channels["source_recipe_tagged_rows"]),
        "vault_expected_tag_omissions": max(
            int(source_channels["source_recipe_tagged_rows"])
            - int(route_tag_channels["vault"]["tagged_rows"]), 0
        ),
        "source_and_producer_tag_channels_separate": True,
        "raw_source_tag_association_matches": None,
        "body_final_newline_and_leading_lf_normalized": min(raw_body, vault_body),
    }
    source_scan_failures = (
        int(source_scan_counts.get("source_parse_failures", 0))
        + int(source_scan_counts.get("source_record_failures", 0))
    )
    source_status_ok = source_scan_failures == 0 and source_status == {"ok": source_total}
    identity_ok = all(
        int(joins[route]["missing_identities"]) == 0
        and int(joins[route]["extra_identities"]) == 0
        and int(fields[route]["invalid_identity_rows"]) == 0
        and int(fields[route]["body_status_failures"]) == 0
        and int(joins[route]["source_rows"]) == int(joins[route]["route_rows"])
        for route in ("raw", "vault")
    )
    unexplained_zero = all(
        value == 0
        for group in unexplained.values()
        for value in (group.values() if isinstance(group, dict) else [group])
    )
    source_recipe_semantic_equal = bool(
        source_status_ok
        and identity_ok
        and publication_ready
        and all(
            int(fields[route]["recipe_row_multiset_matches"]) == int(joins[route]["source_rows"])
            for route in ("raw", "vault")
        )
        and unexplained_zero
        and int(fields["vault"]["metadata_unavailable_rows"]) == 0
    )
    route_pair_summary = timed(
        "compare.route_pair.row_multiset",
        lambda: _route_pair_multiset_summary(
            connection, source_run, raw_run, vault_run,
            ("title_hash", "body_hash", "tags_hash", "metadata_hash")
        ),
    )
    route_pair_matches = int(route_pair_summary["matches"])
    route_output_semantic_equal = bool(
        source_status_ok
        and identity_ok
        and publication_ready
        and int(route_pair_summary["ambiguous_groups"]) == 0
        and route_pair_matches == min(int(joins["raw"]["route_rows"]), int(joins["vault"]["route_rows"]))
        and unexplained_zero
    )
    semantic_equal = bool(
        source_recipe_semantic_equal
        and route_output_semantic_equal
        and tag_channel_comparison["equivalence_established"]
    )
    return {
        "status": "complete",
        "rules_version": RULES_VERSION,
        "source_rows": source_total,
        "source_scan_counts": source_scan_counts,
        "source_scan_failures": source_scan_failures,
        "source_status": source_status,
        "source_frontmatter_status": source_fm,
        "joins": joins,
        "fields": fields,
        "source_channels": source_channels,
        "route_tag_channels": route_tag_channels,
        "tag_channel_comparison": tag_channel_comparison,
        "known_differences": known_differences,
        "title_differences": {
            route: {
                "unexplained": int(unexplained["source_route_title"][route]),
                "known_frontmatter_scalar": int(title_known[route]),
                "exact_matches": int(fields[route]["title_matches"]),
                "pinned_rule_matches": int(fields[route]["pinned_title_rule_matches"]),
            }
            for route in ("raw", "vault")
        },
        "publication": publication,
        "route_pair_row_multiset_matches": route_pair_matches,
        "route_pair_ambiguous_groups": int(route_pair_summary["ambiguous_groups"]),
        "source_recipe_semantic_equal": source_recipe_semantic_equal,
        "route_output_semantic_equal": route_output_semantic_equal,
        "explained_differences": {
            "raw_route_metadata_not_projected": int(fields["raw"]["metadata_unavailable_rows"]),
            "vault_route_metadata_available": int(fields["vault"]["metadata_comparable_rows"]),
            "body_final_newline_and_leading_lf_normalized": min(raw_body, vault_body),
            "raw_and_vault_source_bodies_equal_after_route_rules": int(source_channels["raw_body_matches_vault_body"]),
        },
        "unexplained_differences": unexplained,
        "semantic_equal": bool(semantic_equal),
        "source_content_included": False,
    }


def _file_fingerprint(path: Path) -> dict[str, object]:
    digest, size = _hash_file(path)
    stat = path.stat()
    return {"size": size, "sha256": digest, "mtime_ns": stat.st_mtime_ns}


def _dependency_code_inventory() -> list[dict[str, object]]:
    """Fingerprint every repository-level Python module used by the harness, and this tool.

    The comparator imports local modules for source decoding and publication
    verification.  Hashing all top-level Python files is intentionally
    conservative: a dependency added later cannot silently reuse a completed
    checkpoint merely because this entry point is unchanged.
    """

    inventory: list[dict[str, object]] = []
    own = Path(__file__).resolve()
    for path in sorted([*REPOSITORY_ROOT.glob("*.py"), own], key=lambda item: item.name):
        entry = _file_fingerprint(path)
        entry["path"] = path.relative_to(REPOSITORY_ROOT).as_posix()
        inventory.append(entry)
    return inventory


def _publication_inventory(path: Path) -> dict[str, object]:
    """Fingerprint all regular files in one reviewed publication directory."""

    if path.is_symlink() or not path.is_dir():
        return {"missing": True}
    return _inventory(path)


def _disk_preflight(output: Path, minimum_free_bytes: int, stage: str) -> dict[str, int]:
    """Check output-filesystem capacity once before a stage starts."""

    if type(minimum_free_bytes) is not int or minimum_free_bytes < 0:
        raise C7CError("minimum free disk bytes must be a non-negative integer")
    if not stage or not isinstance(stage, str):
        raise C7CError("disk preflight stage is required")
    try:
        free_bytes = int(shutil.disk_usage(output).free)
    except OSError as exc:
        raise C7CError("cannot determine free disk space") from exc
    if free_bytes < minimum_free_bytes:
        raise C7CError(
            f"insufficient free disk space before {stage} stage: "
            f"{free_bytes} < {minimum_free_bytes} bytes"
        )
    return {
        "free_bytes": free_bytes,
        "minimum_free_bytes": minimum_free_bytes,
    }


def _publication_arguments(args: argparse.Namespace) -> list[tuple[str, Path]]:
    values = getattr(args, "publication", []) or []
    result: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or "=" not in value:
            raise C7CError("publication must be LABEL=ARCHIVE_PATH")
        label, raw_path = value.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", label) or label in seen:
            raise C7CError("publication label is invalid or duplicated")
        if not raw_path:
            raise C7CError("publication archive path is empty")
        seen.add(label)
        result.append((label, Path(raw_path).resolve()))
    return result


def _fingerprint(args: argparse.Namespace, limits: Limits) -> dict[str, object]:
    inputs = {
        "joplin_database": _file_fingerprint(Path(args.joplin_db)) if getattr(args, "joplin_db", None) else None,
        "raw_database": _file_fingerprint(Path(args.raw_db)),
        "vault_database": _file_fingerprint(Path(args.vault_db)),
        "raw_source_inventory": _inventory(Path(args.raw_source_root)),
        "vault_source_inventory": _inventory(Path(args.vault_root)),
    }
    publication_inputs = []
    for label, path in _publication_arguments(args):
        manifest = path / "manifest.json"
        publication_inputs.append({
            "label": label,
            "manifest": _file_fingerprint(manifest) if manifest.is_file() else {"missing": True},
            "inventory": _publication_inventory(path),
        })
    code_inventory = _dependency_code_inventory()
    profile = {
        "rules_version": RULES_VERSION,
        "mapper_version": args.mapper_version,
        "prefix": args.prefix,
        "profile": args.profile,
        "query_timeout_seconds": args.query_timeout_seconds,
        "minimum_free_bytes": getattr(args, "min_free_bytes", DEFAULT_MIN_FREE_BYTES),
        "raw_revision": args.raw_revision,
        "vault_revision": args.vault_revision,
        "limits": limits.__dict__,
        "inputs": inputs,
        "publication_inputs": publication_inputs,
        "dependency_code_inventory": code_inventory,
    }
    code_hash = _sha256_text(_canonical_json(code_inventory))
    return {
        "code_sha256": code_hash,
        "profile_sha256": _sha256_text(_canonical_json(profile)),
        "profile": profile,
    }


def _checkpoint_update(path: Path, checkpoint: dict[str, object]) -> None:
    _atomic_json(path, checkpoint)


def _new_stage(checkpoint: dict[str, object], stage: str) -> str:
    stages = checkpoint.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise C7CError("invalid checkpoint stages")
    stage_run = secrets.token_hex(12)
    stages[stage] = {"status": "running", "run_id": stage_run, "started": time.time()}
    checkpoint["status"] = "running"
    checkpoint["current_stage"] = stage
    return stage_run


def _complete_stage(checkpoint: dict[str, object], stage: str, stage_run: str, counts: dict[str, object]) -> None:
    stages = checkpoint["stages"]
    assert isinstance(stages, dict)
    stages[stage] = {"status": "complete", "run_id": stage_run, "finished": time.time(), "counts": counts}
    checkpoint["current_stage"] = None


def _archive_checkpoint(output: Path, checkpoint: dict[str, object]) -> None:
    attempts = output / "attempts"
    attempts.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(attempts, 0o700)
    except OSError:
        pass
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = attempts / f"{stamp}-{checkpoint.get('run_id', 'unknown')}.json"
    suffix = 1
    while target.exists():
        suffix += 1
        target = attempts / f"{stamp}-{checkpoint.get('run_id', 'unknown')}-{suffix}.json"
    _atomic_json(target, checkpoint)


def run_comparison(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(output, 0o700)
    except OSError:
        pass
    limits = Limits(
        max_source_bytes=args.max_source_bytes,
        max_compressed_bytes=args.max_compressed_bytes,
        max_decompressed_bytes=args.max_decompressed_bytes,
        max_frontmatter_bytes=args.max_frontmatter_bytes,
        max_tags=args.max_tags,
    )
    minimum_free_bytes = getattr(args, "min_free_bytes", DEFAULT_MIN_FREE_BYTES)
    fingerprint = _fingerprint(args, limits)
    checkpoint_path = output / "checkpoint.json"
    spool_path = output / "comparison.sqlite"
    result_path = output / "result.json"
    notification_path = output / "notification.json"
    checkpoint: dict[str, object]
    if checkpoint_path.exists():
        loaded = _read_json(checkpoint_path)
        if not isinstance(loaded, dict):
            raise CheckpointMismatch("checkpoint is not an object")
        checkpoint = loaded
        if checkpoint.get("fingerprint") != fingerprint:
            raise CheckpointMismatch("input, code, or comparison profile changed")
        if checkpoint.get("status") == "complete" and result_path.exists():
            result = _read_json(result_path)
            if not isinstance(result, dict):
                raise C7CError("completed result is invalid")
            return result, 0 if result.get("semantic_equal") or not args.strict else 1
        _archive_checkpoint(output, checkpoint)
    else:
        checkpoint = {
            "schema_version": SPOOL_SCHEMA_VERSION,
            "status": "pending",
            "run_id": secrets.token_hex(12),
            "started": time.time(),
            "fingerprint": fingerprint,
            "stages": {},
            "source_content_included": False,
        }
        _checkpoint_update(checkpoint_path, checkpoint)
    connection = _create_spool(spool_path)
    try:
        stages = checkpoint.setdefault("stages", {})
        assert isinstance(stages, dict)
        disk_preflight = checkpoint.setdefault("disk_preflight", {})
        if not isinstance(disk_preflight, dict):
            raise C7CError("invalid checkpoint disk preflight")
        if stages.get("source", {}).get("status") != "complete":
            disk_preflight["source"] = _disk_preflight(output, minimum_free_bytes, "source")
            _checkpoint_update(checkpoint_path, checkpoint)
            stage_run = _new_stage(checkpoint, "source")
            _checkpoint_update(checkpoint_path, checkpoint)
            counts = _scan_source(
                connection, stage_run, Path(args.raw_source_root), Path(args.vault_root), args.prefix, limits
            )
            _complete_stage(checkpoint, "source", stage_run, counts)
            _checkpoint_update(checkpoint_path, checkpoint)
        source_run = stages["source"]["run_id"]
        if stages.get("raw", {}).get("status") != "complete":
            disk_preflight["raw"] = _disk_preflight(output, minimum_free_bytes, "raw")
            _checkpoint_update(checkpoint_path, checkpoint)
            stage_run = _new_stage(checkpoint, "raw")
            _checkpoint_update(checkpoint_path, checkpoint)
            counts = _scan_route(connection, stage_run, "raw", Path(args.raw_db), limits)
            _complete_stage(checkpoint, "raw", stage_run, counts)
            _checkpoint_update(checkpoint_path, checkpoint)
        raw_run = stages["raw"]["run_id"]
        if stages.get("vault", {}).get("status") != "complete":
            disk_preflight["vault"] = _disk_preflight(output, minimum_free_bytes, "vault")
            _checkpoint_update(checkpoint_path, checkpoint)
            stage_run = _new_stage(checkpoint, "vault")
            _checkpoint_update(checkpoint_path, checkpoint)
            counts = _scan_route(connection, stage_run, "vault", Path(args.vault_db), limits)
            _complete_stage(checkpoint, "vault", stage_run, counts)
            _checkpoint_update(checkpoint_path, checkpoint)
        vault_run = stages["vault"]["run_id"]
        if stages.get("comparison", {}).get("status") != "complete":
            disk_preflight["comparison"] = _disk_preflight(
                output, minimum_free_bytes, "comparison"
            )
            _checkpoint_update(checkpoint_path, checkpoint)
            stage_run = _new_stage(checkpoint, "comparison")
            _checkpoint_update(checkpoint_path, checkpoint)
            _index_spool(connection)
            source_stage_counts = stages.get("source", {}).get("counts", {})
            if not isinstance(source_stage_counts, dict):
                raise C7CError("source stage counts are missing")
            comparison_progress_path = output / "comparison-progress.json"
            query_runner = QueryRunner(
                connection,
                args.query_timeout_seconds,
                comparison_progress_path,
            )
            query_runner.call(
                "comparison.route_identity_map",
                lambda: _materialize_route_identity_map(connection, source_run, raw_run, vault_run),
            )
            producer_imports = {
                "raw": _producer_import_summary(Path(args.raw_db), "raw"),
                "vault": _producer_import_summary(Path(args.vault_db), "vault"),
            }
            archive_paths = dict(_publication_arguments(args))
            archives: dict[str, object] = {}
            publication_work = output / "publication-verification"
            for label, archive_path in archive_paths.items():
                producer_path = None
                if label == "joplin":
                    producer_path = Path(args.joplin_db) if args.joplin_db else None
                elif label == "raw":
                    producer_path = Path(args.raw_db)
                elif label == "vault":
                    producer_path = Path(args.vault_db)
                archives[label] = _verified_publication_summary(
                    connection, checkpoint["run_id"], label, archive_path,
                    producer_path, publication_work / label,
                )
            publication = {
                "archives": archives,
                "producer_imports": producer_imports,
            }
            publication["comparison"] = _publication_comparison(
                connection, checkpoint["run_id"], source_run, raw_run, vault_run, archives,
                query_runner=query_runner,
            )
            result = _compare(
                connection, source_run, raw_run, vault_run, source_stage_counts,
                publication, query_runner=query_runner,
            )
            result["run_id"] = checkpoint["run_id"]
            result["fingerprint"] = {
                "code_sha256": fingerprint["code_sha256"],
                "profile_sha256": fingerprint["profile_sha256"],
            }
            result["comparison_diagnostics"] = {
                "query_timeout_seconds": args.query_timeout_seconds,
                "progress": "comparison-progress.json",
            }
            _atomic_json(result_path, result)
            _atomic_json(notification_path, {
                "status": result["status"],
                "semantic_equal": result["semantic_equal"],
                "finished": time.time(),
                "source_content_included": False,
            })
            _complete_stage(checkpoint, "comparison", stage_run, {
                "semantic_equal": result["semantic_equal"],
                "source_rows": result["source_rows"],
            })
            checkpoint["status"] = "complete"
            checkpoint["finished"] = time.time()
            checkpoint["result"] = "result.json"
            checkpoint["notification"] = "notification.json"
            _checkpoint_update(checkpoint_path, checkpoint)
        else:
            result = _read_json(result_path)
            if not isinstance(result, dict):
                raise C7CError("comparison result is invalid")
    except BaseException as exc:
        checkpoint["status"] = "failed"
        checkpoint["failed_stage"] = checkpoint.get("current_stage")
        checkpoint["error_type"] = type(exc).__name__
        checkpoint["error_message"] = str(exc)
        if checkpoint.get("current_stage") == "comparison":
            checkpoint["comparison_progress"] = "comparison-progress.json"
            if isinstance(exc, C7CQueryTimeout):
                checkpoint["query_timeout"] = {
                    "label": exc.label,
                    "elapsed_seconds": exc.elapsed_seconds,
                    "timeout_seconds": exc.timeout_seconds,
                }
        checkpoint["finished"] = time.time()
        _checkpoint_update(checkpoint_path, checkpoint)
        raise
    finally:
        connection.close()
    return result, 0 if result.get("semantic_equal") or not args.strict else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-db", required=True, help="Pinned Notrios Joplin RAW producer database")
    parser.add_argument("--vault-db", required=True, help="Pinned Notrios Obsidian producer database")
    parser.add_argument(
        "--joplin-db",
        help="Original Joplin producer database for the joplin publication archive",
    )
    parser.add_argument("--raw-source-root", required=True, help="Read-only Joplin RAW source tree")
    parser.add_argument("--vault-root", required=True, help="Read-only Obsidian source tree")
    parser.add_argument("--output", required=True, help="Private writable comparison output directory")
    parser.add_argument("--prefix", default="Recipes/", help="Exact source snapshot prefix to remove")
    parser.add_argument("--profile", default="c7c-recipe-v1")
    parser.add_argument("--mapper-version", default="movenotes-notrios-v1")
    parser.add_argument("--raw-revision", default="not exposed")
    parser.add_argument("--vault-revision", default="not exposed")
    parser.add_argument(
        "--publication", action="append", default=[], metavar="LABEL=ARCHIVE_PATH",
        help="Reviewed Notrios publication archive; repeat for joplin, raw and vault",
    )
    parser.add_argument("--max-source-bytes", type=int, default=DEFAULT_MAX_SOURCE_BYTES)
    parser.add_argument("--max-compressed-bytes", type=int, default=DEFAULT_MAX_COMPRESSED_BYTES)
    parser.add_argument("--max-decompressed-bytes", type=int, default=DEFAULT_MAX_DECOMPRESSED_BYTES)
    parser.add_argument("--max-frontmatter-bytes", type=int, default=DEFAULT_MAX_FRONTMATTER_BYTES)
    parser.add_argument("--max-tags", type=int, default=DEFAULT_MAX_TAGS)
    parser.add_argument(
        "--query-timeout-seconds",
        type=float,
        default=3600.0,
        help="Maximum duration of each comparison SQL substage (default: 3600 seconds)",
    )
    parser.add_argument(
        "--min-free-bytes",
        type=int,
        default=DEFAULT_MIN_FREE_BYTES,
        help=(
            "Minimum free bytes required on the output filesystem before each "
            f"stage (default: {DEFAULT_MIN_FREE_BYTES})"
        ),
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 when semantic equivalence is false")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result, returncode = run_comparison(args)
    except CheckpointMismatch:
        print("C7C checkpoint mismatch: use a fresh output directory or update the profile.", file=sys.stderr)
        return 2
    except (C7CError, OSError, sqlite3.Error) as exc:
        print(f"C7C comparison failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(_canonical_json(result), flush=True)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
