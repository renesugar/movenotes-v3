"""Pure identity and notesdb row projection for movenotes-notrios-v1.

Inputs come from the publication verifier; mapped IDs, transformed bodies and
resource storage choices are supplied by the caller. No files, databases, CLI
helpers or archive-wide identity registries are opened here.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re

import common
import constants
import notesdb
from notrios_archive import NotriosError, Record, _record_timestamp


MAPPER_NAME = "movenotes-notrios-v1"
_MAX_COMPONENT_BYTES = (1 << 32) - 1
_KEY_ARITIES = dict.fromkeys(("collection", "notebook", "document", "revision", "tag", "resource", "link"), 1)
_KEY_ARITIES.update(document_tag=2, document_resource=4)
_MAPPED_ID = re.compile(r"[0-9a-f]{32}\Z")
_EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
    "image/svg+xml": "svg", "image/avif": "avif", "image/bmp": "bmp", "image/tiff": "tif",
    "image/x-icon": "ico", "text/plain": "txt", "text/markdown": "md", "text/csv": "csv",
    "application/pdf": "pdf", "application/json": "json", "application/zip": "zip",
    "audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/wav": "wav", "video/mp4": "mp4", "video/webm": "webm",
}
_NOTE_DEFAULTS = (
    ("is_conflict", "0"), ("latitude", "0.00000000"), ("longitude", "0.00000000"), ("altitude", "0.0000"),
    ("author", ""), ("source_url", ""), ("is_todo", "0"), ("todo_due", "0"), ("todo_completed", "0"),
    ("source", "movenotes-notrios"), ("source_application", "movenotes-notrios2sql"),
    ("application_data", ""), ("order", "0"), ("markup_language", "1"), ("is_shared", "0"),
)


def source_key(database_id: str, kind: str, parts: tuple[str, ...]) -> bytes:
    """Frame the complete source identity without Unicode normalization.

    This is a general string encoder, not an archive-ID validator: the verifier
    applies the stricter ASCII ID grammar before calling the mapper.
    """
    if type(kind) is not str or kind not in _KEY_ARITIES or type(parts) is not tuple or len(parts) != _KEY_ARITIES[kind]:
        raise NotriosError("conversion", "invalid mapper key kind or arity")
    strings = (MAPPER_NAME, database_id, kind, *parts)
    encoded = []
    for value in strings:
        if type(value) is not str or len(value) > _MAX_COMPONENT_BYTES:
            raise NotriosError("conversion", "invalid or oversized mapper key component")
        try:
            raw = value.encode("utf-8")
        except UnicodeEncodeError:
            raise NotriosError("conversion", "mapper key contains invalid Unicode") from None
        if len(raw) > _MAX_COMPONENT_BYTES:
            raise NotriosError("conversion", "oversized mapper key component")
        encoded.append(len(raw).to_bytes(4, "big") + raw)
    if kind == "document_resource":
        ordinal = parts[3]
        if not re.fullmatch(r"0|[1-9][0-9]{0,18}", ordinal) or int(ordinal) > (1 << 63) - 1:
            raise NotriosError("conversion", "mapper ordinal must be a canonical nonnegative integer")
    return b"MNID\x00" + len(strings).to_bytes(4, "big") + b"".join(encoded)


def mapped_id(database_id: str, kind: str, parts: tuple[str, ...]) -> str:
    return hashlib.sha256(source_key(database_id, kind, parts)).hexdigest()[:32]


def joplin_timestamp(value: str) -> str:
    """Floor UTC nanoseconds to milliseconds without floating-point epochs."""
    if type(value) is not str:
        raise NotriosError("conversion", "invalid mapping timestamp")
    try:
        _record_timestamp(value)
    except NotriosError:
        raise NotriosError("conversion", "mapping timestamp must be a valid RFC3339 UTC instant") from None
    fraction = value[20:] if value[19:20] == "." else ""
    milliseconds = (re.match(r"[0-9]*", fraction)[0] + "000")[:3]
    return value[:19] + "." + milliseconds + "Z"


def resource_extension(mime: str) -> str:
    """Choose the frozen storage suffix from an already canonical MIME type."""
    return _EXTENSIONS.get(mime.split(";", 1)[0], "bin")


def _payload(record: Record, kind: str) -> Mapping:
    if not isinstance(record, Record) or record.kind != kind:
        raise NotriosError("conversion", "wrong record kind for row builder")
    return record.payload


def _check_mapped_id(value):
    if type(value) is not str or not _MAPPED_ID.fullmatch(value):
        raise NotriosError("conversion", "row builder requires a mapped item ID")


def generated_properties(row: Mapping) -> list[tuple[str, str]]:
    """Generate this mapper's fixed property profile from the row's inputs."""
    item_type = row["joplin_type_"]
    if type(item_type) is not int or item_type not in (1, 2, 4, 5, 6):
        raise NotriosError("conversion", "unsupported generated item type")
    pairs = [("id", row["joplin_id"])]
    if item_type in (1, 2):
        pairs.append(("parent_id", row["joplin_parent_id"]))
    created, updated = row["joplin_created_time"], row["joplin_updated_time"]
    pairs.extend((("created_time", created), ("updated_time", updated),
                  ("user_created_time", created), ("user_updated_time", updated),
                  ("encryption_cipher_text", ""), ("encryption_applied", "0")))
    if item_type == 1:
        pairs.extend(_NOTE_DEFAULTS)
    elif item_type == 2:
        pairs.extend((("is_shared", "0"), ("application_data", "")))
    elif item_type == 4:
        pairs.extend((key, str(row["joplin_" + key])) for key in ("mime", "filename", "file_extension", "size"))
        pairs.extend((("is_shared", "0"), ("application_data", "")))
    elif item_type == 6:
        pairs.extend((("note_id", row["joplin_note_id"]), ("tag_id", row["joplin_tag_id"])))
    pairs.extend((("user_data", ""), ("type_", str(item_type))))
    return pairs


def _row(*, item_id, item_type, title, body, created, updated, parent_id=None, note_id=None, tag_id=None, **extra):
    _check_mapped_id(item_id)
    for value in (note_id, tag_id):
        if value is not None:
            _check_mapped_id(value)
    if parent_id is not None and not (item_type == 2 and parent_id == ""):
        _check_mapped_id(parent_id)
    if type(title) is not str or type(body) is not str:
        raise NotriosError("conversion", "row title and body must be strings")
    created, updated = joplin_timestamp(created), joplin_timestamp(updated)
    try:
        digest = hashlib.sha512(body.encode("utf-8")).hexdigest()
        title.encode("utf-8")
    except UnicodeEncodeError:
        raise NotriosError("conversion", "row text contains invalid Unicode") from None
    row = dict.fromkeys((*notesdb.NOTE_COLUMNS, *notesdb.JOPLIN_COLUMNS))
    row.update(note_type=common.note_type_from_joplin_type(item_type), note_uuid=item_id,
               note_parent_uuid=parent_id, note_note_uuid=note_id, note_tag_uuid=tag_id,
               note_original_format="notrios", note_internal_date=created[:10] + " " + created[11:-1],
               note_hash=digest, note_title=title, note_data=body, note_data_format="text/markdown",
               joplin_id=item_id, joplin_type_=item_type, joplin_parent_id=parent_id,
               joplin_note_id=note_id, joplin_tag_id=tag_id, joplin_created_time=created,
               joplin_updated_time=updated, **extra)
    properties = generated_properties(row)
    for name, value in properties:
        column = "joplin_" + name
        sql_type = notesdb.JOPLIN_COLUMNS[column]
        row[column] = int(value) if sql_type == "INTEGER" else float(value) if sql_type in ("FLOAT", "REAL") else value
    row["note_source_properties"] = json.dumps(properties, ensure_ascii=False, separators=(",", ":"))
    return row


def build_notebook_row(record: Record, *, item_id, parent_id) -> dict:
    p = _payload(record, "notebook")
    if parent_id is None:
        raise NotriosError("conversion", "notebook parent must be mapped or the empty root parent")
    return _row(item_id=item_id, item_type=int(constants.JoplinType.FOLDER), title=p["name"], body=p["name"],
                created=p["created_at"], updated=p["updated_at"], parent_id=parent_id)


def build_note_row(document: Record, revision: Record, *, item_id, parent_id, body) -> dict:
    p, r = _payload(document, "document"), _payload(revision, "revision")
    if p["current_revision_id"] != r["id"] or r["document_id"] != p["id"]:
        raise NotriosError("conversion", "note row requires its owning current revision")
    _check_mapped_id(parent_id)
    return _row(item_id=item_id, item_type=int(constants.JoplinType.NOTE), title=r["title"], body=body,
                created=p["created_at"], updated=p["updated_at"], parent_id=parent_id)


def build_tag_row(record: Record, *, item_id) -> dict:
    p = _payload(record, "tag")
    return _row(item_id=item_id, item_type=int(constants.JoplinType.TAG), title=p["name"], body=p["name"],
                created=p["created_at"], updated=p["created_at"])


def build_note_tag_row(*, item_id, note_id, tag_id, timestamp) -> dict:
    _check_mapped_id(note_id)
    _check_mapped_id(tag_id)
    return _row(item_id=item_id, item_type=int(constants.JoplinType.NOTE_TAG), title="", body="",
                created=timestamp, updated=timestamp, note_id=note_id, tag_id=tag_id)


def build_resource_row(record: Record, *, item_id, mime, extension) -> dict:
    p = _payload(record, "resource")
    if mime != p["blob"]["media_type"] or extension != resource_extension(mime):
        raise NotriosError("conversion", "resource storage MIME or extension differs from the frozen mapping")
    basename = re.split(r"[/\\]", p.get("filename", ""))[-1]
    filename = re.sub(r"[\x00-\x1f\x7f]", "", basename).strip()
    if filename in ("", ".", ".."):
        filename = "attachment." + extension
    return _row(item_id=item_id, item_type=int(constants.JoplinType.RESOURCE), title=filename, body=filename,
                created=p["created_at"], updated=p["created_at"], joplin_mime=mime,
                joplin_filename=filename, joplin_file_extension=extension, joplin_size=p["blob"]["size_bytes"])
