"""Lossless Obsidian metadata carried through SQLite and Joplin RAW.

Native Obsidian notes do not have Joplin item IDs or a Joplin property block.
The importer therefore creates deterministic Joplin-compatible rows and stores
an exact compressed copy of each original vault file in ``application_data``.
Joplin preserves that property, so a later SQLite -> Joplin -> SQLite ->
Obsidian round trip can restore the original path and bytes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path, PurePosixPath

ENVELOPE_KEY = "movenotes_obsidian_v1"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_sha256(text: str) -> str:
    return sha256_hex(text.encode("utf-8"))


def _compressed_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(zlib.compress(data, 6)).decode("ascii")


def _decode_compressed_b64(value: str) -> bytes | None:
    try:
        return zlib.decompress(base64.urlsafe_b64decode(value.encode("ascii")))
    except (ValueError, TypeError, zlib.error):
        return None


def safe_relative_path(value: str) -> PurePosixPath | None:
    """Return a traversal-safe vault-relative path, or ``None``."""
    value = value.replace("\\", "/").lstrip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path


def deterministic_id(kind: str, relative_path: str) -> str:
    material = f"movenotes\0obsidian\0{kind}\0{relative_path}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def _existing_application_data(value: str | None) -> object | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def encode_note_application_data(
    *,
    relative_path: str,
    raw: bytes,
    generated_joplin_body: str,
    existing_application_data: str | None = None,
) -> str:
    envelope: dict[str, object] = {
        "kind": "note",
        "path": relative_path,
        "raw_zlib_base64": _compressed_b64(raw),
        "raw_sha256": sha256_hex(raw),
        "joplin_body_sha256": text_sha256(generated_joplin_body),
    }
    original = _existing_application_data(existing_application_data)
    root: dict[str, object] = {ENVELOPE_KEY: envelope}
    if original is not None:
        root["original_application_data"] = original
    return json.dumps(root, ensure_ascii=False, separators=(",", ":"))


def encode_path_application_data(
    *,
    kind: str,
    relative_path: str,
    existing_application_data: str | None = None,
) -> str:
    root: dict[str, object] = {
        ENVELOPE_KEY: {"kind": kind, "path": relative_path}
    }
    original = _existing_application_data(existing_application_data)
    if original is not None:
        root["original_application_data"] = original
    return json.dumps(root, ensure_ascii=False, separators=(",", ":"))


def decode_application_data(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    envelope = parsed.get(ENVELOPE_KEY)
    if not isinstance(envelope, dict):
        return None
    path = envelope.get("path")
    kind = envelope.get("kind")
    if not isinstance(path, str) or not isinstance(kind, str):
        return None
    if safe_relative_path(path) is None:
        return None
    return envelope


def note_snapshot(value: str | None) -> tuple[PurePosixPath, bytes, str] | None:
    envelope = decode_application_data(value)
    if envelope is None or envelope.get("kind") != "note":
        return None
    raw_value = envelope.get("raw_zlib_base64")
    body_hash = envelope.get("joplin_body_sha256")
    path_value = envelope.get("path")
    if not isinstance(raw_value, str) or not isinstance(body_hash, str) or not isinstance(path_value, str):
        return None
    raw = _decode_compressed_b64(raw_value)
    path = safe_relative_path(path_value)
    if raw is None or path is None:
        return None
    expected = envelope.get("raw_sha256")
    if isinstance(expected, str) and sha256_hex(raw) != expected:
        return None
    return path, raw, body_hash


def path_snapshot(value: str | None, expected_kind: str) -> PurePosixPath | None:
    envelope = decode_application_data(value)
    if envelope is None or envelope.get("kind") != expected_kind:
        return None
    path = envelope.get("path")
    return safe_relative_path(path) if isinstance(path, str) else None


def row_note_snapshot(row) -> tuple[PurePosixPath, bytes, str] | None:  # noqa: ANN001
    """Read an exact Obsidian snapshot from dedicated columns or metadata."""
    keys = set(row.keys())
    path_value = row["note_obsidian_path"] if "note_obsidian_path" in keys else None
    raw_value = row["note_obsidian_raw"] if "note_obsidian_raw" in keys else None
    body_hash = row["note_obsidian_joplin_body_sha256"] if "note_obsidian_joplin_body_sha256" in keys else None
    if path_value and raw_value is not None and body_hash:
        path = safe_relative_path(str(path_value))
        if path is not None:
            raw = raw_value.tobytes() if isinstance(raw_value, memoryview) else bytes(raw_value)
            return path, raw, str(body_hash)
    application_data = row["joplin_application_data"] if "joplin_application_data" in keys else None
    return note_snapshot(application_data)


def row_resource_path(row) -> PurePosixPath | None:  # noqa: ANN001
    keys = set(row.keys())
    path_value = row["note_obsidian_path"] if "note_obsidian_path" in keys else None
    if path_value:
        path = safe_relative_path(str(path_value))
        if path is not None:
            return path
    application_data = row["joplin_application_data"] if "joplin_application_data" in keys else None
    return path_snapshot(application_data, "resource")


def filesystem_relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
