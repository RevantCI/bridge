# Bridge 0.10.3

Bridge 0.10.3 is a patch release on 0.10.2 that carries out Group A of the
September simplification audit: dead protocol layers, unused modules and
point-in-time documents are removed, and two small performance fixes land.
Nothing about the on-disk project shape, the three schema ladders, the
correction ledger, the goldens or the confidence thresholds changes; a project
created by 0.10.0, 0.10.1 or 0.10.2 opens unchanged.

## What was removed

Every item below had no caller in the UI, no importer in the engine, or both.
Each was re-verified against the code before deletion; the ones where the audit's
claim turned out to be incomplete are noted.

- **13 engine methods no Tauri command could reach** (#102):
  `project.sweepStart/Status/Cancel`, `semanticMapping.getForVerse/confirm/rerunForVerse`,
  `versification.detect/orgRef/backVersificationMap`,
  `alignment.corpusStats.summary/forVerse`, `verse.evidence`, and the sweep job
  manager behind the first three. The modules they wrapped stay: versification
  (used by the Stage 4 runtime), alignment statistics (behind the live
  inconsistent-rendering finding, whose cache and invalidation are untouched)
  and the Stage 3 modules.
- **`ai.explain`** (#105), a synchronous duplicate of what the `ai.review` job
  does per verse, with no UI caller. Its selection-gate tests now drive the live
  `ai.review.start` job instead, with unchanged assertions.
- **47 protocol methods' Rust and TypeScript layers** (#103): every Stage 4 to 8
  direct-access method except the two range getters the Alignment Review
  passage view uses, plus `saveAlignment`, `completeAlignment`,
  `alignmentBackups`, `logos.*`, `paratextSetReference`, `triageClear`,
  `scanProject` and `projectCollectionReport`. The Rust shell goes from 137 to
  90 commands, the client from 137 to 90 methods. The 1,491-line Rust mirror of
  the passage-semantic types (`passage_semantic_wire.rs`) is gone; the JSON
  schema it mirrored stays. The engine handlers all stay: the Stage 5 to 8 tests
  drive them by method string, and Logos remains reachable through
  `navigation.*`.
- **Five engine modules with no importer** (#104): the two machine-proposed
  benchmark evaluators, the Paratext registry HTTPS client, the Tk caret helpers
  from the legacy tool, and the Git identity reader. The benchmark datasets stay
  bundled.
- **The corpus-discovery generator** behind the finished IRVTam review (#101),
  and the dead `showSource` store (#106).
- **Docs**: six point-in-time review documents and `HANDOFF.md` moved to
  `docs/archive/` with an index (#107). About 5.9k lines leave the reading
  path; nothing is deleted, and every inbound link is re-pointed.

## Performance

- **The desktop navigation poll no longer round-trips while sync is off**
  (#110). The 800 ms tick used to cross Rust, stdio and Python about 75 times a
  minute even with neither Paratext nor Logos enabled. It now returns before the
  request unless a connector is enabled. Enabling sync in Settings starts the
  round-trips on the next tick, as before. This is verified from the code and
  the test suites, not yet in the installed app; the issue stays open for that
  check.
- **`project.open` has a 180 s timeout** (#112 step one) instead of the 30 s
  default, the same class as `project.inspectImport`, so a slow or scanned disk
  cannot make the shell give up while Python is still opening a book.

## What stayed, on purpose

- **The Stage 3 semantic-mapping engine and the AI alignment-proposal path.**
  Their removal is a separate recorded decision (#109) and is not in this
  release.
- **The four collection-report entry points** (#108), likewise.
- **`verse_evidence.py`** now has no importer outside its tests; whether it is
  the intended shared evidence shape or dead is #120.
- **Six more caller-less client methods and sixteen unused TypeScript exports**
  the audit did not name are recorded in #121, not removed here.

## Known limitations

- **One commit reached `main` with a failing engine test** (the #103 batch
  deleted a Rust file that one Python test read as text); the fix followed in
  the same session and `main` is green again at the commit this release is cut
  from. The lesson is recorded in `docs/BUILD_LOG.md`.
- The frozen-sidecar smoke check lost its versification, corpus-stats and
  `ai.explain` blocks with their methods; it still stops at the pre-existing
  `project.inspectImport` duplicate-classification mismatch, so the release
  workflow's smoke step remains `continue-on-error`.
- 0.10.0's upgrade rules still apply: a project holding any pre-cutover file
  store refuses to open and must be re-imported. See `RELEASE_0.10.0.md`.
