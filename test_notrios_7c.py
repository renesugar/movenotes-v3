#!/usr/bin/env python3
"""Tests for the resumed 7c trial harness's checkpoints and evidence."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

import notrios_7c_trials as trials  # noqa: E402


class TrialStageTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="notrios-7c-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        binary = Path(sys.executable)
        (self.root / "config.json").write_text(json.dumps({
            "notriosctl": str(binary),
            "notriosctl_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "notriosctl_revision": "test",
        }), encoding="utf-8")
        self.trials = trials.Trials(self.root)

    def _stage(self, text: str) -> Path:
        script = f"import sys;open(sys.argv[1],'w').write({text!r})"
        with contextlib.redirect_stdout(io.StringIO()):
            return self.trials.stage(
                "route/tier/write", [sys.executable, "-c", script, "{stage}/out.txt"],
                inputs={"text": text}, outputs={"out": "{stage}/out.txt"},
            )

    def test_a_changed_input_runs_into_a_fresh_directory_and_keeps_the_old_one(self) -> None:
        first = self._stage("one")
        self.assertEqual(self._stage("one"), first)
        self.assertEqual(self.trials.current("route/tier/write"), first)
        second = self._stage("two")
        self.assertNotEqual(second, first)
        self.assertEqual((first / "out.txt").read_text(), "one")
        self.assertEqual(self.trials.current("route/tier/write"), second)
        measured = json.loads((second / "measurement.json").read_text())["outputs"]["out"]
        self.assertEqual((measured["file_count"], measured["byte_count"]), (1, 3))

    def test_a_failed_attempt_is_kept_and_not_reused(self) -> None:
        # The same command fails once, then succeeds, as a retry after a fix
        # outside the stage's inputs would.
        marker = self.root / "failed-once"
        script = ("import os,sys;first=not os.path.exists(sys.argv[2]);open(sys.argv[2],'w').close();"
                  "open(sys.argv[1],'w').write('x');sys.exit(3 if first else 0)")

        def attempt() -> Path:
            with contextlib.redirect_stdout(io.StringIO()):
                return self.trials.stage(
                    "route/tier/retry", [sys.executable, "-c", script, "{stage}/out.txt", str(marker)],
                    inputs={}, outputs={"out": "{stage}/out.txt"},
                )

        with self.assertRaises(trials.StageFailed):
            attempt()
        with self.assertRaises(SystemExit):
            self.trials.current("route/tier/retry")
        # The retry archives the failed attempt whole, and does not reuse it.
        folder = attempt()
        self.assertEqual(self.trials.current("route/tier/retry"), folder)
        attempts = list((folder / "attempts").iterdir())
        self.assertEqual(len(attempts), 1)
        failed = json.loads((attempts[0] / "checkpoint.json").read_text())
        self.assertEqual((failed["status"], failed["returncode"]), ("failed", 3))

    def test_the_summary_holds_no_path(self) -> None:
        self._stage("private text")
        with contextlib.redirect_stdout(io.StringIO()):
            summary = self.trials.summary()
        text = json.dumps(summary)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn("out.txt", text)
        self.assertNotIn("private text", text)
        self.assertEqual([stage["current"] for stage in summary["stages"]], [True])

    def test_a_child_stage_covers_only_its_own_source(self) -> None:
        convert = trials.consumer_hashes((), "convert-child")
        live = trials.consumer_hashes((), "live-site-child")
        self.assertEqual(set(convert), {"harness:convert-child"})
        self.assertNotEqual(convert["harness:convert-child"], live["harness:live-site-child"])
        self.assertNotIn("scripts/notrios_7c_trials.py", trials.consumer_hashes(("notrios2sql",)))


if __name__ == "__main__":
    unittest.main()
