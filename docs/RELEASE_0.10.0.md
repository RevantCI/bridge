# Bridge 0.10.0

Bridge 0.10.0 finishes the move of every Bridge-private store from JSON
files into SQLite (#44: #75, #76, #77). Review decisions, QA dispositions,
issue resolutions, alignment history, semantic mappings, the progress
rollup, check-finding snapshots, the check cache, triage verdicts and
metrics are all rows in a per-project `bridge-workbench.sqlite3` with an
append-only `change_log`. The project registry, non-secret settings and a
per-project progress cache live in an app-level `workspace.sqlite3`;
`settings.json` now holds only DPAPI-wrapped secrets.

This is a minor version, not a patch, because **projects created by 0.9.x
do not open in 0.10.0.** See "Before you upgrade".

## Before you upgrade

Bridge is pre-release and no user data is migrated. A project whose
`.apps/translationCoreAI/` still holds any of the old file stores
(`decisions/`, `qaDecisions/`, `review/`, `terminology/`, `aiReview/`,
`issueResolutions/`, `alignmentHistory/`, `alignmentDiagnostics/`,
`semanticMappings/`, `semanticValidation/`, `checkFindings/`, `triage/`,
`metrics/`, `checkCache.json`) or a `.bridge/progress.json` refuses to
open with a message naming what it found. Nothing is deleted from disk.

Two remedies:

- **Re-import** the source (Import → same USFM or Paratext folder). This is
  the supported path.
- **Strip the old stores** and keep the folder: delete the directories and
  files named above from the project. Everything else in the project is
  untouched and it opens normally. Review decisions in those files are
  lost, which is the pre-release trade this release makes deliberately.

`project-registry.json` is read once into the new registry table on first
start, so every project you had listed stays listed, then the file is
renamed `project-registry.imported-<stamp>.json`.

## Highlights

- **Three versioned schema ladders.** The semantic database (v16), the
  workbench (v2) and the workspace (v2) each carry their own version
  number and forward-only migration blocks; a database newer than the
  build understands is refused rather than downgraded.
- **The multi-book dashboard reads one cache query**, not one file per
  book. `project.open` repairs a stale or missing entry from the
  workbench's own change log, so a project folder copied from another
  machine, or a reset workspace, heals on the next open.
- **Sync readiness, no server.** The workbench exposes an unsynced-event
  cursor, acknowledgement, and JSON-lines export/import of event batches
  with `base_revision` conflicts surfaced rather than overwritten — the
  local half of the team hub (#80), which is a later release.
- **Batched writes.** A book-wide check job commits its progress rows in
  one transaction instead of one per finding.
- The AI review prompt no longer promises the model "human-approved
  terminology rules" that no UI could record (#93 → #95).
- Two wall-clock test budgets are calibrated to what they prove (#90).

## Safety properties retained

- No Scripture is changed without explicit human Apply confirmation; the
  Stage 9B.3b authorized write remains the only Scripture writer.
- `change_log` rows are immutable except for `synced_at`, enforced by
  triggers, and a deletion is logged as an event carrying the row's last
  image. The correction ledger, token lineage and staleness invariants
  are unchanged.
- Every workbench write carries the local user id and device id; renaming
  yourself changes how you are shown, never which rows are yours.
- Nothing in this release writes to translationCore's own files.
- Offline operation is unchanged; no network is touched on any path.

## Known limitations

- `triage.results` opens each opened sibling's workbench read-only; on a
  fully opened 66-book collection that is about one second on the report
  screen (#94).
- The dashboard cache is not faster than warm file reads (25–32 ms vs
  19 ms on 66 books); its benefit is against opening 66 databases, which
  is what a cold cache costs once. Numbers and method: `docs/BUILD_LOG.md`
  2026-09-15.
- Windows (`x86_64-pc-windows-msvc`) is the only verified target.
- The frozen sidecar smoke (`scripts/smoke_sidecars.py`) runs in the
  release workflow as `continue-on-error`; check its step output rather
  than trusting a green build.
