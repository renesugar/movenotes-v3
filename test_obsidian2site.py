#!/usr/bin/env python3
"""Tests for the large-vault Obsidian to Hugo/Bluge/Pagefind converter."""

from __future__ import annotations

import json
import re
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


def go_code_without_comments(paths: list[Path]) -> str:
    """Concatenated Go source with comments removed.

    Checks for forbidden constructs have to look at code, not prose: the search
    package's own doc comment says "no flags, no log.Fatal, no listening", and a
    plain substring search reads that as a violation.
    """
    out = []
    for path in paths:
        if path.name.endswith("_test.go"):
            continue
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        text = re.sub(r"(?m)//.*$", "", text)
        out.append(text)
    return "\n".join(out)


def write_fake_hugo(path: Path, log: Path, theme_backend: str) -> Path:
    """A stand-in for Hugo that emits enough of a Ledger build to be validated.

    The generated site is checked after building for the search backend its pages
    actually configure, so a fake Hugo that wrote a bare index.html would fail
    that check for the right reason and the wrong test.
    """
    path.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "destination = pathlib.Path(args[args.index('--destination') + 1])\n"
        "destination.mkdir(parents=True, exist_ok=True)\n"
        "(destination / 'index.html').write_text('<html><body>site</body></html>')\n"
        "search = destination / 'search'\n"
        "search.mkdir(parents=True, exist_ok=True)\n"
        "search.joinpath('index.html').write_text(\n"
        "    '<script type=\"application/json\" data-ledger-search-config>'\n"
        f"    '{{{{\"backend\":\"{theme_backend}\"}}}}</script>'\n"
        ")\n"
        f"pathlib.Path({str(log)!r}).write_text('hugo\\n')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


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
            # --search-backend both maps to the theme's auto adapter: it probes
            # /api/health and uses Bluge when the generated server answers,
            # Pagefind when nothing does.
            self.assertEqual(config["params"]["search"]["backend"], "auto")
            self.assertEqual(config["params"]["search"]["endpoint"], "/api/search")
            self.assertEqual(config["params"]["search"]["healthEndpoint"], "/api/health")
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
            # Two entry points over one package: a local process and the
            # serverless functions, so a deployed site cannot answer differently
            # from a local one.
            self.assertTrue((site / "server" / "search" / "service.go").is_file())
            self.assertTrue((site / "server" / "cmd" / "movenotes-site-server" / "main.go").is_file())
            self.assertTrue((site / "server" / "api" / "search.go").is_file())
            self.assertTrue((site / "server" / "api" / "health.go").is_file())
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
            # Front matter only: the tag browser needs the asset pipeline, so it
            # lives in the layout rather than in a shortcode called from here.
            self.assertEqual(tags_body.strip(), "")
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
            self.assertNotIn("custom", metadata)
            # Explicit tags — frontmatter tags plus inline hashtags — become Hugo
            # taxonomy terms. Generated word tags never do.
            self.assertEqual(metadata["tags"], ["alpha", "beta"])
            self.assertEqual(metadata["categories"], ["Folder"])
            # Front matter is repeated once per note, so nothing is written that
            # the theme can derive, and no Relearn field survives.
            for absent in (
                "hidden", "disableBreadcrumb", "disableToc", "hideAuthorDate",
                "movenotes_hide_heading", "movenotes_explicit_tags",
                "movenotes_tags", "summary", "readingTime",
            ):
                self.assertNotIn(absent, metadata)
            # A note at the vault root has no folder to name it, so it takes the
            # site title.
            root_meta, _ = read_json_frontmatter(site / "content" / "notes" / "other.md")
            self.assertEqual(root_meta["categories"], ["vault"])
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
            # The generated project has no shortcodes at all: /search/ is the
            # theme's view, Getting Started is prose, and Browse Tags needs the
            # asset pipeline so its body lives in a layout.
            self.assertFalse((site / "layouts" / "shortcodes").exists())
            about_body = (site / "content" / "about.md").read_text(encoding="utf-8")
            self.assertNotIn("{{<", about_body)
            self.assertIn("since:2026-07-01 until:2026-08-01", about_body)

            browse_tags = (site / "layouts" / "browse-tags.html").read_text(encoding="utf-8")
            self.assertIn("data-movenotes-tags", browse_tags)
            self.assertIn("movenotes/tag-postings/", browse_tags)
            self.assertIn("movenotes/documents/", browse_tags)
            self.assertIn("js.Build", browse_tags)
            self.assertIn(str(obsidian2site._TAG_POSTING_BUCKETS), browse_tags)
            # The theme's own data attributes must not appear: the tag filter is
            # not the site search and must not be driven by its controller.
            self.assertNotIn("data-ledger-search", browse_tags)

            tags_script = (site / "assets" / "js" / "movenotes-tags.js").read_text(encoding="utf-8")
            # The page-number windowing rule is imported from the theme rather
            # than reimplemented — it already exists three times there.
            self.assertIn("import { windowPages } from './search/paging.js'", tags_script)
            self.assertIn("document_chunk_size", tags_script)

            manifest = json.loads(
                (site / "static" / "movenotes" / "tags" / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["version"], 3)
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
            # The Bluge index is what renders a search result card, so the source
            # carries everything a card shows. readingTime especially: a result
            # from the index has no Hugo page behind it to compute .ReadingTime.
            self.assertEqual(first_record["category"], "Folder")
            self.assertEqual(first_record["readingTime"], 1)
            self.assertTrue(first_record["summary"])
            # Every tag reaches Bluge, including generated word tags and the ones
            # the taxonomy cap left out, so `tag:` answers for all of them.
            self.assertIn("codecs", first_record["tags"])   # a generated word tag
            self.assertIn("alpha", first_record["tags"])    # a written tag

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

    def test_taxonomy_tag_cap_promotes_the_most_frequent_tags(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-tag-cap-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            # "common" is on every note, "middling" on three, and each note has
            # a tag of its own, so the promotion order is unambiguous.
            for index in range(6):
                tags = ["common", f"only{index}"]
                if index < 3:
                    tags.append("middling")
                (vault / f"Note {index}.md").write_text(
                    "---\ntags:\n" + "".join(f"  - {tag}\n" for tag in tags) + "---\n"
                    f"Body about UniqueWord{index}.\n",
                    encoding="utf-8",
                )

            result = run(
                "--input", str(vault), "--output", str(site),
                "--max-taxonomy-tags", "2", "--progress-every", "0",
            )
            self.assertIn("2 of 8 explicit tag(s)", result.stdout)
            self.assertIn("the other 6", result.stdout)

            promoted = set()
            for path in (site / "content" / "notes").glob("note-*.md"):
                metadata, _ = read_json_frontmatter(path)
                promoted.update(metadata.get("tags", []))
            self.assertEqual(promoted, {"common", "middling"})

            # Demoted tags are not lost: they stay in the posting index behind
            # Browse Tags, and in the Bluge source.
            indexed = set()
            for path in (site / "static" / "movenotes" / "tags").glob("*.json"):
                if path.name == "manifest.json":
                    continue
                indexed.update(tag for tag, _count in json.loads(path.read_text(encoding="utf-8")))
            self.assertIn("only5", indexed)
            source = (site / "server" / "search-source.jsonl").read_text(encoding="utf-8")
            self.assertIn("only5", source)

    def test_taxonomy_tag_cap_is_deterministic_and_defaults_by_note_count(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-tag-cap-order-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            vault.mkdir()
            # Every tag appears once, so only the name tie-break decides, which
            # is what keeps two runs of one vault identical.
            for index in range(4):
                (vault / f"Note {index}.md").write_text(
                    f"---\ntags:\n  - tag{index}\n---\nBody {index}.\n",
                    encoding="utf-8",
                )
            first, second = (root / "one", root / "two")
            for site in (first, second):
                run(
                    "--input", str(vault), "--output", str(site),
                    "--max-taxonomy-tags", "2", "--progress-every", "0",
                )

            def tags_of(site: Path) -> dict[str, list[str]]:
                return {
                    path.name: read_json_frontmatter(path)[0].get("tags", [])
                    for path in sorted((site / "content" / "notes").glob("note-*.md"))
                }

            self.assertEqual(tags_of(first), tags_of(second))
            self.assertEqual(
                sorted(tag for tags in tags_of(first).values() for tag in tags),
                ["tag0", "tag1"],
            )

        # The automatic cap keeps terms at a tenth of the notes, bounded to
        # 200–5000: a term page costs about as much to build as a note page.
        self.assertEqual(obsidian2site._automatic_taxonomy_tag_cap(0), 200)
        self.assertEqual(obsidian2site._automatic_taxonomy_tag_cap(2_000), 200)
        self.assertEqual(obsidian2site._automatic_taxonomy_tag_cap(5_000), 500)
        self.assertEqual(obsidian2site._automatic_taxonomy_tag_cap(20_000), 2_000)
        self.assertEqual(obsidian2site._automatic_taxonomy_tag_cap(500_000), 5_000)

    def test_uncapped_taxonomy_keeps_every_explicit_tag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-tag-uncapped-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            site = root / "site"
            vault.mkdir()
            (vault / "Note.md").write_text(
                "---\ntags:\n  - alpha\n  - beta\n---\nBody with #gamma.\n",
                encoding="utf-8",
            )
            result = run(
                "--input", str(vault), "--output", str(site),
                "--max-taxonomy-tags", "0", "--progress-every", "0",
            )
            self.assertIn("3 of 3 explicit tag(s)", result.stdout)
            metadata, _ = read_json_frontmatter(site / "content" / "notes" / "note.md")
            self.assertEqual(metadata["tags"], ["alpha", "beta", "gamma"])

    def test_category_modes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="obsidian-site-categories-") as temporary:
            root = Path(temporary)
            vault = root / "vault"
            (vault / "Twitter").mkdir(parents=True)
            (vault / "Deep" / "Nested").mkdir(parents=True)
            (vault / "Twitter" / "Post.md").write_text("A post.\n", encoding="utf-8")
            (vault / "Deep" / "Nested" / "Note.md").write_text("Nested.\n", encoding="utf-8")
            (vault / "Root.md").write_text("At the root.\n", encoding="utf-8")

            folder = root / "folder"
            run("--input", str(vault), "--output", str(folder),
                "--title", "Archive", "--progress-every", "0")
            self.assertEqual(
                read_json_frontmatter(folder / "content" / "notes" / "twitter" / "post.md")[0]["categories"],
                ["Twitter"],
            )
            # Only the top-level folder names the category; nesting deeper does
            # not multiply categories.
            self.assertEqual(
                read_json_frontmatter(folder / "content" / "notes" / "deep" / "nested" / "note.md")[0]["categories"],
                ["Deep"],
            )
            self.assertEqual(
                read_json_frontmatter(folder / "content" / "notes" / "root.md")[0]["categories"],
                ["Archive"],
            )

            fixed = root / "fixed"
            run("--input", str(vault), "--output", str(fixed),
                "--category-mode", "fixed", "--category-name", "All of it",
                "--progress-every", "0")
            for relative in ("twitter/post.md", "root.md"):
                self.assertEqual(
                    read_json_frontmatter(fixed / "content" / "notes" / Path(relative))[0]["categories"],
                    ["All of it"],
                )

            none = root / "none"
            run("--input", str(vault), "--output", str(none),
                "--category-mode", "none", "--progress-every", "0")
            self.assertNotIn(
                "categories",
                read_json_frontmatter(none / "content" / "notes" / "twitter" / "post.md")[0],
            )

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

            fake_hugo = write_fake_hugo(root / "fake-hugo", log, "pagefind")

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

            fake_hugo = write_fake_hugo(root / "fake-hugo", log, "bluge")

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

            # Browse Tags reads those same posting lists, so the count on a tag
            # and the number of results it opens are one number.
            tags_script = (
                site / "assets" / "js" / "movenotes-tags.js"
            ).read_text(encoding="utf-8")
            self.assertIn("postings[tag]", tags_script)
            self.assertIn("'?tag=' + encodeURIComponent(row[0])", tags_script)

            # Chunked document metadata carries the date, so an exact-tag result
            # card looks like every other card on the site.
            documents = json.loads(
                (site / "static" / "movenotes" / "documents" / "000000.json")
                .read_text(encoding="utf-8")
            )
            record = next(iter(documents.values()))
            self.assertEqual(len(record), 3)
            self.assertRegex(record[2], r"^\d{4}-\d{2}-\d{2}$")

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
            # Nothing the generator writes may *load or call* Pagefind in a
            # Bluge-only build. Prose about it is fine — a comment explaining
            # why the tag index exists mentions it — so this looks for the
            # bundle URL and the API, not the word. The theme's own bundle still
            # contains both adapters; which one runs is params.search.backend,
            # and _validate_built_search_backend checks the built HTML for a
            # leaked browser index.
            for path in list((site / "layouts").rglob("*.html")) + \
                    list((site / "assets").rglob("*.js")):
                text = path.read_text(encoding="utf-8").casefold()
                for runtime in ("pagefind/pagefind.js", "pagefind.search(", "lunr", "searchindex"):
                    self.assertNotIn(
                        runtime, text,
                        f"{path.name} references {runtime} in a bluge-only build",
                    )
            # Content, though, should not even mention it: the Getting Started
            # page describes the search this build actually has.
            for path in (site / "content").rglob("*.md"):
                self.assertNotIn("pagefind", path.read_text(encoding="utf-8").casefold())

    def test_built_search_backend_validation(self) -> None:
        """The check reads the theme's embedded config, not script filenames.

        The theme picks its adapter from that JSON, so it is what decides which
        index a visitor downloads. A `bluge` build that shipped
        `"backend":"pagefind"` would look fine and quietly load a browser index.
        """
        def build(output: Path, backend: str, *, pagefind: bool = True,
                  runtime: str = "", config: bool = True) -> None:
            search = output / "public" / "search"
            search.mkdir(parents=True)
            body = (
                '<script type="application/json" data-ledger-search-config>'
                f'{{"allNotesLabel":"All notes","backend":"{backend}"}}</script>'
                if config else "<p>no search view</p>"
            )
            (search / "index.html").write_text(body + runtime, encoding="utf-8")
            if pagefind:
                (output / "public" / "pagefind").mkdir()

        with tempfile.TemporaryDirectory(prefix="obsidian-site-validation-") as temporary:
            root = Path(temporary)

            # Accepted: what each mode actually generates.
            for index, (asked, embedded, needs_pagefind) in enumerate((
                ("both", "auto", True),
                ("bluge", "bluge", False),
                ("pagefind", "pagefind", True),
            )):
                output = root / f"ok{index}"
                build(output, embedded, pagefind=needs_pagefind)
                obsidian2site._validate_built_search_backend(output, asked)

            # A backend mismatch between the flag and the built pages.
            mismatch = root / "mismatch"
            build(mismatch, "auto", pagefind=False)
            with self.assertRaises(SystemExit):
                obsidian2site._validate_built_search_backend(mismatch, "bluge")

            # A build that will fall back to Pagefind, without the index to
            # fall back to.
            missing = root / "missing-index"
            build(missing, "auto", pagefind=False)
            with self.assertRaises(SystemExit):
                obsidian2site._validate_built_search_backend(missing, "both")

            # A Bluge-only build that still loads the Pagefind runtime.
            leaked = root / "leaked"
            build(leaked, "bluge", pagefind=False,
                  runtime='<script src="/pagefind/pagefind.js"></script>')
            with self.assertRaises(SystemExit):
                obsidian2site._validate_built_search_backend(leaked, "bluge")

            # No search view at all: a missing or stale theme.
            empty = root / "empty"
            build(empty, "auto", config=False)
            with self.assertRaises(SystemExit):
                obsidian2site._validate_built_search_backend(empty, "both")

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
            # A Twitter note carries its own heading and timestamp in the body,
            # so the theme's are suppressed. The h1 stays in the document
            # outline for assistive technology; the theme hides it visually.
            self.assertTrue(metadata["ledgerHideTitle"])
            self.assertTrue(metadata["ledgerHideMeta"])
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
        server_dir = PROJECT_DIR / "site_server"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(server_dir.rglob("*.go"))
            if not path.name.endswith("_test.go")
        )
        module = (PROJECT_DIR / "site_server" / "go.mod").read_text(encoding="utf-8")
        checksum = (PROJECT_DIR / "site_server" / "go.sum").read_text(encoding="utf-8")
        self.assertIn("github.com/blugelabs/bluge v0.2.2", module)
        self.assertIn("github.com/blugelabs/bluge v0.2.2 h1:", checksum)
        self.assertIn('HandleFunc("/api/search"', source)
        self.assertIn('HandleFunc("/api/health"', source)
        self.assertIn("NewDateRangeInclusiveQuery", source)
        self.assertIn("NewMatchPhraseQuery", source)
        self.assertIn('NewTermQuery(strings.ToLower(tag)).SetField("tag")', source)
        self.assertIn('NewTermQuery(category).SetField("category")', source)
        self.assertIn("WithStandardAggregations", source)
        # The grammar is parsed once, client-side. This server takes fields and
        # must not grow a parser for `tag:` prefixes or quotes again.
        self.assertNotIn("splitQuery", source)
        self.assertNotIn("operatorRE", source)
        # Phrase queries need term positions, or they match nothing while the
        # server looks healthy.
        for field in ("title", "body", "summary"):
            self.assertIn(f'NewTextField("{field}"', source)
        self.assertEqual(source.count("SearchTermPositions()"), 3)
        # Both paging styles, and the fields a result card renders.
        self.assertIn('values.Get("page")', source)
        self.assertIn('values.Get("offset")', source)
        self.assertIn('perRaw = values.Get("limit")', source)
        for field in ('"category"', '"tags"', '"readingTime"', '"summary"'):
            self.assertIn(field, source)
        self.assertIn('log.Printf("health remote=', source)
        self.assertIn('log.Printf("search remote=', source)
        self.assertIn('Backend: "bluge"', source)
        self.assertIn('"Server-Timing"', source)
        self.assertIn('"X-Movenotes-Search-Backend"', source)
        build_source = (PROJECT_DIR / "obsidian2site.py").read_text(encoding="utf-8")
        self.assertIn('"mod", "tidy"', build_source)
        # The local binary comes from the command package now, not the module
        # root: the module root has no main.
        self.assertIn('"./cmd/movenotes-site-server"', build_source)

    def test_server_package_keeps_process_concerns_out_of_the_shared_code(self) -> None:
        """The search package is wrapped by two entry points, one serverless.

        A serverless function has no command line, no port to listen on, and
        nothing that survives a log.Fatal usefully — so none of those may live in
        the code both halves share, or the deployed half inherits them.
        """
        server_dir = PROJECT_DIR / "site_server"
        package = go_code_without_comments(sorted((server_dir / "search").glob("*.go")))
        for forbidden in ("log.Fatal", "flag.", "ListenAndServe", "os.Exit"):
            self.assertNotIn(forbidden, package, f"search package must not use {forbidden}")

        # Configuration resolves explicit → environment → default, because a
        # deployment configures itself with environment variables.
        for name in ("MOVENOTES_INDEX", "MOVENOTES_SOURCE", "MOVENOTES_SITE"):
            self.assertIn(name, package)

        # The index is opened lazily and never built by a request: indexing takes
        # minutes and needs a writable filesystem.
        self.assertIn("sync.Once", package)
        self.assertIn("StatusServiceUnavailable", package)
        handlers = go_code_without_comments([server_dir / "search" / "handler.go"])
        self.assertNotIn("BuildIndex", handlers)

        # The serverless half is env-configured and serves no static files: a
        # generated archive's public/ dwarfs any function bundle limit.
        api = go_code_without_comments(sorted((server_dir / "api").glob("*.go")))
        self.assertIn("func Search(", api)
        self.assertIn("func Health(", api)
        self.assertNotIn("FileServer", api)
        self.assertNotIn("BuildIndex", api)
        self.assertNotIn("flag.", api)

        # Only the local entry point serves files, builds indexes, or exits.
        command = go_code_without_comments([server_dir / "cmd" / "movenotes-site-server" / "main.go"])
        self.assertIn("FileServer", command)
        self.assertIn("search.BuildIndex", command)
        self.assertIn("ListenAndServe", command)
        # $PORT so the same binary runs in a container or on a PaaS.
        self.assertIn('os.Getenv("PORT")', command)


if __name__ == "__main__":
    unittest.main()
