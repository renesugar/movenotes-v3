# Deploying a movenotes site on GitHub Pages

GitHub Pages serves static files and runs no server, so the Bluge search server
has no place there: this is a **Pagefind** deployment. Search happens in the
browser, over an index built after Hugo.

Two other client-side engines — Orama and FlexSearch — were built, measured against
Pagefind at 25,000 notes, and rejected: every in-browser index has to cross the wire
at least once, and theirs are 33–343 MB against the 0.37 MB Pagefind fetches to
answer a free-text query. The theme's `PERFORMANCE.md` has the numbers. Pagefind is
the static option here, not the default among several.

**Size decides whether this works at all.** A published Pages site may be no
larger than **1 GB**, and a movenotes archive builds to roughly 20 KB per note:

| archive | built size | GitHub Pages |
|---|---|---|
| 10,000 notes | ~200 MB | comfortable |
| 20,000 notes | ~400 MB (measured) | fine |
| 50,000 notes | ~1 GB | at the limit |
| 100,000+ notes | ~2 GB | **will not publish** |

Past that, `DEPLOY_VERCEL.md` covers static hosting on Vercel and running Bluge
on a host that keeps a process. The [limits](#limits) section below has the rest
of the numbers.

## 1. Generate with the right base URL

**A project site is published under a subpath** —
`https://<owner>.github.io/<repo>/` — and that path has to be in the site's
`baseURL`, because Hugo builds every link, stylesheet and fetch URL against it.

```bash
python3 -B obsidian2site.py \
  --input ~/twitter_vault \
  --output ~/twitter_site \
  --title "Twitter Archive" \
  --base-url "https://your-name.github.io/twitter-archive/" \
  --ledger-theme ~/projects/hugo-theme-ledger \
  --search-backend pagefind \
  --build
```

For a **user or organisation site** (`https://<owner>.github.io`, from a
repository named `<owner>.github.io`) the base URL has no subpath:
`--base-url "https://your-name.github.io/"`.

`--search-backend pagefind` is the right choice: it emits no Bluge server, no
`/api/` calls, and no `auto` probe that would fail on every page load. The
generated site says so — the Getting Started page describes static search and
notes that `since:`/`until:` need the Bluge backend.

> The workflow below also passes `--baseURL` to Hugo, which overrides
> `hugo.toml`. Generating with the right value anyway keeps a local
> `hugo --source ~/twitter_site` honest, and matters for the exact-tag index,
> whose paths are resolved from it.

## 2. Push the generated project

```bash
cd ~/twitter_site
git init -b main
git add -A && git commit -m "Generated archive"
git remote add origin git@github.com:your-name/twitter-archive.git
git push -u origin main
```

The generated `.gitignore` excludes `public/` — the workflow builds it — and the
Bluge index, which a static deployment has no use for.

In the repository, open **Settings → Pages** and set **Source** to
**GitHub Actions**. Without that, the workflow's deploy step has nothing to
publish to.

## 3. The workflow

Save as `.github/workflows/hugo.yaml`. This is Hugo's own
[recommended workflow](https://gohugo.io/host-and-deploy/host-on-github-pages/)
with one step added — Pagefind, after the build — and the theme's minimum Hugo
version pinned.

```yaml
name: Build and deploy
on:
  push:
    branches:
      - main
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
defaults:
  run:
    shell: bash
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      HUGO_VERSION: 0.164.0
      NODE_VERSION: 24.18.0
      PAGEFIND_VERSION: 1.5.2
      TZ: UTC
    steps:
      - name: Checkout
        uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - name: Setup Pages
        id: pages
        uses: actions/configure-pages@v6
      - name: Install Node.js
        uses: actions/setup-node@v6
        with:
          node-version: ${{ env.NODE_VERSION }}
      - name: Install Hugo
        run: |
          curl -sfL --output-dir "${{ runner.temp }}" -O \
            "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-amd64.tar.gz"
          mkdir -p "${HOME}/.local/hugo"
          tar -C "${HOME}/.local/hugo" -xf "${{ runner.temp }}/hugo_extended_${HUGO_VERSION}_linux-amd64.tar.gz"
          echo "${HOME}/.local/hugo" >> "${GITHUB_PATH}"
      - name: Build
        run: |
          hugo build \
            --gc \
            --minify \
            --baseURL "${{ steps.pages.outputs.base_url }}/" \
            --cacheDir "${{ runner.temp }}/.cache/hugo"
      - name: Build the Pagefind index
        run: npx --yes pagefind@${PAGEFIND_VERSION} --site public
      - name: Report the published size
        run: |
          echo "files: $(find public -type f | wc -l)"
          echo "size:  $(du -sh public | cut -f1)  (GitHub Pages allows 1 GB)"
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v5
        with:
          path: ./public
  deploy:
    runs-on: ubuntu-latest
    needs: build
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v5
```

Four things about it are specific to this site:

- **Hugo must be the extended build.** The theme's `min_version` is 0.146; it is
  developed on 0.164.
- **Pagefind runs after Hugo**, over `public/`, because it indexes the *built
  HTML*. Reversing the order silently produces an empty index.
- **`--baseURL "${{ steps.pages.outputs.base_url }}/"`** takes the subpath from
  the Pages configuration, so the workflow is correct for both a project site and
  a user site without editing.
- **No Dart Sass, no Go step.** Hugo's own workflow installs both; the theme
  uses neither, and a static deployment has no Go in it. (Hugo's template
  installs Go only `if hashFiles('go.mod') != ''`, which for a `--ledger-theme`
  project is never.)

## 4. Verify

After the first successful run, on the published site:

1. **The shell renders with styling.** If the page is unstyled, the base URL is
   wrong — the stylesheet is being requested from the domain root instead of the
   subpath.
2. **Search returns results.** `/search/?q=tag:something` from the sidebar. If it
   reports search as unavailable, the Pagefind step did not run or ran before
   Hugo; check for `/pagefind/pagefind.js` in the network log.
3. **A result link opens the note.** This is the check that catches a subpath
   mistake: results that 404 mean URLs are missing the `/<repo>/` prefix.
4. **Browse Tags loads its tags, and a tag opens notes.** It reads the hashed
   posting index under `/movenotes/`, which is a separate path from Pagefind's.
5. **`since:2026-01-01` reports itself ignored.** That message is correct here:
   Pagefind has no date filter. It confirms the notice mechanism works rather
   than a query silently returning the unbounded set.

## Limits

| | limit | a movenotes archive |
|---|---|---|
| published site | **1 GB** (hard) | ~20 KB/note → about 50,000 notes |
| source repository | 1 GB recommended | the vault's Markdown plus the theme |
| bandwidth | 100 GB/month (soft) | a 20 KB page view; crawlers dominate |
| builds | 10/hour (soft) | does not apply to a custom Actions workflow |
| deployment | 10 minutes | the upload of `public/`, not the Hugo build |

The 10-minute deployment cap applies to publishing the artifact, and a
six-figure archive is a lot of small files to upload. Combined with the 1 GB
ceiling, GitHub Pages is a good host for an archive up to a few tens of
thousands of notes and the wrong one past that.

Measure before pushing:

```bash
du -sh ~/twitter_site/public            # against 1 GB
find ~/twitter_site/public -type f | wc -l
```

## Subpath deployments

A project site publishes below the domain root, and that used to break more than
it should have. Both repositories now route every site-absolute URL through one
resolver, because Hugo's `relURL` **drops the baseURL's path when its argument
starts with a slash**:

```
baseURL = "https://example.github.io/archive/"
"/search/" | relURL   ->  /search/            wrong
"search/"  | relURL   ->  /archive/search/    right
```

What that touched, all fixed and verified under `/archive/`:

- every link, stylesheet and script in the theme;
- the search config's `bundlePath`, `endpoint` and `healthEndpoint`, which the
  browser fetches;
- **Pagefind's result URLs**, which needed `baseUrl` in `options()` — Pagefind
  records them relative to the directory it indexed, so every result linked to
  the domain root;
- **the exact-tag index's stored note URLs**, which Browse Tags resolves against
  the site root rather than assigning to `href` directly.

If you deploy to a subpath and something 404s, that is the first thing to
suspect, and `--base-url` at generation time is where it starts.

## References

- [Host on GitHub Pages](https://gohugo.io/host-and-deploy/host-on-github-pages/) — the workflow this is based on
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [About GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages) — site types and URL forms
- [Pagefind](https://pagefind.app/)
- `DEPLOY_VERCEL.md` — Vercel, including server-side Bluge search
- `STATIC_SITE.md` — generating and serving the site locally
- The theme's `PERFORMANCE.md` — measured Pagefind behaviour at 10k, 100k and 500k notes
