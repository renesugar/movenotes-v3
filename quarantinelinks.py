#!/usr/bin/env python3
"""Quarantine checked image-report items with a local replacement resource.

Run images2resources.py first, review its Markdown report, and change selected
checkboxes from ``[ ]`` to ``[x]``. This script replaces only those exact image
occurrences in the SQLite note bodies with a Joplin resource link to a local
"Image removed" attachment. The resource ID/path are saved in the INI file and
reused on later runs.
"""

from __future__ import annotations

import argparse
import collections
import sys
import urllib.parse
from pathlib import Path

import common
import constants
import image_resources
import notesdb

__program_name__ = "quarantinelinks"
__version__ = "1.10"


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=__program_name__, description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--input",
        dest="input_path",
        type=common.existing_dir,
        required=True,
        help="Path to the SQLite notes directory",
    )
    parser.add_argument(
        "--report",
        dest="report_path",
        type=Path,
        help=(
            "Markdown report produced by images2resources.py. Optional when "
            "quarantine_domains is configured."
        ),
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        type=Path,
        help=(
            "INI configuration file (default: <input>/"
            f"{image_resources.DEFAULT_CONFIG_FILENAME})"
        ),
    )
    parser.add_argument(
        "--replacement-image",
        dest="replacement_image",
        type=Path,
        help="PNG/JPEG/GIF/WebP/BMP/TIFF/ICO/AVIF/HEIC/SVG replacement image",
    )
    return parser


def _resolved_path(value: Path, base: Path) -> Path:
    path = value.expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _resource_is_usable(sqlconn, input_path: Path, resource_id: str, configured_file: str) -> bool:  # noqa: ANN001
    if not resource_id:
        return False
    row = sqlconn.execute(
        "SELECT joplin_type_ FROM notes WHERE joplin_id = ?", (resource_id,)
    ).fetchone()
    if row is None or row["joplin_type_"] != int(constants.JoplinType.RESOURCE):
        return False
    if configured_file:
        path = Path(configured_file)
        if not path.is_absolute():
            path = input_path / path
        if path.is_file():
            return True
    return any((input_path / "resources").glob(f"{resource_id}.*"))


def _replacement_resource_metadata(
    sqlconn, input_path: Path, resource_id: str, configured_file: str
) -> tuple[str, str, str] | None:  # noqa: ANN001
    candidate_id = resource_id.strip()
    if not candidate_id and configured_file.strip():
        candidate_id = Path(configured_file.strip()).stem.split(".", 1)[0]
    if not candidate_id:
        return None
    row = sqlconn.execute(
        "SELECT joplin_mime, joplin_file_extension FROM notes "
        "WHERE joplin_id = ? AND joplin_type_ = ? ORDER BY note_id LIMIT 1",
        (candidate_id, int(constants.JoplinType.RESOURCE)),
    ).fetchone()
    if row is None:
        return None
    path: Path | None = None
    if configured_file.strip():
        configured = Path(configured_file.strip())
        path = configured if configured.is_absolute() else input_path / configured
        if not path.is_file():
            path = None
    if path is None:
        matches = sorted((input_path / "resources").glob(f"{candidate_id}.*"))
        path = matches[0] if matches else None
    if path is None:
        return None
    try:
        relative = path.relative_to(input_path).as_posix()
    except ValueError:
        relative = str(path)
    mime = str(row["joplin_mime"] or "").strip()
    if not mime:
        mime = image_resources.sniff_image_mime(path.read_bytes()) or "application/octet-stream"
    return candidate_id, relative, mime


def _find_domain_replacements(sqlconn, domains: set[str]):  # noqa: ANN001
    resolved: dict[int, tuple[object, list[tuple[int, int]]]] = {}
    matched = 0
    if not domains:
        return resolved, matched
    query = (
        "SELECT * FROM notes WHERE joplin_type_ = ? AND note_data_format = ? "
        "AND (instr(note_data, 'http://') > 0 OR instr(note_data, 'https://') > 0) "
        "ORDER BY note_id"
    )
    for row in sqlconn.execute(
        query, (int(constants.JoplinType.NOTE), "text/markdown")
    ):
        positions: list[tuple[int, int]] = []
        links, _malformed = image_resources.scan_markdown_images(row["note_data"] or "")
        for link in links:
            if not link.destination.lower().startswith(("http://", "https://")):
                continue
            host = urllib.parse.urlsplit(link.destination).hostname
            if image_resources.host_matches_domains(host, domains):
                positions.append((link.start, link.end))
                matched += 1
        if positions:
            resolved[row["note_id"]] = (row, positions)
    return resolved, matched


def _merge_resolved(target, source) -> None:  # noqa: ANN001
    for note_id, (row, positions) in source.items():
        if note_id not in target:
            target[note_id] = (row, list(positions))
            continue
        existing_row, existing_positions = target[note_id]
        known = set(existing_positions)
        existing_positions.extend(position for position in positions if position not in known)
        target[note_id] = (existing_row, existing_positions)


def _load_replacement_bytes(
    config,
    config_path: Path,
    cli_replacement: Path | None,
) -> tuple[bytes, str, str, str | None]:  # noqa: ANN001
    source: Path | None = None
    if cli_replacement is not None:
        source = _resolved_path(cli_replacement, Path.cwd())
    else:
        configured = config["quarantine"].get("replacement_image", "").strip()
        if configured:
            source = _resolved_path(Path(configured), config_path.parent)

    if source is None:
        content = image_resources.built_in_removed_svg()
        return content, "image/svg+xml", "svg", None
    if not source.is_file():
        common.error(f"replacement image '{source}' does not exist")
    content = source.read_bytes()
    mime = image_resources.sniff_image_mime(content)
    if mime is None:
        common.error(f"replacement image '{source}' is not a recognised image")
    extension = image_resources.extension_for_mime(mime)
    if extension is None:
        common.error(f"replacement image MIME type '{mime}' is unsupported")
    return content, mime, extension, str(source)


def _find_selected_replacements(sqlconn, selected: list[dict]):  # noqa: ANN001
    """Resolve report metadata to current note offsets without changing data."""
    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for metadata in selected:
        grouped[str(metadata["note_id"])].append(metadata)

    resolved: dict[int, tuple[object, list[tuple[int, int]]]] = {}
    misses: list[str] = []
    for item_id, metadata_items in grouped.items():
        rows = sqlconn.execute(
            "SELECT * FROM notes WHERE joplin_id = ? OR note_uuid = ?",
            (item_id, item_id),
        ).fetchall()
        if len(rows) != 1:
            misses.extend(str(item.get("id", "unknown")) for item in metadata_items)
            continue
        row = rows[0]
        body = row["note_data"] or ""
        candidates = image_resources.quarantine_candidates(body)
        by_fingerprint: dict[str, list[image_resources.ImageLink]] = collections.defaultdict(list)
        for candidate in candidates:
            by_fingerprint[candidate.fingerprint].append(candidate)

        positions: list[tuple[int, int]] = []
        claimed: set[tuple[int, int]] = set()
        for metadata in metadata_items:
            fingerprint = str(metadata["fingerprint"])
            occurrence = int(metadata.get("occurrence", 1))
            matches = by_fingerprint.get(fingerprint, [])
            candidate = matches[occurrence - 1] if 0 < occurrence <= len(matches) else None
            if candidate is None or (candidate.start, candidate.end) in claimed:
                misses.append(str(metadata.get("id", "unknown")))
                continue
            claimed.add((candidate.start, candidate.end))
            positions.append((candidate.start, candidate.end))
        if positions:
            resolved[row["note_id"]] = (row, positions)
    return resolved, misses


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)
    input_path: Path = args.input_path
    database_path = input_path / notesdb.DATABASE_FILENAME
    if not database_path.is_file():
        common.error("database not found")

    selected: list[dict] = []
    if args.report_path is not None:
        report_path = _resolved_path(args.report_path, Path.cwd())
        if not report_path.is_file():
            common.error(f"report '{report_path}' does not exist")
        selected = image_resources.parse_checked_report(report_path)

    config_path = args.config_path or (input_path / image_resources.DEFAULT_CONFIG_FILENAME)
    config_path = _resolved_path(config_path, Path.cwd())
    config, _settings = image_resources.load_config(config_path)
    image_resources.ensure_default_config(config)

    sqlconn = notesdb.open_database(database_path, __program_name__)
    resolved, misses = _find_selected_replacements(sqlconn, selected) if selected else ({}, [])
    quarantine = config["quarantine"]
    quarantine_domains = image_resources.parse_domain_list(
        quarantine.get("quarantine_domains", "")
    )
    domain_resolved, domain_match_count = _find_domain_replacements(
        sqlconn, quarantine_domains
    )
    _merge_resolved(resolved, domain_resolved)
    if not resolved:
        sqlconn.close()
        if selected or quarantine_domains:
            print(
                f"no selected or domain-matched image link was found; "
                f"{len(misses)} checked item(s) unresolved"
            )
            return 1 if misses else 0
        print("no checked report items or quarantine_domains configured; no changes made")
        return 0

    configured_id = quarantine.get("replacement_resource_id", "").strip()
    configured_file = quarantine.get("replacement_resource_file", "").strip()
    metadata = _replacement_resource_metadata(
        sqlconn, input_path, configured_id, configured_file
    )
    if metadata is not None:
        resource_id, relative_file, replacement_mime = metadata
        quarantine["replacement_resource_id"] = resource_id
        quarantine["replacement_resource_file"] = relative_file
        quarantine["replacement_mime"] = replacement_mime
        resource_created = False
    else:
        content, mime, extension, source_path = _load_replacement_bytes(
            config, config_path, args.replacement_image
        )
        title = quarantine.get("replacement_title", "Image removed").strip() or "Image removed"
        store = image_resources.ResourceStore(sqlconn, input_path / "resources")
        resource_id = store.ensure(content, mime, extension, f"{title}.{extension}")
        resource_created = resource_id in store.created_ids
        matching_files = sorted((input_path / "resources").glob(f"{resource_id}.*"))
        relative_file = (
            str(matching_files[0].relative_to(input_path)) if matching_files else f"resources/{resource_id}.{extension}"
        )
        quarantine["replacement_resource_id"] = resource_id
        quarantine["replacement_resource_file"] = relative_file
        quarantine["replacement_mime"] = mime
        if source_path is not None:
            quarantine["replacement_image"] = source_path

    title = quarantine.get("replacement_title", "Image removed").strip() or "Image removed"
    replacement = image_resources.markdown_resource_embed(title, resource_id, title)
    replaced_count = 0
    notes_updated = 0
    try:
        for row, positions in resolved.values():
            body = row["note_data"] or ""
            replacements = [(start, end, replacement) for start, end in positions]
            updated = image_resources.apply_replacements(body, replacements)
            if updated != body:
                image_resources.update_note_body(sqlconn, row["note_id"], updated)
                replaced_count += len(positions)
                notes_updated += 1
        sqlconn.commit()
    except Exception:
        sqlconn.rollback()
        raise
    finally:
        sqlconn.close()

    image_resources.write_config(config, config_path)
    print(
        f"quarantined {replaced_count} image link(s) in {notes_updated} note(s); "
        f"replacement resource {resource_id} ({'created' if resource_created else 'reused'})"
    )
    if domain_match_count:
        print(
            f"quarantine_domains matched {domain_match_count} image link(s) "
            f"across configured domains"
        )
    if misses:
        print(f"warning: {len(misses)} checked report item(s) no longer matched the database")
    print(f"configuration updated: {config_path}")
    return 0 if not misses else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
