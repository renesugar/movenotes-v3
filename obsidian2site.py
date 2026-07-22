#!/usr/bin/env python3
"""Convert an Obsidian vault into a scalable Hugo + Pagefind static site.

The generated Hugo project uses the Relearn documentation theme while replacing
its page-tree sidebar with a fixed Getting Started / Search / Tags navigation.
Markdown notes are hidden from the theme menu and are found through Pagefind or
the disk-backed tag index. The converter is standard-library-only; Hugo,
Relearn, and Pagefind are external build-time tools.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import unicodedata
import urllib.parse
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import common
import obsidian2sql

__program_name__ = "obsidian2site"
__version__ = "3.35"

_IGNORED_DIRECTORY_NAMES = frozenset({
    ".git", ".hg", ".svn", ".obsidian", ".movenotes", ".trash", ".Trash",
    "node_modules",
})
_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
_IMAGE_EXTENSIONS = frozenset({
    ".avif", ".bmp", ".gif", ".heic", ".ico", ".jpeg", ".jpg", ".png",
    ".svg", ".tif", ".tiff", ".webp",
})
_WIKI_LINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
_MARKDOWN_LINK_RE = re.compile(
    r"(!?)\[([^\]]*)\]\(((?:\\.|[^()\\]|\([^()]*\))+)\)"
)
_ANGLE_URL_RE = re.compile(r"<(https?://[^<>\s]*)>", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"(?<![\w@])https?://[^\s<>\"'`]*", re.IGNORECASE)
_X_MENTION_RE = re.compile(
    r"(?<![\w@/])@([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])"
)
_REFERENCE_DEFINITION_RE = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*)(.+)$")
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_URL_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_INLINE_TAG_RE = re.compile(r"(?<![\w/])#([\w][\w/-]*)", re.UNICODE)
_WORD_RE = re.compile(r"[^\W\d_][\w'’\-]*", re.UNICODE)
_FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_LEADING_ATX_H1_RE = re.compile(r"\A(?:[ \t]*\r?\n)*[ \t]*#(?:[ \t]+)(.+?)[ \t]*#*[ \t]*(?:\r?\n|\Z)")
_SETEXT_H1_UNDERLINE_RE = re.compile(r"^[ \t]*=+[ \t]*$")

_TAG_POSTING_BUCKETS = 4096
_DOCUMENT_CHUNK_SIZE = 512

# Common English function words plus web/archive noise. User-supplied stop words
# are merged with this set. Content words are deliberately not stemmed: the
# requirement is to retain each unique non-filler word as a site tag.
_DEFAULT_STOP_WORDS = frozenset("""
a about above after again against all am an and any are aren't as at be because
been before being below between both but by can can't cannot could couldn't did
didn't do does doesn't doing don't down during each few for from further had
hadn't has hasn't have haven't having he he'd he'll he's her here here's hers
herself him himself his how how's i i'd i'll i'm i've if in into is isn't it
it's its itself just me more most mustn't my myself no nor not of off on once
only or other ought our ours ourselves out over own same shan't she she'd she'll
she's should shouldn't so some such than that that's the their theirs them
themselves then there there's these they they'd they'll they're they've this
those through to too under until up very was wasn't we we'd we'll we're we've
were weren't what what's when when's where where's which while who who's whom
why why's with won't would wouldn't you you'd you'll you're you've your yours
yourself yourselves http https www com net org html amp rt via tco x twitter
status tweet tweets post posts image images video videos
""".split())

_RELEARN_HUGO_0158_REPLACEMENTS = (
    (".Language.LanguageDirection", ".Language.Direction"),
    (".Language.LanguageCode", ".Language.Locale"),
    (".Language.LanguageName", ".Language.Label"),
    (".Language.Lang", ".Language.Name"),
    ("$site.Sites", "hugo.Sites"),
    ("site.Sites", "hugo.Sites"),
    (".Site.Sites", "hugo.Sites"),
    (".Page.Sites", "hugo.Sites"),
)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=__program_name__, description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--input", dest="input_path", type=common.existing_dir, required=True,
        help="Path to the input Obsidian vault",
    )
    parser.add_argument(
        "--output", dest="output_path", type=Path, required=True,
        help="Directory for the generated Hugo project (created if needed)",
    )
    parser.add_argument("--title", help="Site title (default: vault directory name)")
    parser.add_argument("--base-url", default="/", help="Hugo baseURL (default: /)")
    parser.add_argument(
        "--locale", "--language-code", dest="locale", default="en-US",
        help="Hugo locale (the --language-code alias is retained for compatibility)",
    )
    parser.add_argument(
        "--workers", type=int, default=max(1, min(32, (os.cpu_count() or 2) + 4)),
        help="Markdown conversion worker count",
    )
    parser.add_argument(
        "--progress-every", type=int, default=1000,
        help="Print progress every N converted notes; 0 disables it",
    )
    parser.add_argument(
        "--tag-batch-size", type=int, default=500,
        help="Notes per temporary tag-count update batch (default: 500)",
    )
    parser.add_argument(
        "--minimum-word-length", type=int, default=3,
        help="Minimum generated word-tag length (default: 3)",
    )
    parser.add_argument(
        "--stop-words", type=Path,
        help="Optional UTF-8 file containing additional filler words",
    )
    parser.add_argument(
        "--include-hidden", action="store_true",
        help="Include dot-prefixed vault directories except .movenotes",
    )
    parser.add_argument(
        "--note-embeds", choices=("link", "transclude"), default="link",
        help="Convert ![[Note]] to a link (scalable default) or transclude its body",
    )
    parser.add_argument(
        "--relearn-theme", type=Path,
        help="Copy an existing hugo-theme-relearn checkout into the generated site",
    )
    parser.add_argument(
        "--build", action="store_true",
        help="Run Hugo and the selected search indexer after generating the project",
    )
    parser.add_argument(
        "--search-backend", choices=("both", "bluge", "pagefind"), default="both",
        help=("Search runtime to generate. 'bluge' emits no Pagefind or Relearn/Lunr "
              "runtime; 'both' keeps Pagefind only as a static-hosting fallback "
              "(default: both)"),
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Replace an existing generated site or a non-empty output directory",
    )
    parser.add_argument("--hugo-bin", default="hugo", help="Hugo executable")
    parser.add_argument("--go-bin", default="go", help="Go executable used to build the Bluge server")
    parser.add_argument(
        "--pagefind-bin",
        help="Pagefind executable; defaults to pagefind, python -m pagefind, or npx",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.workers < 1:
        common.error("--workers must be at least 1")
    if args.progress_every < 0:
        common.error("--progress-every cannot be negative")
    if args.tag_batch_size < 1:
        common.error("--tag-batch-size must be at least 1")
    if args.minimum_word_length < 1:
        common.error("--minimum-word-length must be at least 1")
    if args.relearn_theme is not None and not args.relearn_theme.is_dir():
        common.error(f"Relearn theme directory does not exist: {args.relearn_theme}")


def _is_hidden_part(part: str) -> bool:
    return part.startswith(".") and part not in {".", ".."}


def _scan_vault(root: Path, include_hidden: bool) -> tuple[list[Path], list[Path]]:
    markdown: list[Path] = []
    assets: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        current = Path(directory)
        kept: list[str] = []
        for name in dirnames:
            if name == ".movenotes":
                continue
            if name in _IGNORED_DIRECTORY_NAMES and not (include_hidden and name == ".obsidian"):
                continue
            if not include_hidden and _is_hidden_part(name):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            source = current / name
            relative = source.relative_to(root)
            if any(part == ".movenotes" for part in relative.parts):
                continue
            if not include_hidden and any(_is_hidden_part(part) for part in relative.parts):
                continue
            if source.suffix.casefold() in _MARKDOWN_EXTENSIONS:
                markdown.append(source)
            else:
                assets.append(source)
    markdown.sort(key=lambda path: path.relative_to(root).as_posix().casefold())
    assets.sort(key=lambda path: path.relative_to(root).as_posix().casefold())
    return markdown, assets


def _safe_segment(value: str, *, maximum_bytes: int = 180) -> str:
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"[\x00-\x1f\x7f<>:\"/\\|?*]", "_", value).strip().rstrip(". ")
    if not value or value in {".", ".."}:
        value = "untitled"
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    suffix = "-" + hashlib.sha256(encoded).hexdigest()[:12]
    budget = maximum_bytes - len(suffix.encode("utf-8"))
    shortened = encoded[:budget]
    while shortened:
        try:
            prefix = shortened.decode("utf-8")
            break
        except UnicodeDecodeError:
            shortened = shortened[:-1]
    else:
        prefix = "note"
    return prefix.rstrip(". ") + suffix




def _safe_filename(value: str, *, maximum_bytes: int = 180) -> str:
    path = PurePosixPath(value)
    suffix = path.suffix
    if not suffix:
        return _safe_segment(value, maximum_bytes=maximum_bytes)
    suffix_bytes = len(suffix.encode("utf-8"))
    stem_budget = max(32, maximum_bytes - suffix_bytes)
    return _safe_segment(path.stem, maximum_bytes=stem_budget) + suffix


def _unique_output_path(relative: PurePosixPath, used: set[str]) -> PurePosixPath:
    parts = [
        _safe_filename(part) if index == len(relative.parts) - 1 else _safe_segment(part)
        for index, part in enumerate(relative.parts)
    ]
    candidate = PurePosixPath(*parts)
    key = candidate.as_posix().casefold()
    if key not in used:
        used.add(key)
        return candidate
    digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:12]
    stem = _safe_segment(candidate.stem, maximum_bytes=160)
    suffix = candidate.suffix
    candidate = candidate.with_name(f"{stem}-{digest}{suffix}")
    counter = 2
    while candidate.as_posix().casefold() in used:
        candidate = candidate.with_name(f"{stem}-{digest}-{counter}{suffix}")
        counter += 1
    used.add(candidate.as_posix().casefold())
    return candidate


def _slug_site_segment(value: str, *, maximum_bytes: int = 180) -> str:
    """Create a deterministic URL segment that Hugo will emit verbatim.

    The generated note front matter also contains an explicit ``url`` value, so
    these rules—not Hugo's evolving implicit slugger—are the source of truth.
    """
    normalized = unicodedata.normalize("NFKD", value).casefold()
    pieces: list[str] = []
    pending_separator = False
    for character in normalized:
        if unicodedata.combining(character):
            continue
        if character.isalnum() or character in {"@", "_", "."}:
            if pending_separator and pieces and pieces[-1] != "-":
                pieces.append("-")
            pieces.append(character)
            pending_separator = False
        elif character == "-":
            if pieces and pieces[-1] != "-":
                pieces.append("-")
            pending_separator = False
        else:
            pending_separator = True
    slug = "".join(pieces).strip("-._") or "note"
    return _safe_segment(slug, maximum_bytes=maximum_bytes)


def _build_path_maps(
    root: Path, markdown_paths: list[Path], asset_paths: list[Path]
) -> tuple[dict[str, PurePosixPath], dict[str, PurePosixPath]]:
    note_map: dict[str, PurePosixPath] = {}
    asset_map: dict[str, PurePosixPath] = {}
    used_notes: set[str] = set()
    used_assets: set[str] = set()
    for path in markdown_paths:
        relative = PurePosixPath(path.relative_to(root).as_posix())
        parent_parts = [_slug_site_segment(part) for part in relative.parent.parts if part not in {"", "."}]
        filename = _slug_site_segment(relative.stem) + ".md"
        output = _unique_output_path(
            PurePosixPath("notes", *parent_parts, filename), used_notes
        )
        note_map[relative.as_posix()] = output
    for path in asset_paths:
        relative = PurePosixPath(path.relative_to(root).as_posix())
        output = _unique_output_path(PurePosixPath("vault-assets") / relative, used_assets)
        asset_map[relative.as_posix()] = output
    return note_map, asset_map


def _lookup_indexes(paths: Iterable[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    exact: dict[str, str] = {}
    basenames: dict[str, list[str]] = {}
    for value in paths:
        path = PurePosixPath(value)
        variants = {value.casefold()}
        if path.suffix.casefold() in _MARKDOWN_EXTENSIONS:
            variants.add(path.with_suffix("").as_posix().casefold())
        for variant in variants:
            exact.setdefault(variant, value)
        basenames.setdefault(path.name.casefold(), []).append(value)
        if path.suffix.casefold() in _MARKDOWN_EXTENSIONS:
            basenames.setdefault(path.stem.casefold(), []).append(value)
    return exact, basenames


def _normalise_target(value: str) -> tuple[str, str]:
    value = urllib.parse.unquote(value.strip().strip("<>"))
    fragment = ""
    if "#" in value:
        value, fragment = value.split("#", 1)
    return value.replace("\\", "/"), fragment


def _resolve_target(
    target: str,
    source_relative: PurePosixPath,
    exact: dict[str, str],
    basenames: dict[str, list[str]],
) -> str | None:
    target, _fragment = _normalise_target(target)
    if not target:
        return source_relative.as_posix()
    candidate = PurePosixPath(target)
    if target.startswith("/"):
        candidate = PurePosixPath(target.lstrip("/"))
    elif target.startswith("./") or target.startswith("../") or "/" in target:
        candidate = source_relative.parent / candidate
    normalized_parts: list[str] = []
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if normalized_parts:
                normalized_parts.pop()
            continue
        normalized_parts.append(part)
    normalized = PurePosixPath(*normalized_parts).as_posix()
    variants = [normalized.casefold()]
    if not PurePosixPath(normalized).suffix:
        variants.extend((f"{normalized}.md".casefold(), f"{normalized}.markdown".casefold()))
    for variant in variants:
        if variant in exact:
            return exact[variant]
    name = PurePosixPath(normalized).name.casefold()
    matches = basenames.get(name, [])
    if len(matches) == 1:
        return matches[0]
    if not PurePosixPath(name).suffix:
        matches = basenames.get(f"{name}.md", []) + basenames.get(f"{name}.markdown", [])
        unique = list(dict.fromkeys(matches))
        if len(unique) == 1:
            return unique[0]
    return None


def _hugo_heading_fragment(fragment: str) -> str:
    fragment = fragment.removeprefix("^")
    value = unicodedata.normalize("NFKC", fragment).casefold().strip()
    value = re.sub(r"[^\w\- ]+", "", value, flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", value).strip("-")


def _url_quote_path(value: str) -> str:
    return "/".join(urllib.parse.quote(part) for part in value.split("/"))


def _relative_link(current_output: PurePosixPath, target_output: PurePosixPath) -> str:
    current_html = current_output.with_suffix(".html")
    target_html = target_output.with_suffix(".html")
    relative = os.path.relpath(target_html.as_posix(), current_html.parent.as_posix())
    return _url_quote_path(relative.replace(os.sep, "/"))


def _note_hugo_url(output_relative: PurePosixPath) -> str:
    return "/" + output_relative.with_suffix(".html").as_posix()


def _note_site_url(output_relative: PurePosixPath) -> str:
    # Keep search/tag metadata byte-for-byte aligned with Hugo's explicit URL.
    # Browsers percent-encode Unicode when needed, while RFC path characters such
    # as ``@`` remain readable and match the generated filename.
    return _note_hugo_url(output_relative)


def _asset_link(current_output: PurePosixPath, target_static: PurePosixPath) -> str:
    current_html = current_output.with_suffix(".html")
    target = PurePosixPath("static-root") / target_static
    current = PurePosixPath("static-root") / current_html
    relative = os.path.relpath(target.as_posix(), current.parent.as_posix())
    return _url_quote_path(relative.replace(os.sep, "/"))


def _strip_frontmatter(text: str) -> tuple[dict[str, object], str]:
    frontmatter, body = obsidian2sql.split_frontmatter(text)
    return obsidian2sql.parse_frontmatter(frontmatter), body


def _title_from_note(path: Path, metadata: dict[str, object], body: str) -> str:
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    heading = _HEADING_RE.search(body)
    if heading:
        return re.sub(r"\s+#+\s*$", "", heading.group(1)).strip()
    return path.stem or "Untitled"


def _normalise_heading_text(value: str) -> str:
    value = re.sub(r"\s+#+\s*$", "", value).strip()
    value = re.sub(r"[*_~`]", "", value)
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _remove_redundant_leading_heading(body: str, title: str) -> str:
    """Remove an initial H1 that merely repeats Relearn's generated page title."""
    expected = _normalise_heading_text(title)
    if not expected:
        return body

    match = _LEADING_ATX_H1_RE.match(body)
    if match and _normalise_heading_text(match.group(1)) == expected:
        remainder = body[match.end():]
        return remainder.lstrip("\r\n")

    lines = body.splitlines(keepends=True)
    first_content = 0
    while first_content < len(lines) and not lines[first_content].strip():
        first_content += 1
    if first_content + 1 < len(lines):
        first = lines[first_content].rstrip("\r\n")
        underline = lines[first_content + 1].rstrip("\r\n")
        if (
            _SETEXT_H1_UNDERLINE_RE.match(underline)
            and _normalise_heading_text(first) == expected
        ):
            remainder = "".join(lines[first_content + 2:])
            return remainder.lstrip("\r\n")
    return body


def _normalise_datetime(value: object, fallback_path: Path) -> str:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, timezone.utc).isoformat().replace("+00:00", "Z")
        except (OSError, OverflowError, ValueError):
            pass
    if isinstance(value, str) and value.strip():
        raw = value.strip().strip("'\"")
        try:
            parsed = common.parse_isoformat_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except (ValueError, TypeError):
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                    return parsed.isoformat().replace("+00:00", "Z")
                except ValueError:
                    continue
    return datetime.fromtimestamp(fallback_path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")


def _metadata_datetime(metadata: dict[str, object], names: tuple[str, ...], path: Path) -> str:
    for name in names:
        if name in metadata and metadata[name] not in {None, ""}:
            return _normalise_datetime(metadata[name], path)
    return _normalise_datetime(None, path)


def _tags_from_frontmatter(value: object) -> set[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return {str(item).strip().lstrip("#").casefold() for item in parsed if str(item).strip()}
            except (ValueError, json.JSONDecodeError):
                pass
        return {part.strip().lstrip("#").casefold() for part in re.split(r"[,\s]+", stripped) if part.strip()}
    if isinstance(value, list):
        return {str(item).strip().lstrip("#").casefold() for item in value if str(item).strip()}
    return set()


def _searchable_text(body: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        match = _FENCE_RE.match(line)
        if match:
            marker = match.group(1)[0]
            fence = None if fence == marker else marker
            continue
        if fence is None:
            lines.append(_INLINE_CODE_RE.sub(" ", line))
    text = "\n".join(lines)
    text = _WIKI_LINK_RE.sub(
        lambda match: (
            match.group(2).partition("|")[2]
            or PurePosixPath(match.group(2).partition("|")[0].split("#", 1)[0]).stem
        ),
        text,
    )
    # Preserve Markdown link labels before removing their external destinations.
    # Removing bare URLs first leaves fragments such as ``[label](`` in Bluge
    # summaries and search text.
    text = _MARKDOWN_LINK_RE.sub(lambda match: match.group(2), text)
    text = re.sub(r"<https?://[^>]+>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def _extract_tags(
    metadata: dict[str, object], body: str, stop_words: frozenset[str], minimum_length: int
) -> tuple[list[str], list[str]]:
    searchable = _searchable_text(body)
    explicit = set()
    for key in ("tags", "tag"):
        explicit.update(_tags_from_frontmatter(metadata.get(key)))
    explicit.update(match.group(1).strip("/-").casefold() for match in _INLINE_TAG_RE.finditer(searchable))
    explicit.discard("")
    generated: set[str] = set()
    for match in _WORD_RE.finditer(searchable):
        word = match.group(0).strip("-'’").casefold()
        if len(word) < minimum_length or word in stop_words:
            continue
        if not any(character.isalpha() for character in word):
            continue
        generated.add(word)
    all_tags = sorted(explicit | generated)
    return all_tags, sorted(explicit)


def _split_wiki_target(raw: str) -> tuple[str, str, str]:
    target_and_fragment, separator, label = raw.partition("|")
    target, fragment = _normalise_target(target_and_fragment)
    return target, fragment, label.strip() if separator else ""




def _transform_inline_code(line: str, transform) -> str:
    """Apply *transform* outside Markdown inline-code spans on one line."""
    output: list[str] = []
    position = 0
    while position < len(line):
        start = line.find("`", position)
        if start < 0:
            output.append(transform(line[position:]))
            break
        run_end = start
        while run_end < len(line) and line[run_end] == "`":
            run_end += 1
        marker = line[start:run_end]
        close = line.find(marker, run_end)
        if close < 0:
            output.append(transform(line[position:]))
            break
        output.append(transform(line[position:start]))
        output.append(line[start : close + len(marker)])
        position = close + len(marker)
    if position == len(line):
        return "".join(output)
    return "".join(output)


def _transform_outside_code(text: str, transform) -> str:
    """Apply *transform* outside fenced and inline Markdown code."""
    output: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    opener_re = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
    for physical_line in text.splitlines(keepends=True):
        line = physical_line.rstrip("\r\n")
        ending = physical_line[len(line):]
        if fence_character is not None:
            output.append(physical_line)
            closing = re.match(
                rf"^\s{{0,3}}{re.escape(fence_character)}{{{fence_length},}}\s*$",
                line,
            )
            if closing:
                fence_character = None
                fence_length = 0
            continue
        opener = opener_re.match(line)
        if opener:
            marker = opener.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            output.append(physical_line)
            continue
        output.append(_transform_inline_code(line, transform) + ending)
    # splitlines(keepends=True) returns no rows for an empty string.
    return "".join(output) if output else text


def _escape_hugo_shortcodes(text: str) -> str:
    """Render literal Hugo shortcode openers instead of executing them."""
    return text.replace("{{<", "&#123;&#123;&lt;").replace("{{%", "&#123;&#123;%")


def _split_url_suffix(value: str) -> tuple[str, str]:
    """Separate punctuation that is likely prose rather than part of a URL."""
    suffix = ""
    while value and value[-1] in ".,;:!?…":
        suffix = value[-1] + suffix
        value = value[:-1]
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while value.endswith(closing) and value.count(closing) > value.count(opening):
            suffix = closing + suffix
            value = value[:-1]
    return value, suffix


def _repair_http_url(value: str) -> str | None:
    """Return a Go/Hugo-parseable HTTP(S) URL while retaining its information.

    Incomplete percent escapes are encoded as a literal percent sign. Unicode
    host names are converted to IDNA, and non-URL-safe component characters are
    percent-encoded. A missing or structurally invalid host cannot be repaired.
    """
    candidate = value.strip().strip("<>")
    if not candidate:
        return None
    candidate = _URL_CONTROL_RE.sub(
        lambda match: urllib.parse.quote(match.group(0), safe=""), candidate
    )
    candidate = _INVALID_PERCENT_ESCAPE_RE.sub("%25", candidate)
    try:
        parsed = urllib.parse.urlsplit(candidate)
        scheme = parsed.scheme.casefold()
        if scheme not in {"http", "https"} or not parsed.netloc:
            return None
        hostname = parsed.hostname
        if not hostname:
            return None
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return None
        host = f"[{ascii_hostname}]" if ":" in ascii_hostname else ascii_hostname
        try:
            port = parsed.port
        except ValueError:
            return None
        if port is not None:
            host += f":{port}"
        userinfo = ""
        if parsed.username is not None:
            userinfo = urllib.parse.quote(parsed.username, safe="!$&'()*+,;=:-._~")
            if parsed.password is not None:
                userinfo += ":" + urllib.parse.quote(
                    parsed.password, safe="!$&'()*+,;=:-._~"
                )
            userinfo += "@"
        netloc = userinfo + host
        path = urllib.parse.quote(
            parsed.path, safe="/%:@-._~!$&'()*+,;=%"
        )
        query = urllib.parse.quote(
            parsed.query, safe="/?@-._~!$&'()*+,;=:%[]"
        )
        fragment = urllib.parse.quote(
            parsed.fragment, safe="/?@-._~!$&'()*+,;=:%[]"
        )
        repaired = urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))
    except (UnicodeError, ValueError):
        return None
    if _INVALID_PERCENT_ESCAPE_RE.search(repaired) or _URL_CONTROL_RE.search(repaired):
        return None
    return repaired


def _invalid_url_html(value: str, label: str | None = None) -> str:
    """Preserve an unusable URL as visible text without triggering autolinking."""
    visible = label.strip() if label and label.strip() else value
    if visible == value:
        content = html.escape(value)
    else:
        content = f"{html.escape(visible)} — <code>{html.escape(value)}</code>"
    return (
        '<span class="movenotes-invalid-url" '
        'title="Invalid URL preserved as text">'
        f"{content}</span>"
    )


def _markdown_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _split_markdown_destination(value: str) -> tuple[str, str]:
    """Split a Markdown link destination from an optional title suffix."""
    stripped = value.strip()
    if stripped.startswith("<"):
        end = stripped.find(">", 1)
        if end != -1:
            return stripped[1:end], stripped[end + 1 :]
    match = re.match(r"(\S+)(.*)", stripped, flags=re.DOTALL)
    if not match:
        return stripped, ""
    return match.group(1), match.group(2)


def _sanitize_bare_urls(text: str) -> tuple[str, int, int]:
    repaired_count = 0
    preserved_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal repaired_count, preserved_count
        raw, suffix = _split_url_suffix(match.group(0))
        repaired = _repair_http_url(raw)
        if repaired is None:
            preserved_count += 1
            return _invalid_url_html(raw) + suffix
        if repaired != raw:
            repaired_count += 1
            return f"[{_markdown_label(raw)}]({repaired}){suffix}"
        return raw + suffix

    return _BARE_URL_RE.sub(replace, text), repaired_count, preserved_count


def _link_x_mentions(text: str) -> str:
    """Link plain-text X handles without touching emails, URLs, or link markup."""
    return _X_MENTION_RE.sub(
        lambda match: (
            f"[@{match.group(1)}](https://x.com/{match.group(1)})"
        ),
        text,
    )


def _convert_body(
    *,
    body: str,
    source_relative: PurePosixPath,
    output_relative: PurePosixPath,
    note_map: dict[str, PurePosixPath],
    asset_map: dict[str, PurePosixPath],
    note_exact: dict[str, str],
    note_basenames: dict[str, list[str]],
    asset_exact: dict[str, str],
    asset_basenames: dict[str, list[str]],
    note_embeds: str,
    source_root: Path,
    embed_stack: tuple[str, ...] = (),
    url_stats: list[int] | None = None,
) -> str:
    if url_stats is None:
        url_stats = [0, 0]

    def wiki_replace(match: re.Match[str]) -> str:
        embedded = bool(match.group(1))
        raw = match.group(2)
        target, fragment, label = _split_wiki_target(raw)
        resolved_note = _resolve_target(target, source_relative, note_exact, note_basenames)
        if resolved_note is not None and resolved_note in note_map:
            display = label or PurePosixPath(resolved_note).stem
            link = _relative_link(output_relative, note_map[resolved_note])
            if fragment:
                anchor = _hugo_heading_fragment(fragment)
                if anchor:
                    link += "#" + urllib.parse.quote(anchor)
            if embedded and note_embeds == "transclude" and resolved_note not in embed_stack and len(embed_stack) < 8:
                try:
                    raw_text = (source_root / resolved_note).read_text(encoding="utf-8-sig")
                    _meta, included_body = _strip_frontmatter(raw_text)
                    included = _convert_body(
                        body=included_body,
                        source_relative=PurePosixPath(resolved_note),
                        output_relative=output_relative,
                        note_map=note_map,
                        asset_map=asset_map,
                        note_exact=note_exact,
                        note_basenames=note_basenames,
                        asset_exact=asset_exact,
                        asset_basenames=asset_basenames,
                        note_embeds=note_embeds,
                        source_root=source_root,
                        embed_stack=embed_stack + (resolved_note,),
                        url_stats=url_stats,
                    )
                    return f"\n\n> **Embedded from [{display}]({link})**\n\n{included}\n\n"
                except (OSError, UnicodeDecodeError):
                    pass
            return f"[{display}]({link})"
        resolved_asset = _resolve_target(target, source_relative, asset_exact, asset_basenames)
        if resolved_asset is not None and resolved_asset in asset_map:
            display = label or PurePosixPath(resolved_asset).name
            link = _asset_link(output_relative, asset_map[resolved_asset])
            if embedded and PurePosixPath(resolved_asset).suffix.casefold() in _IMAGE_EXTENSIONS:
                return f"![{display}]({link})"
            return f"[{display}]({link})"
        return match.group(0)

    def markdown_replace(match: re.Match[str]) -> str:
        prefix, label, raw_target = match.groups()
        target_value, title_suffix = _split_markdown_destination(raw_target)
        if target_value.casefold().startswith(("http://", "https://")):
            repaired = _repair_http_url(target_value)
            if repaired is None:
                url_stats[1] += 1
                return _invalid_url_html(target_value, label)
            if repaired != target_value:
                url_stats[0] += 1
            return f"{prefix}[{label}]({repaired}{title_suffix})"
        if target_value.startswith(("mailto:", "data:", "#")):
            return match.group(0)
        target, fragment = _normalise_target(target_value)
        resolved_note = _resolve_target(target, source_relative, note_exact, note_basenames)
        if resolved_note is not None and resolved_note in note_map:
            link = _relative_link(output_relative, note_map[resolved_note])
            if fragment:
                anchor = _hugo_heading_fragment(fragment)
                if anchor:
                    link += "#" + urllib.parse.quote(anchor)
            return f"{prefix}[{label}]({link})"
        resolved_asset = _resolve_target(target, source_relative, asset_exact, asset_basenames)
        if resolved_asset is not None and resolved_asset in asset_map:
            link = _asset_link(output_relative, asset_map[resolved_asset])
            return f"{prefix}[{label}]({link})"
        return match.group(0)

    def transform_segment(segment: str) -> str:
        converted = _WIKI_LINK_RE.sub(wiki_replace, segment)
        protected: list[str] = []

        def protect(value: str) -> str:
            token = f"@@MOVENOTES-PROTECTED-LINK-{len(protected)}@@"
            protected.append(value)
            return token

        reference = _REFERENCE_DEFINITION_RE.match(converted)
        if reference:
            prefix, raw_destination = reference.groups()
            target_value, title_suffix = _split_markdown_destination(raw_destination)
            if target_value.casefold().startswith(("http://", "https://")):
                repaired = _repair_http_url(target_value)
                if repaired is None:
                    url_stats[1] += 1
                    converted = protect(_invalid_url_html(target_value, prefix.rstrip()))
                else:
                    if repaired != target_value:
                        url_stats[0] += 1
                    converted = f"{prefix}{repaired}{title_suffix}"

        converted = _MARKDOWN_LINK_RE.sub(
            lambda match: protect(markdown_replace(match)), converted
        )

        def angle_replace(match: re.Match[str]) -> str:
            raw = match.group(1)
            repaired = _repair_http_url(raw)
            if repaired is None:
                url_stats[1] += 1
                return protect(_invalid_url_html(raw))
            if repaired != raw:
                url_stats[0] += 1
            return protect(f"[{_markdown_label(raw)}]({repaired})")

        converted = _ANGLE_URL_RE.sub(angle_replace, converted)
        html_parts = re.split(r"(<[A-Za-z!/][^>\n]*>)", converted)
        for index in range(0, len(html_parts), 2):
            html_parts[index], repaired, preserved = _sanitize_bare_urls(html_parts[index])
            url_stats[0] += repaired
            url_stats[1] += preserved
            html_parts[index] = _link_x_mentions(html_parts[index])
        converted = "".join(html_parts)
        for index, value in enumerate(protected):
            converted = converted.replace(f"@@MOVENOTES-PROTECTED-LINK-{index}@@", value)
        return converted

    return _escape_hugo_shortcodes(_transform_outside_code(body, transform_segment))


def _is_twitter_note(metadata: dict[str, object]) -> bool:
    """Recognize notes produced by twitterx2sql without relying on folder names."""
    original = metadata.get("movenotes-original-format")
    if isinstance(original, str) and original.casefold() == "twitter":
        return True
    source = metadata.get("joplin-source")
    if isinstance(source, str) and source.casefold() == "twitterx2sql":
        return True
    structured = metadata.get("joplin")
    if isinstance(structured, dict):
        value = structured.get("source")
        if isinstance(value, str) and value.casefold() == "twitterx2sql":
            return True
    return False


def _frontmatter_json(
    *, title: str, date: str, lastmod: str, source_path: str,
    explicit_tags: list[str], site_url: str, aliases: list[str] | None = None,
    hide_heading: bool = False, hide_author_date: bool = False,
) -> str:
    data: dict[str, object] = {
        "title": title,
        "date": date,
        "lastmod": lastmod,
        "hidden": True,
        "disableBreadcrumb": True,
        "disableToc": True,
        "url": site_url,
        "movenotes_source_path": source_path,
        "movenotes_explicit_tags": explicit_tags,
        "movenotes_hide_heading": hide_heading,
        "hideAuthorDate": hide_author_date,
    }
    if aliases:
        data["aliases"] = aliases
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _process_note(
    source_path: Path,
    *,
    input_root: Path,
    content_root: Path,
    note_map: dict[str, PurePosixPath],
    asset_map: dict[str, PurePosixPath],
    note_exact: dict[str, str],
    note_basenames: dict[str, list[str]],
    asset_exact: dict[str, str],
    asset_basenames: dict[str, list[str]],
    stop_words: frozenset[str],
    minimum_word_length: int,
    note_embeds: str,
) -> tuple[list[str], str, str, str, str, str, int, int]:
    source_relative = PurePosixPath(source_path.relative_to(input_root).as_posix())
    output_relative = note_map[source_relative.as_posix()]
    raw = source_path.read_text(encoding="utf-8-sig")
    metadata, body = _strip_frontmatter(raw)
    title = common.remove_line_breakers(_title_from_note(source_path, metadata, body)).strip() or "Untitled"
    twitter_note = _is_twitter_note(metadata)
    body = _remove_redundant_leading_heading(body, title)
    tags, explicit_tags = _extract_tags(
        metadata, f"{title}\n{body}", stop_words, minimum_word_length
    )
    date = _metadata_datetime(
        metadata,
        ("date", "created", "created_time", "user_created_time", "created_at"),
        source_path,
    )
    lastmod = _metadata_datetime(
        metadata,
        ("lastmod", "updated", "modified", "updated_time", "user_updated_time", "updated_at"),
        source_path,
    )
    url_stats = [0, 0]
    converted = _convert_body(
        body=body,
        source_relative=source_relative,
        output_relative=output_relative,
        note_map=note_map,
        asset_map=asset_map,
        note_exact=note_exact,
        note_basenames=note_basenames,
        asset_exact=asset_exact,
        asset_basenames=asset_basenames,
        note_embeds=note_embeds,
        source_root=input_root,
        embed_stack=(source_relative.as_posix(),),
        url_stats=url_stats,
    )
    destination = content_root / Path(output_relative.as_posix())
    destination.parent.mkdir(parents=True, exist_ok=True)
    hugo_url = _note_hugo_url(output_relative)
    site_url = _note_site_url(output_relative)
    content = _frontmatter_json(
        title=title, date=date, lastmod=lastmod,
        source_path=source_relative.as_posix(), explicit_tags=explicit_tags,
        site_url=hugo_url, hide_heading=twitter_note,
        hide_author_date=twitter_note,
    ) + "\n" + converted
    destination.write_text(content, encoding="utf-8", newline="\n")
    search_text = re.sub(r"\s+", " ", _searchable_text(f"{title}\n{converted}")).strip()
    summary = search_text[:700]
    return (
        tags,
        source_relative.as_posix(),
        site_url,
        title,
        date,
        search_text,
        url_stats[0],
        url_stats[1],
    )


def _load_stop_words(path: Path | None) -> frozenset[str]:
    words = set(_DEFAULT_STOP_WORDS)
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            common.error(f"cannot read stop-word file '{path}': {exc}")
        for token in re.split(r"[\s,]+", text):
            token = token.strip().casefold()
            if token and not token.startswith("#"):
                words.add(token)
    return frozenset(words)


def _open_tag_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute(
        "CREATE TABLE tags (tag TEXT PRIMARY KEY, bucket TEXT NOT NULL, count INTEGER NOT NULL)"
    )
    connection.execute("CREATE INDEX tags_bucket_idx ON tags(bucket, tag)")
    connection.execute(
        "CREATE TABLE documents ("
        "note_id INTEGER PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE tag_documents ("
        "posting_bucket INTEGER NOT NULL, tag TEXT NOT NULL, note_id INTEGER NOT NULL, "
        "PRIMARY KEY(posting_bucket, tag, note_id)) WITHOUT ROWID"
    )
    return connection


def _update_tag_counts(
    connection: sqlite3.Connection, counts: Mapping[str, int]
) -> None:
    connection.executemany(
        "INSERT INTO tags(tag, bucket, count) VALUES (?, ?, ?) "
        "ON CONFLICT(tag) DO UPDATE SET count = count + excluded.count",
        ((tag, _tag_bucket(tag), count) for tag, count in counts.items()),
    )


def _tag_posting_bucket(tag: str) -> int:
    """Return the same compact FNV-1a bucket used by the browser."""
    value = 2166136261
    for byte in tag.encode("utf-8"):
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return value & (_TAG_POSTING_BUCKETS - 1)


def _update_tag_documents(
    connection: sqlite3.Connection,
    documents: Iterable[tuple[int, str, str]],
    associations: Iterable[tuple[int, str, int]],
) -> None:
    connection.executemany(
        "INSERT INTO documents(note_id, url, title) VALUES (?, ?, ?)",
        sorted(documents, key=lambda row: row[0]),
    )
    connection.executemany(
        "INSERT INTO tag_documents(posting_bucket, tag, note_id) VALUES (?, ?, ?)",
        sorted(associations),
    )


def _tag_bucket(tag: str) -> str:
    normalized = unicodedata.normalize("NFKD", tag.casefold())
    alphanumeric = [character for character in normalized if character.isalnum()]
    if not alphanumeric:
        return "__"
    if alphanumeric[0].isascii():
        ascii_value = "".join(
            character for character in alphanumeric if character.isascii()
        )
        return (ascii_value + "_")[:2]
    return f"u{ord(alphanumeric[0]):x}"


def _write_json_array(path: Path, rows: Iterable[tuple[str, int]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("[")
        first = True
        for tag, occurrences in rows:
            if not first:
                handle.write(",")
            first = False
            json.dump([tag, occurrences], handle, ensure_ascii=False, separators=(",", ":"))
            count += 1
        handle.write("]\n")
    return count


def _write_tag_postings(
    connection: sqlite3.Connection, target: Path
) -> dict[str, int]:
    target.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, int] = {}
    for (bucket_value,) in connection.execute(
        "SELECT DISTINCT posting_bucket FROM tag_documents ORDER BY posting_bucket"
    ):
        bucket = int(bucket_value)
        filename = f"{bucket:03x}.json"
        tag_count = 0
        with (target / filename).open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("{")
            current_tag: str | None = None
            first_tag = True
            first_note = True
            for tag, note_id in connection.execute(
                "SELECT tag, note_id FROM tag_documents "
                "WHERE posting_bucket = ? ORDER BY tag, note_id",
                (bucket,),
            ):
                tag = str(tag)
                if tag != current_tag:
                    if current_tag is not None:
                        handle.write("]")
                    if not first_tag:
                        handle.write(",")
                    first_tag = False
                    json.dump(tag, handle, ensure_ascii=False)
                    handle.write(":[")
                    current_tag = tag
                    first_note = True
                    tag_count += 1
                if not first_note:
                    handle.write(",")
                first_note = False
                handle.write(str(int(note_id)))
            if current_tag is not None:
                handle.write("]")
            handle.write("}\n")
        manifest[f"{bucket:03x}"] = tag_count
    return manifest


def _write_document_chunks(
    connection: sqlite3.Connection, target: Path
) -> dict[str, int]:
    target.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, int] = {}
    current_chunk: int | None = None
    handle = None
    first = True
    row_count = 0
    try:
        for note_id, url, title in connection.execute(
            "SELECT note_id, url, title FROM documents ORDER BY note_id"
        ):
            note_id = int(note_id)
            chunk = note_id // _DOCUMENT_CHUNK_SIZE
            if chunk != current_chunk:
                if handle is not None:
                    handle.write("}\n")
                    handle.close()
                    manifest[f"{current_chunk:06x}"] = row_count
                current_chunk = chunk
                handle = (target / f"{chunk:06x}.json").open(
                    "w", encoding="utf-8", newline="\n"
                )
                handle.write("{")
                first = True
                row_count = 0
            if not first:
                handle.write(",")
            first = False
            json.dump(str(note_id), handle)
            handle.write(":")
            json.dump([str(url), str(title)], handle, ensure_ascii=False, separators=(",", ":"))
            row_count += 1
    finally:
        if handle is not None:
            handle.write("}\n")
            handle.close()
            assert current_chunk is not None
            manifest[f"{current_chunk:06x}"] = row_count
    return manifest


def _write_tag_index(connection: sqlite3.Connection, static_root: Path) -> int:
    target = static_root / "movenotes" / "tags"
    target.mkdir(parents=True, exist_ok=True)
    _write_json_array(
        target / "top.json",
        connection.execute("SELECT tag, count FROM tags ORDER BY count DESC, tag LIMIT 500"),
    )
    total = int(connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0])
    manifest: dict[str, int] = {}
    for (bucket,) in connection.execute("SELECT DISTINCT bucket FROM tags ORDER BY bucket"):
        manifest[str(bucket)] = _write_json_array(
            target / f"{bucket}.json",
            connection.execute(
                "SELECT tag, count FROM tags WHERE bucket = ? ORDER BY tag", (bucket,)
            ),
        )
    posting_manifest = _write_tag_postings(
        connection, static_root / "movenotes" / "tag-postings"
    )
    document_manifest = _write_document_chunks(
        connection, static_root / "movenotes" / "documents"
    )
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "total": total,
                "buckets": manifest,
                "posting_buckets": posting_manifest,
                "document_chunks": document_manifest,
                "document_chunk_size": _DOCUMENT_CHUNK_SIZE,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
    )
    return total


def _copy_assets(input_root: Path, static_root: Path, asset_map: dict[str, PurePosixPath]) -> int:
    copied = 0
    for source_relative, destination_relative in asset_map.items():
        source = input_root / source_relative
        destination = static_root / Path(destination_relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied


def _modernize_copied_relearn_theme(theme_root: Path) -> int:
    """Update a copied Relearn checkout for Hugo's v0.158+ template APIs."""
    changed_files = 0
    layouts = theme_root / "layouts"
    if not layouts.is_dir():
        return 0
    for path in layouts.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {
            ".html", ".gotmpl", ".xml", ".json", ".txt",
        }:
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        updated = original
        for old, new in _RELEARN_HUGO_0158_REPLACEMENTS:
            updated = updated.replace(old, new)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed_files += 1
    return changed_files


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_hugo_project(
    output: Path, *, title: str, base_url: str, locale: str,
    copied_theme: bool, search_backend: str,
) -> None:
    generated_at = (
        datetime.now(timezone.utc).replace(microsecond=0)
        .isoformat().replace("+00:00", "Z")
    )
    build_id = hashlib.sha256(generated_at.encode("ascii")).hexdigest()[:16]
    content = output / "content"
    layouts = output / "layouts"
    static = output / "static"
    assets = output / "assets"
    for path in (
        content / "notes", layouts / "partials", layouts / "shortcodes",
        layouts / "partials" / "sidebar" / "element",
        layouts / "partials" / "dependencies",
        static / "css", static / "js", assets,
    ):
        path.mkdir(parents=True, exist_ok=True)

    module = "" if copied_theme else """
[module]
  [[module.imports]]
    path = 'github.com/McShelby/hugo-theme-relearn'
"""
    theme_line = "theme = 'hugo-theme-relearn'\n" if copied_theme else ""
    hugo_toml = f"""baseURL = {_toml_string(base_url)}
locale = {_toml_string(locale)}
title = {_toml_string(title)}
uglyURLs = true
enableRobotsTXT = true
buildFuture = true
buildExpired = true
buildDrafts = true
disableKinds = ['taxonomy', 'term', 'RSS']
{theme_line}
[params]
  movenotesBuildId = {_toml_string(build_id)}
  disableLandingPageButton = true
  disableBreadcrumb = true
  disableNextPrev = true
  disableToc = true
  disableAnchorCopy = true
  disableInlineCopyToClipBoard = true
  showVisitedLinks = false
  hideAuthorName = true
  hideAuthorEmail = true
  themeVariant = ['relearn-light', 'relearn-dark']
  search = false
  movenotesSearchBackend = {_toml_string(search_backend)}

  [[params.sidebarheadermenus]]
    type = 'custom'
    identifier = 'movenotes-search'
    main = true

    [[params.sidebarheadermenus.elements]]
      type = 'movenotes-search'

  [[params.sidebarheadermenus]]
    type = 'divider'
    identifier = 'movenotes-search-divider'

  [[params.sidebarmenus]]
    type = 'menu'
    identifier = 'movenotes'
    main = true
    disableTitle = true

  [[params.sidebarfootermenus]]
    type = 'divider'
    identifier = 'movenotes-footer-divider'

  [[params.sidebarfootermenus]]
    type = 'custom'
    identifier = 'movenotes-theme-switcher'

    [[params.sidebarfootermenus.elements]]
      type = 'variantswitcher'

[menus]
  [[menus.movenotes]]
    identifier = 'getting-started'
    name = 'Getting Started'
    pageRef = '/'
    weight = 10
    pre = '<i class="fa-fw fas fa-compass"></i> '

  [[menus.movenotes]]
    identifier = 'search'
    name = 'Search'
    pageRef = '/search'
    weight = 20
    pre = '<i class="fa-fw fas fa-magnifying-glass"></i> '

  [[menus.movenotes]]
    identifier = 'browse-tags'
    name = 'Browse Tags'
    pageRef = '/tags'
    weight = 30
    pre = '<i class="fa-fw fas fa-tags"></i> '

[markup]
  [markup.goldmark]
    [markup.goldmark.renderer]
      unsafe = true

[outputs]
  home = ['HTML']
{module}"""
    (output / "hugo.toml").write_text(hugo_toml, encoding="utf-8")
    if not copied_theme:
        (output / "go.mod").write_text(
            "module movenotes/generated-site\n\ngo 1.20\n", encoding="utf-8"
        )

    home = {
        "title": "Getting Started",
        "date": generated_at,
        "lastmod": generated_at,
        "disableBreadcrumb": True,
        "disableToc": True,
        "hideAuthorDate": False,
    }
    if search_backend in {"both", "pagefind"}:
        home["pagefind_ignore"] = True
    getting_started = (
        json.dumps(home, ensure_ascii=False, separators=(",", ":"))
        + "\n{{< movenotes-start >}}\n"
    )
    (content / "_index.md").write_text(getting_started, encoding="utf-8")
    search_meta = {
        "title": "Search",
        "hidden": True,
        "hideAuthorDate": True,
    }
    if search_backend in {"both", "pagefind"}:
        search_meta["pagefind_ignore"] = True
    (content / "search.md").write_text(
        json.dumps(search_meta, separators=(",", ":"))
        + "\n{{< movenotes-search >}}\n",
        encoding="utf-8",
    )
    tags_meta = {
        "title": "Browse Tags",
        "hidden": True,
        "hideAuthorDate": True,
    }
    if search_backend in {"both", "pagefind"}:
        tags_meta["pagefind_ignore"] = True
    (content / "tags.md").write_text(
        json.dumps(tags_meta, separators=(",", ":"))
        + "\n{{< movenotes-tags >}}\n",
        encoding="utf-8",
    )
    notes_meta = {
        "title": "Notes",
        "hidden": True,
        "hideAuthorDate": True,
    }
    if search_backend in {"both", "pagefind"}:
        notes_meta["pagefind_ignore"] = True
    (content / "notes" / "_index.md").write_text(
        json.dumps(notes_meta, separators=(",", ":"))
        + "\nNotes are available through search and tags.\n",
        encoding="utf-8",
    )

    (layouts / "partials" / "content.html").write_text(
        _content_partial(search_backend), encoding="utf-8"
    )
    (layouts / "partials" / "custom-header.html").write_text(
        _CUSTOM_HEADER_PARTIAL, encoding="utf-8"
    )
    # Authoritative cross-version kill switch for Relearn's built-in search.
    # It prevents both the legacy/current Lunr runtime and the native search box.
    disabled_theme_search = (
        "{{- /* movenotes supplies its own search UI and backend. */ -}}\n"
    )
    (layouts / "partials" / "dependencies" / "search.html").write_text(
        disabled_theme_search, encoding="utf-8"
    )
    # Some older Relearn releases call the adapter partial more directly.
    (layouts / "partials" / "dependencies" / "search-lunr.html").write_text(
        disabled_theme_search, encoding="utf-8"
    )
    (layouts / "partials" / "heading.html").write_text(
        _HEADING_PARTIAL, encoding="utf-8"
    )
    (
        layouts / "partials" / "sidebar" / "element" /
        "movenotes-search.html"
    ).write_text(_SIDEBAR_SEARCH_PARTIAL, encoding="utf-8")
    (layouts / "shortcodes" / "movenotes-start.html").write_text(
        _getting_started_shortcode(search_backend), encoding="utf-8"
    )
    (layouts / "shortcodes" / "movenotes-search.html").write_text(
        _search_shortcode(search_backend), encoding="utf-8"
    )
    (layouts / "shortcodes" / "movenotes-tags.html").write_text(
        _tags_shortcode(search_backend), encoding="utf-8"
    )
    (static / "css" / "movenotes-site.css").write_text(
        _SITE_CSS, encoding="utf-8"
    )
    (static / "js" / "movenotes-nav.js").write_text(
        _NAVIGATION_SCRIPT, encoding="utf-8"
    )

    server_source = Path(__file__).resolve().parent / "site_server"
    server_target = output / "server"
    if server_target.exists():
        shutil.rmtree(server_target)
    shutil.copytree(server_source, server_target)

    pagefind_config = output / "pagefind.yml"
    if search_backend in {"both", "pagefind"}:
        pagefind_config.write_text(
            "site: public\noutput_path: public/pagefind\nkeep_index_url: false\n"
            "exclude_selectors:\n  - '[data-pagefind-ignore]'\n",
            encoding="utf-8",
        )
    else:
        pagefind_config.unlink(missing_ok=True)
    (output / ".gitignore").write_text(
        "/public/\n/resources/\n.hugo_build.lock\n/server/bluge-index/\n"
        "/server/bluge-index.building/\n/server/bluge-index.stamp.json\n"
        "/server/movenotes-site-server\n",
        encoding="utf-8",
    )


_SIDEBAR_SEARCH_PARTIAL = r'''<li class="movenotes-sidebar-search-item">
  <form class="movenotes-sidebar-search padding" action="{{ "search.html" | relURL }}" method="get" role="search">
    <label class="a11y-only" for="movenotes-sidebar-q">Search all notes</label>
    <div class="movenotes-sidebar-search-control">
      <i class="fa-fw fas fa-magnifying-glass" aria-hidden="true"></i>
      <input id="movenotes-sidebar-q" name="q" type="search" placeholder="Search all notes" autocomplete="off">
      <button type="submit" aria-label="Search"><i class="fas fa-arrow-right" aria-hidden="true"></i></button>
    </div>
  </form>
</li>
'''

_CONTENT_PARTIAL_PAGEFIND = r'''{{- if .Params.pagefind_ignore }}
<div data-pagefind-ignore>{{ .Content }}</div>
{{- else }}
<article data-pagefind-body>
  <div class="movenotes-index-metadata" data-pagefind-ignore>
    <span data-pagefind-meta="title" data-pagefind-weight="10">{{ .Title }}</span>
    {{- range .Params.movenotes_explicit_tags }}
    <span data-pagefind-filter="tag">{{ . }}</span>
    {{- end }}
  </div>
  {{ .Content }}
</article>
{{- end }}
'''

_CONTENT_PARTIAL_PLAIN = r'''<article>
  {{ .Content }}
</article>
'''


def _content_partial(search_backend: str) -> str:
    if search_backend in {"both", "pagefind"}:
        return _CONTENT_PARTIAL_PAGEFIND
    return _CONTENT_PARTIAL_PLAIN


_HEADING_PARTIAL = r'''{{- if not .Params.movenotes_hide_heading }}
{{- $title := partial "title.gotmpl" (dict "page" .) }}
<h1 id="{{ $title | plainify | anchorize }}">{{ $title }}</h1>
{{- end }}
'''


_CUSTOM_HEADER_PARTIAL = r'''<link rel="stylesheet" href="{{ "css/movenotes-site.css" | relURL }}">
<script defer src="{{ "js/movenotes-nav.js" | relURL }}"></script>
'''

_NAVIGATION_SCRIPT = r'''(() => {
  const prefetched = new Set();
  let hoverTimer;
  function eligible(anchor) {
    if (!anchor || anchor.target || anchor.hasAttribute('download')) return null;
    let url;
    try { url = new URL(anchor.href, location.href); }
    catch (_error) { return null; }
    if (url.origin !== location.origin || url.href === location.href) return null;
    if (!(url.pathname.endsWith('.html') || url.pathname.endsWith('/'))) return null;
    if (url.pathname.includes('/notes/')) return null;
    url.hash = '';
    return url;
  }
  function prefetch(anchor) {
    const url = eligible(anchor);
    if (!url || prefetched.has(url.href)) return;
    prefetched.add(url.href);
    const hint = document.createElement('link');
    hint.rel = 'prefetch';
    hint.as = 'document';
    hint.href = url.href;
    document.head.append(hint);
  }
  document.addEventListener('pointerover', event => {
    const anchor = event.target.closest?.('a[href]');
    if (!eligible(anchor)) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => prefetch(anchor), 120);
  }, {passive: true});
  document.addEventListener('pointerout', () => clearTimeout(hoverTimer), {passive: true});
  document.addEventListener('focusin', event => prefetch(event.target.closest?.('a[href]')));
})();
'''

_GETTING_STARTED_SHORTCODE = r'''<div class="movenotes-start" data-pagefind-ignore>
  <p class="movenotes-lead">A fast, private reading interface for a very large Obsidian vault. Notes stay out of the navigation tree so the browser remains responsive even when the archive contains more than 100,000 pages.</p>
  <div class="movenotes-start-grid">
    <a class="movenotes-start-card" href="{{ "search.html" | relURL }}">
      <span class="movenotes-start-icon"><i class="fas fa-magnifying-glass" aria-hidden="true"></i></span>
      <span><strong>Search the archive</strong><small>Use the generated Bluge server for fast server-side search, with Pagefind as a static-hosting fallback.</small></span>
      <i class="fas fa-arrow-right movenotes-start-arrow" aria-hidden="true"></i>
    </a>
    <a class="movenotes-start-card" href="{{ "tags.html" | relURL }}">
      <span class="movenotes-start-icon"><i class="fas fa-tags" aria-hidden="true"></i></span>
      <span><strong>Browse tags</strong><small>Find explicit Obsidian tags and generated content words through compact tag buckets.</small></span>
      <i class="fas fa-arrow-right movenotes-start-arrow" aria-hidden="true"></i>
    </a>
  </div>
  <div class="movenotes-start-details">
    <section>
      <h2>Search</h2>
      <p>Enter words, quoted phrases, tag:name, since:YYYY-MM-DD, or until:YYYY-MM-DD. The generated Go server searches Bluge on disk; Pagefind remains a static-hosting fallback.</p>
    </section>
    <section>
      <h2>Tags</h2>
      <p>Type at least two characters to load one matching tag bucket. Selecting a tag opens the exact set of notes counted by the tag index, without loading Pagefind.</p>
    </section>
    <section>
      <h2>Navigation</h2>
      <p>Links between notes become ordinary static links. Attachments are copied into <code>static/vault-assets</code>.</p>
    </section>
  </div>
</div>
'''


def _getting_started_shortcode(search_backend: str) -> str:
    if search_backend == "bluge":
        return _GETTING_STARTED_SHORTCODE.replace(
            "Use the generated Bluge server for fast server-side search, with Pagefind as a static-hosting fallback.",
            "Use the generated Bluge server for fast server-side search without downloading a browser index.",
        ).replace(
            "The generated Go server searches Bluge on disk; Pagefind remains a static-hosting fallback.",
            "The generated Go server searches the Bluge index on disk and returns only the visible result page.",
        ).replace(", without loading Pagefind", "").replace(
            ' data-pagefind-ignore', ''
        )
    if search_backend == "pagefind":
        return _GETTING_STARTED_SHORTCODE.replace(
            "Use the generated Bluge server for fast server-side search, with Pagefind as a static-hosting fallback.",
            "Use Pagefind for fully static browser-side search.",
        ).replace(
            "The generated Go server searches Bluge on disk; Pagefind remains a static-hosting fallback.",
            "Pagefind downloads only the index chunks needed for the submitted query.",
        )
    return _GETTING_STARTED_SHORTCODE


_SEARCH_SHORTCODE = r'''<div class="movenotes-search-page" data-pagefind-ignore>
  <form id="movenotes-search-form" class="movenotes-tool-form" role="search">
    <label for="movenotes-q">Search all notes</label>
    <div class="movenotes-search-row">
      <input id="movenotes-q" name="q" type="search" autocomplete="off" placeholder='Words, "quoted phrase", tag:name, since:YYYY-MM-DD, until:YYYY-MM-DD'>
      <button type="submit"><i class="fas fa-magnifying-glass" aria-hidden="true"></i><span>Search</span></button>
    </div>
    <p id="movenotes-filter-label" class="movenotes-filter-label"></p>
  </form>
  <p id="movenotes-search-status" class="movenotes-status" role="status"></p>
  <ol id="movenotes-search-results" class="movenotes-results"></ol>
  <button id="movenotes-more" class="movenotes-more" type="button" hidden>Load more results</button>
</div>
<script type="module">
const params = new URLSearchParams(location.search);
const input = document.querySelector('#movenotes-q');
const form = document.querySelector('#movenotes-search-form');
const status = document.querySelector('#movenotes-search-status');
const resultsElement = document.querySelector('#movenotes-search-results');
const moreButton = document.querySelector('#movenotes-more');
const filterLabel = document.querySelector('#movenotes-filter-label');
const allowServer = @@ALLOW_SERVER@@;
const allowPagefind = @@ALLOW_PAGEFIND@@;
const pagefindUrl = @@PAGEFIND_URL@@;
const tagManifestUrl = '{{ "movenotes/tags/manifest.json" | relURL }}';
const tagPostingsBase = '{{ "movenotes/tag-postings/" | relURL }}';
const documentsBase = '{{ "movenotes/documents/" | relURL }}';
const siteRoot = new URL('{{ "/" | relURL }}', location.href);
const serverHealthUrl = new URL('api/health', siteRoot).href;
const serverSearchUrl = new URL('api/search', siteRoot).href;
const pageSize = 20;
const jsonCache = new Map();
let pagefindReady;
let serverReady;
let results = [];
let tagResultIds = [];
let serverTotal = 0;
let shown = 0;
let searchGeneration = 0;
let resultMode = allowServer ? 'server' : 'pagefind';
let selectedTag = (params.get('tag') || '').trim().toLowerCase();
input.value = params.get('q') || selectedTag;
if (selectedTag) filterLabel.textContent = `Exact tag: ${selectedTag}`;

function escapeText(value) { return String(value ?? ''); }
function tagPostingBucket(value) {
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(value)) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return (hash & 0xfff).toString(16).padStart(3, '0');
}
async function loadJson(url) {
  if (!jsonCache.has(url)) jsonCache.set(url, fetch(url).then(response => {
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }));
  return jsonCache.get(url);
}
async function hasServer() {
  if (!allowServer) return false;
  serverReady ||= fetch(serverHealthUrl, {cache: 'no-store', signal: AbortSignal.timeout(3000)})
    .then(response => response.ok)
    .catch(() => false);
  return serverReady;
}
async function ensurePagefind() {
  if (!allowPagefind) throw new Error('Pagefind was not generated for this site');
  pagefindReady ||= (async () => {
    const module = await import(pagefindUrl);
    await module.options({
      excerptLength: 18,
      metaCacheTag: '{{ site.Params.movenotesBuildId }}',
    });
    await module.init();
    return module;
  })();
  return pagefindReady;
}
function appendResult(fragment, url, title, excerpt, useHtml = false, date = '') {
  const item = document.createElement('li');
  const link = document.createElement('a');
  link.href = url;
  link.textContent = escapeText(title || url);
  const detail = document.createElement('p');
  if (useHtml) detail.innerHTML = excerpt || '';
  else detail.textContent = excerpt || '';
  if (date) {
    const time = document.createElement('time');
    time.dateTime = date;
    time.textContent = date.slice(0, 10);
    item.append(link, time, detail);
  } else {
    item.append(link, detail);
  }
  fragment.append(item);
}
async function renderPagefindMore(generation = searchGeneration) {
  const start = shown;
  const end = Math.min(results.length, start + pageSize);
  moreButton.disabled = true;
  const rows = await Promise.all(
    results.slice(start, end).map(result => result.data().catch(error => {
      console.warn('Unable to load a Pagefind result', error);
      return null;
    }))
  );
  if (generation !== searchGeneration) return;
  const fragment = document.createDocumentFragment();
  rows.forEach(data => {
    if (!data) return;
    appendResult(fragment, data.url, data.meta?.title || data.url, data.excerpt || '', true);
  });
  shown = end;
  resultsElement.append(fragment);
  moreButton.hidden = shown >= results.length;
  moreButton.disabled = false;
}
async function renderServerMore(generation = searchGeneration) {
  moreButton.disabled = true;
  const url = new URL(serverSearchUrl);
  if (selectedTag) url.searchParams.set('tag', selectedTag);
  else url.searchParams.set('q', input.value.trim());
  url.searchParams.set('offset', String(shown));
  url.searchParams.set('limit', String(pageSize));
  const response = await fetch(url, {headers: {'Accept': 'application/json'}});
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  const payload = await response.json();
  if (generation !== searchGeneration) return;
  serverTotal = Number(payload.total || 0);
  const fragment = document.createDocumentFragment();
  for (const row of payload.results || []) {
    appendResult(fragment, row.url, row.title || row.url, row.excerpt || '', false, row.date || '');
  }
  shown += (payload.results || []).length;
  resultsElement.append(fragment);
  status.textContent = selectedTag
    ? `${serverTotal.toLocaleString()} result(s) with exact tag “${selectedTag}” · Bluge server`
    : `${serverTotal.toLocaleString()} result(s) · Bluge server`;
  moreButton.hidden = shown >= serverTotal;
  moreButton.disabled = false;
}
async function renderTagMore(generation = searchGeneration) {
  const start = shown;
  const end = Math.min(tagResultIds.length, start + pageSize);
  moreButton.disabled = true;
  const manifest = await loadJson(tagManifestUrl);
  const chunkSize = Number(manifest.document_chunk_size || 512);
  const neededChunks = new Set(
    tagResultIds.slice(start, end).map(noteId => Math.floor(Number(noteId) / chunkSize))
  );
  const chunks = new Map(await Promise.all(Array.from(neededChunks, async chunk => {
    const name = chunk.toString(16).padStart(6, '0');
    return [chunk, await loadJson(`${documentsBase}${name}.json`)];
  })));
  if (generation !== searchGeneration) return;
  const fragment = document.createDocumentFragment();
  for (const noteId of tagResultIds.slice(start, end)) {
    const chunk = Math.floor(Number(noteId) / chunkSize);
    const record = chunks.get(chunk)?.[String(noteId)];
    if (!record) continue;
    const [relativeUrl, title] = record;
    appendResult(fragment, new URL(relativeUrl, siteRoot).href, title || relativeUrl, `Exact tag match · ${relativeUrl}`);
  }
  shown = end;
  resultsElement.append(fragment);
  moreButton.hidden = shown >= tagResultIds.length;
  moreButton.disabled = false;
}
async function searchExactTag(generation) {
  resultMode = 'tag';
  status.textContent = 'Loading exact tag index…';
  const manifest = await loadJson(tagManifestUrl);
  const bucket = tagPostingBucket(selectedTag);
  if (!Object.prototype.hasOwnProperty.call(manifest.posting_buckets || {}, bucket)) {
    tagResultIds = [];
  } else {
    const postings = await loadJson(`${tagPostingsBase}${bucket}.json`);
    tagResultIds = postings[selectedTag] || [];
  }
  if (generation !== searchGeneration) return;
  status.textContent = `${tagResultIds.length.toLocaleString()} result(s) with exact tag “${selectedTag}”`;
  await renderTagMore(generation);
}
async function searchPagefind(generation) {
  resultMode = 'pagefind';
  status.textContent = 'Loading browser search index…';
  const pagefind = await ensurePagefind();
  const response = await pagefind.search(input.value.trim() || null);
  if (generation !== searchGeneration) return;
  results = response.results || [];
  status.textContent = `${results.length.toLocaleString()} result(s) · Pagefind fallback`;
  await renderPagefindMore(generation);
}
async function searchServer(generation) {
  resultMode = 'server';
  status.textContent = 'Searching server index…';
  await renderServerMore(generation);
}
async function search() {
  const generation = ++searchGeneration;
  resultsElement.replaceChildren();
  shown = 0;
  results = [];
  tagResultIds = [];
  serverTotal = 0;
  moreButton.hidden = true;
  form.setAttribute('aria-busy', 'true');
  try {
    if (selectedTag && allowServer && await hasServer()) await searchServer(generation);
    else if (selectedTag) await searchExactTag(generation);
    else if (allowServer && await hasServer()) await searchServer(generation);
    else if (allowPagefind) await searchPagefind(generation);
    else throw new Error('Bluge server is unavailable');
  } catch (error) {
    if (generation !== searchGeneration) return;
    status.textContent = selectedTag
      ? 'The exact tag index is unavailable. Regenerate the site with obsidian2site.py.'
      : (allowPagefind ? 'Search is unavailable. Start the generated Go server or rebuild Pagefind.' : 'Search is unavailable. Start the generated movenotes-site-server.');
    console.error(error);
  } finally {
    if (generation === searchGeneration) form.removeAttribute('aria-busy');
  }
}
form.addEventListener('submit', event => {
  event.preventDefault();
  selectedTag = '';
  filterLabel.textContent = '';
  const next = new URL(location.href);
  next.searchParams.delete('tag');
  input.value.trim() ? next.searchParams.set('q', input.value.trim()) : next.searchParams.delete('q');
  history.replaceState({}, '', next);
  search();
});
moreButton.addEventListener('click', () => {
  if (resultMode === 'tag') renderTagMore();
  else if (resultMode === 'server') renderServerMore();
  else renderPagefindMore();
});
let preloadTimer;
input.addEventListener('input', () => {
  if (selectedTag || !allowPagefind) return;
  clearTimeout(preloadTimer);
  const term = input.value.trim();
  if (!term) return;
  preloadTimer = setTimeout(async () => {
    try {
      if (!allowServer || !(await hasServer())) (await ensurePagefind()).preload(term);
    } catch (_error) { /* The submitted search will show the actionable error. */ }
  }, 120);
});
window.addEventListener('pagehide', () => {
  if (allowPagefind && pagefindReady) pagefindReady.then(module => module.destroy?.()).catch(() => {});
});
if (input.value || selectedTag) search();
</script>
'''


_SEARCH_SHORTCODE_BLUGE = r'''<div class="movenotes-search-page">
  <form id="movenotes-search-form" class="movenotes-tool-form" role="search">
    <label for="movenotes-q">Search all notes</label>
    <div class="movenotes-search-row">
      <input id="movenotes-q" name="q" type="search" autocomplete="off" placeholder='Words, "quoted phrase", tag:name, since:YYYY-MM-DD, until:YYYY-MM-DD'>
      <button type="submit"><i class="fas fa-magnifying-glass" aria-hidden="true"></i><span>Search</span></button>
    </div>
    <p id="movenotes-filter-label" class="movenotes-filter-label"></p>
  </form>
  <p id="movenotes-search-status" class="movenotes-status" role="status"></p>
  <ol id="movenotes-search-results" class="movenotes-results"></ol>
  <button id="movenotes-more" class="movenotes-more" type="button" hidden>Load more results</button>
</div>
<script type="module">
const params = new URLSearchParams(location.search);
const input = document.querySelector('#movenotes-q');
const form = document.querySelector('#movenotes-search-form');
const status = document.querySelector('#movenotes-search-status');
const resultsElement = document.querySelector('#movenotes-search-results');
const moreButton = document.querySelector('#movenotes-more');
const filterLabel = document.querySelector('#movenotes-filter-label');
const tagManifestUrl = '{{ "movenotes/tags/manifest.json" | relURL }}';
const tagPostingsBase = '{{ "movenotes/tag-postings/" | relURL }}';
const documentsBase = '{{ "movenotes/documents/" | relURL }}';
const siteRoot = new URL('{{ "/" | relURL }}', location.href);
const serverHealthUrl = new URL('api/health', siteRoot).href;
const serverSearchUrl = new URL('api/search', siteRoot).href;
const pageSize = 20;
const jsonCache = new Map();
let serverReady;
let tagResultIds = [];
let serverTotal = 0;
let shown = 0;
let searchGeneration = 0;
let resultMode = 'server';
let selectedTag = (params.get('tag') || '').trim().toLowerCase();
input.value = params.get('q') || selectedTag;
if (selectedTag) filterLabel.textContent = `Exact tag: ${selectedTag}`;

function escapeText(value) { return String(value ?? ''); }
function tagPostingBucket(value) {
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(value)) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return (hash & 0xfff).toString(16).padStart(3, '0');
}
async function loadJson(url) {
  if (!jsonCache.has(url)) jsonCache.set(url, fetch(url).then(response => {
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }));
  return jsonCache.get(url);
}
async function hasServer() {
  serverReady ||= fetch(serverHealthUrl, {cache: 'no-store', signal: AbortSignal.timeout(3000)})
    .then(response => response.ok)
    .catch(() => false);
  return serverReady;
}
function appendResult(fragment, url, title, excerpt, date = '') {
  const item = document.createElement('li');
  const link = document.createElement('a');
  link.href = url;
  link.textContent = escapeText(title || url);
  const detail = document.createElement('p');
  detail.textContent = excerpt || '';
  if (date) {
    const time = document.createElement('time');
    time.dateTime = date;
    time.textContent = date.slice(0, 10);
    item.append(link, time, detail);
  } else item.append(link, detail);
  fragment.append(item);
}
async function renderServerMore(generation = searchGeneration) {
  moreButton.disabled = true;
  const url = new URL(serverSearchUrl);
  if (selectedTag) url.searchParams.set('tag', selectedTag);
  else url.searchParams.set('q', input.value.trim());
  url.searchParams.set('offset', String(shown));
  url.searchParams.set('limit', String(pageSize));
  const response = await fetch(url, {headers: {'Accept': 'application/json'}});
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  const payload = await response.json();
  if (generation !== searchGeneration) return;
  serverTotal = Number(payload.total || 0);
  const fragment = document.createDocumentFragment();
  for (const row of payload.results || []) {
    appendResult(fragment, row.url, row.title || row.url, row.excerpt || '', row.date || '');
  }
  shown += (payload.results || []).length;
  resultsElement.append(fragment);
  status.textContent = selectedTag
    ? `${serverTotal.toLocaleString()} result(s) with exact tag “${selectedTag}” · Bluge server`
    : `${serverTotal.toLocaleString()} result(s) · Bluge server`;
  moreButton.hidden = shown >= serverTotal;
  moreButton.disabled = false;
}
async function renderTagMore(generation = searchGeneration) {
  const start = shown;
  const end = Math.min(tagResultIds.length, start + pageSize);
  moreButton.disabled = true;
  const manifest = await loadJson(tagManifestUrl);
  const chunkSize = Number(manifest.document_chunk_size || 512);
  const neededChunks = new Set(tagResultIds.slice(start, end).map(id => Math.floor(Number(id) / chunkSize)));
  const chunks = new Map(await Promise.all(Array.from(neededChunks, async chunk => {
    const name = chunk.toString(16).padStart(6, '0');
    return [chunk, await loadJson(`${documentsBase}${name}.json`)];
  })));
  if (generation !== searchGeneration) return;
  const fragment = document.createDocumentFragment();
  for (const noteId of tagResultIds.slice(start, end)) {
    const record = chunks.get(Math.floor(Number(noteId) / chunkSize))?.[String(noteId)];
    if (!record) continue;
    const [relativeUrl, title] = record;
    appendResult(fragment, new URL(relativeUrl, siteRoot).href, title || relativeUrl, `Exact tag match · ${relativeUrl}`);
  }
  shown = end;
  resultsElement.append(fragment);
  moreButton.hidden = shown >= tagResultIds.length;
  moreButton.disabled = false;
}
async function searchExactTagFallback(generation) {
  resultMode = 'tag';
  status.textContent = 'Bluge server unavailable; loading the compact exact-tag fallback…';
  const manifest = await loadJson(tagManifestUrl);
  const bucket = tagPostingBucket(selectedTag);
  if (!Object.prototype.hasOwnProperty.call(manifest.posting_buckets || {}, bucket)) tagResultIds = [];
  else tagResultIds = (await loadJson(`${tagPostingsBase}${bucket}.json`))[selectedTag] || [];
  if (generation !== searchGeneration) return;
  status.textContent = `${tagResultIds.length.toLocaleString()} result(s) with exact tag “${selectedTag}” · static fallback`;
  await renderTagMore(generation);
}
async function search() {
  const generation = ++searchGeneration;
  resultsElement.replaceChildren();
  shown = 0;
  tagResultIds = [];
  serverTotal = 0;
  resultMode = 'server';
  moreButton.hidden = true;
  form.setAttribute('aria-busy', 'true');
  try {
    if (await hasServer()) {
      status.textContent = 'Searching Bluge server…';
      await renderServerMore(generation);
    } else if (selectedTag) await searchExactTagFallback(generation);
    else throw new Error('Bluge server is unavailable');
  } catch (error) {
    if (generation !== searchGeneration) return;
    status.textContent = 'Search is unavailable. Start the generated movenotes-site-server.';
    console.error(error);
  } finally {
    if (generation === searchGeneration) form.removeAttribute('aria-busy');
  }
}
form.addEventListener('submit', event => {
  event.preventDefault();
  selectedTag = '';
  filterLabel.textContent = '';
  const next = new URL(location.href);
  next.searchParams.delete('tag');
  input.value.trim() ? next.searchParams.set('q', input.value.trim()) : next.searchParams.delete('q');
  history.replaceState({}, '', next);
  serverReady = undefined;
  search();
});
moreButton.addEventListener('click', () => {
  if (resultMode === 'tag') renderTagMore();
  else renderServerMore();
});
if (input.value || selectedTag) search();
</script>
'''


def _search_shortcode(search_backend: str) -> str:
    if search_backend == "bluge":
        return _SEARCH_SHORTCODE_BLUGE
    allow_server = search_backend == "both"
    allow_pagefind = search_backend in {"both", "pagefind"}
    pagefind_url = "'{{ \"pagefind/pagefind.js\" | relURL }}'" if allow_pagefind else "''"
    return (
        _SEARCH_SHORTCODE
        .replace("@@ALLOW_SERVER@@", "true" if allow_server else "false")
        .replace("@@ALLOW_PAGEFIND@@", "true" if allow_pagefind else "false")
        .replace("@@PAGEFIND_URL@@", pagefind_url)
    )

_TAGS_SHORTCODE = r'''<div class="movenotes-tags-page" data-pagefind-ignore>
  <div class="movenotes-tool-form">
    <label for="movenotes-tag-filter">Find a tag</label>
    <div class="movenotes-tag-filter-control">
      <i class="fas fa-filter" aria-hidden="true"></i>
      <input id="movenotes-tag-filter" type="search" placeholder="Type at least two characters" autocomplete="off">
    </div>
  </div>
  <p id="movenotes-tags-status" class="movenotes-status" role="status">Loading frequent tags…</p>
  <ul id="movenotes-tags-list" class="movenotes-tag-list"></ul>
</div>
<script type="module">
const input = document.querySelector('#movenotes-tag-filter');
const status = document.querySelector('#movenotes-tags-status');
const list = document.querySelector('#movenotes-tags-list');
const base = '{{ "movenotes/tags/" | relURL }}';
const searchUrl = '{{ "search.html" | relURL }}';
let manifest;
const cache = new Map();
function bucketFor(value) {
  const normalized = value.normalize('NFKD').toLowerCase();
  const chars = Array.from(normalized).filter(character => /[\p{L}\p{N}]/u.test(character));
  if (!chars.length) return '__';
  if (/^[a-z0-9]$/.test(chars[0])) {
    const ascii = chars.filter(character => /^[a-z0-9]$/.test(character)).join('');
    return (ascii + '_').slice(0, 2);
  }
  return `u${chars[0].codePointAt(0).toString(16)}`;
}
function render(rows, label) {
  list.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const [tag, count] of rows.slice(0, 300)) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.href = `${searchUrl}?tag=${encodeURIComponent(tag)}`;
    link.textContent = tag;
    const badge = document.createElement('span');
    badge.textContent = Number(count).toLocaleString();
    item.append(link, badge);
    fragment.append(item);
  }
  list.append(fragment);
  status.textContent = `${label}: ${rows.length.toLocaleString()} tag(s)`;
}
async function loadJson(name) {
  if (!cache.has(name)) cache.set(name, fetch(base + name).then(response => {
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }));
  return cache.get(name);
}
async function update() {
  const query = input.value.trim().toLowerCase();
  try {
    if (!query) return render(await loadJson('top.json'), 'Most frequent');
    if (query.length < 2) {
      status.textContent = 'Type at least two characters, or clear the field for frequent tags.';
      list.replaceChildren();
      return;
    }
    manifest ||= await loadJson('manifest.json');
    const bucket = bucketFor(query);
    if (!Object.prototype.hasOwnProperty.call(manifest.buckets, bucket)) {
      return render([], `Tags matching “${query}”`);
    }
    const rows = await loadJson(`${bucket}.json`);
    render(rows.filter(([tag]) => tag.includes(query)), `Tags matching “${query}”`);
  } catch (error) {
    status.textContent = 'Tag index is unavailable.';
    console.error(error);
  }
}
let timer;
input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(update, 160); });
update();
</script>
'''

def _tags_shortcode(search_backend: str) -> str:
    if search_backend == "bluge":
        return _TAGS_SHORTCODE.replace(' data-pagefind-ignore', '')
    return _TAGS_SHORTCODE


_SITE_CSS = r'''
:root {
  --MENU-S-width: 17rem;
  --MENU-M-width: 18rem;
  --MENU-L-width: 20rem;
  --movenotes-radius: .65rem;
  --movenotes-border: color-mix(in srgb, currentColor 18%, transparent);
  --movenotes-muted: color-mix(in srgb, currentColor 68%, transparent);
  --movenotes-surface: color-mix(in srgb, currentColor 5%, transparent);
  --movenotes-surface-hover: color-mix(in srgb, currentColor 9%, transparent);
}

/* Keep Relearn's complete sidebar shell. Only the custom element inside it is styled. */
.movenotes-sidebar-search-item { list-style: none; }
.movenotes-sidebar-search { display: block; padding-top: .55rem !important; padding-bottom: .55rem !important; }
.movenotes-sidebar-search-control,
.movenotes-tag-filter-control {
  display: flex;
  align-items: center;
  gap: .5rem;
  min-width: 0;
  border: 1px solid var(--movenotes-border);
  border-radius: var(--movenotes-radius);
  background: var(--movenotes-surface);
  padding: .15rem .2rem .15rem .65rem;
  transition: border-color .16s ease, background-color .16s ease, box-shadow .16s ease;
}
.movenotes-sidebar-search-control:focus-within,
.movenotes-tag-filter-control:focus-within {
  border-color: currentColor;
  background: transparent;
  box-shadow: 0 0 0 .15rem color-mix(in srgb, currentColor 12%, transparent);
}
.movenotes-sidebar-search-control input,
.movenotes-tag-filter-control input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  padding: .55rem 0;
}
.movenotes-sidebar-search-control input::placeholder,
.movenotes-tag-filter-control input::placeholder { color: var(--movenotes-muted); opacity: 1; }
.movenotes-sidebar-search-control button {
  display: grid;
  place-items: center;
  width: 2.25rem;
  height: 2.25rem;
  border: 0;
  border-radius: .5rem;
  background: color-mix(in srgb, currentColor 12%, transparent);
  color: inherit;
  cursor: pointer;
}
.movenotes-sidebar-search-control button:hover { background: color-mix(in srgb, currentColor 20%, transparent); }

.movenotes-index-metadata {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  overflow: hidden !important;
  clip: rect(0 0 0 0) !important;
  white-space: nowrap !important;
}

.movenotes-lead {
  max-width: 58rem;
  margin: -.35rem 0 1.5rem;
  color: var(--movenotes-muted);
  font-size: 1.08rem;
  line-height: 1.75;
}
.movenotes-start-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
  margin: 1.25rem 0 2rem;
}
.movenotes-start-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: .9rem;
  padding: 1.1rem;
  border: 1px solid var(--movenotes-border);
  border-radius: .85rem;
  background: var(--movenotes-surface);
  color: inherit !important;
  text-decoration: none !important;
  transition: transform .16s ease, border-color .16s ease, background-color .16s ease;
}
.movenotes-start-card:hover {
  transform: translateY(-2px);
  border-color: currentColor;
  background: var(--movenotes-surface-hover);
}
.movenotes-start-card strong { display: block; margin-bottom: .25rem; font-size: 1.05rem; }
.movenotes-start-card small { display: block; color: var(--movenotes-muted); line-height: 1.5; }
.movenotes-start-icon {
  display: grid;
  place-items: center;
  width: 2.75rem;
  height: 2.75rem;
  border-radius: .75rem;
  background: color-mix(in srgb, currentColor 12%, transparent);
}
.movenotes-start-arrow { opacity: .55; }
.movenotes-start-details {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1.4rem;
  margin-top: 1rem;
}
.movenotes-start-details h2 { margin: 0 0 .45rem; font-size: 1.15rem; }
.movenotes-start-details p { margin: 0; color: var(--movenotes-muted); line-height: 1.65; }

.movenotes-tool-form { max-width: 58rem; margin-bottom: .9rem; }
.movenotes-tool-form > label { display: block; font-weight: 650; margin-bottom: .45rem; }
.movenotes-search-row { display: flex; align-items: stretch; gap: .6rem; }
.movenotes-search-row input {
  min-width: 0;
  flex: 1;
  border: 1px solid var(--movenotes-border);
  border-radius: var(--movenotes-radius);
  background: var(--movenotes-surface);
  color: inherit;
  font: inherit;
  padding: .75rem .85rem;
  outline: 0;
}
.movenotes-search-row input:focus {
  border-color: currentColor;
  box-shadow: 0 0 0 .15rem color-mix(in srgb, currentColor 12%, transparent);
}
.movenotes-search-row button,
.movenotes-more {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: .45rem;
  border: 1px solid var(--movenotes-border);
  border-radius: var(--movenotes-radius);
  background: color-mix(in srgb, currentColor 12%, transparent);
  color: inherit;
  font: inherit;
  font-weight: 650;
  padding: .7rem 1rem;
  cursor: pointer;
}
.movenotes-search-row button:hover,
.movenotes-more:hover { background: color-mix(in srgb, currentColor 20%, transparent); }
.movenotes-filter-label,
.movenotes-status { color: var(--movenotes-muted); min-height: 1.5rem; }
.movenotes-results { display: grid; gap: .75rem; padding: 0; list-style: none; counter-reset: movenotes-result; }
.movenotes-results li {
  position: relative;
  counter-increment: movenotes-result;
  border: 1px solid var(--movenotes-border);
  border-radius: var(--movenotes-radius);
  background: var(--movenotes-surface);
  padding: .9rem 1rem .9rem 3rem;
}
.movenotes-results li::before {
  content: counter(movenotes-result);
  position: absolute;
  left: 1rem;
  top: .95rem;
  color: var(--movenotes-muted);
  font-variant-numeric: tabular-nums;
}
.movenotes-results li > a { display: inline-block; font-weight: 680; text-decoration: none; }
.movenotes-results li > a:hover { text-decoration: underline; }
.movenotes-results p { margin: .35rem 0 0; color: var(--movenotes-muted); line-height: 1.55; overflow-wrap: anywhere; }
.movenotes-results mark { border-radius: .2rem; padding: 0 .08em; }
.movenotes-more { margin-top: 1rem; }

.movenotes-tag-filter-control { max-width: 58rem; padding-left: .8rem; }
.movenotes-tag-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr));
  gap: .6rem;
  padding: 0;
  list-style: none;
}
.movenotes-tag-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  min-width: 0;
  border: 1px solid var(--movenotes-border);
  border-radius: .55rem;
  background: var(--movenotes-surface);
  padding: .55rem .7rem;
}
.movenotes-tag-list a { min-width: 0; overflow-wrap: anywhere; text-decoration: none; }
.movenotes-tag-list a:hover { text-decoration: underline; }
.movenotes-tag-list span {
  flex: 0 0 auto;
  color: var(--movenotes-muted);
  font-variant-numeric: tabular-nums;
}
.movenotes-invalid-url { overflow-wrap: anywhere; text-decoration: underline dotted; cursor: help; }

@media (max-width: 52rem) {
  .movenotes-start-grid,
  .movenotes-start-details { grid-template-columns: 1fr; }
}
@media (max-width: 36rem) {
  .movenotes-search-row { flex-direction: column; }
  .movenotes-search-row button { width: 100%; }
  .movenotes-results li { padding-left: 2.65rem; }
}
@media (prefers-reduced-motion: reduce) {
  .movenotes-start-card,
  .movenotes-sidebar-search-control,
  .movenotes-tag-filter-control { transition: none; }
}
'''


def _prepare_output(output: Path, force: bool) -> None:
    marker = output / ".movenotes-static-site.json"
    if output.exists():
        entries = list(output.iterdir())
        if entries and not marker.is_file() and not force:
            common.error(
                f"output directory '{output}' is not empty and is not a generated movenotes site; "
                "use --force to replace it"
            )
        if entries and (marker.is_file() or force):
            for name in ("content", "layouts", "static", "assets", "public", "themes", "resources", "server"):
                target = output / name
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
            for name in (
                "hugo.toml", "pagefind.yml", ".gitignore", ".hugo_build.lock",
                "go.mod", "go.sum", ".obsidian2site-tags.sqlite",
            ):
                (output / name).unlink(missing_ok=True)
    output.mkdir(parents=True, exist_ok=True)


def _write_site_marker(output: Path, input_root: Path, note_count: int, asset_count: int) -> None:
    marker = {
        "generator": __program_name__,
        "version": __version__,
        "source": str(input_root),
        "notes": note_count,
        "files": asset_count,
    }
    (output / ".movenotes-static-site.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _pagefind_command(args: argparse.Namespace, output: Path) -> list[str]:
    if args.pagefind_bin:
        return [args.pagefind_bin, "--site", str(output / "public")]
    executable = shutil.which("pagefind")
    if executable:
        return [executable, "--site", str(output / "public")]
    try:
        import importlib.util
        has_python_pagefind = importlib.util.find_spec("pagefind") is not None
    except (ImportError, ValueError):
        has_python_pagefind = False
    if has_python_pagefind:
        return [sys.executable, "-m", "pagefind", "--site", str(output / "public")]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", "pagefind", "--site", str(output / "public")]
    common.error("Pagefind was not found; install it or pass --pagefind-bin")
    raise AssertionError



def _validate_built_search_backend(output: Path, search_backend: str) -> None:
    """Reject generated HTML that accidentally activates an unwanted browser index."""
    if search_backend != "bluge":
        return
    public = output / "public"
    forbidden = re.compile(
        r'''(?:src|href)=["'][^"']*(?:lunr(?:[.-]|\.js)|searchindex(?:[.-]|\.js)|pagefind/)[^"']*["']''',
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path in public.rglob("*.html"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if forbidden.search(text):
            offenders.append(path.relative_to(public).as_posix())
            if len(offenders) >= 10:
                break
    if offenders:
        common.error(
            "Bluge build still references a browser search index in: "
            + ", ".join(offenders)
        )


def _build_site(args: argparse.Namespace, output: Path) -> None:
    hugo = shutil.which(args.hugo_bin) if os.path.sep not in args.hugo_bin else args.hugo_bin
    if not hugo:
        common.error(f"Hugo executable not found: {args.hugo_bin}")
    print("building Hugo site...")
    subprocess.run(
        [str(hugo), "--source", str(output), "--destination", str(output / "public"), "--gc", "--minify"],
        check=True,
    )
    _validate_built_search_backend(output, args.search_backend)
    if args.search_backend in {"both", "pagefind"}:
        print("building Pagefind index...")
        subprocess.run(_pagefind_command(args, output), cwd=output, check=True)
    if args.search_backend in {"both", "bluge"}:
        print("building Bluge site server...")
        go = shutil.which(args.go_bin) if os.path.sep not in args.go_bin else args.go_bin
        if not go:
            common.error(f"Go executable not found: {args.go_bin}")
        print("resolving Go module checksums...")
        subprocess.run([str(go), "mod", "tidy"], cwd=output / "server", check=True)
        subprocess.run([str(go), "build", "-o", "movenotes-site-server", "."], cwd=output / "server", check=True)
        print("building Bluge search index...")
        subprocess.run(
            [
                str(output / "server" / "movenotes-site-server"),
                "-source", str(output / "server" / "search-source.jsonl"),
                "-index", str(output / "server" / "bluge-index"),
                "-index-only",
            ],
            cwd=output / "server",
            check=True,
        )


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)
    _validate_args(args)
    input_root: Path = args.input_path
    output = args.output_path.expanduser().resolve()
    if output == input_root or input_root in output.parents:
        common.error("output directory must not be inside the input vault")
    _prepare_output(output, args.force)

    markdown_paths, asset_paths = _scan_vault(input_root, args.include_hidden)
    print(f"found {len(markdown_paths):,} Markdown note(s) and {len(asset_paths):,} attachment/file(s)")
    note_map, asset_map = _build_path_maps(input_root, markdown_paths, asset_paths)
    note_exact, note_basenames = _lookup_indexes(note_map.keys())
    asset_exact, asset_basenames = _lookup_indexes(asset_map.keys())

    copied_theme = False
    modernized_theme_files = 0
    if args.relearn_theme is not None:
        theme_target = output / "themes" / "hugo-theme-relearn"
        if theme_target.exists():
            shutil.rmtree(theme_target)
        theme_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(args.relearn_theme, theme_target)
        modernized_theme_files = _modernize_copied_relearn_theme(theme_target)
        copied_theme = True

    _write_hugo_project(
        output,
        title=args.title or input_root.name,
        base_url=args.base_url,
        locale=args.locale,
        copied_theme=copied_theme,
        search_backend=args.search_backend,
    )
    if modernized_theme_files:
        print(
            f"updated {modernized_theme_files:,} copied Relearn template file(s) "
            "for Hugo 0.158+ APIs"
        )
    copied_assets = _copy_assets(input_root, output / "static", asset_map)

    stop_words = _load_stop_words(args.stop_words)
    tag_db_path = output / ".obsidian2site-tags.sqlite"
    if tag_db_path.exists():
        tag_db_path.unlink()
    tag_connection = _open_tag_database(tag_db_path)
    processed = 0
    repaired_urls = 0
    preserved_urls = 0
    pending_tag_counts: Counter[str] = Counter()
    pending_documents: list[tuple[int, str, str]] = []
    pending_tag_documents: list[tuple[int, str, int]] = []
    pending_tag_notes = 0
    search_source_path = output / "server" / "search-source.jsonl"
    search_source = search_source_path.open("w", encoding="utf-8", newline="\n")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            source_iterator = iter(enumerate(markdown_paths))
            pending: dict[concurrent.futures.Future, tuple[Path, int]] = {}

            def submit_next() -> bool:
                try:
                    note_id, path = next(source_iterator)
                except StopIteration:
                    return False
                future = executor.submit(
                    _process_note,
                    path,
                    input_root=input_root,
                    content_root=output / "content",
                    note_map=note_map,
                    asset_map=asset_map,
                    note_exact=note_exact,
                    note_basenames=note_basenames,
                    asset_exact=asset_exact,
                    asset_basenames=asset_basenames,
                    stop_words=stop_words,
                    minimum_word_length=args.minimum_word_length,
                    note_embeds=args.note_embeds,
                )
                pending[future] = (path, note_id)
                return True

            for _ in range(min(len(markdown_paths), max(args.workers * 2, 1))):
                submit_next()
            while pending:
                done, _not_done = concurrent.futures.wait(
                    pending, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    source_path, note_id = pending.pop(future)
                    try:
                        (
                            tags,
                            _source,
                            site_url,
                            note_title,
                            note_date,
                            note_search_text,
                            note_repaired_urls,
                            note_preserved_urls,
                        ) = future.result()
                    except Exception as exc:
                        for outstanding in pending:
                            outstanding.cancel()
                        common.error(
                            f"failed converting Obsidian note {source_path!s}: {exc}"
                        )
                    pending_tag_counts.update(tags)
                    pending_documents.append((note_id, site_url, note_title))
                    search_source.write(json.dumps({
                        "id": note_id,
                        "url": site_url,
                        "title": note_title,
                        "date": note_date,
                        "body": note_search_text,
                        "summary": note_search_text[:700],
                        "tags": tags,
                    }, ensure_ascii=False, separators=(",", ":")) + "\n")
                    pending_tag_documents.extend(
                        (_tag_posting_bucket(tag), tag, note_id) for tag in tags
                    )
                    repaired_urls += note_repaired_urls
                    preserved_urls += note_preserved_urls
                    pending_tag_notes += 1
                    if pending_tag_notes >= args.tag_batch_size:
                        _update_tag_counts(tag_connection, pending_tag_counts)
                        _update_tag_documents(
                            tag_connection,
                            pending_documents,
                            pending_tag_documents,
                        )
                        pending_tag_counts.clear()
                        pending_documents.clear()
                        pending_tag_documents.clear()
                        pending_tag_notes = 0
                    processed += 1
                    submit_next()
                    if args.progress_every and processed % args.progress_every == 0:
                        print(f"converted {processed:,} of {len(markdown_paths):,} note(s)")
        if pending_documents:
            _update_tag_counts(tag_connection, pending_tag_counts)
            _update_tag_documents(
                tag_connection,
                pending_documents,
                pending_tag_documents,
            )
            pending_tag_counts.clear()
            pending_documents.clear()
            pending_tag_documents.clear()
        tag_connection.commit()
        tag_count = _write_tag_index(tag_connection, output / "static")
    finally:
        search_source.close()
        tag_connection.close()
        tag_db_path.unlink(missing_ok=True)
        wal = Path(str(tag_db_path) + "-wal")
        shm = Path(str(tag_db_path) + "-shm")
        wal.unlink(missing_ok=True)
        shm.unlink(missing_ok=True)

    _write_site_marker(output, input_root, processed, copied_assets)
    print(
        f"generated Hugo project: {processed:,} note(s), {copied_assets:,} file(s), "
        f"{tag_count:,} unique tag(s)"
    )
    if repaired_urls or preserved_urls:
        print(
            f"checked URLs: {repaired_urls:,} repaired link target(s), "
            f"{preserved_urls:,} invalid URL(s) retained as visible text"
        )
    server_command = (
        f"{output / 'server' / 'movenotes-site-server'} "
        f"-site {output / 'public'} "
        f"-source {output / 'server' / 'search-source.jsonl'} "
        f"-index {output / 'server' / 'bluge-index'} "
        "-listen 127.0.0.1:8080"
    )
    if args.build:
        _build_site(args, output)
        print(f"built Hugo site in '{output / 'public'}'")
        if args.search_backend in {"both", "bluge"}:
            print(f"serve with '{server_command}'")
        elif args.search_backend == "pagefind":
            print(f"serve static files with 'python3 -m http.server 8080 --directory {output / 'public'}'")
    else:
        print(f"run 'hugo --source {output}'")
        if args.search_backend in {"both", "bluge"}:
            print(f"then build the server with 'cd {output / 'server'} && {args.go_bin} mod tidy && {args.go_bin} build -o movenotes-site-server .'")
            print(f"and serve with '{server_command}'")
        if args.search_backend in {"both", "pagefind"}:
            print(f"for static hosting fallback, run 'npx -y pagefind --site {output / 'public'}'")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
