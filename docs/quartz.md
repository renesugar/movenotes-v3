# Publishing with Quartz

[Quartz](https://quartz.jzhao.xyz/) is a fast, batteries-included
static-site generator that transforms Markdown content into fully
functional websites — thousands of people use it to publish personal
notes and digital gardens. The vaults produced by `sql2obsidian.py` work
as Quartz content: Quartz understands Obsidian-flavored markdown,
including the wiki-style image embeds (`![[photo.png]]`) this project
writes, and reads the `title` and `tags` fields from the exported front
matter (its created-modified-date plugin can also be configured to take
dates from front matter, where this project writes `created` and
`updated`).

Both pipelines end in the same place:

* **Joplin:** Joplin RAW Directory → SQLite → Obsidian vault → Quartz
* **Twitter/X:** Twitter/X archive → SQLite → Obsidian vault → Quartz

## 1. Export a publishable vault

Use `--notebooks` to export only the notebooks you want on the web —
private notebooks are never written into the vault, so they cannot end up
on the site by accident:

```
python3 -B joplin2sql.py --input ~/joplin_raw_export --output ~/notes_sqlite
python3 -B twitterx2sql.py --input ~/twitter-archive --output ~/notes_sqlite --notebook Twitter

python3 -B sql2obsidian.py \
  --notebooks "Blog,Twitter" \
  --input  ~/notes_sqlite \
  --output ~/public_vault
```

## 2. Set up Quartz

Quartz 5 requires Node v22+ and npm v10.9.2+:

```
git clone https://github.com/jackyzha0/quartz.git
cd quartz
npm install --allow-git=all
npx quartz create
npx quartz plugin add github:saberzero1/quartz-themes --subdir plugin
npx quartz plugin install --from-config
NODE_OPTIONS="--max-old-space-size=12288" npx quartz build --serve --concurrency=2
```

`npx quartz create` asks how to initialize the `content/` folder; choose
to import an existing folder and point it at `~/public_vault` (or copy
the vault's contents into `content/` yourself afterwards — re-run
`sql2obsidian.py` with `--output <quartz>/content` on later updates).

Quartz uses `content/index.md` as the site's home page. The export does
not create one, so add it by hand, for example:

```
---
title: Home
---
Welcome! Start with [[Blog]] or browse the tags.
```

## 3. Preview and deploy

```
npx quartz build --serve
```

serves the site at `http://localhost:8080`. When it looks right, publish
with `npx quartz sync` after setting up a GitHub repository; Quartz's
[hosting guide](https://quartz.jzhao.xyz/hosting) covers GitHub Pages,
Cloudflare Pages, Netlify, and Vercel.

Tips:

* To exclude an individual note without moving it out of a published
  notebook, add `draft: true` to its front matter in the vault before
  building — Quartz filters drafts out of the site.
* Re-exporting after notes change is cheap: unchanged attachments are
  skipped and note files are rewritten in place. Exports never delete
  files, though, so after removing or renaming notes it is safest to
  export into an empty directory and replace `content/`.
