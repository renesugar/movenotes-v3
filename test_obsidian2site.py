#!/usr/bin/env python3
"""Tests for the large-vault Obsidian to Hugo/Bluge/Pagefind converter."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from datetime import datetime, timezone
from pathlib import Path

import obsidian2site

PROJECT_DIR = Path(__file__).resolve().parent


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROJECT_DIR / "obsidian2site.py"), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def read_json_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    first, body = text.split("\n", 1)
    return json.loads(first), body


class ObsidianSiteGenerationTest(unittest.TestCase):
    def test_generates_scalable_hugo_project_with_search_tags_and_links(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            (vault / "Folder").mkdir(parents=True)
            (vault / "assets").mkdir()
            (vault / "resources").mkdir()
            (vault / ".obsidian").mkdir()
            (vault / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
            (vault / "assets" / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
            (vault / "resources" / "paper.pdf").write_bytes(b"%PDF-1.7\ncontent")
            (vault / "Other.md").write_text(
                "# Other\n\nThe quick brown fox and the codec.\n",
                encoding="utf-8",
            )
            (vault / "Folder" / "Note.md").write_text(
                "---\n"
                'title: "First Note"\n'
                "date: 2025-01-02 03:04:05\n"
                "tags:\n  - Alpha\n"
                "custom: ignored-for-hugo\n"
                "---\n"
                "# First Note\n\n"
                "This is a sample #Beta note about codecs and video.\n\n"
                "See [[Other|the other note]] and ![[../assets/picture.png]].\n\n"
                "Inline code: `[[Other]]`\n\n"
                "```markdown\n[[Other]]\n{{< unknown >}}\n```\n\n"
                "Literal shortcode: {{< unknown >}}\n"
                "Mention @Some_User but not person@example.com or @way_too_long_username.\n",
                encoding="utf-8",
            )

            result = run(
                "--input", str(vault), "--output", str(site),
                "--progress-every", "1", "--workers", "2",
            )
            self.assertIn("converted 2 of 2 note(s)", result.stdout)
            self.assertTrue((site / "hugo.toml").is_file())
            hugo_config = (site / "hugo.toml").read_text(encoding="utf-8")
            self.assertIn('locale = "en-US"', hugo_config)
            # Hugo deprecated languageCode in v0.158; using it warns on build.
            self.assertNotIn("languageCode", hugo_config)
            # uglyURLs would move the theme's own pages to /search.html, which
            # its templates never link to; notes carry an explicit .html url.
            self.assertNotIn("uglyURLs", hugo_config)
            config = tomllib.loads(hugo_config)
            # Ledger's surfaces are taxonomy-driven, so neither kind may be
            # disabled — the Relearn build disabled both.
            self.assertNotIn("disableKinds", config)
            self.assertEqual(
                config["taxonomies"], {"category": "categories", "tag": "tags"}
            )
            self.assertFalse(config["capitalizeListTitles"])
            self.assertEqual(config["params"]["mainSections"], ["notes"])
            self.assertEqual(config["params"]["search"]["backend"], "bluge")
            self.assertEqual(config["params"]["search"]["endpoint"], "/api/search")
            # A generated archive must not reach a font CDN, or paint 166k
            # striped hero placeholders.
            self.assertFalse(config["params"]["googleFonts"])
            self.assertFalse(config["params"]["post"]["heroPlaceholder"])
            # Both unbounded surfaces are capped: either can hold the archive.
            self.assertEqual(config["params"]["scale"]["maxHomePagerPages"], 500)
            self.assertEqual(config["params"]["scale"]["maxSectionPagerPages"], 500)
            self.assertEqual(config["params"]["taxonomyPageLimit"], 25)
            self.assertEqual(config["params"]["movenotesSearchBackend"], "both")
            self.assertRegex(config["params"]["movenotesBuildId"], r"^[0-9a-f]{16}$")
            # The theme owns every shell surface now; the Relearn build had to
            # override menu, search dependencies, heading and content partials.
            for orphan in (
                ("partials", "menu.html"),
                ("partials", "content.html"),
                ("partials", "heading.html"),
                ("partials", "custom-header.html"),
                ("partials", "dependencies", "search.html"),
                ("partials", "dependencies", "search-lunr.html"),
                ("partials", "sidebar", "element", "movenotes-search.html"),
                ("_default", "baseof.html"),
            ):
                self.assertFalse(
                    (site / "layouts" / Path(*orphan)).exists(),
                    f"layouts/{'/'.join(orphan)} should not be generated",
                )
            self.assertIn("module movenotes/generated-site", (site / "go.mod").read_text(encoding="utf-8"))
            self.assertTrue((site / "server" / "main.go").is_file())
            self.assertIn("github.com/blugelabs/bluge v0.2.2", (site / "server" / "go.mod").read_text(encoding="utf-8"))
            self.assertTrue((site / "server" / "search-source.jsonl").is_file())
            self.assertTrue((site / "content" / "_index.md").is_file())
            self.assertTrue((site / "content" / "search.md").is_file())
            self.assertTrue((site / "content" / "browse-tags.md").is_file())
            self.assertTrue((site / "content" / "about.md").is_file())
            home_meta, home_body = read_json_frontmatter(site / "content" / "_index.md")
            self.assertEqual(
                home_meta["date"][:10],
                datetime.now(timezone.utc).date().isoformat(),
            )
            self.assertEqual(home_meta["date"], home_meta["lastmod"])
            # Home is the theme's own view — a primed search bar over the newest
            # notes — so it carries no body.
            self.assertEqual(home_body.strip(), "")
            about_meta, about_body = read_json_frontmatter(site / "content" / "about.md")
            self.assertEqual(about_meta["title"], "Getting Started")
            self.assertEqual(about_meta["layout"], "about")
            self.assertEqual(about_meta["url"], "/about/")
            self.assertIn("movenotes-start", about_body)
            search_meta, _ = read_json_frontmatter(site / "content" / "search.md")
            self.assertEqual(search_meta["layout"], "search")
            self.assertEqual(search_meta["url"], "/search/")
            tags_meta, tags_body = read_json_frontmatter(site / "content" / "browse-tags.md")
            self.assertEqual(tags_meta["layout"], "browse-tags")
            self.assertEqual(tags_meta["url"], "/browse-tags/")
            self.assertIn("movenotes-tags", tags_body)
            self.assertEqual(
                (vault / "assets" / "picture.png").read_bytes(),
                (site / "static" / "vault-assets" / "assets" / "picture.png").read_bytes(),
            )
            self.assertEqual(
                b"%PDF-1.7\ncontent",
                (site / "static" / "vault-assets" / "resources" / "paper.pdf").read_bytes(),
            )
            self.assertFalse((site / "static" / "vault-assets" / ".obsidian" / "app.json").exists())

            metadata, body = read_json_frontmatter(site / "content" / "notes" / "folder" / "note.md")
            self.assertEqual(metadata["title"], "First Note")
            self.assertEqual(metadata["date"], "2025-01-02T03:04:05Z")
            self.assertEqual(metadata["url"], "/notes/folder/note.html")
            self.assertTrue(metadata["hidden"])
            self.assertNotIn("custom", metadata)
            self.assertNotIn("movenotes_tags", metadata)
            self.assertEqual(metadata["movenotes_explicit_tags"], ["alpha", "beta"])
            self.assertNotIn("# First Note", body)
            self.assertIn("[the other note](../other.html)", body)
            self.assertIn("![picture.png](../../vault-assets/assets/picture.png)", body)
            self.assertIn("`[[Other]]`", body)
            self.assertIn("```markdown\n[[Other]]", body)
            self.assertNotIn("{{< unknown >}}", body)
            self.assertIn("&#123;&#123;&lt; unknown >", body)
            self.assertIn(
                "Mention [@Some_User](https://x.com/Some_User)", body
            )
            self.assertIn("person@example.com", body)
            self.assertIn("@way_too_long_username", body)

            # CSS and JS reach every page through the theme's extraCSS/extraJS
            # hooks; the Relearn build injected them with a custom-header
            # partial override.
            self.assertEqual(config["params"]["extraCSS"], ["/css/movenotes-site.css"])
            self.assertEqual(config["params"]["extraJS"], ["/js/movenotes-nav.js"])
            browse_tags_layout = (
                site / "layouts" / "browse-tags.html"
            ).read_text(encoding="utf-8")
            self.assertIn('{{ define "main" }}', browse_tags_layout)
            self.assertIn("ledger-heading", browse_tags_layout)
            navigation_script = (
                site / "static" / "js" / "movenotes-nav.js"
            ).read_text(encoding="utf-8")
            self.assertIn("rel = 'prefetch'", navigation_script)
            self.assertIn("pointerover", navigation_script)
            self.assertIn("url.pathname.includes('/notes/')", navigation_script)

            # The Pagefind indexing contract moved into the theme: one
            # data-pagefind-body on note articles scopes the index, so the
            # generated project needs neither a content partial nor
            # exclude_selectors to keep the shell and standalone pages out.
            pagefind_config = (site / "pagefind.yml").read_text(encoding="utf-8")
            self.assertIn("site: public", pagefind_config)
            self.assertNotIn("exclude_selectors", pagefind_config)
            search = (site / "layouts" / "shortcodes" / "movenotes-search.html").read_text(encoding="utf-8")
            self.assertIn("pagefind/pagefind.js", search)
            self.assertIn("api/health", search)
            self.assertIn("api/search", search)
            self.assertIn("searchServer", search)
            self.assertIn("since:YYYY-MM-DD", search)
            self.assertIn("searchExactTag", search)
            self.assertIn("tag-postings", search)
            self.assertIn("document_chunk_size", search)
            self.assertIn("Promise.all", search)
            self.assertIn("searchGeneration", search)
            self.assertIn(".preload(term)", search)
            self.assertIn("module.destroy", search)
            self.assertIn("metaCacheTag", search)
            tags_shortcode = (site / "layouts" / "shortcodes" / "movenotes-tags.html").read_text(encoding="utf-8")
            self.assertIn("?tag=${encodeURIComponent(tag)}", tags_shortcode)

            manifest = json.loads(
                (site / "static" / "movenotes" / "tags" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["version"], 2)
            self.assertGreaterEqual(manifest["total"], 5)
            self.assertIn("co", manifest["buckets"])
            self.assertTrue(manifest["posting_buckets"])
            self.assertEqual(manifest["document_chunk_size"], 512)
            codec_rows = json.loads(
                (site / "static" / "movenotes" / "tags" / "co.json").read_text(encoding="utf-8")
            )
            self.assertIn(["codec", 1], codec_rows)
            self.assertIn(["codecs", 1], codec_rows)
            posting_bucket = f"{obsidian2site._tag_posting_bucket('codec'):03x}"
            postings = json.loads(
                (
                    site / "static" / "movenotes" / "tag-postings" /
                    f"{posting_bucket}.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(len(postings["codec"]), 1)
            document_chunk = (
                site / "static" / "movenotes" / "documents" / "000000.json"
            )
            self.assertTrue(document_chunk.is_file())
            source_records = [json.loads(line) for line in (site / "server" / "search-source.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(source_records), 2)
            first_record = next(record for record in source_records if record["title"] == "First Note")
            self.assertEqual(first_record["url"], "/notes/folder/note.html")
            self.assertEqual(first_record["date"], "2025-01-02T03:04:05Z")
            self.assertNotIn("](", first_record["body"])

    def test_note_titles_are_never_added_to_sidebar_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-many-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            for index in range(250):
                (vault / f"Note {index}.md").write_text(
                    f"# Note {index}\n\nUniqueWord{index} shared text.\n", encoding="utf-8"
                )
            run("--input", str(vault), "--output", str(site), "--progress-every", "0")
            hugo_config = (site / "hugo.toml").read_text(encoding="utf-8")
            # No note may be named anywhere in the configuration: the theme's
            # sidebar is byte-identical on every page and never enumerates
            # pages, and nothing here may reintroduce a per-note menu.
            self.assertNotIn("Note 0", hugo_config)
            self.assertNotIn("note-0", hugo_config)
            self.assertNotIn("[menus]", hugo_config)
            self.assertFalse((site / "layouts" / "partials" / "menu.html").exists())
            self.assertEqual(len(list((site / "content" / "notes").glob("*.md"))), 251)

    def test_long_and_colliding_names_are_shortened_deterministically(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-names-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            long_name = "🕊" * 60
            (vault / f"{long_name}.md").write_text("Long body", encoding="utf-8")
            (vault / "Case.md").write_text("One", encoding="utf-8")
            (vault / "case.md").write_text("Two", encoding="utf-8")
            run("--input", str(vault), "--output", str(site), "--progress-every", "0")
            outputs = [path for path in (site / "content" / "notes").glob("*.md") if path.name != "_index.md"]
            self.assertEqual(len(outputs), 3)
            self.assertTrue(all(len(path.name.encode("utf-8")) <= 180 for path in outputs))
            self.assertEqual(len({path.name.casefold() for path in outputs}), 3)

    def test_redundant_leading_headings_are_removed_without_touching_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-headings-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            (vault / "ATX.md").write_text(
                "---\ntitle: Same Title\n---\n\n# Same Title\n\nBody text.\n",
                encoding="utf-8",
            )
            (vault / "Setext.md").write_text(
                "---\ntitle: Setext Title\n---\n\nSetext Title\n============\n\nMore body.\n",
                encoding="utf-8",
            )
            (vault / "Different.md").write_text(
                "---\ntitle: Frontmatter Title\n---\n\n# Different Heading\n\nKeep me.\n",
                encoding="utf-8",
            )
            run("--input", str(vault), "--output", str(site), "--progress-every", "0")
            _meta, atx = read_json_frontmatter(site / "content" / "notes" / "atx.md")
            _meta, setext = read_json_frontmatter(site / "content" / "notes" / "setext.md")
            _meta, different = read_json_frontmatter(site / "content" / "notes" / "different.md")
            self.assertEqual(atx, "Body text.\n")
            self.assertEqual(setext, "More body.\n")
            self.assertIn("# Different Heading", different)

    def test_existing_unrelated_output_requires_force(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-force-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            site.mkdir()
            (vault / "Note.md").write_text("Body", encoding="utf-8")
            (site / "keep.txt").write_text("unrelated", encoding="utf-8")
            result = run("--input", str(vault), "--output", str(site), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a generated movenotes site", result.stderr)
            run("--input", str(vault), "--output", str(site), "--force", "--progress-every", "0")
            self.assertTrue((site / ".movenotes-static-site.json").is_file())


    def test_build_runs_hugo_before_pagefind(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-build-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            log = root / "build.log"
            vault.mkdir()
            (vault / "Note.md").write_text("# Note\n\nSearchable body.\n", encoding="utf-8")

            fake_hugo = root / "fake-hugo"
            fake_hugo.write_text(
                f"#!{sys.executable}\n"
                "import pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "destination = pathlib.Path(args[args.index('--destination') + 1])\n"
                "destination.mkdir(parents=True, exist_ok=True)\n"
                "(destination / 'index.html').write_text('<html><body>site</body></html>')\n"
                f"pathlib.Path({str(log)!r}).write_text('hugo\\n')\n",
                encoding="utf-8",
            )
            fake_hugo.chmod(0o755)

            fake_pagefind = root / "fake-pagefind"
            fake_pagefind.write_text(
                f"#!{sys.executable}\n"
                "import pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "site = pathlib.Path(args[args.index('--site') + 1])\n"
                "assert (site / 'index.html').is_file()\n"
                "(site / 'pagefind').mkdir(parents=True, exist_ok=True)\n"
                f"with pathlib.Path({str(log)!r}).open('a') as handle: handle.write('pagefind\\n')\n",
                encoding="utf-8",
            )
            fake_pagefind.chmod(0o755)

            run(
                "--input", str(vault), "--output", str(site),
                "--build", "--search-backend", "pagefind",
                "--hugo-bin", str(fake_hugo),
                "--pagefind-bin", str(fake_pagefind), "--progress-every", "0",
            )
            self.assertEqual(log.read_text(encoding="utf-8"), "hugo\npagefind\n")
            self.assertTrue((site / "public" / "pagefind").is_dir())


    def test_build_can_select_bluge_server_and_custom_go_binary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-go-build-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            log = root / "build.log"
            vault.mkdir()
            (vault / "Note.md").write_text("# Note\n\nServer search body.\n", encoding="utf-8")

            fake_hugo = root / "fake-hugo"
            fake_hugo.write_text(
                f"#!{sys.executable}\n"
                "import pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "destination = pathlib.Path(args[args.index('--destination') + 1])\n"
                "destination.mkdir(parents=True, exist_ok=True)\n"
                "(destination / 'index.html').write_text('<html><body>site</body></html>')\n"
                f"pathlib.Path({str(log)!r}).write_text('hugo\\n')\n",
                encoding="utf-8",
            )
            fake_hugo.chmod(0o755)

            fake_go = root / "fake-go"
            server_payload = (
                f"#!{sys.executable}\n"
                "import pathlib, sys\n"
                "assert '-index-only' in sys.argv\n"
                "pathlib.Path(sys.argv[sys.argv.index('-index') + 1] + '.stamp.json').write_text('{}')\n"
            )
            fake_go.write_text(
                f"#!{sys.executable}\n"
                "import pathlib, sys\n"
                f"log = pathlib.Path({str(log)!r})\n"
                "if sys.argv[1:] == ['mod', 'tidy']:\n"
                "    with log.open('a') as handle: handle.write('tidy\\n')\n"
                "    raise SystemExit(0)\n"
                "assert sys.argv[1:4] == ['build', '-o', 'movenotes-site-server']\n"
                "server = pathlib.Path('movenotes-site-server')\n"
                f"server.write_text({server_payload!r})\n"
                "server.chmod(0o755)\n"
                "with log.open('a') as handle: handle.write('go\\n')\n",
                encoding="utf-8",
            )
            fake_go.chmod(0o755)

            run(
                "--input", str(vault), "--output", str(site),
                "--build", "--search-backend", "bluge",
                "--hugo-bin", str(fake_hugo), "--go-bin", str(fake_go),
                "--progress-every", "0",
            )
            self.assertEqual(log.read_text(encoding="utf-8"), "hugo\ntidy\ngo\n")
            self.assertTrue((site / "server" / "movenotes-site-server").is_file())
            self.assertTrue((site / "server" / "bluge-index.stamp.json").is_file())
            generated_gitignore = (site / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("/server/bluge-index.stamp.json", generated_gitignore)

    def test_tag_bucket_matches_browser_algorithm_for_unicode(self) -> None:
        self.assertEqual(obsidian2site._tag_bucket("éclair"), "ec")
        self.assertEqual(obsidian2site._tag_bucket("日本語"), "u65e5")

    def test_tag_counts_match_exact_posting_lists(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-exact-tags-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            (vault / "One.md").write_text("Canadian news.\n", encoding="utf-8")
            (vault / "Two.md").write_text("Canadian culture.\n", encoding="utf-8")
            (vault / "Three.md").write_text("Canadians abroad.\n", encoding="utf-8")

            run("--input", str(vault), "--output", str(site), "--progress-every", "0")

            rows = dict(json.loads(
                (site / "static" / "movenotes" / "tags" / "ca.json")
                .read_text(encoding="utf-8")
            ))
            self.assertEqual(rows["canadian"], 2)
            self.assertEqual(rows["canadians"], 1)
            for tag, expected_count in (("canadian", 2), ("canadians", 1)):
                bucket = f"{obsidian2site._tag_posting_bucket(tag):03x}"
                postings = json.loads(
                    (
                        site / "static" / "movenotes" / "tag-postings" /
                        f"{bucket}.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(len(postings[tag]), expected_count)

            tags_ui = (
                site / "layouts" / "shortcodes" / "movenotes-tags.html"
            ).read_text(encoding="utf-8")
            search_ui = (
                site / "layouts" / "shortcodes" / "movenotes-search.html"
            ).read_text(encoding="utf-8")
            self.assertIn("?tag=${encodeURIComponent(tag)}", tags_ui)
            self.assertIn("postings[selectedTag]", search_ui)
            self.assertIn("result(s) with exact tag", search_ui)

    def test_links_plain_x_mentions_without_touching_other_contexts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-mentions-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            (vault / "Mentions.md").write_text(
                "Hello @valid_name and @A1.\n\n"
                "Email person@example.com.\n\n"
                "Existing [@linked](https://example.com/profile).\n\n"
                "URL https://example.com/@path.\n\n"
                "Inline `@code_name`.\n\n"
                "```text\n@fenced_name\n```\n\n"
                "Too long @abcdefghijklmnop.\n",
                encoding="utf-8",
            )
            run("--input", str(vault), "--output", str(site), "--progress-every", "0")
            _metadata, body = read_json_frontmatter(
                site / "content" / "notes" / "mentions.md"
            )
            self.assertIn("[@valid_name](https://x.com/valid_name)", body)
            self.assertIn("[@A1](https://x.com/A1)", body)
            self.assertIn("person@example.com", body)
            self.assertIn("[@linked](https://example.com/profile)", body)
            self.assertIn("https://example.com/@path", body)
            self.assertIn("`@code_name`", body)
            self.assertIn("```text\n@fenced_name\n```", body)
            self.assertIn("@abcdefghijklmnop", body)

    def test_repairs_malformed_external_urls_without_losing_visible_text(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-url-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            broken = "http://kissingsuzykolber.uproxx.com/2011/05/this-week-in-f%E"
            (vault / "Tweet.md").write_text(
                f"Bare {broken} ...\n\n"
                f"Explicit [original target]({broken})\n\n"
                f"Reference [target][broken]\n\n[broken]: {broken}\n\n"
                "Complex [parentheses](https://example.com/wiki/Function_(mathematics)%E)\n\n"
                "Unusable [missing host](http://)\n\n"
                "Bare unusable http://\n\n"
                f"Inline code `{broken}`\n\n"
                f"```text\n{broken}\n```\n",
                encoding="utf-8",
            )

            result = run(
                "--input", str(vault), "--output", str(site),
                "--progress-every", "0",
            )
            self.assertIn("checked URLs: 4 repaired link target(s)", result.stdout)
            self.assertIn("2 invalid URL(s) retained as visible text", result.stdout)
            _metadata, body = read_json_frontmatter(site / "content" / "notes" / "tweet.md")
            repaired = broken.replace("%E", "%25E")
            self.assertIn(f"[{broken}]({repaired}) ...", body)
            self.assertIn(f"[original target]({repaired})", body)
            self.assertIn(f"[broken]: {repaired}", body)
            self.assertIn(
                "[parentheses](https://example.com/wiki/Function_(mathematics)%25E)",
                body,
            )
            self.assertIn("Invalid URL preserved as text", body)
            self.assertIn("missing host", body)
            self.assertIn("<code>http://</code>", body)
            self.assertIn(f"`{broken}`", body)
            self.assertIn(f"```text\n{broken}\n```", body)
            self.assertIsNotNone(obsidian2site._repair_http_url(broken))
            self.assertIsNone(obsidian2site._repair_http_url("http://"))

    def test_copied_ledger_theme_is_used_verbatim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-theme-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            theme = root / "theme"
            vault.mkdir()
            (vault / "Note.md").write_text("Body\n", encoding="utf-8")
            template = theme / "layouts" / "page.html"
            template.parent.mkdir(parents=True)
            template.write_text("{{ .Title }}\n", encoding="utf-8")
            (theme / "theme.toml").write_text('name = "Ledger"\n', encoding="utf-8")
            # Bulk directories a theme checkout carries that a generated site
            # must not: they would multiply the output of every regeneration.
            for skipped in ("exampleSite", "node_modules", "public", "bench", ".git"):
                (theme / skipped).mkdir()
                (theme / skipped / "junk.txt").write_text("x", encoding="utf-8")

            run(
                "--input", str(vault), "--output", str(site),
                "--ledger-theme", str(theme), "--progress-every", "0",
            )
            copied_root = site / "themes" / "hugo-theme-ledger"
            # Copied verbatim: Ledger tracks current Hugo template APIs, so
            # there is nothing to rewrite the way a Relearn checkout needed.
            self.assertEqual(
                (copied_root / "layouts" / "page.html").read_text(encoding="utf-8"),
                "{{ .Title }}\n",
            )
            self.assertTrue((copied_root / "theme.toml").is_file())
            for skipped in ("exampleSite", "node_modules", "public", "bench", ".git"):
                self.assertFalse(
                    (copied_root / skipped).exists(),
                    f"{skipped}/ should not be copied into the generated site",
                )
            hugo_config = (site / "hugo.toml").read_text(encoding="utf-8")
            self.assertIn("theme = 'hugo-theme-ledger'", hugo_config)
            # A copied theme is used instead of the Hugo module, not alongside.
            self.assertNotIn("[module]", hugo_config)
            self.assertFalse((site / "go.mod").exists())

    def test_relearn_theme_flag_is_a_deprecated_alias(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-alias-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            theme = root / "theme"
            vault.mkdir()
            (theme / "layouts").mkdir(parents=True)
            (vault / "Note.md").write_text("Body\n", encoding="utf-8")

            result = run(
                "--input", str(vault), "--output", str(site),
                "--relearn-theme", str(theme), "--progress-every", "0",
            )
            self.assertIn("--relearn-theme is deprecated", result.stderr)
            self.assertTrue((site / "themes" / "hugo-theme-ledger" / "layouts").is_dir())
            self.assertFalse((site / "themes" / "hugo-theme-relearn").exists())

    def test_both_theme_flags_together_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-both-flags-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            theme = root / "theme"
            vault.mkdir()
            (theme / "layouts").mkdir(parents=True)
            (vault / "Note.md").write_text("Body\n", encoding="utf-8")
            result = run(
                "--input", str(vault), "--output", str(root / "site"),
                "--ledger-theme", str(theme), "--relearn-theme", str(theme),
                "--progress-every", "0", check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not both", result.stderr)

    def test_bluge_build_contains_no_lunr_or_pagefind_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-bluge-only-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            (vault / "Note.md").write_text("# Note\n\nServer-only search.\n", encoding="utf-8")
            run(
                "--input", str(vault), "--output", str(site),
                "--search-backend", "bluge", "--progress-every", "0",
            )
            config = tomllib.loads((site / "hugo.toml").read_text(encoding="utf-8"))
            self.assertEqual(config["params"]["search"]["backend"], "bluge")
            self.assertEqual(config["params"]["movenotesSearchBackend"], "bluge")
            self.assertFalse((site / "pagefind.yml").exists())
            search = (
                site / "layouts" / "shortcodes" / "movenotes-search.html"
            ).read_text(encoding="utf-8").casefold()
            self.assertIn("api/search", search)
            self.assertIn("api/health", search)
            self.assertNotIn("pagefind", search)
            self.assertNotIn("lunr", search)
            self.assertNotIn("searchindex", search)
            tags = (
                site / "layouts" / "shortcodes" / "movenotes-tags.html"
            ).read_text(encoding="utf-8").casefold()
            self.assertNotIn("pagefind", tags)
            start = (
                site / "layouts" / "shortcodes" / "movenotes-start.html"
            ).read_text(encoding="utf-8").casefold()
            self.assertNotIn("pagefind", start)
            for path in (site / "content").rglob("*.md"):
                self.assertNotIn("pagefind", path.read_text(encoding="utf-8").casefold())

    def test_bluge_build_validation_rejects_browser_search_scripts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-search-validation-") as temporary:
            output = Path(temporary)
            public = output / "public"
            public.mkdir()
            (public / "index.html").write_text(
                '<script src="/js/lunr.min.js"></script>', encoding="utf-8"
            )
            with self.assertRaises(SystemExit):
                obsidian2site._validate_built_search_backend(output, "bluge")
            obsidian2site._validate_built_search_backend(output, "both")

    def test_twitter_notes_hide_redundant_heading_and_theme_date(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-twitter-heading-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            (vault / "Tweet.md").write_text(
                "---\n"
                "title: Twitter title\n"
                "movenotes-original-format: twitter\n"
                "date: 2026-07-21T18:08:00Z\n"
                "---\n"
                "Twitter title\n\nTweet text.\n",
                encoding="utf-8",
            )
            run(
                "--input", str(vault), "--output", str(site),
                "--search-backend", "bluge", "--progress-every", "0",
            )
            metadata, body = read_json_frontmatter(site / "content" / "notes" / "tweet.md")
            self.assertTrue(metadata["movenotes_hide_heading"])
            self.assertTrue(metadata["hideAuthorDate"])
            self.assertIn("Tweet text.", body)
            # The heading.html override is gone: the theme reads ledgerHideTitle
            # and ledgerHideMeta from front matter instead, which the next step
            # writes. Nothing may reintroduce a partial override for it.
            self.assertFalse((site / "layouts" / "partials" / "heading.html").exists())

    def test_canonical_note_url_matches_hugo_output_and_search_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-url-path-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            twitter = vault / "Twitter"
            twitter.mkdir(parents=True)
            source_name = "@andrew_leach @tomrand @bankofcanada 49.8% of Canadian….md"
            (twitter / source_name).write_text(
                "---\ndate: 2026-07-20\n---\nCanadian example.\n",
                encoding="utf-8",
            )
            run("--input", str(vault), "--output", str(site), "--progress-every", "0")

            generated = (
                site / "content" / "notes" / "twitter" /
                "@andrew_leach-@tomrand-@bankofcanada-49.8-of-canadian.md"
            )
            self.assertTrue(generated.is_file())
            metadata, _body = read_json_frontmatter(generated)
            self.assertEqual(
                metadata["url"],
                "/notes/twitter/@andrew_leach-@tomrand-@bankofcanada-49.8-of-canadian.html",
            )
            documents = json.loads(
                (site / "static" / "movenotes" / "documents" / "000000.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                documents["0"][0],
                "/notes/twitter/@andrew_leach-@tomrand-@bankofcanada-49.8-of-canadian.html",
            )
            search_record = json.loads(
                (site / "server" / "search-source.jsonl").read_text(encoding="utf-8").strip()
            )
            self.assertEqual(search_record["url"], documents["0"][0])

    def test_generated_bluge_server_supports_server_search_and_date_operators(self) -> None:
        source = (PROJECT_DIR / "site_server" / "main.go").read_text(encoding="utf-8")
        module = (PROJECT_DIR / "site_server" / "go.mod").read_text(encoding="utf-8")
        checksum = (PROJECT_DIR / "site_server" / "go.sum").read_text(encoding="utf-8")
        self.assertIn("github.com/blugelabs/bluge v0.2.2", module)
        self.assertIn("github.com/blugelabs/bluge v0.2.2 h1:", checksum)
        self.assertIn('HandleFunc("/api/search"', source)
        self.assertIn('HandleFunc("/api/health"', source)
        self.assertIn('case "since", "until"', source)
        self.assertIn("NewDateRangeInclusiveQuery", source)
        self.assertIn("NewMatchPhraseQuery", source)
        self.assertIn('NewTermQuery(strings.ToLower(value)).SetField("tag")', source)
        self.assertIn("WithStandardAggregations", source)
        self.assertIn('log.Printf("health remote=', source)
        self.assertIn('log.Printf("search remote=', source)
        self.assertIn('Backend: "bluge"', source)
        self.assertIn('"Server-Timing"', source)
        self.assertIn('"X-Movenotes-Search-Backend"', source)
        build_source = (PROJECT_DIR / "obsidian2site.py").read_text(encoding="utf-8")
        self.assertIn('"mod", "tidy"', build_source)


if __name__ == "__main__":
    unittest.main()
