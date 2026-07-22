#!/usr/bin/env python3
"""Convert embedded/remote Markdown images in SQLite notes to local resources.

Base64 ``data:image/...;base64,...`` embeds are decoded. HTTP(S) image links
are inspected with HEAD, downloaded with bounded GET requests, validated, and
stored in the SQLite directory's ``resources`` folder. Note bodies are updated
to native Joplin resource links, which both sql2joplin.py and sql2obsidian.py
already export as local attachments.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path

import common
import constants
import image_resources
import notesdb

__program_name__ = "images2resources"
__version__ = "1.20"


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
        "--config",
        dest="config_path",
        type=Path,
        help=(
            "INI configuration file (default: <input>/"
            f"{image_resources.DEFAULT_CONFIG_FILENAME})"
        ),
    )
    parser.add_argument(
        "--report",
        dest="report_path",
        type=Path,
        help="Markdown report path (overrides report_file in the configuration)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Concurrent remote download workers (overrides configuration)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print note progress every N notes; 0 disables it (default: 1000)",
    )
    return parser


def _item_id(row) -> str:  # noqa: ANN001
    return str(row["joplin_id"] or row["note_uuid"] or f"row-{row['note_id']}")


def _issue_from_problem(row, link, problem, *, url=None) -> image_resources.Issue:  # noqa: ANN001
    redirects = getattr(problem, "redirects", []) or []
    redirect_from = redirects[0][0] if redirects else None
    redirect_to = redirects[-1][1] if redirects else None
    return image_resources.Issue(
        category=getattr(problem, "category", getattr(problem, "issue_category", "could-not-convert")),
        kind=getattr(problem, "kind", getattr(problem, "issue_kind", "conversion-error")),
        note_id=_item_id(row),
        note_title=row["note_title"] or "Untitled",
        note_filename=image_resources.note_filename(row),
        line=link.line,
        raw=link.raw,
        detail=getattr(problem, "detail", str(problem)),
        fingerprint=link.fingerprint,
        url=url,
        redirect_from=redirect_from,
        redirect_to=redirect_to,
        original_mime=getattr(problem, "original_mime", None),
        final_mime=getattr(problem, "final_mime", None),
    )


def _resolved_path(value: Path, base: Path) -> Path:
    path = value.expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _fetch_remote_images_bounded(urls, settings):  # noqa: ANN001
    """Yield remote fetch results without creating one Future per URL."""
    iterator = iter(urls)
    max_pending = max(settings.workers * 2, 1)
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=settings.workers
    ) as executor:
        pending: dict[concurrent.futures.Future, str] = {}

        def submit_next() -> bool:
            try:
                url = next(iterator)
            except StopIteration:
                return False
            pending[executor.submit(image_resources.fetch_remote_image, url, settings)] = url
            return True

        for _ in range(max_pending):
            if not submit_next():
                break

        while pending:
            done, _not_done = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                url = pending.pop(future)
                try:
                    result = future.result()
                except Exception as exc:  # Defensive: every URL belongs in the report.
                    result = image_resources.FetchResult(
                        url=url,
                        issue_kind="unexpected-download-error",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                yield url, result
                submit_next()


def main(argv: list[str]) -> int:
    args = _build_argument_parser().parse_args(argv)
    if args.progress_every < 0:
        common.error("--progress-every cannot be negative")
    input_path: Path = args.input_path
    database_path = input_path / notesdb.DATABASE_FILENAME
    if not database_path.is_file():
        common.error("database not found")

    config_path = args.config_path or (input_path / image_resources.DEFAULT_CONFIG_FILENAME)
    config_path = _resolved_path(config_path, Path.cwd())
    config, settings = image_resources.load_config(config_path)
    image_resources.ensure_default_config(config)
    image_resources.write_config(config, config_path)
    if args.workers is not None:
        if args.workers < 1:
            common.error("--workers must be at least 1")
        settings.workers = args.workers

    if args.report_path is not None:
        report_path = _resolved_path(args.report_path, Path.cwd())
    else:
        configured_report = Path(settings.report_file)
        report_path = _resolved_path(configured_report, input_path)

    sqlconn = notesdb.open_database(database_path, __program_name__)
    note_select = (
        "SELECT note_id, joplin_id, note_uuid, note_title, "
        "note_source_filename, note_data FROM notes "
    )
    note_where = "WHERE joplin_type_ = ? AND note_data_format = ?"
    note_query = note_select + note_where + " ORDER BY note_id"
    remote_note_query = (
        note_select
        + note_where
        + " AND (instr(note_data, 'http://') > 0 OR "
        "instr(note_data, 'https://') > 0) ORDER BY note_id"
    )
    note_params = (int(constants.JoplinType.NOTE), "text/markdown")
    total_notes = int(
        sqlconn.execute(
            "SELECT COUNT(*) FROM notes " + note_where, note_params
        ).fetchone()[0]
    )
    remote_candidate_total = int(
        sqlconn.execute(
            "SELECT COUNT(*) FROM notes " + note_where
            + " AND (instr(note_data, 'http://') > 0 OR "
            "instr(note_data, 'https://') > 0)",
            note_params,
        ).fetchone()[0]
    )

    # First pass: retain only one compact link object per unique remote URL.
    # SQLite filters out notes without HTTP text before Python parses them;
    # note bodies and scan results are not accumulated in memory.
    remote_context: dict[str, image_resources.ImageLink] = {}
    remote_discovery_scanned = 0
    for row in sqlconn.execute(remote_note_query, note_params):
        remote_discovery_scanned += 1
        body = row["note_data"] or ""
        links, _malformed = image_resources.scan_markdown_images(body)
        for link in links:
            if link.destination.lower().startswith(("http://", "https://")):
                remote_context.setdefault(link.destination, link)
        if args.progress_every and (
            remote_discovery_scanned % args.progress_every == 0
            or remote_discovery_scanned == remote_candidate_total
        ):
            print(
                f"inspected {remote_discovery_scanned:,} of "
                f"{remote_candidate_total:,} remote-image candidate note(s)"
            )

    resources = image_resources.ResourceStore(sqlconn, input_path / "resources")
    remote_resources: dict[str, tuple[str, str]] = {}
    remote_failures: dict[str, image_resources.FetchResult] = {}
    if remote_context:
        for url, result in _fetch_remote_images_bounded(remote_context, settings):
            if not result.ok:
                remote_failures[url] = result
                continue
            assert result.content is not None
            assert result.mime is not None
            assert result.extension is not None
            first_link = remote_context[url]
            title = image_resources.title_from_link(
                first_link, result.extension, result.final_url or url
            )
            resource_id = resources.ensure(
                result.content,
                result.mime,
                result.extension,
                title,
                source_url=url,
            )
            remote_resources[url] = (resource_id, title)
            # The resource file and row now own the bytes; do not retain every
            # downloaded image in memory until all notes are updated.
            result.content = None
    issues: list[image_resources.Issue] = []
    notes_scanned = 0
    notes_updated = 0
    links_converted = 0

    try:
        # Second pass: rescan and update one note at a time. This trades one
        # additional linear database scan for bounded memory usage.
        for row in sqlconn.execute(note_query, note_params):
            notes_scanned += 1
            body = row["note_data"] or ""
            links, malformed = image_resources.scan_markdown_images(body)
            replacements: list[tuple[int, int, str]] = []
            for bad in malformed:
                issues.append(
                    image_resources.Issue(
                        category="badly-formatted",
                        kind="malformed-markdown-data-image",
                        note_id=_item_id(row),
                        note_title=row["note_title"] or "Untitled",
                        note_filename=image_resources.note_filename(row),
                        line=bad.line,
                        raw=bad.raw,
                        detail="data:image text is not a parseable inline Markdown image link",
                        fingerprint=bad.fingerprint,
                    )
                )

            for link in links:
                destination_lower = link.destination.lower()
                if destination_lower.startswith("data:image/"):
                    try:
                        content, mime, extension = image_resources.decode_data_image(
                            link.destination,
                            allow_svg=settings.allow_svg,
                            max_bytes=settings.max_image_bytes,
                        )
                    except image_resources.FetchProblem as problem:
                        issues.append(_issue_from_problem(row, link, problem))
                        continue
                    title = image_resources.title_from_link(link, extension)
                    resource_id = resources.ensure(content, mime, extension, title)
                    replacement = image_resources.markdown_resource_embed(
                        link.alt, resource_id, title
                    )
                    replacements.append((link.start, link.end, replacement))
                    links_converted += 1
                elif destination_lower.startswith(("http://", "https://")):
                    converted = remote_resources.get(link.destination)
                    if converted is None:
                        result = remote_failures[link.destination]
                        issues.append(
                            _issue_from_problem(row, link, result, url=link.destination)
                        )
                        continue
                    resource_id, title = converted
                    replacement = image_resources.markdown_resource_embed(
                        link.alt, resource_id, title
                    )
                    replacements.append((link.start, link.end, replacement))
                    links_converted += 1

            if replacements:
                updated = image_resources.apply_replacements(body, replacements)
                if updated != body:
                    image_resources.update_note_body(sqlconn, row["note_id"], updated)
                    notes_updated += 1
            if args.progress_every and (
                notes_scanned % args.progress_every == 0 or notes_scanned == total_notes
            ):
                print(
                    f"processed {notes_scanned:,} of {total_notes:,} note(s); "
                    f"updated {notes_updated:,}"
                )
        sqlconn.commit()
    except Exception:
        sqlconn.rollback()
        raise
    finally:
        sqlconn.close()

    image_resources.write_report(
        report_path,
        issues,
        notes_scanned=notes_scanned,
        notes_updated=notes_updated,
        links_converted=links_converted,
        resources_created=len(resources.created_ids),
        resources_reused=len(resources.reused_ids),
    )
    print(
        f"scanned {notes_scanned} note(s); updated {notes_updated}; converted "
        f"{links_converted} image link(s); created {len(resources.created_ids)} "
        f"resource(s); reported {len(issues)} problem(s)"
    )
    print(f"report: {report_path}")
    print(f"configuration: {config_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
