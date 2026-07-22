#!/usr/bin/env python3
"""Import a Joplin RAW export directory into a SQLite database.

Run joplin2sql.py more than once with different --input directories and the
same --output directory to merge several Joplin sources into one database.
Every RAW item is retained byte-for-byte in SQLite in addition to its parsed,
queryable columns, so unknown and future Joplin properties are never dropped.
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
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import common
import constants
import notesdb

__program_name__ = "joplin2sql"
__author__ = "Rene Sugar"
__version__ = "3.20"
__license__ = "MIT License (https://opensource.org/licenses/MIT)"
__website__ = "https://github.com/renesugar"

# Joplin currently uses ASCII identifier-like keys, but the exact RAW item is
# intended to remain forward compatible.  Accept any non-empty, single-line
# key that does not contain the key/value delimiter so future fields are not
# rejected merely because their naming convention changes.
_PROPERTY_RE = re.compile(r"^([^:\r\n]+):(.*)$")
_MISSING = object()


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
        help="Path to the input Joplin RAW directory",
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        type=common.existing_dir,
        required=True,
        help="Path to the output SQLite directory",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Rows per SQLite executemany batch (default: 1000)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N input items; 0 disables progress (default: 1000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every imported item title instead of periodic progress",
    )
    return parser


def _split_physical_lines(text: str) -> list[str]:
    """Split text only at CR/LF line endings, preserving those endings.

    ``str.splitlines()`` also treats several ASCII and Unicode control
    characters as line boundaries (for example form feed, file separator and
    record separator). Joplin resource OCR metadata can legitimately contain
    those characters inside a single ``ocr_text`` property value, so using
    ``splitlines()`` corrupts the RAW property block.
    """
    if not text:
        return []

    parts = re.split(r"(\r\n|\r|\n)", text)
    lines = [
        parts[index] + parts[index + 1]
        for index in range(0, len(parts) - 1, 2)
    ]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _line_without_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\r", "\n")):
        return line[:-1]
    return line


def _first_physical_line(text: str) -> str:
    """Return the first CR/LF-delimited line without splitting the full body."""
    cr = text.find("\r")
    lf = text.find("\n")
    indexes = [index for index in (cr, lf) if index >= 0]
    return text[: min(indexes)] if indexes else text


def _split_raw_item(text: str, file_path: Path) -> tuple[str, list[tuple[str, str]]]:
    """Split RAW text into body and ordered, unnormalised property pairs."""
    lines = _split_physical_lines(text)
    separator_index: int | None = None

    # The canonical format has a blank separator before a contiguous property
    # block.  Search from the bottom so blank lines inside the note body remain
    # part of the body.  Bodyless relation items may contain properties only.
    for index in range(len(lines) - 1, -1, -1):
        content = _line_without_ending(lines[index])
        if not content:
            separator_index = index
            break
        if _PROPERTY_RE.match(content) is None:
            break

    if separator_index is not None:
        body_lines = lines[:separator_index]
        property_lines = lines[separator_index + 1 :]
    elif all(
        _PROPERTY_RE.match(_line_without_ending(line)) is not None
        for line in lines
        if _line_without_ending(line)
    ):
        body_lines = []
        property_lines = lines
    else:
        common.error(f"cannot find Joplin property block in '{file_path}'")

    properties: list[tuple[str, str]] = []
    for line in property_lines:
        content = _line_without_ending(line)
        if not content:
            # A terminal blank line is harmless; a blank in the property block
            # carries no property data and is preserved by note_source_raw.
            continue
        match = _PROPERTY_RE.match(content)
        if match is None:
            common.error(f"invalid Joplin property line in '{file_path}': {content!r}")
        raw_value = match.group(2)
        # In canonical RAW files the first space after the colon is the
        # key/value delimiter, not part of the value. Consume at most that
        # one delimiter space while preserving every additional leading or
        # trailing character. Exact line formatting remains available in
        # note_source_raw for byte-for-byte export.
        value = raw_value[1:] if raw_value.startswith(" ") else raw_value
        properties.append((match.group(1), value))

    return "".join(body_lines), properties


def _convert_known_value(value: str, sqlite_type: str):
    """Convert a Joplin property value using its declared SQLite type.

    ``REAL`` is SQLite's canonical floating-point declaration. ``FLOAT`` is
    retained for compatibility with the older schema entries used by latitude,
    longitude, and altitude.
    """
    normalised = value.strip()
    declared_type = sqlite_type.strip().upper()
    if declared_type == "INTEGER":
        return int(normalised) if normalised else None
    if declared_type == "REAL":
        return float(normalised) if normalised else None
    if declared_type == "FLOAT":
        return float(normalised) if normalised else None
    return normalised


def _internal_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        if value.lstrip("-").isdigit():
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        return common.parse_isoformat_datetime(value)
    except (OverflowError, OSError, ValueError):
        return None



def _copy_resources_losslessly(src_dir: Path, dst_dir: Path) -> tuple[int, int]:
    """Copy resources, refusing to overwrite a different file with the same ID."""
    copied = skipped = 0
    if not src_dir.is_dir():
        return copied, skipped
    sources = [source for source in sorted(src_dir.iterdir()) if source.is_file()]

    # Validate the whole source before copying anything so a collision cannot
    # leave a partially merged resources directory.
    for source in sources:
        destination = dst_dir / source.name
        if destination.exists() and not common.files_identical(source, destination):
            common.error(
                f"resource collision for '{source.name}': the SQLite resources "
                "directory already contains different bytes for this Joplin ID"
            )

    for source in sources:
        destination = dst_dir / source.name
        if destination.exists():
            skipped += 1
            continue
        common.copy_file_if_changed(source, dst_dir)
        copied += 1
    return copied, skipped

def parse_joplin_note(file_path: Path) -> dict:
    """Parse a Joplin RAW item into database columns without discarding data."""
    columns: dict = {}
    if not (file_path.is_file() and common.check_extension(file_path, ["md"])):
        return columns

    raw = file_path.read_bytes()
    try:
        # utf-8-sig accepts both ordinary UTF-8 and an optional BOM.  The exact
        # bytes, including BOM and line endings, remain in note_source_raw.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        common.error(f"'{file_path}' is not valid UTF-8: {exc}")

    body, properties = _split_raw_item(text, file_path)
    columns["note_source_filename"] = file_path.name
    columns["note_source_body"] = body
    columns["note_source_raw"] = raw
    columns["note_source_sha256"] = hashlib.sha256(raw).digest()
    columns["note_source_properties"] = json.dumps(
        properties,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    # The last occurrence is the effective value, matching ordinary key/value
    # parsing, while the ordered JSON list above preserves duplicates exactly.
    for key, raw_value in properties:
        column_name = f"joplin_{key}"
        if column_name in notesdb.JOPLIN_COLUMNS:
            try:
                columns[column_name] = _convert_known_value(
                    raw_value, notesdb.JOPLIN_COLUMNS[column_name]
                )
            except ValueError:
                common.error(
                    f"invalid {notesdb.JOPLIN_COLUMNS[column_name]} value for "
                    f"'{key}' in '{file_path}': {raw_value!r}"
                )

    type_value = columns.get("joplin_type_")
    item_id = columns.get("joplin_id") or file_path.stem
    columns["note_type"] = (
        common.note_type_from_joplin_type(type_value) if type_value is not None else ""
    )
    columns["note_uuid"] = item_id
    columns["note_parent_uuid"] = columns.get("joplin_parent_id")
    columns["note_tag_uuid"] = columns.get("joplin_tag_id")
    columns["note_note_uuid"] = columns.get("joplin_note_id")
    columns["note_folder"] = None
    columns["note_original_format"] = "joplin"
    columns["note_internal_date"] = _internal_date(columns.get("joplin_created_time"))
    columns["note_hash"] = None
    first_line = _first_physical_line(body)
    columns["note_title"] = common.default_title_from_body(first_line)
    columns["note_url"] = columns.get("joplin_source_url")
    columns["note_data"] = body
    columns["note_data_format"] = "text/markdown"
    return columns


def prepare_joplin_note(columns: dict) -> dict:
    """Fill in derived columns for a parsed Joplin item."""
    note_title = _normalised_note_title(columns.get("note_title"))

    note_data = columns["note_data"] or ""
    columns.update(
        {
            "note_hash": hashlib.sha512(note_data.encode("utf-8")).hexdigest(),
            "note_title": note_title,
            "note_data": note_data,
        }
    )
    return columns


def _normalised_note_title(value: str | None) -> str:
    if value is None:
        return constants.NOTES_UNTITLED
    return common.remove_line_breakers(value).strip() or constants.NOTES_UNTITLED


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)

    if args.batch_size < 1:
        common.error("--batch-size must be at least 1")
    if args.progress_every < 0:
        common.error("--progress-every cannot be negative")

    input_path: Path = args.input_path
    output_path: Path = args.output_path
    input_resources_path = input_path / "resources"
    output_resources_path = output_path / "resources"
    database_path = output_path / notesdb.DATABASE_FILENAME

    new_database = not database_path.is_file()
    if not new_database:
        sqlconn = notesdb.open_database(database_path, __program_name__)
    else:
        sqlconn = notesdb.connect(database_path)
        # Secondary indexes are substantially faster to build once after the
        # bulk insert than to maintain row-by-row during a new large import.
        notesdb.create_database(sqlconn, create_indexes=False)

    output_resources_path.mkdir(parents=True, exist_ok=True)

    # Restrict collision lookups to rows that existed before this import. Rows
    # inserted during the run are covered by ``seen_in_run``. This makes a
    # small merge into a very large database proportional to the input size,
    # rather than preloading every existing Joplin ID and fingerprint.
    baseline = sqlconn.execute(
        "SELECT COALESCE(MAX(note_id), 0), COUNT(*) FROM notes"
    ).fetchone()
    starting_note_id = int(baseline[0])
    existing_row_count = int(baseline[1])

    file_paths = sorted(
        (
            path
            for path in input_path.iterdir()
            if path.is_file() and common.check_extension(path, ["md"])
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )
    source_by_stem: dict[str, Path] = {}
    for path in file_paths:
        source_by_stem.setdefault(path.stem, path)
        source_by_stem.setdefault(path.stem.casefold(), path)

    # A full re-import is fastest with one sequential fingerprint preload;
    # a small merge into a much larger database is fastest with indexed,
    # input-scoped lookups. Select between the two without changing collision
    # semantics.
    preload_threshold = max(1000, existing_row_count // 4)
    preloaded_existing = (
        notesdb.load_joplin_source_fingerprints(sqlconn)
        if starting_note_id and len(file_paths) >= preload_threshold
        else None
    )

    # Resolve ordinary parent notebook titles while parsing, as Claude's
    # implementation usefully demonstrated, but keep support for folders that
    # were imported earlier and for non-canonical source filenames. A parent
    # file is parsed at most once and its parsed columns are reused by the main
    # loop when that file is reached.
    folder_titles = notesdb.load_joplin_folder_titles(sqlconn)
    parsed_file_cache: dict[Path, dict] = {}

    def folder_title(folder_id: str) -> str | None:
        if folder_id in folder_titles:
            return folder_titles[folder_id]
        source = source_by_stem.get(folder_id) or source_by_stem.get(folder_id.casefold())
        title: str | None = None
        if source is not None:
            columns = parsed_file_cache.get(source)
            if columns is None:
                columns = parse_joplin_note(source)
                parsed_file_cache[source] = columns
            if (
                columns.get("joplin_id") == folder_id
                and columns.get("joplin_type_") == int(constants.JoplinType.FOLDER)
            ):
                title = _normalised_note_title(columns.get("note_title"))
        folder_titles[folder_id] = title
        return title

    seen_in_run: dict[str, bytes] = {}
    parsed_batch: list[tuple[dict, str | None, bytes]] = []
    scanned = imported = duplicate_input = already_imported = 0
    needs_folder_fallback = False

    def report_progress() -> None:
        if (
            not args.verbose
            and args.progress_every
            and scanned % args.progress_every == 0
        ):
            print(
                f"processed {scanned:,} item(s): {imported:,} new, "
                f"{already_imported + duplicate_input:,} skipped"
            )

    def flush_batch() -> None:
        nonlocal imported, already_imported, needs_folder_fallback
        if not parsed_batch:
            return
        existing_by_id = preloaded_existing
        if existing_by_id is None:
            existing_by_id = notesdb.load_joplin_source_fingerprints_for_ids(
                sqlconn,
                (item_id for _columns, item_id, _digest in parsed_batch),
                maximum_note_id=starting_note_id,
            )
        insert_rows: list[dict] = []
        for columns, item_id, source_digest in parsed_batch:
            if item_id:
                existing_digests = existing_by_id.get(item_id)
                if existing_digests is not None:
                    if existing_digests == {source_digest}:
                        already_imported += 1
                        if args.verbose:
                            print(f"skipping already imported item '{item_id}'")
                        continue
                    common.error(
                        f"item id collision for '{item_id}': the database already "
                        "contains different data for this Joplin ID"
                    )

            if columns.get("joplin_type_") == int(constants.JoplinType.NOTE):
                parent_id = columns.get("joplin_parent_id")
                if parent_id:
                    columns["note_folder"] = folder_title(parent_id)
                    if columns["note_folder"] is None:
                        needs_folder_fallback = True

            prepared = prepare_joplin_note(columns)
            if columns.get("joplin_type_") == int(constants.JoplinType.FOLDER):
                folder_id = columns.get("joplin_id")
                if folder_id:
                    folder_titles[folder_id] = prepared["note_title"]
            if args.verbose:
                print(f"processing '{prepared['note_title']}'")
            insert_rows.append(prepared)

        if insert_rows:
            notesdb.add_joplin_notes(sqlconn, insert_rows)
            imported += len(insert_rows)
        parsed_batch.clear()

    try:
        for file_path in file_paths:
            scanned += 1
            columns = parsed_file_cache.pop(file_path, None)
            if columns is None:
                columns = parse_joplin_note(file_path)
            item_id = columns.get("joplin_id")
            source_digest = columns["note_source_sha256"]
            if (
                item_id
                and columns.get("joplin_type_") == int(constants.JoplinType.FOLDER)
            ):
                folder_titles[item_id] = _normalised_note_title(
                    columns.get("note_title")
                )
            if item_id:
                previous_digest = seen_in_run.get(item_id, _MISSING)
                if previous_digest is not _MISSING:
                    if previous_digest == source_digest:
                        duplicate_input += 1
                        if args.verbose:
                            print(f"skipping duplicate item '{item_id}'")
                        report_progress()
                        continue
                    common.error(
                        f"item id collision for '{item_id}': two input RAW files "
                        "contain different data"
                    )
                seen_in_run[item_id] = source_digest

            parsed_batch.append((columns, item_id, source_digest))
            if len(parsed_batch) >= args.batch_size:
                flush_batch()

            report_progress()

        flush_batch()

        if new_database:
            notesdb.ensure_indexes(sqlconn)

        # Canonical RAW exports resolve parent titles from their folder files
        # without a database-wide update. The targeted fallback preserves
        # compatibility with renamed/non-canonical files and considers only
        # rows inserted by this run.
        if needs_folder_fallback:
            notesdb.populate_missing_note_folders(
                sqlconn, minimum_note_id=starting_note_id + 1
            )

        # Copy resources only after every item has parsed and passed collision
        # checks. If resource validation fails, the uncommitted SQLite inserts
        # are rolled back rather than leaving partially imported database rows.
        copied, skipped = _copy_resources_losslessly(
            input_resources_path, output_resources_path
        )
        if copied or skipped:
            print(f"resources: {copied} copied, {skipped} unchanged")
        sqlconn.commit()
    except Exception:
        sqlconn.rollback()
        raise
    finally:
        sqlconn.close()

    print(
        f"processed {scanned:,} Joplin item(s): {imported:,} imported, "
        f"{already_imported:,} already present, {duplicate_input:,} duplicate input"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
