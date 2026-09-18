#!/usr/bin/env python3
"""Run a bounded, source-to-route recipe comparison smoke.

The command selects a small representative cohort from the supplied source
tree, joins it independently to the RAW and Obsidian producer databases, and
prints aggregate assertions only.  It never writes source paths, IDs, titles,
bodies, metadata values, or hash values to the report.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import sys

# Keep direct ``python scripts/...`` invocation independent of the caller's
# working directory; this resolves only the repository module, never an input
# or output path.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from notrios_c7c import (
    C7CError,
    Limits,
    _connect_input_database,
    _decode_snapshot,
    _frontmatter_tags,
    _iter_files,
    _parse_raw_source,
    _parse_source_record,
    _read_bounded,
    _route_body,
    _safe_relative,
    _semantic_title,
    _sha256_text,
    parse_frontmatter,
    split_frontmatter,
)


def _contains_numeric(value: object) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if isinstance(value, list):
        return any(_contains_numeric(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_numeric(item) for item in value.values())
    return False


def _source_candidate(
    path: Path,
    raw: bytes,
    *,
    vault_root: Path,
    prefix: str,
    limits: Limits,
) -> dict[str, object] | None:
    record = _parse_source_record(path, raw, vault_root, prefix, limits)
    if record is None or record["status"] != "ok":
        return None
    body, properties = _parse_raw_source(path, raw)
    applications = [value for key, value in properties if key.lower() == "application_data"]
    if len(applications) != 1:
        return None
    snapshot = _decode_snapshot(applications[0], limits)
    snapshot_text = snapshot.raw.decode("utf-8")
    frontmatter, recipe_body = split_frontmatter(snapshot_text)
    values = parse_frontmatter(frontmatter, max_bytes=limits.max_frontmatter_bytes) if frontmatter is not None else {}
    tags, _tags_hash = _frontmatter_tags(values, limits)
    return {
        "record": record,
        "raw_external_id": str(record["raw_external_id"]),
        "relative_path": str(record["relative_path"]),
        "numeric_metadata": _contains_numeric(values),
        "tagged": bool(tags),
        "leading_lf": recipe_body.startswith("\n"),
        "pinned_title_difference": record["pinned_title_hash"] != record["title_hash"],
    }


def _select_candidates(
    raw_root: Path,
    vault_root: Path,
    prefix: str,
    limits: Limits,
    limit: int,
    max_files: int,
) -> tuple[list[dict[str, object]], int, Counter[str]]:
    required = {
        "numeric_metadata": None,
        "tagged": None,
        "untagged": None,
        "leading_lf": None,
        "pinned_title_difference": None,
    }
    candidates: list[dict[str, object]] = []
    inspected = 0
    skipped = Counter()
    for _relative, path in _iter_files(raw_root):
        inspected += 1
        if inspected > max_files:
            break
        if path.suffix.lower() != ".md":
            continue
        try:
            candidate = _source_candidate(
                path,
                _read_bounded(path, limits.max_source_bytes),
                vault_root=vault_root,
                prefix=prefix,
                limits=limits,
            )
        except (C7CError, UnicodeDecodeError):
            skipped["rejected"] += 1
            continue
        if candidate is None:
            skipped["not_a_recipe_note"] += 1
            continue
        candidates.append(candidate)
        if candidate["numeric_metadata"] and required["numeric_metadata"] is None:
            required["numeric_metadata"] = candidate
        if candidate["tagged"] and required["tagged"] is None:
            required["tagged"] = candidate
        if not candidate["tagged"] and required["untagged"] is None:
            required["untagged"] = candidate
        if candidate["leading_lf"] and required["leading_lf"] is None:
            required["leading_lf"] = candidate
        if candidate["pinned_title_difference"] and required["pinned_title_difference"] is None:
            required["pinned_title_difference"] = candidate
        if len(candidates) >= limit and all(value is not None for value in required.values()):
            break

    missing = [key for key, value in required.items() if value is None]
    if missing:
        raise C7CError("representative smoke is missing required categories: " + ",".join(missing))
    selected: list[dict[str, object]] = []
    selected_keys: set[tuple[str, str]] = set()
    for candidate in required.values():
        assert candidate is not None
        key = (str(candidate["raw_external_id"]), str(candidate["relative_path"]))
        if key not in selected_keys:
            selected.append(candidate)
            selected_keys.add(key)
    for candidate in candidates:
        if len(selected) >= limit:
            break
        key = (str(candidate["raw_external_id"]), str(candidate["relative_path"]))
        if key not in selected_keys:
            selected.append(candidate)
            selected_keys.add(key)
    return selected, inspected, skipped


def _load_route_rows(
    path: Path,
    route: str,
    identities: list[str],
    limits: Limits,
) -> dict[str, dict[str, object]]:
    if not identities:
        return {}
    connection = _connect_input_database(path)
    try:
        result: dict[str, dict[str, object]] = {}
        identity_column = "external_id"
        source_system = "joplin" if route == "raw" else "obsidian"
        for offset in range(0, len(identities), 700):
            batch = identities[offset : offset + 700]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                "SELECT d.id AS document_id, d.title AS document_title, "
                "r.title AS revision_title, r.body AS body, "
                "s.external_id AS external_id, s.metadata_json AS source_metadata "
                "FROM documents d JOIN document_revisions r ON r.id = d.current_revision_id "
                "JOIN document_sources s ON s.document_id = d.id "
                f"WHERE d.deleted_at IS NULL AND s.source_system = ? AND s.{identity_column} IN ({placeholders})",
                (source_system, *batch),
            ).fetchall()
            for row in rows:
                identity = str(row["external_id"])
                body = row["body"] if isinstance(row["body"], str) else ""
                expected_path = None
                if route == "vault":
                    metadata = json.loads(row["source_metadata"] or "{}")
                    declared = metadata.get("relative_path") if isinstance(metadata, dict) else None
                    safe = _safe_relative(declared)
                    if safe is None or safe.as_posix() != identity:
                        continue
                    expected_path = safe.as_posix()
                semantics = _route_body(route, body, limits, expected_path=expected_path)
                result[identity] = {
                    "body_hash": semantics["body_hash"],
                    "title_hash": _sha256_text(_semantic_title(str(row["revision_title"] or row["document_title"] or ""))),
                    "metadata_hash": semantics["metadata_hash"],
                    "body_status": semantics["body_status"],
                    "metadata_status": semantics["metadata_status"],
                }
        return result
    finally:
        connection.close()


def _write_report(path: Path | None, report: dict[str, object]) -> None:
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(encoded)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    path.write_text(encoded, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-source-root", required=True)
    parser.add_argument("--vault-root", required=True)
    parser.add_argument("--raw-db", required=True)
    parser.add_argument("--vault-db", required=True)
    parser.add_argument("--prefix", default="Recipes/")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-files", type=int, default=100_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.limit < 5 or args.max_files < args.limit:
        parser.error("limit must be at least 5 and max-files must cover the cohort")
    limits = Limits()
    try:
        selected, inspected, skipped = _select_candidates(
            Path(args.raw_source_root), Path(args.vault_root), args.prefix,
            limits, args.limit, args.max_files,
        )
        raw_ids = [str(candidate["raw_external_id"]) for candidate in selected]
        vault_ids = [str(candidate["relative_path"]) for candidate in selected]
        raw_rows = _load_route_rows(Path(args.raw_db), "raw", raw_ids, limits)
        vault_rows = _load_route_rows(Path(args.vault_db), "vault", vault_ids, limits)
        route_results: dict[str, dict[str, int]] = {}
        assertions: list[str] = []
        for route, rows, ids in (("raw", raw_rows, raw_ids), ("vault", vault_rows, vault_ids)):
            body_matches = 0
            title_exact = 0
            title_pinned_only = 0
            title_pinned = 0
            metadata_matches = 0
            status_ok = 0
            for candidate, identity in zip(selected, ids):
                source = candidate["record"]
                route_row = rows.get(identity)
                if route_row is None:
                    continue
                if route_row["body_status"] == "ok":
                    status_ok += 1
                if route_row["body_hash"] == source["body_hash"]:
                    body_matches += 1
                if route_row["title_hash"] == source["title_hash"]:
                    title_exact += 1
                elif route_row["title_hash"] == source["pinned_title_hash"]:
                    title_pinned_only += 1
                if route_row["title_hash"] == source["pinned_title_hash"]:
                    title_pinned += 1
                if route == "vault" and source["metadata_hash"] is not None and route_row["metadata_hash"] == source["metadata_hash"]:
                    metadata_matches += 1
            route_results[route] = {
                "documents_found": len(rows),
                "body_hash_matches": body_matches,
                "title_exact_matches": title_exact,
                "title_pinned_matches": title_pinned,
                "title_categories": {
                    "exact": title_exact,
                    "pinned_frontmatter_scalar": title_pinned_only,
                    "unexplained": max(len(selected) - title_exact - title_pinned_only, 0),
                },
                "body_status_ok": status_ok,
                "metadata_hash_matches": metadata_matches,
            }
            if len(rows) != len(selected):
                assertions.append(route + ":all_identities_found")
            if body_matches != len(selected):
                assertions.append(route + ":body_hashes_match_source")
            if status_ok != len(selected):
                assertions.append(route + ":body_status_ok")
        source_counts = Counter()
        for candidate in selected:
            source_counts["numeric_metadata" if candidate["numeric_metadata"] else "non_numeric_only"] += 1
            source_counts["tagged" if candidate["tagged"] else "untagged"] += 1
            if candidate["leading_lf"]:
                source_counts["leading_lf"] += 1
            if candidate["pinned_title_difference"]:
                source_counts["pinned_title_difference"] += 1
        if source_counts["numeric_metadata"] == 0:
            assertions.append("source:numeric_metadata_represented")
        if source_counts["tagged"] == 0 or source_counts["untagged"] == 0:
            assertions.append("source:tagged_and_untagged_represented")
        if source_counts["leading_lf"] == 0:
            assertions.append("source:leading_lf_represented")
        if source_counts["pinned_title_difference"] == 0:
            assertions.append("source:pinned_title_difference_represented")
        report = {
            "status": "complete" if not assertions else "failed",
            "selected_records": len(selected),
            "inspected_source_files": inspected,
            "skipped_source_files": dict(sorted(skipped.items())),
            "source_categories": dict(sorted(source_counts.items())),
            "routes": route_results,
            "assertions_failed": assertions,
            "source_content_included": False,
        }
    except (C7CError, OSError, sqlite3.Error, UnicodeDecodeError, ValueError) as exc:
        report = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": "bounded smoke failed; inspect the private command stderr",
            "source_content_included": False,
        }
    _write_report(args.output, report)
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
