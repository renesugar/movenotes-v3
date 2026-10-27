# Plan archive

Finished plans are archived here by the release they shipped in:

```text
plans/v<major>.<minor>/<NNN>-<slug>.md
```

`000-<slug>-plan.md` is the plan itself, kept verbatim. Its structured ledger,
when it has one, sits beside it, and its working records (evidence, reviews,
trial reports) follow as `001-…`, `002-…` in the order their slices ran. The
plan being implemented now is [`PLAN.md`](../PLAN.md) at the repository root,
and the rules for archiving it are in [`AGENTS.md`](../AGENTS.md#plans-the-roadmap-and-the-archive).

| Release | Plan | Working records |
|---|---|---|
| [v3.34](v3.34/) | [Refocus movenotes on Joplin import and export](v3.34/000-refocus-plan.md), steps 1–19 | — |
| [v3.36](v3.36/) | [Replace Relearn with Ledger, add Vercel deployment, re-open the static-search question](v3.36/000-ledger-migration-plan.md), steps 20 onward | — |
| [v3.37](v3.37/) | [Import a Notrios publication handoff](v3.37/000-notrios-import-plan.md), with its [ledger](v3.37/notrios-import-ledger.json) | [verifier audit](v3.37/001-verifier-audit.md), [tag review](v3.37/002-tag-review.md), [resource review](v3.37/003-resource-review.md), [site acceptance](v3.37/004-site-acceptance.md), [compatibility review](v3.37/005-compatibility-review.md), [C7c evidence](v3.37/006-c7c-evidence.md), [performance evidence](v3.37/007-performance-evidence.md), [P7b evidence](v3.37/008-p7b-evidence.md), [P7c evidence](v3.37/009-p7c-evidence.md), [corpus trials](v3.37/010-corpus-trials.md) |

An archived plan's ledger still renders and checks in place:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/render_plan_ledger.py --ledger plans/v3.37/notrios-import-ledger.json --check
```

These are historical records. Their prose describes the repository as it was
when they were written; only paths to moved files have been updated since.
