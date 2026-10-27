# Notrios v1.0.0 titled-link publication evidence — S43b

Generated on 2026-10-22 with Notrios `v1.0.0`
(`2aab9a8fe7c1ba8e411cd6003a6115b09abd6b9a`), built from a clean temporary
clone with Go 1.27.0, Linux amd64, CGO enabled. The binary's SHA-256 is
`b4f368a9879ce16b544c0d7bd175f95ad4647b43b71f0172bf0344dda048e55c`. The archive is
unmodified output of real `import obsidian`, `tags add`, `publish profile save`,
`publish plan` and `publish run` commands against a new, disposable synthetic
library. No private library was opened. The schema-27 and schema-28 fixtures
and their audit evidence are unchanged.

| Handoff | Contents | Archive commit SHA-256 | Reviewed selection SHA-256 |
|---|---|---|---|
| [publication-titled](publication-titled/) | 3 notes, 2 notebooks, 3 tags, 4 tag memberships, 1 resource, 1 resource relation, 11 links | `7f093e27d5d7ab18cac5d97324ae08c8509f4467954220911df7f9c799b206d9` | `a8537bb0582b7bcd9f01c0074923175ad04380930db66e7dafd23a32717b6dc2` |

Pass only the `archive/` directory to the consumer. Reports, `expected.json`,
`generation.json` and this README are evidence outside the archive. The
generation record holds the binary hash, Go build metadata, generator and helper
hashes, the input vault inventory and sanitized command arrays. Fresh generation
chooses new library and snapshot identities and timestamps. It is semantically
reproducible, not byte-identical.

## Input and what it exercises

The input is the synthetic Obsidian vault [vault-titled-v1](../vault-titled-v1/).
J43's Obsidian rewriter is what keeps a title when it replaces a destination, so
this fixture imports a vault rather than an archive-v1 seed. The published
`Home` note carries every title form, each followed by the canonical
`document://` or `resource://` destination:

- double-quoted, single-quoted and parenthesised titles;
- a tab separator;
- a title after a fragment;
- a Unicode title containing brackets and parentheses;
- an empty `""` title;
- a titled image embed (the only resource);
- a titled external URL;
- a titled self-anchor;
- one untitled link.

The single-quoted link was written as `<Other Note.md>`, an angle-bracketed
destination with a space. The producer resolved it to a canonical URI (J42),
which is why it is admitted.

`Child` links back with a title. One titled link points at a note in the
unselected `Private` notebook. The `plain_text` link action rewrites it to its
label, `Secret`, so neither its target nor its title is published.
`generate_v1_titled.py` checks the following against raw archive bytes,
independently of movenotes' own parser:

- every titled token appears exactly once;
- exactly one link was rewritten and none skipped;
- `PRIVATE-BODY-SENTINEL`, `WITHHELD-TITLE-SENTINEL`, the private path, the
  private document ID and the withheld note's `private-only` tag are all absent.

The manifest declares source schema 28, minimum 12 and maximum 28.

## Verification and integration

The release's reader accepts and fully verifies the publication, and so does
Python. [verifier-audit.json](verifier-audit.json) records all **56**
differential cases from [schema28-audit-cases.json](../schema28-audit-cases.json),
run against this fixture and the exact generation binary. Results: **9 shared
acceptances, 30 shared refusals, 17 documented consumer-only refusals**, with no
unexpected disagreement.

Two cases inject records that must name an existing document and resource.
Older fixtures keep their original `doc_public` and `res_image` targets. This
fixture declares its own in `expected.json` under `audit_targets`, which
`audit_verifier.py` and the tests read. The earlier fixtures' mutations are
unchanged.

`NotriosV1TitledTest` checks the following without needing Go:

- the fixture's inventory, pins, reports and titled tokens are immutable and the
  archive fully verifies;
- the offline differential cases replay;
- the archive converts with the reviewed selection digest, and an identical
  rerun leaves the output inventory unchanged;
- every note's database body equals the published body with only its
  destinations mapped, so every title survives byte for byte;
- the vault export keeps the titles: note links use actual relative paths, the
  titled image becomes `![shot](../attachments/shot.png "Photo title")`, the
  attachment bytes equal the input PNG, the written tags match, and the bundle
  hashes cover the finalized files.

Validation on 2026-10-22: the three `NotriosV1TitledTest` methods passed in
5.333 seconds, and the differential runner reported all 56 expectations matched.
The full five-module result is recorded in the plan's progress log.

## Reproduce

Build from a clean clone at the tag. The default module mode is required:
`-mod=mod` rewrites `go.mod`, and the binary then reports `vcs.modified=true`.

```bash
git clone --no-hardlinks <notrios checkout or https://github.com/renesugar/notrios> /tmp/movenotes-s43b/notrios-src
git -C /tmp/movenotes-s43b/notrios-src checkout v1.0.0
(cd /tmp/movenotes-s43b/notrios-src && GOCACHE=/tmp/movenotes-s43b/go-cache go build -o /tmp/movenotes-s43b/notriosctl ./cmd/notriosctl)
```

From the movenotes repository root (choose new work/output paths):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/generate_v1_titled.py \
  --notriosctl /tmp/movenotes-s43b/notriosctl \
  --work-dir /tmp/movenotes-s43b/gen-work \
  --output /tmp/movenotes-s43b/gen-out
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/audit_verifier.py \
  --notriosctl /tmp/movenotes-s43b/notriosctl \
  --fixture testdata/notrios/v1.0.0/publication-titled \
  --cases testdata/notrios/schema28-audit-cases.json \
  --output /tmp/movenotes-s43b/audit.json
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  tests.test_notrios2sql.NotriosLinkProjectionTest \
  tests.test_notrios2sql.NotriosLinkIntegrationTest \
  tests.test_notrios2sql.NotriosV1TitledTest
```

The generator refuses a binary without the exact clean VCS pin. The audit
runner checks its binary hash against the fixture's generation record. For a
rebuilt binary with different build metadata, generate a fresh fixture and audit
that pair instead of editing the committed hash.
