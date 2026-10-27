#!/usr/bin/env python3
"""Small synthetic review-claim reproducers; no user data or production edits."""
from collections import Counter
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
import joplin2sql
import notesdb
import obsidian2sql


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-fixed", action="store_true", help="require P7b C01/C02 protections")
    args = parser.parse_args(argv)
    findings = {}
    with tempfile.TemporaryDirectory(prefix="p7a-probes-") as directory:
        root = Path(directory)
        connection = notesdb.connect(root / "notes.sqlite")
        with redirect_stdout(io.StringIO()):
            notesdb.create_database(connection)
        rows = [dict(joplin_id="same", note_uuid="same", note_obsidian_sha256=value,
                     joplin_type_=1, note_title="Synthetic") for value in (b"a"*32, b"b"*32)]
        try:
            inserted, skipped = obsidian2sql._insert_rows(connection, rows, 500)
            collision = False
        except SystemExit:
            inserted = skipped = 0
            collision = True
        findings["same_batch_different_digest"] = dict(collision=collision, inserted=inserted, skipped=skipped,
            rows=connection.execute("SELECT COUNT(*) FROM notes WHERE joplin_id='same'").fetchone()[0])
        connection.close()
        source = root / "source"
        target = root / "target"
        source.mkdir(); target.mkdir()
        (source / "asset.bin").write_bytes(b"same")
        (target / "asset.bin").write_bytes(b"same")
        with patch.object(common, "files_identical", wraps=common.files_identical) as compare:
            result = joplin2sql._copy_resources_losslessly(source, target)
            findings["joplin_unchanged_resource"] = dict(comparisons=compare.call_count, copied=result[0], skipped=result[1])
        (source / "asset.bin").write_bytes(b"different")
        try:
            common.copy_resources(source, target, reject_collisions=True)
            protected = False
        except SystemExit:
            protected = (target / "asset.bin").read_bytes() == b"same"
        findings["preserved_resource_collision_protected"] = protected
        findings["insert_column_count"] = len(notesdb._INSERT_COLUMNS)
        plan_db = sqlite3.connect(":memory:")
        with redirect_stdout(io.StringIO()):
            notesdb.create_database(plan_db, create_indexes=False)
        query = "SELECT note_title FROM notes WHERE joplin_id=? AND joplin_type_=2 ORDER BY note_id LIMIT 1"
        before = [row[3] for row in plan_db.execute("EXPLAIN QUERY PLAN " + query, ("parent",))]
        notesdb.ensure_indexes(plan_db)
        after = [row[3] for row in plan_db.execute("EXPLAIN QUERY PLAN " + query, ("parent",))]
        findings["folder_parent_lookup"] = dict(before_indexes=before, after_indexes=after)
        plan_db.close()
    assert findings["joplin_unchanged_resource"]["comparisons"] == 1
    if args.expect_fixed:
        assert findings["same_batch_different_digest"] == {"collision": True, "inserted": 0, "skipped": 0, "rows": 0}
        assert findings["preserved_resource_collision_protected"]
    print(json.dumps(findings, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
