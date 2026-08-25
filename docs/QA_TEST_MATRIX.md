# Bridge stabilization QA matrix

This is the release gate for the current import → check → review → export
workflow. A feature is not considered release-ready merely because its unit
tests pass; the relevant source, frozen-sidecar, and desktop rows must pass.

Status values: **PASS**, **FAIL**, **BLOCKED**, or **NOT RUN**.

## Automated and packaged checks

| ID | Area | Scenario | Level | Status |
|---|---|---|---|---|
| A01 | Backend | Complete Python suite | Source | PASS — 183 passed on Windows/Python 3.12.4 with real Wildebeest 0.9.2, real uroman 1.3.1.1, and vendored Smart Edit Distance. Includes project identity, relocation validation, legacy collection grouping, corrupt-registry recovery, collection-aware exact/partial/metadata/missing-project duplicate detection, endpoint-level block/allow decisions, forget-without-delete, and portable-collection regressions |
| A02 | Frontend | Svelte/TypeScript diagnostics | Source | PASS — 0 errors, 0 warnings |
| A03 | Frontend | Production Vite build | Source | PASS — existing chunk-size warning |
| A04 | Desktop | Rust tests and compilation | Source | PASS — release and test profiles compile; 1 sidecar-timeout unit test passed |
| A05 | Packaging | Build both target-suffixed sidecars | Frozen | PASS — rebuilt for Beta 4; the `dist`, Tauri staging, and release-staged copies are byte-identical |
| A06 | USFM | Non-Latin duplicate/missing-verse job | Frozen | PASS — the real standalone checker found both conditions in the packaged Odia fixture |
| A07 | Protocol | Sidecar remains responsive during a background job | Frozen | PASS — status polling completed the background job while lightweight requests remained responsive |
| A08 | Security | Settings never serialize plaintext secrets | Source | PASS — regression suite |
| A09 | Alignment | Manual protocol, conflicts, history, restart and USFM round trip | Source | PASS |
| A10 | Versification | Detect/orgRef/backVersificationMap against real schema data | Source | PASS — includes real Psalm 3 descriptive-title shift |
| A11 | Versification | Same three protocol methods from a real frozen bridge-engine.exe | Frozen | PASS — `detect`, `orgRef`, and `backVersificationMap` succeeded against the Beta 4 release-staged worker |
| A12 | Versification | Edge cases: merges, splits, unknown books, verse bridges/segments | Source | PASS — 11 tests against real vendored data |
| A13 | Versification | Concurrent callers: correctness and a GIL-contention regression guard | Source | PASS — a fresh-process test verifies concurrent first-load correctness against real schema data; a deterministic instrumented test verifies the expensive matcher is serialized (`max_active == 1`) without using a machine-dependent deadline |
| A14 | Names/Transliteration | Whole-book spelling-consistency check against real uroman + vendored Smart Edit Distance | Source | PASS — 15 tests; real Muhammad/Mohamed and Titus/Tituss cases, a real Tamil vowel-sign inconsistency through full verse sentences, a false-positive exclusion (church/churches), and a bigram-blocking performance regression guard |
| A15 | Names/Transliteration | Same check from a real frozen bridge-engine.exe | Frozen | PASS — real Uroman and vendored Smart Edit Distance loaded, and the planted Titus/Tituss inconsistency was found through `verse.runChecks` |
| A16 | Alignment statistics | Corpus co-occurrence/probability/PMI/SED-boost against real completed alignments and a real multi-book collection | Source | PASS — 7 tests; completed-only filtering, hand-verified PMI/probability math, multi-book aggregation with lazy-sibling skipping, protocol-level summary/forVerse calls, cache invalidation on newly-completing a verse, a real (no-mock) Uroman+SED case, and a 2,000-completed-verse performance measurement (well under a second) |
| A17 | Alignment statistics | Same protocol methods from a real frozen bridge-engine.exe | Frozen | PASS — summary/forVerse returned the expected completed-alignment joint count and probability |
| A18 | AI alignment proposals | `alignment.aiPropose`/`alignment.aiApplyProposal` against real `compile_link_proposal`/`apply_proposal` logic, fake HTTP transport (no live API key) | Source | PASS — 4 tests; missing-API-key error, an accepted link compiled into a new group with the existing protected group surviving untouched, real AI-usage-totals accumulation confirmed (`settings.record_ai_usage` was dead code before this phase), a cross-link between two different established groups correctly rejected as a conflict rather than silently merged, and apply saving through the normal identity-checked pipeline |
| A19 | AI alignment proposals | Same protocol methods from a real frozen bridge-engine.exe | Frozen | PASS — packaged dispatch/imports execute and return the expected clean missing-API-key error without a live external call |
| A20 | Resource materialization | translationWordsLinks resource-level `{kt,names,other}/groups/<book>/<term>.json` index (the shape `knowledge_base.py`'s TWL reader actually reads) | Source | PASS — 3 tests; real Titus TWL data produces the correct real file layout, is idempotent, and `TranslationHelpsKnowledgeBase.twl_occurrences()` reads real materialized data end to end through a full import → verse.runChecks flow, not just "the files got written" |
| A21 | Resource materialization | translationAcademy bundling + `knowledge_base.py`'s TA-reading fix | Source | PASS — 4 tests against a real, freshly-downloaded 2.2MB/728-file `git.door43.org/unfoldingWord/en_ta` v90 tag (not a synthetic fixture): confirms the real nested-directory article shape (`checking/accuracy-check/{title.md,01.md}`), a real article read with the correct human-readable title (not the raw "01" filename stem), a graceful empty result for an unknown slug, and all 13 hardcoded `global_checking_evidence()` identifiers resolving against real content |
| A22 | AI explain | `ai.explain` (wires `prepare_verse_review`) against real materialized tN/tW/TA evidence, fake HTTP transport (no live API key) | Source | PASS — 2 tests; missing-API-key error, and a real evidence-backed run whose fake check-review response is built from checkIds discovered from the real materialized project data (not guessed), confirming real usage-total accumulation |
| A23 | AI explain | Same protocol method from a real frozen bridge-engine.exe | Frozen | PASS — packaged dispatch/evidence imports execute and return the expected clean configuration error without a live external call |
| A24 | Paratext/Logos connectors | `paratext.getState/setReference`, `logos.getState/setReference` protocol wiring — no companion Paratext plugin instance or Logos installation available on this machine | Source | PASS — 4 protocol-level tests plus 4 direct `LogosConnectorClient`↔real `logos_bridge.ps1` integration tests (real subprocess, real `-STA` PowerShell, real newline-delimited JSON exchange, a real "not installed" COM error round-tripping cleanly) — see paratext_plugin/README.md and engine/logos_connector/README.md for what remains genuinely unverified against live Paratext/Logos |
| A25 | Paratext/Logos connectors | Same protocol methods from a real frozen bridge-engine.exe | Frozen | PASS — Paratext returns the expected clean companion-unavailable response; the packaged Logos PowerShell bridge launches and cleanly reports unavailable COM integration |
| A26 | Paratext companion plugin | `paratext_plugin/TranslationCoreAIBridgePlugin.cs` — a separate .NET project, not part of the Python source tree | Build only | PASS (compile) / NOT RUN (load) — compiles cleanly via the bundled .NET Framework `csc.exe` against Paratext's real installed `PluginInterfaces.dll`/`CorePluginInterfaces.dll` (every interface member used was confirmed by reflecting into those real DLLs). Deployment into `C:\Program Files\Paratext 9\plugins\...` was not performed this session (a protected-system-directory write, blocked by this session's own safety controls) — the plugin has never actually been loaded by a running Paratext instance. See paratext_plugin/README.md for the exact next steps |

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
| I11 | Drag a file/folder from the OS onto the window (not the file picker) | Same inspect/preview/import flow as the picker | NOT RUN — `npm run check`/`npm run build` verify the code compiles; no real OS-level drag was exercised in a running Tauri window this session |
| I12 | Import the exact same source twice | Existing project is offered by default; no write without explicit separate-copy choice | PASS — protocol regression verifies exact fingerprint match, default rejection, and explicit suffixed copy |
| I13 | Same book/language/Bible with changed or unknown source | Possible overlap is shown for human review; no automatic merge or overwrite | PASS — deterministic registry classification coverage; desktop wording still needs manual acceptance |
| I14 | Move a registered project and locate it | Stable project identity is retained and the registry path is repaired | PASS — managed rename discovery and external locate regressions |
| I15 | Move a multi-book collection parent | Every sibling remains switchable through portable relative collection metadata | PASS — schema 2 move/reopen regression; schema 1 absolute paths remain readable |
| I16 | Inspect a large folder with hundreds of registered book projects | Registry discovery is not repeatedly hashed; request has bounded 180-second headroom | PASS — real 337-entry Project Home discovery measured 5.20s and a real 66-book folder inspection measured 1.58s after the fix; installed Beta 4 GUI retest NOT RUN |
| I17 | Multi-book source whose exact books are scattered across unrelated projects | Warn with exact coverage but allow a new collection; never treat the unrelated projects as one complete duplicate | PASS — registry and real `project.import` endpoint regressions |
| I18 | One existing collection exactly covers every incoming source book | Offer that collection and block the default import until separate-copy intent is explicit | PASS — registry and real `project.import` endpoint regressions |
| I19 | Same display name with different canonical book/content, or same book with different language/Bible metadata | Never classify by display name; metadata overlap remains non-blocking | PASS — canonical-book, content, language, Bible, whitespace, and case regressions |
| I20 | Exact source belongs only to a missing registered folder | Explain the missing match, allow recovery import, and retain Locate behavior | PASS — missing-path classification regression; installed wording NOT RUN |

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

## Project management

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| P01 | Restart after importing/opening projects | Project Home discovers managed projects and lists recent external projects | PASS — registry/discovery source regressions; installed GUI NOT RUN |
| P02 | Open a recent project | Project opens without browsing for its folder | PASS — command/client/UI wiring and source regression; installed GUI NOT RUN |
| P03 | Registered folder is missing | Card remains visible with Locate and Forget actions | PASS — registry and frontend diagnostics; installed GUI NOT RUN |
| P04 | Locate a moved folder | Old project ID is retained and path is updated atomically | PASS — source regression |
| P05 | Forget a missing project | Registry entry is removed; files are never deleted | PASS — source regression |
| P06 | Corrupt registry | Damaged file is quarantined and managed projects are rediscovered | PASS — source regression |
| P07 | Run the Python suite | Default `BridgeEngine()` instances use isolated temporary app data and cannot pollute the user's Project Home | PASS — autouse isolation fixture; 84 leaked Beta 3 development entries were backed up and removed from the affected machine |
| P08 | Review exact, partial, metadata-only, and missing-folder matches | Content versus metadata reason, book coverage, related project/collection, and the correct Open/Separate/Continue action are explicit | PASS — backend contract regressions plus clean Svelte diagnostics; installed GUI wording NOT RUN |
| P09 | Many related registry entries match one preview | Review remains bounded instead of rendering an unbounded list | PASS — UI shows five groups and a remaining-count summary; installed large-library GUI NOT RUN |

## Export and compatibility

| ID | Scenario | Expected result | Status |
|---|---|---|---|
| E01 | Aligned export | Re-importable USFM 3 with occurrence-aware `zaln`/`w` groups | PASS — source round trip |
| E02 | Non-aligned export | Valid USFM is generated and re-importable | PASS |
| E03 | Footnotes/headings/poetry/milestones | No silent structural loss | PASS — source-template export; explicit fallback without source |
| E04 | ESFM content | Supported markers preserved or limitation made explicit | PASS — custom markers retained by source-template export |
| E05 | Windows bundle | Both helper executables are present and runnable | PASS — Beta 4 app and NSIS installer produced; both workers are version-checked, hash-matched across staging locations, and exercised by the enhanced frozen smoke |
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
| L10 | Frozen protocol/export/undo | Packaged sidecars perform the real workflow | PASS — the Beta 4 frozen worker completed many-to-many alignment, completion, aligned export, and undo |

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

- Python: 183 tests, including all alignment cardinalities, conflicts/history/restart/rollback,
  RTL metadata, nested aligned-USFM round trips, versification detection/org-normalization/
  back-versification against the real vendored schema data (including merge/split edge cases),
  a concurrency regression guard for a real GIL-contention slowdown, a whole-book
  names/spelling-consistency check against real uroman + vendored Smart Edit Distance
  (including a bigram-blocking performance regression guard for a real ~24x slowdown found
  that session), alignment corpus statistics (co-occurrence/probability/PMI/SED-boost)
  computed over real completed alignments across a real multi-book collection, including a
  2,000-completed-verse performance measurement, real AI alignment-proposal compilation
  (fake transport, real `compile_link_proposal`/`apply_proposal` logic), a real
  translationWordsLinks resource-layout fix, real translationAcademy content (a genuine
  2.2MB/728-file download, not a fixture) with its own reading-shape fix, `ai.explain`
  against real materialized evidence, and real subprocess-level Paratext/Logos connector
  protocol tests (the Logos ones spawn the actual bundled PowerShell helper).
- Frontend: `svelte-check` reports 0 errors and 0 warnings; production Vite build succeeds.
- Frozen workers: real Wildebeest, Uroman, and Smart Edit Distance load; versification,
  a planted spelling inconsistency, corpus statistics, AI-proposal/explain packaging,
  connector error paths, Project Registry/exact-duplicate reason/count protocol, manual many-to-many
  alignment/export/undo, and USFM duplicate/missing-verse checks pass. Lightweight
  status calls remain responsive during the job.
- Windows: the Beta 4 release executable and NSIS installer were produced with both
  verified worker binaries. The installer is
  `Bridge_0.8.0-beta.4_x64-setup.exe` (SHA-256
  `256466811DBD80B9363B04E52B621CDF3E735EBFB1898D1889DD39E98776AC77`).

## Beta 4 artifact provenance — 2026-08-25

- Release source: current Milestone 2.1 duplicate-classification completion worktree (commit pending).
- Desktop executable: 12,739,072 bytes, ProductVersion `0.8.0-beta.4`, SHA-256
  `CC8617CD06C96E0FDAA5BE9B6373733AB304ECEC549AC081EB5726965D39C2BF`.
- `bridge-engine.exe`: 21,045,827 bytes, SHA-256
  `769E6B25D735B8334FBB8E8893A2281981C049177C828216A7B2FB9BD26999C9`.
- `bridge-usfm-checker.exe`: 7,673,749 bytes, SHA-256
  `91CC1C5E18CDCF0A467DAF3FE6ED79EE553D3E9C39213987FE8CFB35A62A86E1`.
- Installer: 30,672,848 bytes, ProductVersion `0.8.0-beta.4`, SHA-256
  `256466811DBD80B9363B04E52B621CDF3E735EBFB1898D1889DD39E98776AC77`.
- Exact release-staged workers passed the enhanced frozen smoke. The app, workers,
  and installer remain `NotSigned`; installed GUI and native drag-and-drop acceptance
  remain manual release gates.

## Beta 3 artifact provenance — 2026-08-25

- Release source: current Milestone 2.1 worktree (commit pending).
- Desktop executable: 12,733,952 bytes, ProductVersion `0.8.0-beta.3`, SHA-256
  `6B2889A8F06B519AA21F2CAC3CEE42CE8FBDA82DD6723E1CA4A5C98FB2361B54`.
- `bridge-engine.exe`: 21,044,442 bytes, SHA-256
  `20611103C4280E3C43FD3E5DD78B5CCF337E7D11CE051E7CE60EF989139DD020`.
- `bridge-usfm-checker.exe`: 7,673,012 bytes, SHA-256
  `D3A103E8CF51CA5A60FCFE9929277989BBAC083B05569452DB5ED4C418164B37`.
- Installer: 30,665,068 bytes, ProductVersion `0.8.0-beta.3`, SHA-256
  `DF27F012ADDC630E04DDDF919F3A38D4ED5982011F34665D51E7ADE8886C4205`.
- The enhanced frozen-worker smoke passed against the exact release-staged workers,
  including Project Registry and exact-duplicate classification. The app, workers,
  and installer are `NotSigned`; installed GUI and native OS drag-and-drop acceptance
  remain manual release gates.

## Beta 2 artifact provenance — 2026-08-25

- Release source: `a7a0747` (`chore(release): bump Bridge to 0.8.0-beta.2`).
- Desktop executable: ProductVersion `0.8.0-beta.2`, SHA-256
  `16C0DB7D96BC3B003C323E58FD850AD02BE2761DA7DDD42FF26197F3F688D092`.
- `bridge-engine.exe`: 21,031,375 bytes, SHA-256
  `5DD3B2962192AF65E3BC32FCE274018CB0AA9CA6FEA566AF26F550243261D2C6`.
- `bridge-usfm-checker.exe`: 7,673,124 bytes, SHA-256
  `C8EB228675EA875E6827E8B92F728D7CE1F72452CE6E40DDBDCB45402CCA8E5E`.
- Installer: 30,644,707 bytes, ProductVersion `0.8.0-beta.2`, SHA-256
  `9CC512F8F3BAA18B4CB93A61FA8CB51651038A8D1DEC788D07043700EDBABB03`.
- The enhanced frozen-worker smoke test passed against the exact release-staged
  workers. Installing and clicking through this newly produced Beta 2 NSIS artifact
  remains a manual acceptance step; the 2026-08-21 acceptance below was Beta 1.

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
