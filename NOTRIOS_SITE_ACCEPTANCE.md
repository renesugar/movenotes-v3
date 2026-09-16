# Notrios live site acceptance — 7b

Completed 2026-09-16 with the current schema-28 synthetic resource publication.
Both real builds and Chromium checks passed after fixing a Ledger Bluge subpath
bug. This is a three-note functional acceptance run, not a scale measurement.

## Finding and fix

At Ledger `f9d28ea297427890ecffa31fa74caa9ee385d9f5`, Bluge returned the correct
three `tag:published` results but rendered `/notes/...` links on a site mounted
at `/archive/`. The browser assertion failed before accepting the run.

Ledger commit **`85ac1b070c657b975629ed728c700694811d6e80`** resolves result URLs
against `config.siteRoot` in `assets/js/search/backends/bluge.js`, preserving
already-prefixed and absolute URLs. Its regression covers root deployments,
relative paths, Unicode/anchors and prefix collisions. All **16 JavaScript tests**
passed with Node's `--test-isolation=none`. Both sites were rebuilt from this
commit and the browser checks rerun. The theme checkout is clean; no push was
performed. Movenotes' canonical path maps and source-row URLs were unchanged.

## Environment and evidence

- Hugo: `v0.164.0-ce2470e7012b5ab5fc4e10ebe4027e9f8d9e00dc+extended`, Linux amd64.
- Go: `go1.27.0 linux/amd64`; generated Bluge server compiled and indexed for real.
- Pagefind: `1.5.2`; indexed **3 pages, 74 words, 2 filters, 1 sort**.
- Playwright: `1.61.1`, installed Chromium; Browser plugin not available.
- Viewports: desktop **1365 × 900**, mobile **390 × 844**.
- Fixture: [schema-28 resource publication](testdata/notrios/schema28/publication-loose/expected.json).
  Archive digest `c1cebd8da881cc30cf921ae903b6816ddb3a859280f3f3c6dc69073f1f20e8d4`;
  reviewed selection `9e06e07e6e57499f1f11577d2aefc8f97fc7370ceeb04f3dac2d17f38cabd97f`.
- Local work/evidence: `/tmp/movenotes-7b/`; logs `import.log`, `vault.log`,
  `bluge-build.log`, `pagefind-build.log`, `theme-tests.log`, `browser.log`,
  `artifact.log`; structured `browser-results.json` and `artifact-results.json`.
  Four screenshots: `{bluge,pagefind}-{desktop,mobile}.png`.
- Full five-module Python regression: **262 tests passed in 150.295s**,
  `/tmp/movenotes-7b-tests.log`, both bytecode-suppression flags, local sockets permitted.

Initial sandbox builds stopped at Hugo's read-only cache directory. Approved
cache access resolved that environmental failure. No generated site, index,
private library or screenshot is committed.

## Checks

| Check | Bluge | Pagefind |
|---|---|---|
| Real Hugo build; built backend validator | Pass, 24 HTML pages | Pass, 24 HTML pages |
| Real search index and browser query | Pass | Pass |
| `published`, `café`, `research notes`, `東京` counts | 3, 1, 1, 1 | 3, 1, 1, 1 |
| Taxonomy card counts equal search counts | Pass | Pass |
| Canonical note URLs and search-result URLs under `/archive/` | Pass after fix | Pass |
| Unicode child/Back navigation, heading anchor, image load | Pass | Pass |
| Text/binary download hashes and all 3 public attachment hashes | Pass | Pass |
| Receipt preserved publicly, absent from HTML/search-source content | Pass | Pass |
| Ten excluded sentinels and both receipt digests return no search results | Pass | Pass |
| Publishable files + JSONL scanned for excluded sentinels/local work path | 103 files | 122 files |
| Backend isolation | API traffic, no Pagefind requests or index | Pagefind traffic, no API requests |
| Page identity, meaningful content, no error overlay/console errors/HTTP failures | Pass | Pass |
| Desktop/mobile screenshot inspection; no horizontal overflow | Pass | Pass |

The unchanged source inventory is compared to its frozen hashes. All four
explicit tags (six memberships) reach search-source rows; generated `préface`
is absent from their tag lists. Ten excluded sentinels are absent from every
publishable file and both JSONL sources. Browser queries complement raw byte
scans of compressed indexes. These checks apply to this synthetic publication;
large-corpus time/RSS/disk and recovery trials remain 7c.

## Reproduce

Use the pinned Ledger checkout above, Hugo/Go/Pagefind and an existing Playwright
Chromium installation. Choose a fresh work directory. Commands below use the
local checkout locations from this run; replace tool paths if needed.

```bash
mkdir -p /tmp/movenotes-7b-repro/vault
PYTHONDONTWRITEBYTECODE=1 python3 -B notrios2sql.py \
  --input testdata/notrios/schema28/publication-loose/archive \
  --output /tmp/movenotes-7b-repro/import \
  --expected-selection-sha256 9e06e07e6e57499f1f11577d2aefc8f97fc7370ceeb04f3dac2d17f38cabd97f
PYTHONDONTWRITEBYTECODE=1 python3 -B sql2obsidian.py \
  --input /tmp/movenotes-7b-repro/import --output /tmp/movenotes-7b-repro/vault \
  --include-notrios-receipt --no-simplify-urls
PYTHONDONTWRITEBYTECODE=1 python3 -B obsidian2site.py \
  --input /tmp/movenotes-7b-repro/vault --output /tmp/movenotes-7b-repro/bluge \
  --ledger-theme ~/projects/hugo-theme-ledger \
  --base-url http://127.0.0.1:18771/archive/ --search-backend bluge \
  --include-notrios-receipt --build
PYTHONDONTWRITEBYTECODE=1 python3 -B obsidian2site.py \
  --input /tmp/movenotes-7b-repro/vault --output /tmp/movenotes-7b-repro/pagefind \
  --ledger-theme ~/projects/hugo-theme-ledger \
  --base-url http://127.0.0.1:18772/archive/ --search-backend pagefind \
  --pagefind-bin ~/projects/hugo-theme-ledger/node_modules/.bin/pagefind \
  --include-notrios-receipt --build
```

In separate terminals start the generated backend and the test-only subpath mount:

```bash
/tmp/movenotes-7b-repro/bluge/server/movenotes-site-server \
  -site /tmp/movenotes-7b-repro/bluge/public \
  -source /tmp/movenotes-7b-repro/bluge/server/search-source.jsonl \
  -index /tmp/movenotes-7b-repro/bluge/server/bluge-index -listen 127.0.0.1:18773
python3 -B testdata/notrios/serve_site_acceptance.py /tmp/movenotes-7b-repro
```

The mount strips `/archive/` before serving files or forwarding API requests;
it models a subpath deployment. The generated Go server itself serves at `/`.
Stop both test processes after checking:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B testdata/notrios/check_site_artifacts.py /tmp/movenotes-7b-repro
node testdata/notrios/check_site_acceptance.mjs /tmp/movenotes-7b-repro \
  ~/projects/test/node_modules/playwright/index.mjs
node --test --test-isolation=none \
  ~/projects/hugo-theme-ledger/assets/js/search/backends/bluge.test.js \
  ~/projects/hugo-theme-ledger/assets/js/search/query.test.js
```

The helpers are deliberately fixture-specific development tools, outside the
standard-library-only importer runtime and offline unit suite. Browser output
and screenshots are written only beneath the supplied work directory.
