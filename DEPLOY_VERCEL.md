# Deploying a movenotes site on Vercel

`obsidian2site.py --vercel` emits everything Vercel needs: the built site as
static output, and the Bluge search API as two Go functions.

**Read this section before anything else.** Vercel's limits decide which
archives can go there at all, and the deciding limit is not the one you would
expect:

| archive | what works |
|---|---|
| up to ~5,000 notes | anything, including `vercel deploy` from your machine |
| ~5,000–45,000 notes | Git-connected project; the CLI's upload limits are exceeded |
| beyond ~45,000 notes | static search on Vercel, Bluge on a host that keeps a process — see [Past the ceiling](#past-the-ceiling) |

Those thresholds are measured, not estimated. [Limits, measured](#limits-measured)
shows the numbers and how to check your own archive against them.

## Prerequisites

- Hugo extended, Go, and Node (for Pagefind) locally — the site is built on your
  machine, not on Vercel.
- A local checkout of [hugo-theme-ledger](https://github.com/renesugar/hugo-theme-ledger).
  `--vercel` with Bluge search requires `--ledger-theme`: Vercel's Go runtime
  wants `go.mod` at the project root, and Hugo's module mode claims that same
  file.
- The [Vercel CLI](https://vercel.com/docs/cli), or a Git repository connected to
  a Vercel project.

## 1. Generate and build

```bash
python3 -B obsidian2site.py \
  --input ~/twitter_vault \
  --output ~/twitter_site \
  --title "Twitter Archive" \
  --ledger-theme ~/projects/hugo-theme-ledger \
  --search-backend both \
  --vercel \
  --build
```

`--build` runs Hugo, Pagefind, `go build`, and the Bluge indexer, then reports
the site against Vercel's limits:

```text
built Hugo site in '~/twitter_site/public'
Vercel deployment readiness:
  built site: 49,277 files, 397 MB
    ! 49,277 files exceeds Vercel's 15,000-file limit for a CLI deployment. …
  Bluge index: 97 MB
```

Every line prefixed `!` is a hard platform limit, not a suggestion.

**`--search-backend both` is the right choice here.** It selects the theme's
`auto` search backend, which probes `/api/health` and uses Bluge when a server
answers and Pagefind when none does. The same build then works whether or not
the functions are reachable — including on your machine, where
`server/movenotes-site-server` serves the whole site itself.

## 2. What the generator emitted

```
~/twitter_site/
  vercel.json          outputDirectory + the index the functions need
  .vercelignore         keeps Hugo's inputs out of the upload
  go.mod  go.sum        root module: Vercel's Go runtime requires this location
  api/search.go         GET /api/search
  api/health.go         GET /api/health
  server/               the implementation, plus the JSONL and the built index
  public/               the built site — Vercel's CDN serves this
```

`vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "outputDirectory": "public",
  "functions": {
    "api/*.go": {
      "includeFiles": "server/bluge-index/**",
      "maxDuration": 30
    }
  }
}
```

Three things about it are deliberate:

- **No `buildCommand`.** The site is built locally. Hugo, Pagefind and a Bluge
  index inside one [45-minute build](https://vercel.com/docs/limits#build-time-per-deployment)
  is not a plan for a six-figure archive, and building the index there would make
  it a build product rather than something you can inspect before deploying.
- **`includeFiles`** names the index explicitly. It is data, not code, so nothing
  discovers it for you. See
  [`functions`](https://vercel.com/docs/project-configuration/vercel-json#functions).
- **No `trailingSlash`.** The theme links to directory-style paths (`/search/`,
  `/tags/x/`) while notes are `.html` files. Enforcing either form turns every
  internal navigation into a 308.

The functions serve **no static files**: `public/` for a large archive is
hundreds of megabytes, far past the
[250 MB function bundle](https://vercel.com/docs/functions/limitations#bundle-size-limits).
Vercel's CDN serves it; only `/api/*` reaches Go.

## 3. Deploy

### Small archives: from your machine

```bash
cd ~/twitter_site
vercel deploy --prod
```

This uploads the project as source files, which is subject to **15,000 files**
and **100 MB (Hobby) / 1 GB (Pro)**. That covers roughly 5,000 notes.

### Larger archives: from Git

Commit the generated project, push it, and connect the repository to a Vercel
project. A Git deployment clones in the build container instead of uploading, so
the CLI's file-count and upload limits do not apply.

```bash
cd ~/twitter_site
git init -b main
git add -A && git commit -m "Generated archive"
git remote add origin git@github.com:you/twitter-archive.git
git push -u origin main
```

`--vercel` leaves `public/` and `server/bluge-index/` **out** of the generated
`.gitignore`, unlike an ordinary generation, because those two are exactly what a
Git deployment ships.

In the Vercel project's settings, leave the framework preset as **Other** and
the output directory as `public`. There is no build step to configure.

> A repository holding a six-figure archive plus its built output is large. That
> is the trade for not rebuilding it on every deploy.

## 4. Configure and verify

The functions read their configuration from the environment, because a
deployment has no command line:

| variable | default | set it when |
|---|---|---|
| `MOVENOTES_INDEX` | `server/bluge-index` | the index is not at the default path |
| `MOVENOTES_SOURCE` | `server/search-source.jsonl` | never needed — functions do not build indexes |

The default resolves correctly for a project laid out as generated. If
`/api/health` reports otherwise, set `MOVENOTES_INDEX` in
[Project Settings → Environment Variables](https://vercel.com/docs/environment-variables).

Then check the deployment, in this order:

```bash
# 1. Is the search server answering at all, and did the index ship?
curl -s https://your-site.vercel.app/api/health
# {"backend":"bluge","notes":166654}

# 2. Does a query work?
curl -s 'https://your-site.vercel.app/api/search?tag=economics&per=2'
```

**Check `/api/health` explicitly.** The `auto` backend makes a broken Bluge
deployment invisible: if the index did not ship, the probe fails, the browser
quietly falls back to Pagefind, and search still works. You would notice only
that `since:`/`until:` queries report themselves as unsupported. A 503 from
`/api/health` names the path it looked for:

```text
search index unavailable: no Bluge index at "server/bluge-index": build it
before serving, with 'movenotes-site-server -index-only'
```

> **Unverified:** whether Vercel copies `server/bluge-index/**` into the function
> bundle exactly as `includeFiles` describes has not been confirmed on a real
> deployment. The health check above is how you find out, and the failure is loud
> rather than silent.

## 5. What runs where

- **The filesystem is read-only**, with a 500 MB writable `/tmp`
  ([runtimes](https://vercel.com/docs/functions/runtimes#file-system-support)).
  The index is only ever read: Bluge opens a directory with no write permission
  at all, searches it, and creates nothing. That is verified by a test in
  `site_server/search/service_test.go`, not assumed.
- **The index is never built by a request.** Indexing 100k notes takes minutes.
  A function with no index answers 503 rather than trying.
- **Cold starts.** The index is opened on the first request that needs it and
  then shared for the life of the instance, so only that request pays. Functions
  are also
  [archived](https://vercel.com/docs/functions/runtimes#archiving) after two weeks
  without traffic, which adds at least a second to the next one — for a personal
  archive that is read occasionally, expect the first search of the month to be
  slow.
- **Two functions.** Hobby allows 12 per deployment without a framework.
- `maxDuration` is 30 s. A Bluge query on a six-figure archive answers in tens of
  milliseconds; the budget exists for the cold open.

## Limits, measured

From a generated 20,000-note archive, so the per-note figures are real:

| | measured at 20k notes | per note | limit |
|---|---|---|---|
| files in `public/` | 49,277 | 2.5 | **15,000** per CLI deployment |
| size of `public/` | 397 MB | 20 KB | **100 MB** Hobby, **1 GB** Pro (CLI) |
| Bluge index | 97 MB | 4.85 KB | **250 MB** function bundle, shared with the binary |

Which gives the thresholds at the top of this page: the CLI's file count runs out
around **6,000 notes**, its Hobby upload limit around **5,000**, and the function
bundle around **45,000**.

The corpus behind those numbers is deliberately unkind — 181 unique words per
note, each becoming a tag — so real prose should do better. Measure your own:

```bash
find ~/twitter_site/public -type f | wc -l      # against 15,000
du -sh ~/twitter_site/public                    # against 100 MB / 1 GB
du -sh ~/twitter_site/server/bluge-index        # against 250 MB
```

`--build --vercel` prints all three and flags the ones you exceed.

## Past the ceiling

When the index no longer fits a function, or the archive is simply too large,
three options in increasing order of effort:

**1. Publish statically, search statically.** Regenerate with
`--search-backend pagefind --vercel`. No Go, no functions, no bundle limit — and
no `--ledger-theme` requirement either. Pagefind is comfortable up to about 25k
notes; past that, filter queries get slow and deep paging gets slower. See the
theme's `PERFORMANCE.md` for the measured curve.

**2. Keep Vercel for the site, run Bluge elsewhere.** Deploy the static site as
above, run `server/movenotes-site-server` on a host that keeps a process
(a VPS, Fly.io, a container), and point the theme at it:

```toml
# hugo.toml
[params.search]
  backend = "bluge"                        # or auto, to fall back when it is down
  endpoint = "https://search.example.com/api/search"
  healthEndpoint = "https://search.example.com/api/health"
```

A cross-origin endpoint needs CORS on that server, or a Vercel
[rewrite](https://vercel.com/docs/project-configuration/vercel-json#rewrites) so
the browser stays same-origin:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://search.example.com/api/:path*" }
  ]
}
```

A proxied request has its own [120-second ceiling](https://vercel.com/docs/limits#proxied-request-timeout),
which no Bluge query approaches.

**3. Split the archive.** Several smaller sites, each inside the limits, is
sometimes the honest answer for a very large vault — the tag index and search are
per-site, so this costs cross-archive search.

## Troubleshooting

| symptom | cause |
|---|---|
| `/api/health` 503 naming a path | the index did not ship, or is elsewhere — set `MOVENOTES_INDEX` |
| search works but `since:` says it was ignored | the `auto` backend fell back to Pagefind; the Bluge functions are not reachable |
| deployment fails on file count | over 15,000 source files — deploy from Git |
| deployment fails on size | over the 100 MB/1 GB upload limit — Pro, or Git |
| `/api/search` 404 | `api/` was not deployed; check `.vercelignore` and that `go.mod` is at the project root |
| build detects a Go project on a static-only deploy | Hugo's own `go.mod` was uploaded; `--vercel` adds it to `.vercelignore` for `pagefind` builds |

## References

- [Using the Go Runtime with Vercel Functions](https://vercel.com/docs/functions/runtimes/go)
- [Zero-configuration Go backend support](https://vercel.com/changelog/zero-configuration-go-backend-support)
- [Vercel Functions limits](https://vercel.com/docs/functions/limitations)
- [Runtimes: filesystem, archiving, functions per deployment](https://vercel.com/docs/functions/runtimes)
- [Platform limits: files, uploads, build time](https://vercel.com/docs/limits)
- [`vercel.json` configuration](https://vercel.com/docs/project-configuration/vercel-json)
- `STATIC_SITE.md` — generating and serving the site locally
- `site_server/README.md` — the two entry points and their configuration
