#!/usr/bin/env python3
"""Run a durable, alternating P7c source-variant benchmark matrix.

Each side is a complete movenotes source tree.  The script creates a fresh
output per pair, optionally reruns the same input for an unchanged case, and
optionally merges the ten-note ``tiny`` corpus after the initial native
import.  It never overwrites a completed output.  ``--resume`` continues an
interrupted matrix using a new attempt directory for an incomplete side.

The benchmark is deliberately sequential.  ``/usr/bin/time`` supplies
per-import wall/user/system time, maximum RSS and filesystem input-operation
counts without model-mediated polling; progress is persisted after every
importer process.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from notrios_p7b_benchmark import _fingerprint, _tree_sha256


FORMAT = "movenotes-p7c-benchmark-v1"
CASES = {
    "native": ("obsidian2sql.py", "vault", "fresh"),
    "native-unchanged": ("obsidian2sql.py", "vault", "unchanged"),
    "native-small-merge": ("obsidian2sql.py", "vault", "small-merge"),
    "preserved": ("obsidian2sql.py", "preserved", "fresh"),
    "preserved-unchanged": ("obsidian2sql.py", "preserved", "unchanged"),
    "raw": ("joplin2sql.py", "raw", "fresh"),
    "raw-unchanged": ("joplin2sql.py", "raw", "unchanged"),
    "media": ("obsidian2sql.py", "media", "fresh"),
    "media-unchanged": ("obsidian2sql.py", "media", "unchanged"),
    "prepared-unchanged": ("obsidian2sql.py", "preserved", "prepared-unchanged"),
    "prepared-small-merge": ("obsidian2sql.py", "tiny", "prepared-small-merge"),
}


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _tree_bytes(root: Path) -> int:
    total = 0
    for current, dirs, files in os.walk(root):
        dirs.sort()
        for name in files:
            path = Path(current) / name
            if path.is_symlink():
                continue
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total


def _source_inventory(root: Path) -> dict[str, object]:
    files = 0
    bytes_ = 0
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in {".git", "__pycache__"})
        for name in sorted(names):
            path = Path(current) / name
            if path.is_symlink() or path.name.endswith(".pyc"):
                continue
            files += 1
            bytes_ += path.stat().st_size
    return {"files": files, "bytes": bytes_, "sha256": _tree_sha256(root)}


def _harness_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _parse_time(path: Path) -> dict[str, object]:
    raw = path.read_text(encoding="utf-8").strip()
    parts = raw.split()
    if len(parts) != 6 or parts[0] != "P7C_TIME":
        raise ValueError(f"invalid /usr/bin/time record: {raw!r}")
    return {
        "wall_seconds": float(parts[1]),
        "user_seconds": float(parts[2]),
        "system_seconds": float(parts[3]),
        "max_rss_kib": int(parts[4]),
        "filesystem_input_operations": int(parts[5]),
    }


def _phase_paths(stage: Path, side: str, phase: str, attempt: int) -> tuple[Path, Path]:
    """Return unique replay paths and refuse to overwrite orphan evidence."""
    suffix = "" if attempt == 1 else f"-attempt-{attempt:02d}"
    log = stage / f"{side}-{phase}{suffix}.log"
    metrics = stage / f"{side}-{phase}{suffix}.time"
    if log.exists() or metrics.exists():
        raise FileExistsError(f"refusing to overwrite existing phase evidence: {log} / {metrics}")
    return log, metrics


def _run_import(
    source: Path,
    script: str,
    corpus: Path,
    destination: Path,
    log: Path,
    metrics: Path,
    root: Path,
) -> dict[str, object]:
    # Fresh attempts use a new destination; unchanged and merge phases reuse
    # the same database deliberately.
    destination.mkdir(parents=True, exist_ok=True)
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
    before_bytes = _tree_bytes(destination)
    before_free = shutil.disk_usage(root).free
    started = time.time()
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.run(
            [
                "/usr/bin/time",
                "-f",
                "P7C_TIME %e %U %S %M %I",
                "-o",
                str(metrics),
                *command,
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
        )
    elapsed = time.time() - started
    record: dict[str, object] = {
        "command": command,
        "returncode": process.returncode,
        "log": str(log.relative_to(root)),
        "metrics": str(metrics.relative_to(root)),
        "elapsed_observer_seconds": elapsed,
        "disk_free_before": before_free,
        "disk_free_after": shutil.disk_usage(root).free,
        "output_bytes_before": before_bytes,
        "output_bytes_after": _tree_bytes(destination),
    }
    if process.returncode == 0:
        record.update(_parse_time(metrics))
        database = destination / "notesdb.sqlite"
        if not database.is_file():
            raise RuntimeError(f"import succeeded without database: {destination}")
        record["fingerprint"] = _fingerprint(database, destination / "resources")
        record["database_bytes"] = database.stat().st_size
    return record


def _clone_seed(seed: Path, destination: Path) -> dict[str, object]:
    """Clone a completed seed and verify its tree before the importer runs."""
    if destination.exists():
        raise FileExistsError(destination)
    source_hash = _tree_sha256(seed)
    shutil.copytree(seed, destination, symlinks=True)
    clone_hash = _tree_sha256(destination)
    if source_hash != clone_hash:
        raise RuntimeError(f"prepared seed changed while cloning: {seed}")
    return {
        "phase": "seed-clone",
        "seed_source": str(seed),
        "seed_source_sha256": source_hash,
        "seed_clone_sha256": clone_hash,
        "seed_clone_bytes": _tree_bytes(destination),
    }


def _latest(records: list[dict[str, object]]) -> dict[tuple[str, int, str], dict[str, object]]:
    latest: dict[tuple[str, int, str], dict[str, object]] = {}
    for record in records:
        key = (str(record["case"]), int(record["pair"]), str(record["side"]))
        old = latest.get(key)
        if old is None or int(record.get("attempt", 0)) >= int(old.get("attempt", 0)):
            latest[key] = record
    return latest


def _attempt_destination(root: Path, case: str, pair: int, side: str, attempt: int) -> Path:
    base = root / case / f"pair-{pair:02d}" / side
    if attempt == 1:
        return base
    return base.with_name(f"{side}-attempt-{attempt:02d}")


def _matrix_complete(records: list[dict[str, object]], cases: list[str], pairs: int) -> bool:
    latest = _latest(records)
    expected = {
        (case, pair, side)
        for case in cases
        for pair in range(1, pairs + 1)
        for side in ("left", "right")
    }
    if not expected or set(latest) != expected:
        return False
    for case in cases:
        for pair in range(1, pairs + 1):
            for side in ("left", "right"):
                record = latest.get((case, pair, side))
                if (
                    not record
                    or record.get("status") != "complete"
                    or not isinstance(record.get("fingerprint"), dict)
                    or not record.get("fingerprint")
                ):
                    return False
    return True


def _comparison(records: list[dict[str, object]], cases: list[str], pairs: int) -> dict[str, object]:
    latest = _latest(records)
    result: dict[str, object] = {}
    for case in cases:
        entries = []
        for pair in range(1, pairs + 1):
            left = latest.get((case, pair, "left"))
            right = latest.get((case, pair, "right"))
            if not left or not right:
                continue
            left_fp = left.get("fingerprint")
            right_fp = right.get("fingerprint")
            left_time = float(left.get("wall_seconds", 0.0))
            right_time = float(right.get("wall_seconds", 0.0))
            entries.append(
                {
                    "pair": pair,
                    "left_seconds": left_time,
                    "right_seconds": right_time,
                    "right_minus_left_seconds": right_time - left_time,
                    "right_over_left": right_time / left_time if left_time else None,
                    "fingerprints_equal": left_fp == right_fp,
                    "left_max_rss_kib": left.get("max_rss_kib"),
                    "right_max_rss_kib": right.get("max_rss_kib"),
                    "left_database_bytes": left.get("database_bytes"),
                    "right_database_bytes": right.get("database_bytes"),
                }
            )
        values = [entry["right_over_left"] for entry in entries if entry["right_over_left"] is not None]
        result[case] = {
            "pairs": entries,
            "all_fingerprints_equal": bool(entries) and all(entry["fingerprints_equal"] for entry in entries),
            "median_right_over_left": sorted(values)[len(values) // 2] if values else None,
        }
    return result


def _persist(
    output: Path,
    status: str,
    records: list[dict[str, object]],
    metadata: dict[str, object],
    reason: str | None = None,
) -> None:
    comparison = _comparison(records, list(metadata["cases"]), int(metadata["pairs"]))
    metadata = {
        key: value
        for key, value in metadata.items()
        if key not in {"format", "status", "records", "comparison", "reason", "harness_sha256"}
    }
    results = {
        **metadata,
        "format": FORMAT,
        "status": status,
        "records": records,
        "comparison": comparison,
        "harness_sha256": _harness_sha256(),
    }
    if reason:
        results["reason"] = reason
    _atomic_json(output / "results.json", results)
    notification = {
        "format": FORMAT,
        "status": status,
        "output": str(output),
        "completed_records": sum(record.get("status") == "complete" for record in records),
        "total_records": len(metadata["cases"]) * int(metadata["pairs"]) * 2,
        "reason": reason,
    }
    _atomic_json(output / "notification.json", notification)


def _load_resume(output: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    try:
        payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"--resume requires a readable results.json: {exc}") from exc
    if payload.get("format") != FORMAT:
        raise SystemExit("results.json is not a P7c benchmark")
    if payload.get("harness_sha256") != _harness_sha256():
        raise SystemExit("benchmark harness changed; start a new matrix instead of resuming")
    metadata = {
        key: value
        for key, value in payload.items()
        if key not in {"format", "status", "records", "comparison", "reason", "harness_sha256"}
    }
    return metadata, list(payload.get("records", []))


def _verify_completed_outputs(output: Path, records: list[dict[str, object]]) -> None:
    """Refuse to reuse a completed record whose durable output changed."""
    for record in records:
        if record.get("status") != "complete":
            continue
        destination_value = record.get("destination")
        expected = record.get("fingerprint")
        if not isinstance(destination_value, str) or not isinstance(expected, dict):
            raise SystemExit("completed record is missing its destination or fingerprint")
        destination = (output / destination_value).resolve()
        try:
            destination.relative_to(output.resolve())
        except ValueError as exc:
            raise SystemExit(f"completed destination escapes benchmark output: {destination}") from exc
        database = destination / "notesdb.sqlite"
        if not database.is_file():
            raise SystemExit(f"completed output is missing its database: {destination}")
        actual = _fingerprint(database, destination / "resources")
        if actual != expected:
            raise SystemExit(f"completed output fingerprint changed: {destination}")


def run_matrix(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    cases = list(args.cases)
    inputs = {
        "vault": args.vault.resolve(),
        "raw": args.raw.resolve(),
        "preserved": args.preserved.resolve(),
        "tiny": args.tiny.resolve(),
        "media": args.media.resolve(),
    }
    seed = args.seed.resolve() if args.seed is not None else None
    for name, path in inputs.items():
        if not path.is_dir():
            raise SystemExit(f"input {name} is not a directory: {path}")
    if any(CASES[case][2].startswith("prepared-") for case in cases):
        if seed is None or not seed.is_dir() or not (seed / "notesdb.sqlite").is_file():
            raise SystemExit("prepared cases require --seed pointing to a completed importer output")
    for source in (args.left_source, args.right_source):
        if not (source / "obsidian2sql.py").is_file() or not (source / "joplin2sql.py").is_file():
            raise SystemExit(f"not a movenotes source tree: {source}")
    if args.pairs < 1:
        raise SystemExit("--pairs must be at least one")
    if output.exists() and not args.resume:
        raise SystemExit(f"output exists; use --resume only for an interrupted matrix: {output}")

    if args.resume:
        metadata, records = _load_resume(output)
        expected = {
            "left_source_sha256": _tree_sha256(args.left_source),
            "right_source_sha256": _tree_sha256(args.right_source),
            "input_sha256": {name: _tree_sha256(path) for name, path in inputs.items()},
            "seed_sha256": _tree_sha256(seed) if seed is not None else None,
        }
        if metadata.get("cases") != cases or metadata.get("pairs") != args.pairs:
            raise SystemExit("--resume matrix differs from its original cases or pair count")
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise SystemExit(f"--resume {key} differs from the original matrix")
        _verify_completed_outputs(output, records)
    else:
        old_umask = os.umask(0o077)
        try:
            output.mkdir(parents=True)
        finally:
            os.umask(old_umask)
        metadata = {
            "left_name": args.left_name,
            "right_name": args.right_name,
            "left_source": str(args.left_source),
            "right_source": str(args.right_source),
            "left_source_sha256": _tree_sha256(args.left_source),
            "right_source_sha256": _tree_sha256(args.right_source),
            "left_source_inventory": _source_inventory(args.left_source),
            "right_source_inventory": _source_inventory(args.right_source),
            "input_sha256": {name: _tree_sha256(path) for name, path in inputs.items()},
            "input_inventory": {name: _source_inventory(path) for name, path in inputs.items()},
            "seed": str(seed) if seed is not None else None,
            "seed_sha256": _tree_sha256(seed) if seed is not None else None,
            "cases": cases,
            "pairs": args.pairs,
            "started_at": time.time(),
        }
        records = []

    state = {"status": "running", "reason": None}
    _persist(output, "running", records, metadata)

    def mark_interrupted() -> None:
        if state["status"] == "running":
            _persist(output, "failed", records, metadata, "interrupted")

    atexit.register(mark_interrupted)
    latest = _latest(records)
    try:
        for case in cases:
            script, input_name, mode = CASES[case]
            corpus = inputs[input_name]
            for pair in range(1, args.pairs + 1):
                sides = (("left", args.left_source), ("right", args.right_source)) if pair % 2 else (("right", args.right_source), ("left", args.left_source))
                for side, source in sides:
                    key = (case, pair, side)
                    previous = latest.get(key)
                    if previous and previous.get("status") == "complete":
                        continue
                    attempt = int(previous.get("attempt", 0)) + 1 if previous else 1
                    destination = _attempt_destination(output, case, pair, side, attempt)
                    stage = destination.parent
                    stage.mkdir(parents=True, exist_ok=True)
                    phases: list[dict[str, object]] = []
                    if mode.startswith("prepared-"):
                        if seed is None:
                            raise SystemExit("prepared case missing --seed")
                        phases.append(_clone_seed(seed, destination))
                        if mode == "prepared-unchanged":
                            log, metrics = _phase_paths(stage, side, "unchanged", attempt)
                            prepared = _run_import(
                                source, script, corpus, destination, log, metrics, output
                            )
                            prepared["phase"] = "unchanged"
                        else:
                            log, metrics = _phase_paths(stage, side, "merge", attempt)
                            prepared = _run_import(
                                source, script, inputs["tiny"], destination, log, metrics, output
                            )
                            prepared["phase"] = "merge"
                        phases.append(prepared)
                        final = prepared
                    elif mode == "small-merge":
                        log, metrics = _phase_paths(stage, side, "fresh", attempt)
                        first = _run_import(
                            source, script, corpus, destination, log, metrics, output
                        )
                        first["phase"] = "fresh"
                        phases.append(first)
                        if first["returncode"] != 0:
                            record = {"case": case, "pair": pair, "side": side, "attempt": attempt, "status": "failed", "phases": phases, "error": "fresh phase failed"}
                            records.append(record)
                            _persist(output, "failed", records, metadata, "importer failure")
                            return int(first["returncode"] or 1)
                        merge = _run_import(
                            source, script, inputs["tiny"], destination,
                            *_phase_paths(stage, side, "merge", attempt), output
                        )
                        merge["phase"] = "merge"
                        phases.append(merge)
                        final = merge
                    else:
                        log, metrics = _phase_paths(stage, side, "fresh", attempt)
                        fresh = _run_import(
                            source, script, corpus, destination, log, metrics, output
                        )
                        fresh["phase"] = "fresh"
                        phases.append(fresh)
                        final = fresh
                        if fresh["returncode"] == 0 and mode == "unchanged":
                            log, metrics = _phase_paths(stage, side, "unchanged", attempt)
                            unchanged = _run_import(
                                source, script, corpus, destination, log, metrics, output
                            )
                            unchanged["phase"] = "unchanged"
                            phases.append(unchanged)
                            final = unchanged
                    status = "complete" if final["returncode"] == 0 else "failed"
                    record = {
                        "case": case,
                        "pair": pair,
                        "side": side,
                        "attempt": attempt,
                        "status": status,
                        "destination": str(destination.relative_to(output)),
                        "phases": phases,
                    }
                    if status == "complete":
                        record.update(final)
                    else:
                        record["error"] = "importer failure"
                    records.append(record)
                    latest[key] = record
                    _persist(output, "running" if status == "complete" else "failed", records, metadata, None if status == "complete" else "importer failure")
                    if status != "complete":
                        state["status"] = "failed"
                        return int(final["returncode"] or 1)
        complete = _matrix_complete(records, cases, args.pairs)
        comparison = _comparison(records, cases, args.pairs)
        equal = all(bool(value.get("all_fingerprints_equal")) for value in comparison.values())
        state["status"] = "complete" if complete and equal else "failed"
        reason = None if complete and equal else "incomplete matrix or output fingerprint mismatch"
        _persist(output, state["status"], records, metadata, reason)
        marker = "P7C_BENCHMARK_COMPLETE" if state["status"] == "complete" else "P7C_BENCHMARK_FAILED"
        print(f"{marker} output={output}", flush=True)
        return 0 if state["status"] == "complete" else 3
    finally:
        atexit.unregister(mark_interrupted)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left-name", default="left")
    parser.add_argument("--right-name", default="right")
    parser.add_argument("--left-source", type=Path, required=True)
    parser.add_argument("--right-source", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--preserved", type=Path, required=True)
    parser.add_argument("--tiny", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--cases", nargs="+", choices=sorted(CASES), default=["native", "preserved", "raw"])
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    args.left_source = args.left_source.resolve()
    args.right_source = args.right_source.resolve()
    return run_matrix(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
