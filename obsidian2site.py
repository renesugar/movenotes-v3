#!/usr/bin/env python3
"""Convert an Obsidian vault into a scalable Hugo static site.

The generated Hugo project uses the Ledger theme, which is built for archives of
100k+ notes: no page tree is ever enumerated, unbounded surfaces are capped, and
search is a swappable backend. Notes are found through server-side Bluge search,
the Pagefind static fallback, or the disk-backed tag index. The converter is
standard-library-only; Hugo, the theme, Go, and Pagefind are external build-time
tools.
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

_LEDGER_THEME_NAME = "hugo-theme-ledger"
_LEDGER_THEME_MODULE = "github.com/renesugar/hugo-theme-ledger"

# Bounds on the automatic taxonomy-tag cap. Measured at 5,000 synthetic notes: a
# taxonomy term costs about as much to build as a note page (200 terms → 11.2 s,
# 2,000 → 18.6 s, 5,000 → 32.2 s), so terms have to stay a small fraction of the
# note count or a small archive pays more for its tags than for its notes. The
# upper bound is the term count the theme has been benchmarked at.
_MINIMUM_TAXONOMY_TAGS = 200
_MAXIMUM_TAXONOMY_TAGS = 5000
_TAXONOMY_TAGS_PER_NOTE = 10


def _automatic_taxonomy_tag_cap(notes: int) -> int:
    return max(
        _MINIMUM_TAXONOMY_TAGS,
        min(_MAXIMUM_TAXONOMY_TAGS, notes // _TAXONOMY_TAGS_PER_NOTE),
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
        "--category-mode", choices=("folder", "fixed", "none"), default="folder",
        help=("Note category: from the top-level vault folder (default), one "
              "fixed name, or none"),
    )
    parser.add_argument(
        "--category-name",
        help=("Category for --category-mode fixed, and for notes at the vault "
              "root under folder mode (default: the site title)"),
    )
    parser.add_argument(
        "--max-taxonomy-tags", type=int,
        help=("Most frequent explicit tags to publish as Hugo taxonomy terms; "
              "the rest stay searchable through the tag index and Bluge. A term "
              "page costs about as much to build as a note page, so the default "
              "keeps terms at a tenth of the note count, bounded to "
              f"{_MINIMUM_TAXONOMY_TAGS}–{_MAXIMUM_TAXONOMY_TAGS}. 0 removes the "
              "cap"),
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
        "--ledger-theme", type=Path,
        help="Copy an existing hugo-theme-ledger checkout into the generated site",
    )
    parser.add_argument(
        "--relearn-theme", type=Path,
        help=(
            "Deprecated alias for --ledger-theme, kept because it appears in "
            "published command lines; the generated site uses hugo-theme-ledger"
        ),
    )
    parser.add_argument(
        "--build", action="store_true",
        help="Run Hugo and the selected search indexer after generating the project",
    )
    parser.add_argument(
        "--search-backend", choices=("both", "bluge", "pagefind"), default="both",
        help=("Search runtime to generate. 'bluge' emits no browser search index; "
              "'both' keeps Pagefind only as a static-hosting fallback "
              "(default: both)"),
    )
    parser.add_argument(
        "--vercel", action="store_true",
        help=("Also emit Vercel deployment files: vercel.json, .vercelignore, "
              "and — unless --search-backend pagefind — a root Go module with "
              "api/ functions for Bluge search"),
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
    if args.relearn_theme is not None and args.ledger_theme is None:
        # Accepted, not silently reinterpreted: the copied theme is Ledger now.
        print(
            "warning: --relearn-theme is deprecated; treating it as --ledger-theme. "
            "The generated site uses hugo-theme-ledger.",
            file=sys.stderr,
        )
        args.ledger_theme = args.relearn_theme
    elif args.relearn_theme is not None:
        common.error("pass either --ledger-theme or --relearn-theme, not both")
    if args.ledger_theme is not None and not args.ledger_theme.is_dir():
        common.error(f"Ledger theme directory does not exist: {args.ledger_theme}")
    if args.max_taxonomy_tags is not None and args.max_taxonomy_tags < 0:
        common.error("--max-taxonomy-tags cannot be negative")
    if args.vercel and args.search_backend != "pagefind" and args.ledger_theme is None:
        # Vercel's Go runtime needs go.mod at the project root, and Hugo's module
        # mode needs that same file for the theme import — `go mod tidy` would
        # then strip the theme, since no Go file imports it. A copied theme keeps
        # the root go.mod for Go alone.
        common.error(
            "--vercel with Bluge search requires --ledger-theme: the Go runtime "
            "needs go.mod at the project root, which Hugo's module mode also "
            "claims. Use --search-backend pagefind for a static-only Vercel "
            "deployment, which needs no Go module at all."
        )


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
    """Remove an initial H1 that merely repeats the theme's generated page title."""
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


def _note_category(
    source_relative: PurePosixPath, *, mode: str, fixed_name: str,
) -> str:
    """Return the note's category, or "" when categories are disabled.

    Folder mode uses the top-level vault folder, which is meaningful for the
    archives this converter targets (``Twitter/``, ``Notes/``). The name is used
    verbatim, not slugged: it is display text and it is what a `category:` query
    has to match.
    """
    if mode == "none":
        return ""
    if mode == "fixed":
        return fixed_name
    parts = source_relative.parts
    if len(parts) > 1:
        return parts[0]
    return fixed_name


def _frontmatter_json(
    *, title: str, date: str, lastmod: str, source_path: str,
    site_url: str, category: str = "", tags: list[str] | None = None,
    aliases: list[str] | None = None,
    hide_title: bool = False, hide_meta: bool = False,
) -> str:
    """Front matter for one note.

    Deliberately small: it is repeated once per note, so 166k notes pay for
    every field. Nothing is written that the theme can derive — no summary
    (Hugo's own `.Summary` is what result cards fall back to, and the post view
    refuses to use it as a standfirst because it duplicates the body directly
    below it) and no readingTime (`.ReadingTime`). The boolean switches are
    emitted only when true, since the theme's default for both is false.
    """
    data: dict[str, object] = {
        "title": title,
        "date": date,
        "lastmod": lastmod,
        "url": site_url,
        "movenotes_source_path": source_path,
    }
    if category:
        data["categories"] = [category]
    if tags:
        data["tags"] = tags
    if hide_title:
        data["ledgerHideTitle"] = True
    if hide_meta:
        data["ledgerHideMeta"] = True
    if aliases:
        data["aliases"] = aliases
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _reading_minutes(text: str) -> int:
    """Reading time in minutes, matching Hugo's .ReadingTime.

    Hugo divides the word count by 213 and rounds up. The theme falls back to
    .ReadingTime for its own pages, but a search result rendered from the Bluge
    index has no Hugo page behind it, so the number has to travel in the index.
    """
    words = len(text.split())
    return max(1, -(-words // 213)) if words else 0


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
    category_mode: str,
    category_name: str,
) -> tuple[list[str], list[str], str, str, str, str, str, str, int, int, int]:
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
    category = _note_category(
        source_relative, mode=category_mode, fixed_name=category_name
    )
    # Every explicit tag is written now; the ones that do not survive the
    # taxonomy cap are removed afterwards, once the global counts are known.
    content = _frontmatter_json(
        title=title, date=date, lastmod=lastmod,
        source_path=source_relative.as_posix(),
        site_url=hugo_url, category=category, tags=explicit_tags,
        hide_title=twitter_note, hide_meta=twitter_note,
    ) + "\n" + converted
    destination.write_text(content, encoding="utf-8", newline="\n")
    search_text = re.sub(r"\s+", " ", _searchable_text(f"{title}\n{converted}")).strip()
    return (
        tags,
        explicit_tags,
        source_relative.as_posix(),
        site_url,
        title,
        date,
        search_text,
        category,
        _reading_minutes(search_text),
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
        "note_id INTEGER PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, "
        "date TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE tag_documents ("
        "posting_bucket INTEGER NOT NULL, tag TEXT NOT NULL, note_id INTEGER NOT NULL, "
        "PRIMARY KEY(posting_bucket, tag, note_id)) WITHOUT ROWID"
    )
    # Explicit tags only — the ones eligible to become Hugo taxonomy terms.
    # Generated word tags never enter the taxonomy, so they are not recorded
    # here; they live in tag_documents with everything else.
    connection.execute(
        "CREATE TABLE explicit_tags ("
        "tag TEXT NOT NULL, note_id INTEGER NOT NULL, "
        "PRIMARY KEY(tag, note_id)) WITHOUT ROWID"
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
    documents: Iterable[tuple[int, str, str, str]],
    associations: Iterable[tuple[int, str, int]],
) -> None:
    connection.executemany(
        "INSERT INTO documents(note_id, url, title, date) VALUES (?, ?, ?, ?)",
        sorted(documents, key=lambda row: row[0]),
    )
    connection.executemany(
        "INSERT INTO tag_documents(posting_bucket, tag, note_id) VALUES (?, ?, ?)",
        sorted(associations),
    )


def _update_explicit_tags(
    connection: sqlite3.Connection, associations: Iterable[tuple[str, int]]
) -> None:
    connection.executemany(
        "INSERT OR IGNORE INTO explicit_tags(tag, note_id) VALUES (?, ?)",
        sorted(associations),
    )


def _rewrite_note_tags(path: Path, promoted: frozenset[str]) -> bool:
    """Drop demoted tags from one note's front matter. Returns True if changed.

    Front matter is a single JSON line, so this rewrites the first line and
    copies the body through untouched.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    first, separator, body = text.partition("\n")
    try:
        data = json.loads(first)
    except (ValueError, json.JSONDecodeError):
        return False
    tags = data.get("tags")
    if not isinstance(tags, list):
        return False
    kept = [tag for tag in tags if tag in promoted]
    if len(kept) == len(tags):
        return False
    if kept:
        data["tags"] = kept
    else:
        data.pop("tags")
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + separator + body,
        encoding="utf-8", newline="\n",
    )
    return True


def _apply_taxonomy_tag_cap(
    connection: sqlite3.Connection, content_root: Path, maximum: int
) -> tuple[int, int, int]:
    """Keep only the most frequent explicit tags in Hugo's taxonomy.

    Returns (distinct explicit tags, promoted, notes rewritten).

    Every taxonomy term is a generated page, so an archive with 50k distinct
    hashtags would add 50k pages to the build. The cap keeps that bounded.
    Demoted tags are not lost: they stay in the hashed posting index behind
    Browse Tags and in the Bluge index, so `tag:` still finds them.

    This runs after conversion because promotion needs global counts, which are
    only complete once every note has been read. Notes are rewritten rather than
    buffered because a vault's bodies do not fit in memory. Only the notes
    carrying a demoted tag are touched, so a vault under the cap pays nothing.
    """
    total = connection.execute(
        "SELECT COUNT(*) FROM (SELECT tag FROM explicit_tags GROUP BY tag)"
    ).fetchone()[0]
    if maximum == 0 or total <= maximum:
        return total, total, 0

    # Ties break by tag name so two runs of the same vault promote the same set.
    connection.execute("CREATE TEMP TABLE promoted_tags (tag TEXT PRIMARY KEY)")
    connection.execute(
        "INSERT INTO promoted_tags(tag) SELECT tag FROM explicit_tags "
        "GROUP BY tag ORDER BY COUNT(*) DESC, tag ASC LIMIT ?",
        (maximum,),
    )
    promoted = frozenset(
        row[0] for row in connection.execute("SELECT tag FROM promoted_tags")
    )
    rewritten = 0
    cursor = connection.execute(
        "SELECT DISTINCT documents.url FROM explicit_tags "
        "LEFT JOIN promoted_tags ON promoted_tags.tag = explicit_tags.tag "
        "JOIN documents ON documents.note_id = explicit_tags.note_id "
        "WHERE promoted_tags.tag IS NULL"
    )
    for (url,) in cursor:
        # The canonical URL is the generated content path with a .html suffix.
        relative = PurePosixPath(url.lstrip("/")).with_suffix(".md")
        if _rewrite_note_tags(content_root / Path(relative.as_posix()), promoted):
            rewritten += 1
    connection.execute("DROP TABLE promoted_tags")
    return total, len(promoted), rewritten


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
        for note_id, url, title, date in connection.execute(
            "SELECT note_id, url, title, date FROM documents ORDER BY note_id"
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
            json.dump(
                [str(url), str(title), str(date)[:10]],
                handle, ensure_ascii=False, separators=(",", ":"),
            )
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
                # 3: document chunk records carry a date as their third field.
                "version": 3,
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


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _theme_search_backend(search_backend: str) -> str:
    """Map the movenotes backend choice onto the theme's adapter name.

    ``both`` becomes the theme's ``auto`` adapter, which probes ``/api/health``
    and uses Bluge when the generated server answers and Pagefind when nothing
    does — one build that works whether or not the server is running, which is
    what ``both`` has always meant here.
    """
    return {"pagefind": "pagefind", "bluge": "bluge"}.get(search_backend, "auto")


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
    assets = output / "assets" / "js"
    for path in (
        content / "notes", layouts,
        static / "css", static / "js", assets,
    ):
        path.mkdir(parents=True, exist_ok=True)

    module = "" if copied_theme else f"""
[module]
  [[module.imports]]
    path = '{_LEDGER_THEME_MODULE}'
"""
    theme_line = f"theme = '{_LEDGER_THEME_NAME}'\n" if copied_theme else ""
    # Notes carry an explicit `url` ending in .html, so uglyURLs is unnecessary
    # for them and would only push the theme's own pages to /search.html, which
    # its templates do not link to. Auxiliary pages stay directory-style.
    # `locale`, not `languageCode`: Hugo deprecated the latter in v0.158.
    hugo_toml = f"""baseURL = {_toml_string(base_url)}
locale = {_toml_string(locale)}
title = {_toml_string(title)}
enableRobotsTXT = true
buildFuture = true
buildExpired = true
buildDrafts = true
# Terms are used verbatim in search queries (tag:codec), so they must not be
# title-cased for display.
capitalizeListTitles = false
{theme_line}
[taxonomies]
  category = 'categories'
  tag = 'tags'

[pagination]
  pagerSize = 20

# A feed of a six-figure archive is neither useful nor cheap to generate.
[services.rss]
  limit = 20

[markup]
  [markup.goldmark]
    [markup.goldmark.renderer]
      unsafe = true

[params]
  movenotesBuildId = {_toml_string(build_id)}
  movenotesSearchBackend = {_toml_string(search_backend)}
  mainSections = ['notes']
  defaultTheme = 'light'
  # A local archive should not reach out to a font CDN to render.
  googleFonts = false
  siteBlurb = ''
  # Above this many notes a category or tag routes to search instead of
  # rendering a paginated archive.
  taxonomyPageLimit = 25
  extraCSS = ['/css/movenotes-site.css']
  extraJS = ['/js/movenotes-nav.js']

  [params.pagination]
    home = 20
    term = 20
    search = 20
    tagsGrid = 60
    sidebarCategories = 7
    sidebarCategoriesMobile = 6
    sidebarTags = 9
    sidebarTagsMobile = 8

  [params.sidebar]
    width = 282
    minWidth = 190
    maxWidth = 460
    order = 'count'
    allNotesLabel = 'All notes'
    maxTerms = 200

  [params.post]
    # 100k striped placeholders are noise, not design.
    heroPlaceholder = false

  [params.search]
    backend = {_toml_string(_theme_search_backend(search_backend))}
    bundlePath = '/pagefind/pagefind.js'
    endpoint = '/api/search'
    healthEndpoint = '/api/health'

  # Both ceilings matter here: either surface can hold the whole archive.
  [params.scale]
    maxHomePagerPages = 500
    maxSectionPagerPages = 500

  [params.footer]
    rss = true
    sourceURL = ''

  [params.taxonomy]
    categoryPlural = 'categories'
    tagPlural = 'tags'

[outputs]
  home = ['html', 'rss']
  section = ['html']
  term = ['html']
{module}"""
    (output / "hugo.toml").write_text(hugo_toml, encoding="utf-8")
    if not copied_theme:
        (output / "go.mod").write_text(
            "module movenotes/generated-site\n\ngo 1.20\n", encoding="utf-8"
        )

    # Home is the theme's own view: a primed search bar over the newest notes,
    # capped by params.scale. It needs no body.
    (content / "_index.md").write_text(
        json.dumps(
            {"title": title, "date": generated_at, "lastmod": generated_at},
            ensure_ascii=False, separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
    )
    (content / "about.md").write_text(
        json.dumps({
            "title": "Getting Started",
            "layout": "about",
            "url": "/about/",
            "date": generated_at,
            "lastmod": generated_at,
        }, ensure_ascii=False, separators=(",", ":"))
        + "\n" + _getting_started_body(search_backend),
        encoding="utf-8",
    )
    (content / "search.md").write_text(
        json.dumps({
            "title": "Search",
            "layout": "search",
            "url": "/search/",
            "date": generated_at,
        }, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    # Browse Tags lists every generated word tag from the disk-backed posting
    # index, which is a different set from the Hugo tag taxonomy behind /tags/.
    (content / "browse-tags.md").write_text(
        json.dumps({
            "title": "Browse Tags",
            "layout": "browse-tags",
            "url": "/browse-tags/",
            "date": generated_at,
        }, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    (content / "notes" / "_index.md").write_text(
        json.dumps({"title": "Notes", "date": generated_at}, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    # No shortcodes at all: /search/ is the theme's own view, driven by its
    # grammar and its Pagefind/Bluge adapters; Getting Started is prose in
    # about.md; and Browse Tags needs the asset pipeline, so its body belongs in
    # a layout rather than a shortcode.
    (layouts / "browse-tags.html").write_text(
        _BROWSE_TAGS_LAYOUT.replace("@@TAGS_BODY@@", _tags_body()),
        encoding="utf-8",
    )
    # An assets/ module rather than a static file: it imports the theme's
    # paging.js through Hugo's asset pipeline, so the page-number windowing rule
    # is the theme's one implementation and not a copy of it.
    (assets / "movenotes-tags.js").write_text(_TAGS_SCRIPT, encoding="utf-8")
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
        # No exclude_selectors: the theme scopes indexing with a single
        # data-pagefind-body on note articles, so the shell and the standalone
        # pages are already out of the index.
        pagefind_config.write_text(
            "site: public\noutput_path: public/pagefind\nkeep_index_url: false\n",
            encoding="utf-8",
        )
    else:
        pagefind_config.unlink(missing_ok=True)
    # public/ and the Bluge index are build outputs, so they are ignored here —
    # but a Git-based Vercel deployment of a large archive needs them committed,
    # because the alternative is rebuilding a six-figure archive inside a
    # 45-minute build. DEPLOY_VERCEL.md says which case is which.
    (output / ".gitignore").write_text(
        "/public/\n/resources/\n.hugo_build.lock\n/server/bluge-index/\n"
        "/server/bluge-index.building/\n/server/bluge-index.stamp.json\n"
        "/server/movenotes-site-server\n/.vercel/\n",
        encoding="utf-8",
    )


_BROWSE_TAGS_LAYOUT = r'''{{ define "main" }}
{{- /* Generated by obsidian2site.py. Browse Tags is a movenotes view, not one of
       the theme's: it reads the hashed posting index under static/movenotes/,
       which holds every tag, including every generated content word. The theme's
       /tags/ grid shows the Hugo tag taxonomy, which is the smaller set of the
       most frequent written tags. */ -}}
<div class="ledger-heading">
  <span class="ledger-eyebrow">movenotes</span>
  <h1>{{ .Title }}</h1>
</div>
{{ with .Content }}<div class="ledger-prose">{{ . }}</div>{{ end }}
@@TAGS_BODY@@
{{ end }}
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

_GETTING_STARTED_BODY = r'''A reading interface for a very large Obsidian vault.
No note is ever listed in the navigation, and no page grows with the size of the
archive, so the site stays responsive past 100,000 notes.

<div class="movenotes-start-grid">
  <a class="movenotes-start-card" data-card href="/search/">
    <strong>Search</strong>
    <small>@@SEARCH_CARD@@</small>
  </a>
  <a class="movenotes-start-card" data-card href="/browse-tags/">
    <strong>Browse tags</strong>
    <small>Every tag in the archive — the ones written in notes and every unique
    content word — with the exact notes each one carries.</small>
  </a>
</div>

## Finding notes

Sidebar categories and tags open an archive when the term is small enough to
render one, and the search page when it is not. The search box accepts:

| query | meaning |
|---|---|
| `canadian housing` | both words, anywhere in the note |
| `"Bank of Canada"` | that exact phrase |
| `category:Twitter` | one category; quote a name containing a space |
| `tag:economics` | one tag; repeat it to require several |
| `since:2026-07-01 until:2026-08-01` | July, by note date — `until:` is exclusive |

@@SYNTAX_NOTE@@

## Two kinds of tag

A note's tags are the tags written in it plus every unique non-filler word it
contains. The most frequent written tags become ordinary site tags, with their
own archive pages, and appear in the sidebar. All of them — including every
content word — stay on **Browse tags**, whose counts come from the same posting
lists that produce its results.

## Links and attachments

Links between notes are ordinary static links. Attachments are copied into
`static/vault-assets`.
'''

_SEARCH_CARD_BLUGE = (
    "Server-side search over the whole archive. Only the result page you are "
    "looking at crosses the connection."
)
_SEARCH_CARD_PAGEFIND = (
    "Static browser-side search. Only the index fragments a query touches are "
    "downloaded."
)
_SEARCH_CARD_BOTH = (
    "Server-side search when the generated Go server is running, with static "
    "Pagefind search as the fallback."
)
_SYNTAX_NOTE_PAGEFIND = (
    "Date bounds need the Bluge backend. On a statically hosted site the search "
    "page says so rather than quietly ignoring them."
)
_SYNTAX_NOTE_BLUGE = "Every clause above is answered by the Bluge server."


def _getting_started_body(search_backend: str) -> str:
    """Markdown for the Getting Started page.

    Plain Markdown in `content/about.md` rather than a shortcode: a `{{< >}}`
    shortcode's output is not run through the Markdown renderer, and this page is
    prose. Only the two cards are inline HTML, which goldmark passes through.
    """
    card = {
        "bluge": _SEARCH_CARD_BLUGE,
        "pagefind": _SEARCH_CARD_PAGEFIND,
    }.get(search_backend, _SEARCH_CARD_BOTH)
    note = (
        _SYNTAX_NOTE_PAGEFIND if search_backend == "pagefind"
        else _SYNTAX_NOTE_BLUGE
    )
    return (
        _GETTING_STARTED_BODY
        .replace("@@SEARCH_CARD@@", card)
        .replace("@@SYNTAX_NOTE@@", note)
    )


_TAGS_SCRIPT = r'''/* Browse Tags: the movenotes tag index, in two modes.

   Without ?tag=, a filterable list of tags read from bucketed static JSON.
   With ?tag=, the exact set of notes carrying that tag, read from the hashed
   posting index and the chunked document metadata.

   Why this exists next to the theme's own search: a note's tags are the union of
   its explicit tags and every unique non-filler word in it, which is far more
   terms than a Hugo taxonomy can hold. Only the most frequent explicit tags
   become taxonomy terms, and Pagefind can only filter on those. This page
   answers for every tag, and its counts come from the same posting lists that
   produce the badges — so the number on a tag and the number of results it
   opens are the same number by construction.

   windowPages comes from the theme, deliberately: the "page 1, current ±1, last"
   rule is already implemented three times there and a fourth copy would drift. */

import { windowPages } from './search/paging.js';

var root = document.querySelector('[data-movenotes-tags]');
if (root) init(root);

function init(root) {
  var config = JSON.parse(root.querySelector('[data-movenotes-tags-config]').textContent);
  var browser = root.querySelector('[data-movenotes-tag-browser]');
  var filter = root.querySelector('[data-movenotes-tag-filter]');
  var grid = root.querySelector('[data-movenotes-tag-grid]');
  var browserStatus = root.querySelector('[data-movenotes-tag-status]');
  var results = root.querySelector('[data-movenotes-tag-results]');
  var resultsHeading = root.querySelector('[data-movenotes-tag-heading]');
  var resultsCount = root.querySelector('[data-movenotes-tag-count]');
  var resultsList = root.querySelector('[data-movenotes-tag-list]');
  var resultsPager = root.querySelector('[data-movenotes-tag-pager]');

  var cache = new Map();
  var manifest = null;
  var token = 0;

  /* Both bucket functions mirror obsidian2site.py exactly. They decide which
     file to fetch, so a difference here is a 404, not a wrong answer. */
  function displayBucket(value) {
    var chars = Array.from(value.normalize('NFKD').toLowerCase())
      .filter(function (character) { return /[\p{L}\p{N}]/u.test(character); });
    if (!chars.length) return '__';
    if (/^[a-z0-9]$/.test(chars[0])) {
      return (chars.filter(function (c) { return /^[a-z0-9]$/.test(c); }).join('') + '_').slice(0, 2);
    }
    return 'u' + chars[0].codePointAt(0).toString(16);
  }

  function postingBucket(value) {
    var hash = 0x811c9dc5;
    var bytes = new TextEncoder().encode(value);
    for (var i = 0; i < bytes.length; i++) {
      hash ^= bytes[i];
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return (hash & (config.postingBuckets - 1)).toString(16).padStart(3, '0');
  }

  function loadJson(url) {
    if (!cache.has(url)) {
      cache.set(url, fetch(url).then(function (response) {
        if (!response.ok) throw new Error(response.status + ' ' + response.statusText);
        return response.json();
      }));
    }
    return cache.get(url);
  }

  function currentTag() {
    return (new URLSearchParams(location.search).get('tag') || '').trim().toLowerCase();
  }

  function currentPage() {
    return parseInt(new URLSearchParams(location.search).get('page'), 10) || 1;
  }

  /* ── Tag browser ──────────────────────────────────────────────────────── */

  function renderTags(rows, label) {
    grid.textContent = '';
    var fragment = document.createDocumentFragment();
    rows.slice(0, config.maxTagsShown).forEach(function (row) {
      var cell = document.createElement('a');
      cell.className = 'ledger-grid-cell';
      cell.href = config.pageURL + '?tag=' + encodeURIComponent(row[0]);
      var name = document.createElement('span');
      name.className = 'ledger-grid-name';
      name.textContent = '#' + row[0];
      var count = document.createElement('span');
      count.className = 'ledger-grid-count';
      count.textContent = Number(row[1]).toLocaleString();
      var hint = document.createElement('span');
      hint.className = 'ledger-sr-only';
      hint.textContent = ' notes';
      count.appendChild(hint);
      cell.append(name, count);
      fragment.appendChild(cell);
    });
    grid.appendChild(fragment);
    var total = rows.length;
    browserStatus.textContent = label + ': ' + total.toLocaleString() +
      (total === 1 ? ' tag' : ' tags') +
      (total > config.maxTagsShown
        ? ' · showing the first ' + config.maxTagsShown.toLocaleString()
        : '');
  }

  async function updateBrowser() {
    var mine = ++token;
    var query = filter.value.trim().toLowerCase();
    try {
      if (!query) {
        var top = await loadJson(config.tagsBase + 'top.json');
        if (mine === token) renderTags(top, 'Most frequent');
        return;
      }
      if (query.length < 2) {
        grid.textContent = '';
        browserStatus.textContent =
          'Type at least two characters, or clear the field for the most frequent tags.';
        return;
      }
      manifest = manifest || await loadJson(config.tagsBase + 'manifest.json');
      var bucket = displayBucket(query);
      var rows = Object.prototype.hasOwnProperty.call(manifest.buckets, bucket)
        ? await loadJson(config.tagsBase + bucket + '.json')
        : [];
      if (mine !== token) return;
      renderTags(
        rows.filter(function (row) { return row[0].indexOf(query) !== -1; }),
        'Tags matching “' + query + '”'
      );
    } catch (error) {
      browserStatus.textContent = 'The tag index is unavailable.';
      if (window.console) console.error('[movenotes] tag index:', error);
    }
  }

  /* ── Exact-tag results ────────────────────────────────────────────────── */

  function card(url, title, date) {
    var link = document.createElement('a');
    link.className = 'ledger-card';
    link.setAttribute('data-card', '');
    link.href = url;
    var heading = document.createElement('h3');
    heading.className = 'ledger-card-title';
    heading.textContent = title;
    link.appendChild(heading);
    var meta = document.createElement('div');
    meta.className = 'ledger-card-meta';
    var spacer = document.createElement('span');
    spacer.className = 'ledger-spacer';
    spacer.style.minWidth = '8px';
    meta.appendChild(spacer);
    var when = document.createElement('span');
    when.className = 'ledger-card-date';
    when.textContent = date || '';
    meta.appendChild(when);
    link.appendChild(meta);
    return link;
  }

  function pager(tag, page, pages) {
    var nav = document.createElement('nav');
    nav.className = 'ledger-pagination';
    nav.setAttribute('aria-label', 'Pagination');

    function step(label, target, disabled) {
      var node = document.createElement(disabled ? 'span' : 'a');
      node.className = 'ledger-page-step';
      node.textContent = label;
      if (disabled) node.setAttribute('aria-disabled', 'true');
      else node.href = pageHref(tag, target);
      return node;
    }

    nav.appendChild(step('‹ Prev', page - 1, page <= 1));
    windowPages(page, pages).forEach(function (number) {
      if (number === null) {
        var gap = document.createElement('span');
        gap.className = 'ledger-page-gap';
        gap.textContent = '…';
        gap.setAttribute('aria-hidden', 'true');
        nav.appendChild(gap);
        return;
      }
      var link = document.createElement('a');
      link.className = 'ledger-page-number';
      link.href = pageHref(tag, number);
      link.textContent = String(number);
      if (number === page) link.setAttribute('aria-current', 'page');
      nav.appendChild(link);
    });
    nav.appendChild(step('Next ›', page + 1, page >= pages));
    return nav;
  }

  function pageHref(tag, page) {
    var query = '?tag=' + encodeURIComponent(tag) + (page > 1 ? '&page=' + page : '');
    return config.pageURL + query;
  }

  async function showResults(tag, page) {
    var mine = ++token;
    browser.hidden = true;
    results.hidden = false;
    resultsHeading.textContent = '#' + tag;
    resultsCount.textContent = 'Loading the exact tag index…';
    resultsList.textContent = '';
    resultsPager.textContent = '';
    try {
      manifest = manifest || await loadJson(config.tagsBase + 'manifest.json');
      var bucket = postingBucket(tag);
      var ids = [];
      if (Object.prototype.hasOwnProperty.call(manifest.posting_buckets || {}, bucket)) {
        var postings = await loadJson(config.postingsBase + bucket + '.json');
        ids = postings[tag] || [];
      }
      if (mine !== token) return;

      var pages = Math.max(1, Math.ceil(ids.length / config.perPage));
      page = Math.min(Math.max(1, page), pages);
      resultsCount.textContent = ids.length.toLocaleString() +
        (ids.length === 1 ? ' note' : ' notes') +
        (pages > 1 ? ' · page ' + page + ' of ' + pages.toLocaleString() : '');
      if (!ids.length) {
        resultsList.appendChild(emptyState(tag));
        return;
      }

      /* Only this page's note IDs are resolved, and only the chunks they fall
         in are fetched — the whole point of chunking the metadata. */
      var slice = ids.slice((page - 1) * config.perPage, page * config.perPage);
      var chunkSize = Number(manifest.document_chunk_size || 512);
      var wanted = {};
      slice.forEach(function (id) { wanted[Math.floor(Number(id) / chunkSize)] = true; });
      var chunks = new Map();
      await Promise.all(Object.keys(wanted).map(async function (chunk) {
        var name = Number(chunk).toString(16).padStart(6, '0');
        chunks.set(Number(chunk), await loadJson(config.documentsBase + name + '.json'));
      }));
      if (mine !== token) return;

      var fragment = document.createDocumentFragment();
      slice.forEach(function (id) {
        var record = (chunks.get(Math.floor(Number(id) / chunkSize)) || {})[String(id)];
        if (!record) return;
        fragment.appendChild(card(record[0], record[1] || record[0], record[2]));
      });
      resultsList.appendChild(fragment);
      if (pages > 1) resultsPager.appendChild(pager(tag, page, pages));
    } catch (error) {
      resultsCount.textContent = 'The tag index is unavailable.';
      if (window.console) console.error('[movenotes] exact tag:', error);
    }
  }

  function emptyState(tag) {
    var wrapper = document.createElement('div');
    wrapper.className = 'ledger-empty';
    var title = document.createElement('p');
    title.className = 'ledger-empty-title';
    title.textContent = 'No notes carry the tag “' + tag + '”';
    wrapper.appendChild(title);
    return wrapper;
  }

  function route() {
    var tag = currentTag();
    if (tag) {
      showResults(tag, currentPage());
    } else {
      browser.hidden = false;
      results.hidden = true;
      updateBrowser();
    }
  }

  var timer;
  filter.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(updateBrowser, 160);
  });
  filter.form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearTimeout(timer);
    updateBrowser();
  });
  window.addEventListener('popstate', route);
  route();
}
'''


_TAGS_BODY = r'''{{- $script := resources.Get "js/movenotes-tags.js" | js.Build (dict
      "targetPath" "js/movenotes-tags.js"
      "format" "esm"
      "minify" hugo.IsProduction) -}}
{{- if hugo.IsProduction }}{{ $script = $script | fingerprint }}{{ end -}}
{{- $config := dict
      "tagsBase"       ("/movenotes/tags/" | relURL)
      "postingsBase"   ("/movenotes/tag-postings/" | relURL)
      "documentsBase"  ("/movenotes/documents/" | relURL)
      "pageURL"        ("/browse-tags/" | relURL)
      "postingBuckets" @@POSTING_BUCKETS@@
      "perPage"        (site.Params.pagination.search | default 20)
      "maxTagsShown"   300
-}}
<div class="movenotes-tags" data-movenotes-tags>
  <script type="application/json" data-movenotes-tags-config>{{ $config | jsonify | safeJS }}</script>

  <div data-movenotes-tag-browser>
    <p class="ledger-prose-lead">Every tag in the archive: the tags written in a
    note plus every unique content word. Counts come from the same posting lists
    the results do.</p>

    {{- /* The theme's search-bar classes, its own data attributes deliberately
           not reused: this filter is not the site search and must not be driven
           by the theme's search controller. */ -}}
    <div class="ledger-searchbar">
      <form class="ledger-searchbar-row" role="search" onsubmit="return false">
        <div class="ledger-searchbar-field" data-card>
          <span class="ledger-searchbar-glyph" aria-hidden="true">&#x2315;</span>
          <label class="ledger-sr-only" for="movenotes-tag-filter">Find a tag</label>
          <input class="ledger-searchbar-input" id="movenotes-tag-filter" type="search"
                 placeholder="Filter tags — type at least two characters"
                 autocomplete="off" spellcheck="false" data-movenotes-tag-filter>
        </div>
      </form>
      <div class="ledger-meta">
        <span class="ledger-meta-count" role="status" aria-live="polite"
              data-movenotes-tag-status>Loading the most frequent tags…</span>
      </div>
    </div>

    <div class="ledger-grid" data-movenotes-tag-grid></div>
  </div>

  <div data-movenotes-tag-results hidden>
    <div class="ledger-heading">
      <span class="ledger-eyebrow">exact tag</span>
      {{- /* h2, not h1: these results are a section of this page, whose h1 is
             its title. */ -}}
      <h2 data-movenotes-tag-heading></h2>
      <span class="ledger-heading-meta" role="status" aria-live="polite"
            data-movenotes-tag-count></span>
    </div>
    <p><a class="ledger-post-back" href="{{ "/browse-tags/" | relURL }}">&larr; all tags</a></p>
    <div class="ledger-results" data-movenotes-tag-list></div>
    <div data-movenotes-tag-pager></div>
  </div>

  <noscript>
    <p class="ledger-page-ceiling">Browsing tags needs JavaScript, because the
    tag index is fetched one bucket at a time rather than built into every page.
    <a href="{{ "/search/" | relURL }}">Search</a> works without it.</p>
  </noscript>
</div>
<script type="module" src="{{ $script.RelPermalink }}"></script>
'''


def _tags_body() -> str:
    """The Browse Tags body, for the generated layout.

    No Pagefind opt-out markers anywhere in it: the theme scopes indexing to note
    articles with a single data-pagefind-body, so this page is outside the index
    whatever the backend.
    """
    return _TAGS_BODY.replace(
        "@@POSTING_BUCKETS@@", str(_TAG_POSTING_BUCKETS)
    )


_SITE_CSS = r'''/* movenotes additions to the Ledger theme.

   Everything the theme already provides is used as-is — result cards, the tag
   grid, headings, pagers, the search bar — so this file only styles what the
   theme has no equivalent for. It is loaded through params.extraCSS, after the
   theme's stylesheet, and uses the theme's tokens so all three themes and the
   contrast palette keep working.

   Kept deliberately small: it is fetched on every page of the archive. */

.ledger-prose-lead {
  margin: 0 0 var(--gap-result, 14px);
  font: 400 15px/1.6 var(--font-sans);
  color: var(--dim);
}

/* Getting Started: two cards pointing at the two ways in. */
.movenotes-start-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  margin: 0 0 22px;
}

.movenotes-start-card {
  display: block;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--r-card);
  background: var(--panel2);
  color: inherit;
  text-decoration: none;
  transition: border-color .16s ease, background-color .16s ease;
}

.movenotes-start-card:hover {
  border-color: var(--accent);
  background: var(--hover);
}

.movenotes-start-card strong {
  display: block;
  margin-bottom: 4px;
  font: 600 14px/1.4 var(--font-sans);
}

.movenotes-start-card small {
  display: block;
  font: 400 12px/1.55 var(--font-mono);
  color: var(--dim);
}

/* Browse Tags result cards have a title and a date and no body text, because
   that is all the exact-tag index stores. Pull the meta row up so the card does
   not look like a card with something missing. */
[data-movenotes-tag-list] .ledger-card-meta {
  margin-top: 6px;
}

@media (prefers-reduced-motion: reduce) {
  .movenotes-start-card { transition: none; }
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


# Vercel's own limits, from https://vercel.com/docs/limits and
# https://vercel.com/docs/functions/limitations. They decide which deployment
# shape an archive of a given size can use at all, so the generator reports
# against them rather than leaving it to be discovered on a failed deploy.
_VERCEL_MAX_SOURCE_FILES = 15_000
_VERCEL_MAX_UPLOAD_BYTES_HOBBY = 100 * 1024 * 1024
_VERCEL_MAX_UPLOAD_BYTES_PRO = 1024 * 1024 * 1024
_VERCEL_MAX_FUNCTION_BYTES = 250 * 1024 * 1024

_VERCEL_API_SEARCH = '''// Vercel function: GET /api/search.
//
// Generated by obsidian2site.py. The whole implementation lives in the server
// module beside it; this file exists because Vercel's Go runtime turns each
// exported http.HandlerFunc under api/ into a function, and needs go.mod at the
// project root.
//
// The CDN serves public/, so nothing here touches static files: a generated
// archive's public/ is far larger than any function bundle limit.
package handler

import (
	"net/http"
	"sync"

	"movenotes/site-server/search"
)

var (
	once    sync.Once
	service *search.Service
)

// shared returns the per-instance service. Configuration comes from the
// environment, because a deployment has no command line, and the index is opened
// on the first request that needs it.
func shared() *search.Service {
	once.Do(func() { service = search.New(search.Config{}) })
	return service
}

// Search answers GET /api/search.
func Search(w http.ResponseWriter, r *http.Request) {
	shared().Search(w, r)
}
'''

_VERCEL_API_HEALTH = '''// Vercel function: GET /api/health. Generated by obsidian2site.py.
package handler

import "net/http"

// Health answers GET /api/health.
//
// The theme's `auto` search backend probes this to decide whether a server is
// answering at all. It answers 503 when the index is missing rather than
// reporting a healthy backend with nothing behind it.
func Health(w http.ResponseWriter, r *http.Request) {
	shared().Health(w, r)
}
'''

_VERCEL_ROOT_GO_MOD_HEADER = '''// Generated by obsidian2site.py. Vercel's Go runtime looks for go.mod at the
// project root; the implementation stays in server/, reached with a local
// replace so there is one copy of it.
//
// The requirements below are the server module's, rewritten as indirect: the
// root module contains only the api/ wrappers, and everything they need comes
// through that module. Derived from server/go.mod at generation time so the two
// cannot drift.
module movenotes/site

go {go_version}

require movenotes/site-server v0.0.0

replace movenotes/site-server => ./server
'''


def _vercel_root_go_mod(server_go_mod: str) -> str:
    """Build the root module file from the server module's.

    A `go build` at the project root has to be able to resolve every package it
    reaches, which for a module whose only code is two wrappers means listing the
    whole transitive set as indirect. Copying it from the server module keeps one
    source of truth; hard-coding nineteen dependencies here would rot.
    """
    version = "1.20"
    requirements: list[str] = []
    for line in server_go_mod.splitlines():
        stripped = line.strip()
        if stripped.startswith("go ") and len(stripped.split()) == 2:
            version = stripped.split()[1]
            continue
        if not stripped or stripped.startswith(("module ", ")", "//", "replace ")):
            continue
        # `require path version` and `require (` both start with require; only the
        # single-line form carries a requirement, and dropping it silently is how
        # the direct dependency went missing the first time.
        if stripped.startswith("require"):
            stripped = stripped[len("require"):].strip()
            if not stripped or stripped == "(":
                continue
        # Every requirement is indirect from the root module's point of view.
        requirement = stripped.split("//", 1)[0].strip()
        if requirement:
            requirements.append(f"\t{requirement} // indirect")
    header = _VERCEL_ROOT_GO_MOD_HEADER.format(go_version=version)
    if not requirements:
        return header
    return header + "\nrequire (\n" + "\n".join(sorted(requirements)) + "\n)\n"

_VERCEL_IGNORE = '''# Generated by obsidian2site.py.
#
# Vercel counts uploaded *source* files against a 15,000-file limit, so the Hugo
# inputs stay out of the deployment: the site is built before deploying, and only
# the built output, the search index and the functions are needed.
content/
themes/
layouts/
assets/
static/
resources/
.hugo_build.lock
hugo.toml
pagefind.yml
.movenotes-static-site.json

# The JSONL is the index's *source*. Functions never read it — they never build —
# and on a large archive it is bigger than the index itself.
server/search-source.jsonl
server/bluge-index.stamp.json
server/movenotes-site-server
'''


def _vercel_json(search_backend: str) -> str:
    """The deployment configuration.

    No build command: the site is built locally, because building on Vercel means
    Hugo, Pagefind and the Bluge index inside one 45-minute build. Static files
    come from public/; the index rides along with the functions through
    includeFiles.
    """
    config: dict[str, object] = {
        "$schema": "https://openapi.vercel.sh/vercel.json",
        "outputDirectory": "public",
        "trailingSlash": False,
    }
    if search_backend != "pagefind":
        config["functions"] = {
            "api/*.go": {
                # The index is data, not code, so it has to be named explicitly.
                # Verify after the first deploy that it arrived: /api/health
                # answers 503 with the path it looked for when it did not.
                "includeFiles": "server/bluge-index/**",
                "maxDuration": 30,
            }
        }
    return json.dumps(config, indent=2) + "\n"


def _write_vercel_project(output: Path, *, search_backend: str) -> None:
    (output / "vercel.json").write_text(
        _vercel_json(search_backend), encoding="utf-8"
    )
    ignore = _VERCEL_IGNORE
    if search_backend == "pagefind":
        # Any go.mod here belongs to Hugo's module mode, not to us, and a root
        # go.mod is exactly what makes Vercel's Go runtime detect a Go project.
        # A static deployment must not ship one.
        ignore += "\n# Hugo's module file; a static deployment has no Go in it.\ngo.mod\ngo.sum\n"
    (output / ".vercelignore").write_text(ignore, encoding="utf-8")
    if search_backend == "pagefind":
        # Static only: no Go, no functions, nothing to configure.
        return
    api = output / "api"
    api.mkdir(parents=True, exist_ok=True)
    (api / "search.go").write_text(_VERCEL_API_SEARCH, encoding="utf-8")
    (api / "health.go").write_text(_VERCEL_API_HEALTH, encoding="utf-8")
    (output / "go.mod").write_text(
        _vercel_root_go_mod(
            (output / "server" / "go.mod").read_text(encoding="utf-8")
        ),
        encoding="utf-8",
    )
    # The root module builds the same dependency set as the server module, so its
    # checksums are the server module's.
    shutil.copyfile(output / "server" / "go.sum", output / "go.sum")


def _directory_size(path: Path) -> tuple[int, int]:
    """Return (bytes, files) under path, following no symlinks."""
    total = 0
    files = 0
    for entry in path.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
            files += 1
    return total, files


def _vercel_readiness(output: Path, search_backend: str) -> list[str]:
    """Measure the generated site against Vercel's limits.

    Every one of these is a hard platform limit that turns into a failed deploy
    or a broken search page, and every one of them is only visible once the site
    has actually been built. Measuring beats guessing from a note count.
    """
    notes: list[str] = []
    public = output / "public"
    if public.is_dir():
        size, files = _directory_size(public)
        notes.append(
            f"built site: {files:,} files, {size / 1024 / 1024:.0f} MB"
        )
        if files > _VERCEL_MAX_SOURCE_FILES:
            notes.append(
                f"  ! {files:,} files exceeds Vercel's {_VERCEL_MAX_SOURCE_FILES:,}-file "
                "limit for a CLI deployment. Deploy from a Git repository "
                "instead, where the build container clones the project, or host "
                "the static site somewhere without a file-count limit."
            )
        if size > _VERCEL_MAX_UPLOAD_BYTES_PRO:
            notes.append(
                "  ! larger than the 1 GB source upload limit (Pro; 100 MB on "
                "Hobby). A CLI deployment of this site will be rejected."
            )
        elif size > _VERCEL_MAX_UPLOAD_BYTES_HOBBY:
            notes.append(
                "  ! larger than the 100 MB source upload limit on Hobby; needs "
                "Pro, Git deployment, or another host."
            )
    index = output / "server" / "bluge-index"
    if search_backend != "pagefind" and index.is_dir():
        size, _files = _directory_size(index)
        notes.append(f"Bluge index: {size / 1024 / 1024:.0f} MB")
        if size > _VERCEL_MAX_FUNCTION_BYTES:
            notes.append(
                f"  ! over Vercel's {_VERCEL_MAX_FUNCTION_BYTES // 1024 // 1024} MB "
                "function bundle limit, which the index has to fit inside along "
                "with the binary. Run Bluge on a host that keeps a process "
                "instead, and point params.search.endpoint at it — or publish "
                "statically with --search-backend pagefind."
            )
        elif size > _VERCEL_MAX_FUNCTION_BYTES * 3 // 4:
            notes.append(
                "  ! within 25% of the 250 MB function bundle limit; the compiled "
                "binary shares that budget."
            )
    return notes


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



_SEARCH_CONFIG_BACKEND_RE = re.compile(
    r'data-ledger-search-config[^>]*>\s*\{[^<]*?"backend"\s*:\s*"([a-z]+)"',
    re.IGNORECASE,
)
_PAGEFIND_RUNTIME_RE = re.compile(
    r'''(?:src|href)=["'][^"']*pagefind/[^"']*["']''', re.IGNORECASE
)


def _validate_built_search_backend(output: Path, search_backend: str) -> None:
    """Check the built site actually uses the search backend that was asked for.

    The theme selects its adapter from a JSON config embedded in every page that
    carries the search view, so that value — not a script filename — is what
    decides which index a visitor downloads. A `bluge` build that shipped
    `"backend":"pagefind"` would look fine and quietly load a browser index; a
    `both` build missing its Pagefind index would fall back to nothing.

    Relearn's Lunr filenames are gone from this check: the theme emits no
    built-in search runtime to suppress.
    """
    public = output / "public"
    expected = _theme_search_backend(search_backend)
    wrong_backend: list[str] = []
    pagefind_runtime: list[str] = []
    configured = 0
    for path in public.rglob("*.html"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _SEARCH_CONFIG_BACKEND_RE.finditer(text):
            configured += 1
            if match.group(1).casefold() != expected:
                wrong_backend.append(
                    f"{path.relative_to(public).as_posix()} ({match.group(1)})"
                )
        if search_backend == "bluge" and _PAGEFIND_RUNTIME_RE.search(text):
            pagefind_runtime.append(path.relative_to(public).as_posix())
    if wrong_backend:
        common.error(
            f"generated for --search-backend {search_backend} (theme backend "
            f"'{expected}') but the built pages configure: "
            + ", ".join(sorted(wrong_backend)[:10])
        )
    if pagefind_runtime:
        common.error(
            "Bluge-only build still references a browser search index in: "
            + ", ".join(sorted(pagefind_runtime)[:10])
        )
    if not configured:
        common.error(
            "no search view was built: expected the theme's search config on at "
            "least the /search/ page. Is the theme missing or out of date?"
        )
    # A build that will fall back to Pagefind needs the index it falls back to.
    if expected in {"pagefind", "auto"} and not (public / "pagefind").is_dir():
        common.error(
            f"theme backend '{expected}' needs a Pagefind index, but "
            f"{public / 'pagefind'} was not built"
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
    if args.search_backend in {"both", "pagefind"}:
        print("building Pagefind index...")
        subprocess.run(_pagefind_command(args, output), cwd=output, check=True)
    # After the indexes exist, not before: the check includes whether the index
    # the configured backend needs is actually there.
    _validate_built_search_backend(output, args.search_backend)
    if args.search_backend in {"both", "bluge"}:
        print("building Bluge site server...")
        go = shutil.which(args.go_bin) if os.path.sep not in args.go_bin else args.go_bin
        if not go:
            common.error(f"Go executable not found: {args.go_bin}")
        print("resolving Go module checksums...")
        subprocess.run([str(go), "mod", "tidy"], cwd=output / "server", check=True)
        subprocess.run(
            [str(go), "build", "-o", "movenotes-site-server", "./cmd/movenotes-site-server"],
            cwd=output / "server", check=True,
        )
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
    if args.ledger_theme is not None:
        theme_target = output / "themes" / _LEDGER_THEME_NAME
        if theme_target.exists():
            shutil.rmtree(theme_target)
        theme_target.parent.mkdir(parents=True, exist_ok=True)
        # No post-copy rewriting: Ledger tracks current Hugo template APIs, so a
        # checkout that does not build is a theme bug to fix in the theme.
        shutil.copytree(
            args.ledger_theme, theme_target,
            ignore=shutil.ignore_patterns(
                ".git", "node_modules", "public", "resources", "bench",
                "exampleSite", "tmp-corpus",
            ),
        )
        copied_theme = True

    _write_hugo_project(
        output,
        title=args.title or input_root.name,
        base_url=args.base_url,
        locale=args.locale,
        copied_theme=copied_theme,
        search_backend=args.search_backend,
    )
    if args.vercel:
        _write_vercel_project(output, search_backend=args.search_backend)
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
    pending_documents: list[tuple[int, str, str, str]] = []
    pending_tag_documents: list[tuple[int, str, int]] = []
    pending_explicit_tags: list[tuple[str, int]] = []
    pending_tag_notes = 0
    category_name = args.category_name or (args.title or input_root.name)
    maximum_taxonomy_tags = (
        _automatic_taxonomy_tag_cap(len(markdown_paths))
        if args.max_taxonomy_tags is None else args.max_taxonomy_tags
    )
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
                    category_mode=args.category_mode,
                    category_name=category_name,
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
                            explicit_tags,
                            _source,
                            site_url,
                            note_title,
                            note_date,
                            note_search_text,
                            note_category,
                            note_reading_minutes,
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
                    pending_documents.append((note_id, site_url, note_title, note_date))
                    # Every tag goes to Bluge, including the generated word
                    # tags and the ones the taxonomy cap left out: `tag:` in
                    # server-side search answers for all of them.
                    search_source.write(json.dumps({
                        "id": note_id,
                        "url": site_url,
                        "title": note_title,
                        "date": note_date,
                        "body": note_search_text,
                        "summary": note_search_text[:700],
                        "category": note_category,
                        "tags": tags,
                        # What a result card shows: the tags written in the note.
                        # `tags` above carries every generated content word too,
                        # so `tag:` finds them, but a card listing four random
                        # words looks like a bug — and storing all of them for
                        # display cost 23% of the Bluge index.
                        "displayTags": explicit_tags,
                        "readingTime": note_reading_minutes,
                    }, ensure_ascii=False, separators=(",", ":")) + "\n")
                    pending_tag_documents.extend(
                        (_tag_posting_bucket(tag), tag, note_id) for tag in tags
                    )
                    pending_explicit_tags.extend(
                        (tag, note_id) for tag in explicit_tags
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
                        _update_explicit_tags(tag_connection, pending_explicit_tags)
                        pending_tag_counts.clear()
                        pending_documents.clear()
                        pending_tag_documents.clear()
                        pending_explicit_tags.clear()
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
            _update_explicit_tags(tag_connection, pending_explicit_tags)
            pending_tag_counts.clear()
            pending_documents.clear()
            pending_tag_documents.clear()
            pending_explicit_tags.clear()
        tag_connection.commit()
        explicit_total, promoted_tags, demoted_notes = _apply_taxonomy_tag_cap(
            tag_connection, output / "content", maximum_taxonomy_tags
        )
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
    if explicit_total:
        published = (
            f"{promoted_tags:,} of {explicit_total:,} explicit tag(s) published as "
            "Hugo taxonomy terms"
        )
        if promoted_tags < explicit_total:
            chosen = (
                "" if args.max_taxonomy_tags is not None
                else f" (automatic cap for {processed:,} note(s))"
            )
            print(
                f"{published}{chosen}; the other {explicit_total - promoted_tags:,} "
                f"stay searchable through the tag index and Bluge "
                f"({demoted_notes:,} note(s) rewritten)"
            )
        else:
            print(published)
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
        if args.vercel:
            print("Vercel deployment readiness:")
            for line in _vercel_readiness(output, args.search_backend):
                print(f"  {line}")
        if args.search_backend in {"both", "bluge"}:
            print(f"serve with '{server_command}'")
        elif args.search_backend == "pagefind":
            print(f"serve static files with 'python3 -m http.server 8080 --directory {output / 'public'}'")
    else:
        print(f"run 'hugo --source {output}'")
        if args.search_backend in {"both", "bluge"}:
            print(
                f"then build the server with 'cd {output / 'server'} && "
                f"{args.go_bin} mod tidy && {args.go_bin} build -o movenotes-site-server "
                "./cmd/movenotes-site-server'"
            )
            print(f"and serve with '{server_command}'")
        if args.search_backend in {"both", "pagefind"}:
            print(f"for static hosting fallback, run 'npx -y pagefind --site {output / 'public'}'")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
