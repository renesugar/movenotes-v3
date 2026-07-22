#!/usr/bin/env python3
"""Export a SQLite notes database to a Joplin RAW directory.

Imported Joplin items are written from their exact stored source bytes by
default, including unknown properties, original property order, whitespace and
line endings.  URL simplification is available only as an explicit, lossy
option.
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
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import common
import constants
import notesdb

__program_name__ = "sql2joplin"
__author__ = "Rene Sugar"
__version__ = "3.20"
__license__ = "MIT License (https://opensource.org/licenses/MIT)"
__website__ = "https://github.com/renesugar"

_FOLDER_TEMPLATE = """{title}

id: {id}
created_time: {created_time}
updated_time: {updated_time}
user_created_time: {created_time}
user_updated_time: {updated_time}
encryption_cipher_text: 
encryption_applied: 0
parent_id: {parent_id}
is_shared: 0
type_: 2"""


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
        help="Path to the output Joplin RAW directory",
    )
    url_group = parser.add_mutually_exclusive_group()
    url_group.add_argument(
        "--simplify-urls",
        dest="simplify_urls",
        action="store_true",
        default=False,
        help=(
            "Lossy: replace URL-only markdown links ([https://x](https://x), "
            "<https://x>) with bare URLs"
        ),
    )
    # Retained for command-line compatibility with older releases; preserving
    # URLs is now the default required for a lossless round trip.
    url_group.add_argument(
        "--no-simplify-urls",
        dest="simplify_urls",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N exported items; 0 disables it (default: 1000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every exported item title instead of periodic progress",
    )
    return parser


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def write_folder(
    output_path: Path,
    folder_name: str | None,
    folder_id: str | None,
    folder_parent_id: str | None,
) -> tuple[str, str]:
    """Write a generated Joplin folder item and return its name and id."""
    if folder_name is None or not folder_name.strip():
        folder_name = constants.NOTES_FOLDER_NAME
    if folder_id is None:
        folder_id = (
            constants.NOTES_FOLDER_UUID
            if folder_name == constants.NOTES_FOLDER_NAME
            else common.create_uuid_string()
        )

    output_filename = output_path / f"{folder_id}.md"
    print(f"processing folder '{folder_name}' ({output_filename})")
    timestamp = _utc_timestamp()
    output_filename.write_text(
        _FOLDER_TEMPLATE.format(
            title=folder_name,
            id=folder_id,
            created_time=timestamp,
            updated_time=timestamp,
            parent_id=folder_parent_id or "",
        ),
        encoding="utf-8",
    )
    return (folder_name, folder_id)


def _output_filename(output_path: Path, row: sqlite3.Row) -> Path:
    source_name = row["note_source_filename"]
    if source_name:
        safe_name = Path(source_name).name
        if safe_name.lower().endswith(".md"):
            return output_path / safe_name
    item_id = row["joplin_id"] or row["note_uuid"]
    return output_path / f"{item_id}.md"


def write_joplin_item(
    output_path: Path, row: sqlite3.Row, simplify_urls: bool = False
) -> None:
    """Write a database row as one Joplin RAW item.

    With the default ``simplify_urls=False``, imported Joplin items are emitted
    byte-for-byte from note_source_raw.  Generated rows and explicitly
    transformed exports are reconstructed from all ordered source properties.
    """
    if row["note_data_format"] != "text/markdown":
        common.error(
            f"item '{row['note_uuid']}' has unsupported data format "
            f"'{row['note_data_format']}'"
        )

    output_filename = _output_filename(output_path, row)
    exact = notesdb.exact_source_bytes(row)
    if (
        exact is not None
        and not simplify_urls
        and row["note_original_format"] == "joplin"
        and notesdb.source_row_unchanged(row)
    ):
        output_filename.write_bytes(exact)
        return

    body = row["note_data"] or ""
    if simplify_urls and row["joplin_type_"] == int(constants.JoplinType.NOTE):
        body = common.simplify_url_links(body)
    output_filename.write_bytes(notesdb.serialize_joplin_item(row, body=body))


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)
    if args.progress_every < 0:
        common.error("--progress-every cannot be negative")
    input_path: Path = args.input_path
    output_path: Path = args.output_path

    database_path = input_path / notesdb.DATABASE_FILENAME
    if not database_path.is_file():
        common.error("database not found")

    sqlconn = notesdb.open_database(database_path, __program_name__)
    sqlcur = sqlconn.cursor()

    input_resources_path = input_path / "resources"
    output_resources_path = output_path / "resources"
    output_resources_path.mkdir(parents=True, exist_ok=True)
    copied, skipped = common.copy_resources(input_resources_path, output_resources_path)
    if copied or skipped:
        print(f"resources: {copied} copied, {skipped} unchanged")

    sqlcur.execute(
        "SELECT COUNT(*) FROM notes WHERE joplin_type_ = ?",
        (int(constants.JoplinType.FOLDER),),
    )
    if sqlcur.fetchone()[0] == 0:
        write_folder(
            output_path,
            constants.NOTES_FOLDER_NAME,
            constants.NOTES_FOLDER_UUID,
            None,
        )

    sqlcur.execute("SELECT * FROM notes ORDER BY note_internal_date DESC")
    output_names: set[str] = set()
    item_count = 0
    for row in sqlcur:
        if not row["joplin_id"]:
            common.error(
                f"note '{row['note_title']}' has no Joplin item id "
                f"(original format '{row['note_original_format']}'). Re-import "
                "the source with a current movenotes importer."
            )
        output_name = _output_filename(output_path, row).name.lower()
        if output_name in output_names:
            common.error(
                f"multiple database rows would overwrite Joplin RAW file "
                f"'{output_name}'; resolve the duplicate item ID first"
            )
        output_names.add(output_name)
        title = common.remove_line_breakers(row["note_title"] or "")
        if args.verbose:
            print(f"processing '{title}'")
        write_joplin_item(output_path, row, simplify_urls=args.simplify_urls)
        item_count += 1
        if (
            not args.verbose
            and args.progress_every
            and item_count % args.progress_every == 0
        ):
            print(f"exported {item_count:,} Joplin item(s)")

    sqlconn.close()
    print(f"exported {item_count:,} Joplin item(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
