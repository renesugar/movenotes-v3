"""Shared helper functions for the movenotes Joplin import/export scripts."""

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
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import constants

# Matches Joplin resource links, e.g.
#   ![IMAGE.JPG](:/7dd8b560cbc1467693f024d650870a0c)
#   [FILE.pdf](:/a56a1e70f3b14bb085f8b8d7794c05fc)
# Used by the export scripts to find attachments referenced by a note.
# The display text must not contain ']' so that two links on one line are
# not merged into a single greedy match.
#
# An optional Markdown link title, e.g. ``(:/id "Photo")``: separating spaces
# or tabs, then one "…", '…' or (…) on a single line holding no backslash,
# backtick or closing delimiter, then optional spaces or tabs. It is the same
# grammar notrios_links.py admits, so a title is copied rather than parsed.
LINK_TITLE = r"""[ \t]+(?:"[^"\\`\r\n]*"|'[^'\\`\r\n]*'|\([^()\\`\r\n]*\))[ \t]*"""
LINK_TITLE_RE = re.compile(LINK_TITLE)
RESOURCE_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(:/([a-fA-F0-9]{32})(" + LINK_TITLE + r")?\)")
RESOURCE_ID_RE = re.compile(r":/([a-fA-F0-9]{32})")

# An HTML image's ``src`` value, e.g. ``<img width="300" src=":/id">``: double-
# or single-quoted (groups 2 and 3) or unquoted (group 4). ``src`` must follow
# whitespace, so ``data-src`` is not one. The match ends with the value, so the
# rest of the tag is never touched.
HTML_IMAGE_SRC_RE = re.compile(
    r"""(<img\b[^<>]*?[ \t\r\n]src[ \t\r\n]*=[ \t\r\n]*)(?:"([^"<>]*)"|'([^'<>]*)'|([^\s"'<>=`]+))""",
    re.IGNORECASE,
)

# Characters treated as line breaks (or vertical whitespace) that must not
# appear in a note title.
_LINE_BREAKERS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
_LINE_BREAKER_TABLE = str.maketrans({c: " " for c in _LINE_BREAKERS})

# Characters stripped from the start of a body line to derive a title.
_TITLE_MARKUP_CHARS = "# \n\t*`-"


def error(msg: str) -> None:
    """Exit the program with an error message."""
    raise SystemExit(f"ERROR: {msg}")


def existing_dir(value: str) -> Path:
    """argparse type: an existing directory, expanded and made absolute."""
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"directory '{value}' does not exist")
    return path


def remove_line_breakers(s: str | None) -> str | None:
    """Replace all line-break characters in *s* with spaces."""
    if s is None:
        return None
    return s.translate(_LINE_BREAKER_TABLE)


def parse_isoformat_datetime(s: str) -> datetime:
    """Parse an ISO 8601 datetime, accepting a trailing 'Z' for UTC."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def create_uuid_string() -> str:
    """Create a new random id in Joplin's 32-hex-digit format."""
    return uuid.uuid4().hex


def default_title_from_body(body: str | None) -> str:
    """Derive a title from the first line of a note body.

    Leading markdown markup characters (``#``, ``*``, `` ` ``, ``-``) are
    stripped, matching how Joplin displays untitled notes.
    """
    if not body:
        return constants.NOTES_UNTITLED
    first_line = body.strip().split("\n", 1)[0].strip()
    title = first_line.lstrip(_TITLE_MARKUP_CHARS).strip()
    return title or constants.NOTES_UNTITLED


def check_extension(path: str | Path, exts: list[str] | None = None) -> bool:
    """Return True if *path* has one of the extensions in *exts*.

    *exts* is a list of extensions without leading dots. An empty or None
    *exts* matches everything.
    """
    if not exts:
        return True
    extension = Path(path).suffix.lstrip(".").casefold()
    if not extension:
        return False
    return any(extension == ext.lstrip(".").casefold() for ext in exts)


def files_identical(first: Path, second: Path, chunk_size: int = 1024 * 1024) -> bool:
    """Compare two files by size and content without loading them into memory."""
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        with first.open("rb") as a, second.open("rb") as b:
            while True:
                a_chunk = a.read(chunk_size)
                b_chunk = b.read(chunk_size)
                if a_chunk != b_chunk:
                    return False
                if not a_chunk:
                    return True
    except OSError:
        return False


def copy_file_if_changed(src: Path, dst_dir: Path, dst_name: str | None = None) -> bool:
    """Copy *src* into *dst_dir* unless an identical copy is already there.

    Content is compared byte-for-byte; size and modification time alone are
    not reliable enough for a lossless conversion. Returns True if copied.
    """
    dst = dst_dir / (dst_name or src.name)
    if dst.is_file() and files_identical(src, dst):
        return False
    shutil.copy2(src, dst)
    return True


def copy_resources(
    src_dir: Path, dst_dir: Path, *, reject_collisions: bool = False
) -> tuple[int, int]:
    """Copy attachment files from *src_dir* to *dst_dir*, skipping unchanged
    files. Returns ``(copied, skipped)`` counts.
    """
    copied = skipped = 0
    if src_dir.is_dir():
        if reject_collisions:
            files = [file_path for file_path in src_dir.iterdir() if file_path.is_file()]
            # Validate the whole set before writing any attachment.  The
            # SQLite transaction can roll back rows, but not a partial file
            # copy made before a later collision is discovered.
            for file_path in files:
                destination = dst_dir / file_path.name
                if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                    error(f"resource collision at '{destination}'")
                if destination.is_file() and not files_identical(file_path, destination):
                    error(f"resource collision at '{destination}'")
        else:
            files = (file_path for file_path in src_dir.iterdir() if file_path.is_file())
        for file_path in files:
            if file_path.is_file():
                if copy_file_if_changed(file_path, dst_dir):
                    copied += 1
                else:
                    skipped += 1
    return (copied, skipped)


def get_resource_links(text: str) -> list[tuple[str, str, str]]:
    """Find Joplin resource links in note text.

    Returns a list of ``(link, filename, resource_id)`` tuples for every
    ``[filename](:/resource_id)`` or ``![filename](:/resource_id)`` link,
    including one with a title, so a titled reference still counts.
    """
    return [(m.group(0), m.group(1), m.group(2)) for m in RESOURCE_LINK_RE.finditer(text)]


def get_resource_ids(text: str) -> set[str]:
    """Return every Joplin ``:/<id>`` reference, including links in HTML."""
    return {match.group(1).lower() for match in RESOURCE_ID_RE.finditer(text)}


def replace_html_image_sources(text: str, replace, where=None) -> str:
    """Replace each HTML image's ``src`` value with ``replace(value)``.

    Only the value's bytes change: the quotes, the attributes either side and
    the rest of the tag are kept. A ``None`` result keeps the value, and so
    does ``where(start, end)`` returning false for the tag's span. The
    replacement must be safe inside the value's quotes; a percent-encoded path
    is, quoted or not.
    """

    def substitute(match: re.Match[str]) -> str:
        if where is not None and not where(match.start(), match.end()):
            return match.group(0)
        group = next(index for index in (2, 3, 4) if match.group(index) is not None)
        replacement = replace(match.group(group))
        if replacement is None:
            return match.group(0)
        start, end = match.start(group) - match.start(), match.end(group) - match.start()
        return match.group(0)[:start] + replacement + match.group(0)[end:]

    return HTML_IMAGE_SRC_RE.sub(substitute, text)


# A markdown link whose display text is exactly its URL, e.g.
#   [https://example.com](https://example.com)
# The negative lookbehind excludes image links (![...](...)).
_URL_ONLY_LINK_RE = re.compile(r"(?<!!)\[(https?://[^\]\s]+)\]\(\1\)")

# A markdown autolink, e.g. <https://example.com>
_AUTOLINK_RE = re.compile(r"<(https?://[^<>\s]+)>")

# An inline code span on a single line, e.g. `[x](y)`
_INLINE_CODE_RE = re.compile(r"`[^`]*`")

# The start or end of a fenced code block (``` or ~~~).
_CODE_FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")


def _simplify_url_links_in_segment(segment: str) -> str:
    segment = _URL_ONLY_LINK_RE.sub(r"\1", segment)
    segment = _AUTOLINK_RE.sub(r"\1", segment)
    return segment


def simplify_url_links(text: str) -> str:
    """Replace URL-only markdown links with the bare URL.

    Joplin auto-links plain URLs, so ``[https://x](https://x)`` and
    ``<https://x>`` can be written as just ``https://x``, which reads
    better in the markdown source. Links with meaningful display text,
    image links, and resource links are left untouched, as is anything
    inside fenced code blocks or inline code spans.
    """
    output_lines = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            output_lines.append(line)
            continue
        if in_fence:
            output_lines.append(line)
            continue
        # Transform only the parts of the line outside inline code spans.
        parts = []
        last_end = 0
        for m in _INLINE_CODE_RE.finditer(line):
            parts.append(_simplify_url_links_in_segment(line[last_end : m.start()]))
            parts.append(m.group(0))
            last_end = m.end()
        parts.append(_simplify_url_links_in_segment(line[last_end:]))
        output_lines.append("".join(parts))
    return "".join(output_lines)


def note_type_from_joplin_type(type_: int | str) -> str:
    """Map a Joplin ``type_`` value to the note_type name stored in SQLite."""
    return constants.NOTE_TYPE_NAMES.get(int(type_), "")
