# Twitter/X archives

## Import a Twitter/X archive into SQLite

Download your archive from X (`Settings → Your account → Download an archive
of your data`), extract the ZIP, then:

```
python3 -B twitterx2sql.py \
  --input  ~/twitter-archive \
  --output ~/notes_sqlite \
  --notebook Twitter \
  --timezone America/Vancouver
```

No Twitter/X API access is used — only the archive files are read
(`data/tweets*.js`, `data/account.js`, and the media folder; legacy
`tweet*.js` archives also work). Tweets become notes in the notebook named
by `--notebook` (default `Twitter`); the notebook is created if missing and
reused if it already exists, so archives can be merged into a database
alongside Joplin notebooks. Each note keeps the tweet's timestamps and a
`source_url` pointing at the original post; photos and other media become
attachments embedded in the note. Reply context, a linked date/time in the
selected local zone, retweet count, and favorite count are included in the
Markdown body. `--timezone` accepts an IANA name; when omitted, the machine's
local zone is used.

`t.co` short links are expanded in two layers: first offline, from the URL
entities stored in the archive itself (this covers almost all links); any
`t.co` link still left is resolved over the network with a HEAD request
that follows redirects. Relative redirect targets such as `/user/status/id`
and scheme-relative targets such as `//x.com/user/status/id` are resolved
against the current URL before the next request. Results are cached in
`tco_cache.json` in the output directory so re-runs don't re-fetch. Invalid
relative values written by an older cache are ignored and fetched again.
Pass `--no-expand-tco` to skip the network step.

Re-importing the same archive creates duplicate notes with identical
content (attachment ids are derived from file content, so embeds are
reproducible); run `removedups.py` afterwards to remove them.
