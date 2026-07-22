#!/usr/bin/env python3
"""Remove duplicate notes from a SQLite notes database.

Notes are duplicates when they have the same body hash; the note with the
lowest note_id is kept. Useful after merging several Joplin sources into
one database with joplin2sql.py.
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

__program_name__ = "removedups"
__author__ = "Rene Sugar"
__version__ = "2.00"
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

    database_path = input_path / notesdb.DATABASE_FILENAME
    if not database_path.is_file():
        common.error("database not found")

    sqlconn = notesdb.open_database(database_path, __program_name__)
    sqlcur = sqlconn.cursor()

    # Remove notes with duplicate hash values, keeping the lowest note_id.
    sqlcur.execute(
        """DELETE FROM notes
           WHERE note_type = 'note' AND note_id NOT IN (
               SELECT MIN(note_id)
               FROM notes
               GROUP BY note_hash
           )"""
    )
    print(f"removed {sqlcur.rowcount} duplicate note(s)")

    sqlconn.commit()
    sqlconn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
