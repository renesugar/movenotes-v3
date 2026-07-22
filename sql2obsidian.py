#!/usr/bin/env python3
"""Export a SQLite notes database to an Obsidian vault.

Notebooks become vault subdirectories and notes become "Title.md" files.
Unlike Joplin, Obsidian identifies notes by their file names, so titles are
sanitized for the filesystem and duplicate titles within a folder are
deduplicated ("Title.md", "Title 2.md", ...). Attachments are copied to an
"attachments" folder; Joplin resource links are rewritten to wiki-style
embeds for images and relative markdown links for other files. Common Joplin
metadata maps to YAML properties, all source properties remain namespaced, and
a lossless Joplin RAW preservation bundle is stored under ``.movenotes``.
"""

#
# MIT License
#
# https://opensource.org/licenses/MIT
#
# Copyright 2020 Rene Sugar
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import urllib.parse
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath

import common
import constants
import notesdb
import obsidianmeta

__program_name__ = "sql2obsidian"
__author__ = "Rene Sugar"
__version__ = "3.20"
__license__ = "MIT License (https://opensource.org/licenses/MIT)"
__website__ = "https://github.com/renesugar"

ATTACHMENTS_DIR_NAME = "attachments"
PRESERVATION_DIR_NAME = ".movenotes"
PRESERVED_RAW_DIR_NAME = "joplin-raw"

# Characters not allowed in Obsidian note names (a superset of the
# Windows-illegal set; #, ^, [, ] and | also break Obsidian wiki links).
_ILLEGAL_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|#^\[\]]')

# Windows reserved device names cannot be used as file names.
_WINDOWS_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

_MAX_NAME_LENGTH = 100
_MAX_FILENAME_BYTES = 240

_IMAGE_EXTENSIONS = frozenset(
    ["png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "avif"]
)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=__program_name__, description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        type=common.existing_dir,
        required=True,
        help="Path to the input SQLite directory",
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        type=common.existing_dir,
        required=True,
        help="Path to the output Obsidian vault directory",
    )
    parser.add_argument(
        "--no-simplify-urls",
        dest="simplify_urls",
        action="store_false",
        help=(
            "Keep URL-only markdown links ([https://x](https://x), <https://x>) "
            "as-is instead of simplifying them to bare URLs"
        ),
    )
    parser.add_argument(
        "--no-frontmatter",
        dest="frontmatter",
        action="store_false",
        help=(
            "Do not add YAML front matter (mapped Obsidian properties and "
            "namespaced Joplin metadata) to exported notes"
        ),
    )
    parser.add_argument(
        "--no-preserve-joplin",
        dest="preserve_joplin",
        action="store_false",
        help=(
            "Do not write the lossless .movenotes/joplin-raw preservation "
            "bundle (enabled by default)"
        ),
    )
    parser.add_argument(
        "--notebooks",
        dest="notebooks",
        action="append",
        metavar="NAMES",
        help=(
            "Export only these notebooks (comma-separated titles, exact "
            "match) and all their subnotebooks; may be given multiple "
            "times. Each selected notebook becomes a top-level vault "
            "directory, and only attachments referenced by exported notes "
            "are copied. Useful for publishing a public subset of notes "
            "(e.g. with Quartz) without exporting private notebooks."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N exported notes; 0 disables it (default: 1000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every exported note path instead of periodic progress",
    )
    return parser


def _truncate_utf8(value: str, maximum_bytes: int) -> str:
    """Truncate without splitting a UTF-8 code point."""
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore")


def _fit_filename(stem: str, suffix: str, extra: str = "") -> str:
    budget = max(_MAX_FILENAME_BYTES - len((extra + suffix).encode("utf-8")), 1)
    fitted = _truncate_utf8(stem, budget).rstrip(". ") or constants.NOTES_UNTITLED
    return fitted + extra + suffix


def sanitize_name(name: str | None) -> str:
    """Make a note or notebook title safe to use as a file/directory name."""
    name = common.remove_line_breakers(name or "") or ""
    name = _ILLEGAL_FILENAME_CHARS_RE.sub(" ", name)
    name = " ".join(name.split())  # collapse runs of whitespace
    name = name.strip(". ")  # names may not start/end with dots or spaces
    if len(name) > _MAX_NAME_LENGTH:
        name = name[:_MAX_NAME_LENGTH].rstrip(". ")
    name = _truncate_utf8(name, _MAX_FILENAME_BYTES).rstrip(". ")
    if not name:
        name = constants.NOTES_UNTITLED
    if name.upper() in _WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    return name


class NameDeduplicator:
    """Assign unique names within each directory, case-insensitively.

    Case-insensitive because the vault may be synced to case-insensitive
    filesystems (Windows, macOS).
    """

    def __init__(self) -> None:
        self._used: dict[str, set[str]] = defaultdict(set)
        self._next_counter: dict[tuple[str, str, str, str], int] = {}

    def reserve(
        self, directory: str, name: str, suffix: str = "", separator: str = " "
    ) -> str:
        """Return *name* (plus *suffix*), made unique within *directory*."""
        used = self._used[directory]
        candidate = _fit_filename(name, suffix)
        key = (directory, name.lower(), suffix.lower(), separator)
        counter = self._next_counter.get(key, 2)
        while candidate.lower() in used:
            extra = f"{separator}{counter}"
            candidate = _fit_filename(name, suffix, extra)
            counter += 1
        used.add(candidate.lower())
        self._next_counter[key] = counter
        return candidate


def select_notebooks(
    folders: list[sqlite3.Row], notebook_args: list[str] | None
) -> set[str] | None:
    """Resolve --notebooks arguments to a set of folder ids to export.

    Returns None when no filtering was requested. Each named notebook is
    included together with all its subnotebooks. Unknown names are an
    error, so a typo cannot silently publish (or omit) the wrong notes.
    """
    if not notebook_args:
        return None
    names = [
        name.strip()
        for arg in notebook_args
        for name in arg.split(",")
        if name.strip()
    ]
    if not names:
        common.error("--notebooks was given but no notebook names were provided")

    by_title: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    for row in folders:
        by_title[row["note_title"]].append(row["joplin_id"])
        children[row["joplin_parent_id"]].append(row["joplin_id"])

    selected: set[str] = set()
    for name in names:
        folder_ids = by_title.get(name)
        if not folder_ids:
            known = ", ".join(sorted(f"'{t}'" for t in by_title))
            common.error(f"notebook '{name}' not found; notebooks are: {known}")
        queue = list(folder_ids)
        while queue:  # include all subnotebooks
            folder_id = queue.pop()
            if folder_id not in selected:
                selected.add(folder_id)
                queue.extend(children[folder_id])
    return selected


def build_folder_paths(
    folders: list[sqlite3.Row],
    dedup: NameDeduplicator,
    selected: set[str] | None = None,
) -> dict[str, PurePosixPath]:
    """Map each folder id to its vault-relative directory path.

    Notebook nesting is preserved. Folders with a missing parent (or in a
    parent cycle) are placed at the vault root. When *selected* is given,
    only those folders are mapped, and selected notebooks whose parent is
    not itself selected are re-rooted to the vault root — so exporting a
    nested notebook does not expose its parent notebooks' names.
    """
    by_id = {row["joplin_id"]: row for row in folders}
    resolved: dict[str, PurePosixPath] = {}

    def resolve(folder_id: str, seen: set[str]) -> PurePosixPath:
        if folder_id in resolved:
            return resolved[folder_id]
        row = by_id[folder_id]
        parent_id = row["joplin_parent_id"]
        in_scope = parent_id in by_id and (selected is None or parent_id in selected)
        if in_scope and parent_id not in seen:
            parent_path = resolve(parent_id, seen | {folder_id})
        else:
            parent_path = PurePosixPath(".")
        name = dedup.reserve(str(parent_path), sanitize_name(row["note_title"]))
        path = parent_path / name
        resolved[folder_id] = path
        return path

    for folder_id in by_id:
        if selected is None or folder_id in selected:
            resolve(folder_id, {folder_id})
    return resolved


def load_note_tags(sqlcur: sqlite3.Cursor) -> dict[str, list[str]]:
    """Map note ids to their sorted Joplin tag titles."""
    tag_titles = {
        row["joplin_id"]: row["note_title"]
        for row in sqlcur.execute(
            "SELECT joplin_id, note_title FROM notes WHERE joplin_type_ = ?",
            (int(constants.JoplinType.TAG),),
        )
    }
    note_tags: dict[str, list[str]] = defaultdict(list)
    for row in sqlcur.execute(
        "SELECT joplin_note_id, joplin_tag_id FROM notes WHERE joplin_type_ = ?",
        (int(constants.JoplinType.NOTE_TAG),),
    ):
        title = tag_titles.get(row["joplin_tag_id"])
        if title:
            note_tags[row["joplin_note_id"]].append(title)
    return {note_id: sorted(titles) for note_id, titles in note_tags.items()}


class AttachmentTable:
    """Assigns vault file names to Joplin resources and copies them."""

    def __init__(
        self,
        sqlcur: sqlite3.Cursor,
        input_resources_path: Path,
        vault_path: Path,
        dedup: NameDeduplicator,
    ) -> None:
        self._input_resources_path = input_resources_path
        self._attachments_path = vault_path / ATTACHMENTS_DIR_NAME
        self._dedup = dedup
        self._names: dict[str, str] = {}
        self._copied: set[str] = set()
        self.vault_paths: dict[str, str] = {}
        self.copied_count = 0
        self._resource_files: dict[str, list[Path]] = defaultdict(list)
        if self._input_resources_path.is_dir():
            for path in sorted(self._input_resources_path.iterdir()):
                if path.is_file():
                    resource_id = path.name.split(".", 1)[0]
                    self._resource_files[resource_id].append(path)
        self._resources = {
            row["joplin_id"]: row
            for row in sqlcur.execute(
                "SELECT joplin_id, note_title, joplin_file_extension, joplin_mime "
                "FROM notes WHERE joplin_type_ = ?",
                (int(constants.JoplinType.RESOURCE),),
            )
        }

    def _source_file(self, resource_id: str, extension: str) -> Path | None:
        candidate = self._input_resources_path / (
            f"{resource_id}.{extension}" if extension else resource_id
        )
        if candidate.is_file():
            return candidate
        # Fall back to any file named after the resource id.
        candidates = self._resource_files.get(resource_id)
        return candidates[0] if candidates else None

    def is_image(self, resource_id: str) -> bool:
        row = self._resources.get(resource_id)
        if row is None:
            return False
        mime = row["joplin_mime"] or ""
        if mime.startswith("image/"):
            return True
        extension = (row["joplin_file_extension"] or "").lower()
        return extension in _IMAGE_EXTENSIONS

    def vault_name(self, resource_id: str) -> str | None:
        """Return the attachment's vault file name, copying it on first use.

        Returns None for resource ids not present in the database.
        """
        if resource_id in self._names:
            return self._names[resource_id]
        row = self._resources.get(resource_id)
        if row is None:
            return None

        extension = (row["joplin_file_extension"] or "").lower()
        source = self._source_file(resource_id, extension)
        if source is not None and not extension:
            extension = source.suffix.lstrip(".")

        # Prefer the resource's human-readable title for the file name.
        title = sanitize_name(row["note_title"])
        stem = title.removesuffix(f".{extension}") if extension else title
        suffix = f".{extension}" if extension else ""
        name = self._dedup.reserve(ATTACHMENTS_DIR_NAME, stem, suffix)
        self._names[resource_id] = name
        self.vault_paths[resource_id] = str((PurePosixPath(ATTACHMENTS_DIR_NAME) / name).as_posix())

        if source is not None and resource_id not in self._copied:
            self._attachments_path.mkdir(parents=True, exist_ok=True)
            if common.copy_file_if_changed(source, self._attachments_path, name):
                self.copied_count += 1
            self._copied.add(resource_id)
        return name


def rewrite_resource_links(
    body: str, note_dir: PurePosixPath, attachments: AttachmentTable
) -> str:
    """Rewrite Joplin ``(:/resource_id)`` links for Obsidian.

    Images become wiki-style embeds (``![[file.png]]``); other files become
    markdown links with a path relative to the note's directory.
    """

    def replace(match: re.Match) -> str:
        link, display, resource_id = match.group(0), match.group(1), match.group(2)
        name = attachments.vault_name(resource_id)
        if name is None:
            return link  # Unknown resource: leave the link unchanged.
        if link.startswith("!") and attachments.is_image(resource_id):
            return f"![[{name}]]"
        relative_dir = PurePosixPath(
            *([".."] * len(note_dir.parts))
        ) / ATTACHMENTS_DIR_NAME
        href = urllib.parse.quote(str(relative_dir / name))
        display = display or name
        return f"[{display}]({href})"

    return common.RESOURCE_LINK_RE.sub(replace, body)


def _yaml_string(value: str) -> str:
    """Return a JSON string literal, which is also a safe YAML scalar."""
    return json.dumps(value, ensure_ascii=False)


def build_frontmatter(row: sqlite3.Row, tags: list[str]) -> str:
    """Build Obsidian YAML properties without discarding Joplin metadata.

    Common fields are mapped to convenient Obsidian properties. Every Joplin
    property is exposed in three compatible forms:

    * legacy flat ``joplin-*`` fields for existing vault consumers;
    * a structured ``joplin`` JSON object that Obsidian's REST API can return
      directly as frontmatter data without reparsing sanitized key names; and
    * ``joplin-properties``, an ordered array of pairs that retains duplicate
      keys exactly. ``joplin-properties-json`` remains as a compatibility
      string for earlier movenotes exports.
    """
    lines = ["---"]
    if row["note_title"]:
        lines.append(f"title: {_yaml_string(row['note_title'])}")
    if row["note_original_format"]:
        lines.append(
            f"movenotes-original-format: {_yaml_string(row['note_original_format'])}"
        )

    created = row["joplin_user_created_time"] or row["joplin_created_time"]
    updated = row["joplin_user_updated_time"] or row["joplin_updated_time"]
    if created:
        lines.append(f"created: {_yaml_string(str(created))}")
    if updated:
        lines.append(f"updated: {_yaml_string(str(updated))}")
    if row["joplin_source_url"]:
        lines.append(f"source-url: {_yaml_string(row['joplin_source_url'])}")
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {_yaml_string(tag)}" for tag in tags)

    properties = notesdb.joplin_property_pairs(row)
    effective: dict[str, str] = {}
    order: list[str] = []
    for key, value in properties:
        if key not in effective:
            order.append(key)
        effective[key] = value

    # Retain the previous flat fields, but make sanitized-name collisions
    # deterministic instead of emitting duplicate YAML keys.
    used_flat_keys: set[str] = set()
    for key in order:
        safe_key = re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-") or "property"
        base_key = "joplin-" + safe_key.replace("_", "-").rstrip("-")
        yaml_key = base_key
        suffix = 2
        while yaml_key in used_flat_keys:
            yaml_key = f"{base_key}-{suffix}"
            suffix += 1
        used_flat_keys.add(yaml_key)
        lines.append(f"{yaml_key}: {_yaml_string(effective[key])}")

    effective_json = json.dumps(
        effective, ensure_ascii=False, separators=(",", ":")
    )
    properties_json = json.dumps(
        [[key, value] for key, value in properties],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # JSON object/array syntax is valid YAML and is parsed by Obsidian as
    # structured frontmatter rather than an opaque string.
    lines.append(f"joplin: {effective_json}")
    lines.append(f"joplin-properties: {properties_json}")
    lines.append(f"joplin-properties-json: {_yaml_string(properties_json)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _property_id_map(row: sqlite3.Row) -> dict[str, set[str]]:
    """Map each source property to canonical 32-hex IDs found in its value."""
    result: dict[str, set[str]] = {}
    for key, value in notesdb.joplin_property_pairs(row):
        ids = {match.lower() for match in re.findall(r"[a-fA-F0-9]{32}", value)}
        if ids:
            result[key] = ids
    return result


def _select_preserved_rows(
    rows: list[sqlite3.Row],
    selected_folders: set[str] | None,
    exported_note_ids: set[str],
    referenced_resource_ids: set[str],
) -> list[sqlite3.Row]:
    """Choose a dependency-closed source subset without following backlinks.

    A selected tag must not pull in every other note carrying that tag, and a
    selected nested folder must not pull in its private parent. Dependencies are
    followed outward from selected notes, while relation rows are included only
    when their owning note/item/resource is already in scope.

    The dependency graph is indexed once and traversed with a queue. This keeps
    filtered preservation linear in the number of rows and references instead
    of repeatedly reparsing every row during fixed-point scans.
    """
    if selected_folders is None:
        return rows

    selected_ids = set(selected_folders) | exported_note_ids | referenced_resource_ids
    primary_types = {
        int(constants.JoplinType.NOTE),
        int(constants.JoplinType.FOLDER),
        int(constants.JoplinType.RESOURCE),
        int(constants.JoplinType.TAG),
    }
    owner_keys = ("note_id", "item_id", "parent_id", "resource_id")
    non_dependency_keys = {"id", "note_id", "item_id", "parent_id"}

    by_item_id: dict[str, list[int]] = defaultdict(list)
    relations_by_owner: dict[str, list[int]] = defaultdict(list)
    dependencies: list[set[str]] = []
    item_ids: list[str | None] = []

    for index, row in enumerate(rows):
        item_id = row["joplin_id"]
        item_ids.append(item_id)
        if item_id:
            by_item_id[item_id].append(index)

        property_ids = _property_id_map(row)
        row_dependencies: set[str] = set()
        for key, ids in property_ids.items():
            if key not in non_dependency_keys:
                row_dependencies.update(ids)
        dependencies.append(row_dependencies)

        if row["joplin_type_"] not in primary_types:
            # Prefer the most specific ownership field. For example, a
            # NOTE_RESOURCE row can contain both note_id and resource_id; a
            # selected resource must not pull in a relation belonging to an
            # unselected/private note.
            owner_ids: set[str] = set()
            for key in owner_keys:
                owner_ids = property_ids.get(key, set())
                if owner_ids:
                    break
            for owner_id in owner_ids:
                relations_by_owner[owner_id].append(index)

    included_indexes: set[int] = set()
    scope_ids: set[str] = set()
    pending_ids: deque[str] = deque()

    def add_scope_id(item_id: str) -> None:
        if item_id and item_id not in scope_ids:
            scope_ids.add(item_id)
            pending_ids.append(item_id)

    def include_row(index: int) -> None:
        if index in included_indexes:
            return
        included_indexes.add(index)
        item_id = item_ids[index]
        if item_id:
            add_scope_id(item_id)
        for dependency_id in dependencies[index]:
            add_scope_id(dependency_id)

    for item_id in selected_ids:
        add_scope_id(item_id)

    while pending_ids:
        item_id = pending_ids.popleft()
        for index in by_item_id.get(item_id, ()):
            include_row(index)
        for index in relations_by_owner.get(item_id, ()):
            include_row(index)

    return [row for index, row in enumerate(rows) if index in included_indexes]


def write_preservation_bundle(
    sqlconn: sqlite3.Connection,
    input_resources_path: Path,
    vault_path: Path,
    selected_folders: set[str] | None,
    exported_note_ids: set[str],
    referenced_resource_ids: set[str],
    obsidian_paths: dict[str, str],
    obsidian_hashes: dict[str, str],
    attachment_paths: dict[str, str],
) -> tuple[int, int]:
    """Write an importable Joplin RAW copy and a mapping manifest in the vault."""
    preservation_root = vault_path / PRESERVATION_DIR_NAME
    if preservation_root.exists():
        # A filtered re-export must never retain stale private items from a
        # previous full export.
        shutil.rmtree(preservation_root)
    raw_root = preservation_root / PRESERVED_RAW_DIR_NAME
    raw_root.mkdir(parents=True, exist_ok=True)

    if selected_folders is None:
        # Stream full rows so large exact-source BLOBs are never all resident in
        # memory at once.
        rows = sqlconn.execute("SELECT * FROM notes ORDER BY note_id")
    else:
        # Dependency analysis needs properties and typed Joplin columns, but it
        # does not need note bodies or exact source BLOBs. Keep the graph compact,
        # then stream the selected full rows in a second database pass.
        dependency_columns = ["note_id", "note_source_properties"] + list(
            notesdb.JOPLIN_COLUMNS
        )
        column_sql = ", ".join(f'"{name}"' for name in dependency_columns)
        dependency_rows = sqlconn.execute(
            f"SELECT {column_sql} FROM notes ORDER BY note_id"
        ).fetchall()
        selected_rows = _select_preserved_rows(
            dependency_rows,
            selected_folders,
            exported_note_ids,
            referenced_resource_ids,
        )
        selected_note_ids = {row["note_id"] for row in selected_rows}
        rows = (
            row
            for row in sqlconn.execute("SELECT * FROM notes ORDER BY note_id")
            if row["note_id"] in selected_note_ids
        )

    manifest_items = []
    raw_name_dedup = NameDeduplicator()
    included_resource_ids: set[str] = set()
    row_count = 0
    for row in rows:
        row_count += 1
        item_id = row["joplin_id"] or row["note_uuid"] or f"row-{row['note_id']}"
        source_name = Path(row["note_source_filename"] or f"{item_id}.md").name
        if not source_name.lower().endswith(".md"):
            source_name += ".md"
        source_path = Path(source_name)
        name = raw_name_dedup.reserve(
            str(raw_root), source_path.stem, source_path.suffix, separator="--"
        )

        data = notesdb.exact_source_bytes(row)
        exact = data is not None and notesdb.source_row_unchanged(row)
        if not exact:
            data = notesdb.serialize_joplin_item(row)
        (raw_root / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        manifest_items.append(
            {
                "id": item_id,
                "type": row["joplin_type_"],
                "raw_path": f"{PRESERVED_RAW_DIR_NAME}/{name}",
                "original_filename": row["note_source_filename"],
                "obsidian_path": obsidian_paths.get(item_id),
                "obsidian_sha256": obsidian_hashes.get(item_id),
                "exact_source_bytes": exact,
                "sha256": digest,
            }
        )
        if row["joplin_type_"] == int(constants.JoplinType.RESOURCE):
            included_resource_ids.add(item_id)

    raw_resources = raw_root / "resources"
    copied_resources = 0
    if input_resources_path.is_dir():
        for resource_path in sorted(input_resources_path.iterdir()):
            if not resource_path.is_file():
                continue
            if selected_folders is not None and resource_path.stem not in included_resource_ids:
                continue
            raw_resources.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resource_path, raw_resources / resource_path.name)
            copied_resources += 1

    manifest = {
        "format": "movenotes-lossless-joplin-preservation",
        "version": 1,
        "raw_directory": PRESERVED_RAW_DIR_NAME,
        "scope": "full" if selected_folders is None else "selected-notebooks",
        "items": manifest_items,
        "resource_files": copied_resources,
        "attachments": dict(sorted(attachment_paths.items())),
    }
    (preservation_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (preservation_root / "README.md").write_text(
        "# movenotes preservation data\n\n"
        "`joplin-raw/` is a lossless Joplin RAW export retained alongside the "
        "Obsidian-friendly notes. `manifest.json` maps Joplin item IDs to "
        "their Obsidian paths and includes SHA-256 checksums.\n",
        encoding="utf-8",
    )
    return row_count, copied_resources


def strip_leading_title(body: str, title: str) -> str:
    """Remove a first line that duplicates the note title.

    Joplin RAW bodies start with the note title; in Obsidian the file name
    is the title, so a matching first line would be shown twice.
    """
    lines = body.split("\n")
    if lines and lines[0].strip() in (title.strip(), f"# {title.strip()}"):
        index = 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        return "\n".join(lines[index:])
    return body


def _resource_source(input_resources_path: Path, resource_id: str) -> Path | None:
    direct = input_resources_path / resource_id
    if direct.is_file():
        return direct
    matches = sorted(input_resources_path.glob(f"{resource_id}.*"))
    return matches[0] if matches else None


def restore_native_obsidian_directories(
    sqlconn: sqlite3.Connection, vault_path: Path
) -> int:
    """Restore empty and non-note directories from native Obsidian metadata."""
    restored = 0
    for row in sqlconn.execute(
        "SELECT joplin_application_data FROM notes WHERE joplin_type_ = ?",
        (int(constants.JoplinType.FOLDER),),
    ):
        relative = obsidianmeta.path_snapshot(
            row["joplin_application_data"], "folder"
        )
        if relative is None:
            continue
        target = vault_path / relative
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            restored += 1
    return restored


def restore_native_obsidian_resources(
    sqlconn: sqlite3.Connection, input_resources_path: Path, vault_path: Path
) -> int:
    """Restore files imported from a native Obsidian vault to original paths."""
    restored = 0
    for row in sqlconn.execute(
        "SELECT * FROM notes WHERE joplin_type_ = ? ORDER BY note_id",
        (int(constants.JoplinType.RESOURCE),),
    ):
        relative = obsidianmeta.row_resource_path(row)
        if relative is None:
            continue
        source = _resource_source(input_resources_path, str(row["joplin_id"]))
        if source is None:
            continue
        target = vault_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if common.copy_file_if_changed(source, target.parent, target.name):
            restored += 1
    return restored


def _fallback_long_note_path(note_path: Path, item_id: str, dedup: NameDeduplicator) -> Path:
    suffix = note_path.suffix or ".md"
    directory = str(note_path.parent)
    stem = sanitize_name(note_path.stem)
    digest = hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:12]
    name = dedup.reserve(directory, _fit_filename(stem, "", f"--{digest}"), suffix)
    return note_path.parent / name


def write_note_bytes(
    note_path: Path, data: bytes, *, item_id: str, dedup: NameDeduplicator
) -> Path:
    """Write a note and recover from component-length filesystem errors."""
    note_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        note_path.write_bytes(data)
        return note_path
    except OSError as exc:
        if exc.errno != errno.ENAMETOOLONG:
            raise
    fallback = _fallback_long_note_path(note_path, item_id, dedup)
    fallback.parent.mkdir(parents=True, exist_ok=True)
    fallback.write_bytes(data)
    print(f"warning: shortened overlong note file name to '{fallback}'")
    return fallback


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)
    if args.progress_every < 0:
        common.error("--progress-every cannot be negative")

    input_path: Path = args.input_path
    vault_path: Path = args.output_path

    database_path = input_path / notesdb.DATABASE_FILENAME
    if not database_path.is_file():
        common.error("database not found")

    sqlconn = notesdb.open_database(database_path, __program_name__)
    sqlcur = sqlconn.cursor()

    dedup = NameDeduplicator()
    # Reserve the attachments directory name at the vault root so a notebook
    # with the same name cannot collide with it.
    dedup.reserve(".", ATTACHMENTS_DIR_NAME)

    folders = sqlcur.execute(
        "SELECT joplin_id, joplin_parent_id, note_title FROM notes "
        "WHERE joplin_type_ = ? ORDER BY note_title",
        (int(constants.JoplinType.FOLDER),),
    ).fetchall()
    selected = select_notebooks(folders, args.notebooks)
    folder_paths = build_folder_paths(folders, dedup, selected)

    note_tags = load_note_tags(sqlconn.cursor())
    restored_native_directories = restore_native_obsidian_directories(
        sqlconn, vault_path
    )
    restored_native_resources = restore_native_obsidian_resources(
        sqlconn, input_path / "resources", vault_path
    )
    attachments = AttachmentTable(
        sqlconn.cursor(), input_path / "resources", vault_path, dedup
    )

    note_count = 0
    skipped_count = 0
    exported_note_ids: set[str] = set()
    referenced_resource_ids: set[str] = set()
    obsidian_paths: dict[str, str] = {}
    obsidian_hashes: dict[str, str] = {}
    for row in sqlcur.execute(
        "SELECT * FROM notes WHERE joplin_type_ = ? ORDER BY note_internal_date",
        (int(constants.JoplinType.NOTE),),
    ):
        # Every importer in this project writes complete joplin_* columns;
        # a row without a joplin_id cannot be exported.
        if not row["joplin_id"]:
            common.error(
                f"note '{row['note_title']}' has no Joplin item id "
                f"(original format '{row['note_original_format']}'). This "
                "version only supports databases created by this project's "
                "importers; re-import your notes."
            )

        if selected is not None and row["joplin_parent_id"] not in selected:
            skipped_count += 1
            continue

        item_id = row["joplin_id"]
        snapshot = obsidianmeta.row_note_snapshot(row)
        if snapshot is not None:
            original_path, original_raw, expected_body_hash = snapshot
            current_body = row["note_data"] or ""
            if obsidianmeta.text_sha256(current_body) == expected_body_hash:
                note_path = write_note_bytes(
                    vault_path / original_path, original_raw, item_id=item_id, dedup=dedup
                )
                relative_written = note_path.relative_to(vault_path).as_posix()
                exported_note_ids.add(item_id)
                obsidian_paths[item_id] = relative_written
                obsidian_hashes[item_id] = hashlib.sha256(original_raw).hexdigest()
                note_count += 1
                if args.verbose:
                    print(f"processing '{relative_written}' (exact Obsidian source)")
                elif args.progress_every and note_count % args.progress_every == 0:
                    print(f"exported {note_count:,} Obsidian note(s)")
                continue

        note_dir = folder_paths.get(row["joplin_parent_id"], PurePosixPath("."))
        title = sanitize_name(row["note_title"])
        filename = dedup.reserve(str(note_dir), title, ".md")
        if args.verbose:
            print(f"processing '{note_dir / filename}'")

        original_body = row["note_data"] or ""
        referenced_resource_ids.update(common.get_resource_ids(original_body))
        body = strip_leading_title(original_body, row["note_title"] or "")
        body = rewrite_resource_links(body, note_dir, attachments)
        if args.simplify_urls:
            body = common.simplify_url_links(body)

        content = body if body.endswith("\n") or not body else body + "\n"
        if args.frontmatter:
            content = build_frontmatter(row, note_tags.get(row["joplin_id"], [])) + content

        note_path = write_note_bytes(
            vault_path / note_dir / filename, content.encode("utf-8"),
            item_id=item_id, dedup=dedup,
        )
        exported_note_ids.add(item_id)
        obsidian_paths[item_id] = note_path.relative_to(vault_path).as_posix()
        obsidian_hashes[item_id] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        note_count += 1
        if (
            not args.verbose
            and args.progress_every
            and note_count % args.progress_every == 0
        ):
            print(f"exported {note_count:,} Obsidian note(s)")

    preserved_items = preserved_resources = 0
    if args.preserve_joplin:
        preserved_items, preserved_resources = write_preservation_bundle(
            sqlconn,
            input_path / "resources",
            vault_path,
            selected,
            exported_note_ids,
            referenced_resource_ids,
            obsidian_paths,
            obsidian_hashes,
            attachments.vault_paths,
        )

    summary = f"exported {note_count} note(s)"
    if restored_native_directories:
        summary += (
            f"; restored {restored_native_directories} native Obsidian "
            "director(ies)"
        )
    if restored_native_resources:
        summary += f"; restored {restored_native_resources} native Obsidian file(s)"
    if skipped_count:
        summary += f" ({skipped_count} outside the selected notebooks skipped)"
    if args.preserve_joplin:
        summary += (
            f"; preserved {preserved_items} Joplin item(s) and "
            f"{preserved_resources} raw resource file(s)"
        )
    print(summary)
    sqlconn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
