"""Documentation checks: every fenced example is registered, and the executed ones run."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest

PROJECT_DIR = Path(__file__).resolve().parent.parent
CHECKER = PROJECT_DIR / "scripts" / "check_doc_examples.py"

sys.path.insert(0, str(PROJECT_DIR / "scripts"))
from check_doc_examples import fences  # noqa: E402


def run_checker(root, *args, env=None):
    environment = {key: value for key, value in os.environ.items() if key != "NOTRIOSCTL"}
    environment.update(env or {}, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-B", str(CHECKER), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=900, env=environment)


def make_repository(root, readme, registry, files=None):
    (root / "docs").mkdir()
    (root / "README.md").write_text(readme, encoding="utf-8")
    (root / "docs" / "examples.json").write_text(json.dumps(registry), encoding="utf-8")
    for name, text in (files or {}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def entry(block, **fields):
    return {key: block[key] for key in ("ordinal", "heading", "language", "sha256")} | fields


class DocumentationExampleTest(unittest.TestCase):
    def test_every_example_in_the_repository_is_registered_and_the_executed_ones_pass(self):
        result = run_checker(PROJECT_DIR)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FAIL", result.stdout)
        self.assertIn(" 0 failed, 0 skipped", result.stderr)

    def test_fences_are_found_with_their_heading_language_and_text(self):
        blocks = fences("# A\n\n```bash\necho 1\n```\n\n## B\n\n  ~~~~\n  x\n   y\n  ~~~~\n\n```\nno end\n")
        self.assertEqual([(b["ordinal"], b["line"], b["heading"], b["language"], b["body"]) for b in blocks], [
            (1, 3, "A", "bash", "echo 1\n"),
            (2, 9, "B", "", "x\n y\n"),
            (3, 14, "B", "", "no end\n\n"),
        ])

    def test_a_changed_an_unregistered_and_a_stale_example_are_refused_before_anything_runs(self):
        readme = ("# Top\n\n```\necho one > ~/one.txt\n```\n\n## Next\n\n```bash\ntrue\n```\n\n"
                  "```\nnot registered\n```\n")
        blocks = fences(readme)
        registry = {"pages": {
            "README.md": {"examples": [
                entry(blocks[0], state="executed") | {"sha256": "0" * 64},
                entry(blocks[1], state="executed"),
                {"ordinal": 7, "heading": "Gone", "language": "", "sha256": "0" * 64, "state": "executed"}]},
            "docs/gone.md": {"examples": []}}}
        with tempfile.TemporaryDirectory() as work:
            make_repository(Path(work), readme, registry)
            result = run_checker(work)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "README.md:3: example 1 (Top) changed: sha256 differ from docs/examples.json; "
            "re-run it and register it again",
            "README.md:13: example 3 (Next) is not registered in docs/examples.json",
            "README.md: stale entry for example 7: the page has no such fence",
            "docs/gone.md: stale entry: no fenced example on that page",
        ])
        self.assertIn("3 fenced example(s) in 1 page(s)", result.stderr)

    def test_examples_share_a_home_and_failures_missing_tools_and_servers_are_reported(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        readme = ("# Run\n\n"
                  "```\necho <value> > ~/one.txt\n```\n\n"
                  "```\ntest \"$(cat ~/one.txt)\" = one\n```\n\n"
                  "```\ntest -f ~/seeded/a.txt\ntest ! -e ~/one.txt\n```\n\n"
                  "```\nfalse\necho never\n```\n\n"
                  "```\nnotriosctl --version\n```\n\n"
                  "```\ntest -L ~/projects/hugo-theme-ledger\n```\n\n"
                  f"```\npython3 -m http.server {port} --bind 127.0.0.1 --directory ~\n```\n\n"
                  "```\nsynopsis <with> placeholders\n```\n")
        blocks = fences(readme)
        registry = {"pages": {"README.md": {
            "homes": {"other": {"seed": {"seeded": "fixtures"}}},
            "substitute": {"<value>": "one"},
            "examples": [
                entry(blocks[0], state="executed"),
                entry(blocks[1], state="executed"),
                entry(blocks[2], state="executed", home="other"),
                entry(blocks[3], state="executed"),
                entry(blocks[4], state="tools", tools=["notriosctl"]),
                entry(blocks[5], state="tools", tools=["ledger-theme"]),
                entry(blocks[6], state="executed", home="other", serves=f"http://127.0.0.1:{port}/seeded/a.txt"),
                entry(blocks[7], state="unverified", reason="a synopsis")]}}}
        with tempfile.TemporaryDirectory() as work:
            make_repository(Path(work), readme, registry, {"fixtures/a.txt": "seeded\n", "theme/layouts/a.html": ""})
            gate = run_checker(work)
            tools = run_checker(work, "--with-tools", env={"LEDGER_THEME": str(Path(work) / "theme")})
        self.assertEqual(gate.returncode, 1, gate.stdout + gate.stderr)
        self.assertEqual(re.findall(r"^(PASS|FAIL|SKIP) README.md:(\d+) example (\d+)", gate.stdout, re.M),
                         [("PASS", "3", "1"), ("PASS", "7", "2"), ("PASS", "11", "3"), ("FAIL", "16", "4"),
                          ("PASS", "29", "7")])
        self.assertIn("exited with status 1", gate.stdout)
        self.assertNotIn("never", gate.stdout)
        self.assertIn("ran 5 example(s): 4 passed, 1 failed, 0 skipped", gate.stderr)
        self.assertIn("SKIP README.md:21 example 5: missing notriosctl", tools.stdout)
        self.assertIn("SKIP README.md:25 example 6: after skipped example 5", tools.stdout)
        self.assertIn("ran 7 example(s): 4 passed, 1 failed, 2 skipped", tools.stderr)


if __name__ == "__main__":
    unittest.main()
