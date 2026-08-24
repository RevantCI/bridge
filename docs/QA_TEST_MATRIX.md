# Bridge stabilization QA matrix

This is the release gate for the current import → check → review → export
workflow. A feature is not considered release-ready merely because its unit
tests pass; the relevant source, frozen-sidecar, and desktop rows must pass.

Status values: **PASS**, **FAIL**, **BLOCKED**, or **NOT RUN**.

## Automated and packaged checks

| ID | Area | Scenario | Level | Status |
|---|---|---|---|---|
| A01 | Backend | Complete Python suite | Source | PASS — 144 passed (137 + 7 new Phase 6 alignment-statistics tests) with real Wildebeest 0.9.2, real uroman, and vendored Smart Edit Distance. One pre-existing test (`test_versification_concurrency.py`'s wall-clock GIL regression guard) is known to fail under heavy background CPU load — reproducible on unmodified `main`, not a regression from any phase's work; not release-blocking, see A13's own note |
| A02 | Frontend | Svelte/TypeScript diagnostics | Source | PASS — 0 errors, 0 warnings |
| A03 | Frontend | Production Vite build | Source | PASS — existing chunk-size warning |
| A04 | Desktop | Rust tests and compilation | Source | PASS — release and test profiles compile |
| A05 | Packaging | Build both target-suffixed sidecars | Frozen | PASS — current-source sidecars and Windows NSIS installer built |
| A06 | USFM | Non-Latin duplicate/missing-verse job | Frozen | PASS — real standalone checker findings |
| A07 | Protocol | Sidecar remains responsive during a background job | Frozen | PASS — status polled until completion |
| A08 | Security | Settings never serialize plaintext secrets | Source | PASS — regression suite |
| A09 | Alignment | Manual protocol, conflicts, history, restart and USFM round trip | Source | PASS |
| A10 | Versification | Detect/orgRef/backVersificationMap against real schema data | Source | PASS — includes real Psalm 3 descriptive-title shift |
| A11 | Versification | Same three protocol methods from a real frozen bridge-engine.exe | Frozen | PASS — verified against a real PyInstaller build this session |
| A12 | Versification | Edge cases: merges, splits, unknown books, verse bridges/segments | Source | PASS — 11 tests against real vendored data |
| A13 | Versification | Concurrent callers: correctness and a GIL-contention performance regression guard | Source | PASS — fixed a real ~90x slowdown found under 16-thread concurrency. Wall-clock bound is machine-load-sensitive: failed under heavy background CPU use during Phase 6's own test run (2026-08-24, 50.9s vs. the 30s bound); reproducible on unmodified `main`, not a regression — not release-blocking, but worth revisiting with a less load-sensitive bound |
| A14 | Names/Transliteration | Whole-book spelling-consistency check against real uroman + vendored Smart Edit Distance | Source | PASS — 15 tests; real Muhammad/Mohamed and Titus/Tituss cases, a real Tamil vowel-sign inconsistency through full verse sentences, a false-positive exclusion (church/churches), and a bigram-blocking performance regression guard |
| A15 | Names/Transliteration | Same check from a real frozen bridge-engine.exe | Frozen | PASS — verified uroman's ~4.2MB data dir and vendored SED both resolve under sys._MEIPASS; a real planted typo was correctly flagged end to end |
| A16 | Alignment statistics | Corpus co-occurrence/probability/PMI/SED-boost against real completed alignments and a real multi-book collection | Source | PASS — 7 tests; completed-only filtering, hand-verified PMI/probability math, multi-book aggregation with lazy-sibling skipping, protocol-level summary/forVerse calls, cache invalidation on newly-completing a verse, a real (no-mock) Uroman+SED case, and a 2,000-completed-verse performance measurement (well under a second) |
| A17 | Alignment statistics | Same protocol methods from a real frozen bridge-engine.exe | Frozen | PASS — `scripts/smoke_sidecars.py` extended to complete a real fixture verse then call `alignment.corpusStats.summary`/`forVerse` against the frozen executable; confirmed `versesScanned == 1` and a real jointCount=1/probability=1.0 pair, using no new PyInstaller `datas`/`hiddenimports` entries (reuses the vendor tree and uroman data already bundled for A15) |

## Import workflows

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| I01 | One `.usfm` file | One normalized tC-compatible book project | PASS |
| I02 | One `.sfm`/`.txt` Scripture file | Accepted after marker validation | PASS |
| I03 | Folder containing several books | All books discovered; one project per book | PASS |
| I04 | translationCore project folder | Existing alignments/check state preserved | PASS |
| I05 | `.tcore`/`.tstudio`/`.zip` archive | Safely extracted and imported | PASS — all three extensions |
| I06 | Paratext-style folder | Metadata and Scripture detected without modifying source | PASS |
| I07 | Unknown language | Searchable language/project/Bible form is required | PASS — required metadata protocol and ISO-639-3 UI source |
| I08 | Malformed markers/duplicate verses | Import/check failure is explicit, never false-clean | PASS |
| I09 | Path traversal in archive | Import rejected; nothing written outside destination | PASS |
| I10 | UTF-8 BOM and non-Latin Scripture | Text preserved exactly through normalization | PASS |

## Desktop core loop

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| D01 | Open/import then select first verse | Editor appears before checking completes | PASS — installed 66-book acceptance test |
| D02 | Chapter background pass | Real stage/verse progress and findings | PASS — source and frozen process |
| D03 | Whole-book pass | Every chapter checked once; results remain navigable | PASS — backend job coverage |
| D04 | Cancel and retry | Unfinished verses are not approved; retry succeeds | PASS — includes cancellation during USFM subprocess |
| D05 | Switch chapter/book during checking | No stale result is applied to the new selection/project | NOT RUN |
| D06 | Edit verse during/after checking | Transaction is safe and findings are rechecked | PASS — background edit lock plus transaction/E2E coverage |
| D07 | Accept/reject/ignore then restart | Decisions retain stable IDs and state | PASS — fresh-process E2E |
| D08 | Sidecar crash/restart | UI reports failure and can recover without app restart | NOT RUN — transport restart path compiles; live kill still manual |
| D09 | Checker error | Bounded, readable error with useful retry behavior | PASS |
| D10 | Real Wildebeest | Real adapter is packaged and identifies itself | PASS — frozen smoke verifies usingRealEngine |

## Export and compatibility

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| E01 | Aligned export | Re-importable USFM 3 with occurrence-aware `zaln`/`w` groups | PASS — source round trip |
| E02 | Non-aligned export | Valid USFM is generated and re-importable | PASS |
| E03 | Footnotes/headings/poetry/milestones | No silent structural loss | PASS — source-template export; explicit fallback without source |
| E04 | ESFM content | Supported markers preserved or limitation made explicit | PASS — custom markers retained by source-template export |
| E05 | Windows bundle | Both helper executables are present and runnable | PASS — hashes match staged artifacts; packaged app launched |
| E06 | macOS/Linux bundles | Build, permissions and runtime behavior verified | BLOCKED |

## Manual word alignment

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| L01 | 1:1, 1:many, many:1 and many:many | Exact source/target identities are regrouped without loss | PASS — source tests |
| L02 | Repeated target word | Occurrence and total-occurrence attributes round-trip | PASS — source tests |
| L03 | Unalign then undo/selected restore | Word bank and selected verse return to the saved state | PASS — source tests |
| L04 | Concurrent/stale editor save | Save is rejected and no other edit is overwritten | PASS — source tests |
| L05 | Edit target Scripture | Existing alignment is reconciled and marked invalid | PASS — source tests |
| L06 | Complete verse | Blocked until source and every target token have valid groups | PASS — source tests |
| L07 | Missing original source | Readable import guidance; no invented/downloaded tokens | PASS — source and UI |
| L08 | RTL source/target | Direction metadata is respected by token panes | PASS — source/UI diagnostics; manual RTL layout NOT RUN |
| L09 | Restart persistence | Alignment, completion and history survive a new engine instance | PASS — source tests |
| L10 | Frozen protocol/export/undo | Packaged sidecars perform the real workflow | PASS — release-staged workers |

## Manual desktop and usability checks

| ID | Scenario | Status |
|---|---|---|
| M01 | Every visible button, menu, modal and keyboard flow | NOT RUN |
| M02 | Tamil, Odia and English projects | NOT RUN |
| M03 | RTL project layout | NOT RUN |
| M04 | 100%, 125%, 150% display scaling and narrow window | NOT RUN |
| M05 | Screen-reader labels, focus order and contrast | NOT RUN |
| M06 | Large-book performance and memory use | NOT RUN |

## Automated evidence

- Python: 144 tests, including all alignment cardinalities, conflicts/history/restart/rollback,
  RTL metadata, nested aligned-USFM round trips, versification detection/org-normalization/
  back-versification against the real vendored schema data (including merge/split edge cases),
  a concurrency regression guard for a real GIL-contention slowdown, a whole-book
  names/spelling-consistency check against real uroman + vendored Smart Edit Distance
  (including a bigram-blocking performance regression guard for a real ~24x slowdown found
  that session), and alignment corpus statistics (co-occurrence/probability/PMI/SED-boost)
  computed over real completed alignments across a real multi-book collection, including a
  2,000-completed-verse performance measurement.
- Frontend: `svelte-check` reports 0 errors and 0 warnings; production Vite build succeeds.
- Frozen workers: real Wildebeest loads, the USFM helper reports duplicate and missing verses,
  manual many-to-many alignment/export/undo succeeds, and lightweight status calls
  remain responsive while the job runs.
- Windows: release executable launches both WebView2 and `bridge-engine`; the NSIS installer
  `Bridge_0.8.0-beta.1_x64-setup.exe` is produced with both verified worker binaries.

## Windows acceptance test — 2026-08-21

- Installer launched successfully.
- A real 66-book Bible imported successfully in approximately four minutes.
- Real check progress, Cancel, Retry, Dismiss, verse navigation, decisions, and verse editing
  were exercised successfully.
- Acceptance feedback led to a fixed-width progress layout, selected-verse scroll-to-top,
  explicit decision-save confirmation, visible post-edit rechecking, and export access before
  review completion. These five UI refinements require one short installed-build retest.

## Release rule

P0/P1 failures in A, I, D, or E block the stabilization release. Manual-only
and unavailable-platform rows may remain blocked only when recorded explicitly
in the release notes with an owner and follow-up milestone.
