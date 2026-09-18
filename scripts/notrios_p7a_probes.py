#!/usr/bin/env python3
"""Small synthetic review-claim reproducers; no user data or production edits."""
from collections import Counter
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


def main():
    findings = {}
    with tempfile.TemporaryDirectory(prefix="p7a-probes-") as directory:
        root = Path(directory)
        connection = notesdb.connect(root / "notes.sqlite")
        with redirect_stdout(io.StringIO()):
            notesdb.create_database(connection)
        rows = [dict(joplin_id="same", note_uuid="same", note_obsidian_sha256=value,
                     joplin_type_=1, note_title="Synthetic") for value in (b"a"*32, b"b"*32)]
        inserted, skipped = obsidian2sql._insert_rows(connection, rows, 500)
        findings["same_batch_different_digest"] = dict(inserted=inserted, skipped=skipped,
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
        common.copy_resources(source, target)
        findings["preserved_resource_helper_overwrites"] = (target / "asset.bin").read_bytes() == b"different"
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
    assert findings["same_batch_different_digest"]["rows"] == 2
    assert findings["joplin_unchanged_resource"]["comparisons"] == 1
    assert findings["preserved_resource_helper_overwrites"]
    print(json.dumps(findings, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
