"""Shared image-link conversion helpers for movenotes.

The module intentionally uses only the Python standard library.  It parses
inline Markdown image links outside code, decodes data-image URIs, retrieves
remote images with a HEAD-first redirect inspection, validates the declared
MIME type against the file signature, creates deterministic Joplin resources,
and writes machine-readable Markdown issue reports.
"""

from __future__ import annotations

import base64
import binascii
import collections
import configparser
import hashlib
import html
import ipaddress
import json
import re
import socket
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import common
import constants
import notesdb

REPORT_METADATA_PREFIX = "movenotes-image-issue "
DEFAULT_CONFIG_FILENAME = "movenotes-images.ini"
DEFAULT_REPORT_FILENAME = "images2resources-report.md"
DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_WORKERS = 8

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_HEAD_FALLBACK_CODES = {403, 405, 501}
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_DATA_PREFIX_RE = re.compile(r"^data:image/", re.IGNORECASE)
_HTTP_PREFIX_RE = re.compile(r"^https?://", re.IGNORECASE)
_MALFORMED_DATA_MARKER_RE = re.compile(r"data:image/", re.IGNORECASE)
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+")

_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
    "image/x-icon": "image/vnd.microsoft.icon",
    "image/ico": "image/vnd.microsoft.icon",
    "image/svg": "image/svg+xml",
}
_MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tif",
    "image/vnd.microsoft.icon": "ico",
    "image/avif": "avif",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/svg+xml": "svg",
}
_EXTENSION_MIMES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "jpe": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "ico": "image/vnd.microsoft.icon",
    "avif": "image/avif",
    "heic": "image/heic",
    "heif": "image/heif",
    "svg": "image/svg+xml",
}


@dataclass(frozen=True)
class ImageLink:
    """One inline Markdown image link and its source offsets."""

    start: int
    end: int
    raw: str
    alt: str
    destination: str
    line: int
    malformed: bool = False

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.raw.encode("utf-8")).hexdigest()


@dataclass
class Issue:
    """A reportable image conversion problem."""

    category: str
    kind: str
    note_id: str
    note_title: str
    note_filename: str
    line: int
    raw: str
    detail: str
    fingerprint: str
    occurrence: int = 1
    url: str | None = None
    redirect_from: str | None = None
    redirect_to: str | None = None
    original_mime: str | None = None
    final_mime: str | None = None

    @property
    def issue_id(self) -> str:
        seed = f"{self.note_id}\0{self.fingerprint}\0{self.occurrence}\0{self.kind}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]

    def metadata(self) -> dict:
        result = {
            "id": self.issue_id,
            "note_id": self.note_id,
            "kind": self.kind,
            "category": self.category,
            "fingerprint": self.fingerprint,
            "occurrence": self.occurrence,
            "line": self.line,
        }
        if self.url:
            result["url"] = self.url
        return result


@dataclass
class Settings:
    """Configuration shared by the conversion and quarantine scripts."""

    stop_domains: set[str] = field(default_factory=set)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    workers: int = DEFAULT_WORKERS
    user_agent: str = "movenotes-images2resources/1.0"
    allow_private_networks: bool = False
    allow_svg: bool = False
    report_file: str = DEFAULT_REPORT_FILENAME


@dataclass
class FetchResult:
    """Result of retrieving one remote image."""

    url: str
    final_url: str | None = None
    content: bytes | None = None
    mime: str | None = None
    extension: str | None = None
    redirects: list[tuple[str, str]] = field(default_factory=list)
    issue_kind: str | None = None
    issue_category: str = "could-not-convert"
    detail: str = ""
    original_mime: str | None = None
    final_mime: str | None = None

    @property
    def ok(self) -> bool:
        return self.content is not None and self.mime is not None and self.extension is not None


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Expose redirect responses so the caller can inspect every hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class FetchProblem(Exception):
    def __init__(
        self,
        kind: str,
        detail: str,
        *,
        category: str = "could-not-convert",
        final_url: str | None = None,
        redirects: list[tuple[str, str]] | None = None,
        original_mime: str | None = None,
        final_mime: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.category = category
        self.final_url = final_url
        self.redirects = redirects or []
        self.original_mime = original_mime
        self.final_mime = final_mime


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def normalise_mime(value: str | None) -> str | None:
    if not value:
        return None
    mime = value.split(";", 1)[0].strip().lower()
    return _MIME_ALIASES.get(mime, mime) or None


def extension_for_mime(mime: str) -> str | None:
    return _MIME_EXTENSIONS.get(normalise_mime(mime) or "")


def mime_from_url(url: str) -> str | None:
    path = urllib.parse.urlsplit(url).path
    extension = Path(urllib.parse.unquote(path)).suffix.lstrip(".").lower()
    return _EXTENSION_MIMES.get(extension)


def _is_svg(data: bytes) -> bool:
    prefix = data[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    if prefix.startswith(b"<?xml"):
        marker = prefix.find(b"<svg")
        return marker >= 0
    return prefix.startswith(b"<svg")


def sniff_image_mime(data: bytes) -> str | None:
    """Identify common image formats from magic bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")):
        return "image/vnd.microsoft.icon"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"avif", b"avis"}:
            return "image/avif"
        if brand in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}:
            return "image/heic"
    if _is_svg(data):
        return "image/svg+xml"
    return None


def load_config(config_path: Path | None) -> tuple[configparser.ConfigParser, Settings]:
    """Load an INI file, returning defaults when it does not exist."""
    parser = configparser.ConfigParser(interpolation=None)
    if config_path is not None and config_path.is_file():
        parser.read(config_path, encoding="utf-8")
    section = parser["images2resources"] if parser.has_section("images2resources") else {}

    domains_text = str(section.get("stop_domains", ""))
    domains = {
        token.strip().lower().lstrip(".")
        for token in re.split(r"[\s,]+", domains_text)
        if token.strip()
    }

    def get_int(name: str, default: int, minimum: int = 1) -> int:
        try:
            return max(minimum, int(section.get(name, default)))
        except (TypeError, ValueError):
            return default

    def get_float(name: str, default: float) -> float:
        try:
            return max(0.1, float(section.get(name, default)))
        except (TypeError, ValueError):
            return default

    def get_bool(name: str, default: bool) -> bool:
        if not hasattr(section, "getboolean"):
            return default
        try:
            return section.getboolean(name, fallback=default)
        except ValueError:
            return default

    settings = Settings(
        stop_domains=domains,
        timeout_seconds=get_float("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        max_image_bytes=get_int("max_image_bytes", DEFAULT_MAX_IMAGE_BYTES),
        max_redirects=get_int("max_redirects", DEFAULT_MAX_REDIRECTS, minimum=0),
        workers=get_int("workers", DEFAULT_WORKERS),
        user_agent=str(section.get("user_agent", "movenotes-images2resources/1.0")),
        allow_private_networks=get_bool("allow_private_networks", False),
        allow_svg=get_bool("allow_svg", False),
        report_file=str(section.get("report_file", DEFAULT_REPORT_FILENAME)),
    )
    return parser, settings


def ensure_default_config(parser: configparser.ConfigParser) -> None:
    if not parser.has_section("images2resources"):
        parser.add_section("images2resources")
    section = parser["images2resources"]
    defaults = {
        "stop_domains": "",
        "timeout_seconds": str(DEFAULT_TIMEOUT_SECONDS),
        "max_image_bytes": str(DEFAULT_MAX_IMAGE_BYTES),
        "max_redirects": str(DEFAULT_MAX_REDIRECTS),
        "workers": str(DEFAULT_WORKERS),
        "user_agent": "movenotes-images2resources/1.0",
        "allow_private_networks": "false",
        "allow_svg": "false",
        "report_file": DEFAULT_REPORT_FILENAME,
    }
    for key, value in defaults.items():
        section.setdefault(key, value)
    if not parser.has_section("quarantine"):
        parser.add_section("quarantine")
    quarantine = parser["quarantine"]
    quarantine.setdefault("replacement_image", "")
    quarantine.setdefault("replacement_resource_id", "")
    quarantine.setdefault("replacement_resource_file", "")
    quarantine.setdefault("replacement_mime", "")
    quarantine.setdefault("replacement_title", "Image removed")
    quarantine.setdefault("quarantine_domains", "")


def write_config(parser: configparser.ConfigParser, config_path: Path) -> None:
    """Write the INI and keep the quarantine-managed block canonical."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8", newline="\n") as handle:
        parser.write(handle)
    text = config_path.read_text(encoding="utf-8")
    quarantine = parser["quarantine"] if parser.has_section("quarantine") else {}
    managed = (
        "# Managed by quarantinelinks.py after the replacement is imported. Normally do\n"
        "# not edit these values; they make subsequent runs reuse one local resource.\n"
        f"replacement_resource_id = {quarantine.get('replacement_resource_id', '')}\n"
        f"replacement_resource_file = {quarantine.get('replacement_resource_file', '')}\n"
        f"replacement_mime = {quarantine.get('replacement_mime', '')}"
    )
    pattern = re.compile(
        r"(?:# Managed by quarantinelinks\.py[^\n]*\n(?:#.*\n)*)?"
        r"replacement_resource_id\s*=.*\n"
        r"replacement_resource_file\s*=.*\n"
        r"replacement_mime\s*=.*",
        re.MULTILINE,
    )
    text, count = pattern.subn(managed, text, count=1)
    if count == 0 and "[quarantine]" in text:
        text = text.rstrip() + "\n\n" + managed + "\n"
    config_path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def _code_mask(text: str) -> bytearray:
    """Return a byte mask marking fenced and inline code positions."""
    mask = bytearray(len(text))
    offset = 0
    in_fence = False
    fence_char = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        match = _FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                in_fence = False
            mask[offset : offset + len(line)] = b"\x01" * len(line)
            offset += len(line)
            continue
        if in_fence:
            mask[offset : offset + len(line)] = b"\x01" * len(line)
            offset += len(line)
            continue

        # Common single-line inline-code cases, including multi-backtick spans.
        index = 0
        while index < len(line):
            if line[index] != "`":
                index += 1
                continue
            run_end = index + 1
            while run_end < len(line) and line[run_end] == "`":
                run_end += 1
            marker = line[index:run_end]
            close = line.find(marker, run_end)
            if close < 0:
                index = run_end
                continue
            end = close + len(marker)
            mask[offset + index : offset + end] = b"\x01" * (end - index)
            index = end
        offset += len(line)
    return mask


def _find_unescaped(text: str, start: int, target: str, limit: int | None = None) -> int:
    end = len(text) if limit is None else min(limit, len(text))
    escaped = False
    for index in range(start, end):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == target:
            return index
    return -1


def _find_closing_paren(text: str, start: int) -> int:
    depth = 1
    quote: str | None = None
    angle = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if angle:
            if char == ">":
                angle = False
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char == "<":
            angle = True
        elif char in ('"', "'"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        elif char in "\r\n" and depth == 1:
            # Inline links spanning lines are uncommon and make malformed-data
            # quarantine ambiguous. Leave them untouched and report data URIs.
            return -1
    return -1


def _parse_destination(inner: str) -> str | None:
    stripped = inner.strip()
    if not stripped:
        return None
    if stripped.startswith("<"):
        close = _find_unescaped(stripped, 1, ">")
        if close < 0:
            return None
        return stripped[1:close]

    escaped = False
    depth = 0
    chars: list[str] = []
    for char in stripped:
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "(" :
            depth += 1
            chars.append(char)
            continue
        if char == ")" and depth:
            depth -= 1
            chars.append(char)
            continue
        if char.isspace() and depth == 0:
            break
        chars.append(char)
    return html.unescape("".join(chars)) or None


def scan_markdown_images(text: str) -> tuple[list[ImageLink], list[ImageLink]]:
    """Scan inline Markdown images outside code.

    Returns ``(valid_links, malformed_data_image_candidates)``.  The parser
    supports angle-bracket destinations, optional titles, escaped punctuation,
    and balanced parentheses in URLs.
    """
    mask = _code_mask(text)
    valid: list[ImageLink] = []
    index = 0
    while True:
        start = text.find("![", index)
        if start < 0:
            break
        index = start + 2
        if mask[start]:
            continue
        alt_end = _find_unescaped(text, start + 2, "]")
        if alt_end < 0:
            continue
        cursor = alt_end + 1
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
        if cursor >= len(text) or text[cursor] != "(":
            continue
        close = _find_closing_paren(text, cursor + 1)
        if close < 0:
            continue
        destination = _parse_destination(text[cursor + 1 : close])
        if destination is None:
            continue
        raw = text[start : close + 1]
        valid.append(
            ImageLink(
                start=start,
                end=close + 1,
                raw=raw,
                alt=text[start + 2 : alt_end],
                destination=destination,
                line=text.count("\n", 0, start) + 1,
            )
        )
        index = close + 1

    covered = [(link.start, link.end) for link in valid]
    malformed: list[ImageLink] = []
    for match in _MALFORMED_DATA_MARKER_RE.finditer(text):
        marker = match.start()
        if mask[marker] or any(start <= marker < end for start, end in covered):
            continue
        line_start = text.rfind("\n", 0, marker) + 1
        line_end = text.find("\n", marker)
        if line_end < 0:
            line_end = len(text)
        opener = text.rfind("![", line_start, marker)
        candidate_start = opener if opener >= 0 else marker
        close = text.find(")", marker, line_end)
        candidate_end = close + 1 if close >= 0 else line_end
        raw = text[candidate_start:candidate_end]
        malformed.append(
            ImageLink(
                start=candidate_start,
                end=candidate_end,
                raw=raw,
                alt="",
                destination="",
                line=text.count("\n", 0, candidate_start) + 1,
                malformed=True,
            )
        )
    return valid, malformed


def decode_data_image(
    destination: str, *, allow_svg: bool, max_bytes: int = DEFAULT_MAX_IMAGE_BYTES
) -> tuple[bytes, str, str]:
    """Decode and validate a base64 image data URI."""
    if not destination.lower().startswith("data:"):
        raise ValueError("not a data URI")
    try:
        header, payload = destination.split(",", 1)
    except ValueError as exc:
        raise FetchProblem("malformed-data-uri", "data URI has no comma separator") from exc
    parts = header[5:].split(";")
    declared_mime = normalise_mime(parts[0])
    parameters = {part.strip().lower() for part in parts[1:] if part.strip()}
    if not declared_mime or not declared_mime.startswith("image/"):
        raise FetchProblem("malformed-data-uri", "data URI does not declare an image MIME type")
    if "base64" not in parameters:
        raise FetchProblem(
            "unsupported-data-uri",
            "embedded image data URI is not base64 encoded",
            category="badly-formatted",
        )
    compact = re.sub(r"\s+", "", payload)
    estimated_size = (len(compact) * 3) // 4
    if estimated_size > max_bytes:
        raise FetchProblem(
            "image-too-large",
            f"embedded image exceeds configured limit of {max_bytes} bytes",
        )
    try:
        content = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FetchProblem("invalid-base64", f"invalid base64 image data: {exc}", category="badly-formatted") from exc
    if len(content) > max_bytes:
        raise FetchProblem(
            "image-too-large",
            f"embedded image exceeds configured limit of {max_bytes} bytes",
        )
    if not content:
        raise FetchProblem("empty-image", "embedded image decoded to zero bytes", category="badly-formatted")
    actual_mime = sniff_image_mime(content)
    if actual_mime is None:
        raise FetchProblem(
            "unrecognised-image-data",
            "decoded data does not have a recognised image signature",
            category="badly-formatted",
            original_mime=declared_mime,
        )
    if normalise_mime(actual_mime) != declared_mime:
        raise FetchProblem(
            "data-content-type-mismatch",
            f"data URI declares {declared_mime} but bytes are {actual_mime}",
            category="badly-formatted",
            original_mime=declared_mime,
            final_mime=actual_mime,
        )
    if actual_mime == "image/svg+xml" and not allow_svg:
        raise FetchProblem(
            "svg-disabled",
            "SVG conversion is disabled by configuration",
            category="should-not-convert",
            original_mime=declared_mime,
        )
    extension = extension_for_mime(actual_mime)
    if extension is None:
        raise FetchProblem("unsupported-image-type", f"unsupported image MIME type {actual_mime}")
    return content, actual_mime, extension


def parse_domain_list(value: str) -> set[str]:
    """Parse comma/whitespace separated domain names."""
    return {
        token.strip().lower().rstrip(".")
        for token in re.split(r"[\s,]+", value or "")
        if token.strip()
    }


def host_matches_domains(host: str | None, domains: set[str]) -> str | None:
    if not host:
        return None
    host = host.lower().rstrip(".")
    for domain in domains:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def _host_matches_stoplist(host: str, stop_domains: set[str]) -> str | None:
    return host_matches_domains(host, stop_domains)


def _is_non_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    return not ip.is_global


def validate_remote_url(url: str, settings: Settings) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise FetchProblem(
            "unsupported-url-scheme",
            f"URL scheme '{parsed.scheme or '(missing)'}' is not HTTP or HTTPS",
            category="should-not-convert",
        )
    if not parsed.hostname:
        raise FetchProblem("invalid-url", "URL has no hostname")
    stop_domain = _host_matches_stoplist(parsed.hostname, settings.stop_domains)
    if stop_domain:
        raise FetchProblem(
            "stop-listed-domain",
            f"domain '{stop_domain}' is on the download stop list",
            category="should-not-convert",
        )
    if settings.allow_private_networks:
        return
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise FetchProblem("dns-failure", f"cannot resolve host: {exc}") from exc
    blocked = sorted(address for address in addresses if _is_non_public_address(address))
    if blocked:
        raise FetchProblem(
            "blocked-private-address",
            f"host resolves to non-public address(es): {', '.join(blocked)}",
            category="should-not-convert",
        )


def _open_once(
    opener: urllib.request.OpenerDirector,
    url: str,
    method: str,
    settings: Settings,
):
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    try:
        return opener.open(request, timeout=settings.timeout_seconds)
    except urllib.error.HTTPError as exc:
        return exc


def _request_chain(
    url: str,
    method: str,
    settings: Settings,
    *,
    read_body: bool,
) -> tuple[int, object, str, list[tuple[str, str]], bytes | None]:
    opener = urllib.request.build_opener(NoRedirectHandler())
    current = url
    redirects: list[tuple[str, str]] = []
    first_headers = None
    for _hop in range(settings.max_redirects + 1):
        validate_remote_url(current, settings)
        try:
            response = _open_once(opener, current, method, settings)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchProblem(
                "network-error",
                f"{method} request failed: {exc}",
                final_url=current,
                redirects=redirects,
            ) from exc
        status = int(getattr(response, "status", response.getcode()))
        headers = response.headers
        if first_headers is None:
            first_headers = headers
        if status in _REDIRECT_CODES:
            location = headers.get("Location")
            response.close()
            if not location:
                raise FetchProblem(
                    "redirect-without-location",
                    f"HTTP {status} redirect has no Location header",
                    final_url=current,
                    redirects=redirects,
                )
            target = urllib.parse.urljoin(current, location)
            redirects.append((current, target))
            current = target
            continue
        body = None
        if read_body:
            try:
                body = response.read(settings.max_image_bytes + 1)
            finally:
                response.close()
            if len(body) > settings.max_image_bytes:
                raise FetchProblem(
                    "image-too-large",
                    f"image exceeds configured limit of {settings.max_image_bytes} bytes",
                    final_url=current,
                    redirects=redirects,
                )
        else:
            response.close()
        return status, headers, first_headers, current, redirects, body
    raise FetchProblem(
        "too-many-redirects",
        f"more than {settings.max_redirects} redirects",
        final_url=current,
        redirects=redirects,
    )


def fetch_remote_image(url: str, settings: Settings) -> FetchResult:
    """Retrieve one image after HEAD-first redirect and MIME inspection."""
    try:
        validate_remote_url(url, settings)
        url_mime = mime_from_url(url)
        head_status, head_headers, head_first_headers, head_final, head_redirects, _ = _request_chain(
            url, "HEAD", settings, read_body=False
        )
        head_mime = normalise_mime(head_headers.get("Content-Type"))
        head_initial_mime = normalise_mime(head_first_headers.get("Content-Type")) if head_first_headers else None
        original_mime = url_mime
        if not original_mime and head_initial_mime and head_initial_mime.startswith("image/"):
            original_mime = head_initial_mime
        if not original_mime and not head_redirects and head_mime and head_mime.startswith("image/"):
            original_mime = head_mime

        if head_status not in range(200, 300) and head_status not in _HEAD_FALLBACK_CODES:
            raise FetchProblem(
                "http-status",
                f"HEAD returned HTTP {head_status}",
                final_url=head_final,
                redirects=head_redirects,
                original_mime=original_mime,
                final_mime=head_mime,
            )

        if head_redirects and original_mime and head_mime and original_mime != head_mime:
            raise FetchProblem(
                "redirect-content-type-change",
                f"redirect changed image type from {original_mime} to {head_mime}",
                final_url=head_final,
                redirects=head_redirects,
                original_mime=original_mime,
                final_mime=head_mime,
            )

        length_header = head_headers.get("Content-Length")
        if length_header:
            try:
                if int(length_header) > settings.max_image_bytes:
                    raise FetchProblem(
                        "image-too-large",
                        f"Content-Length {length_header} exceeds configured limit of {settings.max_image_bytes} bytes",
                        final_url=head_final,
                        redirects=head_redirects,
                    )
            except ValueError:
                pass

        get_status, get_headers, get_first_headers, final_url, get_redirects, content = _request_chain(
            url, "GET", settings, read_body=True
        )
        if get_status not in range(200, 300):
            raise FetchProblem(
                "http-status",
                f"GET returned HTTP {get_status}",
                final_url=final_url,
                redirects=get_redirects,
                original_mime=original_mime,
                final_mime=normalise_mime(get_headers.get("Content-Type")),
            )
        final_mime = normalise_mime(get_headers.get("Content-Type"))
        get_initial_mime = normalise_mime(get_first_headers.get("Content-Type")) if get_first_headers else None
        if not original_mime and get_initial_mime and get_initial_mime.startswith("image/"):
            original_mime = get_initial_mime
        all_redirects = get_redirects or head_redirects
        if all_redirects and original_mime and final_mime and original_mime != final_mime:
            raise FetchProblem(
                "redirect-content-type-change",
                f"redirect changed image type from {original_mime} to {final_mime}",
                final_url=final_url,
                redirects=all_redirects,
                original_mime=original_mime,
                final_mime=final_mime,
            )
        if head_status in range(200, 300) and head_mime and final_mime and head_mime != final_mime:
            raise FetchProblem(
                "head-get-content-type-change",
                f"HEAD reported {head_mime} but GET reported {final_mime}",
                final_url=final_url,
                redirects=all_redirects,
                original_mime=head_mime,
                final_mime=final_mime,
            )
        if not final_mime or not final_mime.startswith("image/"):
            raise FetchProblem(
                "non-image-content-type",
                f"server returned Content-Type {final_mime or '(missing)'}",
                final_url=final_url,
                redirects=all_redirects,
                original_mime=original_mime,
                final_mime=final_mime,
            )
        if content is None:
            raise FetchProblem("empty-response", "GET returned no response body")
        actual_mime = sniff_image_mime(content)
        if actual_mime is None:
            raise FetchProblem(
                "unrecognised-image-data",
                "downloaded bytes do not have a recognised image signature",
                final_url=final_url,
                redirects=all_redirects,
                original_mime=original_mime,
                final_mime=final_mime,
            )
        if actual_mime != final_mime:
            raise FetchProblem(
                "content-type-mismatch",
                f"server declared {final_mime} but bytes are {actual_mime}",
                final_url=final_url,
                redirects=all_redirects,
                original_mime=original_mime,
                final_mime=actual_mime,
            )
        if actual_mime == "image/svg+xml" and not settings.allow_svg:
            raise FetchProblem(
                "svg-disabled",
                "SVG conversion is disabled by configuration",
                category="should-not-convert",
                final_url=final_url,
                redirects=all_redirects,
                original_mime=original_mime,
                final_mime=actual_mime,
            )
        extension = extension_for_mime(actual_mime)
        if extension is None:
            raise FetchProblem(
                "unsupported-image-type",
                f"unsupported image MIME type {actual_mime}",
                final_url=final_url,
                redirects=all_redirects,
            )
        return FetchResult(
            url=url,
            final_url=final_url,
            content=content,
            mime=actual_mime,
            extension=extension,
            redirects=all_redirects,
            original_mime=original_mime,
            final_mime=actual_mime,
        )
    except FetchProblem as exc:
        return FetchResult(
            url=url,
            final_url=exc.final_url,
            redirects=exc.redirects,
            issue_kind=exc.kind,
            issue_category=exc.category,
            detail=exc.detail,
            original_mime=exc.original_mime,
            final_mime=exc.final_mime,
        )
    except Exception as exc:  # Last-resort report instead of aborting a batch.
        return FetchResult(
            url=url,
            issue_kind="unexpected-download-error",
            detail=f"{type(exc).__name__}: {exc}",
        )


def safe_title(text: str | None, fallback: str) -> str:
    value = common.remove_line_breakers(text or "") or ""
    value = re.sub(r"[\\/*?:\"<>|\[\]]+", " ", value)
    value = " ".join(value.split()).strip(". ")
    return value[:120] or fallback


def title_from_link(link: ImageLink, extension: str, remote_url: str | None = None) -> str:
    fallback = "Embedded image" if _DATA_PREFIX_RE.match(link.destination) else "Remote image"
    title = safe_title(link.alt, "")
    if not title and remote_url:
        basename = Path(urllib.parse.unquote(urllib.parse.urlsplit(remote_url).path)).name
        title = safe_title(basename, "")
    if not title:
        title = fallback
    if not title.lower().endswith("." + extension.lower()):
        title += "." + extension
    return title


def markdown_resource_embed(alt: str, resource_id: str, fallback: str) -> str:
    display = safe_title(alt, fallback)
    return f"![{display}](:/{resource_id})"


class ResourceStore:
    """Create or reuse deterministic Joplin resource rows and files."""

    def __init__(self, sqlconn: sqlite3.Connection, resources_path: Path) -> None:
        self.sqlconn = sqlconn
        self.resources_path = resources_path
        self.resources_path.mkdir(parents=True, exist_ok=True)
        self.created_ids: set[str] = set()
        self.reused_ids: set[str] = set()
        self._content_ids: dict[bytes, str] = {}
        self._files_by_resource_id: dict[str, list[Path]] = collections.defaultdict(list)
        for path in sorted(self.resources_path.iterdir()):
            if path.is_file():
                resource_id = path.name.split(".", 1)[0]
                self._files_by_resource_id[resource_id].append(path)

    def _candidate_id(self, content: bytes, counter: int = 0) -> str:
        seed = content if counter == 0 else content + b"\0movenotes-collision\0" + str(counter).encode()
        return hashlib.sha256(seed).hexdigest()[:32]

    def _resource_file_candidates(self, resource_id: str) -> list[Path]:
        return self._files_by_resource_id.get(resource_id, [])

    def _remember_resource_file(self, path: Path) -> None:
        files = self._files_by_resource_id[path.name.split(".", 1)[0]]
        if path not in files:
            files.append(path)
            files.sort()

    def _existing_content_matches(self, resource_id: str, content: bytes) -> bool:
        candidates = self._resource_file_candidates(resource_id)
        return any(path.read_bytes() == content for path in candidates)

    def _record_source_url(self, row: sqlite3.Row, source_url: str | None) -> None:
        """Append provenance without overwriting non-JSON user data."""
        if not source_url:
            return
        raw = row["joplin_user_data"]
        if raw:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                return
            if not isinstance(data, dict):
                return
        else:
            data = {}
        namespace = data.setdefault("movenotes", {})
        if not isinstance(namespace, dict):
            return
        sources = namespace.setdefault("image_sources", [])
        if not isinstance(sources, list):
            return
        if source_url in sources:
            return
        sources.append(source_url)
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        self.sqlconn.execute(
            "UPDATE notes SET joplin_user_data = ? WHERE note_id = ?",
            (encoded, row["note_id"]),
        )

    def ensure(
        self,
        content: bytes,
        mime: str,
        extension: str,
        title: str,
        *,
        source_url: str | None = None,
    ) -> str:
        content_digest = hashlib.sha256(content).digest()
        cached_id = self._content_ids.get(content_digest)
        if cached_id is not None:
            if source_url:
                row = self.sqlconn.execute(
                    "SELECT note_id, joplin_user_data FROM notes WHERE joplin_id = ?",
                    (cached_id,),
                ).fetchone()
                if row is not None:
                    self._record_source_url(row, source_url)
            self.reused_ids.add(cached_id)
            return cached_id

        counter = 0
        while True:
            resource_id = self._candidate_id(content, counter)
            row = self.sqlconn.execute(
                "SELECT * FROM notes WHERE joplin_id = ?", (resource_id,)
            ).fetchone()
            files = self._resource_file_candidates(resource_id)
            if row is None:
                if not files or self._existing_content_matches(resource_id, content):
                    # Reuse a content-addressed orphan file by creating its
                    # missing resource row instead of generating another ID.
                    break
                counter += 1
                continue
            if row["joplin_type_"] == int(constants.JoplinType.RESOURCE):
                if self._existing_content_matches(resource_id, content):
                    self._record_source_url(row, source_url)
                    self._content_ids[content_digest] = resource_id
                    self.reused_ids.add(resource_id)
                    return resource_id
                content_hash = hashlib.sha512(content).hexdigest()
                if (
                    not files
                    and row["note_original_format"] == "movenotes-image"
                    and row["note_hash"] == content_hash
                ):
                    # Repair a missing generated resource file in place.
                    target = self.resources_path / f"{resource_id}.{extension}"
                    target.write_bytes(content)
                    self._remember_resource_file(target)
                    self._record_source_url(row, source_url)
                    self._content_ids[content_digest] = resource_id
                    self.reused_ids.add(resource_id)
                    return resource_id
            counter += 1

        filename = f"{resource_id}.{extension}" if extension else resource_id
        target = self.resources_path / filename
        target.write_bytes(content)
        self._remember_resource_file(target)
        timestamp = utc_timestamp()
        user_data = None
        if source_url:
            user_data = json.dumps(
                {"movenotes": {"image_sources": [source_url]}},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        columns = {
            "note_type": "resource",
            "note_uuid": resource_id,
            "note_original_format": "movenotes-image",
            "note_internal_date": datetime.now(timezone.utc),
            "note_hash": hashlib.sha512(content).hexdigest(),
            "note_title": title,
            "note_data": f"{title}\n",
            "note_data_format": "text/markdown",
            "joplin_id": resource_id,
            "joplin_type_": int(constants.JoplinType.RESOURCE),
            "joplin_created_time": timestamp,
            "joplin_updated_time": timestamp,
            "joplin_user_created_time": timestamp,
            "joplin_user_updated_time": timestamp,
            "joplin_mime": mime,
            "joplin_filename": title,
            "joplin_file_extension": extension,
            "joplin_size": len(content),
            "joplin_encryption_applied": 0,
            "joplin_encryption_blob_encrypted": 0,
            "joplin_is_shared": 0,
            "joplin_user_data": user_data,
        }
        notesdb.add_joplin_note(self.sqlconn, columns)
        self._content_ids[content_digest] = resource_id
        self.created_ids.add(resource_id)
        return resource_id


def note_filename(row: sqlite3.Row) -> str:
    source = row["note_source_filename"]
    if source:
        return Path(source).name
    item_id = row["joplin_id"] or row["note_uuid"] or f"row-{row['note_id']}"
    return f"{item_id}.md"


def apply_replacements(text: str, replacements: Iterable[tuple[int, int, str]]) -> str:
    """Apply non-overlapping replacements in one linear pass.

    Repeated string slicing copies the whole note once per image and becomes
    quadratic for notes containing many links. Building a list of unchanged
    spans and replacements copies each character at most once.
    """
    ordered = sorted(replacements, key=lambda item: item[0])
    if not ordered:
        return text

    output: list[str] = []
    cursor = 0
    for start, end, replacement in ordered:
        if start < cursor or end < start or end > len(text):
            raise ValueError("overlapping or invalid replacement range")
        output.append(text[cursor:start])
        output.append(replacement)
        cursor = end
    output.append(text[cursor:])
    return "".join(output)


def update_note_body(sqlconn: sqlite3.Connection, note_id: int, body: str) -> None:
    digest = hashlib.sha512(body.encode("utf-8")).hexdigest()
    sqlconn.execute(
        "UPDATE notes SET note_data = ?, note_hash = ? WHERE note_id = ?",
        (body, digest, note_id),
    )


def _preview(raw: str, limit: int = 180) -> str:
    compact = " ".join(raw.replace("`", "\\`").split())
    if len(compact) > limit:
        compact = compact[: limit - 1] + "…"
    return compact


def assign_issue_occurrences(issues: list[Issue]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for issue in sorted(issues, key=lambda item: (item.note_id, item.line)):
        key = (issue.note_id, issue.fingerprint)
        counts[key] = counts.get(key, 0) + 1
        issue.occurrence = counts[key]


def write_report(
    report_path: Path,
    issues: list[Issue],
    *,
    notes_scanned: int,
    notes_updated: int,
    links_converted: int,
    resources_created: int,
    resources_reused: int,
) -> None:
    assign_issue_occurrences(issues)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    groups = [
        ("could-not-convert", "Could not be converted"),
        ("should-not-convert", "Should not be converted"),
        ("badly-formatted", "Badly formatted embedded images"),
    ]
    lines = [
        "# Image conversion report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- Notes scanned: {notes_scanned}",
        f"- Notes updated: {notes_updated}",
        f"- Image links converted: {links_converted}",
        f"- Resources created: {resources_created}",
        f"- Existing resources reused: {resources_reused}",
        f"- Problems reported: {len(issues)}",
        "",
        "Check an item (`[x]`) and run `quarantinelinks.py` to replace that exact",
        "problematic image occurrence with the configured local “Image removed” resource.",
        "Do not delete the HTML metadata comment below a checked item.",
        "",
    ]
    for category, heading in groups:
        lines.extend([f"## {heading}", ""])
        category_issues = [issue for issue in issues if issue.category == category]
        if not category_issues:
            lines.extend(["_None._", ""])
            continue
        for issue in category_issues:
            description = (
                f"- [ ] **{issue.kind}** — `{issue.note_filename}`; "
                f"note “{issue.note_title}” (`{issue.note_id}`), line {issue.line}: "
                f"`{_preview(issue.raw)}` — {issue.detail}"
            )
            if issue.redirect_from and issue.redirect_to:
                description += f" Redirect: `{issue.redirect_from}` → `{issue.redirect_to}`."
            if issue.original_mime or issue.final_mime:
                description += (
                    f" Types: `{issue.original_mime or '(unknown)'}` → "
                    f"`{issue.final_mime or '(unknown)'}`."
                )
            lines.append(description)
            metadata = json.dumps(issue.metadata(), ensure_ascii=False, separators=(",", ":"))
            lines.append(f"  <!-- {REPORT_METADATA_PREFIX}{metadata} -->")
            lines.append("")
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def parse_checked_report(report_path: Path) -> list[dict]:
    """Return metadata for checked report items."""
    lines = report_path.read_text(encoding="utf-8").splitlines()
    selected: list[dict] = []
    checked = False
    for line in lines:
        checkbox = _CHECKBOX_RE.match(line)
        if checkbox:
            checked = checkbox.group(1).lower() == "x"
            continue
        marker = "<!-- " + REPORT_METADATA_PREFIX
        stripped = line.strip()
        if checked and stripped.startswith(marker) and stripped.endswith(" -->"):
            payload = stripped[len(marker) : -4]
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                checked = False
                continue
            if isinstance(data, dict) and data.get("note_id") and data.get("fingerprint"):
                selected.append(data)
            checked = False
    return selected


def quarantine_candidates(text: str) -> list[ImageLink]:
    valid, malformed = scan_markdown_images(text)
    candidates = [
        link
        for link in valid
        if _DATA_PREFIX_RE.match(link.destination) or _HTTP_PREFIX_RE.match(link.destination)
    ]
    candidates.extend(malformed)
    return sorted(candidates, key=lambda item: item.start)


def built_in_removed_svg() -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">'
        '<rect width="640" height="360" fill="#e5e7eb"/>'
        '<path d="M220 105h200v150H220z" fill="none" stroke="#6b7280" stroke-width="12"/>'
        '<path d="m238 232 55-58 42 42 33-31 34 47" fill="none" stroke="#6b7280" stroke-width="12"/>'
        '<circle cx="365" cy="147" r="18" fill="#6b7280"/>'
        '<path d="m202 87 236 186" stroke="#b91c1c" stroke-width="18"/>'
        '<text x="320" y="320" text-anchor="middle" font-family="sans-serif" font-size="28" fill="#374151">Image removed</text>'
        '</svg>\n'
    ).encode("utf-8")
