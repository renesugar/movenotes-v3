"""Documentation checks: every relative link in the repository's documents resolves."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT_DIR = Path(__file__).resolve().parent
CHECKER = PROJECT_DIR / "scripts" / "check_doc_links.py"


def run_checker(root):
    return subprocess.run([sys.executable, "-B", str(CHECKER), "--root", str(root)],
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


class DocumentationLinkTest(unittest.TestCase):
    def test_every_relative_link_in_the_repository_resolves(self):
        result = run_checker(PROJECT_DIR)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_broken_links_are_refused_and_code_and_fixtures_are_not_links(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "docs").mkdir()
            (root / "testdata" / "vault").mkdir(parents=True)
            (root / "docs" / "guide.md").write_text(
                "# Guide\n\n## Run it — twice (2026-10-22/23)\n\nText.\n", encoding="utf-8")
            (root / "README.md").write_text(
                "# Top\n\n"
                "[good](docs/guide.md#run-it--twice-2026-10-2223) and [self](#top)\n"
                "[web](https://example.com/missing.md) [joplin](:/0123abcd) ![img](docs/guide.md \"t\")\n"
                "[missing file](docs/none.md)\n"
                "[missing anchor](docs/guide.md#run-it--twice-2026-102223)\n"
                "[outside](../elsewhere/README.md)\n"
                "[absolute](/docs/guide.md)\n"
                "`[code span](docs/none.md)`\n\n"
                "```\n[fenced](docs/none.md)\n```\n", encoding="utf-8")
            (root / "testdata" / "vault" / "Note.md").write_text("[note link](Nowhere.md)\n", encoding="utf-8")
            (root / "testdata" / "README.md").write_text("[fixture](vault/Note.md)\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            result = run_checker(root)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "README.md:5: no such file: docs/none.md",
            "README.md:6: no heading for #run-it--twice-2026-102223 in docs/guide.md",
            "README.md:7: link leaves the repository: ../elsewhere/README.md",
            "README.md:8: site-absolute link /docs/guide.md",
        ])
        self.assertIn("checked 3 document(s): 4 broken link(s)", result.stderr)


if __name__ == "__main__":
    unittest.main()
