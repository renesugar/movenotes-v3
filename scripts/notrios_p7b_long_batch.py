#!/usr/bin/env python3
"""One sequential, notification-backed P7b long-run driver for Luna."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(command: list[str], cwd: Path, log: Path) -> int:
    with log.open("w", encoding="utf-8") as stream:
        return subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "GOCACHE": "/tmp/movenotes-p7b-go-cache"}).returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument("--go-baseline", type=Path, required=True)
    parser.add_argument("--go-candidate", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--preserved", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--skip-python", action="store_true", help="run only remaining Go validation after a completed Python batch")
    args = parser.parse_args(argv)
    if args.output.exists(): parser.error("output already exists")
    old_umask = os.umask(0o077)
    try:
        args.output.mkdir(parents=True)
    finally:
        os.umask(old_umask)
    state = {"status": "running", "steps": []}
    def save() -> None:
        temporary = args.output / "notification.json.tmp"
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(args.output / "notification.json")
    def step(name: str, command: list[str], cwd: Path) -> bool:
        code = run(command, cwd, args.output / (name + ".log"))
        state["steps"].append({"name": name, "command": command, "returncode": code, "log": name + ".log"}); save()
        return code == 0
    try:
        save()
        benchmark = [sys.executable, "-B", str(Path(__file__).with_name("notrios_p7b_benchmark.py")), "--baseline-source", str(args.baseline_source), "--candidate-source", str(args.candidate_source), "--vault", str(args.vault), "--raw", str(args.raw), "--preserved", str(args.preserved), "--output", str(args.output / "python-comparison"), "--pairs", str(args.pairs)]
        checks = [
        ("python-suite", [sys.executable, "-B", "-m", "unittest", "-v", "tests/test_movenotes.py", "tests/test_image_resources.py", "tests/test_obsidian2sql.py", "tests/test_obsidian2site.py", "tests/test_notrios2sql.py", "tests/test_notrios_c7c.py", "tests/test_notrios_p7a.py", "tests/test_notrios_p7b.py"], args.candidate_source),
        ("python-comparison", benchmark, args.candidate_source),
        ("go-baseline-test", ["go", "test", "./..."], args.go_baseline),
        ("go-candidate-test", ["go", "test", "./..."], args.go_candidate),
        ("go-baseline-benchmark", ["go", "test", "-run", "^$", "-bench", "BenchmarkExtractLineLayouts", "-benchmem", "./internal/markdownlinks"], args.go_baseline),
        ("go-candidate-benchmark", ["go", "test", "-run", "^$", "-bench", "BenchmarkExtractLineLayouts", "-benchmem", "./internal/markdownlinks"], args.go_candidate),
        ]
        if args.skip_python:
            checks = [entry for entry in checks if entry[0].startswith("go-")]
        for name, command, cwd in checks:
            if not step(name, command, cwd):
                state["status"] = "failed"; save(); print(f"P7B_LONG_BATCH_FAILED output={args.output}", flush=True); return 1
        state["status"] = "complete"; save()
        print(f"P7B_LONG_BATCH_COMPLETE output={args.output}", flush=True)
        return 0
    except Exception as exc:
        state["status"] = "failed"; state["error"] = repr(exc); save()
        print(f"P7B_LONG_BATCH_FAILED output={args.output}", flush=True)
        return 1
    finally:
        if state["status"] == "running":
            state["status"] = "failed"; state["error"] = "interrupted"; save()
        subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("notrios_p7a_artifacts.py")), "--root", str(args.output)], check=False,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
