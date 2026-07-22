#!/usr/bin/env python3
"""Remove unused files from a resources directory.

A resource file is unused when no note in the database references it
through a markdown resource link ``(:/resource_id)``.
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
import sys
from pathlib import Path

import common
import notesdb

__program_name__ = "cleanres"
__author__ = "Rene Sugar"
__version__ = "2.10"
__license__ = "MIT License (https://opensource.org/licenses/MIT)"
__website__ = "https://github.com/renesugar"


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
    return parser


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)

    input_path: Path = args.input_path

    input_resources_path = input_path / "resources"
    if not input_resources_path.is_dir():
        common.error(f"input resources path '{input_resources_path}' does not exist.")

    database_path = input_path / notesdb.DATABASE_FILENAME
    if not database_path.is_file():
        common.error("database not found")

    sqlconn = notesdb.open_database(database_path, __program_name__)
    sqlcur = sqlconn.cursor()

    # Collect the resource ids referenced by any note in one pass over the
    # database instead of running a LIKE table scan per resource file.
    referenced_ids: set[str] = set()
    sqlcur.execute("SELECT note_data FROM notes WHERE note_data LIKE '%(:/%'")
    for (note_data,) in sqlcur:
        for _link, _filename, resource_id in common.get_resource_links(note_data):
            referenced_ids.add(resource_id)

    # Remove resource files not referenced by any note.
    deleted = 0
    for file_path in sorted(p for p in input_resources_path.rglob("*") if p.is_file()):
        if file_path.stem not in referenced_ids:
            print(f"deleting '{file_path}'...")
            file_path.unlink()
            deleted += 1
    print(f"deleted {deleted} unused resource file(s)")

    sqlconn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
