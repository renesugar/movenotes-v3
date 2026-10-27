#!/usr/bin/env python3
"""Run selected P7c matrices sequentially with durable notifications.

This driver is intended to be started once and left running.  It does not
poll children: each benchmark is a blocking subprocess and persists its own
record after every importer.  A later ``--resume`` reruns only an incomplete
experiment in a new output directory; completed experiment directories are
never overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


EXPERIMENTS = {
    "f02-preserved": {"left": "base", "right": "f02", "cases": ["preserved"]},
    "f02-unchanged": {"left": "base", "right": "f02", "cases": ["preserved-unchanged"]},
    "f04-native": {"left": "base", "right": "f04", "cases": ["native", "native-unchanged", "native-small-merge"]},
    "f04-media": {"left": "base", "right": "f04", "cases": ["media", "media-unchanged"]},
    "f04-real-native": {"left": "base", "right": "f04", "cases": ["native", "native-unchanged"]},
    "raw-control-f02": {"left": "base", "right": "f02", "cases": ["raw", "raw-unchanged"]},
    "raw-control-f04": {"left": "base", "right": "f04", "cases": ["raw", "raw-unchanged"]},
    "f02-prepared": {"left": "base", "right": "f02", "cases": ["prepared-unchanged", "prepared-small-merge"]},
    "both-native": {"left": "base", "right": "both", "cases": ["native", "preserved"]},
}
FORMAT = "movenotes-p7c-long-batch-v1"


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def next_batch_log(output: Path, name: str) -> Path:
    """Choose a replay log without overwriting an earlier attempt."""
    first = output / f"{name}.log"
    if not first.exists():
        return first
    attempt = 2
    while True:
        candidate = output / f"{name}-attempt-{attempt:02d}.log"
        if not candidate.exists():
            return candidate
        attempt += 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants-root", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--preserved", type=Path, required=True)
    parser.add_argument("--tiny", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--seed", type=Path, help="completed importer output for prepared-seed cases")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--experiments", nargs="+", choices=sorted(EXPERIMENTS), default=["f02-preserved", "f04-native"])
    parser.add_argument("--resume", action="store_true", help="continue an existing interrupted batch")
    args = parser.parse_args(argv)
    variants_root = args.variants_root.resolve()
    output = args.output.resolve()
    if output.exists() and not args.resume:
        raise SystemExit(f"output exists; use --resume only for an interrupted batch: {output}")
    for name in ("base", "f02", "f04", "both"):
        if not (variants_root / name / "obsidian2sql.py").is_file():
            raise SystemExit(f"missing source variant: {variants_root / name}")
    if args.resume:
        try:
            state = json.loads((output / "notification.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"--resume requires notification.json: {exc}") from exc
        if state.get("format") != FORMAT or state.get("experiments") != args.experiments or state.get("pairs") != args.pairs:
            raise SystemExit("--resume batch metadata differs from the original run")
        state["status"] = "running"
    else:
        output.mkdir(parents=True, mode=0o700)
        state = {
            "format": FORMAT,
            "status": "running",
            "started_at": time.time(),
            "variants_root": str(variants_root),
            "pairs": args.pairs,
            "experiments": args.experiments,
            "steps": [],
        }

    def save() -> None:
        atomic_json(output / "notification.json", state)

    save()
    try:
        for name in args.experiments:
            specification = EXPERIMENTS[name]
            experiment_output = output / name
            previous_steps = [step for step in state["steps"] if step.get("name") == name]
            command = [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("notrios_p7c_benchmark.py")),
                "--left-name",
                specification["left"],
                "--right-name",
                specification["right"],
                "--left-source",
                str(variants_root / specification["left"]),
                "--right-source",
                str(variants_root / specification["right"]),
                "--vault",
                str(args.vault.resolve()),
                "--raw",
                str(args.raw.resolve()),
                "--preserved",
                str(args.preserved.resolve()),
                "--tiny",
                str(args.tiny.resolve()),
                "--media",
                str(args.media.resolve()),
                "--output",
                str(experiment_output),
                "--pairs",
                str(args.pairs),
                "--cases",
                *specification["cases"],
            ]
            if args.seed is not None:
                command.extend(["--seed", str(args.seed.resolve())])
            if args.resume and (experiment_output / "results.json").is_file():
                command.append("--resume")
            log = next_batch_log(output, name)
            with log.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    command,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
            step = {
                "name": name,
                "command": command,
                "returncode": result.returncode,
                "log": str(log.relative_to(output)),
                "output": str(experiment_output.relative_to(output)),
                "resume_validation": bool(args.resume and (experiment_output / "results.json").is_file()),
            }
            state["steps"].append(step)
            save()
            if result.returncode != 0:
                state["status"] = "failed"
                state["reason"] = f"experiment {name} failed"
                save()
                print(f"P7C_LONG_BATCH_FAILED output={output}", flush=True)
                return result.returncode or 1
        state["status"] = "complete"
        state["completed_at"] = time.time()
        save()
        print(f"P7C_LONG_BATCH_COMPLETE output={output}", flush=True)
        return 0
    except BaseException as exc:
        state["status"] = "failed"
        state["reason"] = repr(exc)
        save()
        print(f"P7C_LONG_BATCH_FAILED output={output}", flush=True)
        raise
    finally:
        # Keep a purpose-labelled, non-deleting inventory even when the parent
        # process is interrupted or one experiment fails.  The manifest is
        # evidence for later disk-cleanup decisions; this driver never deletes.
        subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("notrios_p7a_artifacts.py")),
                "--root",
                str(output),
            ],
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
