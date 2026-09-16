# Bridge 0.10.1

Bridge 0.10.1 is a patch release on 0.10.0 with one purpose: importing a
whole Bible, and opening a large book for the first time, no longer time
out. Nothing about the on-disk shape, the three schema ladders, or the
0.10.0 upgrade rules changes; a project created by 0.10.0 opens unchanged.

## What was wrong

The first import after the 0.10.0 data reset (hin-irv, 66 books) reported
`sidecar request 'project.import' timed out` although the import itself had
finished in about seven seconds. The next five minutes went into opening the
first book, Genesis, inside two places in the semantic runtime that each did
one SQLite commit, and therefore one fsync, per record:

- **The alignment compatibility scan.** A raw import writes every unaligned
  source word as its own alignment group with an empty target side. The scan
  quarantines each of those as `LEGACY_EMPTY_BOTTOM_WORDS_AMBIGUOUS`, one
  commit each: 20,612 commits for Genesis, 5m11s.
- **Verse revision setup.** The first open establishes a
  `current_target_revisions` row per verse, one read connection and one
  commit each: 1,533 commits for Genesis, about 21 seconds.

Neither was new. Both date from Stages 3 and 4 and surfaced now because a
whole-Bible import always opens Genesis first. Against the 30 second
`project.open` timeout, every first open of a book over roughly 2,000 source
words, which is most of the Bible, would have failed the same way and then
succeeded on a retry once the memoized work had finished in the background.
Issue #99 has the full timeline and evidence.

## What changed

- Both writers batch. The scan collects its quarantine records and writes
  them in one transaction; verse revisions are read once for the book and
  every new one is established in one transaction. The single-record methods
  remain and delegate to the batch ones, so every other caller is unchanged.
- `project.open` and `project.import` each write one `[trace]` line to
  stderr with wall-clock seconds per phase. The Rust shell relays it into
  the diagnostics panel and `engine-events.log` under the app's log folder.
  It currently shows at level "warn" because the relay only distinguishes
  tracebacks; that mapping is a follow-up on #99.

Measured in the desktop app on the same laptop, same 66-book import:

| Request | 0.10.0 | 0.10.1 |
|---|---|---|
| `project.import`, 66 books | timed out at 300s | 7.5s |
| Open of the first book inside the import | 5m11s | 0.9s |
| Exodus, first open | about 22s | 2.0s |
| Exodus, re-open | 3.0s | 0.4s |

## Safety properties retained

- No schema change in any of the three databases. `migration_quarantine`
  and `current_target_revisions` are the same tables with the same rows;
  only the number of transactions producing them changed.
- The scan's crash-safety is unchanged: both digests are still plain
  content-addressed idempotency checks, and a crash between the batch and
  its `migration_runs` row simply redoes the scan.
- A verse whose text changed outside Bridge still takes the per-reference
  prepare/apply intent pair; only the establish-new path is batched.
- Nothing auto-applies, nothing touches Scripture or native alignment data.

## Known limitations

- The frozen-sidecar smoke check still stops at the pre-existing
  `project.inspectImport` duplicate-classification mismatch, so the release
  workflow's smoke step remains `continue-on-error`. The checks before it
  (info, resource provenance, a 66-project import, open, registry) pass on
  the 0.10.1 sidecar.
- Whether the scan should quarantine the raw-import empty-alignment shape
  at all, rather than merely quarantine it quickly, is an open design
  question on #99. This release does not change what is quarantined.
- 0.10.0's upgrade rules still apply: a project holding any pre-cutover
  file store refuses to open and must be re-imported. See
  `RELEASE_0.10.0.md`.
