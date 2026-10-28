# Documentation

[`README.md`](../README.md) says what movenotes is, lists the scripts, and gives
the shortest path through each workflow. These pages have the rest.

## Workflows

| Page | Covers |
|---|---|
| [Joplin RAW directories](joplin.md) | `joplin2sql.py`, `sql2joplin.py`, merging sources, `removedups.py`, `cleanres.py`, PDF OCR metadata |
| [Twitter/X archives](twitter.md) | `twitterx2sql.py`: tweets, media, reply context and `t.co` expansion |
| [Obsidian vaults](obsidian.md) | `obsidian2sql.py`, `sql2obsidian.py`, the preservation bundle, a damaged bundle, and the lossless round trips |
| [Notrios publications](notrios.md) | `notrios2sql.py`, and publishing a Notrios library through to a site |
| [Images](images.md) | `images2resources.py` and `quarantinelinks.py`: localizing embedded and remote images |

## Publishing a site

| Page | Covers |
|---|---|
| [Static site](static-site.md) | `obsidian2site.py`: Hugo with the Ledger theme, Bluge and Pagefind search, tags, conversion rules |
| [Deploying to Vercel](deploy-vercel.md) | server-side Bluge search, with the measured platform limits |
| [Deploying to GitHub Pages](deploy-github-pages.md) | a static Pagefind site, with the measured platform limits |
| [Quartz](quartz.md) | publishing a smaller vault with Quartz |

## Reference

| Page | Covers |
|---|---|
| [Testing](testing.md) | running the suite and what each module covers |
| [Schema references](schema.md) | the Joplin and Obsidian schemas the database follows |
| [Notrios import contract](notrios-import-contract.md) | what the importer admits from a Notrios archive, pinned to the producer's source |
| [Notrios import design](notrios-import-design.md) | the importer's modules, identities, staging and limits |
| [Performance review](performance-review.md) | complexity decisions and their measurements |
| [Implementation review](implementation-review.md) | a dated comparison with an independently written implementation of the same requirements |

No plan is active now; the next will be `PLAN.md`, with its ledger at
`docs/plan/ledger.json`. Finished plans and their ledgers are in
[`plans/`](../plans/README.md), and what comes next is in
[`ROADMAP.md`](../ROADMAP.md).
