# Bridge 0.10.2

Bridge 0.10.2 is a patch release on 0.10.1 that removes one finished
research workflow from the app: the **Validate semantic mappings** screen and
everything behind it. Nothing about the on-disk shape, the three schema
ladders, or the 0.10.0 upgrade rules changes; a project created by 0.10.0 or
0.10.1 opens unchanged.

## What was removed

The project dashboard carried a **Validate semantic mappings** button (shown
as **Enable semantic validation** outside Advanced mode). It opened a review
queue of 40 machine-proposed cross-verse mappings in the Tamil IRV Luke and
Philippians corpus, built to check the Stage 3 semantic-mapping engine
against a human. That review was completed on 2026-08-31 (38 confirmed, one
corrected, one rejected) and the queue had no further purpose, so issue #100
removed it end to end:

- the dashboard button and the validation screen;
- the `semanticValidation.list` and `semanticValidation.decide` protocol
  methods, their Tauri commands and the engine service behind them;
- the bundled validation manifest: the installer no longer carries
  `resources/semantic_mapping/validation/`, and the sidecar build script no
  longer fails when it is absent;
- the generator script that produced the manifest, and its tests.

The Settings toggle **Allow manual override** stays. It still gates the
translation-helps review panel; it just no longer unlocks a second screen.

## What stayed, on purpose

- **The Stage 3 semantic-mapping engine** underneath the queue. The optional
  AI review still builds its prompt context from it and still shows a
  `semantic_mapping` block on AI check reviews. Removing that engine is a
  separate, recorded decision (see `docs/SIMPLIFICATION_AUDIT_2026-09.md`,
  item B1) and is not part of this release.
- **No schema change.** The `semantic_validation_runs` table remains in the
  workbench database's v1 block, empty and unused, because the migration
  ladder is never edited in place. A future workbench bump may drop it.
- **The pre-cutover guard.** A project holding a pre-0.10.0
  `semanticValidation/` directory still refuses to open and must be
  re-imported, exactly as in 0.10.0 and 0.10.1.

## Record of the review

The per-project audit files that held the 40 raw decisions no longer exist
on any machine; the Tamil IRV projects were re-imported after the 0.10.0
data reset. The summary table in `docs/DEVELOPER_GUIDE.md` ("Historical
Beta 15 developer handoff") and `docs/validation/README.md` are the surviving
record, and the generated candidate manifest stays in `docs/validation/` as
evidence. QA matrix rows M29 to M35 are retired.

## Also in this release

- `docs/ARCHITECTURE.md` is rewritten as a current-state map of the code
  (process boundary, the three databases, pipelines, UI surfaces), and
  `docs/SIMPLIFICATION_AUDIT_2026-09.md` records what is slowing development
  down and what is slated for removal. Documentation only; no behaviour
  change.

## Known limitations

- This is the first release build to run the trimmed sidecar build script.
  The change is a pure deletion of a copy step, and the frontend, Rust and
  Python gates passed on the source; the installer itself is the evidence
  that the frozen pair is unaffected.
- The frozen-sidecar smoke check still stops at the pre-existing
  `project.inspectImport` duplicate-classification mismatch, so the release
  workflow's smoke step remains `continue-on-error`.
- 0.10.0's upgrade rules still apply: a project holding any pre-cutover
  file store refuses to open and must be re-imported. See
  `RELEASE_0.10.0.md`.
