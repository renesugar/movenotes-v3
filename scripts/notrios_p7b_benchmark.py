#!/usr/bin/env python3
"""Run isolated P7b baseline/candidate importer comparisons sequentially.

The caller supplies two complete source trees.  This is intentional: candidate
selection never travels through a production command-line flag.  Each run has
its own database directory and a compact SQLite identity fingerprint, while
the source corpus is only read.  The script does not delete any result.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


CASES = {
    "native": ("obsidian2sql.py", "vault"),
    "raw": ("joplin2sql.py", "raw"),
    "preserved": ("obsidian2sql.py", "preserved"),
}


def _is_generated_tag_or_relation(item_type: object, path: object) -> bool:
    value = str(path or "")
    return (
        item_type == 5 and value.startswith(".movenotes/tags/")
    ) or (
        item_type == 6 and value.startswith(".movenotes/note-tags/")
    )


def _fingerprint(database: Path, resources: Path) -> dict[str, object]:
    """Hash all stable stored note fields and copied resource bytes.

    SQLite note IDs and import timestamps are allocated per run, so they are
    deliberately excluded. Everything else includes bodies, exact source
    envelopes and unknown-property storage rather than only identity fields.
    """
    conn = sqlite3.connect(database)
    try:
        # note_id is allocated by SQLite and note_internal_date is a local
        # import timestamp. Source timestamps remain compared. Generated tag
        # and relation rows are normalized below because their only timestamp
        # comes from datetime.now() in _native_rows.
        excluded = {"note_id", "note_internal_date"}
        columns = [row[1] for row in conn.execute("PRAGMA table_info(notes)") if row[1] not in excluded]
        quoted = ", ".join('"' + column + '"' for column in columns)
        rows = conn.execute(
            f"SELECT {quoted} FROM notes ORDER BY joplin_id, joplin_type_, note_uuid"
        )
        digest = hashlib.sha256()
        count = 0
        timestamp_columns = {
            "joplin_created_time", "joplin_updated_time", "joplin_user_created_time",
            "joplin_user_updated_time", "joplin_item_updated_time", "joplin_blob_updated_time",
        }
        type_index = columns.index("joplin_type_")
        source_index = columns.index("note_obsidian_path")
        timestamp_indexes = [columns.index(column) for column in timestamp_columns if column in columns]
        for row in rows:
            values = list(row)
            if _is_generated_tag_or_relation(values[type_index], values[source_index]):
                for index in timestamp_indexes:
                    values[index] = "<generated-at-import>"
                # The generated tag/relation property envelope repeats these
                # four values. Normalize only those known generated keys while
                # retaining its ordered unknown properties verbatim.
                properties_index = columns.index("note_source_properties")
                raw_properties = values[properties_index]
                try:
                    properties = json.loads(raw_properties) if raw_properties else None
                    if isinstance(properties, list):
                        normalized = []
                        for entry in properties:
                            if isinstance(entry, list) and len(entry) == 2 and entry[0] in {"created_time", "updated_time", "user_created_time", "user_updated_time"}:
                                normalized.append([entry[0], "<generated-at-import>"])
                            else:
                                normalized.append(entry)
                        properties = normalized
                        values[properties_index] = json.dumps(properties, separators=(",", ":"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            digest.update(repr(tuple(values)).encode("utf-8", "backslashreplace"))
            digest.update(b"\n")
            count += 1
        tables: dict[str, str] = {}
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> 'notes' ORDER BY name"):
            table_columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            table_digest = hashlib.sha256()
            if table_columns:
                query_columns = ", ".join('"' + column + '"' for column in table_columns)
                order = ", ".join('"' + column + '"' for column in table_columns)
                for table_row in conn.execute(f'SELECT {query_columns} FROM "{table}" ORDER BY {order}'):
                    table_digest.update(repr(tuple(table_row)).encode("utf-8", "backslashreplace"))
                    table_digest.update(b"\n")
            tables[table] = table_digest.hexdigest()
        return {
            "notes": count,
            "stable_note_columns": columns,
            "notes_sha256": digest.hexdigest(),
            "auxiliary_tables_sha256": tables,
            "resources_sha256": _tree_sha256(resources) if resources.is_dir() else None,
        }
    finally:
        conn.close()


def _tree_sha256(root: Path) -> str:
    """Hash a read-only tree once, including names, bytes and empty folders."""
    digest = hashlib.sha256()
    for current, dirs, files in os.walk(root):
        dirs.sort()
        files.sort()
        current_path = Path(current)
        for name in dirs:
            digest.update(b"D\0" + (current_path / name).relative_to(root).as_posix().encode() + b"\0")
        for name in files:
            path = current_path / name
            if path.is_symlink():
                continue
            digest.update(b"F\0" + path.relative_to(root).as_posix().encode() + b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _persist(output: Path, records: list[dict[str, object]], status: str, **extra: object) -> None:
    payload = {"status": status, "records": records, **extra}
    for name, value in (("results.json", payload), ("notification.json", {"status": status, "output": str(output), **extra})):
        target = output / name
        temporary = output / (name + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)


def _inventory(output: Path) -> None:
    subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name("notrios_p7a_artifacts.py")), "--root", str(output)],
        check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _run_one(
    source: Path, corpus: Path, script: str, destination: Path, log_path: Path
) -> dict[str, object]:
    destination.mkdir(parents=True)
    command = [
        sys.executable,
        "-B",
        str(source / script),
        "--input",
        str(corpus),
        "--output",
        str(destination),
        "--progress-every",
        "0",
        "--batch-size",
        "500",
    ]
    before = time.perf_counter()
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, text=True, env=environment)
    elapsed = time.perf_counter() - before
    record: dict[str, object] = {
        "command": command,
        "wall_seconds": elapsed,
        "returncode": result.returncode,
        "log": log_path.name,
    }
    database = destination / "notesdb.sqlite"
    if result.returncode == 0 and database.is_file():
        record["fingerprint"] = _fingerprint(database, destination / "resources")
    return record


def _recompare(root: Path, sources: dict[str, Path], inputs: dict[str, Path]) -> int:
    """Rehash completed outputs without rerunning an importer or mutating state."""
    original = json.loads((root / "results.json").read_text(encoding="utf-8"))
    report_path = root / "RECOMPARE_REPORT.json"
    if report_path.exists():
        raise SystemExit(f"recompare report already exists: {report_path}")
    current_sources = {name: _tree_sha256(path) for name, path in sources.items()}
    current_inputs = {name: _tree_sha256(path) for name, path in inputs.items()}
    cases = original.get("cases", [])
    pair_count = int(original.get("pairs", 0))
    valid_matrix = bool(cases) and pair_count > 0 and all(case in CASES for case in cases) and len(set(cases)) == len(cases)
    expected = {(case, pair, side) for case in cases for pair in range(1, pair_count + 1) for side in ("baseline", "candidate")}
    original_keys = {(str(record.get("case")), int(record.get("pair", 0)), str(record.get("side"))) for record in original.get("records", [])}
    complete = valid_matrix and len(original_keys) == len(original.get("records", [])) and original_keys == expected and all(record.get("returncode") == 0 for record in original.get("records", []))
    records = []
    for record in original.get("records", []):
        destination = root / str(record["case"]) / f"pair-{int(record['pair']):02d}" / str(record["side"])
        database = destination / "notesdb.sqlite"
        if not database.is_file():
            complete = False
            continue
        records.append({**{key: record[key] for key in ("case", "pair", "side")}, "fingerprint": _fingerprint(database, destination / "resources")})
    pairs: dict[tuple[str, int], dict[str, object]] = {}
    for record in records:
        pairs.setdefault((str(record["case"]), int(record["pair"])), {})[str(record["side"])] = record["fingerprint"]
    report = {
        "format": "movenotes-p7b-recompare-v1",
        "original_results": "results.json",
        "comparator_change": "normalizes only generated tag/note-tag property-envelope timestamp keys",
        "comparator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_hash_matches_snapshot": current_sources == original.get("source_sha256"),
        "input_hash_matches_snapshot": current_inputs == original.get("input_sha256"),
        "records": records,
        "all_pair_fingerprints_equal": all(values.get("baseline") == values.get("candidate") for values in pairs.values()),
    }
    report["record_set_complete"] = complete
    temporary = root / "RECOMPARE_REPORT.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    print(f"P7B_RECOMPARE_COMPLETE report={report_path}", flush=True)
    return 0 if complete and report["source_hash_matches_snapshot"] and report["input_hash_matches_snapshot"] and report["all_pair_fingerprints_equal"] else 3


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--preserved", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recompare", action="store_true", help="rehash an existing completed output only")
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--cases", nargs="+", choices=sorted(CASES), default=sorted(CASES))
    args = parser.parse_args(argv)
    if args.pairs < 1:
        parser.error("--pairs must be at least 1")
    for source in (args.baseline_source, args.candidate_source):
        if not (source / "obsidian2sql.py").is_file() or not (source / "joplin2sql.py").is_file():
            parser.error(f"not a movenotes source tree: {source}")
    inputs = {"vault": args.vault, "raw": args.raw, "preserved": args.preserved}
    for label, path in inputs.items():
        if not path.is_dir():
            parser.error(f"--{label} is not a directory: {path}")
    if args.recompare:
        if not args.output.is_dir():
            parser.error("--recompare requires an existing --output directory")
        return _recompare(args.output, {"baseline": args.baseline_source, "candidate": args.candidate_source}, {"vault": args.vault, "raw": args.raw, "preserved": args.preserved})
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    old_umask = os.umask(0o077)
    try:
        args.output.mkdir(parents=True)
    finally:
        os.umask(old_umask)
    records: list[dict[str, object]] = []
    sources = {"baseline": args.baseline_source, "candidate": args.candidate_source}
    metadata: dict[str, object] = {"pairs": args.pairs, "cases": args.cases}
    terminal: dict[str, object] = {"status": "failed", "reason": "unexpected benchmark exception"}
    def finish() -> None:
        _persist(args.output, records, str(terminal["status"]), **metadata, **{key: value for key, value in terminal.items() if key != "status"})
        _inventory(args.output)
    atexit.register(finish)
    inputs_hashes = {name: _tree_sha256(path) for name, path in inputs.items()}
    source_hashes = {name: _tree_sha256(path) for name, path in sources.items()}
    metadata.update({"input_sha256": inputs_hashes, "source_sha256": source_hashes})
    _persist(
        args.output, records, "running", input_sha256=inputs_hashes,
        source_sha256=source_hashes, pairs=args.pairs, cases=args.cases,
    )
    for case in args.cases:
        script, input_name = CASES[case]
        # Reverse alternate pairs so cache/order bias is balanced before P7c's
        # broader acceptance matrix.
        for pair in range(1, args.pairs + 1):
            sides = ("baseline", "candidate") if pair % 2 else ("candidate", "baseline")
            for side in sides:
                destination = args.output / case / f"pair-{pair:02d}" / side
                log_path = destination.parent / f"{side}.log"
                record = _run_one(sources[side], inputs[input_name], script, destination, log_path)
                record.update({"case": case, "pair": pair, "side": side})
                records.append(record)
                _persist(
                    args.output, records, "running", input_sha256=inputs_hashes,
                    source_sha256=source_hashes, pairs=args.pairs, cases=args.cases,
                )
                if record["returncode"] != 0:
                    _persist(
                        args.output, records, "failed", reason="importer failure",
                        input_sha256=inputs_hashes, source_sha256=source_hashes,
                    )
                    _inventory(args.output)
                    terminal.update({"status": "failed", "reason": "importer failure"})
                    print(f"P7B_BENCHMARK_FAILED output={args.output}", flush=True)
                    return int(record["returncode"])
    by_case: dict[str, dict[str, list[dict[str, object]]]] = {}
    for record in records:
        by_case.setdefault(str(record["case"]), {}).setdefault(str(record["side"]), []).append(record)
    comparison: dict[str, object] = {}
    for case, sides in by_case.items():
        baseline = sides["baseline"]
        candidate = sides["candidate"]
        same_output = [
            item["fingerprint"] == other["fingerprint"]
            for item, other in zip(baseline, candidate, strict=True)
        ]
        comparison[case] = {
            "baseline_seconds": [item["wall_seconds"] for item in baseline],
            "candidate_seconds": [item["wall_seconds"] for item in candidate],
            "all_pair_fingerprints_equal": all(same_output),
        }
    outputs_equal = all(
        bool(value["all_pair_fingerprints_equal"]) for value in comparison.values()
    )
    status = "complete" if outputs_equal else "failed"
    _persist(
        args.output, records, status, input_sha256=inputs_hashes,
        source_sha256=source_hashes, pairs=args.pairs, cases=args.cases, comparison=comparison,
        reason=None if outputs_equal else "baseline/candidate output mismatch",
    )
    # Reuse P7a's recursive, purpose-labelled, non-deleting inventory rather
    # than maintaining a weaker second manifest format here.
    _inventory(args.output)
    terminal.update({"status": status, "comparison": comparison, "reason": None if outputs_equal else "baseline/candidate output mismatch"})
    atexit.unregister(finish)
    marker = "P7B_BENCHMARK_COMPLETE" if outputs_equal else "P7B_BENCHMARK_FAILED"
    print(f"{marker} output={args.output}", flush=True)
    return 0 if outputs_equal else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
