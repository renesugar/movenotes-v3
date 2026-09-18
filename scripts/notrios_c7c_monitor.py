#!/usr/bin/env python3
"""Wait once for a C7c process and write one terminal notification.

The monitor uses a Linux PIDFD and ``select``.  It never polls a checkpoint,
reads a log repeatedly, or wakes on a short timer.  A private monitor state
file records the child identity and command digest so a parent can reconnect
without allowing two live writers for one output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
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


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _proc_start_ticks(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return None
    closing = text.rfind(")")
    if closing < 0:
        return None
    fields = text[closing + 2 :].split()
    # The slice starts at field 3 (state), and starttime is field 22.
    return fields[19] if len(fields) > 19 else None


def _child_alive(pid: int, start_ticks: str | None) -> bool:
    current = _proc_start_ticks(pid)
    return current is not None and (start_ticks is None or current == start_ticks)


def _wait_once(pid: int) -> None:
    if not hasattr(os, "pidfd_open"):
        raise RuntimeError("Linux PIDFD support is required")
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError as exc:
        # The helper may have exited between identity validation and PIDFD
        # acquisition.  Its durable receipt is checked by _load_summary.
        return
    try:
        # One event-driven wait.  There is deliberately no timeout or loop.
        select.select([descriptor], [], [])
    finally:
        os.close(descriptor)


def _monitor_paths(checkpoint: Path) -> tuple[Path, Path, Path]:
    return (
        checkpoint.with_name(checkpoint.name + ".monitor.json"),
        checkpoint.with_name(checkpoint.name + ".monitor.lock"),
        checkpoint.with_name(checkpoint.name + ".monitor.receipt.json"),
    )


def _acquire_lock(
    lock: Path,
    state_path: Path,
    state: dict[str, object],
    *,
    reconnect_pid: int | None = None,
) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for _attempt in range(2):
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            old = _read_json(state_path)
            if isinstance(old, dict):
                if old.get("status") == "running" and old.get("monitor_run_id") != state.get("monitor_run_id"):
                    # The first monitor may not have spawned its child yet;
                    # its lock still represents a live writer.
                    raise RuntimeError("a live C7c monitor already owns this output")
                try:
                    old_pid = int(old.get("pid", 0))
                except (TypeError, ValueError):
                    old_pid = 0
                if old_pid and _child_alive(old_pid, str(old.get("proc_start_ticks") or "")):
                    if reconnect_pid is None or old_pid != reconnect_pid:
                        raise RuntimeError("a live C7c monitor already owns this output")
            try:
                lock.unlink()
            except FileNotFoundError:
                continue
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical(state) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return
    raise RuntimeError("could not acquire C7c monitor lock")


def _load_summary(
    result: Path,
    checkpoint: Path,
    returncode: int | None,
    state: dict[str, object],
    receipt_path: Path,
) -> dict[str, object]:
    """Accept only the result produced by this invocation.

    A logical comparison run may resume with the same ``run_id``.  The
    invocation receipt and checkpoint/result generations distinguish that
    legitimate resume from an old successful result left behind by a newly
    failed or no-op command.
    """

    base = {
        "returncode": returncode,
        "monitor_run_id": state.get("monitor_run_id"),
        "pid": state.get("pid"),
        "command_sha256": state.get("command_sha256"),
        "finished": time.time(),
        "source_content_included": False,
    }
    receipt = _read_json(receipt_path)
    if receipt is None:
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "missing_exit_receipt"}
    if receipt.get("invocation_id") != state.get("monitor_run_id"):
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "exit_receipt_mismatch"}
    receipt_code = receipt.get("returncode")
    if type(receipt_code) is not int:
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "invalid_exit_receipt"}
    child_rusage = receipt.get("child_rusage")
    if isinstance(child_rusage, dict):
        # The helper is the only child of the monitor, so RUSAGE_CHILDREN is
        # a durable peak for the comparison process.  Copy only typed scalar
        # fields into the notification; never expose command or source data.
        safe_rusage = {
            key: child_rusage[key]
            for key in ("max_rss_kib", "user_seconds", "system_seconds")
            if key in child_rusage and isinstance(child_rusage[key], (int, float))
            and not isinstance(child_rusage[key], bool)
        }
        if safe_rusage:
            base["child_rusage"] = safe_rusage
    if returncode is None:
        returncode = receipt_code
        base["returncode"] = returncode
    if returncode != receipt_code:
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "exit_receipt_mismatch"}
    if returncode != 0:
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "child_failed"}
    checkpoint_value = _read_json(checkpoint)
    result_value = _read_json(result)
    if checkpoint_value is None or result_value is None:
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "missing_or_invalid_result"}
    if checkpoint_value.get("status") != "complete" or result_value.get("status") != "complete":
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "incomplete_result"}
    checkpoint_run_id = checkpoint_value.get("run_id")
    if not isinstance(checkpoint_run_id, str) or result_value.get("run_id") != checkpoint_run_id:
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "run_id_mismatch"}
    checkpoint_fingerprint = checkpoint_value.get("fingerprint")
    result_fingerprint = result_value.get("fingerprint")
    if not isinstance(checkpoint_fingerprint, dict) or not isinstance(result_fingerprint, dict):
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "fingerprint_missing"}
    for key in ("code_sha256", "profile_sha256"):
        if result_fingerprint.get(key) != checkpoint_fingerprint.get(key):
            return {**base, "status": "blocked", "semantic_equal": False, "reason": "fingerprint_mismatch"}
    checkpoint_generation = _file_sha256(checkpoint)
    result_generation = _file_sha256(result)
    before_checkpoint = state.get("checkpoint_before_sha256")
    before_result = state.get("result_before_sha256")
    generation_changed = (
        checkpoint_generation != before_checkpoint
        or result_generation != before_result
    )
    # A checkpoint that was already marked failed is an explicit resume
    # boundary.  It can legitimately retain the same logical run and result
    # bytes when all completed stages are reused.  A previously complete
    # checkpoint with unchanged outputs is stale and must be rejected.
    prior_status = state.get("prior_checkpoint_status")
    if (
        not generation_changed
        and prior_status == "complete"
        and checkpoint_run_id == state.get("prior_checkpoint_run_id")
    ):
        return {**base, "status": "blocked", "semantic_equal": False, "reason": "stale_result"}
    base["checkpoint_generation_sha256"] = checkpoint_generation
    base["result_generation_sha256"] = result_generation
    base["generation_changed"] = generation_changed
    return {
        **base,
        "status": "complete",
        "semantic_equal": bool(result_value.get("semantic_equal")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="PID recorded by the long-running comparison")
    parser.add_argument("--checkpoint", required=True, help="Private checkpoint JSON")
    parser.add_argument("--result", required=True, help="Private comparison result JSON")
    parser.add_argument("--notification", required=True, help="Private terminal notification JSON")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Optional command to launch after --")
    args = parser.parse_args(argv)
    checkpoint = Path(args.checkpoint).resolve()
    result = Path(args.result).resolve()
    notification = Path(args.notification).resolve()
    state_path, lock_path, receipt_path = _monitor_paths(checkpoint)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if args.pid is None and not command:
        parser.error("provide --pid or a command after --")
    if args.pid is not None and command:
        parser.error("provide --pid or a command after --, not both")

    prior_checkpoint = _read_json(checkpoint)
    prior_run_id = prior_checkpoint.get("run_id") if isinstance(prior_checkpoint, dict) else None
    prior_status = prior_checkpoint.get("status") if isinstance(prior_checkpoint, dict) else None
    monitor_run_id = uuid.uuid4().hex
    command_digest = hashlib.sha256(_canonical(command).encode("utf-8")).hexdigest() if command else None
    state: dict[str, object] = {
        "monitor_run_id": monitor_run_id,
        "command_sha256": command_digest,
        "checkpoint": str(checkpoint),
        "result": str(result),
        "notification": str(notification),
        "pid": args.pid,
        "proc_start_ticks": None,
        "started": time.time(),
        "prior_checkpoint_run_id": prior_run_id,
        "prior_checkpoint_status": prior_status,
        "checkpoint_before_sha256": _file_sha256(checkpoint),
        "result_before_sha256": _file_sha256(result),
        "exit_receipt": str(receipt_path),
        "status": "running",
    }
    try:
        reconnect_state = _read_json(state_path) if args.pid is not None else None
        if args.pid is not None:
            if reconnect_state is None or reconnect_state.get("pid") != args.pid:
                raise RuntimeError("reconnect metadata does not match PID")
            if not _child_alive(args.pid, str(reconnect_state.get("proc_start_ticks") or "")):
                receipt = _read_json(Path(str(reconnect_state.get("exit_receipt") or "")))
                if receipt is None or receipt.get("invocation_id") != reconnect_state.get("monitor_run_id"):
                    raise RuntimeError("reconnect PID identity is not live")
            state = reconnect_state
            receipt_path = Path(str(state.get("exit_receipt") or receipt_path)).resolve()
        _acquire_lock(lock_path, state_path, state, reconnect_pid=args.pid)
        child: subprocess.Popen[bytes] | None = None
        if args.pid is None:
            helper = Path(__file__).with_name("notrios_c7c_child.py").resolve()
            wrapped = [
                sys.executable, "-B", str(helper),
                "--receipt", str(receipt_path),
                "--invocation", str(monitor_run_id),
                "--", *command,
            ]
            child = subprocess.Popen(wrapped)
            state["pid"] = child.pid
            state["proc_start_ticks"] = _proc_start_ticks(child.pid)
            _atomic_json(state_path, state)
            pid = child.pid
        else:
            pid = args.pid
        _wait_once(pid)
        returncode = child.wait() if child is not None else None
        summary = _load_summary(result, checkpoint, returncode, state, receipt_path)
        state["status"] = summary["status"]
        state["finished"] = summary["finished"]
        state["checkpoint_after_sha256"] = _file_sha256(checkpoint)
        state["result_after_sha256"] = _file_sha256(result)
        _atomic_json(state_path, state)
        _atomic_json(notification, summary)
        print(json.dumps(summary, sort_keys=True), flush=True)
        return 0 if summary["status"] == "complete" else 1
    except Exception as exc:
        summary = {
            "status": "blocked",
            "semantic_equal": False,
            "reason": type(exc).__name__,
            "monitor_run_id": monitor_run_id,
            "command_sha256": command_digest,
            "finished": time.time(),
            "source_content_included": False,
        }
        try:
            _atomic_json(notification, summary)
        except OSError:
            pass
        print(json.dumps(summary, sort_keys=True), file=sys.stderr, flush=True)
        return 1
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
