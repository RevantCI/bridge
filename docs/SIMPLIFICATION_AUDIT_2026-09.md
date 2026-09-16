# Simplification audit — September 2026

*Read against commit `83221fd` on 2026-09-16. Method: three read-only sweeps (frontend
surfaces, engine and storage, complexity and slowness signals), each claim then re-checked
with `grep`/`wc` against the working tree, plus an independent second ranking. Every item
cites a file and line so it can be re-verified before acting on it. Numbers are lines of
code unless stated. Nothing here was changed in the audit itself; each item is meant to
become one Idea issue.*

**Decisions already taken by the maintainer (2026-09-16):** rank by both developer velocity
and runtime speed; **drop the Stage 3 semantic-mapping stack and the AI alignment-proposal
path** (#23 closed as not planned); **keep triage** and fix #94 instead; **keep Logos** (B5,
it is required); **hold B7** (the Semantic and Passage tabs) until the cross-verse alignment
page is built and accepted, since that work supersedes those views; **fold the report entry
points** (B4); replace the old `ARCHITECTURE.md` with a current-state map (done in the same
commit as this file).

**Issues filed from this audit (2026-09-16):** A1 #101 · A2 #102 · A3 #103 · A4 #104 ·
A5 #105 · A6 is #93 (pre-existing) · A7 #106 · A8 #107 · B4 #108 · B1+B2 #109.
Not filed: B5 (keep), B6, B7 (held), B8, B9, and the §4/§5 fixes.

## 1. What is slowing every feature down

| Cause | Evidence | Effect |
|---|---|---|
| Every RPC is defined four times | 148 `Methods` constants (`bridge_service.py:285-460`), 140 Rust commands (`commands.rs`), 140 TS methods (`bridgeClient.ts`), types in `finding.ts` (884) and `passageSemanticV1.ts` (860) | Four edits and a Rust rebuild per method. 50 wired methods have no UI caller; 13 engine methods have no Rust command; `passage_semantic_wire.rs` (1491) is referenced only by `mod` in `main.rs:5` |
| One dispatcher, one project object | `bridge_service.py` 4545, `BridgeEngine` 184 methods, `handle_request` is a 668-line if-chain (`:3878-4545`); `tc_project.py` 2980 | 38 of 72 engine test files import `bridge_service`, so nothing can be selected or tested by module (#74) |
| Two parallel semantic systems | Stage 3 (about 2.3k LOC, a 119 MB bundled SQLite, 2 workbench tables) beside the deterministic Stages 4 to 8 (49 tables) | Two vocabularies, two stores; 70% of the 170 MB resource bundle is Stage 3 |
| Five copies of one job runner | `check_jobs.py`, `ai_review_jobs.py`, `triage_jobs.py`, `report_jobs.py`, `project_sweep.py` share an identical `_Job` / `Manager` / error-triple skeleton; `analysis_jobs.py` (724) is the legitimate outlier because it persists runs to the semantic DB | Five polling loops in `App.svelte`, five cancel paths |
| Three AI verdict layers and two review vocabularies | triage (`triage.py:1-7`, "an overlay, never a gate"), `ai.review` (tN/tW), Stage 9A dispositions; "Accept finding" and "Accept translation" mean opposite things (`VerseList.svelte:45-48`) | Every finding-related change is reasoned about three times |
| Test suite cost | 925 tests; 11 min best, 62 min serial worst; about 2,700 of 3,700 test-seconds is fixture setup (#82); `-n auto` is 1.55x *slower* on the CI runner (BUILD_LOG 2026-09-13) | The `main` gate is slow enough to encourage batching commits |
| Documentation volume | `docs/` 20.8k lines; `BUILD_LOG.md` 8.2k and `HANDOFF.md` 4.1k overlap; six point-in-time review docs (1,776 lines) sit on the reading path; CLAUDE.md sends a newcomer to seven docs and then says to distrust them | No single current-state map existed until this audit |

## 2. What is slowing the app down (measured)

1. **Project open builds the semantic runtime eagerly and synchronously.** `open_project`
   (`bridge_service.py:593-723`) constructs `PassageSemanticRuntime` before returning. After
   the #99 fixes (`7b8ec3a`, `83221fd`) a first open of Genesis from source is about 1 s and a
   lazy sibling's first open about 4 s (BUILD_LOG 2026-09-16 table); before them it was
   minutes, and the live installed app ran about 2x slower than the bench. `project.open` is
   still absent from the sidecar timeout table (`sidecar.rs:121-177`), so it gets the 30 s
   default. `_PhaseTimer` and `init_timing_summary()` already exist to measure each phase.
2. **Head-of-line blocking on the single-threaded dispatcher.** `build_project_report`'s
   docstring (`bridge_service.py:989-1000`) records a slow handler queuing an unrelated
   `project.open` into a client timeout. Sharing that line: the navigation poll every 800 ms
   for the app's lifetime (`App.svelte:243`, guarded only by in-flight and engine-ready at
   `:193-194`, not by "a connection is enabled"), `triage.results` opening every sibling's
   workbench read-only (#94, 25 ms to about 1 s), and `report.get`.
3. **Connection per repository call with `synchronous=FULL`.** Tests mask this
   (`engine/tests/conftest.py:79-97` sets `synchronous=OFF`); production does not.
4. **Entering a chapter auto-starts a check job** (`App.svelte:790-792`), which on a fresh
   book spawns the USFM checker subprocess (120 s hard timeout).

## 3. Ranked candidates

### Group A: dead or one-off, safe to remove without a product decision

| # | Item | Evidence | Capability lost | Removes | Effort |
|---|---|---|---|---|---|
| A1 | Extend #100 to `semantic_corpus_discovery.py` (403, zero non-test importers, one of the 12 slow test files at about 70 s) and `scripts/generate_irvtam_mapping_candidates.py` | `conftest.py:40-65`; import grep | none (the 40-verse IRVTam review is finished: 38 confirmed, 1 corrected, 1 rejected) | about 1.2k LOC, one slow test file | S |
| A2 | 13 engine methods with no Rust command: `project.sweepStart/Status/Cancel` (plus all of `project_sweep.py`, 170), `semanticMapping.getForVerse/confirm/rerunForVerse`, `versification.detect/orgRef/backVersificationMap`, `alignment.corpusStats.summary/forVerse`, `verse.evidence`. **The modules stay**: `alignment_statistics` (imported `bridge_service.py:91`, backs the live `alignment.inconsistent_rendering` finding), `versification` (`passage_semantic_runtime.py:50`), `verse_evidence` (`bridge_service.py:103`) are load-bearing; only their RPC wrappers are dead | `bridge_service.py:1086-1099, 2287-2306, 3738-3778, 3790-3829, 1401` | none reachable | about 400 LOC of handlers and dispatcher branches plus `project_sweep.py`; tests in `tests/service/test_bridge_service.py` and `tests/service/test_verse_evidence.py` follow | S |
| A3 | The Rust and TS layers of the 50 UI-dead methods: 38 of the 39 Stage 5 to 8 direct-access commands (`commands.rs:955-1882`, `bridgeClient.ts:511-942`; keep `semanticLocationGetRange`, used by `PassageAlignmentMode.svelte:58`), `semanticReviewDecideLocation/Meaning`, `reviewHistoryGetEntityHistory`, `analysisJobGetRecent`, `aiExplainVerse`, `saveAlignment`, `completeAlignment`, `alignmentBackups`, `logosGetState/SetReference`, `paratextSetReference`, `triageClear`, `scanProject`, `projectCollectionReport`. **Engine handlers stay for now**: they are the test harness for Stages 5 to 8 (`tests/semantic/*`, `tests/review/test_qa_review_service_stage9a.py` drive `handle_request` by method string) until #74/#82 re-point those tests at services. Also `passage_semantic_wire.rs` (1491): check whether `schemas/bridge-passage-semantic-v1.schema.json` is exercised only by its tests, and update CLAUDE.md's `cargo test` note | frontend sweep §6; engine sweep §1b | none in the UI | about 1.35k LOC of Rust and TS, plus 1.5k of dead Rust types | M |
| A4 | Engine modules with no importer outside tests: `semantic_location_benchmark.py` 205, `qa_benchmark.py` 157, `paratext_api.py` 117, `text_graphemes.py` 81, `identity.py` 51. Benchmarks can move under `scripts/` if still wanted | import grep over `engine/` excluding `tests/` and `vendor/` | none | about 600 LOC | S |
| A5 | The `ai.explain` path: `explain_verse` (`bridge_service.py:1952`) is a thinner duplicate of the live `ai.review` job, has no UI caller, and its test file (`tests/ai/test_ai_explain.py`) costs about 203 s of suite time (#82) | grep `src/` for `aiExplainVerse` | none in the UI | about 150 LOC and 203 s of tests | S |
| A6 | #93's 58 defined-but-unreferenced names, two of which are behaviour bugs: `record_terminology_rule` has no caller so `ai_client.py:611` always feeds an empty rule list while `:677` tells the model rules outrank it; `TeamWorkflow` never writes `team.json`, so every report's team section is a constant | #93 | none; removes two false claims | unknown until done | M |
| A7 | Dead `showSource` store (`stores.ts:85`, read at `VerseList.svelte:380`, never set) and the #100 leftovers at `App.svelte:902-913` | grep | none | under 50 LOC | S |
| A8 | Docs: move the six point-in-time review docs (`V11-000a_REVIEW_FIX_PROMPT`, `V11-000_STAGE6B_ALIGNMENT_SPIKE`, `V11-003_ISSUE57_PROMPT`, `V1_1_UNICODE_ACCEPTANCE`, `V1_1_ACCEPTANCE_01`, `STAGE_9B4_ACCEPTANCE`) to `docs/archive/`; fold `CLAUDE.md:267`'s "note in HANDOFF.md" obligation into BUILD_LOG and archive `HANDOFF.md` (4,133 lines, duplicating BUILD_LOG) | doc line counts | none | about 5.9k lines off the reading path | S |

### Group B: decided, or needing one product decision

| # | Item | Decision and evidence | Capability lost | Removes | Effort |
|---|---|---|---|---|---|
| B1 | **Stage 3 semantic-mapping stack**: `semantic_mapping.py` 867, `semantic_mapping_bridge.py` 319, `semantic_mapping_service.py` 69, `semantic_review_policy.py` 164, `semantic_validation_service.py` 333, `semantic_alignment_guard.py` 124; the 119 MB `engine/resources/semantic_mapping/bridge_semantic_source_v0.3.sqlite` shipped via `tauri.conf.json` `bundle.resources`; workbench tables `semantic_mappings` and `semantic_validation_runs` (`workbench_repository.py:227,241`); the `stage3db` marker; two `_PRE_CUTOVER_STORE_DIRS` entries | **Decided: remove.** Honest loss: `ai_client.py:592-617` feeds Stage 3 mappings into the tN/tW AI-review prompt and `:818` applies `apply_semantic_review_policy_all` as a gate on which checks the model may mark. AI review loses passage-level source context and that gate | AI-review prompt context and policy gate | about 2.3k LOC, about 70% of the installer, 2 tables, 3 test files | M |
| B2 | **AI alignment proposals**: `alignment.aiPropose` / `alignment.aiApplyProposal` (`bridge_service.py:1919`), `alignment_reliability.py` 428, `propose_alignment` in `ai_client.py`, their sidecar timeout entries | **Decided: remove.** No UI caller. Close #23 with a note. Do B1 and B2 in one issue: the guard is the seam between them | the auto-align direction | about 600 LOC, 2 methods | S |
| B3 | **Triage** (`triage.py` 620, `triage_prompts.py` 220, `triage_jobs.py` 242, report-screen overlay, `triage_verdicts` table) | **Decided: keep.** Fix #94 with a collection-level cache, the way `listBookProgress` reads `project_progress_cache` | none | none | S to M |
| B4 | Four collection-report entry points: live `project.report` (dashboard) and `report.*` (report screen); dead `project.collectionReport` and `project.sweep*`. `reporting.py` (203) is the sole importer of `analytics.py`, `psalms_qa.py`, `git_service.py`, `team.py`. Preserve the no-cache-warming rule in `build_project_report`'s docstring (`bridge_service.py:989-1000`) | **Decided: fold** (#108) | none if the dashboard exception queue is re-derived from the report builder | about 600 LOC | M |
| B5 | **Logos**: `logos_connector.py` 281 plus its PowerShell helper; reachable through `navigation.*` and the Settings toggle (`SettingsModal.svelte:228`); only the two direct `logos.*` commands are dead (they go with A3, #103) | **Decided: keep.** Logos sync is required | none | none | — |
| B6 | **Navigation poll**: run `pollNavigation` only while a connection is enabled, or push from the engine's probe thread as a Tauri event | verified `App.svelte:193-194, 243` | none | about 75 sidecar round-trips per minute | S |
| B7 | **Alignment Review Semantic and Passage tabs** (`SemanticAlignmentMode` 298, `PassageAlignmentMode` 258, `VirtualPassageStream` 205): read-only re-presentations of the finding that QA mode already shows through `EvidenceInspector` | **Held** until the cross-verse alignment page is built and accepted; that page supersedes these views, so decide then | two alternative views of the same relationship | about 760 LOC of UI, 2 client methods | M |
| B8 | **Five job-runner copies into one generic manager**, keeping `analysis_jobs.py` separate (#12) | engineering, low product risk; preserve each kind's one-at-a-time conflict rule | none | about 900 LOC net | M |
| B9 | **Team and roles scaffolding** ahead of #45/#46: `team.py`, `team_members` and `team_assignments` tables, `security.py`, `session.py` | depends on whether #44 to #47 stay on the roadmap | none today | small | S |

### Group C: large but load-bearing, keep

- **Stages 4 to 8 and their storage**: `passage_semantic_repository.py` 5070,
  `passage_semantic_runtime.py` 1364, `passage_semantic_models.py` 1171, `semantic_location.py`
  853, `qa_audit.py` 822, `source_semantic_inventory.py` 779, `meaning_analysis.py` 560,
  `target_semantic_inventory.py` 392. This is the product's semantic QA. Simplify by making
  the runtime lazy on open (§4), not by removal.
- **Stage 9B correction** (`correction_*`, about 3.1k) and `CorrectionReviewPanel.svelte`
  (1259): the only authorized Scripture writer and an append-only ledger.
- **Token lineage, the three schema ladders, `tc_project.py`, `workbench_repository.py`,
  `workspace_repository.py`, `transaction_journal.py`**: the compatibility and durability
  layer. Split later if at all; do not remove.
- **`versification.py`, `knowledge_base.py`, `plugins.py`, `local_checks.py`,
  `alignment_statistics.py`, `verse_evidence.py`**: imported by live paths even where their
  RPC wrappers are dead (A2).
- **Greek Room adapters and both vendored trees**; **Paratext** (`paratext_connector.py`,
  `paratext_notes.py`, the C# plugin, and the issue-resolution handoff in
  `TranslationHelpsReview.svelte:136,172,195`); `passageSemanticV1.ts` (seven live importers).
- **The two review queues.** ReviewPanel and Alignment Review's QA mode are two data sources
  with two ledgers, not a duplicated UI. The vocabulary clash is a UX fix, not a removal. The
  "two AI-review entry points" are one job surfaced twice (cosmetic), and the "three
  correction routes" are one function (`correctionApplication.ts:57`) called from two places.
- **The if-chain dispatcher.** Do not spend a PR converting it to a dict; it loses about 60
  branches through A2, A3, A5, B1 and B2.
- **#91's five USFM parsers**: a real correctness problem, but a replacement is large and
  touches import, alignment, Stage 6A and finding offsets. Deferred, not a removal.

## 4. Runtime fixes that are not removals

1. **Lazy `PassageSemanticRuntime` on open.** Return project info after `TranslationCoreProject`
   loads; build the runtime on a worker. The `passageSemantic` status already models
   `UNAVAILABLE` to `READY` (`bridge_service.py:670-706`) and the UI polls it. Add
   `project.open` to the timeout table meanwhile. Read the existing `[trace] project.open`
   phase output first: after #99 the remaining cost may already be acceptable.
2. **Unblock the dispatcher line.** Gate the navigation poll (B6); cache `triage.results`
   (#94); reuse connections with `synchronous=NORMAL` under WAL instead of a fresh
   `synchronous=FULL` connection per call.
3. **Make the auto-check on chapter entry explicit or book-scoped.** A product call.

## 5. Developer-velocity fixes that are not removals

1. **#82**: build the Stage 5 to 8 fixture once per module. The single biggest test-time win.
2. **Collapse the RPC layers.** One generic `engine_call(method, params)` Tauri command plus a
   typed TS method map. `commands.rs` goes from 2117 to about 100 lines; adding a method
   becomes an engine handler plus one TS line; `passage_semantic_wire.rs` becomes unnecessary.
3. **#74 step 4**: fewer `bridge_service` importers in tests, which A3's "handlers are the
   harness" note depends on.

## 6. Suggested order, one issue each

1. #100, then #101 (A1).
2. #109 (B1 and B2 together; Stage 3 and the AI-alignment path share `semantic_alignment_guard`).
3. #102 (A2) and #105 (A5).
4. #103 (A3, including `passage_semantic_wire.rs`).
5. #107 (A8, docs archive) and #106 (A7).
6. B6 (navigation poll, not yet filed).
7. #94.
8. §4.1 lazy runtime, after reading the traces.
9. #82.
10. B8, #108 (B4), #104 (A4), then #93 (A6).

## 7. Draft issue bodies for Group A (Idea template)

### A1 — Remove `semantic_corpus_discovery.py` and the IRVTam candidate generator with #100

**What goes wrong today?** `engine/tc_ai_bridge/semantic_corpus_discovery.py` (403 lines) is the
generator side of the finished IRVTam validation workflow that #100 removes. Nothing outside
`engine/tests/semantic/test_semantic_corpus_discovery.py` imports it, and that test is one of the
twelve `_SLOW_FILES` in `engine/tests/conftest.py` at about 70 s. `scripts/generate_irvtam_mapping_candidates.py`
exists only to feed it.
**Proposal.** Delete the module, its test file and its `_FILE_MARKERS` / `_SLOW_FILES` entries,
and the script, in the same PR as #100 or immediately after.
**Verified.** Import grep over `engine/` excluding `tests/` and `vendor/` returns no importer.

### A2 — Remove the 13 engine methods that have no Tauri command

**What goes wrong today?** `bridge_service.py` dispatches 13 methods that no Rust command can
reach: `project.sweepStart/Status/Cancel`, `semanticMapping.getForVerse/confirm/rerunForVerse`,
`versification.detect/orgRef/backVersificationMap`, `alignment.corpusStats.summary/forVerse`,
`verse.evidence`. They are dead protocol carried through every build.
**Proposal.** Delete the `Methods` constants, handlers and dispatcher branches; delete
`engine/project_sweep.py` (170 lines, only the sweep methods use it); adjust
`tests/service/test_bridge_service.py` and `tests/service/test_verse_evidence.py`.
**Keep** `alignment_statistics.py`, `versification.py` and `verse_evidence.py`: each is imported
by a live path (`bridge_service.py:91,103`, `passage_semantic_runtime.py:50`).

### A3 — Remove the Rust and TypeScript layers of the 50 methods no component calls

**What goes wrong today?** 50 of the 140 `bridge.*` client methods have no caller in `src/`
(38 of the 39 Stage 5 to 8 direct-access methods, `semanticReviewDecide*`,
`reviewHistoryGetEntityHistory`, `analysisJobGetRecent`, `aiExplainVerse`, `saveAlignment`,
`completeAlignment`, `alignmentBackups`, `logos*`, `paratextSetReference`, `triageClear`,
`scanProject`, `projectCollectionReport`), and each has a matching `#[tauri::command]`.
`passage_semantic_wire.rs` (1491 lines) is referenced only by `mod` in `main.rs`.
**Proposal.** Delete the TS methods, their Rust commands and registrations, the unused types,
and `passage_semantic_wire.rs` (after confirming the JSON schema is not exercised elsewhere).
Keep `semanticLocationGetRange` and `targetSemanticGetRange`. Leave the engine handlers
in place for now: the Stage 5 to 8 tests drive them by method string.
**Gates.** `npm run check`, `npm run test`, `npm run build`, `cargo check`, `cargo test`;
update CLAUDE.md's `cargo test` count.

### A4 — Delete five engine modules with no importer

`semantic_location_benchmark.py` (205), `qa_benchmark.py` (157), `paratext_api.py` (117),
`text_graphemes.py` (81), `identity.py` (51). Move the two benchmarks under `scripts/` if
anyone still runs them; delete the rest with their tests.

### A5 — Remove the `ai.explain` path

`explain_verse` (`bridge_service.py:1952`) is a thinner duplicate of `ai.review`, has no UI
caller, and `tests/ai/test_ai_explain.py` costs about 203 s of suite time. Delete the method,
its Rust command and TS method, its sidecar timeout entry, and the test file.

### A7 — Remove the dead `showSource` store and the #100 leftovers

`stores.ts:85` is never written; `VerseList.svelte:380` toggles a class on it that can never
change. Remove both with the `allowManualOverride` gating and `"validation"` screen literal
at `App.svelte:902-913` once #100 lands.

### A8 — Archive point-in-time docs and fold HANDOFF into BUILD_LOG

Move the six review docs listed in A8 to `docs/archive/` with a one-line index; change
`CLAUDE.md:267` to route schema notes to `BUILD_LOG.md`; archive `HANDOFF.md`. Fix the
inbound links from `BUILD_LOG.md`, `QA_TEST_MATRIX.md` and the release notes.

## 8. Re-verification footer

Spot-check before acting on any row (all true at `83221fd`):

```
grep -n "WORKBENCH_SCHEMA_VERSION = " engine/tc_ai_bridge/workbench_repository.py     # 2
grep -n "DATABASE_SCHEMA_VERSION = "  engine/tc_ai_bridge/passage_semantic_repository.py  # 16
grep -c "#\[tauri::command\]" src-tauri/src/commands.rs                               # 140
grep -rn "passage_semantic_wire" src-tauri/src | grep -v passage_semantic_wire.rs      # main.rs:5 only
grep -rln "semantic_corpus_discovery" engine --include=*.py | grep -v /tests/          # none
grep -rn "aiExplainVerse\|aiProposeAlignment" src --include=*.svelte --include=*.ts | grep -v bridgeClient  # none
grep -n "setInterval" src/App.svelte                                                    # :243, 800 ms
```
