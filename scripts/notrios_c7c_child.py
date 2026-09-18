#!/usr/bin/env python3
"""Run one monitored command and durably publish its exit status.

The monitor can be disconnected while this helper remains alive.  The helper
writes the receipt before exiting, so a reconnecting monitor can recover the
actual command status after a PIDFD notification without polling or guessing
from an old result file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import uuid


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:12])
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(_canonical(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--invocation", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --")
    started = time.time()
    child = subprocess.Popen(command)
    returncode = child.wait()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {
        "status": "complete",
        "invocation_id": args.invocation,
        "pid": child.pid,
        "started": started,
        "finished": time.time(),
        "returncode": int(returncode),
        "child_rusage": {
            "max_rss_kib": int(usage.ru_maxrss),
            "user_seconds": float(usage.ru_utime),
            "system_seconds": float(usage.ru_stime),
        },
    }
    _atomic_json(Path(args.receipt).resolve(), receipt)
    return int(returncode)


if __name__ == "__main__":
    raise SystemExit(main())
