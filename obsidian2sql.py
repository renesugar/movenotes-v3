#!/usr/bin/env python3
"""Import an Obsidian vault into the movenotes SQLite database.

The importer supports both native Obsidian vaults and vaults produced by
``sql2obsidian.py``. A ``.movenotes/joplin-raw`` preservation bundle is used
when present; a damaged one is refused, with the commands to run next. Native Obsidian files are represented by deterministic
Joplin-compatible note, folder and resource rows while their exact paths and
bytes are retained for lossless Obsidian round trips and carried through
Joplin's ``application_data`` property.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import html
import json
import mimetypes
import os
import re
import shlex
import shutil
import sqlite3
import sys
import urllib.parse
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import common
import constants
import joplin2sql
import notesdb
import obsidianmeta

__program_name__ = "obsidian2sql"
__version__ = "3.38"

_PRESERVATION_DIR = ".movenotes"
_MANIFEST_NAME = "manifest.json"
_WIKI_LINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
# A titled link is tried first: a destination with no spaces or parentheses,
# or an <...> destination, then one title (common.LINK_TITLE). Anything else
# takes the original untitled pattern, so its output is unchanged.
_MARKDOWN_LINK_RE = re.compile(
    r"(!?)\[([^\]]*)\]\((?:(<[^<>\r\n]*>|[^\s()<>]+)(" + common.LINK_TITLE + r")|([^)]+))\)"
)
_IMAGE_EXTENSIONS = frozenset(
    {"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "avif", "tif", "tiff", "ico", "heic"}
)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=__program_name__, description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--input", dest="input_path", type=common.existing_dir, required=True,
        help="Path to the input Obsidian vault",
    )
    parser.add_argument(
        "--output", dest="output_path", type=common.existing_dir, required=True,
        help="Path to the output SQLite directory",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500,
        help="Rows per SQLite batch (default: 500)",
    )
    parser.add_argument(
        "--progress-every", type=int, default=1000,
        help="Print progress every N imported files; 0 disables it (default: 1000)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print every imported path")
    parser.add_argument(
        "--ignore-preservation", action="store_true",
        help=(
            "Import the vault as plain Obsidian notes even if it holds a .movenotes "
            "preservation bundle, valid or damaged; the bundle is not read"
        ),
    )
    return parser


def _iso_timestamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _safe_json_scalar(value: str) -> object:
    value = value.strip()
    if not value:
        return ""
    try:
        return json.loads(value)
    except (ValueError, json.JSONDecodeError):
        lowered = value.lower()
        if lowered in {"null", "~"}:
            return None
        if lowered in {"true", "false"}:
            return lowered == "true"
        return value.strip("'\"")


def _frontmatter_summary(path: Path, maximum_bytes: int = 4 * 1024 * 1024) -> dict[str, object]:
    """Read only an initial YAML block for ID/path indexing."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            first = handle.readline()
            if first.rstrip("\r\n") != "---":
                return {}
            lines: list[str] = []
            total = 0
            for line in handle:
                total += len(line.encode("utf-8"))
                if total > maximum_bytes:
                    return {}
                if line.rstrip("\r\n") in {"---", "..."}:
                    return parse_frontmatter("".join(lines))
                lines.append(line)
    except (OSError, UnicodeDecodeError):
        return {}
    return {}


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(frontmatter_without_fences, body)`` without normalising text."""
    offset = 1 if text.startswith("\ufeff") else 0
    if not text[offset:].startswith("---"):
        return "", text
    first_end = text.find("\n", offset)
    if first_end < 0 or text[offset:first_end].rstrip("\r") != "---":
        return "", text
    position = first_end + 1
    while position <= len(text):
        end = text.find("\n", position)
        if end < 0:
            end = len(text)
        line = text[position:end].rstrip("\r")
        if line in {"---", "..."}:
            body_start = end + 1 if end < len(text) else end
            return text[first_end + 1 : position], text[body_start:]
        position = end + 1
    return "", text


def parse_frontmatter(frontmatter: str) -> dict[str, object]:
    """Parse only the scalar/list fields needed by the converter.

    The exact frontmatter text remains authoritative in ``note_obsidian_raw``;
    this deliberately small parser never needs to understand arbitrary YAML.
    """
    result: dict[str, object] = {}
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^([A-Za-z0-9_-]+):(?:\s*(.*))?$", line)
        if not match:
            index += 1
            continue
        key, raw_value = match.group(1), match.group(2) or ""
        if key == "tags" and not raw_value.strip():
            values: list[str] = []
            index += 1
            while index < len(lines):
                item = re.match(r"^\s+-\s+(.*)$", lines[index])
                if not item:
                    break
                parsed = _safe_json_scalar(item.group(1))
                if parsed is not None:
                    values.append(str(parsed))
                index += 1
            result[key] = values
            continue
        result[key] = _safe_json_scalar(raw_value)
        index += 1

    properties_value = result.get("joplin-properties")
    if isinstance(properties_value, str):
        try:
            result["joplin-properties"] = json.loads(properties_value)
        except (ValueError, json.JSONDecodeError):
            pass
    if not isinstance(result.get("joplin-properties"), list):
        compatibility = result.get("joplin-properties-json")
        if isinstance(compatibility, str):
            try:
                result["joplin-properties"] = json.loads(compatibility)
            except (ValueError, json.JSONDecodeError):
                pass
    tags = result.get("tags")
    if isinstance(tags, str):
        stripped = tags.strip()
        if stripped.startswith("["):
            try:
                parsed_tags = json.loads(stripped)
                if isinstance(parsed_tags, list):
                    result["tags"] = [str(value) for value in parsed_tags]
            except (ValueError, json.JSONDecodeError):
                pass
        elif stripped:
            result["tags"] = [stripped]
    return result


def _property_pairs(value: object) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str):
                result.append((entry[0], str(entry[1])))
    return result


def _generated_properties(
    *, item_id: str, item_type: int, timestamp: str, parent_id: str = "",
    application_data: str = "", title: str = "", mime: str = "",
    filename: str = "", extension: str = "", size: int | None = None,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = [("id", item_id)]
    if item_type in {int(constants.JoplinType.NOTE), int(constants.JoplinType.FOLDER)}:
        pairs.append(("parent_id", parent_id))
    pairs.extend(
        [
            ("created_time", timestamp), ("updated_time", timestamp),
            ("user_created_time", timestamp), ("user_updated_time", timestamp),
            ("encryption_cipher_text", ""), ("encryption_applied", "0"),
        ]
    )
    if item_type == int(constants.JoplinType.NOTE):
        pairs.extend(
            [
                ("is_conflict", "0"), ("latitude", "0.00000000"),
                ("longitude", "0.00000000"), ("altitude", "0.0000"),
                ("author", ""), ("source_url", ""), ("is_todo", "0"),
                ("todo_due", "0"), ("todo_completed", "0"),
                ("source", "movenotes-obsidian"),
                ("source_application", "movenotes-obsidian2sql"),
                ("application_data", application_data), ("order", "0"),
                ("markup_language", "1"), ("is_shared", "0"),
            ]
        )
    elif item_type == int(constants.JoplinType.FOLDER):
        pairs.extend([("is_shared", "0"), ("application_data", application_data)])
    elif item_type == int(constants.JoplinType.RESOURCE):
        pairs.extend(
            [
                ("mime", mime), ("filename", filename),
                ("file_extension", extension), ("size", str(size or 0)),
                ("is_shared", "0"), ("application_data", application_data),
            ]
        )
    pairs.extend([("user_data", ""), ("type_", str(item_type))])
    return pairs


def _columns_from_properties(
    *, properties: list[tuple[str, str]], body: str, title: str,
    source_path: str, raw: bytes | None, frontmatter: str = "",
    obsidian_body: str = "", application_data_override: str | None = None,
) -> dict:
    effective: dict[str, str] = {}
    columns: dict[str, object] = {}
    for key, value in properties:
        effective[key] = value
        column_name = f"joplin_{key}"
        if column_name in notesdb.JOPLIN_COLUMNS:
            columns[column_name] = joplin2sql._convert_known_value(
                value, notesdb.JOPLIN_COLUMNS[column_name]
            )
    if application_data_override is not None:
        columns["joplin_application_data"] = application_data_override
        properties = [
            (key, application_data_override if key == "application_data" else value)
            for key, value in properties
        ]
        if not any(key == "application_data" for key, _value in properties):
            properties.insert(-1 if properties else 0, ("application_data", application_data_override))

    item_id = str(columns.get("joplin_id") or obsidianmeta.deterministic_id("note", source_path))
    item_type = int(columns.get("joplin_type_") or constants.JoplinType.NOTE)
    # Native Obsidian bytes belong only in note_obsidian_raw. Keeping them out
    # of note_source_raw avoids duplicating large notes and prevents the Joplin
    # exact-source path from mistaking an Obsidian file for a RAW item.
    source_raw = None
    source_digest = None
    obsidian_digest = (
        hashlib.sha256(raw).digest()
        if raw is not None
        else hashlib.sha256(source_path.encode()).digest()
    )
    note_data = body
    return {
        **columns,
        "note_type": common.note_type_from_joplin_type(item_type),
        "note_uuid": item_id,
        "note_parent_uuid": columns.get("joplin_parent_id"),
        "note_tag_uuid": columns.get("joplin_tag_id"),
        "note_note_uuid": columns.get("joplin_note_id"),
        "note_folder": None,
        "note_original_format": "obsidian",
        "note_internal_date": columns.get("joplin_created_time"),
        "note_hash": hashlib.sha512(note_data.encode("utf-8")).hexdigest(),
        "note_title": title or constants.NOTES_UNTITLED,
        "note_data": note_data,
        "note_data_format": "text/markdown",
        "note_url": columns.get("joplin_source_url"),
        "note_source_filename": None,
        "note_source_body": None,
        "note_source_raw": source_raw,
        "note_source_sha256": source_digest,
        "note_source_properties": json.dumps(properties, ensure_ascii=False, separators=(",", ":")),
        "note_obsidian_path": source_path,
        "note_obsidian_raw": raw,
        "note_obsidian_sha256": obsidian_digest,
        "note_obsidian_body": obsidian_body,
        "note_obsidian_frontmatter": frontmatter,
        "note_obsidian_joplin_body_sha256": obsidianmeta.text_sha256(note_data),
    }


def _normalise_target(value: str) -> str:
    value = urllib.parse.unquote(value.strip().strip("<>"))
    if " " in value and not value.startswith(("./", "../")):
        # A markdown destination may be followed by an optional quoted title.
        title_match = re.match(r"^(.*?)(?:\s+[\"'].*[\"'])$", value)
        if title_match:
            value = title_match.group(1)
    return value.split("#", 1)[0]


def _resolve_vault_target(
    target: str, note_path: PurePosixPath, all_paths: dict[str, str], basename_paths: dict[str, list[str]]
) -> str | None:
    target = _normalise_target(target).replace("\\", "/")
    if not target or target.startswith(("http://", "https://", "mailto:", "data:", ":/")):
        return None
    candidates: list[PurePosixPath] = []
    raw = PurePosixPath(target.lstrip("/"))
    candidates.append(note_path.parent / raw)
    candidates.append(raw)
    if raw.suffix == "":
        candidates.append(note_path.parent / raw.with_suffix(".md"))
        candidates.append(raw.with_suffix(".md"))
    for candidate in candidates:
        normalised = os.path.normpath(candidate.as_posix()).replace("\\", "/")
        if normalised in all_paths:
            return normalised
    basename = raw.name.casefold()
    matches = basename_paths.get(basename, [])
    if len(matches) == 1:
        return matches[0]
    if raw.suffix == "":
        matches = basename_paths.get((raw.name + ".md").casefold(), [])
        if len(matches) == 1:
            return matches[0]
    return None


def rewrite_obsidian_links(
    body: str,
    note_path: PurePosixPath,
    path_to_id: dict[str, str],
    basename_paths: dict[str, list[str]],
    resource_paths: set[str],
) -> str:
    """Translate resolvable Obsidian local links to Joplin ``:/id`` links.

    An HTML image whose ``src`` names a vault attachment gets ``:/id`` as its
    source, and keeps every other byte of the tag, which is how sql2obsidian.py
    exports a Joplin HTML image (H1).
    """
    def wiki_replace(match: re.Match[str]) -> str:
        embed, inside = match.group(1), match.group(2)
        target, separator, alias = inside.partition("|")
        resolved = _resolve_vault_target(target, note_path, path_to_id, basename_paths)
        if resolved is None:
            return match.group(0)
        item_id = path_to_id[resolved]
        display = alias or PurePosixPath(target.split("#", 1)[0]).stem or target
        if resolved in resource_paths and (embed or PurePosixPath(resolved).suffix.lower().lstrip(".") in _IMAGE_EXTENSIONS):
            return f"![{display}](:/{item_id})"
        return f"[{display}](:/{item_id})"

    def markdown_replace(match: re.Match[str]) -> str:
        embed, display = match.group(1), match.group(2)
        # A title is copied after the mapped destination, never parsed.
        title = match.group(4) or ""
        target = match.group(3) if match.group(3) is not None else match.group(5)
        resolved = _resolve_vault_target(target, note_path, path_to_id, basename_paths)
        if resolved is None:
            return match.group(0)
        item_id = path_to_id[resolved]
        if resolved in resource_paths and (embed or PurePosixPath(resolved).suffix.lower().lstrip(".") in _IMAGE_EXTENSIONS):
            return f"![{display}](:/{item_id}{title})"
        return f"[{display or PurePosixPath(resolved).name}](:/{item_id}{title})"

    def source_replace(value: str) -> str | None:
        resolved = _resolve_vault_target(html.unescape(value), note_path, path_to_id, basename_paths)
        return f":/{path_to_id[resolved]}" if resolved in resource_paths else None

    return common.replace_html_image_sources(
        _MARKDOWN_LINK_RE.sub(markdown_replace, _WIKI_LINK_RE.sub(wiki_replace, body)), source_replace)


def _file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.digest()


def _copy_resource(source: Path, destination_dir: Path, resource_id: str) -> Path:
    suffix = source.suffix.lower()
    destination = destination_dir / f"{resource_id}{suffix}"
    destination_dir.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not common.files_identical(source, destination):
            common.error(f"resource collision at '{destination}'")
    else:
        shutil.copy2(source, destination)
    return destination


def _existing_import_hashes(sqlconn: sqlite3.Connection, item_ids: list[str]) -> dict[str, set[bytes | None]]:
    """Load exact Obsidian hashes, falling back to exact Joplin RAW hashes."""
    result: dict[str, set[bytes | None]] = {}
    for offset in range(0, len(item_ids), 800):
        chunk = list(dict.fromkeys(item_ids[offset:offset + 800]))
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        for row in sqlconn.execute(
            f"SELECT joplin_id, note_obsidian_sha256, note_source_sha256 "
            f"FROM notes WHERE joplin_id IN ({placeholders})",
            chunk,
        ):
            values = (row["note_obsidian_sha256"], row["note_source_sha256"])
            target = result.setdefault(str(row["joplin_id"]), set())
            for value in values:
                if value is None:
                    continue
                digest = value.tobytes() if isinstance(value, memoryview) else value
                target.add(digest)
            if not target:
                target.add(None)
    return result


def _insert_rows(sqlconn: sqlite3.Connection, rows: list[dict], batch_size: int) -> tuple[int, int]:
    inserted = skipped = 0
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        existing = _existing_import_hashes(
            sqlconn, [str(row.get("joplin_id") or row.get("note_uuid")) for row in batch]
        )
        pending: list[dict] = []
        # ``existing`` describes the database before this batch.  Keep the
        # incoming identities too: SQLite's primary key is note_id, so two
        # distinct rows with the same Joplin item ID would otherwise both be
        # inserted when they occur in one executemany call.
        pending_hashes: dict[str, set[bytes | None]] = {}
        for row in batch:
            item_id = str(row.get("joplin_id") or row.get("note_uuid"))
            incoming = row.get("note_obsidian_sha256")
            if incoming is None:
                incoming = row.get("note_source_sha256")
            current = existing.get(item_id)
            if current is not None:
                if incoming in current:
                    skipped += 1
                    continue
                common.error(f"item id collision for '{item_id}' while importing Obsidian vault")
            pending_current = pending_hashes.get(item_id)
            if pending_current is not None:
                if incoming in pending_current:
                    skipped += 1
                    continue
                common.error(f"item id collision for '{item_id}' while importing Obsidian vault")
            pending.append(row)
            pending_hashes.setdefault(item_id, set()).add(incoming)
        if pending:
            notesdb.add_joplin_notes(sqlconn, pending)
            inserted += len(pending)
    return inserted, skipped


class _UnchangedNote(NamedTuple):
    """A vault note already stored with the same ID and bytes."""

    path: str


class _ManifestNote(NamedTuple):
    """The fields of a manifest note item the importer uses."""

    id: str
    obsidian_path: str | None
    obsidian_sha256: str | None


class _Manifest(NamedTuple):
    """A version-1 preservation manifest, reduced to what the importer uses.

    A full-library manifest holds over a million items; decoded whole it took
    1.8 GiB.  Only these compact per-item fields are kept: every item's RAW
    path in order, resource IDs, and the note items' paths and digests.
    """

    item_count: int  # items that are objects
    raw_paths: list[str]
    resource_ids: list[str]
    notes: list[_ManifestNote]
    raw_directory: object
    attachments: object


_MANIFEST_FORMAT = "movenotes-lossless-joplin-preservation"
_MANIFEST_LABEL = f"{_PRESERVATION_DIR}/{_MANIFEST_NAME}"
_RAW_DIR_NAME = "joplin-raw"
_JSON_WHITESPACE = frozenset(" \t\n\r")
_JSON_NUMBER_CHARACTERS = "0123456789.eE+-"
# Where the decoder stops in a literal the end of the file cut short.
_JSON_CUT_LITERALS = frozenset({"t", "tr", "tru", "f", "fa", "fal", "fals", "n", "nu", "nul"})


class _ManifestSyntaxError(ValueError):
    """Malformed JSON at a character offset; at_end if the file ended mid-value."""

    def __init__(self, message: str, offset: int, at_end: bool) -> None:
        super().__init__(message)
        self.message = message
        self.offset = offset
        self.at_end = at_end


class _BundleProblem(Exception):
    """Why a .movenotes preservation bundle cannot be imported.

    kind is "unreadable", "syntax", "format", "version", "items",
    "no-manifest" or "unfinished"; it decides which next steps are offered.
    """

    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


class _JsonReader:
    """Read one JSON document a value at a time from a text stream.

    Each value is decoded by the standard decoder, so the result is what
    json.loads would give; only the enclosing object and the item array are
    walked here.  A value that does not fit in the buffer is retried with
    twice the data, so the cost stays linear in its size.
    """

    _CHUNK = 1 << 20

    def __init__(self, stream) -> None:  # noqa: ANN001
        self._stream = stream
        self._decoder = json.JSONDecoder()
        self._buffer = ""
        self._position = 0
        self._offset = 0  # characters read before the buffer
        self._eof = False

    def _fill(self, wanted: int) -> bool:
        if self._eof:
            return False
        chunk = self._stream.read(max(wanted, self._CHUNK))
        if not chunk:
            self._eof = True
            return False
        self._offset += self._position
        self._buffer = self._buffer[self._position:] + chunk
        self._position = 0
        return True

    def fail(self, message: str, position: int | None = None) -> None:
        """Raise _ManifestSyntaxError at position, by default the current one."""
        position = self._position if position is None else position
        rest = self._buffer[position:].rstrip(" \t\n\r")
        cut = self._eof and (rest in _JSON_CUT_LITERALS or not rest.strip(_JSON_NUMBER_CHARACTERS))
        raise _ManifestSyntaxError(message, self._offset + position, cut)

    def peek(self) -> str:
        """Skip whitespace and return the next character, or "" at the end."""
        while True:
            buffer, position = self._buffer, self._position
            while position < len(buffer) and buffer[position] in _JSON_WHITESPACE:
                position += 1
            self._position = position
            if position < len(buffer):
                return buffer[position]
            if not self._fill(0):
                return ""

    def expect(self, character: str) -> None:
        if self.peek() != character:
            self.fail(f"Expecting {character!r}")
        self._position += 1

    def value(self) -> object:
        if self.peek() == "":
            self.fail("Expecting value")
        while True:
            try:
                value, end = self._decoder.raw_decode(self._buffer, self._position)
            except json.JSONDecodeError as exc:
                if self._fill(len(self._buffer) - self._position):
                    continue
                if exc.msg.startswith("Unterminated string"):
                    # The string runs to the end of the file, so the file was cut.
                    raise _ManifestSyntaxError(exc.msg, self._offset + exc.pos, True) from None
                self.fail(exc.msg, exc.pos)
            # A number cut by the end of the buffer ("12" of "123", or "1" of
            # "1.5") decodes early; only what follows it shows that it ended.
            if (
                isinstance(value, (int, float))
                and not self._buffer[end:].strip(_JSON_NUMBER_CHARACTERS)
                and self._fill(len(self._buffer) - self._position)
            ):
                continue
            self._position = end
            return value


def _check_bundle(vault_path: Path) -> _Manifest | None:
    """The vault's preservation manifest, or None for a plain vault.

    A bundle is present when .movenotes holds a manifest, a Joplin RAW copy or
    an export record.  sql2obsidian.py writes them in the reverse order, so
    either of the others without a manifest is an export that did not finish.
    A bundle that cannot be imported raises _BundleProblem.
    """
    root = vault_path / _PRESERVATION_DIR
    manifest_path = root / _MANIFEST_NAME
    if manifest_path.exists() or manifest_path.is_symlink():
        return _load_manifest(manifest_path)
    if (root / _RAW_DIR_NAME).exists():
        raise _BundleProblem(
            "no-manifest",
            f"{_PRESERVATION_DIR}/{_RAW_DIR_NAME}/ is present but {_MANIFEST_LABEL} is not: "
            "the export that wrote the bundle did not finish, or the manifest was removed.",
        )
    if (root / obsidianmeta.EXPORT_RECORD_NAME).exists():
        raise _BundleProblem(
            "unfinished",
            f"{_PRESERVATION_DIR}/{obsidianmeta.EXPORT_RECORD_NAME} is present but there is "
            "no manifest and no Joplin RAW copy: the export that wrote this vault did not finish.",
        )
    return None


def _load_manifest(path: Path) -> _Manifest:
    """Read a preservation manifest; any reason it cannot be imported raises _BundleProblem."""
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            return _read_manifest(_JsonReader(stream))
    except _ManifestSyntaxError as exc:
        raise _BundleProblem("syntax", _describe_syntax_error(path, exc)) from None
    except UnicodeDecodeError:
        raise _BundleProblem("syntax", _describe_invalid_utf8(path)) from None
    except OSError as exc:
        raise _BundleProblem(
            "unreadable", f"{_MANIFEST_LABEL} cannot be read: {exc.strerror or exc}."
        ) from None


def _describe_syntax_error(path: Path, error: _ManifestSyntaxError) -> str:
    size = path.stat().st_size
    if size == 0:
        return f"{_MANIFEST_LABEL} is empty, which is what an interrupted export leaves."
    line = column = 1
    byte_offset = 0
    remaining = error.offset
    with path.open(encoding="utf-8", newline="") as stream:
        while remaining > 0:
            chunk = stream.read(min(remaining, 1 << 20))
            if not chunk:
                break
            remaining -= len(chunk)
            newlines = chunk.count("\n")
            if newlines:
                line += newlines
                column = len(chunk) - chunk.rfind("\n")
            else:
                column += len(chunk)
            byte_offset += len(chunk.encode("utf-8"))
    text = (
        f"{_MANIFEST_LABEL} is not valid JSON: {error.message.removesuffix(' at')} "
        f"at line {line:,}, column {column:,} (byte {byte_offset:,} of {size:,})."
    )
    if error.at_end:
        text += " The file ends in the middle of the document, which is what an interrupted export leaves."
    return text


def _describe_invalid_utf8(path: Path) -> str:
    size = path.stat().st_size
    decoder = codecs.getincrementaldecoder("utf-8")()
    position = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1 << 20)
            pending = len(decoder.getstate()[0])
            try:
                decoder.decode(block, final=not block)
            except UnicodeDecodeError as exc:
                at = position - pending + exc.start
                return f"{_MANIFEST_LABEL} is not valid UTF-8 at byte {at:,} of {size:,}."
            if not block:
                return f"{_MANIFEST_LABEL} is not valid UTF-8."
            position += len(block)


def _json_excerpt(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 80 else text[:77] + "..."


def _read_manifest(reader: _JsonReader) -> _Manifest:
    """Return the manifest's compact form.

    Malformed JSON raises _ManifestSyntaxError where json.loads would raise,
    and a well-formed document that is not an importable manifest raises
    _BundleProblem.  The whole document is read before either is decided.
    """
    first = reader.peek()
    if first == "\ufeff":
        reader.fail("Unexpected UTF-8 byte-order mark")
    if first != "{":
        reader.value()
        if reader.peek() != "":
            reader.fail("Extra data")
        raise _BundleProblem(
            "format", f"{_MANIFEST_LABEL} is not a movenotes preservation manifest: it is not a JSON object."
        )
    reader.expect("{")
    members: dict[str, object] = {}
    items: tuple[int, list[str], list[str], list[_ManifestNote]] | None = (0, [], [], [])
    if reader.peek() == "}":
        reader.expect("}")
    else:
        while True:
            if reader.peek() != '"':
                reader.fail("Expecting property name enclosed in double quotes")
            key = reader.value()
            reader.expect(":")
            if key == "items" and reader.peek() == "[":
                items = _read_manifest_items(reader)
            elif key == "items":
                reader.value()
                items = None
            else:
                members[key] = reader.value()
            if reader.peek() == ",":
                reader.expect(",")
                continue
            reader.expect("}")
            break
    if reader.peek() != "":
        reader.fail("Extra data")
    if members.get("format") != _MANIFEST_FORMAT:
        found = (
            f"its format is {_json_excerpt(members['format'])}" if "format" in members
            else "it has no format field"
        )
        raise _BundleProblem(
            "format", f"{_MANIFEST_LABEL} is not a movenotes preservation manifest: {found}."
        )
    version = members.get("version")
    if type(version) is not int:
        found = f"its version is {_json_excerpt(version)}" if "version" in members else "it has no version"
        raise _BundleProblem("format", f"{_MANIFEST_LABEL} is damaged: {found}, not a whole number.")
    if version != 1:
        raise _BundleProblem(
            "version",
            f"{_MANIFEST_LABEL} is version {version}, and this release of obsidian2sql.py "
            "reads version 1 only.",
        )
    if items is None:
        raise _BundleProblem("items", f"{_MANIFEST_LABEL} is damaged: its items field is not a list.")
    return _Manifest(
        *items,
        raw_directory=members.get("raw_directory", _RAW_DIR_NAME),
        attachments=members.get("attachments", {}),
    )


def _read_manifest_items(
    reader: _JsonReader,
) -> tuple[int, list[str], list[str], list[_ManifestNote]]:
    count = 0
    raw_paths: list[str] = []
    resource_ids: list[str] = []
    notes: list[_ManifestNote] = []
    note_type = int(constants.JoplinType.NOTE)
    resource_type = int(constants.JoplinType.RESOURCE)
    reader.expect("[")
    if reader.peek() == "]":
        reader.expect("]")
        return count, raw_paths, resource_ids, notes
    while True:
        item = reader.value()
        if isinstance(item, dict):
            count += 1
            raw_path = item.get("raw_path")
            if isinstance(raw_path, str):
                raw_paths.append(raw_path)
            item_id = item.get("id")
            if isinstance(item_id, str):
                item_type = item.get("type")
                if item_type == resource_type:
                    resource_ids.append(item_id)
                elif item_type == note_type:
                    path = item.get("obsidian_path")
                    digest = item.get("obsidian_sha256")
                    notes.append(_ManifestNote(
                        item_id,
                        path if isinstance(path, str) else None,
                        digest if isinstance(digest, str) else None,
                    ))
        if reader.peek() == ",":
            reader.expect(",")
            continue
        reader.expect("]")
        return count, raw_paths, resource_ids, notes


def _ancestor_directories(paths: set[str]) -> set[str]:
    result: set[str] = set()
    for value in paths:
        parent = PurePosixPath(value).parent
        while parent != PurePosixPath("."):
            result.add(parent.as_posix())
            parent = parent.parent
    return result


def _import_preserved_joplin(
    vault_path: Path,
    output_path: Path,
    sqlconn: sqlite3.Connection,
    manifest: _Manifest,
    batch_size: int,
    progress_every: int = 1000,
    verbose: bool = False,
) -> tuple[int, int, dict[str, object]]:
    """Import a preservation bundle with bounded parsing and indexed overlays."""
    preservation_root = vault_path / _PRESERVATION_DIR
    item_count = manifest.item_count
    inserted = skipped = processed = 0
    batch: list[dict] = []

    def flush() -> None:
        nonlocal inserted, skipped
        if not batch:
            return
        added, repeated = _insert_rows(sqlconn, batch, batch_size)
        inserted += added
        skipped += repeated
        batch.clear()

    for raw_path in manifest.raw_paths:
        source = preservation_root / raw_path
        if not source.is_file():
            common.error(f"preserved Joplin RAW item not found: '{source}'")
        columns = joplin2sql.prepare_joplin_note(
            joplin2sql.parse_joplin_note(source)
        )
        batch.append(columns)
        processed += 1
        if verbose:
            print(f"processing preserved item '{raw_path}'")
        if len(batch) >= batch_size:
            flush()
        if (
            not verbose
            and progress_every
            and processed % progress_every == 0
        ):
            print(
                f"processed {processed:,} of {item_count:,} "
                "preserved Joplin item(s)"
            )
    flush()
    if (
        not verbose
        and progress_every
        and processed
        and processed % progress_every
    ):
        print(
            f"processed {processed:,} of {item_count:,} "
            "preserved Joplin item(s)"
        )

    raw_resources = (
        preservation_root
        / str(manifest.raw_directory)
        / "resources"
    )
    if raw_resources.is_dir():
        common.copy_resources(
            raw_resources, output_path / "resources", reject_collisions=True
        )

    # Joplin RAW has no place for Notrios' resource-association bookkeeping.
    # Retain only the in-scope resource identities in SQLite so a later vault
    # export can distinguish a deleted resource row from an omitted note target.
    is_notrios_bundle = sqlconn.execute(
        "SELECT 1 FROM notes WHERE joplin_type_=? AND joplin_source=? "
        "AND joplin_source_application=? LIMIT 1",
        (int(constants.JoplinType.NOTE), "movenotes-notrios", "movenotes-notrios2sql"),
    ).fetchone()
    if is_notrios_bundle:
        sqlconn.execute(
            "CREATE TABLE IF NOT EXISTS notrios_preserved_resources "
            "(resource_id TEXT PRIMARY KEY)"
        )
        sqlconn.executemany(
            "INSERT OR IGNORE INTO notrios_preserved_resources(resource_id) VALUES (?)",
            ((resource_id,) for resource_id in manifest.resource_ids),
        )

    # Resolve attachment paths from the manifest and from native-Obsidian
    # metadata carried by resource items.
    attachment_map = manifest.attachments
    if not isinstance(attachment_map, dict):
        attachment_map = {}
    path_to_id = {
        str(path): str(resource_id)
        for resource_id, path in attachment_map.items()
        if isinstance(resource_id, str) and isinstance(path, str)
        and obsidianmeta.safe_relative_path(path) is not None
    }
    # The bundle's attachment map records the names already embedded in exact
    # Notrios vault snapshots.  Keep that presentation metadata in the
    # dedicated Obsidian path column: it must not alter Joplin RAW source
    # properties or application_data.
    for path, resource_id in path_to_id.items():
        sqlconn.execute(
            "UPDATE notes SET note_obsidian_path=? WHERE joplin_id=? AND joplin_type_=?",
            (path, resource_id, int(constants.JoplinType.RESOURCE)),
        )
    for resource_row in sqlconn.execute(
        "SELECT joplin_id, joplin_application_data FROM notes "
        "WHERE joplin_type_ = ?",
        (int(constants.JoplinType.RESOURCE),),
    ):
        original_path = obsidianmeta.path_snapshot(
            resource_row["joplin_application_data"], "resource"
        )
        if original_path is not None:
            path_to_id.setdefault(
                original_path.as_posix(), str(resource_row["joplin_id"])
            )

    represented_paths: set[str] = set(path_to_id)
    external_path_ids: dict[str, str] = dict(path_to_id)
    folder_id_overrides: dict[str, str] = {}

    note_items = manifest.notes

    # A user may rename an Obsidian file. Only scan frontmatter identities when
    # at least one manifest path is missing; ordinary unmodified imports avoid
    # this extra vault pass.
    missing_ids = {
        item.id
        for item in note_items
        if item.obsidian_path is None
        or obsidianmeta.safe_relative_path(item.obsidian_path) is None
        or not (
            vault_path / obsidianmeta.safe_relative_path(item.obsidian_path)
        ).is_file()
    }
    renamed_by_id: dict[str, PurePosixPath] = {}
    if missing_ids:
        for root, dirs, files in os.walk(vault_path):
            root_path = Path(root)
            relative_root = root_path.relative_to(vault_path)
            dirs[:] = [
                directory
                for directory in dirs
                if not (
                    relative_root == Path(".")
                    and directory == _PRESERVATION_DIR
                )
            ]
            for name in files:
                if not name.lower().endswith(".md"):
                    continue
                path = root_path / name
                properties = _property_pairs(
                    _frontmatter_summary(path).get("joplin-properties")
                )
                item_id = dict(properties).get("id")
                if item_id in missing_ids:
                    renamed_by_id[str(item_id)] = PurePosixPath(
                        path.relative_to(vault_path).as_posix()
                    )

    for offset in range(0, len(note_items), batch_size):
        chunk = note_items[offset : offset + batch_size]
        item_ids = [item.id for item in chunk]
        placeholders = ",".join("?" for _ in item_ids)
        rows_by_id = {
            str(row["joplin_id"]): row
            for row in sqlconn.execute(
                "SELECT note_id, joplin_id, joplin_parent_id, note_data, "
                "note_title, joplin_application_data FROM notes "
                f"WHERE joplin_id IN ({placeholders}) ORDER BY note_id",
                item_ids,
            )
        }
        for item in chunk:
            item_id = item.id
            row = rows_by_id.get(item_id)
            if row is None:
                continue
            safe = (
                obsidianmeta.safe_relative_path(item.obsidian_path)
                if item.obsidian_path is not None
                else None
            )
            if safe is None or not (vault_path / safe).is_file():
                safe = renamed_by_id.get(item_id)
            if safe is None:
                continue
            represented_paths.add(safe.as_posix())
            external_path_ids[safe.as_posix()] = item_id
            parent_path = safe.parent.as_posix()
            parent_id = row["joplin_parent_id"]
            if parent_path != "." and parent_id:
                folder_id_overrides.setdefault(parent_path, str(parent_id))
            note_file = vault_path / safe
            raw = note_file.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                common.error(f"'{note_file}' is not valid UTF-8: {exc}")
            frontmatter, obsidian_body = split_frontmatter(text)
            parsed_frontmatter = parse_frontmatter(frontmatter)
            generated_body = row["note_data"] or ""
            expected_sha = item.obsidian_sha256
            edited = (
                expected_sha is not None
                and hashlib.sha256(raw).hexdigest() != expected_sha
            )
            application_data = row["joplin_application_data"] or ""
            title = str(parsed_frontmatter.get("title") or row["note_title"] or note_file.stem)
            if edited:
                local_paths = {safe.as_posix(): item_id, **path_to_id}
                basename_paths: dict[str, list[str]] = defaultdict(list)
                for path in local_paths:
                    basename_paths[PurePosixPath(path).name.casefold()].append(path)
                converted = rewrite_obsidian_links(
                    obsidian_body,
                    safe,
                    local_paths,
                    basename_paths,
                    set(path_to_id),
                )
                generated_body = title + (
                    "\n\n" + converted if converted else ""
                )
                application_data = obsidianmeta.encode_note_application_data(
                    relative_path=safe.as_posix(),
                    raw=raw,
                    generated_joplin_body=generated_body,
                    existing_application_data=application_data,
                )
                sqlconn.execute(
                    "UPDATE notes SET note_data = ?, note_hash = ?, "
                    "note_title = ?, joplin_application_data = ? "
                    "WHERE note_id = ?",
                    (
                        generated_body,
                        hashlib.sha512(generated_body.encode()).hexdigest(),
                        title,
                        application_data,
                        row["note_id"],
                    ),
                )
            sqlconn.execute(
                "UPDATE notes SET note_obsidian_path = ?, note_obsidian_raw = ?, "
                "note_obsidian_sha256 = ?, note_obsidian_body = ?, "
                "note_obsidian_frontmatter = ?, "
                "note_obsidian_joplin_body_sha256 = ? WHERE note_id = ?",
                (
                    safe.as_posix(),
                    raw,
                    hashlib.sha256(raw).digest(),
                    obsidian_body,
                    frontmatter,
                    obsidianmeta.text_sha256(generated_body),
                    row["note_id"],
                ),
            )
    context: dict[str, object] = {
        "represented_paths": represented_paths,
        "known_directories": _ancestor_directories(represented_paths),
        "external_path_ids": external_path_ids,
        "folder_id_overrides": folder_id_overrides,
    }
    return inserted, skipped, context

def _native_rows(
    vault_path: Path,
    output_path: Path,
    *,
    exclude_paths: set[str] | None = None,
    known_directories: set[str] | None = None,
    external_path_ids: dict[str, str] | None = None,
    folder_id_overrides: dict[str, str] | None = None,
    existing_hashes: Callable[[list[str]], dict[str, set[bytes | None]]] | None = None,
    lookahead: int = 500,
):  # noqa: ANN201
    """Return a bounded-memory row iterator and the number of vault files.

    Path/ID indexes are compact and built once. Note bytes are read
    ``lookahead`` files ahead of the rows yielded, so at most that many note
    bodies plus one SQLite batch are held in memory. Attachment bytes remain in
    ``resources/`` rather than being copied into a second SQLite BLOB.

    ``existing_hashes`` is ``_existing_import_hashes`` bound to the output
    database. A note it reports as stored with the same ID and bytes is yielded
    as an ``_UnchangedNote`` instead of a row.
    """
    exclude_paths = exclude_paths or set()
    known_directories = known_directories or set()
    external_path_ids = external_path_ids or {}
    folder_id_overrides = folder_id_overrides or {}
    # Retain the normalized relative path discovered during the inventory
    # walk.  Reconstructing it with Path.relative_to() at every later stage
    # dominated native fresh profiling while adding no semantic information.
    markdown_files: list[tuple[Path, str]] = []
    resource_files: list[tuple[Path, str]] = []
    vault_directories: set[str] = set()
    for root, dirs, files in os.walk(vault_path):
        root_path = Path(root)
        relative_root = root_path.relative_to(vault_path)
        dirs[:] = sorted(
            d
            for d in dirs
            if not (relative_root == Path(".") and d == _PRESERVATION_DIR)
        )
        for directory in dirs:
            relative_directory = (relative_root / directory).as_posix()
            if (
                relative_directory != "."
                and relative_directory not in known_directories
            ):
                vault_directories.add(relative_directory)
        for name in sorted(files):
            path = root_path / name
            relative = path.relative_to(vault_path)
            relative_text = relative.as_posix()
            if relative.parts and relative.parts[0] == _PRESERVATION_DIR:
                continue
            if relative_text in exclude_paths:
                continue
            if path.suffix.lower() == ".md":
                markdown_files.append((path, relative_text))
            else:
                resource_files.append((path, relative_text))

    frontmatter_identity: dict[str, tuple[str | None, str | None]] = {}
    for path, relative in markdown_files:
        properties = _property_pairs(
            _frontmatter_summary(path).get("joplin-properties")
        )
        effective = dict(properties)
        item_id = effective.get("id")
        parent_id = effective.get("parent_id")
        frontmatter_identity[relative] = (item_id, parent_id)

    note_ids = {
        relative: (
            frontmatter_identity[relative][0]
            or obsidianmeta.deterministic_id(
                "note", relative
            )
        )
        for _path, relative in markdown_files
    }
    resource_ids = {
        relative: obsidianmeta.deterministic_id(
            "resource", relative
        )
        for _path, relative in resource_files
    }
    all_path_ids = {**external_path_ids, **note_ids, **resource_ids}
    basename_paths: dict[str, list[str]] = defaultdict(list)
    for relative in all_path_ids:
        basename_paths[PurePosixPath(relative).name.casefold()].append(relative)

    folder_paths: set[str] = set(vault_directories)
    note_parent_paths: set[str] = set()
    for relative in note_ids:
        parent = PurePosixPath(relative).parent
        if parent != PurePosixPath("."):
            note_parent_paths.add(parent.as_posix())
        while parent != PurePosixPath("."):
            folder_paths.add(parent.as_posix())
            parent = parent.parent
    folder_id_candidates: dict[str, set[str]] = defaultdict(set)
    for relative, (_item_id, parent_id) in frontmatter_identity.items():
        folder_path = PurePosixPath(relative).parent.as_posix()
        if folder_path != "." and parent_id:
            folder_id_candidates[folder_path].add(parent_id)
    folder_ids = dict(folder_id_overrides)
    for path in folder_paths:
        if path in folder_ids:
            continue
        candidates = folder_id_candidates.get(path, set())
        folder_ids[path] = (
            next(iter(candidates))
            if len(candidates) == 1
            else obsidianmeta.deterministic_id("folder", path)
        )
    folder_rows = {
        path
        for path in folder_paths
        if path not in folder_id_overrides
        and (path not in known_directories or path in note_parent_paths)
    }

    def note_row(
        source: Path, relative: str, raw: bytes, frontmatter: str,
        obsidian_body: str, parsed: dict[str, object],
        properties: list[tuple[str, str]], note_id: str,
    ) -> dict:
        title = str(parsed.get("title") or source.stem)
        timestamp = str(parsed.get("created") or _iso_timestamp(source))
        updated = str(parsed.get("updated") or timestamp)
        source_url = str(parsed.get("source-url") or "")
        parent_id = folder_ids.get(
            PurePosixPath(relative).parent.as_posix(), ""
        )
        converted = rewrite_obsidian_links(
            obsidian_body,
            PurePosixPath(relative),
            all_path_ids,
            basename_paths,
            set(resource_ids),
        )
        generated_body = title + ("\n\n" + converted if converted else "")
        existing_app = ""
        if properties:
            effective = dict(properties)
            note_id = effective.get("id", note_id)
            parent_id = effective.get("parent_id", parent_id)
            existing_app = effective.get("application_data", "")
        app_data = obsidianmeta.encode_note_application_data(
            relative_path=relative,
            raw=raw,
            generated_joplin_body=generated_body,
            existing_application_data=existing_app,
        )
        if not properties:
            properties = _generated_properties(
                item_id=note_id,
                item_type=int(constants.JoplinType.NOTE),
                timestamp=timestamp,
                parent_id=parent_id,
                application_data=app_data,
            )
        else:
            properties = [
                (key, app_data if key == "application_data" else value)
                for key, value in properties
            ]
            if not any(key == "application_data" for key, _value in properties):
                properties.insert(-1, ("application_data", app_data))
            properties = [
                (
                    key,
                    source_url
                    if key == "source_url" and source_url
                    else value,
                )
                for key, value in properties
            ]
        row = _columns_from_properties(
            properties=properties,
            body=generated_body,
            title=title,
            source_path=relative,
            raw=raw,
            frontmatter=frontmatter,
            obsidian_body=obsidian_body,
            application_data_override=app_data,
        )
        row["joplin_id"] = note_id
        row["note_uuid"] = note_id
        row["joplin_parent_id"] = parent_id
        row["note_parent_uuid"] = parent_id
        row["joplin_created_time"] = row.get("joplin_created_time") or timestamp
        row["joplin_updated_time"] = row.get("joplin_updated_time") or updated
        row["joplin_source_url"] = row.get("joplin_source_url") or source_url
        return row

    def generate():  # noqa: ANN202
        tag_ids: dict[str, str] = {}
        note_tag_pairs: list[tuple[str, str, str]] = []

        # Folder rows are shallow-to-deep so their direct parent is known.
        for relative in sorted(
            folder_rows,
            key=lambda value: (len(PurePosixPath(value).parts), value.casefold()),
        ):
            path = PurePosixPath(relative)
            folder_id = folder_ids[relative]
            parent_id = folder_ids.get(path.parent.as_posix(), "")
            timestamp = _iso_timestamp(vault_path / path)
            app_data = obsidianmeta.encode_path_application_data(
                kind="folder", relative_path=relative
            )
            properties = _generated_properties(
                item_id=folder_id,
                item_type=int(constants.JoplinType.FOLDER),
                timestamp=timestamp,
                parent_id=parent_id,
                application_data=app_data,
            )
            yield _columns_from_properties(
                properties=properties,
                body=path.name,
                title=path.name,
                source_path=relative,
                raw=None,
                application_data_override=app_data,
            )

        for source, relative in resource_files:
            resource_id = resource_ids[relative]
            content_digest = _file_sha256(source)
            content_size = source.stat().st_size
            destination = _copy_resource(
                source, output_path / "resources", resource_id
            )
            mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            extension = source.suffix.lstrip(".").lower()
            timestamp = _iso_timestamp(source)
            app_data = obsidianmeta.encode_path_application_data(
                kind="resource", relative_path=relative
            )
            properties = _generated_properties(
                item_id=resource_id,
                item_type=int(constants.JoplinType.RESOURCE),
                timestamp=timestamp,
                application_data=app_data,
                title=source.name,
                mime=mime,
                filename=source.name,
                extension=extension,
                size=content_size,
            )
            row = _columns_from_properties(
                properties=properties,
                body=source.name,
                title=source.name,
                source_path=relative,
                raw=None,
                application_data_override=app_data,
            )
            row["note_source_raw"] = None
            row["note_source_sha256"] = None
            row["note_obsidian_raw"] = None
            row["note_obsidian_sha256"] = content_digest
            row["note_source_filename"] = destination.name
            yield row

        for start in range(0, len(markdown_files), lookahead):
            # Read one batch of notes ahead and ask the database once whether
            # each is already stored with the same ID and bytes.  That is the
            # test _insert_rows applies, and the database only gains rows
            # before the batch reaches it, so a note found unchanged here
            # would be skipped there too; converting it would be wasted work.
            # Its tags are still collected below.  A file that cannot be read
            # or decoded stops the read-ahead, and its error is raised in file
            # order, after the notes before it have been yielded.
            notes = []
            failure = None
            for source, relative in markdown_files[start:start + lookahead]:
                try:
                    raw = source.read_bytes()
                    text = raw.decode("utf-8-sig")
                    frontmatter, obsidian_body = split_frontmatter(text)
                    parsed = parse_frontmatter(frontmatter)
                except Exception as exc:  # noqa: BLE001 - re-raised in order below
                    failure = (source, exc)
                    break
                properties = _property_pairs(parsed.get("joplin-properties"))
                note_id = note_ids[relative]
                if properties:
                    note_id = dict(properties).get("id", note_id)
                notes.append(
                    (source, relative, raw, frontmatter, obsidian_body, parsed,
                     properties, note_id)
                )
            stored = (
                existing_hashes([str(note[-1]) for note in notes])
                if existing_hashes is not None and notes
                else {}
            )
            for (
                source, relative, raw, frontmatter, obsidian_body, parsed,
                properties, note_id,
            ) in notes:
                if hashlib.sha256(raw).digest() in stored.get(str(note_id), ()):
                    yield _UnchangedNote(relative)
                else:
                    yield note_row(
                        source, relative, raw, frontmatter, obsidian_body,
                        parsed, properties, note_ids[relative],
                    )
                tags = parsed.get("tags")
                if isinstance(tags, list):
                    for tag in tags:
                        tag_name = str(tag).lstrip("#").strip()
                        if not tag_name:
                            continue
                        tag_id = tag_ids.setdefault(
                            tag_name,
                            obsidianmeta.deterministic_id("tag", tag_name),
                        )
                        note_tag_pairs.append((note_id, tag_id, tag_name))
            if failure is not None:
                source, exc = failure
                if isinstance(exc, UnicodeDecodeError):
                    common.error(f"'{source}' is not valid UTF-8: {exc}")
                raise exc

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for tag_name, tag_id in sorted(
            tag_ids.items(), key=lambda entry: entry[0].casefold()
        ):
            properties = _generated_properties(
                item_id=tag_id,
                item_type=int(constants.JoplinType.TAG),
                timestamp=timestamp,
            )
            yield _columns_from_properties(
                properties=properties,
                body=tag_name,
                title=tag_name,
                source_path=f".movenotes/tags/{tag_id}",
                raw=None,
            )
        for note_id, tag_id, tag_name in note_tag_pairs:
            relation_id = obsidianmeta.deterministic_id(
                "note-tag", f"{note_id}:{tag_id}"
            )
            properties = [
                ("id", relation_id),
                ("note_id", note_id),
                ("tag_id", tag_id),
                ("created_time", timestamp),
                ("updated_time", timestamp),
                ("user_data", ""),
                ("type_", str(int(constants.JoplinType.NOTE_TAG))),
            ]
            yield _columns_from_properties(
                properties=properties,
                body="",
                title=f"{tag_name} relation",
                source_path=f".movenotes/note-tags/{relation_id}",
                raw=None,
            )

    return generate(), len(markdown_files) + len(resource_files)


_SOURCE_PLACEHOLDER = "SOURCE_LIBRARY"


def _printable(text: str) -> bool:
    """No control characters, which could rewrite the terminal around them."""
    return not any(ord(character) < 0x20 or 0x7F <= ord(character) < 0xA0 for character in text)


def _invocation(argv: list[str]) -> tuple[list[str], list[str], Callable[[str], str]]:
    """How this run was started, for printing commands the user can run next.

    Returns the interpreter with its flags, the words that ran this script, and
    a function naming a sibling script the same way.  sys.orig_argv holds the
    command as typed; when main() was called some other way it does not end
    with argv, and the interpreter and this file's absolute path stand in.
    """
    original = list(getattr(sys, "orig_argv", None) or [])
    head = original[: len(original) - len(argv)]
    here = Path(__file__).resolve()
    if original[len(head):] == argv and len(head) >= 2:
        if Path(head[-1]).name == here.name:
            script = head[-1]
            return head[:-1], head, lambda name: str(Path(script).with_name(name))
        if len(head) >= 3 and head[-2] == "-m":
            return head[:-2], head, lambda name: str(here.with_name(name))
    return [sys.executable], [sys.executable, str(here)], lambda name: str(here.with_name(name))


def _suggested_directory(vault_path: Path) -> Path:
    candidate = vault_path.with_name(f"{vault_path.name}-reexport")
    number = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = vault_path.with_name(f"{vault_path.name}-reexport-{number}")
        number += 1
    return candidate


def _recorded_export(root: Path) -> tuple[str, list[str], str, list[str]]:
    """The source library and sql2obsidian.py options of the export, from its record.

    Returns the --input word, the options, a comment for the command line and
    notes to print under it.  The record may come from someone else's vault, so
    its values are only ever printed, shell-quoted, never run.
    """
    label = f"{_PRESERVATION_DIR}/{obsidianmeta.EXPORT_RECORD_NAME}"
    explain = (
        f"{_SOURCE_PLACEHOLDER} is the directory that was given to sql2obsidian.py --input "
        f"when this vault was exported; it holds {notesdb.DATABASE_FILENAME}."
    )
    unknown_options = (
        " Add the options that export used, if any: --notebooks, --no-frontmatter, "
        "--no-simplify-urls, --include-notrios-receipt."
    )
    path = root / obsidianmeta.EXPORT_RECORD_NAME
    if not path.exists():
        return _SOURCE_PLACEHOLDER, [], "", [
            explain + " This vault has no export record, so it is not known here." + unknown_options
        ]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc)
    else:
        reason = "it is not a version-1 movenotes export record"
        options = record.get("options") if isinstance(record, dict) else None
        if (
            isinstance(record, dict)
            and record.get("format") == obsidianmeta.EXPORT_RECORD_FORMAT
            and type(record.get("version")) is int
            and record["version"] == 1
            and isinstance(options, dict)
        ):
            source = obsidianmeta.expand_portable_path(record.get("source_database"))
            notebooks = options.get("notebooks")
            flags = {
                "--no-frontmatter": options.get("frontmatter"),
                "--no-simplify-urls": options.get("simplify_urls"),
                "--include-notrios-receipt": options.get("include_notrios_receipt"),
            }
            if (
                source is not None
                and _printable(str(source))
                and (notebooks is None or isinstance(notebooks, list) and all(
                    isinstance(value, str) and _printable(value) for value in notebooks
                ))
                and all(isinstance(value, bool) for value in flags.values())
            ):
                words: list[str] = []
                for value in notebooks or []:
                    # "--notebooks=-x", or argparse takes "-x" for an option.
                    words += [f"--notebooks={value}"] if value.startswith("-") else ["--notebooks", value]
                words += [flag for flag in ("--no-frontmatter", "--no-simplify-urls") if not flags[flag]]
                if flags["--include-notrios-receipt"]:
                    words.append("--include-notrios-receipt")
                comment = "" if (source / notesdb.DATABASE_FILENAME).is_file() else (
                    "  # source library recorded when the vault was exported; not found here"
                )
                return str(source), words, comment, []
            reason = "its source library or options are malformed"
    return _SOURCE_PLACEHOLDER, [], "", [
        explain + f" The export record, {label}, cannot be read ({reason}), so it is not known here."
        + unknown_options
    ]


def _refusal(
    problem: _BundleProblem,
    vault_path: Path,
    output_path: Path,
    args: argparse.Namespace,
    argv: list[str],
) -> str:
    """The error for a damaged bundle, with the commands that can follow it."""
    interpreter, this_script, sibling = _invocation(argv)
    original = this_script + list(argv)
    root = vault_path / _PRESERVATION_DIR
    raw_copy = root / _RAW_DIR_NAME
    steps: list[tuple[str, list[str], list[str]]] = []
    if problem.kind == "version":
        steps.append((
            "Update movenotes to a release that reads this manifest version, then rerun this command:",
            [shlex.join(original)], [],
        ))
    elif problem.kind != "unfinished":
        steps.append((
            f"Restore {_MANIFEST_LABEL} from a backup, then rerun this command:",
            [shlex.join(original)], [],
        ))
    if raw_copy.is_dir():
        steps.append((
            "Import the Joplin RAW copy instead. It is lossless for the export, "
            "but leaves out any Obsidian edits made since:",
            [shlex.join(interpreter + [
                sibling("joplin2sql.py"), "--input", str(raw_copy), "--output", str(output_path),
            ])], [],
        ))
    steps.append((
        "Import the vault as plain Obsidian notes. This keeps edits made since the export, "
        "but drops the Joplin-only items and properties the bundle holds:",
        [shlex.join(original + ["--ignore-preservation"])], [],
    ))
    target = _suggested_directory(vault_path)
    source, export_options, comment, notes = _recorded_export(root)
    parser = _build_argument_parser()
    import_options: list[str] = []
    if args.batch_size != parser.get_default("batch_size"):
        import_options += ["--batch-size", str(args.batch_size)]
    if args.progress_every != parser.get_default("progress_every"):
        import_options += ["--progress-every", str(args.progress_every)]
    if args.verbose:
        import_options.append("--verbose")
    steps.append((
        "Export the source library again into a new directory and import that. "
        "This leaves out any edits made since the export:",
        [
            f"mkdir {shlex.quote(str(target))}  # suggested; any new empty directory works",
            shlex.join(interpreter + [
                sibling("sql2obsidian.py"), "--input", source, "--output", str(target),
            ] + export_options) + comment,
            shlex.join(this_script + [
                "--input", str(target), "--output", str(output_path),
            ] + import_options),
        ],
        notes,
    ))
    lines = [
        f"cannot import '{vault_path}': its movenotes preservation bundle is damaged.",
        problem.reason,
        "Nothing was imported.",
        "",
        "Next steps, any one of:",
    ]
    for number, (title, commands, step_notes) in enumerate(steps, 1):
        lines += ["", f"{number}. {title}"]
        lines += [f"     {command}" for command in commands]
        lines += [f"   {note}" for note in step_notes]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)
    if args.batch_size < 1:
        common.error("--batch-size must be at least 1")
    if args.progress_every < 0:
        common.error("--progress-every cannot be negative")
    vault_path: Path = args.input_path
    output_path: Path = args.output_path
    manifest = None
    if not args.ignore_preservation:
        # Before the output is touched, so a refusal writes nothing.
        try:
            manifest = _check_bundle(vault_path)
        except _BundleProblem as problem:
            common.error(_refusal(problem, vault_path, output_path, args, argv))
    database_path = output_path / notesdb.DATABASE_FILENAME
    new_database = not database_path.is_file()
    if new_database:
        sqlconn = notesdb.connect(database_path)
        notesdb.create_database(sqlconn, create_indexes=False)
        # Every batch looks up its item IDs before inserting; without this
        # index each lookup scans the rows already imported, which is
        # quadratic over a large vault.  The other indexes still wait for the
        # final pass.
        notesdb.ensure_joplin_id_index(sqlconn)
    else:
        sqlconn = notesdb.open_database(database_path, __program_name__)
        if sqlconn.execute("SELECT 1 FROM notes LIMIT 1").fetchone() is None:
            # A library with no rows, such as an interrupted fresh import
            # leaves, is imported like a new database: maintaining the other
            # indexes row by row made it up to 48% slower.  The final pass
            # rebuilds them, and so does the next open if this run stops.
            notesdb.drop_deferred_indexes(sqlconn)
    output_path.joinpath("resources").mkdir(parents=True, exist_ok=True)

    try:
        inserted = skipped = 0

        def stored_hashes(item_ids: list[str]) -> dict[str, set[bytes | None]]:
            return _existing_import_hashes(sqlconn, item_ids)

        def import_native_rows(rows, file_count: int) -> tuple[int, int]:  # noqa: ANN001
            batch: list[dict] = []
            added_total = skipped_total = files_processed = 0
            next_progress = args.progress_every if args.progress_every else 0

            # A note found unchanged before conversion still takes its slot, so
            # batches close where they would if its row had been built, and the
            # remaining rows meet _insert_rows' checks at the same points.
            batch_slots = 0

            def flush_native_batch() -> None:
                nonlocal added_total, skipped_total, batch_slots
                batch_slots = 0
                if not batch:
                    return
                added, repeated = _insert_rows(sqlconn, batch, args.batch_size)
                added_total += added
                skipped_total += repeated
                batch.clear()

            for row in rows:
                unchanged = isinstance(row, _UnchangedNote)
                if unchanged:
                    source_path = row.path
                    files_processed += 1
                    skipped_total += 1
                else:
                    item_type = row.get("joplin_type_")
                    source_path = str(row.get("note_obsidian_path") or "")
                    is_vault_file = item_type in {
                        int(constants.JoplinType.NOTE),
                        int(constants.JoplinType.RESOURCE),
                    } and not source_path.startswith(".movenotes/")
                    if is_vault_file:
                        files_processed += 1
                if args.verbose:
                    print(f"processing '{source_path or row.get('note_title')}'")
                if not unchanged:
                    batch.append(row)
                batch_slots += 1
                if batch_slots >= args.batch_size:
                    flush_native_batch()
                if (
                    not args.verbose
                    and next_progress
                    and files_processed >= next_progress
                ):
                    print(
                        f"processed {files_processed:,} of {file_count:,} "
                        "Obsidian vault file(s)"
                    )
                    while next_progress <= files_processed:
                        next_progress += args.progress_every
            flush_native_batch()
            if (
                not args.verbose
                and args.progress_every
                and files_processed
                and files_processed % args.progress_every
            ):
                print(
                    f"processed {files_processed:,} of {file_count:,} "
                    "Obsidian vault file(s)"
                )
            return added_total, skipped_total

        if manifest is not None:
            preserved_inserted, preserved_skipped, context = _import_preserved_joplin(
                vault_path, output_path, sqlconn, manifest, args.batch_size,
                args.progress_every, args.verbose,
            )
            inserted += preserved_inserted
            skipped += preserved_skipped
            rows, file_count = _native_rows(
                vault_path,
                output_path,
                exclude_paths=set(context["represented_paths"]),
                known_directories=set(context["known_directories"]),
                external_path_ids=dict(context["external_path_ids"]),
                folder_id_overrides=dict(context["folder_id_overrides"]),
                existing_hashes=stored_hashes,
                lookahead=args.batch_size,
            )
            native_inserted, native_skipped = import_native_rows(rows, file_count)
            inserted += native_inserted
            skipped += native_skipped
            source_description = "Joplin preservation bundle"
            if file_count:
                source_description += f" plus {file_count:,} additional Obsidian vault file(s)"
        else:
            rows, file_count = _native_rows(
                vault_path, output_path,
                existing_hashes=stored_hashes, lookahead=args.batch_size,
            )
            inserted, skipped = import_native_rows(rows, file_count)
            source_description = f"native Obsidian vault ({file_count:,} file(s))"
        notesdb.ensure_joplin_id_index(sqlconn)
        notesdb.populate_missing_note_folders(sqlconn)
        notesdb.ensure_indexes(sqlconn)
        sqlconn.commit()
    except Exception:
        sqlconn.rollback()
        raise
    finally:
        sqlconn.close()
    print(f"imported {inserted:,} item(s) from {source_description}; {skipped:,} unchanged item(s) skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
