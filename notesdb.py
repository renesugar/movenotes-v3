"""SQLite database code shared by the movenotes import/export scripts."""

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

import hashlib
import json
import sqlite3
import sys

DATABASE_FILENAME = "notesdb.sqlite"

# Schema v3 adds lossless source storage.  ``note_source_raw`` contains the
# exact bytes of an imported Joplin RAW item and ``note_source_properties``
# contains its ordered key/value property lines as JSON.  The raw bytes make a
# byte-for-byte round trip possible; the ordered property list lets exporters
# expose all metadata, including properties introduced by future Joplin
# versions, without requiring a schema change for every new field. Schema v4
# adds a compact SHA-256 fingerprint of those source bytes plus indexes used by
# import, image-processing and export scripts. The fingerprint lets importers
# detect duplicate/colliding Joplin IDs without retaining or repeatedly reading
# every source BLOB. Schema v5 adds exact native-Obsidian snapshots and paths.
DB_SCHEMA_VERSION = "5"
DB_SCHEMA_MIN_VERSION = "2"

# Known Joplin RAW properties.  These columns make common fields convenient to
# query while note_source_properties remains the authoritative, extensible copy
# of every source property.  The list covers the current Joplin Data API note,
# folder, resource, tag and revision properties plus relationship fields used by
# other item types.
JOPLIN_COLUMNS = {
    "joplin_id": "TEXT",
    "joplin_parent_id": "TEXT",
    "joplin_type_": "INTEGER",
    "joplin_created_time": "TEXT",
    "joplin_updated_time": "TEXT",
    "joplin_is_conflict": "INTEGER",
    "joplin_latitude": "FLOAT",
    "joplin_longitude": "FLOAT",
    "joplin_altitude": "FLOAT",
    "joplin_author": "TEXT",
    "joplin_source_url": "TEXT",
    "joplin_is_todo": "INTEGER",
    "joplin_todo_due": "INTEGER",
    "joplin_todo_completed": "INTEGER",
    "joplin_source": "TEXT",
    "joplin_source_application": "TEXT",
    "joplin_application_data": "TEXT",
    # Joplin documents note order as numeric, not integer. Values can be
    # fractional or use scientific notation, including subnormal values such
    # as 6e-323. SQLite REAL is the canonical floating-point type and preserves those values.
    "joplin_order": "REAL",
    "joplin_user_created_time": "TEXT",
    "joplin_user_updated_time": "TEXT",
    "joplin_encryption_cipher_text": "TEXT",
    "joplin_encryption_applied": "INTEGER",
    "joplin_encryption_blob_encrypted": "INTEGER",
    "joplin_size": "INTEGER",
    "joplin_markup_language": "INTEGER",
    "joplin_is_shared": "INTEGER",
    "joplin_share_id": "TEXT",
    "joplin_conflict_original_id": "TEXT",
    "joplin_master_key_id": "TEXT",
    "joplin_user_data": "TEXT",
    "joplin_deleted_time": "INTEGER",
    "joplin_is_locked": "INTEGER",
    "joplin_extracted_resource_ids": "TEXT",
    "joplin_icon": "TEXT",
    "joplin_note_id": "TEXT",
    "joplin_tag_id": "TEXT",
    "joplin_item_type": "INTEGER",
    "joplin_item_id": "TEXT",
    "joplin_item_updated_time": "INTEGER",
    "joplin_title_diff": "TEXT",
    "joplin_body_diff": "TEXT",
    "joplin_metadata_diff": "TEXT",
    "joplin_mime": "TEXT",
    "joplin_filename": "TEXT",
    "joplin_file_extension": "TEXT",
    "joplin_blob_updated_time": "INTEGER",
    "joplin_ocr_text": "TEXT",
    "joplin_ocr_details": "TEXT",
    "joplin_ocr_status": "INTEGER",
    "joplin_ocr_error": "TEXT",
    "joplin_ocr_driver_id": "INTEGER",
}

# Generic note columns.  Source-preservation columns deliberately use the
# note_* namespace so they can never be mistaken for actual Joplin properties.
NOTE_COLUMNS = {
    "note_type": "TEXT",
    "note_uuid": "TEXT",
    "note_parent_uuid": "TEXT",
    "note_tag_uuid": "TEXT",
    "note_note_uuid": "TEXT",
    "note_folder": "TEXT",
    "note_original_format": "TEXT",
    "note_internal_date": "DATETIME DEFAULT CURRENT_TIMESTAMP",
    "note_hash": "TEXT",
    "note_title": "TEXT",
    "note_data": "TEXT",
    "note_data_format": "TEXT",
    "note_url": "TEXT",
    "note_source_filename": "TEXT",
    "note_source_body": "TEXT",
    "note_source_raw": "BLOB",
    "note_source_sha256": "BLOB",
    "note_source_properties": "TEXT",
    # Exact native-Obsidian preservation. These columns are independent of
    # Joplin RAW source snapshots and survive direct SQLite round trips.
    "note_obsidian_path": "TEXT",
    "note_obsidian_raw": "BLOB",
    "note_obsidian_sha256": "BLOB",
    "note_obsidian_body": "TEXT",
    "note_obsidian_frontmatter": "TEXT",
    "note_obsidian_joplin_body_sha256": "TEXT",
}

_ALL_COLUMNS = {**NOTE_COLUMNS, **JOPLIN_COLUMNS}
_INSERT_COLUMNS = list(NOTE_COLUMNS) + list(JOPLIN_COLUMNS)
_INSERT_SQL = (
    f"INSERT INTO notes ({', '.join(_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_INSERT_COLUMNS))});"
)

_INDEX_STATEMENTS = (
    'CREATE INDEX IF NOT EXISTS "hashidx" ON "notes" ("note_hash");',
    'CREATE INDEX IF NOT EXISTS "dateidx" ON "notes" ("note_internal_date");',
    'CREATE INDEX IF NOT EXISTS "joplinididx" ON "notes" ("joplin_id");',
    'CREATE INDEX IF NOT EXISTS "joplintypeidx" ON "notes" ("joplin_type_");',
    'CREATE INDEX IF NOT EXISTS "joplinparentidx" ON "notes" ("joplin_parent_id");',
    'CREATE INDEX IF NOT EXISTS "noteuuididx" ON "notes" ("note_uuid");',
    'CREATE INDEX IF NOT EXISTS "foldertitleidx" '
    'ON "notes" ("joplin_type_", "note_title");',
    'CREATE INDEX IF NOT EXISTS "obsidianpathidx" ON "notes" ("note_obsidian_path");',
)


def connect(database_path) -> sqlite3.Connection:
    """Open the notes database with the settings the scripts rely on."""
    conn = sqlite3.connect(str(database_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def ensure_indexes(sqlconn: sqlite3.Connection) -> None:
    """Create indexes shared by importers, exporters and maintenance tools."""
    for statement in _INDEX_STATEMENTS:
        sqlconn.execute(statement)


def create_database(
    sqlconn: sqlite3.Connection, *, create_indexes: bool = True
) -> None:
    """Create the settings and notes tables in a new database."""
    print("creating database...")
    column_defs = ",\n  ".join(f'"{name}" {type_}' for name, type_ in _ALL_COLUMNS.items())
    sqlconn.execute("CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT);")
    sqlconn.execute(
        "INSERT INTO settings (name, value) VALUES (?, ?);",
        ("db_version", DB_SCHEMA_VERSION),
    )
    sqlconn.execute(
        f'''CREATE TABLE IF NOT EXISTS "notes" (
  "note_id" INTEGER,
  {column_defs},
  PRIMARY KEY("note_id")
  );'''
    )
    if create_indexes:
        ensure_indexes(sqlconn)
    sqlconn.commit()


def get_db_settings(sqlcur: sqlite3.Cursor) -> dict:
    """Return the settings table as a dict, exiting if it is missing."""
    try:
        sqlcur.execute("SELECT name, value FROM settings")
        return dict(sqlcur)
    except sqlite3.OperationalError as exc:
        print(exc)
        sys.exit(6)


def _version_number(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def check_db_settings(db_settings: dict, prog: str) -> None:
    """Exit if the database schema version is outside the supported range."""
    version = _version_number(db_settings.get("db_version"))
    minimum = _version_number(DB_SCHEMA_MIN_VERSION)
    maximum = _version_number(DB_SCHEMA_VERSION)
    if version < minimum or version > maximum:
        print(
            f"\n\nThis database was created with version {db_settings.get('db_version')} "
            f"of the database schema while this program {prog} requires version "
            f"{DB_SCHEMA_MIN_VERSION} - {DB_SCHEMA_VERSION}.\n"
            "Recreate the database by re-importing the source, or open it with "
            "a compatible version of movenotes."
        )
        sys.exit(4)


def _ensure_schema_columns(sqlconn: sqlite3.Connection) -> set[str]:
    """Add missing columns and return the names that were added."""
    existing = {row[1] for row in sqlconn.execute("PRAGMA table_info(notes)")}
    added: set[str] = set()
    for name, type_ in _ALL_COLUMNS.items():
        if name not in existing:
            # SQLite only permits constant defaults in ALTER TABLE ADD COLUMN.
            # New tables keep CURRENT_TIMESTAMP; migrated databases add the
            # compatible base type and existing/new importers supply values.
            alter_type = type_.split(" DEFAULT ", 1)[0]
            sqlconn.execute(f'ALTER TABLE notes ADD COLUMN "{name}" {alter_type}')
            added.add(name)
    return added


def _bytes_value(value) -> bytes | None:  # noqa: ANN001
    """Normalise a SQLite BLOB value to ``bytes`` without copying bytes twice."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, memoryview):
        return value.tobytes()
    return bytes(value)


def source_sha256(raw) -> bytes | None:  # noqa: ANN001
    """Return the compact binary SHA-256 fingerprint for exact source bytes."""
    value = _bytes_value(raw)
    return hashlib.sha256(value).digest() if value is not None else None


def _backfill_source_sha256(
    sqlconn: sqlite3.Connection, *, batch_size: int = 500
) -> int:
    """Populate v4 source fingerprints in bounded-memory batches."""
    read_cursor = sqlconn.execute(
        "SELECT note_id, note_source_raw FROM notes "
        "WHERE note_source_raw IS NOT NULL AND note_source_sha256 IS NULL "
        "ORDER BY note_id"
    )
    updated = 0
    while True:
        rows = read_cursor.fetchmany(batch_size)
        if not rows:
            break
        values = [
            (source_sha256(row["note_source_raw"]), row["note_id"])
            for row in rows
        ]
        sqlconn.executemany(
            "UPDATE notes SET note_source_sha256 = ? WHERE note_id = ?", values
        )
        updated += len(values)
    return updated


def migrate_database(sqlconn: sqlite3.Connection, db_settings: dict) -> None:
    """Upgrade a supported older database in place to the current schema."""
    version = _version_number(db_settings["db_version"])
    if version < _version_number(DB_SCHEMA_VERSION):
        print(f"upgrading database schema {version} -> {DB_SCHEMA_VERSION}...")
    # Be tolerant of early development databases that claim the current
    # version but are missing a column or index.
    added_columns = _ensure_schema_columns(sqlconn)
    if version < 4 or "note_source_sha256" in added_columns:
        count = _backfill_source_sha256(sqlconn)
        if count:
            print(f"indexed {count} exact Joplin source item(s)")
    ensure_indexes(sqlconn)
    if version < _version_number(DB_SCHEMA_VERSION):
        sqlconn.execute(
            "UPDATE settings SET value = ? WHERE name = 'db_version'",
            (DB_SCHEMA_VERSION,),
        )
    sqlconn.commit()


def open_database(database_path, prog: str) -> sqlite3.Connection:
    """Open an existing database, verify it and apply supported migrations."""
    conn = connect(database_path)
    db_settings = get_db_settings(conn.cursor())
    check_db_settings(db_settings, prog)
    migrate_database(conn, db_settings)
    return conn


def add_joplin_note(sqlconn: sqlite3.Connection, columns: dict) -> None:
    """Insert one Joplin-style item row."""
    sqlconn.execute(
        _INSERT_SQL,
        tuple(columns.get(name) for name in _INSERT_COLUMNS),
    )


def add_joplin_notes(sqlconn: sqlite3.Connection, columns_list: list[dict]) -> None:
    """Insert a batch of Joplin-style item rows in one executemany call."""
    sqlconn.executemany(
        _INSERT_SQL,
        (
            tuple(columns.get(name) for name in _INSERT_COLUMNS)
            for columns in columns_list
        ),
    )


def load_joplin_source_fingerprints(
    sqlconn: sqlite3.Connection,
) -> dict[str, set[bytes | None]]:
    """Load compact collision metadata for every existing Joplin item ID.

    ``None`` represents a row with no exact source snapshot (for example a row
    generated by another importer). Such a row still reserves its Joplin ID and
    therefore collides with an incoming RAW item using the same ID.
    """
    records: dict[str, set[bytes | None]] = {}
    for row in sqlconn.execute(
        "SELECT joplin_id, note_source_sha256 FROM notes "
        "WHERE joplin_id IS NOT NULL AND joplin_id <> ''"
    ):
        item_id = str(row["joplin_id"])
        digest = _bytes_value(row["note_source_sha256"])
        records.setdefault(item_id, set()).add(digest)
    return records


def load_joplin_source_fingerprints_for_ids(
    sqlconn: sqlite3.Connection,
    item_ids,
    *,
    maximum_note_id: int | None = None,
    query_chunk_size: int = 800,
) -> dict[str, set[bytes | None]]:
    """Load collision metadata only for the requested Joplin item IDs.

    Importing a small source into a very large database should not preload the
    fingerprint for every stored row.  The requested IDs are looked up through
    the ``joplin_id`` index in bounded ``IN`` queries.  ``maximum_note_id`` can
    restrict the lookup to rows that existed before the current import began;
    duplicates within the current run are handled by the importer's in-memory
    digest map.
    """
    unique_ids = list(dict.fromkeys(str(item_id) for item_id in item_ids if item_id))
    records: dict[str, set[bytes | None]] = {}
    if not unique_ids:
        return records
    if query_chunk_size < 1:
        raise ValueError("query_chunk_size must be at least 1")

    for offset in range(0, len(unique_ids), query_chunk_size):
        chunk = unique_ids[offset : offset + query_chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        params: list[object] = list(chunk)
        where = f"joplin_id IN ({placeholders})"
        if maximum_note_id is not None:
            where += " AND note_id <= ?"
            params.append(maximum_note_id)
        for row in sqlconn.execute(
            "SELECT joplin_id, note_source_sha256 FROM notes WHERE " + where,
            params,
        ):
            item_id = str(row["joplin_id"])
            digest = _bytes_value(row["note_source_sha256"])
            records.setdefault(item_id, set()).add(digest)
    return records


def load_joplin_folder_titles(sqlconn: sqlite3.Connection) -> dict[str, str | None]:
    """Return existing Joplin folder IDs and their derived titles."""
    return {
        str(row["joplin_id"]): row["note_title"]
        for row in sqlconn.execute(
            "SELECT joplin_id, note_title FROM notes "
            "WHERE joplin_type_ = ? AND joplin_id IS NOT NULL",
            (2,),
        )
    }


def populate_missing_note_folders(
    sqlconn: sqlite3.Connection, *, minimum_note_id: int | None = None
) -> int:
    """Fill direct notebook titles with one indexed, set-based database pass.

    When ``minimum_note_id`` is supplied, only rows inserted during the current
    import are considered.  This avoids rescanning an established database
    when a small additional RAW directory is merged.
    """
    note_id_clause = ""
    params: list[object] = [2, 1]
    if minimum_note_id is not None:
        note_id_clause = " AND note_id >= ?"
        params.append(minimum_note_id)
    params.append(2)
    cursor = sqlconn.execute(
        f"""UPDATE notes
           SET note_folder = (
               SELECT parent.note_title
               FROM notes AS parent
               WHERE parent.joplin_id = notes.joplin_parent_id
                 AND parent.joplin_type_ = ?
               ORDER BY parent.note_id
               LIMIT 1
           )
           WHERE joplin_type_ = ?
             AND note_folder IS NULL
             {note_id_clause}
             AND joplin_parent_id IS NOT NULL
             AND joplin_parent_id <> ''
             AND EXISTS (
               SELECT 1
               FROM notes AS parent
               WHERE parent.joplin_id = notes.joplin_parent_id
                 AND parent.joplin_type_ = ?
           )""",
        params,
    )
    return max(cursor.rowcount, 0)


def decode_source_properties(value: str | None) -> list[tuple[str, str]]:
    """Decode an ordered JSON property list, discarding malformed entries."""
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    result: list[tuple[str, str]] = []
    if isinstance(decoded, list):
        for entry in decoded:
            if (
                isinstance(entry, list)
                and len(entry) == 2
                and isinstance(entry[0], str)
                and isinstance(entry[1], str)
            ):
                result.append((entry[0], entry[1]))
    return result


def _row_keys(row: sqlite3.Row | dict) -> set[str]:
    return set(row.keys())


def _format_property_value(column_name: str, value) -> str:
    float_formats = {
        "joplin_latitude": "{:.8f}",
        "joplin_longitude": "{:.8f}",
        "joplin_altitude": "{:.4f}",
    }
    if column_name in float_formats:
        return float_formats[column_name].format(value)
    return str(value)


def _changed_known_property_keys(
    row: sqlite3.Row | dict, source: list[tuple[str, str]]
) -> set[str]:
    """Return source property keys whose typed SQLite columns were changed."""
    keys = _row_keys(row)
    effective: dict[str, str] = {}
    for key, value in source:
        effective[key] = value

    changed: set[str] = set()
    for column_name, sqlite_type in JOPLIN_COLUMNS.items():
        if column_name not in keys:
            continue
        key = column_name.removeprefix("joplin_")
        source_value = effective.get(key)
        if source_value is None:
            if row[column_name] is not None:
                changed.add(key)
            continue
        normalised = source_value.strip()
        try:
            if sqlite_type == "INTEGER":
                expected = int(normalised) if normalised else None
            elif sqlite_type in {"FLOAT", "REAL"}:
                expected = float(normalised) if normalised else None
            else:
                expected = normalised
        except ValueError:
            changed.add(key)
            continue
        if row[column_name] != expected:
            changed.add(key)
    return changed


def joplin_property_pairs(row: sqlite3.Row | dict) -> list[tuple[str, str]]:
    """Return all Joplin properties for *row* in stable source order.

    Imported rows use the ordered source list, retaining unknown properties,
    duplicate keys, and the original logical value text. If a typed SQLite
    column has been edited, its updated value is substituted into each source
    occurrence of that property. Generated rows fall back to JOPLIN_COLUMNS.
    """
    keys = _row_keys(row)
    source = decode_source_properties(
        row["note_source_properties"] if "note_source_properties" in keys else None
    )
    changed_keys = _changed_known_property_keys(row, source)
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, source_value in source:
        column_name = f"joplin_{key}"
        value = source_value
        if key in changed_keys and column_name in keys and row[column_name] is not None:
            value = _format_property_value(column_name, row[column_name])
        output.append((key, value))
        seen.add(key)

    for column_name in JOPLIN_COLUMNS:
        key = column_name.removeprefix("joplin_")
        if key in seen or column_name not in keys:
            continue
        value = row[column_name]
        if value is not None:
            output.append((key, _format_property_value(column_name, value)))
    return output


def source_row_unchanged(row: sqlite3.Row | dict) -> bool:
    """Return True when parsed fields still match the imported RAW snapshot."""
    keys = _row_keys(row)
    if exact_source_bytes(row) is None or "note_source_body" not in keys:
        return False
    current_body = row.get("note_data") if isinstance(row, dict) else row["note_data"]
    if row["note_source_body"] is None or current_body != row["note_source_body"]:
        return False

    source = decode_source_properties(
        row["note_source_properties"] if "note_source_properties" in keys else None
    )
    return not _changed_known_property_keys(row, source)


def serialize_joplin_item(
    row: sqlite3.Row | dict,
    *,
    body: str | None = None,
    newline: str = "\n",
) -> bytes:
    """Reconstruct one Joplin RAW item from a database row.

    Exact imported bytes should be preferred when available.  This function is
    used for generated rows and for explicitly transformed exports.
    """
    keys = _row_keys(row)
    if body is None:
        body = row["note_data"] if "note_data" in keys else ""
    body = body or ""
    properties = joplin_property_pairs(row)
    property_text = newline.join(f"{key}: {value}" for key, value in properties)
    if body:
        text = body
        if not text.endswith(("\n", "\r")):
            text += newline
        text += newline + property_text
    else:
        text = property_text
    return text.encode("utf-8")


def exact_source_bytes(row: sqlite3.Row | dict) -> bytes | None:
    """Return exact imported RAW bytes, normalising SQLite BLOB wrappers."""
    keys = _row_keys(row)
    if "note_source_raw" not in keys:
        return None
    value = row["note_source_raw"]
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, memoryview):
        return value.tobytes()
    return bytes(value)
