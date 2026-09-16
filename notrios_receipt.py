"""Strict, opt-in propagation of content-free Notrios import receipts."""
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import secrets

from notrios_archive import NotriosError, strict_json_loads, _open_root_directory, _open_regular_file


RECEIPT_KEY = "movenotes.notrios.import.v1"
VAULT_PATH = Path(".movenotes/notrios-receipt.json")
SITE_PATH = Path("static/movenotes/notrios-receipt.json")
MAX_BYTES = 16384
_FIXED = {
    "version": 1, "contract": "notrios-archive-v2", "contract_schema_version": 1,
    "reader_profile": "movenotes-publication-loose-v1", "mapper": "movenotes-notrios-v1",
    "target": "publication_handoff",
}
_DIGESTS = ("commit_sha256", "selection_manifest_sha256")
_IDS = ("snapshot_id", "database_id")


def validate(value):
    if type(value) is not dict or set(value) != set(_FIXED) | set(_DIGESTS) | set(_IDS):
        raise NotriosError("receipt", "Notrios receipt fields differ from the supported allowlist")
    for name, expected in _FIXED.items():
        if type(value[name]) is not type(expected) or value[name] != expected:
            raise NotriosError("receipt", "unsupported Notrios receipt version or contract")
    for name, pattern in [(name, r"[0-9a-f]{64}") for name in _DIGESTS] + [
            (name, r"[a-z0-9][a-z0-9_.:-]{1,127}") for name in _IDS]:
        if type(value[name]) is not str or not re.fullmatch(pattern, value[name]):
            raise NotriosError("receipt", "invalid Notrios receipt digest or identity")
    return dict(value)


def _decode(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return validate(strict_json_loads(raw, max_bytes=MAX_BYTES, max_depth=4))


def from_settings(connection):
    row = connection.execute("SELECT length(CAST(value AS BLOB)) FROM settings WHERE name=?",
                             (RECEIPT_KEY,)).fetchone()
    if row is None:
        raise NotriosError("receipt", "no Notrios receipt in database settings")
    if row[0] is None or row[0] > MAX_BYTES:
        raise NotriosError("receipt", "Notrios receipt exceeds size limit")
    raw = connection.execute("SELECT value FROM settings WHERE name=?", (RECEIPT_KEY,)).fetchone()[0]
    if not isinstance(raw, (str, bytes)):
        raise NotriosError("receipt", "Notrios receipt must be JSON text")
    return _decode(raw)


def from_vault(root):
    with _open_root_directory(Path(root)) as fd:
        with _open_regular_file(fd, VAULT_PATH.as_posix()) as stream:
            return _decode(stream.read(MAX_BYTES + 1))


def remove_vault(root):
    """Remove only the reserved sidecar, including stale opt-out output."""
    with _open_root_directory(Path(root)) as root_fd:
        try:
            fd = os.open(".movenotes", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except FileNotFoundError:
            return
        try:
            try:
                os.unlink(VAULT_PATH.name, dir_fd=fd)
            except FileNotFoundError:
                pass
        finally:
            os.close(fd)


@contextmanager
def _write_errors():
    try:
        yield
    except OSError:
        raise NotriosError("receipt", "cannot write Notrios receipt sidecar") from None


def write(root, relative, receipt):
    """Atomically replace one validated sidecar within real output directories."""
    if relative not in (VAULT_PATH, SITE_PATH):
        raise ValueError("unsupported receipt location")
    raw = (json.dumps(validate(receipt), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n").encode("utf-8")
    with ExitStack() as stack:
        fd = stack.enter_context(_open_root_directory(Path(root)))
        stack.enter_context(_write_errors())
        for component in relative.parts[:-1]:
            try:
                os.mkdir(component, dir_fd=fd)
            except FileExistsError:
                pass
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        name = ".notrios-receipt-" + secrets.token_hex(16)
        temp_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        try:
            with os.fdopen(temp_fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, relative.name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(name, dir_fd=fd)
            except FileNotFoundError:
                pass
