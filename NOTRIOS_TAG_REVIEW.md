# Notrios vault and site tag review — slice 4c

Reviewed 2026-09-14. The existing runtime satisfies the importer tag contract;
no converter, exporter, site URL or theme changes were needed. A new regression
connects the real schema-28 resource-free publication to the actual vault and
site generators. This review covers generated inputs, not a new Hugo build,
Pagefind indexing run, browser session or live Bluge query.

## Data path and semantics

- `notrios2sql.py` inserts the mapped TAG and NOTE_TAG rows. Source identities
  remain distinct even when tag names are identical; 4a/4b cover membership
  integrity and preservation-bundle round trips.
- `sql2obsidian.py:load_note_tags` joins memberships to tag titles and sorts
  the per-note list. The vault stores these titles as explicit YAML list tags.
  Quoting keeps multiword names such as `research notes` together. The vault
  and preservation bundle retain tag text and identities as established in 4b.
- `obsidian2site.py:_tags_from_frontmatter` intentionally projects tags for
  search: it trims surrounding whitespace, removes leading `#`, casefolds and
  deduplicates names. YAML list entries preserve internal spaces. This is not
  a promise to retain source tag IDs, casing or duplicate memberships in site
  taxonomy. `_extract_tags` also treats inline hashtags as explicit tags.
- `_extract_tags` separately derives words from searchable body text, using
  the configured stop words and minimum word length. The combined set goes to
  the disk-backed hashed posting index. Only the explicit set goes to Hugo
  frontmatter and `server/search-source.jsonl` tags. Generated words remain
  reachable through Browse Tags and free-text search.
- `_apply_taxonomy_tag_cap` promotes explicit names by frequency, breaking ties
  by name. Demoted names remain in the posting index and Bluge source tags.
  Hugo taxonomy and its Pagefind filter see the promoted subset. This is the
  documented cap exception to tag-surface equality; it never admits generated
  words to any `tag:` field. No Notrios-specific bypass is necessary.

The early M2 table in [the Ledger migration plan](LEDGER_MIGRATION_PLAN.md)
still described generated words in Bluge tag fields. It now reflects the
completed Step 46 behavior rather than the superseded proposal. M3's taxonomy
cap remains unchanged.

## Regression evidence

`test_notrios2sql.NotriosSiteTagTest` imports the unmodified
[schema-28 text publication](testdata/notrios/schema28/publication-text/),
exports its vault and runs `obsidian2site.py` twice: with default taxonomy
settings, then with `--max-taxonomy-tags 1`.

The test checks all three note paths independently of their duplicate titles:

- The vault carries exactly the expected per-note lists containing `café`,
  `published`, `research notes` and `東京`.
- Default Hugo tags and Bluge source tags equal those written lists. With cap
  one, only `published` reaches Hugo, while Bluge retains every written tag.
- Generated `préface` reaches neither tag field. It remains in the searchable
  body and has a posting for exactly the corresponding document ID, proving
  generated-word indexing was exercised rather than disabled.
- `research notes` still has one posting under the cap, and `published` has
  three. The set of generated note source paths equals the vault's three paths;
  section `_index.md` files are excluded from note assertions.

The focused run also includes the existing Step 46 agreement test, explicit
tag promotion test and uncapped taxonomy test. Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  test_notrios2sql.NotriosSiteTagTest \
  test_obsidian2site.ObsidianSiteGenerationTest.test_tag_searches_agree_with_the_tag_archive \
  test_obsidian2site.ObsidianSiteGenerationTest.test_taxonomy_tag_cap_promotes_the_most_frequent_tags \
  test_obsidian2site.ObsidianSiteGenerationTest.test_uncapped_taxonomy_keeps_every_explicit_tag
```

All four focused tests passed in 3.991 seconds. The first test attempt included
section index files in note assertions; correcting that test selection required
no runtime change. All 231 tests in the five-module regression suite passed
in 104.534 seconds with localhost sockets permitted and both bytecode-suppression
flags. Full-suite results are recorded in the
[import plan](NOTRIOS_IMPORT_PLAN.md). Resources remain Step 5; this review does
not enable their conversion or expose a public importer CLI.
