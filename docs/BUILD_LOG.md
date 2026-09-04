# Build log: Bridge v0.8.0-beta.14

Updated: 2026-09-04

> **Start with [`DEVELOPER_GUIDE.md`](DEVELOPER_GUIDE.md) instead** for an
> oriented, up-to-date summary of the stack decisions, phase roadmap, and
> dependencies. Come here for the full investigation behind a specific
> decision or gotcha — exact root causes, file:line references, and the
> session-by-session narrative that the summary distills. This file is the
> continuously-updated detailed record; `DEVELOPER_GUIDE.md` is what to read
> first to get oriented.

## Stage 9A.4 follow-up - QA queue follows the active canonical scope (2026-09-04)

Installed acceptance showed that analysis correctly ran a newly selected
range, but `AlignmentQaMode` then refreshed `qaReview.getQueue` without that
range. The backend therefore returned every persisted project finding: after
PHP 1:3-1:6 followed by PHP 1:1, both scopes appeared together.

Schema v10 adds `qa_finding_scope_references`, populated from each finding's
source and target semantic units and backfilled during migration. Queue
filtering now occurs in SQLite before total count, ordering and keyset
pagination. `SOURCE_COVERAGE` follows canonical source-unit ownership;
`TARGET_SUPPORT` follows canonical target-unit ownership. This keeps a Greek
PHP 1:3 relationship in the selected source scope even when Tamil realizes it
in 1:6, without filtering only by the displayed target verse. Existing rows,
human dispositions, notes and append-only history are never deleted.

The complete wire path now carries `canonicalReferences` through Svelte,
TypeScript, Tauri/Rust, the Python protocol/service and the repository. Scope
input changes clear the previous queue immediately; late responses are
generation-gated; the persisted completed job is authoritative for an
affected-only run. The UI identifies the default as **Review scope: Current
analysis range**.

Verification: 42 focused queue/migration tests, 101 repository/runtime/review
tests, 126 frontend tests, 5 Rust tests, and the complete 599-test Python suite
pass. Svelte/TypeScript reports 0 errors and 0 warnings; Cargo check, the
production frontend build, frozen-sidecar rebuild, Tauri release build and
NSIS packaging pass. The exact installer was installed successfully, and a
disposable installed-sidecar acceptance verified 26 persisted findings split
13/13 between PHP 1:1 and PHP 1:3-1:6, restored a reviewed decision/note after
switching back, retained a real cross-verse 1:3-to-1:6 association, and
reported scoped pagination/counts accurately.

Separate blocker: the repository-wide frozen smoke reaches project import but
currently expects `exactDuplicate` where the engine returns
`possibleDuplicate`. No duplicate-import code was changed in this scoped fix.
Stage 9B remains unstarted.

## Stage 9A.4 — Analysis orchestration and queue population (2026-09-03)

The previously recorded empty-queue product gap is resolved. Alignment
Review QA mode now has an explicit **Run analysis** control for current
passage, chapter, book, or selected range. It runs the frozen Stage 5, 6A,
6B, 7 and 8 engines in dependency order on a background worker, polls a
durable job snapshot, shows stage-based progress, supports cooperative
cancellation, and refreshes the indexed QA queue when Stage 8 completes.
Opening a project or the review surface only reads analysis state; it never
starts analysis automatically.

Schema v9 adds `analysis_jobs`, CAS revisions, recovery of abandoned workers,
and a partial unique index enforcing one queued/running job per project even
across manager instances. Jobs record scope and fingerprints, reused and
created run ids, provider capability, warnings/failures, per-stage timings,
and Stage 8's source-coverage/target-support/synthesis/persistence profile.
Content-addressed Stage 5–8 caches remain authoritative and unchanged.

After a target edit, Bridge compares current per-reference hashes, expands
changed verses to the smallest available structural passage, and offers
**Re-run affected analysis**. A smaller refreshed run composes with still-
current cached results so its parent chapter/book scope does not remain
incorrectly stale. Interrupted or failed jobs never appear current.

The UI distinguishes `NOT_ANALYZED`, `PARTIALLY_ANALYZED`, `STALE`, `RUNNING`,
`FAILED`, `SEARCH_INCOMPLETE`, and current-with-no-findings. Incomplete Stage
6B search remains `SEARCH_INCOMPLETE`; Stage 8's existing gate still prevents
an unresolved search from becoming an omission finding.

Normal runtime never uses fixture vectors. `SemanticEmbeddingProvider`
descriptors now say whether a provider is fixture-only, normal orchestration
rejects such providers, and the PHP seeder opts in explicitly while itself
running through the same orchestration path. With no production multilingual
embedding provider, analysis remains available but visibly reports limited
semantic retrieval; persisted findings remain reviewable.

Verification: 17 Stage 9A.4 Python tests, 11 PHP walkthrough tests, 104
frontend tests, 5 Rust tests, and the complete 577-test Python suite pass.
Svelte/TypeScript has 0 errors and 0 warnings; the production frontend build
passes. Analysis leaves editable Scripture JSON, preserved imported USFM, and
native translationCore alignment data unchanged.

Still deferred: whole-Bible orchestration, Stage 8 write batching (it remains
persistence-bound), a production multilingual embedding provider, Stage 9B
correction generation/application, and installed-app manual acceptance.

## Stage 9A.3 — PHP 1:3-6 review fixture, and a Stage 8 read-only bug (2026-09-02)

Closes Stage 9A: a seeded fixture project a human can actually open, the
Philippians walkthrough asserted end to end, and one real defect found by
running it.

### The bug: a QA audit made its own project read-only

`scripts/seed_review_fixture.py` seeded a project fine, but *reopening* it
threw `attempt to write a readonly database` from
`bind_project_metadata` — during `PassageSemanticRuntime.__init__`, so the
project could not be opened at all.

Cause: `FoundationRepository.__init__` runs `recovery_check()`, which sets
`self.read_only = True` if it finds any integrity problem. Its
`known_record_tables` map did not contain `QA_RUN`, but Stage 8's
`save_qa_audit_run` registers `QA_RUN` dependency edges. So every dependency
edge Stage 8 wrote was reported as `unknown-record-dependency-type`, the
database flipped to read-only on the next open, and the next write failed.

**Any project that had run a QA audit was unusable from its second open
onward.** Introduced by Stage 8 (`807353d`) and invisible until something
opened a companion database twice — which nothing in the test suite did,
because tests build a fresh project per test. This is exactly the
second-call class of bug the vendored-tool notes warn about, in Bridge's own
code this time.

Fix: `QA_RUN` (and `LOCATION_RELATIONSHIP`, for symmetry with the stale-
propagation map) added to `known_record_tables`, with a comment tying the
two maps together. Regressions added: one asserting a QA_RUN edge is
recognised, one parametrized over every dependency type the engine writes,
and one confirming a genuinely unknown type is *still* reported — the check
had to keep working, not just stop complaining.

### The fixture project

`scripts/seed_review_fixture.py` builds a real translationCore-compatible
IRV Tamil Philippians project and runs Stages 5-8 over it with a fixture
embedding provider, leaving the results in the project's own companion
database.

This is what makes the review UI exercisable in the desktop app at all. The
shipped app has no embedding provider (`available = False`), so it cannot
produce the reordered-passage analysis itself — but the review surface only
ever *reads* persisted findings, so a pre-seeded project works. The location
run fingerprint includes the embedding descriptor, so the app will not
mistake a seeded run for one of its own.

Generated rather than committed, matching the repository's practice of not
committing companion databases. Seeded output: 28 relationships, 12
cross-verse, `reordered: True`, 12 findings in the review queue.

### The walkthrough

`engine/tests/test_php_review_walkthrough_stage9a.py` drives the review APIs
over the reordered passage — Greek 1:3 to Tamil 1:6, 1:4 to 1:4, 1:5 to 1:3,
1:6 to 1:5 — and imports the seeder, so what a human opens is what the tests
assert on.

The load-bearing assertion is
`test_no_omission_is_raised_merely_because_a_verse_moved`: every
POSSIBLE_OMISSION must correspond to a source unit with no located
realization anywhere, never to one simply found in a different verse. A
reordered translation must not read as a missing one. The rest cover
cross-verse relationships being visible and marked LOCATED rather than as a
failure to locate, location and meaning being reported from separate records
with neither field leaking into the other, every finding exposing its
evidence layers, a reviewer accepting, rejecting and deferring with the
reason landing in structured history, a stale revision being refused, and —
directly — that reviewing the passage leaves both `php/1.json` and
`php.usfm` byte-identical.

### Stop condition

A human can open Alignment Review, choose QA mode, select a possible issue,
see the source evidence, the Stage 6B location, the Stage 7 meaning
assessment, the Stage 8 coverage/support reasoning, the applicable resource
evidence, the alternatives and the history, decide, and move to the next
issue — without modifying Scripture. No correction generation exists, and no
export path changed.

**Not verified here:** the final click-through in the running desktop app.
That needs the Tauri build plus both sidecars, and jsdom cannot check real
1366x768 layout. The structure is asserted and the engine paths are covered;
the pixels are not.

## Stage 9A.2 — Alignment Review UI: shell, QA mode, evidence inspector (2026-09-02)

The first UI for the Stage 4-8 semantic pipeline. A reviewer can now open
Alignment Review, work the QA queue, inspect a finding's evidence in layers,
and record one of four decisions - without any route to changing Scripture.
Frontend only: no Python or Rust changed in this step, and the backend tree
is byte-identical to the one that passed 532 tests at Stage 9A.1.

Semantic and Passage modes landed in the same pass rather than as
placeholders, since both turned out to need no new backend: the read chain
already existed (a finding's location `runId` to `semanticLocation.getRange`
to `targetSemantic.getRange`). The remaining Stage 9A.3 work is the seeded
fixture project, the PHP 1:3-6 walkthrough, and final verification.

### Vitest

Bridge had no frontend test framework; `svelte-check` plus `npm run build`
were the whole gate. Added Vitest + @testing-library/svelte + jsdom
(`vitest.config.ts`, `npm test`). Playwright was deliberately **not** added:
it roughly doubles the test-infra surface, and Bridge ships offline into a
Tauri shell where a headless-browser harness buys little over asserting on
the DOM these components actually produce. The cost of that choice is
recorded under "what these tests cannot check" below.

### Components

- `AlignmentReview.svelte` - the shell, with Word / Semantic / Passage / QA
  tabs following the WAI-ARIA tabs pattern (one tab stop, arrow keys move,
  each panel labelled by its tab). Opens in QA mode.
- `SemanticAlignmentMode.svelte` - the same focused record presented
  relationship-first: source meaning, target realization, and an assessment
  strip keeping location, meaning and coverage in separate cells. Each
  realization kind (lexical, grammatical, pronominalized, implicit) and each
  property (split, merged, cross-verse) carries a sentence saying what it
  means, described neutrally rather than as a defect.
- `PassageAlignmentMode.svelte` + `VirtualPassageStream.svelte` - the target
  passage as a windowed stream of collapsible verse rows, never one column
  per verse. Connector detail is drawn only for the focused relationship; an
  unfocused linked verse gets a count instead, which is what keeps the view
  from becoming a full-passage spaghetti graph. Relationships are matched to
  verses through their target token ids, since a relationship carries tokens
  rather than references - which is also what makes cross-verse realization
  visible, one relationship's tokens falling in more than one verse.

  When a run had no embedding provider, the mode says so and reports how many
  relationships were found, so sparse linking reads as the capability limit
  it is rather than as an indictment of the translation.
- `AlignmentQaMode.svelte` - queue on the left, evidence and decision on the
  right; filter chips for order, review state and issue type.
- `QaFindingList.svelte` - the queue, windowed above 60 rows so a
  thousand-finding queue puts a few dozen rows in the DOM rather than a
  thousand. Fixed row height so the window is computed from `scrollTop`
  without measuring.
- `QaFindingDetail.svelte` - the four reviewer actions, the note field, and
  the opt-in promotion checkbox.
- `EvidenceInspector.svelte` - FINDING / SOURCE / LOCATION / MEANING /
  COVERAGE / RESOURCES / HISTORY as separate sections.
- `ReviewStatusBadge.svelte` - status pills.
- `reviewStores.ts`, `reviewLabels.ts`, `__tests__/fixtures.ts`.

`AlignmentModal.svelte` is mounted unchanged as Word mode. Nothing converts
Bridge semantic relationships into translationCore alignment groups.

### Where the design decisions actually live

**Wording is centralized in `reviewLabels.ts`** so no component can invent
its own. Everything Stage 8 produces reads as "Possible omission", never
"Error"; the confirmed forms exist only because a reviewer can promote a
finding explicitly. `AI_PROPOSED` renders as **"Machine-proposed"**, not "AI
proposed" - Stages 6B-8 are deterministic and no language model is involved,
so calling it AI would be simply untrue.

**Severity is labelled "… priority"** with a tooltip saying it sets review
order and does not mean the issue is confirmed. Nothing about severity is
styled to look like a verdict.

**Location and meaning are separate sections by construction**, and the
inspector ends with a plain-language "What this means" that names which of
the two the reviewer is looking at: mapping uncertain, mapping probably
right so this is about the translation, or nothing located at all. That is
the mapping-error / translation-error distinction made explicit rather than
left for the reviewer to infer.

**Coverage statuses carry their own justification.** GRAMMATICALLY_REQUIRED
and EXPLICITATION_SUPPORTED render with a sentence explaining why an
apparent extra word may be perfectly correct, so the UI does not nudge
toward treating every addition as a fault. Cross-verse, split and reordered
realizations get the same treatment.

**Alternatives are always shown when the engine retained them**, and say so
explicitly when it retained none, so the UI never implies a single candidate
where several competed.

**STALE is never hidden.** A stale finding carries a badge in the list, a
badge in the header, and a notice at the top of the inspector saying it was
produced against an earlier revision and must be re-evaluated - while its
human decision stays visible in history.

**There is no "Apply correction" anywhere**, and a test asserts its absence
rather than trusting that nobody adds one.

### Concurrency in the UI

`decideFinding` sends the `revision` and `targetContentHashes` the reviewer
actually saw. A `revision_conflict` is never retried: the finding is
reloaded and the reviewer is told it changed since they opened it, so the
decision is made against what it says now.

### Accessibility

Status never depends on colour alone - every badge pairs a Unicode glyph
with its own text, selection is marked by a left rule as well as a fill, and
filter chips use border weight plus `aria-pressed`. Unicode glyphs rather
than an icon font, per the existing gotcha about offline builds not reaching
a CDN. The queue is one tab stop with arrow/Home/End navigation and
`aria-activedescendant`, so reaching row 900 does not mean 900 tab presses.
Meaning components are a real table with row and column headers.

### Small-screen behaviour

The decision controls live in a sticky footer that is a *sibling* of the
scrolling evidence area, not inside it, so long evidence cannot push them
below the fold - the specific failure Bridge's alignment UI had before. The
filter block is capped and scrolls rather than pushing the queue off-screen;
the panes stack below ~900px; Scripture wraps with `overflow-wrap: anywhere`
and a line height that suits Tamil and Hebrew.

### What these tests cannot check

jsdom does not lay out or paint. The viewport tests assert *structure* -
scroll containers exist, the action bar is outside the scrolling region,
long text is not truncated, a 400-row queue windows correctly - not measured
pixels. **Real 1366x768 behaviour still needs a pass in the running desktop
app**, which needs the Tauri build and both sidecars. The tests keep the
structure from regressing between those passes; they do not replace one.

### Entry point

Alignment Review is a new top-level surface (`screen === "review"`) reached
from the editor toolbar, alongside ReviewPanel's existing per-verse alignment
modal rather than replacing it. `resetReviewState()` is called wherever
`resetBookState()` is, so a finding id from one book can never appear under
another - the same class of bug as gotcha 7.

**Tests:** 97 frontend tests across 9 files - evidence layering, possible-vs-
confirmed wording, the four dispositions, promotion gating, note-without-
deciding, revision conflict, queue paging and dedup, virtualization,
keyboard navigation, accessibility, small-viewport structure, realization and
property wording, passage windowing, focused-relationship marking, and
passage search.

**Files:** `vitest.config.ts`, `package.json`, `src/App.svelte`,
`src/lib/components/TopBar.svelte`, `src/lib/reviewStores.ts`,
`src/lib/utils/reviewLabels.ts`, `src/lib/types/qaReview.ts`, and the six new
components plus `src/lib/components/__tests__/`.

## Stage 9A.1 — Stable finding identity and the human review APIs (2026-09-02)

Backend half of Stage 9A. A reviewer can now be given a deterministic queue,
layered evidence, and four decisions to make, with none of it touching
Scripture. No UI yet.

### Finding ids are re-keyed off stable semantic identity

Stage 8 hashed the *run fingerprint* into every finding id
(`_build_finding`), so any upstream change — a target edit, a policy bump —
minted brand-new ids and orphaned every human decision recorded against the
old ones. That made the spec's "a stale human-confirmed issue is preserved
and re-evaluated" unimplementable: after an edit there was no identity left
to preserve it against. This is the same lesson `_stable_finding_id()` in
`bridge_service.py` already encodes for the Greek Room findings (CLAUDE.md
gotcha 3); Stage 8 had not applied it.

`QaAuditEngine._stable_finding_id()` now keys on
kind + direction + coverage dimension + source unit ids + target anchors, and
deliberately excludes the run fingerprint **and** the engine/policy versions —
keying on policy would orphan decisions on every policy bump. Both are still
recorded as fields.

Verified before relying on it, rather than assumed:

- **Source unit ids are stable.** `source-unit-<fingerprint>` hashes
  kind + token ids + rule + policy, and the source resource is locked, so
  they survive target edits by construction.
- **Target unit ids are not.** `target-unit-<fingerprint>` includes
  `targetRevision`, and `PassageSemanticRuntime.text_revision()` is
  per-verse — so editing one verse re-ids every target unit in it. Target
  support findings therefore anchor on
  reference + normalized surface + occurrence instead
  (`_finding_anchors`), which holds an addition finding's identity steady
  when an unrelated word in the same verse changes, and breaks it only when
  the word the finding is actually about changes — at which point it
  genuinely is a different finding.
- **Relationship ids embed the run fingerprint** and are correctly excluded.
- **Coverage account ids** derive from the source inventory fingerprint, so
  they are stable across target edits; the dimension is used rather than the
  id itself.

No golden fixture had to change: there is no Stage 8 golden file, and
`test_qa_audit_stage8.py` never asserts a literal finding id — it derives
`finding["id"]` at runtime everywhere.

### save_qa_finding became an upsert that cannot overwrite a decision

Stable ids mean a re-run now reaches an existing row instead of inserting a
fresh one. `save_qa_finding` merges the machine fields and preserves
`qaDisposition` / `reviewStatus` / `revision` exactly as the reviewer left
them (`_HUMAN_FINDING_FIELDS`). If nothing the machine produced actually
changed it writes nothing at all, so re-runs do not churn revisions. When it
does refresh a finding that already carries a human decision it appends a
SYSTEM ReviewRecord, leaving an audit trail rather than a silent overwrite.

Measured end to end: confirm a finding → edit the target verse → the finding
goes STALE with the decision intact → re-run → same id, back to ACTIVE,
decision still intact, history `[HUMAN, SYSTEM]`. A wording change never
becomes CORRECTED on its own; only a future Stage 9B recheck may conclude
that.

### Review APIs

New `engine/tc_ai_bridge/qa_review.py` (`QaReviewService`), deliberately
separate from the `qaAudit.*` analysis methods so that analysis stays
read-only and every human write leaves a ReviewRecord:

`qaReview.getQueue` · `qaReview.getFinding` · `qaReview.decideFinding` ·
`qaReview.addNote` · `semanticReview.decideLocation` ·
`semanticReview.decideMeaning` · `reviewHistory.getEntityHistory`

- **Disposition → review status is now explicit.** The old derivation folded
  everything decided into HUMAN_APPROVED. FALSE_POSITIVE is the one case
  where the human rejects the machine's claim outright, so it is the only
  disposition yielding HUMAN_REJECTED; ACCEPTABLE_TRANSLATION still approves
  the *observation* and carries its nuance in the disposition.
- **Promotion is opt-in only.** POSSIBLY_MISSING → MISSING and
  POSSIBLY_UNSUPPORTED → UNSUPPORTED happen only via `promote: true`
  alongside CONFIRMED_TRANSLATION_ERROR, and are expressed on the coverage
  account rather than by adding bare OMISSION/ADDITION finding kinds.
  Opening or deciding a finding never promotes.
- **Mapping and meaning are reviewable independently.** Rejecting a Stage 6B
  location marks it HUMAN_REJECTED (or HUMAN_MODIFIED when an alternative
  candidate is chosen) and invalidates dependent Stage 7/8 records without
  rewriting their history; the QA disposition is untouched, because a mapping
  verdict decides nothing about whether the translation is wrong. Overriding
  a Stage 7 meaning assessment works the same way.
- **Notes do not decide.** `append_standalone_note` records a note against
  the entity without touching its review state or bumping its revision.

`record_human_review()` is the single generic write path (CAS + ReviewRecord
+ optional dependent invalidation) for every reviewable entity;
`_REVIEWABLE_TABLES` names them.

### Concurrency

`decideFinding` takes both `expectedEntityRevision` and
`expectedTargetContentHashes`. `FoundationConflict` and
`FoundationValidationError` now have explicit handlers at the protocol
boundary and surface as `revision_conflict` / `semantic_validation_error`
instead of falling through to `internal_error`.

### Found by running it: Stage 7 evidence is not in evidence_records

`qaReview.getFinding` crashed on `Unknown evidence record:
meaning-evidence-…`. Stage 7 synthesizes per-component `meaning-evidence-*`
ids *inside* the assessment payload and never writes them to the
`evidence_records` table, but Stage 8 copies those ids onto the finding's
supporting/conflicting evidence lists. The resolver now reads both stores and
tags each item `EVIDENCE_RECORD` / `MEANING_ASSESSMENT` / `UNRESOLVED` — a
reviewer should see that a piece of evidence is missing, not be blocked from
reviewing the finding at all.

### Command layer

Stage 8 shipped no Tauri commands, so its methods were unreachable from the
UI. Added all seven `qa_audit_*` commands plus the seven review commands to
`commands.rs`, registered in `main.rs`, with matching `bridgeClient.ts`
methods and a new `src/lib/types/qaReview.ts`. Stage 9A.2 is therefore pure
Svelte. (`passage_semantic_wire.rs` holds schema-validation serde types, not
the command layer — no additions needed there.)

**Files:** `engine/tc_ai_bridge/qa_review.py` (new),
`engine/tc_ai_bridge/qa_audit.py`,
`engine/tc_ai_bridge/passage_semantic_repository.py`,
`engine/tc_ai_bridge/passage_semantic_models.py`,
`engine/tc_ai_bridge/passage_semantic_runtime.py`,
`engine/bridge_service.py`, `src-tauri/src/commands.rs`,
`src-tauri/src/main.rs`, `src/lib/api/bridgeClient.ts`,
`src/lib/types/qaReview.ts` (new),
`engine/tests/test_qa_review_service_stage9a.py` (new, 37 tests).

## Stage 9A.0 — Review-queue storage preflight (2026-09-02)

Preflight for Stage 9A (human QA review). No review API and no UI yet; this
step only makes storage able to answer review-queue questions and measures
where Stage 8 actually spends its time.

**Regression baseline before any change** — 478 Python tests passed (7m49s),
`svelte-check` 0/0, `npm run build` OK (801.59 kB bundle, already past Vite's
500 kB warn threshold), `cargo check` clean.

**Schema v8** (`_MIGRATION_V8`, `passage_semantic_repository.py`). Stage 8
stored everything about a finding inside `qa_findings.payload_json`; the table
itself had no `book`, `kind`, `severity` or reference columns. A review queue
that orders by canonical position or severity and filters by type/state could
only have been built by scanning and re-parsing every payload. v8 lifts those
values into real columns (`book`, `kind`, `direction`, `severity`,
`severity_rank`, `sort_chapter`, `sort_verse`, `displayed_reference`) with
three supporting indexes, backfilling existing rows from the payload via
`json_extract`. `severity_rank` exists because `QaFindingSeverity` does not
sort lexicographically — CRITICAL/HIGH/MEDIUM/LOW/INFO is review priority, not
alphabetical order. Verified against a real v7 database built from the shipped
v1-v7 migration scripts: it upgrades, backfills, and leaves the automatic
`backups/pre-schema-v8-*` snapshot.

`sort_chapter`/`sort_verse`/`displayed_reference` currently backfill empty:
`QaFinding` carries no reference of its own (`_finding_to_dataclass` sets
`passage_id` to the *book*). `_queue_sort_key()` already reads an optional
`displayed_references` attribute, so those columns populate themselves once
Stage 9A.1 adds that field — no repository change needed then.

**`query_qa_findings()`** — keyset (not OFFSET) pagination, so a human
decision made mid-review cannot shift rows across a page boundary. Both
orderings end in the finding id, making order fully deterministic for
equal-priority findings.

**Reviewer notes.** `_append_review()` hardcoded `note=""`, so no write path
could record one — only `import_review_record` accepted a note. The parameter
is now threaded through `update_qa_disposition`. The existing revision-CAS and
`FoundationConflict` behaviour is unchanged.

**Stage 8 profiling** (the gap the Stage 8 report flagged). `PhaseProfiler`
does exclusive accounting — time in a nested phase is subtracted from its
parent, so phases sum to the total instead of double-counting. Persistence is
attributed through `_ProfiledRepository`, a transparent forwarding proxy that
times only `save_*`/`update_*`/`create_*`, so no save call site changed. The
proxy is restored in a `finally`. Results, measured on the PHP Tamil fixture:

| Range | Findings | Elapsed | persistence | sourceCoverageAudit | targetSupportAudit |
|---|---|---|---|---|---|
| PHP 1:3 | 6 | 0.41s | 0.376s (92%) | 0.031s | 0.002s |
| PHP 1:3-1:6 | 29 | 0.96s | 0.782s (81%) | 0.177s | 0.002s |

**Stage 8 is persistence-bound, not analysis-bound** — 81-92% of its runtime
is SQLite writes, because every `save_qa_finding`/`save_coverage_account` call
opens its own connection and commits individually. The audit logic itself is
cheap. Extrapolated to a whole book this is minutes of mostly-commit time.
Batching a run's writes into one transaction is the obvious fix, but it
changes Stage 8 persistence semantics and is deliberately **not** done here.
Not a blocker for review UI work, which reads rather than writes.

Cache hits short-circuit before any audit pass; a cached run reports only
`cachedRetrieval` (~1.3ms).

**Files:** `engine/tc_ai_bridge/passage_semantic_repository.py`,
`engine/tc_ai_bridge/qa_audit.py`,
`engine/tests/test_qa_review_stage9a.py` (new, 17 tests).

### Found while surveying: Stage 8 has no Rust wire and no client methods

Stages 4, 5, 6A, 6B and 7 each shipped their own `src-tauri/src/commands.rs` +
`passage_semantic_wire.rs` + `bridgeClient.ts` additions. Stage 8 shipped
none: its commit touched only `src/lib/types/passageSemanticV1.ts` on the
frontend side. `bridgeClient.ts` has `semanticLocation*` and
`meaningAnalysis*` but no `qaAudit*`, and `passage_semantic_wire.rs` contains
no qa_audit entries. Because each protocol method needs a named
`#[tauri::command]`, Stage 8's methods are currently reachable only over the
raw sidecar protocol, not from the UI. Stage 9A must add that wiring for the
existing `qaAudit.*` methods as well as for its own review APIs.

## Retrospective: Stages 4-7 (added 2026-09-02, reconstructed)

> **Marked retrospective.** These stages shipped without BUILD_LOG entries.
> Reconstructed only from commit contents, the code, and the tests that exist
> today — deliberately limited to what those verify. The investigation
> narrative that the other entries in this file carry was not recorded at the
> time and is not reproduced here rather than guessed at.

Numbering note: these are passage-semantic **Stages**, a different axis from
the Greek Room **Phases** 4-7 documented further down this file (USFM
checker, versification, names, alignment statistics). Both numbering schemes
are in use; they do not correspond.

**Stage 4 — passage runtime and stale invalidation** (`78fdf4b`, 2026-09-01).
Added `passage_semantic_runtime.py` (1,171 lines) as the composition point for
the passage-semantic pipeline, plus a large repository expansion (+734) for
target-revision tracking and dependency-driven staleness — `record_dependencies`
with `_stale_generic_dependencies` walking the dependency graph, and the
`prepare_`/`apply_`/`cancel_target_invalidation` intent flow. First stage to
add Rust wire (`passage_semantic_wire.rs`, +161) and client methods.
Tests: `test_passage_semantic_runtime.py` (547 lines).

**Stage 5 — source semantic inventory** (`82d6664`, 2026-09-01).
`source_semantic_inventory.py` (736 lines): the source-side obligation
inventory, carrying `SemanticObligationStrength`, `CoverageAccountingRole`,
`CoverageDimension` and `AuditEligibility` — the fields Stage 8's coverage
audit later gates on. Golden fixture `stage5-source-golden-v1.json` was added
in the following commit. Tests: `test_source_semantic_inventory_stage5.py`.

**Stage 6A — target semantic inventory** (`de8ce4c`, 2026-09-02).
`target_semantic_inventory.py` (398 lines), built as language-independent —
the target side is inventoried without source knowledge, which is what makes
the later target-support audit a genuinely independent direction rather than a
re-reading of source coverage. Tests:
`test_target_semantic_inventory_stage6a.py`.

**Stage 6B — passage-aware semantic location** (`91e5394`, 2026-09-02).
`semantic_location.py` (809 lines) plus `semantic_location_benchmark.py`.
Locates where source meaning was realized in the target, across verse
boundaries, producing `LocationOutcome` + `Realization` + `RelationshipProperty`
without judging meaning — `test_semantic_location_stage6b.py` asserts
`all("meaningStatus" not in item for item in result["relationships"])`,
enforcing the location/meaning separation at the data level. Golden fixture
`stage6b-location-golden-v1.json` pins the reordered IRV Tamil PHP 1:3-6
mapping (Greek 1:3→Tamil 1:6, 1:4→1:4, 1:5→1:3, 1:6→1:5) and the test asserts
it is discovered without book-specific engine rules. This commit also touched
`versification.py` (+83).

`SemanticEmbeddingProvider` is defined here with `available = False`, and
`PassageSemanticRuntime` constructs `SemanticLocationEngine(self)` with no
provider — so **the shipped app runs without embeddings**; the reordering
fixture passes only because tests inject a `FixtureEmbeddingProvider` with
hand-built paired vectors. Embeddings are candidate retrieval only
(`EmbeddingRole.CANDIDATE_RETRIEVAL_ONLY`), never a meaning judge.

**Stage 7 — meaning preservation** (`0289ae5`, 2026-09-02).
`meaning_analysis.py` (512 lines) plus `meaning_benchmark.py`. Assesses
whether located realizations preserve meaning, producing `MeaningStatus` and
per-dimension `MeaningComponentStatus` so that a component judgement
(e.g. quantity contradicted) stays visible instead of collapsing into one
score. `MeaningAssessmentReason` records why an assessment was *not* made
(`NO_LOCATED_REALIZATION`, `AMBIGUOUS_LOCATION`, `SEARCH_INCOMPLETE`), keeping
"not assessed" distinct from "assessed as fine". Tests:
`test_meaning_analysis_stage7.py` (365 lines).

Stages 5-8 are all deterministic: none of `source_semantic_inventory.py`,
`target_semantic_inventory.py`, `semantic_location.py`, `meaning_analysis.py`
or `qa_audit.py` imports `ai_client` or `model_router`. The `AI_PROPOSED`
review status Stage 8 stamps on findings marks them as machine-proposed rather
than human-decided; it does not indicate a language model was involved.

## Stage 8 — Bidirectional Source Coverage, Target Support, and Translation QA (2026-09-02)

First stage in the passage-semantic pipeline allowed to produce
translation-problem findings. Synthesizes evidence already produced by
Stage 5 (source obligations), Stage 6A (target inventory), Stage 6B
(location), and Stage 7 (meaning preservation) — it never re-runs location
search or re-judges meaning, only reads their frozen, already-persisted
run payloads.

**New module** `engine/tc_ai_bridge/qa_audit.py`: `QaAuditPolicy` (a single
versioned deterministic gate/precedence/severity policy, `qa-policy-v1`)
plus `QaAuditEngine`, mirroring `meaning_analysis.py`'s shape exactly
(fingerprint over upstream fingerprints + engine/policy versions, cache
check via `qa_audit_for_fingerprint`, `run_range`/`status`/`get_range`/
`get_source_coverage`/`get_target_support`/`get_finding`/`get_diagnostics`).

**A real discovery that shrank this stage's scope**: the persistence
foundation for QA was already built in Stage 3 and simply never called —
`FoundationRepository.save_qa_finding(QaFinding)`,
`save_coverage_account(SemanticCoverageAccount)`, and
`update_qa_disposition(...)` (the human-confirmation-boundary transition,
item 22 of the spec) were all fully functional, unused code. Stage 5
already seeds one `SemanticCoverageAccount` per `(auditOwnerUnitId,
coverageDimension)` for every `PRIMARY`-role source unit, with
`findingId=None` placeholders — Stage 8 finalizes those same rows in place
(new `update_coverage_account_status`, optimistic-concurrency, same
pattern as `update_qa_disposition`) rather than inserting duplicates.
Target-side accounting needed no new Stage 6A structure either —
`TargetSemanticUnit` already carries `auditEligibility`/`accountingRole`/
`auditOwnerUnitId`/`coverageDimension` (`target_semantic_inventory.py:183`)
so `PRIMARY`+`ELIGIBLE` units are exactly the reverse-audit candidates.

**Schema**: migration v6→v7 adds one table, `qa_audit_runs` (mirrors
`meaning_analysis_runs` — id/fingerprint/`meaning_run_id` FK/payload_json/
`UNIQUE(project_id,book,range_key,fingerprint)`). `qa_findings` and
`coverage_accounts` needed no column changes (both existed unused since
schema v1); run traceability goes through `record_dependencies` the same
way `MEANING_RUN`/`LOCATION_RUN` already do (`QA_RUN`→`MEANING_RUN`,
`COVERAGE_ACCOUNT`/`QA_FINDING`→`QA_RUN`), so the existing
`_stale_generic_dependencies` BFS cascades edits all the way from a
`SOURCE_RESOURCE`/target-text change down through `QA_FINDING.lifecycleStatus
= STALE` with one new map entry (`"QA_RUN": "qa_audit_runs"`).

**Model changes** (`passage_semantic_models.py`): `QaFindingKind` gained 12
new values (`POSSIBLE_OMISSION`, `POSSIBLE_ADDITION`,
`POSSIBLE_UNDERTRANSLATION`, `POSSIBLE_OVERTRANSLATION`, `MEANING_SHIFT`,
`CONTRADICTION`, `NEGATION_PROBLEM`, `QUANTITY_PROBLEM`, `TEMPORAL_PROBLEM`,
`PARTICIPANT_PROBLEM`, `REFERENT_PROBLEM`, `SOURCE_VARIANT_REVIEW`) —
the original 7 (`POSSIBLY_MISSING`/`MISSING`/etc.) are untouched. New
`QaFindingSeverity` and `QaRunStatus` enums; `EvidenceKind` gained
`SOURCE_VARIANT`. `QaFinding` gained 13 fields the Stage-3 foundation
hadn't anticipated (severity, meaning-assessment/coverage-account id links,
location/meaning snapshots, supporting/conflicting/resource evidence id
lists, target/source hashes, engine/policy versions, fingerprint) — all
required, since every real construction site is new Stage 8 code.
`SemanticCoverageAccount` gained one field, `coverage_status: str =
"NOT_CHECKED"` (a `SourceCoverage` value for `SOURCE_COVERAGE`-direction
accounts, `TargetSupport` for `TARGET_SUPPORT`-direction, validated in
`__post_init__`); the default keeps Stage 5's existing construction site
unmodified. This tripped the existing canonical-schema parity tests
(`test_python_record_fields_match_canonical_schema`,
`test_python_and_typescript_controlled_enums_match_canonical_schema`,
which assert every dataclass field and enum value is mirrored 1:1 in
`schemas/bridge-passage-semantic-v1.schema.json` and
`src/lib/types/passageSemanticV1.ts`) — both were updated to match, plus
one pre-existing foundation test
(`test_passage_evidence_qa_exportability_and_review_round_trip`) that
constructed a bare `QaFinding` and needed the new fields filled in.

**Source coverage gates** (items 5–9 of the spec): `NOT_LOCATED` only
becomes `POSSIBLY_MISSING` when every relationship touching that obligation
resolved to `NOT_LOCATED` (never `AMBIGUOUS`/`SEARCH_INCOMPLETE`/
`UNSUPPORTED_ANALYSIS`, which gate to `UNCERTAIN` instead) and no
documented source-variant evidence explains the absence (checked via the
owner unit's real `evidence_ids` against `EvidenceRecord.kind ==
SOURCE_VARIANT`, falling back to `SOURCE_VARIANT_REVIEW` instead of
`POSSIBLE_OMISSION` when one exists). A `LOCATED` relationship whose Stage 7
assessment is `PRESERVED`/`PRESERVED_WITH_RESTRUCTURING` becomes `COVERED`
or `COVERED_BY_RESTRUCTURING` depending on whether `RelationshipProperty`
is non-empty or realization isn't `LEXICALLY_REALIZED`. `POSSIBLY_MISSING`
is never auto-promoted to `MISSING` — that stays a human-only transition
via `update_qa_disposition`.

**Target support gates** (items 12–17): a target unit with zero
referencing relationship becomes `GRAMMATICALLY_REQUIRED` for a small
controlled function-word list, `EXPLICITATION_SUPPORTED` for licensed
explicitation targets (reusing `DeterministicMeaningComparator
.LICENSED_EXPLICITATIONS`'s target side from Stage 7), `POSSIBLY_UNSUPPORTED`
only for an unmatched specificity marker (reusing `SPECIFICITY_MARKERS`),
else the conservative default `UNCERTAIN` — deliberately not
`POSSIBLY_UNSUPPORTED`, since a v1 deterministic policy can't yet
positively rule out every legitimate grammatical/explicitation reason for
an unmatched word, and false positives are worse than an `UNCERTAIN`.

**Meaning-failure pass** (items 10–11, 24, 27): for every `LOCATED`
relationship whose Stage 7 meaning isn't preserved/unverifiable, a single
component-aware precedence chain picks the finding kind — a `CONTRADICTED`/
`ALTERED` component on `POLARITY`/`QUANTITY`/`TEMPORAL_ASPECTUAL`/
`PARTICIPANT`/`REFERENT` wins over the generic `MEANING_SHIFT`/
`CONTRADICTION`/`POSSIBLE_UNDERTRANSLATION`/`POSSIBLE_OVERTRANSLATION`
fallback from the aggregate status, and a `CONFLICTING` resource-evidence
status on any component overrides everything to `RESOURCE_CONFLICT`. One
finding per relationship, not per component (verified by
`test_deduplication_one_finding_per_relationship`).

**Benchmarks** (`engine/resources/qa_audit/{omission,addition}-benchmark-v1.json`,
15 cases each, `reviewStatus: "MACHINE_PROPOSED"` guarded the same way
`meaning_benchmark.py` guards its own): new `qa_benchmark.py` drives
`QaAuditPolicy.source_coverage_for`/`target_support_for` directly from
synthetic gate inputs (mirroring how `meaning_benchmark.py` drives
`DeterministicMeaningComparator.compare`), plus `false_positive_metrics()`
reporting possible-omission/addition precision/recall, false-omission/
addition rate, legitimate-restructuring false-positive count, and
ambiguity/search-incomplete-to-error leakage separately — not one generic
accuracy number, per the spec's explicit false-positive emphasis. Current
deterministic baseline: 100% accuracy, zero leakage on both TEST splits
(15/15 cases here are the deterministic-policy self-check, not a
human-reviewed calibration claim).

**Philippians 1:3–6**: ran Stage 8 over the existing `REORDERED` Stage 6B
relationships (Greek 1:3→Tamil 1:6, 1:4→1:4, 1:5→1:3, 1:6→1:5). Confirmed
none of the well-covered content lemmas (the 19 `PHP_PAIRS` used since
Stage 6B/7) are falsely flagged `POSSIBLE_OMISSION` despite the cross-verse
reordering, and that at least one of them reaches `COVERED`/
`COVERED_BY_RESTRUCTURING`. Some genuinely-uncovered function
words/particles in the real UGNT text (not in the 19-pair fixture) do
legitimately gate to `POSSIBLY_MISSING` — that's correct behavior given
the fixture's vocabulary coverage, not a false positive, and the test
(`test_php_reordered_passage_produces_no_false_omissions`) asserts against
the covered-lemma set specifically rather than a blanket zero-omissions
claim. Did not implement a QA-specific verdict for the ἐπιτελέσει/நடத்தி
வருவார் completion-vs-continuation case beyond what Stage 7 already scores
(`TARGET_WEAKENS_SPECIFICITY` → `POSSIBLE_UNDERTRANSLATION` via the generic
precedence path) — no dedicated completion/continuation finding kind was
requested by the spec.

**Tests**: `engine/tests/test_qa_audit_stage8.py`, 27 cases — precedence/
severity policy (parametrized over all 5 dimension→kind mappings plus
generic status precedence and resource-conflict override), all→some
quantity problem, genuine absence, ambiguous/search-incomplete blocking
omission, the PHP reordered passage, grammatical function words and
unsupported specificity on the target side, human-confirmation +
edit-staleness preservation, QA-run cache hit, full `qaAudit.*` protocol
round-trip via `BridgeEngine`, Hebrew (Gen 2:5) and Aramaic (Dan 2:4)
reuse, and finding deduplication.

**Not implemented** (explicitly out of scope, per spec): automatic
Scripture correction, `CorrectionProposal` construction (the dataclass/
table are untouched — no finding requires one), final QA UI, Scripture
Burrito export, new translationCore projection behavior. `MISSING`/
`UNSUPPORTED` and their `OMISSION`/`ADDITION` finding equivalents remain
human-only transitions.

**Unresolved risks**: the target-support gate's function-word/explicitation/
specificity-marker lists are small, deliberately controlled fixtures
(mirroring Stage 7's own comparator lists) — real-world coverage across
languages is unvalidated beyond the English/Tamil/Hebrew/Aramaic cases
tested here. `QaFinding.severity` thresholds (0.85/0.9 confidence cutoffs
for `HIGH`→`CRITICAL`) are uncalibrated, same caveat as every confidence
value elsewhere in this pipeline. No dedicated target-support account for
`AGGREGATE`/`EVIDENCE_ONLY`-role target units (`NOT_CHECKED`, consistent
with the source side) — if a future stage needs aggregate-level target QA,
that's unbuilt.

**Verified**: focused suite 27 passed; full Python suite 478 passed (up
from 428 at the end of Stage 6B); `cargo check` clean; `npm run check` 0
errors/0 warnings; `npm run build` succeeds; `git diff --check` clean.
Stage 6B golden locations and Stage 7 golden meaning statuses unchanged
(no test in `test_semantic_location_stage6b.py`/`test_meaning_analysis_stage7.py`
was modified, and both suites still pass unmodified). Existing
translationCore behavior unchanged (no `tc_project.py`/alignment/import
code touched).

**Note for Benz**: verifying this repo against the Stage 5–7 handoff doc
turned up a pre-existing gap this session didn't create or fix — Stages 4
through 7's commits (`78fdf4b`, `82d6664`, `de8ce4c`, `91e5394`, `0289ae5`)
have no corresponding `BUILD_LOG.md` narrative (no reported test counts,
no session notes), unlike every other feature landed in this file.
`DEVELOPER_GUIDE.md`'s phase-roadmap table also has no row for any of
these stages. Worth backfilling at some point so the record stays
continuous, independent of Stage 8's own entry above.

## Flag for Benz: duplicate-detection fingerprint regression from Stage 4 passage-runtime merge (2026-09-02)

Found while pulling `78fdf4b` (feat(semantic): integrate Stage 4 passage
runtime and stale invalidation) and re-verifying the frozen sidecar with
`scripts/smoke_sidecars.py` — the smoke test's own duplicate-classification
assertion started failing. Reproduced in source mode too (not a
PyInstaller/freeze artifact), so this is a real regression in the merged
code, not a packaging issue.

**Root cause:** `project.open` now constructs a `PassageSemanticRuntime`
after `ProjectRegistry.register()` has already run. That runtime writes new
state — `.apps/translationCoreAI/passageSemantic/bridge-semantic.sqlite3`
plus per-migration backup snapshots under `.../passageSemantic/backups/` —
directly into the project directory. For any project whose identity falls
back to a whole-tree hash (`_source_fingerprint()` in
`engine/tc_ai_bridge/project_registry.py:201`, used whenever a project has
no `.bridge/import.json` provenance — e.g. a hand-placed or externally
created translationCore project, not one imported through Bridge's own
`project.import` flow), `register()` snapshots the tree *before* those
passageSemantic files exist. Any later `project.inspectImport` call
recomputes the tree hash via `source_fingerprints()`/`_tree_fingerprint()`
(`project_registry.py:74`) against the *current* tree, which now includes
the new sqlite/backup files — so the project no longer hashes the same as
its own stored fingerprint. Effect: re-inspecting a project you already
opened classifies it as `possibleDuplicate` of itself instead of
`exactDuplicate`.

`_tree_fingerprint()` already excludes `.bridge/project.json` and
`.bridge/collection.json` for exactly this kind of reason (Bridge-local
identity shouldn't affect the project's own source fingerprint) — the new
`.apps/translationCoreAI/passageSemantic/` tree needs the same treatment,
or `register()` needs to snapshot the fingerprint after passage-runtime
attach instead of before. Projects imported through Bridge's normal import
flow are unaffected (their fingerprint comes from `.bridge/import.json`'s
stored SHA-256, not a tree hash), so this is scoped to
externally-created/hand-placed projects — real but not the common path.

Not fixed yet — surfacing this for Benz since it's their in-flight feature;
did not want to patch someone else's just-landed identity/lineage logic
without a decision on whether the exclusion belongs in the fingerprint
function or in ordering `register()` after runtime attach.

Repro: open any tC-shaped project lacking `.bridge/import.json` (e.g. a
hand-built fixture, as `scripts/smoke_sidecars.py`'s fixture project does),
then call `project.inspectImport` on the same path again — `classification`
comes back `possibleDuplicate`/`bookLanguageBible` instead of
`exactDuplicate`/`sourceFingerprint`.

## Automatic alignment during AI review; alignment popup goes read/decide-only (2026-08-31)

Issues #20/#21, agreed with Benz: the "Automatic AI review" card's This
verse/Chapter/Whole book buttons only ran tN/tW evidence review; alignment
stayed a fully separate manual popup action. Both are now one automatic
pass, and the popup's manual controls shrink to match.

- **#20** — `prepare_verse_review` (`tc_ai_bridge/ai_client.py`) already
  computed a gap_fill alignment proposal internally whenever a verse's
  alignment was incomplete, purely to ground the tN/tW review against —
  the proposal was then discarded (only surfaced as an unused
  `alignmentProposal` field, never rendered anywhere in the UI). No second
  AI call was needed: `_run_ai_review_for_project` (`bridge_service.py`)
  now saves that same in-memory proposal through the normal
  identity-checked `_save_alignment` pipeline whenever it actually differs
  from the verse's current alignment, deliberately bypassing Bridge's usual
  human-confirm-before-apply gate for this one path (explicit call by
  Revant + Benz, not an oversight). A failed auto-align (concurrent edit,
  validation edge case) is swallowed rather than failing the verse's tN/tW
  result — the verse just stays flagged unaligned.
- **#21** — `AlignmentModal.svelte` no longer has "Ask AI to propose
  alignment" / "Apply proposal" (alignment is filled automatically per
  #20); manual align/unalign token-click controls are unchanged. A new
  `_finish_alignment_mutation` helper in `bridge_service.py` is now the
  shared tail for every alignment-mutating path (`_save_alignment`,
  `undo_alignment`/`restore`) — it auto-marks the verse `completionState:
  "completed"` the instant every word is grouped, no button click. The
  manual "Mark alignment complete" button is removed; the existing "✓
  Human-completed" label is kept as-is (explicit decision: don't rename to
  "approved"). A new banner flags an incomplete verse in the popup itself;
  the verse-list's existing per-verse indicator (`VerseList.svelte`, ●
  complete/◐ partial/○ untouched/! invalid) needed no change — it was
  already driven by the same data-derived `status`, not the button-gated
  `completionState`.
- Deliberately left alone: `alignment.complete`/`alignment.aiPropose`/
  `alignment.aiApplyProposal` (backend + `bridgeClient.ts` wrappers) still
  exist, just unreachable from any current UI — removing a still-tested,
  independently-useful capability wasn't part of either issue's ask.

Verified: full engine suite 321 passed (2 new tests added in
`test_ai_review_auto_align.py`); `npm run check` 0 errors/0 warnings;
`npm run build` succeeds.

## Stage 3 human validation workflow (2026-08-29)

- Added an Advanced-mode validation screen for the 40 ranked IRVTam
  `MACHINE_PROPOSED` candidates. It supports status/relationship/text filters,
  source and exact-target evidence, passage navigation, reviewer notes, and
  confirm/reject/correct/needs-discussion decisions.
- Confirmation is allowed only while every proposed target span still exactly
  matches the open imported project. Human corrections support multiple target
  spans and optional explicit offsets for repeated target text; all corrected
  relationships, meaning states, confidence values, and cross-verse
  classifications are deterministically validated.
- Decisions are stored in an append-only per-project companion audit with
  reviewer, timestamp, manifest SHA-256, candidate mapping fingerprint, note,
  provenance, and the exact accepted/corrected mapping. The latest decision is
  indexed for restart recovery; no validation path writes USFM, checkData, or
  alignment data.
- Added live calibration summaries for reviewed proposals overall and by model
  confidence band/relationship. Unconfirmed and needs-discussion rows are not
  counted as model failures. Threshold or classification changes remain gated
  on the first 15–20 human decisions.
- Release packaging copies the single checked-in validation artifact into
  Tauri resources, avoiding a second tracked copy while keeping development and
  installed builds on the same SHA-pinned queue.

Verified on Windows/Python 3.12.4:

- Complete Python suite: **319 passed in 320.31s**.
- Focused semantic validation/Stage 3 suites: **28 passed in 16.29s**.
- Svelte/TypeScript: **0 errors, 0 warnings**.
- Production Vite build: passed (existing >500 kB chunk warning only).
- UI state tests: **4 passed**.
- Rust command/sidecar tests: **2 passed**; changed command file passes rustfmt.

## Stage 3 IRVTam discovery and adaptive-search hardening (2026-08-29)

- Replaced implicit radius behavior with explicit language-independent search
  budgets for model calls, adjacent structural layers, windows, segments, and
  target characters. Verse counts are not semantic boundaries.
- Search-budget exhaustion now surfaces as
  `needs_extended_passage_review`; it cannot become omission or
  Nothing-to-Select.
- Fixed expanded-result cache lookup so a persisted wide-passage result is
  reused before any repeat seed-window model call.
- Hardened Basic-mode application: Stage 3 mappings must be same-verse,
  meaning-preserved, at least 90% confident, non-uncertain, exactly grounded in
  imported USFM, compatible with the native selection, and free of matching
  contradictory QA evidence. Advanced-mode passage mappings remain advisory.
- Added a reproducible IRVTam discovery tool. After explicit data-transfer
  authorization, a full `gpt-5.6` pass generated 90 validator-accepted
  mappings and ranked a 40-row `MACHINE_PROPOSED` / `UNCONFIRMED` review queue
  across Luke (28) and Philippians (12). All 43 overt spans were independently
  verified against exact imported-USFM offsets.
- The PHP 1:3 -> 1:6 `τῷ Θεῷ μου` -> `என் தேவனை` regression is preserved as
  `CROSS_VERSE_REORDERED`, meaning preserved, at 99% model confidence. This is
  an unconfirmed validation candidate, not a Tamil-specific rule.
- One Luke 11:2-4 batch was rejected when a target quote was not an
  unambiguous exact USFM match. The generator now checkpoints every batch,
  retains rejection diagnostics, and reuses content-fingerprinted validated
  results without weakening production validation.
- Mapping remains companion-only and a regression test verifies the input USFM
  stays byte-identical.

Verified on Windows/Python 3.12.4:

- Complete Python suite: **315 passed in 314.32s**.
- Focused Stage 3/corpus suites: **24 passed in 16.19s**.
- Svelte/TypeScript: **0 errors, 0 warnings**.
- Production Vite build: passed (existing >500 kB chunk warning only).
- UI state tests: **4 passed**.
- Rust desktop tests: **2 passed**.

## Current release state

The current working release adds the complete manual word-alignment loop and
Milestone 3A's offline original-language source baseline. The
authoritative design and limitations are in `docs/ALIGNMENT.md`; the release
gate is `docs/QA_TEST_MATRIX.md`.

- Protocol: `alignment.get/status/realign/unalign/save/complete/undo/backups/restore`.
- UI: per-verse alignment modal with occurrence-aware source/target token
  selection, all four group cardinalities, word bank, issues, status, completion,
  undo and selected-history restore. RTL/LTR direction is applied independently.
- Persistence: optimistic conflict comparison, exact token-identity validation,
  transaction-journal rollback, per-verse durable history, restart persistence,
  and tC word-alignment completed/invalid/pending markers.
- Rechecking: each alignment mutation immediately reruns local and Greek Room
  verse checks and refreshes editor state.
- AI review navigation: verse progress/results follow only the exact verse,
  chapter jobs follow only their chapter, and whole-book jobs follow only their
  project. Active off-reference jobs remain visible as background work without
  presenting an old result as belonging to the newly selected reference.
- Translation Helps navigation: an explicit reserved loading surface prevents
  the panel from collapsing and expanding while a newly selected reference is
  prepared.
- Issue resolution: saved tN/tW resolutions carry exact target text, correction,
  evidence and reviewer notes; Paratext Project Note handoff is identity-gated,
  crash-safe and idempotent. Edited resolved verses enter a persisted automatic
  recheck lifecycle, while Advanced-mode AI proposals require explicit human
  acceptance before a safe pass can close an issue.
- AI selection consistency: an applicable pass may no longer become **Nothing
  to Select** merely because a provider omitted target IDs. A uniquely quoted
  phrase found exactly once in the current verse is recovered transparently;
  ambiguous or missing target text remains pending instead of being guessed.
- AI provider compatibility: structured Responses requests first use the
  configured reasoning effort. If and only if a provider/model returns an
  explicit HTTP 400 unsupported-`reasoning` error, Bridge retries once without
  that optional object and records `provider-default`; unrelated 400 errors
  remain failures.
- Export/import: nested many-to-many `zaln`/`w` milestones are parsed into tC
  groups and aligned export writes re-importable USFM 3 over the retained source
  template.
- Original-language resources: raw OT/NT imports are initialized from exact,
  checksum-verified unfoldingWord UHB v3.0.0/UGNT v0.34 packs. All 66 books,
  31,103 verses, and 443,131 canonical tokens are bundled with CC BY-SA 4.0
  licenses, attribution, exact upstream commits, source/artifact hashes, and a
  reproducible generator. Aligned USFM and native tC projects are never
  overwritten; legacy raw-import recovery only fills empty source arrays and
  stops on a resource-version mismatch.
- Automated source gate: the complete Python suite passes in the maintained Windows/
  Python 3.12.4 environment. Four focused frontend navigation-state tests,
  clean Svelte diagnostics, the production frontend build, and 2 Rust tests
  also pass. Beta 13 frozen-sidecar and NSIS results, including exact artifact
  hashes and the remaining installed GUI acceptance, are recorded in the QA
  matrix. The former load-sensitive versification wall-clock bound is now a
  deterministic concurrency-invariant test.
- Explicitly deferred: live original-source resource downloads and automatic
  continuous Paratext/Logos synchronization. Explicit one-shot Paratext issue
  handoff is implemented and manually verified. AI alignment proposals and UAlign-derived
  corpus statistics (count/probability/PMI/SED-boost) are implemented; see the
  Phase 6/7 sections further down.
- Word-info lexicon popup: clicking a source token in the alignment modal
  opens a popup with decoded morphology and a Strong's dictionary gloss
  (lemma, transliteration, Meaning/Usage/Source), matching translationCore's
  own word-details popup. New vendored resource (`openscriptures/strongs`,
  public domain) plus a `lexicon.getEntry` protocol method. See "Alignment
  word-info lexicon popup" further down for the full detail, including two
  real bugs found and fixed in the same pass (one a genuine regression, one
  pre-existing).

## Phase roadmap status — read this first before picking up new work

The original plan (from the Claude Code sessions that did Phases 1-3, see
below) laid out 7 phases. Actual status as of 2026-08-21:

- **Phases 1-3**: done.
- **Phase 4 (USFM Checker + Versification): done (2026-08-21).** The USFM
  structural checker was completed first (vendored, wired up, verified
  against both source and a frozen packaged build — see that section
  further down). **Versification (detection, org-normalization, and a
  back-versification map) is now also done** — vendored separately, wired
  into the protocol as `versification.detect`/`orgRef`/`backVersificationMap`,
  and verified against both source and a real frozen build (see the
  Versification section further down). Nothing in Phase 4 has UI beyond
  what already existed — both halves are backend/protocol-only this pass,
  matching how the USFM checker itself shipped without a dedicated panel.
- **Phase 5 (Names & Transliteration, Uroman + Smart Edit Distance): done
  (2026-08-21).** A whole-book spelling-consistency check (Uroman +
  vendored Smart Edit Distance) is wired into `verse.runChecks` behind the
  existing `"local"` checks list — no frontend change needed, same as the
  USFM checker. See "Names & Transliteration — Phase 5 complete" further
  down.
- **Phase 6 (Alignment Intelligence, UAlign corpus stats): statistics engine
  done (2026-08-24).** The manual word-alignment editor added in
  `feat(alignment)` (see `docs/ALIGNMENT.md`) wasn't in the original plan at
  all — it was a prerequisite Phase 6 actually needed, since you can't
  compute corpus statistics over "human-approved alignments" if there was
  previously no way to create or approve one inside Bridge. That gap closed
  first; Phase 6's actual statistics work is now built on top of it —
  co-occurrence counts, translation probability, PMI, and an optional
  Smart-Edit-Distance phonetic boost, computed directly from Bridge's own
  completed alignments (not a vendored `ualign.py` — see the dedicated
  section further down for why). Backend/protocol-only this pass, same
  shape as Phases 4-5: two new read-only methods
  (`alignment.corpusStats.summary`/`forVerse`), no UI yet, no QaFinding
  output — AI alignment proposals stay in Phase 7, a scope decision made
  explicitly with the user before writing any code.
- **Phase 7 (Paratext/Logos connectors, AI explain, drag-and-drop): all four
  slices have real, tested work as of 2026-08-24, on a best-effort basis for
  the two that need a live external application to fully verify.** AI
  alignment proposals and drag-and-drop import are done and verified
  end-to-end (source + frozen). AI explain is wired and tested against real
  materialized evidence (a real TWL resource-layout bug and a missing
  translationAcademy bundle were both found and fixed along the way — see
  below), verified with a fake transport since no real API key was available
  this session. The Paratext connector's real, previously-missing companion
  plugin now exists and compiles against Paratext's actual installed
  interfaces, but was not deployed or loaded by a running Paratext instance
  this session (a protected-system-directory write was correctly blocked by
  this session's own safety controls). The Logos connector's real,
  previously-missing PowerShell/COM bridge script now exists and its
  process/protocol wiring is genuinely tested, but the actual COM automation
  calls inside it are unverified — Logos was not installed on this machine.
  See "Paratext/Logos connectors and AI explain — Phase 7 continued" further
  down for the full detail, what's verified vs. not, and exact next steps.

Between Phase 3 and now, real unplanned work also landed that mattered more
than staying on the numbered track: a 66-book import that took 4-6 minutes
and hit a hard timeout is now ~5-6 seconds (lazy per-book normalization), a
real security fix (plaintext API keys could persist to disk), and a
cancellable/retryable background job system replacing a blocking frontend
loop. None of that was in the original 7 phases either — it was necessary,
so it got done. Don't assume the next piece of work has to be the next
numbered phase in sequence; check what's actually broken or blocking first.

**A hard-won practice from this project so far, worth continuing**: every
external integration attempted (Wildebeest, the USFM checker, versification)
turned out to have a real, non-obvious problem that only surfaced by actually
running the code — wrong PyPI package name, a Python 3.13 compatibility
break, an unpublished dependency, a Windows-only `strftime` crash, a
version-skew bug between upstream's own GitHub and PyPI releases, a
class-level-state crash on a second call in the same process, a silently
different data license hiding inside an otherwise BSD-licensed vendor tree.
Don't trust a doc's
description of what a new integration will do — install it, run it against
real input, and read what actually happens before writing an adapter around
it. This is equally true of *this* documentation: verify claims made here
against the actual code before relying on them for follow-up work, the same
way you'd verify any third-party dependency's claims about itself.

### Versification — now done, see the dedicated section further down

This section originally recorded a research breadcrumb ("versification.py
was located in the same upstream repo, but not read, not vendored, and not
verified — do that next"). That work is now done (2026-08-21); see
"Versification — Phase 4 complete" further down in this document, and
`engine/vendor/greekroom-versification/NOTICE.md` for full provenance. Two
things from that breadcrumb turned out to matter and weren't visible until
the code was actually read and run: `versification.py` is a genuine
importable library (unlike the USFM checker's monolithic CLI script), so
it's wired in as a direct import, not a subprocess/helper executable; and
its `data/standard_mappings/*.json` files carry a **different license (CC
BY-SA 4.0) than the BSD-3-Clause code around them** — see the dedicated
section for why that's a real distinction, not a rubber-stamp of the USFM
checker's licensing precedent.

## Project context (carried over from the Claude Code sessions that did Phases 1-3)

This section summarizes what the earlier Claude Code work (`docs/CLAUDE_CODE_HANDOVER.md`,
not committed to this repo — it lives in the original handover doc) established, so this
file is self-contained for whoever picks it up next.

**What Bridge is:** a local-first Bible translation QA workbench replacing a legacy Python
Tkinter tool. One window, one Python sidecar process, Tauri/Svelte desktop shell.

**Core principle** (see `docs/ARCHITECTURE.md`):
- Greek Room says: "This is objectively suspicious."
- AI says: "Here is what it may mean in this passage."
- Human says: "This is what the translation should be."
- Nothing auto-applies to project files without human approval.

**Tech stack:** Tauri v2 (Rust) shell, Svelte 4 + TypeScript + Tailwind frontend, Python 3.13
PyInstaller-bundled sidecar (`bridge-engine`), Greek Room (Wildebeest adapter, mock fallback
if the real package isn't installed) plus 29 pre-existing `tc_ai_bridge` business-logic
modules (alignment, Paratext, Logos, AI, now also import), JSON-over-stdio protocol, pytest.
Windows is the primary target (`x86_64-pc-windows-msvc`); macOS/Linux are planned.

**Repo layout skeleton:**

```
engine/
  bridge_service.py          ← the sidecar dispatcher, read this first
  main.py                    ← sidecar entrypoint (PyInstaller target)
  greek_room_engine/         ← QA adapter layer (engine.py, models/finding.py,
                                protocol.py, adapters/, transport/stdio_transport.py)
  tc_ai_bridge/               ← 29 existing business-logic modules, not rewritten
                                (now 30, with project_import.py added — see below)
  tests/                      ← pytest suite

src/
  App.svelte, lib/stores.ts, lib/api/bridgeClient.ts, lib/types/finding.ts,
  lib/components/{ImportScreen,TopBar,VerseList,ReviewPanel,SettingsModal,ExportModal}.svelte

src-tauri/
  src/{main.rs,sidecar.rs,commands.rs}
  tauri.conf.json, capabilities/default.json, binaries/, icons/

docs/
  ARCHITECTURE.md, DEVELOPER_GUIDE.md, BUILD_LOG.md (this file), IMPORTS.md
```

### Phases 1-3 (done, before this import work)

- **Phase 1 — Protocol & sidecar consolidation:** `BridgeEngine` composes
  `GreekRoomEngine` + `tc_ai_bridge` behind one JSON protocol (`ping`, `engine.info`,
  `project.open`, `project.scan`, `chapter.verses`, `chapter.verseData`, `verse.get`,
  `verse.runChecks`, `verse.decide`, `verse.edit`, `settings.get`, `settings.set`,
  `export.aligned`, `export.nonAligned`). 24/24 pytest passing against a real fixture
  project with verified real file writes.
- **Phase 2 — Svelte frontend wired to the real sidecar:** full single-window UI
  (ImportScreen, TopBar, VerseList with inline colored findings, ReviewPanel with live
  Greek Room re-check and Accept/Reject/Ignore/Edit). Windows UTF-8 stdout fix applied.
- **Phase 3 — Decision persistence, chapter switching, whole-book, Settings & Export:**
  stable finding ids so decisions survive re-runs, chapter switching, "Run whole book"
  automation, `SettingsModal` (any OpenAI-compatible provider/endpoint/model/key),
  `ExportModal` (aligned JSON + simplified USFM export). Automation now uses
  sidecar-owned `checks.start/status/cancel/retry` jobs with real per-stage
  progress; cancellation is cooperative at check boundaries and failed or
  cancelled jobs remain retryable.

**This import-pipeline work (below) was new ground, not the originally planned Phase 4.**
The original roadmap after Phase 3 was: Phase 4 = USFM structural checker
+ versification; Phase 5 = names/transliteration (Uroman + SED); Phase 6 = alignment
intelligence (UAlign corpus stats); Phase 7 = Paratext/Logos connectors wired to the
protocol + AI explain + drag-and-drop import. Import work was picked up first because a
working import pipeline blocks everything downstream (you need real Scripture in the app
before checks/alignment/names work matter). **The USFM structural checker half of Phase 4
is now done (2026-08-20, see below)** — versification, and Phases 5-7, still haven't been
started.

### Gotchas still in force (from Phases 1-3, verified still true in the current code)

1. `TranslationCoreProject.summary` is a `@property`, not a method — calling `summary()` crashes.
2. `TranslationCoreProject.__init__` creates its own `self.journal`. Never create a second one.
3. Finding ids are stable (`_stable_finding_id()` in `bridge_service.py`, a sha1 of
   `chapter:verse:engine:check_type:disambiguator`) so decisions persist across runs.
   Don't revert to random `uuid4()` ids.
4. `verse.runChecks` re-applies prior decisions from `qa_decisions_for_verse()` after
   running checks — this must stay in the check flow, not a separate call.
5. Windows stdout UTF-8 fix (`sys.stdout.reconfigure(encoding="utf-8")` in
   `stdio_transport.py`) is critical — without it, non-Latin verse text crashes the
   sidecar silently and the Rust side just sees a timeout. Never remove it.
6. `plugins.shell.sidecar` must NOT be in `tauri.conf.json` — not a valid field, causes
   a startup panic. Sidecar permission comes entirely from `capabilities/default.json`'s
   `shell:allow-execute` entry.
7. Store keys are composite `chapter:verse` (e.g. `"1:3"`) — use `verseKey()` from
   `stores.ts`, not verse-only keys (silently collides data across chapters).
8. `ai_client.py`'s `OpenAIResponsesClient` endpoint is configurable via `base_url`;
   don't reintroduce a hardcoded `ENDPOINT` constant.
9. The sidecar binary name must match the Rust target triple exactly
   (`bridge-engine-x86_64-pc-windows-msvc.exe` on Windows — get the triple from `rustc -vV`).
10. Don't use icon-font classes (`ti-settings` etc.) for icon-only controls with no
    fallback label — PyInstaller/offline builds can't reach CDN icon fonts and they
    render as empty boxes. Use Unicode characters or pair with a text label.

### Known gaps still open (from Phases 1-3, verified still true in the current code)

- ~~USFM edit round-trip is still a stub~~ — **done 2026-08-20.** The real
  write logic wasn't missing from `tc_ai_bridge` at all — it turned out
  `TranslationCoreProject.apply_scripture_edit()` in `tc_project.py` was
  already a complete, working implementation (writes the target chapter
  JSON, reconciles alignment by word/occurrence signature, marks word
  alignment invalid, flags touched tN/tW index entries `verseEdits=True`,
  full journal transaction with rollback). `bridge_service.py`'s
  `edit_verse()` was just never calling it — it had its own separate no-op
  stub instead. Now it does: `edit_verse()` is a thin wrapper again, matching
  every other method in this file. The frontend (`ReviewPanel.svelte`) was
  already fully built for this (save, update store, re-run checks) and
  needed no changes beyond two small robustness fixes found while wiring
  this in: saving unchanged text is now a silent no-op instead of throwing
  an unhandled rejection (`apply_scripture_edit` correctly rejects a no-op
  edit; the UI just didn't call it before, so it never surfaced), and a real
  failure now shows an inline error instead of vanishing silently. Covered
  by two new tests in `test_bridge_service.py` that verify the edit actually
  lands (not just "committed": true) and that `WA_INVALID` surfaces on the
  next `verse.runChecks`. Full suite: 39/39 passing. Not click-tested in a
  running Tauri window this session (same build constraint as the other
  frontend work above) — worth a real click-through: edit a verse, confirm
  the new text persists after switching chapters and reopening the project,
  and that a stale-alignment finding appears.
- ~~`export.nonAligned` was a simplified reconstruction~~ — **superseded.** Both
  USFM exporters now use the retained source as a structural template and
  report the simplified fallback only for projects with no source USFM.
- **OWL repeated-word adapter doesn't exist yet** (`adapters/owl_adapter.py`).
- ~~Real Wildebeest package is still untested~~ — **done 2026-08-20, real
  engine wired up and passing tests. Requires Python 3.12, not 3.13.**

  **Root cause of the original blocker**: `pip install wildebeest` installs
  the wrong package (a same-named, unrelated ShopRunner image-processing
  library — never use it). The real one, from Ulf Hermjakob/USC-ISI, is on
  PyPI as **`wildebeest-nlp`** (only release: 0.9.2). Installing that under
  Python 3.13 fails to *compile* with `UnicodeEncodeError: ...surrogates not
  allowed` — one of its docstrings contains a literal `\uDC80`-`\uDCFF`
  escape as prose (describing surrogateescape handling, ironically), and
  **Python 3.13 newly disallows lone-surrogate escapes in docstrings at
  compile time** ([CPython issue #142411](https://github.com/python/cpython/issues/142411)
  confirms this is an intentional 3.13 change). Confirmed the same broken
  docstring is still on upstream's GitHub `master`, so installing from
  GitHub wouldn't have helped either. **Python 3.12.10 does not hit this
  restriction — confirmed working.** The machine this was developed on has
  since been switched from 3.13 to 3.12 entirely.

  **Engine now has a dedicated venv**: `engine/.venv` (gitignored), built
  with `py -3.12 -m venv .venv`, populated via
  `.venv\Scripts\python.exe -m pip install -e ".[dev,wildebeest]"`. The
  `wildebeest` extra in `pyproject.toml` pins `wildebeest-nlp==0.9.2` and is
  optional, not a hard dependency — `WildebeestAdapter` degrades to its mock
  whether it's installed or not, so a plain `pip install -e ".[dev]"` on any
  supported Python still works. Run tests via
  `engine\.venv\Scripts\python.exe -m pytest tests/ greek_room_engine/tests/ -q`
  (45 passed, includes 6 new real-engine tests, auto-skipped when the extra
  isn't installed).

  **Found and fixed a real related bug while investigating**: the adapter's
  `try: import wildebeest.wb_analysis ... except ImportError` only caught
  `ImportError`. Since the real failure mode is `UnicodeEncodeError`, simply
  having `wildebeest-nlp` installed (even with zero other code changes)
  would have crashed the entire sidecar at startup instead of degrading to
  the mock. Widened to `except Exception` — done and safe regardless of
  which Python version anyone else builds with.

  **What `_check_with_wildebeest()` now actually does** (previous version
  called a `wb_ana.check()` function that doesn't exist in the real
  package — that whole implementation was speculative and never once run
  against the real dependency). The real entry point is
  `wb_analysis.process(string=, lang_code=, json_output=<IO>)`, which
  returns an aggregate analysis report grouped by category — not a flat
  per-position issue list. Verified directly against 0.9.2 with real inputs
  (not documented anywhere upstream). Only three of its categories are
  wired into findings, each checked against real triggering input:
  `notable-token` (mixed-script tokens), `non-canonical` (NFD vs NFC form,
  with a real suggested-replacement), and zero-width/invisible characters
  from `block.ZERO_WIDTH`. Deliberately **not** treating every top-level key
  as a finding — most of the rest (`letter-script`, `block`'s ordinary
  per-character tallies) are corpus-level descriptive counts, not defects;
  verified a clean real Tamil verse produces zero findings from the real
  engine. `char-conflict` and `pattern` are real categories in the schema
  that no test input in this session happened to trigger — their shape is
  unverified, so they're not wired up. Don't guess it; verify against real
  triggering input first, the same way the rest of this was done.

  **Not yet done**: PyInstaller packaging for the real engine wasn't
  attempted this session. `wildebeest-nlp` ships a `data/` directory
  alongside its code — untested whether `wb_analysis.process()` reads
  anything from it at runtime (none of the three wired categories needed it
  in testing, but that doesn't rule out other paths). If building a frozen
  `.exe` with the real engine included, add
  `--collect-data wildebeest` to the PyInstaller command below as a
  defensive measure and verify carefully — this is unverified insurance,
  not a confirmed-necessary step.
- **Drag-and-drop import is still not wired** — no `onDragDropEvent` listener from
  `@tauri-apps/api` exists in `src/`; `ImportScreen` still requires the file picker.

### USFM structural checker — Phase 4 half done (2026-08-20)

New adapter, `engine/greek_room_engine/adapters/usfm_adapter.py`, registered
in `GreekRoomEngine`. Catches duplicate/missing verse numbers, unclosed
inline markers, and other structural USFM problems — a real gap nothing
else in the app checked before this.

**This is vendored, unpublished third-party code, not a normal
dependency — read this before touching it.** Unlike Wildebeest,
`greekroom`'s `usfm` submodule is **not published on PyPI** (only `owl`
and `gr_utilities` are, confirmed by inspecting the actual installed
wheel — `usfm`/`versification`/`wildebeest` exist only in the
`BibleNLP/greek-room` GitHub source tree). The decision to vendor it
anyway — rather than wait on upstream packaging or build a lesser
in-house checker — was made explicitly, with the license and long-term
maintenance cost discussed first. Don't undo that decision by casually
"cleaning up" or replacing this without the same consideration.

**Where it lives**: `engine/vendor/greekroom-usfm/` — `usfm_check.py`,
`ualign_utilities.py`, `Bible_USFM_tag_data.jsonl`,
`Bible_USFM_explanations.txt`, and a nested `greekroom/gr_utilities/`
package (see below for why). Full provenance — source URL, pinned commit
`18ddcf0e6c03fa2774b73b21186115d712e4cba9`, BSD 3-Clause license text and
attribution, and an explicit "don't edit these files in place" policy —
is in `NOTICE.md` in that directory. **Read `NOTICE.md` before re-syncing
against upstream or making any change here.**

**How it's invoked**: as an isolated subprocess (`UsfmAdapter.check_book()`),
not an import. In source mode the adapter uses the active Python interpreter
and the vendored script. In a frozen build it resolves the sibling
`bridge-usfm-checker[.exe]`, a separate PyInstaller artifact with a
Bridge-owned entrypoint (`engine/usfm_checker_main.py`). This matters:
`bridge-engine.exe` always starts the JSON-RPC loop and cannot be used as
`python.exe usfm_check.py`. The helper bundles the pinned vendor directory,
`regex`, both checker data files, and the license/notice. The adapter passes
stdin as `DEVNULL`, validates the exit code and report, and returns an
explicit `checker_error` for a timeout/crash/missing report instead of
silently treating failure as a clean book.

**Its own `-j/--json` output flag is dead code** — accepted by its
argparse setup but never referenced anywhere else in the 4,000 lines.
Verified by reading the source, not assumed; don't try to use `-j` and
expect a file to appear. The `.txt` report is the only real output to
parse, and its indentation depth to reach an individual issue varies by
category (3 or 4 levels) — `_parse_report()` in the adapter tracks an
indentation stack rather than assuming a fixed depth, and recognizes three
distinct real location-reference formats found by testing (see the
function's own docstring and `test_usfm_adapter.py` for the real captured
report text each was found in).

**Two real bugs found and fixed while integrating** — both documented
inline where fixed, in case they inform an upstream bug report later
(see the earlier discussion in this doc about contributing a packaging
fix upstream):
- A line in `usfm_check.py` used `%-d`/`%-H` in a `strftime` format string
  — glibc-only extensions Windows' C runtime doesn't support, raising
  `ValueError` immediately on startup on this Windows dev machine.
  Patched in place (marked `# BRIDGE PATCH`, per `NOTICE.md`'s policy for
  changes that are genuinely unavoidable) to the portable zero-padded
  equivalent — cosmetic only, just a report timestamp.
- The vendored `usfm_check.py` (pinned commit) calls
  `general_util.mkdirs_in_path()`, which doesn't exist in the *published*
  `greekroom==0.0.20` PyPI package's `gr_utilities.general_util` —
  **upstream's own GitHub source and PyPI release have already drifted
  apart from each other.** Fixed by also vendoring `general_util.py` from
  the *same* pinned commit (`greekroom/gr_utilities/` inside the vendor
  directory) and prioritizing it on the subprocess's own `PYTHONPATH`,
  rather than relying on the separately pip-installed `greekroom` package
  for this specific tool's dependencies. This is why the subprocess's
  `PYTHONPATH` matters — don't "simplify" it to just use whatever
  `greekroom` happens to be pip-installed.

**Wiring into checks**: whole-book, not per-verse — see
`UsfmAdapter`'s and `BridgeEngine._usfm_findings_for_book()`'s own
docstrings for why (each run spawns a subprocess loading a real tag
database). `bridge_service.py` computes and caches findings once per
book (keyed by project path), then filters to the requested chapter/verse
inside `run_verse_checks` whenever `"local"` or `"usfm"` is requested —
so it activates automatically with the frontend's existing default checks
list, no frontend change needed. A finding with no specific verse (e.g. a
whole-chapter "missing verse N") surfaces on that chapter's first verse,
since the UI has no chapter-level display slot. **Not invalidated by
`verse.edit`** — re-running the subprocess after every edit would be far
too slow, and a single verse edit essentially never changes book-wide
structure; re-opening the project re-runs it fresh. Findings get the same
stable-id treatment as Wildebeest/tN/tW findings, so decisions persist
across sessions.

**Verified**: `test_usfm_adapter.py` (parser unit tests against real
captured report text, not synthetic guesses; real end-to-end subprocess
tests against real broken and clean USFM; a subprocess-failure test
confirming explicit failure rather than false-clean degradation) plus
book-level success/failure caching tests in `test_bridge_service.py`.
`scripts/smoke_sidecars.py` runs the actual frozen `bridge-engine.exe` and
helper against balanced USFM containing duplicate and missing verses, then
asserts real `engine="usfm"` findings. Verified on Windows 2026-08-20.
Historical result at that milestone: 56 passed, 1 optional-Wildebeest module skipped.

**Packaging**: run `scripts/build-sidecars.ps1`; it builds both committed
specs and copies both target-suffixed artifacts into `src-tauri/binaries/`.
Tauri declares both in `bundle.externalBin`. Chapter/book automation starts a
sidecar-owned background job and polls lightweight status snapshots, so the
stdio dispatcher stays responsive while the helper runs. `verse.runChecks`
retains a 150-second timeout for the separate live per-verse recheck path.

### Versification — Phase 4 complete (2026-08-21)

New module, `engine/tc_ai_bridge/versification.py`, wrapping the vendored
Greek Room versification tool at `engine/vendor/greekroom-versification/`
(see that directory's `NOTICE.md` for full provenance, license, and the real
bugs found while integrating it — summarized below). Adds three sidecar
protocol methods: `versification.detect`, `versification.orgRef`,
`versification.backVersificationMap`.

**Different books/traditions number chapters and verses differently** — the
concrete motivating example: Psalm 3's Hebrew ('org') text opens with a
descriptive title ("A Psalm of David, when he fled from Absalom his son")
counted as verse 1, which most English ('eng') Bibles don't number as its
own verse. So eng verse 1 ("LORD, how are they increased that trouble me!")
is org verse 2, and the whole rest of the chapter is shifted by one. Six
standard schemas are supported: `org` (original Hebrew/Greek), `eng`
(English/Protestant), `rsc`/`rso` (Russian Synodal canonical/Orthodox),
`vul` (Vulgate/Catholic), `lxx` (Septuagint/Orthodox) — the same six
`versification.py` itself defines, sourced from real Paratext/Copenhagen
Alliance mapping tables, not invented by Bridge.

**This is vendored, unpublished third-party code, like the USFM checker —
but integrated differently, not by copying that precedent blindly.**
Confirmed freshly this session (not assumed from the USFM checker's
already-established facts): still not on PyPI; still BSD-3-Clause code from
the same pinned commit `18ddcf0e6c03fa2774b73b21186115d712e4cba9`. But two
things turned out to be genuinely different, found only by reading the
source and running it against real data:

1. **`versification.py` is a real library, not a CLI script.**
   `BibleStructure`, `Versification`, `VersifiedCorpus`,
   `VersificationMatch`, and `BackVersification` are classes with methods
   that operate on in-memory dicts — unlike `usfm_check.py`'s 4,000 lines
   with no reusable functions. So this is **imported directly into the
   long-lived `bridge-engine` process**, not run as a subprocess/helper
   executable. `tc_ai_bridge/versification.py` builds `VersifiedCorpus`
   objects straight from Bridge's own already-parsed chapter/verse text
   (`TranslationCoreProject.verses()`/`target_verse_text()`) — it never
   calls the vendored tool's file-based `load_corpus`/`write_corpus`/`main()`
   entry points at all.
2. **The mapping data carries a different license than the code around
   it.** `data/standard_mappings/*.json` originates from the Copenhagen
   Alliance Versification Working Group, not greek-room itself, and that
   project's own `LICENSE.md` splits code (Apache 2.0) from **data (CC
   BY-SA 4.0 — attribution + share-alike)**. Bridge's own root license is
   GPLv3 (already copyleft), which makes bundling attributed, unmodified CC
   BY-SA 4.0 reference data low-risk — but this was a real, separate
   decision, not a rubber-stamp of the USFM checker's BSD-3-Clause-only
   precedent. See `engine/vendor/greekroom-versification/NOTICE.md` for the
   full reasoning; re-review if these JSON files are ever modified before
   redistribution.

**Two real bugs found by actually running the vendored code against real
data** (documented in full in that directory's `NOTICE.md`, including how
each was reproduced):

- `Versification.load_versifications()` keeps **class-level** state
  (`Versification.versification_d`, `Versification.org`) that is never
  reset. A second real call in the same process — exactly what a naive
  per-project-open call from a long-lived `bridge-engine.exe` would do —
  hits a duplicate-schema branch, logs an error, and returns a
  half-constructed object with no `verse_id_list`; the very next line then
  crashes with `AttributeError`. Reproduced directly by calling it twice,
  not assumed from the USFM checker's own gotchas. Fixed in Bridge's
  wrapper by loading exactly once per process (lock + flag guard) —
  nothing outside `tc_ai_bridge/versification.py` should import the
  vendored `versification` module or call `load_versifications()` directly.
- `VersifiedCorpus.load_corpus()`/`write_corpus()` (and `main()`'s other
  file opens) use bare `open()` with no explicit encoding, which reproduces
  the exact same Windows `cp1252` `UnicodeDecodeError` already found and
  patched in `usfm_check.py`, confirmed here with a real Tamil string. **Not
  patched**, unlike the USFM checker's two `# BRIDGE PATCH` markers — Bridge's
  usage never calls those file-based methods (point 1 above), so this bug is
  architecturally avoided rather than fixed. If anything ever calls
  `load_corpus`/`write_corpus`/`main()` directly, patch it the same way.
- `vref.txt` (390 KB) and `psalm-descriptive-titles.txt` were deliberately
  **not** vendored: verified by reading the source that neither is read by
  any of the five classes Bridge actually calls, only by the CLI `main()`
  Bridge never invokes.

**Protocol methods** (all whole-book-scoped, cached per project path like
the USFM findings, computed lazily on first request rather than on every
`project.open`):

- `versification.detect` — sniffs the best-fitting schema for the open
  project's book against all six standard schemas and returns every
  schema's match cost, not just a bare label, so a caller can show how
  confident the detection is.
- `versification.orgRef` — normalizes one chapter:verse into its `org`
  equivalent (defaulting to the project's own detected schema). Returns a
  `mapping` field — `same` / `mapped` / `merge` / `split` — because
  cross-tradition shifts aren't always 1:1; callers should branch on that
  field rather than parsing `orgRef` as free text.
- `versification.backVersificationMap` — the inverse: every `org` verse in
  the book mapped back to the project's own numbering, for display/export
  use without hand-rolling the mapping direction.

**Verified**: `engine/tests/test_versification.py` (22 tests against the
real vendored data — including the Psalm 3 shift and its back-versification
round trip, real merge/split mappings, unknown books, USFM verse
bridges/segments passed straight through, and a direct real-bug-reproduction
test that calls the module's public functions twice in a row to confirm the
class-level-state crash found above stays fixed) plus protocol-level
coverage in `test_bridge_service.py` (a Ruth fixture proving identity
mapping for a fully-canonical book, and a dedicated Psalms fixture proving
the real cross-tradition shift flows end-to-end through `handle_request`).
Full source suite: 122 passed.

**Concurrency — a second real bug found, this time by writing concurrency
edge case tests rather than by reading the source.** `detect_schema()`'s
scan over a schema's full verse list is pure Python and ~0.5s
single-threaded — but running several of those scans on different threads
*at once* doesn't scale proportionally under CPython's GIL, it degrades
catastrophically: measured directly at 16 concurrent callers taking **~47
seconds each** (not the ~8s naive linear scaling predicts — over 90x worse
than sequential). Reproduced with a genuinely fresh subprocess and
fine-grained per-thread timing, not assumed from general GIL folklore.
Since `bridge_service.py` calls this once per book on first request and
caches the result, the realistic trigger is a burst of near-simultaneous
`versification.detect` calls before any of those caches are warm — which
would look exactly like the sidecar hanging. Fixed by serializing the scan
with the same lock `_ensure_loaded()` already uses; the identical 16-thread
scenario then completes in ~8s total. `to_org_ref`/`back_versification_map`
do plain dict lookups (not this scan) and were separately measured safe
unlocked under the same concurrency — this isn't a "lock everything"
fix, and don't assume it's free insurance for code added to this module
later without re-measuring. Guarded by `test_versification_concurrency.py`,
which deterministically instruments the expensive matcher boundary and
asserts that concurrent callers never overlap there. Full details in
`engine/vendor/greekroom-versification/NOTICE.md`'s finding 4.

**Packaging — a real gap found and fixed, not assumed to be handled by
precedent**: because this is imported directly into `bridge-engine.exe`
rather than run as a separate helper (unlike the USFM checker), the
vendored `versification.py` + `data/` tree and its one third-party
dependency (`regex`) are invisible to PyInstaller's static import analysis
— `main.py` never imports them directly; `tc_ai_bridge/versification.py`
only reaches them via a runtime `sys.path.insert` + `import`. Left alone,
a frozen build would have shipped with `versification.detect` crashing on
first use. Fixed in `bridge-engine.spec`: `datas` now includes
`vendor/greekroom-versification`, extracted under `sys._MEIPASS` in a
frozen build (`tc_ai_bridge/versification.py`'s `_vendor_root()` resolves
the same way `resource_materializer.bundled_resources_source()` already
does), and `hiddenimports` now includes `regex`. **Verified against a real
PyInstaller build this session**, not left as an assumption: built
`bridge-engine.exe` from the updated spec, ran it as a real subprocess over
its stdio JSON-RPC protocol, and confirmed `versification.detect`/`orgRef`/
`backVersificationMap` all return correct real results (including the
Psalm 3 shift) from inside the genuinely frozen executable. The existing
`scripts/smoke_sidecars.py` frozen-sidecar smoke test also still passes
against the rebuilt executable.

**Not done in this pass**: no UI surfaces any of this yet (no schema
indicator, no dual-reference display, no export-time renumbering) — matching
how the USFM checker itself shipped as backend/protocol-only. `versification
.detect`'s result isn't wired into the findings feed as an informational
notice; it's exposed as project metadata a future UI can call on demand,
not injected automatically. Per-book detection results are cached only for
the lifetime of the process/current project (same lifetime as the USFM
findings cache), not persisted to disk.

### Names & Transliteration — Phase 5 complete (2026-08-21)

This section originally recorded a research breadcrumb (nothing wired up,
just an investigation of whether Uroman and Smart Edit Distance were even
real, installable dependencies). That work is now done — a whole-book
names/spelling-consistency check is wired into the protocol, tested against
both source and a real frozen build. The original research findings below
are kept as-is (still accurate, still worth reading for *why* things are
built the way they are); the "What was actually built" subsection further
down covers the implementation, the two real bugs found while building it,
and what's verified. **Verify all of this again before relying on it** —
same standing instruction as everywhere else in this doc.

**Uroman is a real, currently installable PyPI dependency — it does not
follow the Wildebeest name-trap pattern.** `pip install uroman` installs
the genuine package by Ulf Hermjakob, USC/ISI (same research group as
Wildebeest and the vendored `greek-room` tools), current release
`1.3.1.1`, `Requires-Python: >=3.10`, one real dependency
(`regex>=2024.5.15`, compatible with the `regex>=2023.10.3` floor already
in `engine/pyproject.toml` for the USFM checker). Confirmed by actually
installing it and reading the wheel's own METADATA — not assumed from the
package name alone, per this project's standing rule.

- **API, verified by direct use, not docs**: `uroman.Uroman()` is the
  entry point. Construction loads the full romanization table set — real
  measured cost on this machine was **1.8-2.1 seconds** — after which
  `romanize_string(s, lcode=...)` calls measured effectively instant
  (0.0000s) on repeat calls, confirmed by timing both a first and second
  call. This is a real, substantial cost that validates
  `docs/ARCHITECTURE.md`'s "loaded once, not per call, per Uroman's own
  documented recommendation" line — that line was written before anyone
  had actually read Uroman's docs or run the code; it's now confirmed true
  for a concrete, non-hypothetical reason (a multi-second table load), not
  rubber-stamped.
- **Data**: ships ~4.2 MB of real resource files inside the wheel itself
  (`UnicodeData.txt` at 1.9 MB, `romanization-auto-table.txt` at ~1 MB,
  `Chinese_to_Pinyin.txt`, `Scripts.txt`, etc. — 13 files total), resolved
  at runtime via `Path(__file__).parent / "data"` (confirmed by reading
  `Uroman.default_data_dir()`'s source directly). This is the same shape
  of packaging risk already flagged as unverified insurance for
  `wildebeest-nlp`'s own `data/` directory in the Real Wildebeest section
  above, and the same shape of problem versification's vendor tree solved
  with `bridge-engine.spec`'s `datas` entry — **not yet tested against a
  frozen PyInstaller build this session**; treat as a real open item, not
  a formality, before shipping.
- **Verified against real cross-script Biblical name data on Windows**,
  not synthetic strings: Hindi/Urdu/English "Nepal" (नेपाल → `nepaal`,
  نیپال → `nipal`, matching Uroman's own paper example exactly), Greek
  Ἰωάννης → `Ioannes`, Tamil யோவான் → `yoovaan`, Arabic محمد → `mhmd`,
  Hebrew יוֹחָנָן → `yochanan`. No network access was used or required —
  entirely offline, matching Bridge's own connectivity requirement.
- **License — real, confirmed drift, same shape of bug as the
  `greekroom` package's Apache/BSD classifier mismatch already recorded
  above, not a new problem shape.** Both the published wheel's METADATA
  *and* upstream's own `pyproject.toml` on GitHub classify the license as
  `"License :: OSI Approved :: Apache Software License"`. The actual
  bundled `LICENSE.txt` (confirmed identical between the PyPI wheel and
  upstream's GitHub `LICENSE.txt`, so this is an upstream authoring
  mistake, not a wheel-build artifact) is **not Apache 2.0 text at all** —
  it's a custom MIT-style permissive license with a mandatory attribution
  clause: *"Any publication of projects using uroman shall acknowledge its
  use: 'This project uses the universal romanizer software "uroman"
  written by Ulf Hermjakob, USC Information Sciences Institute
  (2015-2020)'."* This confirms `docs/ARCHITECTURE.md`'s previously
  unverified "Uroman has its own attribution requirement" note was right,
  but for a more specific reason than assumed — it isn't an extra clause
  layered on top of Apache 2.0, the Apache classifier itself is simply
  wrong. Bridge will need to surface that exact acknowledgment string
  somewhere real (an about screen, a NOTICE.md, export metadata), not just
  bundle a copy of the license file.

**Smart Edit Distance (SED) is not a separately published tool and not
part of a different repo — it lives in the same pinned `BibleNLP/greek-room`
commit (`18ddcf0e6c03fa2774b73b21186115d712e4cba9`) already vendored for
the USFM checker and versification**, at
`smart_edit_distance/src/smart_edit_distance.py` plus
`smart_edit_distance/data/string-distance-cost-rules.txt` (general rules)
and a second Devanagari-specific cost file. Confirmed not on PyPI under
`smart-edit-distance`, `smart_edit_distance`, or inside the published
`greekroom` PyPI package (`0.0.20`, which — per the USFM checker's own
established precedent — only ships `owl`/`gr_utilities`, not this). Same
integration shape as the USFM checker and versification: unpublished,
vendor it from the pinned commit, don't wait on upstream packaging.

- **Shape: closer to versification.py than to usfm_check.py.** It's a
  single ~430-line file, pure Python standard library only (`argparse`,
  `logging`, `re`, `sys`, `typing` — zero third-party imports, and no
  import of Uroman itself despite the module's own docstring describing
  the two as complementary). A `SmartEditDistance` class holds
  per-instance state (`self.ht`, `self.max1`/`self.max2`, etc.) — no
  class-level shared state like the real bug found in
  `Versification.load_versifications()`, so the same second-call crash
  class of bug doesn't reproduce here (checked directly by instantiating
  it twice). This argues for a direct import into the long-lived
  `bridge-engine` process, the same way `versification.py` was integrated,
  not a subprocess/helper executable like the USFM checker.
- **License: plain BSD-3-Clause, same as the repo root — no hidden
  second license this time.** Checked directly because versification's
  CC BY-SA data-license surprise means this can no longer be assumed;
  this time there wasn't one. The cost-rule `.txt` data files carry no
  separate license notice of their own.
- **Real bug found by actually running it against the real data file —
  the third confirmed instance of the exact same bug class this project
  keeps finding in every one of these vendored/adjacent tools.**
  `SmartEditDistance.load_smart_edit_distance_data()` calls bare
  `open(raw_cost_file)` with no explicit encoding when given a string
  path. The real `string-distance-cost-rules.txt` contains 117 non-ASCII
  bytes (confirmed by reading it as raw bytes, not assumed from the
  filename). Loading it under this machine's default Windows locale
  (`cp1252`) throws `UnicodeDecodeError: 'charmap' codec can't decode byte
  0x90 in position 3802: character maps to <undefined>` — reproduced live,
  not inferred. Needs the same explicit `encoding="utf-8"` fix already
  applied to `usfm_check.py` (2 call sites) and identified-but-architecturally-
  avoided in `versification.py`'s file-based methods.
- **Functional verification, combined with real Uroman output, not
  hypothetical pairs**: loaded the real cost-rules file (417 entries / 834
  compiled rules) and ran `string_distance_cost()` on name pairs. Results
  matched the module's own docstring examples exactly: `"Josef Schumann"`
  vs `"Joseph Schuman"` scored **0.03** (plain Levenshtein: 3),
  `"Muhammad"` vs `"Mohamed"` scored **0.22** (plain Levenshtein: 3),
  `"Jim"` vs `"Kim"` correctly stayed at the default substitution cost of
  **1.0** (matching the docstring's own claim that these should read as
  more different than the phonetic-variant pairs above). A live
  cross-script test combining both tools — Tamil யோவான் (uroman:
  `yoovaan`) vs English `"John"` — scored **1.52**, correctly landing
  between "same word, different spelling convention" and "unrelated
  strings." This is the first time in this session anything actually
  chained Uroman's output into SED's cost function, not just tested each
  tool in isolation.

The above was investigation only when first written — nothing was built
yet, deliberately, until the real shape of both dependencies was confirmed.
Everything below this point was added afterward, once the user confirmed
the check's actual design.

#### What was actually built

**Design decision, made explicitly with the user before writing any code**:
of three options presented (a general whole-book phonetic spelling check; a
translationWords-names-anchored consistency check requiring a new,
unproven candidate-extraction heuristic; or infrastructure-only with no
check at all), the user chose the general whole-book check. It compares
every pair of distinct target-language word types used in the open book
and flags pairs whose *romanized* forms are suspiciously close (low Smart
Edit Distance cost) but not identical. It never claims two spellings are
the same name or that either is wrong — only that they're objectively
close — keeping it on the "Greek Room says: this is objectively
suspicious" side of the architecture doc's three-way design boundary. The
names-anchored alternative was explicitly rejected as riskier: it would
have required guessing which target word renders a given name from
translationWords occurrence data alone (no word alignment exists for most
verses), a real semantic claim Greek Room has no reliable way to verify.

**Vendored**: `engine/vendor/greekroom-smart-edit-distance/` — pinned to
the exact same `BibleNLP/greek-room` commit already used for the USFM
checker and versification (`18ddcf0e6c03fa2774b73b21186115d712e4cba9`).
Confirmed via the GitHub API tree listing that `smart_edit_distance.py`
plus two cost-rule data files are the *entire* contents of that directory
at this commit. See that directory's `NOTICE.md` for full provenance.
`uroman>=1.3.1.1` was added as a real, hard dependency in
`engine/pyproject.toml` (not optional/mock-fallback like Wildebeest — it
has no known installability problem on any currently supported Python
version). `regex`'s floor was raised from `>=2023.10.3` to `>=2024.5.15`
to satisfy uroman's own requirement — same package, no real conflict.

**New code**: `engine/greek_room_engine/adapters/names_adapter.py`
(`NamesAdapter`, registered in `GreekRoomEngine`), a new
`GreekRoomEngine.check_book_names()` method mirroring
`check_book_usfm()`'s shape, and `BridgeEngine._names_findings_for_book()`
in `bridge_service.py` mirroring `_usfm_findings_for_book()` — same
whole-book caching-per-project-path pattern, same cache-clearing on
`project.open`/`project.import`, same stable-id treatment (here keyed on
the two spellings being compared, sorted, so decisions survive repeat
runs regardless of which spelling a given run happens to treat as
"majority"). Wired into `run_verse_checks` behind `"local" in checks or
"names" in checks` — the exact same gating shape as the USFM checker —
which is why **no frontend change was needed**: `App.svelte` and
`ReviewPanel.svelte` already always send `checks: ["local", "greekroom"]`.

**Two real bugs found by actually running this against real data, not by
reading the source**, on top of the encoding bug already found and
documented (architecturally avoided, not patched) during the research
phase and recorded in the vendor directory's `NOTICE.md`:

1. **A real false-positive class**: testing against plain English
   "church"/"churches" — an ordinary, correctly-spelled singular/plural
   pair, not a spelling inconsistency — scored **0.70** under the general
   cost-rules file, because rules tuned for name-like variation (dropped
   vowels, consonant doubling) also happen to cover common inflectional
   endings. The vendored module's own docstring frames its "Jim"/"Kim"
   example (cost 1.0) as meaningfully different, which suggested a
   threshold just under 1.0 — but 1.0 alone isn't a safe ceiling. The
   threshold (`_MAX_COST` in `names_adapter.py`) was tuned down to **0.4**,
   the highest value that still keeps every real phonetic-variant pair
   found this session (Josef Schumann/Joseph Schuman = 0.03, Muhammad/
   Mohamed = 0.22, a synthetic Titus/Tituss typo = 0.02, Yohaan/Yohan =
   0.02) while excluding the church/churches false positive. This is an
   inherent limitation of an edit-distance-family metric applied to
   morphologically rich languages, not something a threshold alone fully
   solves — expect some inflectional false positives to still surface near
   this ceiling; the human reviewer is the actual filter, per this
   adapter's own design-boundary docstring.
2. **A real, serious performance bug**: the first working version pruned
   comparison candidates by length-bucket only (only compare romanized
   forms within a couple of characters of each other in length). Measured
   directly against a synthetic ~3000-distinct-word-type vocabulary (a
   plausible single-book size): **133 seconds**. Length-bucket pruning
   alone still leaves well over a million length-compatible pairs, and
   each `string_distance_cost` call is a non-trivial DP. Fixed with
   character-bigram "blocking" (`NamesAdapter._candidate_pairs`), a
   standard approximate record-linkage technique: a real near-duplicate
   pair (1-2 edits) shares almost all of its bigrams, so requiring most
   bigrams to overlap before ever calling the expensive comparison throws
   away the overwhelming majority of unrelated pairs cheaply first.
   Measured result on the same 3000-token benchmark: **5.5 seconds** (a
   ~24x improvement). An 8000-token benchmark (worse than most single
   books) took 27.9s — still tolerable for a backgrounded preflight job
   (the same job shape already tolerates the USFM checker's 120s subprocess
   timeout), but scaling is worse than linear with the current blocking
   parameters (`_MAX_BIGRAM_MISMATCH`, `_MAX_BIGRAM_BUCKET` in
   `names_adapter.py`) — a real area for future tuning if a genuinely huge
   single-book vocabulary turns out to need it, not claimed as fully solved.
   Both benchmarks used adversarial uniformly-random letter strings (worst
   case for bigram blocking, since real language text has far more skewed
   bigram frequency); real target-language vocabulary should perform at
   least as well.

**Known, deliberately unaddressed limitations** (documented rather than
silently absent, matching this project's own established practice):
whole-book in-process comparison has no mid-flight cancellation support
(unlike the USFM checker's subprocess, which the check-job preflight can
terminate) — acceptable given the measured timings above, revisit if real
usage shows otherwise. The Devanagari-specific supplementary cost-rules
file is vendored but not loaded (see the vendor directory's `NOTICE.md`).
No UI surfaces this beyond the existing findings list — same as how the
USFM checker and versification both shipped backend/protocol-only.

**Verified**:
- `engine/greek_room_engine/tests/test_names_adapter.py` (9 tests) — real
  uroman + real vendored SED, no mocks: a planted typo gets flagged and
  anchored at its own occurrence; the real Muhammad/Mohamed cost (0.22) is
  asserted exactly, not just "some finding exists"; the church/churches
  false-positive class and the vendored module's own Jim/Kim example are
  both asserted to NOT be flagged; a bigram-blocking performance regression
  guard.
- `engine/tests/test_names_check.py` (6 tests) — protocol-level, through
  `BridgeEngine.handle_request`: a real finding surfaces via
  `verse.runChecks` with `checks: ["names"]`, is correctly absent when
  "names" isn't requested, has a stable id across a fresh `BridgeEngine`
  instance (simulating an app restart), is listed as `usingRealEngine` in
  `engine.info`, doesn't leak across a `project.open` switch to a different
  project, and — importantly, since every other test above this one only
  exercised English, where Uroman's romanization step is close to a no-op
  — a real Tamil case through full verse sentences (not isolated words):
  an inconsistently included/omitted long-a vowel sign on the same name
  ("யோவான்" vs "யோவன்") is correctly flagged, exercising
  `whitespace_tokens`' real combining-mark/punctuation handling on actual
  target-language text, not bypassing it with synthetic tokens. Bridge's
  real target languages are mostly non-Latin, so this was worth confirming
  before treating the check as done, not just a nice-to-have extra test.
- Full source suite: **137 passed** (122 before this phase + 15 new).
  `npm run check` still reports 0 errors/0 warnings (no frontend files
  touched).
- **Frozen build, verified this session** (not left as an open item like
  Wildebeest's packaging was): built both sidecars via
  `scripts/build-sidecars.ps1` against the updated
  `engine/bridge-engine.spec` (now also bundling
  `vendor/greekroom-smart-edit-distance` and uroman's data files via
  `collect_data_files('uroman')`, the same `sys._MEIPASS` extraction
  pattern versification's vendor tree already uses). Ran the real frozen
  `bridge-engine.exe` as an actual subprocess over its stdio JSON-RPC
  protocol with a real planted "Tituss"/"Titus" typo: `engine.info`
  reports `usingRealEngine: true` for the `names` adapter, and
  `verse.runChecks` returned the correct real finding
  (`original_text: "Tituss"`, `suggested_replacement: "Titus"`, cost
  `0.02`) — confirming uroman's ~4.2MB bundled data directory and the
  vendored SED tree both actually resolve correctly under `sys._MEIPASS`
  in a genuinely frozen executable, not just in source mode. This had been
  explicitly flagged as unverified in the original research breadcrumb;
  it no longer is.

### Alignment corpus statistics — Phase 6 complete (2026-08-24)

**Investigation first, same discipline as every prior phase.** "UAlign" was
an unresearched name in the roadmap, same as Uroman/SED were before Phase 5.
The first, false lead: `ualign_utilities.py` already sits vendored in two
places (`engine/vendor/greekroom-usfm/` and
`engine/vendor/greekroom-versification/greekroom/usfm/`) and looked, from
the name alone, like it might already be the statistics engine. Reading it
showed otherwise — it's a small set of generic Bible-reference/HTML utility
classes (`BibleUtilities`, `BibleRefSpan`, `ScriptDirection`, ...) already
actively imported by `usfm_check.py` and `versification.py`, not dead
weight and not UAlign itself. Its own docstring pointed at the real answer:
"utilities, taken from script `ualign.py`."

Pulling the pinned `BibleNLP/greek-room` commit's full GitHub tree (no `gh`
CLI on this machine — used the raw GitHub API and
`raw.githubusercontent.com` directly instead) found `utilities/ualign.py`:
a real, 3,598-line, unpublished script at the same pinned commit
(`18ddcf0e6c03fa2774b73b21186115d712e4cba9`) already vendored three times
for the USFM checker, versification, and Smart Edit Distance. Confirmed not
on PyPI under any plausible name and outside the published `greekroom`
package (`0.0.20`, which — per the USFM checker's own established
precedent — only ships `owl`/`gr_utilities`). Its `AlignmentModel` class
computes exactly the statistics ARCHITECTURE.md's own non-goal section
names ("local statistical recomputation — fertility, PMI, frequency"):
bilingual co-occurrence counts, per-word fertility distributions, joint
counts, and a Smart-Edit-Distance-boosted translation probability. Its own
docs page (`site/content/en/align.md`) independently confirms the same
statistic vocabulary (count, probability, joint count, phonetic/SED score)
in the context of a word-alignment *visualization* tool.

**Decision: reimplement the statistics against Bridge's own data, don't
vendor `ualign.py`.** Its actual I/O contract is built for a
`fast_align`-style pipeline — Pharaoh-format alignment files, `"e ||| f |||
ref"` triple-pipe parallel-text files, before/after ttable model files —
plus it bundles HTML visualization, morphology-variant checking, and a
spell-checker Bridge doesn't want. None of that matches tC's own
`alignmentData/<book>/<chapter>.json` shape or Bridge's in-memory
`VerseAlignment`/`TokenRef` objects. Vendoring it and subprocessing it like
`usfm_check.py` would mean synthesizing fake files in its exact expected
format just to extract a few numbers back out of HTML/log output designed
for a different UI. License-wise this also sidesteps the one real
entanglement risk `ualign.py`'s usage comment references — an external,
separately-licensed `fast_align` binary to produce an initial alignment —
since Bridge already has human-approved alignments as input and never needs
to run an aligner from scratch. The formulas below mirror `ualign.py`'s own
`AlignmentModel.support_probability()` (verified by reading that method
directly) but are original, small, textbook implementations, not copied
code — no new vendor license obligation beyond the SED tree already
vendored and licensed for Phase 5.

**A related false lead worth recording**: `tc_ai_bridge/
alignment_reliability.py` already exists and sounds on-topic, but it's
AI-link-proposal compilation (confidence thresholds, protected-group
merging for Phase 7's AI alignment suggestions), not corpus statistics —
real evidence Phase 7 already has scaffolding, and further reason to keep
this phase scoped to statistics only. That scope split (statistics this
session, AI proposals deferred to Phase 7) was decided explicitly with the
user before any code was written, matching ARCHITECTURE.md's v0.9.x
roadmap line which had bundled both under one entry.

**What was built**: `engine/tc_ai_bridge/alignment_statistics.py`
(`build_corpus_stats()`, `CorpusStatsTable`, `CorpusPairStats`) plus two new
`bridge_service.py` protocol methods, `alignment.corpusStats.summary` and
`alignment.corpusStats.forVerse`. Scans every verse marked complete — tC's
own `tools/wordAlignment/completed/<chapter>/<verse>.json` markers, the
same signal `alignment.complete` writes via `mark_word_alignment_completed`
— across the open book, plus (by default) every already-normalized sibling
book in the same multi-book collection (`.bridge/collection.json`); a
sibling still marked lazy is skipped rather than force-materialized just to
compute statistics. The scan reads only chapters that actually contain a
completed-verse marker, and reads each such chapter's alignment JSON
exactly once regardless of how many completed verses it holds — the real
cost driver is completed verses, not the project's total verse count,
which matters for a whole-Bible-sized collection where most verses are
never touched by manual alignment. `corpusStats.forVerse` returns, for
every top↔bottom link in one verse's *current* alignment groups (it does
not need to be complete itself): joint count, source/target counts,
translation probability, PMI, and — when Uroman and the vendored SED are
both available — a romanized SED cost and phonetic-boosted probability for
sparse pairs. PMI is reimplemented directly in the new module (the same
standard formula also sitting unused in vendored `ualign_utilities.py`,
not imported from it, to avoid coupling this module to
`versification.py`'s vendor-path/sys.path lifecycle for two lines of math
with no vendor-specific tuning). The SED-boost path reuses the exact same
vendored Smart Edit Distance tree and loading pattern already established
in `names_adapter.py`, plus its own separate lazy Uroman singleton — a
deliberate, documented tradeoff: sharing Uroman's singleton across the
`greek_room_engine`/`tc_ai_bridge` layers would need a real refactor of
already-shipped, tested Phase 5 code, out of scope here, so a session using
both the names check and corpus stats pays Uroman's one-time ~1.8-2.1s
table load twice rather than once.

Caching mirrors the USFM/versification/names pattern (per project path,
cleared on `project.open`) but goes one step further: it's *also*
invalidated by every alignment-mutating call (`realign`/`unalign`/`save`/
`complete`/`undo`) for the currently open book, rather than only on the
next project reopen — cheap enough (a linear scan over already-completed
verses, not a subprocess or whole-book vocabulary comparison) that keeping
it fresh on every mutation was worth it.

**Measured, not guessed, per this project's own standing rule**: a
synthetic but realistically-shaped 2,000-completed-verse corpus (50
chapters × 40 verses × 6 token pairs, comparable to a heavily-aligned large
book) scanned in well under a second of real compute — the entire pytest
process for that one test, including Python startup, was 2.42s. This is
genuinely CPU-only, zero AI/API cost: no LLM tokens, no network calls, just
counting already-known token pairs from alignment JSON already on disk
plus a few arithmetic formulas over those counts.

**Verified**: `engine/tests/test_alignment_statistics.py` (7 new tests, no
mocks) — completed-only filtering (an incomplete sibling verse is excluded),
hand-computed PMI/probability values checked against the formula directly,
multi-book aggregation with a real lazy-sibling skip, protocol-level
`summary`/`forVerse` calls through `BridgeEngine.handle_request`, cache
invalidation when a verse is newly marked complete, a real (not mocked)
Uroman + vendored-SED case (a Greek name romanizing to "Ioannes" paired
against a target spelling romanizing to "Ioanes" scores a real SED cost of
0.02 and a boosted probability at or above the plain co-occurrence
probability — and, checked separately, not every cross-script "same name"
pair clears SED's `max_cost=1` ceiling: Ἰωάννης/"Ioannes" against Tamil
யோவான்/"yoovaan" — the exact real romanization pair from Phase 5's own
investigation — scores no cost at all, handled by the None/None graceful
fallback, which is expected: SED is tuned for near-duplicate spellings, not
open transliteration variance), and the 2,000-verse performance measurement
above. Full source suite: **144 passed** (137 + 7 new), plus the one
pre-existing, load-sensitive `test_versification_concurrency.py` failure
noted at the top of this document — confirmed unrelated to this phase's
changes, reproducible on unmodified `main`.

**Frozen build, verified this session (2026-08-24)**: no new PyInstaller
`datas`/`hiddenimports` entries were needed — this module reuses the
`vendor/greekroom-smart-edit-distance` tree and `uroman` data files already
bundled for Phase 5 — but "expected to work" was checked rather than
assumed. `scripts/smoke_sidecars.py` was extended to call
`alignment.corpusStats.summary`/`forVerse` immediately after its existing
`alignment.complete` step (the fixture verse's realigned single group is
still complete at that point, before the script's own `alignment.undo`
call). Ran the real frozen `bridge-engine.exe` as an actual subprocess over
its stdio JSON-RPC protocol: `corpusStats.summary` correctly reported
`versesScanned: 1`, and `corpusStats.forVerse` returned a real
`jointCount: 1`/`translationProbability: 1.0` pair for the completed
verse's own link. `bridge-engine.spec` needed no changes for this.

**Not done in this pass**: no UI surfaces this yet (no reliability
color-coding in the alignment editor, no corpus-stats panel) — matching how
the USFM checker, versification, and the names check all shipped their
first pass backend/protocol-only. No QaFinding output — this phase was
scoped to data only, per the explicit choice made with the user; a future
phase could flag statistically-outlier links in already-completed
alignments, the same way Phase 5's names check flags outlier spellings, but
that needs its own threshold-tuning investigation against real data, the
same way Phase 5's 0.4 cost ceiling was tuned rather than guessed. All
testing so far — this phase and every prior one — uses small, hand-written
synthetic fixtures (a handful of made-up words per test), not a real
published translation at any real scale (e.g. a real Tamil IRV-sized
corpus); real tools (Uroman, SED) have been verified against real
individual words/names, but never against a large real corpus's actual
statistical distribution. That's a real gap worth closing before trusting
these statistics' *usefulness* (as opposed to their correctness) on an
actual translation project, not yet attempted.

### AI alignment proposals and drag-and-drop import — Phase 7, part 1 (2026-08-24)

A prior session's investigation (recorded in the previous revision of this
section) found that `tc_ai_bridge/ai_client.py`'s `propose_alignment()` and
`tc_ai_bridge/alignment_reliability.py`'s `compile_link_proposal()` were
already real, complete implementations from Phases 1-3 — deterministic
confidence thresholds, protected/locked existing-group handling, connected-
component group compilation — with **zero test coverage anywhere in the repo**
and no protocol method calling either one. This session verified that was
still true (`grep -rl "OpenAIResponsesClient\|compile_link_proposal"
--include=*.py` outside `tc_ai_bridge/` matched only `bridge_service.py`'s
unrelated `structural_issues` import), then wired and tested it, and
separately wired drag-and-drop import. The user was asked explicitly which
Phase 7 slice(s) to prioritize (see the AskUserQuestion in this session);
AI explain and the live Paratext/Logos connectors were deliberately not
attempted — see their own subsections below for the real, confirmed
blockers.

**AI alignment proposals — new protocol methods, `alignment.aiPropose` and
`alignment.aiApplyProposal`, in `bridge_service.py`.** Deliberately two
separate calls, not one: `aiPropose` is read-only (asks AI for individual
token links, then `compile_link_proposal` compiles them deterministically
into legal tC groups) and writes nothing to project files; `aiApplyProposal`
is a separate, explicit, human-triggered step. This keeps AI alignment on
the same "nothing auto-applies without human approval" side of
`docs/ARCHITECTURE.md`'s three-way design boundary as every other Greek
Room/AI feature in Bridge.

- `BridgeEngine.__init__` gained an `ai_transport: Optional[Transport] = None`
  parameter — the same `Callable[[url, headers, body, timeout], (status,
  bytes)]` shape `ai_client.OpenAIResponsesClient` already accepted,
  threaded one level up so `propose_ai_alignment()` can be unit-tested with
  a fake HTTP transport instead of a real OpenAI-compatible API key. This is
  exactly the dependency-injection pattern the previous session's
  investigation flagged as the way to test this without live network
  access. Production code paths still pass `None`, meaning "use the real
  network" (`ai_client.default_transport`).
- `apply_ai_alignment_proposal()` reuses the *exact* identity-checked save
  pipeline manual realign/save already goes through (`_save_alignment`,
  including `validate_preparation_proposal`'s defense-in-depth check that an
  AI proposal cannot detach/remap an already-established group, on top of
  `compile_link_proposal`'s own protection) — an AI-sourced edit gets no
  more trust than a manual one.
- `propose_ai_alignment()`'s returned `proposal` object keeps
  `compile_link_proposal`'s own snake_case field names
  (`top_ids`/`bottom_ids`/`requires_human_review`/...) verbatim, breaking
  this file's usual camelCase protocol convention on purpose: the object
  must round-trip byte-for-byte from `aiPropose`'s response back into
  `aiApplyProposal`'s request body, which calls `alignment_engine.
  apply_proposal()` expecting those exact keys. Re-keying it in either
  direction would risk a lossy/asymmetric conversion for no real benefit,
  since the frontend only needs to read `top_ids`/`bottom_ids` generically
  to resolve token labels — the same way `AlignmentModal.svelte` already
  does for ordinary alignment groups. See the comment at the return
  statement in `propose_ai_alignment()` for the same rationale inline.
- `settings.record_ai_usage()` (`tc_ai_bridge/secret_store.py`) was itself
  real, already-implemented, dead code before this session — nothing called
  it, confirmed by grepping the whole `engine/` tree. `alignment.aiPropose`
  is now its first real caller, so `settings.get`'s `aiUsage` total actually
  accumulates real token/cost data instead of always reading zero.
- Rust: `alignment_ai_propose`/`alignment_ai_apply_proposal` commands added
  to `commands.rs` and registered in `main.rs`'s `generate_handler!`, the
  same thin-wrapper shape as every other alignment command.
  `sidecar.rs`'s per-method timeout table gained
  `"alignment.aiPropose" => 260` — `ai_client.py`'s own HTTP timeout is 240s
  with retries, so the default 30s interactive timeout would have made the
  UI report "timed out" while the sidecar was still legitimately waiting on
  a real model call. This one call is a direct blocking request (like
  `verse.runChecks`'s existing 150s), not routed through the `checks.start`
  background-job system — consistent with that method's own precedent for a
  single-verse operation, and simpler than building job-tracking for what
  is, from the UI's perspective, one blocking button press.
- Frontend: `AlignmentModal.svelte` gained an "Ask AI to propose alignment"
  button next to the existing manual align/unalign controls, and a
  preview panel for the returned proposal — shows only the non-`existing`
  groups (what would actually change), a `requires_human_review` warning
  banner summarizing conflict/uncertain-link/target-only counts when
  present, and explicit "Apply proposal & save" / "Discard proposal"
  buttons. Applying reuses the same `refreshChecks()` path (re-run
  local+Greek Room checks, update stores) every other alignment mutation in
  this component already uses. `bridgeClient.ts` gained
  `aiProposeAlignment`/`aiApplyAlignmentProposal`, and `types/finding.ts`
  gained `AlignmentAiProposal`/`AlignmentAiProposeResponse` (documented
  inline with the same snake_case rationale as above).

**Verified**: `engine/tests/test_ai_alignment_propose.py` (4 new tests, real
`compile_link_proposal`/`apply_proposal` logic exercised through
`BridgeEngine.handle_request` with a fake transport, no mocks of Bridge's
own code) — `alignment.aiPropose` fails with a clear `ai_error` when no API
key is configured; a real accepted link compiles into a new group while the
existing protected group survives untouched, and `settings.
get_ai_usage_totals()` reflects the call; a cross-link between two different
already-established groups is correctly rejected as a
`protected_alignment_conflict` (not applied, `requires_human_review: true`)
rather than silently merging two independent human decisions; and
`alignment.aiApplyProposal` saves a proposal through the normal
identity-checked pipeline, filling the previously-empty word bank and
empty-bottom group. One real fixture bug found while writing these: the
project's existing test fixtures for alignment data always include
`"type": "bottomWord"` on every bottom-side token because
`TokenRef.to_dict(bottom=True)` always adds it — a first draft of this
session's fixture helper omitted it, which made `alignment.aiApplyProposal`
spuriously report "changed on disk" (the raw-file identity check in
`save_verse_alignment` compares byte-for-byte against `expectedOriginal`,
which came from a real `to_dict()` call that *does* include `type`). Fixed
in the test fixture, not in product code — this is a pre-existing,
already-correct on-disk data contract this session hadn't matched yet, not
a Bridge bug. Full source suite: 148 passed (144 + 4 new), plus the one
pre-existing, load-sensitive `test_versification_concurrency.py` failure
noted at the top of this document (confirmed unrelated, reproduced again
this session under background load). `npm run check` (0 errors/0 warnings)
and `npm run build` (succeeds, same pre-existing chunk-size warning) both
still pass. `cargo check` succeeds.

**Not done in this pass**: not click-tested in a running Tauri window (no
sidecar binary was built this session — same build constraint noted
elsewhere in this document). `mode: "audit"` is wired end-to-end on the
backend and typed on the frontend but the UI only ever requests
`"gap_fill"` — `compile_link_proposal`'s own docstring frames `audit` as a
read-only whole-verse comparison "not meant to be applied directly", and
`aiApplyAlignmentProposal`'s `validate_preparation_proposal` call correctly
rejects an audit-mode proposal that would detach an established group, but
no UI surfaces an audit-only read-only comparison view yet. AI usage
totals accumulate in `settings.json` but are still not displayed anywhere
in `SettingsModal.svelte` — `get_ai_usage_totals()`'s data has been real
since this phase but remains invisible to the user; a small, separate UI
gap worth closing later.

**Drag-and-drop import — `bridgeClient.ts` gained `onFileDrop()`**, using
Tauri v2's native OS drag-and-drop (`getCurrentWebview().onDragDropEvent`,
confirmed against the installed `node_modules/@tauri-apps/api/webview.d.ts`
rather than assumed from memory — its `DragDropEvent` union is
`{type:'enter'|'over'|'drop', paths, position} | {type:'leave'}`), kept
behind the same "only `bridgeClient.ts` imports `@tauri-apps/api`" rule the
file's own header comment already states. `ImportScreen.svelte` listens in
`onMount`/unlistens in `onDestroy`, reuses the exact same `inspect(path)`
function the existing file/folder pickers already call (so drag-drop gets
every validation/preview/warning path the picker flow already has, free),
shows a dashed drop-target highlight only while a drag is over the initial
picker screen (not during import-review, where a drop is intentionally
ignored — dropping a second source while reviewing the first would be
confusing, matching how the existing "Choose another source" flow requires
an explicit reset first), and rejects a multi-path drop with a clear error
instead of silently importing only the first path and discarding the rest.
No Rust/`tauri.conf.json` change was needed — Tauri v2's window-level
`dragDropEnabled` defaults to `true` and nothing in `tauri.conf.json` turns
it off (checked, not assumed). **Not click-tested in a running Tauri
window** in this session (same build constraint as above) — `npm run
check`/`npm run build` verify the code compiles and type-checks, not that
a real OS-level file drag actually reaches the webview and imports
correctly; worth a real click-through (drag a `.usfm` file, then a
multi-book folder, onto the window) before treating this as fully verified.

### Paratext/Logos connectors and AI explain — Phase 7 continued (2026-08-24)

Picked up immediately after part 1 above, in the same session, on the user's
explicit "go ahead on all counts on a best-effort basis" instruction — with
the honest caveat given back at the time: two of these three slices
fundamentally need a live external application (Paratext, Logos) this
machine either didn't have running or didn't have installed at all, so
"best effort" here means real, compiling, protocol-correct code that has
never been exercised against the real external app. Every such gap is
flagged explicitly below and in the new files' own README/header comments —
never silently presented as more verified than it is.

**translationWordsLinks resource-layout bug — found and fixed first, because
AI explain depends on it.** `knowledge_base.py`'s `twl_occurrences()` reads
`translationWordsLinks/<version>/{kt,names,other}/groups/<book>/<term>.json`
— a *resource-level* layout, keyed by category and term — but
`resource_materializer.materialize_translation_words()` only ever wrote the
*project-level* check-index shape
(`.apps/translationCore/index/translationWords/<book>/<group>.json`),
confirmed by reading both functions directly, not assumed from the earlier
research breadcrumb. Fixed with a new function,
`materialize_translation_words_links_index()`, that parses the exact same
bundled `twl_<BOOK>.tsv` a second time (no shared-parsing risk with the
already-tested project-level writer) into the resource-level shape,
called from `materialize_book_checks()` alongside the two existing
materializers. Verified with 3 new tests, including one that calls
`TranslationHelpsKnowledgeBase.twl_occurrences()` directly and confirms it
now returns real data — not just "the files got written."

**translationAcademy — bundled for the first time, and its own real reading
bug found and fixed.** Two real gaps stacked here, found only by actually
downloading and inspecting the content, the same way every other resource
gap in this project has been found:

1. `ensure_resources_installed()`'s resource list was
   `('translationNotes', 'translationWordsLinks', 'translationWords')` —
   `translationAcademy` was never in it, so even after bundling real content
   under `engine/resources/`, nothing would ever copy it into application
   storage. Fixed by adding it to that tuple.
2. The real content itself: downloaded the actual
   `git.door43.org/unfoldingWord/en_ta` repository at tag `v90` (the same
   tag already used for tN/TW/TWL — confirmed to exist via that Gitea
   instance's own API, not GitHub; `unfoldingWord/en_ta` and
   `unfoldingWord/en_tn` both 404 on api.github.com, confirming this
   content was never on GitHub proper for either resource, and the earlier
   P0 bundling pass's own "Door43" references meant the Gitea instance all
   along) — a real 2.2MB, 728-file, CC BY-SA 4.0 archive, not a synthetic
   fixture. Extracting and inspecting it directly showed
   `knowledge_base.py`'s `_find_article()`/`global_checking_evidence()` were
   both written for a **flat** `"<identifier>.md"` file shape — correct for
   translationWords (confirmed by the earlier, already-passing P0
   acceptance tests) but wrong for translationAcademy, whose real articles
   are **directories** (`checking/accuracy-check/{title.md, sub-title.md,
   01.md}`). This is the same bug *class* every vendored/bundled
   integration in this project has hit — an assumption written before real
   content existed to check it against — just newly found in
   `knowledge_base.py` instead of a vendored tool. Fixed with a dedicated
   `_find_ta_article_dirs()` (left `_find_article()` itself untouched, since
   translationWords' flat-file use of it is correct and already tested) plus
   updated `ta_articles()`/`global_checking_evidence()` to read `01.md` for
   body content and `title.md` for a real human-readable title instead of
   using the raw `"01"` filename stem. Verified with 4 new tests against the
   real downloaded content, including all 13 of `global_checking_evidence()`'s
   hardcoded checking-category identifiers confirmed as real, existing
   slugs (not guessed).

**`ai.explain` — new protocol method wiring `ai_client.OpenAIResponsesClient
.prepare_verse_review()`**, itself real, complete, already-implemented code
from Phases 1-3 that had zero protocol wiring and zero test coverage before
this pass (same shape of gap as `alignment.aiPropose`'s scaffolding in part
1 above). Read-only — nothing is written to project files; the human
reviewer sees AI's evidence-backed check-review preparation and whole-verse
QA as something to confirm or reject, same "AI says what it may mean, human
decides" boundary as everywhere else in Bridge. Verified with 2 tests using
the same fake-transport injection seam as `alignment.aiPropose`, against
*real* materialized translationNotes/translationWords evidence (a real
import + `verse.runChecks` preflight, not synthetic fixtures) — the fake AI
response's `check_reviews` are built from checkIds discovered from the real
project data, not guessed, so the test genuinely exercises
`prepare_verse_review`'s "every supplied check must come back or the model
response is rejected" validation. `bridge-engine.spec` needed no new
`datas`/`hiddenimports` entries (this reuses the `resources` tree, now
including translationAcademy, already bundled wholesale). Frozen build
verified via an extended `scripts/smoke_sidecars.py`: since that fixture
project has no application-storage `resources/` folder of its own, `ai
.explain` legitimately hits `knowledge_base_error` before `ai_client.py`'s
own missing-API-key check ever runs — the smoke test accepts either clean
error code, since both prove the bundle (imports, and now translationAcademy
data) is genuinely intact rather than crashing.

**Frontend**: `ReviewPanel.svelte` gained a "🤖 Explain with AI" button and
a results section (summary, per-check verdict/rationale/suggested
correction, whole-verse QA issues) — deliberately no new evidence-browser
UI; check reviews and issues render with the same finding-card visual
language the rest of the panel already uses. `bridgeClient.ts` gained
`aiExplainVerse()`; `types/finding.ts` gained `AiExplainResult`/
`AiCheckReview`/`AiQaIssue` (documented inline with the same snake_case
wire-shape rationale as `AlignmentAiProposal` in part 1 — these mirror
`AICheckReview.to_dict()`/`QAIssue.to_dict()`'s real Python output verbatim,
since it's read-only display data with no round-trip requirement to get
"wrong" the way the alignment proposal has, but declaring the true shape
still beats a silently-incorrect camelCase guess).

**Paratext companion plugin — the real, previously-missing artifact now
exists.** `paratext_connector.py`'s `ParatextConnectorClient` only ever
talked to a companion plugin over a named pipe
(`\\.\pipe\translationCoreAIBridge`) that did not exist anywhere in this
repo; building one had been flagged as "a different technology stack, a
genuinely separate undertaking" by the investigation earlier this session.
It turned out to be more tractable than that framing suggested, once
actually investigated rather than assumed:

- The real Paratext plugin interface DLLs
  (`PluginInterfaces.dll`/`CorePluginInterfaces.dll`/
  `EmbeddedUiPluginInterfaces.dll`) are already installed locally at
  `C:\Program Files\Paratext 9`. Reflecting into them directly (PowerShell's
  `[System.Reflection.Assembly]::LoadFrom` + `GetTypes()`/`GetMethods()`,
  not documentation) gave the real interface surface: `IPluginHost
  .add_VerseRefChanged(ReferenceChangedHandler)`,
  `SetReferenceForSyncGroup(IVerseRef, SyncReferenceGroup)`, `IVerseRef`,
  `IParatextChildState`, `IProject`/`IReadOnlyProject`, and
  `ParatextInternal.IParatextPlugin` (the real, if oddly-namespaced, base
  interface every plugin implements) — everything
  `tc_ai_bridge/navigation.py`'s `NavigationBroker` design already needs.
- No Visual Studio, modern .NET SDK, or NuGet install was needed: the C#
  compiler bundled with Windows' own .NET Framework
  (`csc.exe`) compiles directly against those installed DLLs plus
  `System.Web.Extensions.dll` (bundled, provides `JavaScriptSerializer` for
  JSON with no external dependency) and `netstandard.dll` (also already
  present — the plugin interfaces are themselves built against
  netstandard2.0, discovered from the compiler's own first-attempt `CS0012`
  errors, not assumed).
- The real plugin *deployment* mechanism was confirmed from Paratext's own
  official demo-plugins wiki (`ubsicap/paratext_demo_plugins`, fetched
  directly via `raw.githubusercontent.com`, not assumed): a compiled DLL
  renamed to `.ptxplg`, copied into
  `C:\Program Files\Paratext 9\plugins\{PluginFolder}\` while Paratext is
  closed. No marketplace registration or signing is required for local
  development use.
- New code: `paratext_plugin/TranslationCoreAIBridgePlugin.cs` — implements
  `get_state` (reads the active window's verse reference/project/sync
  group) and `set_reference` (calls `SetReferenceForSyncGroup`) over the
  exact newline-delimited JSON protocol `paratext_connector.py`'s
  `_exchange()` already speaks. **`create_note` is deliberately NOT
  implemented** — it returns a clear "not implemented" error — because
  Bridge already has a complete, working Paratext Notes 1.1 XML writer
  (`tc_ai_bridge/paratext_notes.py`) that writes notes directly to disk
  without needing the plugin at all; a live `AddNote()` call would need an
  `IWriteLock`/`IScriptureTextSelection`/`CommentParagraph` this session had
  no way to construct or verify against a real running Paratext instance.
- **What's verified**: the plugin compiles cleanly (`paratext_plugin
  /build.ps1`) against the real reflected interfaces. **What's not**:
  it has never been loaded by a running Paratext instance. Deploying it
  requires writing into `C:\Program Files\Paratext 9\plugins\...`, a
  protected system directory — this session's own safety controls correctly
  blocked that write rather than silently proceeding. See
  `paratext_plugin/README.md` for the exact remaining steps (close
  Paratext, run `build.ps1 -Deploy` elevated, check
  `%LOCALAPPDATA%\Paratext95\ParatextLog.log` for the plugin loading).

**Logos bridge script — the real, previously-missing artifact now exists,
with its own genuinely-tested process wiring.**
`logos_connector.py`'s `LogosConnectorClient` spawns
`logos_connector/logos_bridge.ps1` as a persistent `-STA` PowerShell helper
and talks to it over its own stdin/stdout — that script did not exist
anywhere in the repo before this pass, and Logos is not installed on this
machine (the user is installing it; a colleague with a working Logos
install will do the real functional testing).

- The real COM API surface (type library `Logos4Lib`, GUID
  `{81490292-5570-4D02-A2AC-7B828DBD0A8A}`; `new LogosLauncher().Application`;
  `LogosApplication.ApiVersion/.Activate()/.Exit()/.ExecuteUri()/
  .CreateNavigationRequest()/.Navigate(request)/.DataTypes.LoadReference()/
  .GetDataType()`; `PanelActivated`/`PanelChanged`/`PanelOpened`/
  `PanelClosed`/`Exiting` events) was pulled from `LogosBible
  /Logos4ComApiDemo`'s actual `.cs`/`.csproj` source, fetched directly from
  `raw.githubusercontent.com` (the wiki page itself 403'd), the same
  standard this project applies to every other integration.
- **Two things are genuinely unverified and flagged inline in the script's
  own header** (the most likely things to need a real fix once tested
  against live Logos): the exact COM ProgID string
  (`"Logos4Lib.LogosLauncher"` follows the standard `tlbimp` naming
  convention but was never seen registered for real — `Get-LogosLauncher`
  searches the registry for a plausible alternative and reports it if the
  literal string fails), and reading the *currently active panel's*
  reference (`Get-CurrentReferenceInfo`'s `$app.ActivePanel` guess) — the
  official demo only shows *pushing* a reference via `Navigate()`, never
  reading one back, so there was no real source to confirm this against.
  Both paths are wrapped in defensive `try`/`catch` so a wrong guess
  degrades to an empty/error response rather than crashing the helper.
- No live COM event push is attempted — a plain PowerShell script has no
  message loop to reliably pump COM callbacks, and `navigation.py`'s
  `NavigationBroker` is already designed around a *polling* connector
  (its echo-suppression/settling-window logic exists specifically to make
  repeated polling safe), so a poll-only helper matches the existing
  design rather than falling short of it.
- **What's genuinely verified, real subprocess-level testing, not just
  syntax-checking**: `engine/tests/test_logos_connector.py` (4 tests) proves
  `LogosConnectorClient` actually spawns this exact script in `-STA` mode,
  exchanges real newline-delimited JSON, and a real "Logos isn't installed"
  COM failure round-trips as a clean `LogosConnectorError` — not a hang, not
  a malformed-response error. A real bug was found and fixed this way: the
  first draft double-printed the `close` action's response (an inline
  `WriteLine` inside the request-dispatch `switch` *and* the general
  response-write path after it) — caught by actually running the script
  with real stdin input, not by reading the code.

**Python-side connector protocol wiring — deliberately scoped to direct
pass-through, not full automatic live sync.** New methods:
`paratext.getState`/`paratext.setReference`,
`logos.getState`/`logos.setReference`. `BridgeEngine` caches one
`LogosConnectorClient` instance per process (unlike Paratext's stateless
per-call named-pipe open, spawning a fresh `-STA` PowerShell process on
every poll would be far too slow — real measured cold-start well over a
second), registered with `atexit` for best-effort clean shutdown (a known,
documented limitation: `atexit` does not run on a hard kill, e.g. Tauri
force-terminating the sidecar — see `logos_connector/README.md`). This
deliberately does **not** wire `navigation.py`'s
`NavigationBroker`/`NavigationOwnership` into an automatic background
polling loop yet — that's a real, separate UX design (conflict handling, a
background job, a live-sync toggle) worth its own pass once these two
connectors have been proven against real running Paratext/Logos instances.
What's here is already useful on its own: a future "Connections" panel can
show live state and let a reviewer manually push Bridge's current verse
into either application. Verified with 4 protocol-level tests (clean error
codes for both connectors with no companion running) plus the real Logos
subprocess tests above, run again through the full `BridgeEngine
.handle_request` dispatch this time. Frozen build verified via
`scripts/smoke_sidecars.py`: `paratext.getState` fails cleanly with no
companion plugin, and `logos.getState` genuinely spawns the bundled
`logos_bridge.ps1` from under `sys._MEIPASS` (confirming a new
`bridge-engine.spec` `datas` entry — `logos_connector/`, invisible to
PyInstaller's static analysis the same way every other runtime-resolved
vendor/helper path in this project has been) and gets the real "Logos isn't
installed" COM error, not a missing-file/spawn error.

**Full source suite after this continuation**: see `docs/QA_TEST_MATRIX.md`'s
A20-A26 rows for the exact test counts and what each verifies. `npm run
check` (0 errors/0 warnings) and `npm run build` both still pass. `cargo
check` succeeds with the six new Tauri commands
(`ai_explain`/`paratext_get_state`/`paratext_set_reference`/
`logos_get_state`/`logos_set_reference`, plus the two from part 1)
registered and per-method sidecar timeouts tuned (`ai.explain` needs up to
two sequential real model calls; `logos.*` needs headroom for the helper's
slow cold start).

**Not done in this pass**: no click-through in a running Tauri window for
any of this (same build constraint as part 1 — no interactive window
automation available in this environment, confirmed by two failed
standard Windows foreground-focus tricks earlier in the session). The
Paratext plugin has never been loaded by real Paratext. The Logos bridge
script has never made a real COM call. No "Connections" panel UI exists yet
for either connector — only the protocol methods and (for Logos) the fake
`get_state`/`set_reference` failure paths are exercised. `mode: "audit"`
for `alignment.aiPropose` remains backend-only with no UI. AI usage totals
still accumulate in `settings.json` but still aren't surfaced anywhere in
`SettingsModal.svelte`.

Continue building Bridge's import workflow so users can bring in individual
USFM/SFM files, whole-Bible folders, Paratext folders, and translationCore
projects, then use the normalized data for local QA, Greek Room,
translationNotes, translationWords, and word alignment.

The import foundation described below is implemented and verified. It has since
been committed as `9ed60cb feat(import): add translationCore-compatible Scripture
imports` — the working tree is currently clean. The "Working-tree warning" section
near the end of this document is kept for historical reference (it describes what
that commit touched) but no longer describes an uncommitted state.

## What is implemented

### Backend normalization

`engine/tc_ai_bridge/project_import.py` provides two public entry points:

- `inspect_import(source_path)`: read-only detection and metadata preview.
- `import_source(source_path, destination_root, metadata)`: staged,
  non-overwriting import and normalization.

Accepted input:

- `.usfm` and `.sfm` files.
- Marker-based `.txt` Scripture files.
- Folders containing one or many Scripture books.
- Paratext-style folders with `Settings.xml`.
- Existing translationCore project folders.
- `.tcore`, `.tstudio`, and ZIP project archives.

For raw Scripture, each book becomes a translationCore-compatible book project:

```text
<project>/
  manifest.json
  <book>.usfm
  <book>/headers.json
  <book>/<chapter>.json
  .apps/translationCore/alignmentData/<book>/<chapter>.json
  .apps/translationCore/index/translationNotes/<book>/
  .apps/translationCore/index/translationWords/<book>/
  .apps/translationCore/checkData/...
  .bridge/import.json
```

Important behavior:

- Original source bytes are preserved.
- `.bridge/import.json` records SHA-256 provenance and capability status.
- Existing translationCore indexes, decisions, comments, and alignments are
  copied intact.
- Older tC/tS projects with target chapter JSON but no alignment data receive
  unaligned target word banks so `TranslationCoreProject` can open them.
- Each unaligned target token is represented once in `wordBank`, with correct
  `occurrence` and `occurrences` values.
- Nested USFM 3 `zaln`/`w` alignment milestones are converted into occurrence-aware
  translationCore 1:1, 1:many, many:1, and many:many groups.
- Malformed alignment structures are not guessed; target words remain in
  `wordBank` for review.
- Multi-book folders produce one compatible project entry per book. All source
  files are copied immediately, the first book is normalized and opened, and
  remaining books carry `.bridge/lazy-import.json` until first open. Every
  sibling has `.bridge/collection.json`, so the full selector survives restart.
- ZIP entries are validated against path traversal before extraction.
- Imports use private staging and collision suffixes instead of deleting or
  overwriting existing projects.

### Sidecar protocol

`engine/bridge_service.py` adds:

- `project.inspectImport`
- `project.import`

The project response now also supplies confirmed `targetLanguageId`,
`targetLanguageDirection`, `projectName`, and `bibleName`.

Greek Room now receives the confirmed language identifier from
`manifest.target_language.id`, rather than the display-language name. Local QA
already gets its language context from the manifest via `PluginRegistry`.

USFM verse bridges/segments such as `3-4` and `3a` no longer crash local finding
conversion. Findings use the first numeric component as their numeric anchor,
while project navigation retains the exact verse string.

### Tauri and frontend

The Tauri layer adds:

- Native import-file picker with USFM/SFM/TXT/TCORE/TSTUDIO/ZIP filters.
- Thin commands for inspection and import.
- A five-minute sidecar safety timeout remains for import, but whole-Bible raw
  import no longer relies on it: the real 66-book OV Tamil source measured
  5.17 seconds from source and 6.21 seconds through the frozen packaged sidecar
  after lazy book normalization was introduced.

`src/lib/components/ImportScreen.svelte` now provides:

- Separate file import, folder import, and open-existing-project actions.
- Read-only preview before import.
- Detected-book list, verse counts, alignment status, and warnings.
- Required Language, Project name, Bible/translation name, and text direction.
- Offline searchable ISO 639-3 catalog using `iso-639-3@3.0.1`.
- Import is disabled until the required metadata is valid.

The complete catalog adds about 94 KB gzip to the production bundle and causes
Vite's non-fatal 500 KB chunk warning. It can be split later if startup size
becomes a concern.

## Critical design boundary: tN/tW are not fabricated

Raw USFM contains Scripture, not translationNotes or translationWords checks.
translationCore first imports Scripture and later materializes tool indexes from
installed, versioned checking resources. Bridge follows that boundary.

Current behavior:

- Imported existing translationCore projects immediately expose any real tN/tW
  indexes they already contain.
- Raw imports record `requires-resource-index` for translationNotes and
  translationWords until the first background-check preflight for that book.
- Compatible index directories are created, but no fake/empty check entries are
  generated.
- Local Scripture QA, Greek Room, and word-alignment preparation work now.
- Bundled-resource acquisition and real per-book tN/tW materialization are
  implemented; online resource/version selection is still future work.

## Recommended next work

### P0 — Resource acquisition and tN/tW index materialization (done 2026-08-20)

**Approach taken:** bundle a pinned English tN/tW/TWL snapshot in the repo
(matching real translationCore's own default of shipping English checking
helps in the installer) rather than fetching on demand — Bridge's own
premise is field translation teams with unreliable connectivity, so a raw
import must produce real tN/tW checks with zero network access.

What's bundled, under `engine/resources/en/translationHelps/` (~42 MB,
committed):

- `translationNotes/v90_unfoldingWord/tn_<BOOK>.tsv` — raw Door43
  `unfoldingWord/en_tn` tag v90, 56 of 66 books.
- `translationWordsLinks/v90_unfoldingWord/twl_<BOOK>.tsv` — raw
  `unfoldingWord/en_twl` tag v90, same 56 books.
- `translationWords/v90_unfoldingWord/bible/{kt,names,other}/*.md` — raw
  `unfoldingWord/en_tw` tag v90 articles (953 files), plus each resource's
  own `manifest.yaml`/`LICENSE.md` for provenance and attribution.
- **10 Old Testament books are not currently in the upstream release**
  (Numbers, 1-2 Chronicles, Ecclesiastes, Isaiah, Jeremiah, Ezekiel, Daniel,
  Amos, Zechariah) — verified directly against the live Door43 catalog on
  2026-08-20, not a gap in this bundling pass. Re-run the same fetch against
  a newer tag later to pick up whichever of these ship next; nothing else
  needs to change.

**New code:**

- `engine/tc_ai_bridge/resource_materializer.py` — pure parser/writer.
  `ensure_resources_installed(app_resources_root)` copies the bundled
  snapshot into application-owned storage once (mirrors how `project_root`
  itself is a copy separate from the repo — `TranslationHelpsKnowledgeBase`
  resolves resources relative to a project's own path, i.e.
  `settings_root/resources/...`, never the repo). `materialize_book_checks()`
  parses the bundled TN/TWL TSVs for one book and writes real
  `.apps/translationCore/index/{translationNotes|translationWords}/<book>/<group>.json`
  entries with a full `contextId` (`reference`, `tool`, `groupId` — the TA
  slug for tN, the term slug for tW — `checkId`, `quoteString`,
  `occurrenceNote`). Always fully regenerates those files: safe, because
  Bridge's own Accept/Reject/Ignore decisions live in the project's separate
  `decisions/` companion directory (stable finding ids) and are re-applied
  onto findings after checks run — never stored inside these index files.
- `project_import.py` gained `apply_resource_materialization()`, which pins
  `tc_en_check_version_translationNotes`/`...translationWords` in
  `manifest.json` and records real `ready`/`unavailable` capability status
  (never a fabricated `ready` with zero checks) in `.bridge/import.json`.
- `bridge_service.py` prepares these indexes in the background checking
  preflight, and **only for raw USFM/SFM/Paratext imports**. Import no longer
  blocks on every book's tN/tW data. An imported existing translationCore/
  translationStudio project keeps its own real indexes untouched, per the
  tN/tW design boundary in `docs/IMPORTS.md`. tN/tW are gateway-language
  (English) checking helps applied to any target-language translation, so this
  doesn't depend on the imported project's target language.

**Verified:** `test_resource_materializer.py` (5 tests, all against the real
bundled Titus TN/TWL slice, not a synthetic fixture) — parses into the
correct `contextId` shape, is idempotent, correctly reports `unavailable`
for an unreleased book (tested with Isaiah), and an end-to-end
import→`verse.runChecks` call surfaces real `translation_note`/
`translation_word` findings. Historical suite after lazy whole-Bible import: 79/79
passing (2026-08-21).

**Still open / not done in this pass:**

- **`knowledge_base.py`'s own TWL reader is still unfed.** It expects a
  *different*, pre-materialized layout —
  `translationWordsLinks/<version>/{kt,names,other}/groups/<book>/<term>.json`
  — used only by `ai_client.py`'s evidence-gathering (the unwired Phase 7
  `ai.explain`). This pass bundled the raw TWL TSVs and materializes
  *project-level* check indexes from them directly; it does not also build
  that second, resource-level grouped-JSON shape. Needed before Phase 7 can
  gather TW evidence, not needed for `verse.runChecks`.
- **`translationAcademy` was not bundled.** Nothing on the `verse.runChecks`
  path reads it today (`local_checks.py` never imports `knowledge_base.py`);
  it's only needed for TA article evidence in the same unwired `ai.explain`
  path. `knowledge_base.py.resolve('translationAcademy')` will raise
  `KnowledgeBaseError` if something calls it before this exists — currently
  nothing on any wired protocol method does.
- **PyInstaller build needs `--add-data` to ship the bundle**, and should
  now be run from the `engine/.venv` Python 3.12 environment (see the real
  Wildebeest section above), e.g. (from `engine/`, Windows path separator
  is `;`):
  `.venv\Scripts\python.exe -m PyInstaller --onefile --name bridge-engine --add-data "resources;resources" main.py`.
  Without `--add-data`, a frozen `.exe` has no bundled tN/tW snapshot and
  every raw import falls back to `unavailable` on a machine where
  `ensure_resources_installed` has never run before (dev-mode runs are
  unaffected since `bundled_resources_source()` reads straight from
  `engine/resources`). If the real Wildebeest engine (`wildebeest-nlp`,
  installed via the `wildebeest` extra) should be in the build, also add
  `--collect-data wildebeest` — unverified insurance for its `data/`
  directory, see the real Wildebeest section above. This was not verified
  against an actual PyInstaller build in this session — no sidecar binary
  was built. Confirm the frozen `.exe` actually finds the resource bundle
  via `sys._MEIPASS`, and that Greek Room findings still say
  `usingRealEngine: true` in `engine.info`, before shipping.
- **Only English is bundled.** Non-English tN/tW (or a refreshed English
  version) still needs the online path described in the original P0 below —
  not built in this pass, since it wasn't required to satisfy the
  acceptance criteria against real data.

Original acceptance criteria (all met):

- A raw USFM import followed by resource preparation produces non-zero real
  tN/tW checks for known verses. ✓
- `verse.runChecks` returns those items as translation-note/translation-word
  findings. ✓
- Resource versions and hashes are visible in provenance (pinned
  `tc_en_check_version_*` fields; `knowledge_base.py`'s existing
  `provenance_manifest()` hashes each bundled `manifest.yaml`). ✓
- Re-running indexing is deterministic and does not erase human decisions. ✓

### P0 — Multi-book collection navigation (done 2026-08-20)

`TopBar.svelte`'s book `<select>` was previously a dead placeholder — one
hardcoded option, no `on:change`. It now lists every sibling from
`ProjectInfo.importedProjects` and calls `project.open` on selection.

Implementation notes for whoever touches this next:

- `project.open` does **not** echo back `importedProjects` (only
  `project.import` does — see `bridge_service.py`'s `_project_info()` vs
  `import_project()`). The sibling list is therefore carried forward on the
  frontend across a switch (`App.svelte`'s `switchBook()`) rather than
  re-fetched from the backend. If the app is closed and reopened, or a book is
  opened individually via "Open an existing project," the sibling list is
  gone and the selector falls back to showing just that one book — this is
  accepted as in-session-only, matching the P0 scope (switching immediately
  after import).
- `stores.ts` gained `resetBookState()`, called before switching: chapter and
  verse numbers restart at 1 in every book, so `chapterVerseNums`,
  `verseTexts`, `findingsByVerse`, and `loadedChapters` must be cleared on
  switch or the new book would show the old book's data under matching
  chapter/verse keys — the same class of bug gotcha #7 was written to avoid,
  just at the book level instead of the chapter level.
- `App.svelte` factored the "land on first chapter, load it, select first
  verse" sequence out of `handleOpened()` into `enterCurrentProject()`, shared
  by both initial open and `switchBook()`.
- Verified: `npm run check` (0 errors), `npm run build` (succeeds, same
  pre-existing chunk-size warning as before). Not exercised in a running
  Tauri window in this session — no sidecar binary was built/available to
  launch `npm run tauri dev` end-to-end. Whoever picks this up next should
  do a real click-through (import a multi-book folder, switch between books,
  confirm chapter/verse state doesn't bleed across books) before treating
  this as fully verified.

### P1 — Maintained full USFM parser

The current parser is conservative and the original source is always preserved,
but normalized extraction still uses regular expressions. Replace or augment it
with a maintained USFM parser for full marker placement, verse bridges/segments,
tables, peripheral material, and project validation. Nested alignment milestones
are supported by the current targeted parser and source-template export; retain
both behaviors during that migration.

### P1 — Direct Paratext import

Local Paratext folders are detected and `Settings.xml` is used for metadata.
Direct Scripture retrieval from Paratext/API is not wired. Keep that separate
from the existing note connector and require explicit project selection.

### P1 — Import reporting and recovery

Add an import-results screen showing all created project paths, warnings,
unaligned milestone counts, resource-index status, and a way to open any book.
For a multi-book failure, either make the whole collection atomic or clearly
report which book projects completed.

## Verification completed

From `engine/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/ greek_room_engine/tests/ -q -p no:cacheprovider
Remove-Item Env:PYTHONDONTWRITEBYTECODE
```

Result: `32 passed`.

From the repository root:

```powershell
npm run check
npm run build
```

Results:

- Svelte check: 0 errors and 0 warnings.
- Production build: successful, with only the language-catalog chunk-size
  warning described above.

From `src-tauri/`:

```powershell
cargo check
```

Result: successful.

`git diff --check` also passes; only Windows LF-to-CRLF notices are printed.

`npm install` reports seven dependency advisories (six moderate and one high).
No automatic `npm audit fix --force` was run because it can introduce breaking
dependency changes. Audit and upgrade these separately.

## Tests added

`engine/tests/test_project_import.py` covers:

- Read-only USFM preview and missing-language detection.
- Raw SFM normalization and provenance.
- Multi-book folder import.
- Basic USFM 3 alignment preservation.
- Existing tC archive check-index preservation.
- ZIP path-traversal rejection.
- End-to-end sidecar import and automatic project opening.
- Verse-bridge import and checking.

## Upstream translationCore research

The implementation was compared against:

- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/actions/Import/LocalImportWorkflowActions.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/UsfmFileConversionHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/ZipFileConversionHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/manifestHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/ProjectValidation/ProjectStructureValidationHelpers.js

Key upstream behavior confirmed:

- tC accepts USFM/SFM/TXT and TCORE/TSTUDIO files through its local file picker.
- USFM import generates a manifest, copies the source, and creates target chapter
  JSON.
- Alignment data is created when alignment milestones are present.
- Missing project/language details are handled during validation.
- Upstream translationCore rejects multiple-book projects; Bridge deliberately
  imports them as a collection of book-wise projects instead.

## Working-tree warning (historical — now committed as `9ed60cb`)

At the time this document was originally written the working tree was uncommitted;
it has since been committed. Files involved in this import work were:

- `engine/tc_ai_bridge/project_import.py` (new)
- `engine/tests/test_project_import.py` (new)
- `engine/bridge_service.py`
- `src/lib/components/ImportScreen.svelte`
- `src/lib/api/bridgeClient.ts`
- `src/lib/types/finding.ts`
- `src-tauri/src/commands.rs`
- `src-tauri/src/main.rs`
- `src-tauri/src/sidecar.rs`
- `package.json`
- `package-lock.json`
- `docs/IMPORTS.md` (new)
- `README.md`

`src-tauri/Cargo.toml` and `vite.config.ts` were also modified in the broader
working session and are part of the same commit.

## Alignment word-info lexicon popup (2026-08-26)

**What it does:** clicking the small "i" button on a source (Hebrew/Greek)
token in the Word Alignment modal opens a popup with that word's decoded
morphology and a Strong's dictionary gloss — lemma, transliteration,
pronunciation, Meaning, Usage, and Source (etymology) — the same information
translationCore's own word-details popup shows. Compound tokens (a lexeme
fused with a Hebrew proclitic prefix, e.g. the "the" in "the earth") show one
popup with a segment per morpheme rather than needing any change to how
tokens are split.

### Data source: `openscriptures/strongs`, not UHAL/UGL

The user's reference screenshot's exact phrasing ("Meaning: the 'earth'
(at large...)", "Usage: × common, country...", "Source: from an unused
root...") turned out to be verbatim classic Strong's Dictionary text, not
unfoldingWord's UHAL/UGL (which write numbered-sense prose entries — a
different shape entirely). The real match, confirmed by cloning the repo and
reading the actual data rather than trusting a description of it (same rule
as every other vendored dependency in this project): `openscriptures/strongs`
(github.com/openscriptures/strongs, commit `0acd2f251c2d35ff8db2dece4e0593979d3ac223`).
Its `hebrew/strongs-hebrew-dictionary.js` and `greek/strongs-greek-dictionary.js`
are plain CommonJS modules exporting a Strong's-number-keyed object —
`require()`-able directly from the vendoring script, no XML parsing needed.
8,674 Hebrew + 5,523 Greek entries. License: each file's own header states
"Copyright 2009/2010, Open Scriptures. CC-BY-SA" (no version number given);
the underlying 1890s Strong's Concordance text itself is public domain.

New vendor script: `scripts/vendor-strongs-lexicon.mjs`, same shape as
`vendor-original-language-resources.mjs` — takes `--checkout <path>`, verifies
the pinned commit, emits one gzipped JSON index per language under
`engine/resources/{hbo,el-x-koine}/lexicons/strongs/v1.0.2_openscriptures/`
with the same `NOTICE.md`/`PROVENANCE.json`/`index.json` convention as the
UHB/UGNT packs.

### Real data quirks found (not assumed) while wiring up lookups

- Hebrew Strong's numbers on tokens are inconsistently zero-padded (`H0430`
  vs `H7225`) and sometimes carry an OSHB-only trailing homonym letter not
  present in classic Strong's numbering (`H1254a` for ברא in Genesis 1:1).
- Greek (UGNT) Strong's numbers always carry one extra trailing "variant"
  digit beyond the 4-digit base that classic Strong's numbering doesn't have
  (`G23160` → base `G2316`).
- Compound tokens use a colon-joined `strong`/`morph` pair per morpheme
  (e.g. strong `"d:H0776"`, morph `"He,Td:Ncbsa"` for "the earth") — the
  prefix side (`b`/`c`/`d`/`k`/`l`/`m`) has no Strong's number of its own.
  Confirmed which letter means what by cross-checking ~30 real verses
  (Genesis 1-2, Psalm 119, Deuteronomy 6) against their paired morph codes,
  not guessed — see `HEBREW_PREFIX_LABELS` in `lexicon_resources.py`.

All three are handled by `_normalize_strong()`/compound-splitting in
`engine/tc_ai_bridge/lexicon_resources.py` before the dictionary lookup.

### Morphology decoding

`engine/tc_ai_bridge/morphology_codes.py` decodes the raw codes already
present on every source token into readable labels:

- **Hebrew** (`He,Ncmsa` etc.): the OpenScriptures Hebrew Bible (OSHB)
  parsing scheme, doc-verified against
  `github.com/openscriptures/morphhb/blob/master/parsing/HebrewMorphologyCodes.html`.
- **Greek** (`Gr,V,IAA3,,S,` etc.): **no locatable specification document** —
  repeated lookups against door43/GitHub for UGNT's own morphology docs found
  nothing. The mapping was instead reverse-engineered by cross-checking every
  real UGNT token in John 3:16 and Titus 1:1 (both unambiguous, well-known
  grammar) against their known parsing, field position by field position.
  Only codes actually confirmed that way are mapped; anything unrecognized
  falls back to showing the raw code rather than guessing — see the module's
  own docstring for the full reasoning.

### New protocol method: `lexicon.getEntry`

`Methods.LEXICON_GET_ENTRY = "lexicon.getEntry"` (`bridge_service.py`), takes
`{strong, morph}` off the `AlignmentToken` the frontend already has — no
`languageId` param needed; `decode_morph()` reads the `"He,"`/`"Gr,"` prefix
itself. Returns `{languageId, segments: [...]}`, one segment per
colon-separated morpheme, each with `strong`/`morphLabel`/`partOfSpeech`/
`lemma`/`translit`/`pron`/`meaning`/`usage`/`source` (all nullable — a
segment with no lexicon hit still gets its decoded morphology, and non-numeric
Hebrew prefixes get a label from `HEBREW_PREFIX_LABELS` instead). Wired
straight through: `commands.rs`'s `lexicon_get_entry` → `main.rs` invoke list
→ `bridgeClient.ts`'s `getLexiconEntry()` → new `LexiconPopup.svelte`.

### Two real bugs found and fixed in the same pass

**1. A genuine regression, caught from the user's live bug report, not from
a test.** The first version of this work also added a copy step to
`resource_materializer.py`'s `ensure_resources_installed()`, mirroring the
existing UHB/UGNT copy loop, to make the new lexicon's license/provenance
discoverable in app storage. After shipping it, opening a KJV Genesis project
threw `sidecar request 'checks.status' timed out` and `check.listForVerse`
timed out too. Root cause, traced end to end (not guessed):
`materialize_book_checks()` — which parses Genesis's entire English tN/tW
TSVs (5,758 + 5,640 checks, 442 file writes) — already ran synchronously
inside a `with self._checker_lock:` block on a background thread, and was
**already** taking ~15-19s cold (confirmed by `git stash`-ing just the
`resource_materializer.py` change and re-timing: 18.9s baseline vs. 26.2s
with the added copy step). `checks.status`/`check.listForVerse` are
hard-coded to a 30s timeout specifically so they *never* wait on that lock
(see `sidecar.rs`'s `interactive_check_requests_keep_the_short_timeout`
test and `list_checks_for_verse()`'s non-blocking lock acquire) — but with
one Python process and the GIL, sustained CPU/IO-heavy work on the
background job thread can still starve the main stdio dispatcher's ability
to read and answer the next request in time. The added copy step (~7s more)
was enough to tip an already-borderline first-time cost over that 30s
budget. **Fix:** removed the copy step entirely — it turned out to be
unnecessary anyway, since `lexicon_resources.py` always reads straight from
the bundled/source resources directory (same pattern as
`original_language_resources.py`), never from the app-storage copy. Re-timed
after the fix: back to ~15-17s, matching the pre-existing baseline.

**2. A CSS bug, then a second CSS bug it exposed.** The user reported the
popup had an unwanted horizontal scrollbar. Cause: `LexiconPopup.svelte`'s
`<dl>` grid and the header's `<span class="headword">` are flex/grid items
that default to `min-width: auto`, which for an unbreakable Hebrew word (no
spaces to wrap on) means "don't shrink below this word's full width" — wider
content pushed the whole 440px popup wider, so `overflow: auto` added a
horizontal scrollbar to compensate. Fixed with `min-width: 0` +
`overflow-wrap: anywhere` on the grid/flex items, `minmax(0, 1fr)` on the
grid track, and `overflow-x: hidden` on the popup itself. That fix then
exposed a **second, latent** bug: the header's `"WORD DETAILS"` eyebrow used
`flex: 0 0 100%` to force itself onto its own row, but `header` never
actually had `flex-wrap: wrap` — it had only ever *looked* like two rows
because the resulting horizontal overflow was visible. Once overflow was
clipped instead of scrolled, the eyebrow's now-enforced full-width claim
squeezed the headword down to near-zero width (rendering one Hebrew letter
per line) and pushed the close button out of the visible/clickable area.
Real fix: add `flex-wrap: wrap` to `header` so the eyebrow genuinely wraps to
its own row, leaving the second row's full width for the headword and close
button.

### Files touched

New: `scripts/vendor-strongs-lexicon.mjs`,
`engine/tc_ai_bridge/lexicon_resources.py`,
`engine/tc_ai_bridge/morphology_codes.py`,
`engine/tests/test_lexicon_resources.py`,
`engine/tests/test_morphology_codes.py`,
`src/lib/components/LexiconPopup.svelte`,
`engine/resources/{hbo,el-x-koine}/lexicons/strongs/v1.0.2_openscriptures/`
(vendored data + NOTICE.md/PROVENANCE.json/index.json).

Modified: `engine/bridge_service.py` (new method + dispatch branch),
`engine/tc_ai_bridge/resource_materializer.py` (net no-op after the fix above
— comment explains why the lexicon is deliberately *not* mirrored into app
storage), `engine/tests/test_bridge_service.py`,
`src-tauri/src/commands.rs`, `src-tauri/src/main.rs`,
`src/lib/api/bridgeClient.ts`, `src/lib/types/finding.ts`,
`src/lib/components/AlignmentModal.svelte` (per-token info button, wired to
the popup; existing selection behavior untouched).

### Verified

- `pytest tests/ greek_room_engine/tests/ -q` — 240 passed, no regressions;
  new lexicon/morphology tests cross-check decoder output against real
  vendored data (Genesis 1:1, Titus 1:1, John 3:16), not synthetic fixtures.
- `npm run check` — 0 errors, 0 warnings. `npm run build` — succeeds.
- **Not verified:** `cargo check`/`cargo tauri dev` — this checkout has no
  built sidecar binaries (`build-sidecars.ps1` not yet run this session), a
  pre-existing environment gap unrelated to this work. The new Rust command
  is a direct structural copy of the existing `alignment_get` command.

### Still open

- The pre-existing ~15-19s synchronous first-time cost of
  `materialize_book_checks()` for a large book (confirmed independent of
  this work, see bug #1 above) is close enough to the 30s
  `checks.status`/`check.listForVerse` timeout that it can plausibly still
  time out occasionally on a slower disk, with no lexicon-popup code
  involved at all. The code's own comments describe the intended design as
  never blocking the dispatcher this way; worth a dedicated pass — likely
  moving `_ensure_resource_indexes()` off any synchronous call path
  (`run_verse_checks`, `saveEdit`'s `["local", "greekroom"]` call) the same
  way `list_checks_for_verse()` already avoids blocking.
- `LexiconPopup.svelte` has no client-side caching — refetches on every open.
  Fine given the tiny payload and Python-side `lru_cache`; revisit only if
  it's ever visibly slow.
- Greek morphology decoding covers every code actually observed in testing,
  not necessarily every code that exists in UGNT — unrecognized codes fall
  back to the raw string rather than a wrong label, by design.

## Stage 3 semantic passage mapping merge (2026-08-28)

Merged the Stage 3 builder-handoff package (6 new `tc_ai_bridge` modules,
`models.py`/`ai_client.py`/`bridge_service.py` integration, Svelte review-UI
changes, regression tests) per `patches/BETA14_STAGE3_CHECKLIST.md`. Stage 3
locates where a source tN/tW meaning is actually realized across a target
passage — including when the target moved it to a different verse — instead
of assuming every check's meaning stays verse-local, and gates unsafe
verse-local application of a mapping it can't ground with high confidence.

### Two real bugs found only by running the merged code, not by reading the patch

1. **Silent no-op on any per-unit mapping failure.**
   `semantic_mapping_bridge.prepare_semantic_mappings_for_review`'s
   `except Exception` handler on a `map_units` failure returned
   `checkStates: anchor_unresolved` — correct for anchor-lookup failures
   discovered *before* `map_units` runs, but anchor_unresolved is empty for
   units that were found and only failed *later* (e.g. the model's proposed
   target span didn't validate). Every check in that batch — not just the
   one that triggered the exception — silently reverted to identical-looking
   non-Stage-3 review with zero visible signal anything went wrong,
   defeating the fail-closed design's whole point (surfaced review, not
   silent bypass). Confirmed live: opening PHP 1:3 in a real Hindi IRV
   project produced no semantic-mapping card at all; the saved AI review's
   `semanticMapping.diagnostic` on disk (`.apps/translationCoreAI/aiReview/
   php/1/3.json`) showed the mapping attempt had actually failed. Fixed by
   populating one `mapping_error` check-state entry per unit in that except
   block, and adding the missing `mapping_error` branch to the Svelte
   semantic-map-card (the original patch's card only handled the other six
   states).
2. **Model-supplied target-span offsets are untrustworthy for non-Latin
   scripts.** `semantic_mapping.py`'s span validator hard-rejected a mapping
   whenever `seg_text[start:end] != quote` for model-supplied integer
   offsets — and the prompt never tells the model what indexing convention
   `start`/`end` use in the first place. This is exactly the failure
   observed for the Hindi case above (`"Target quote/offset mismatch ...
   hallucinated or normalized text rejected"`) — LLMs are unreliable at
   counting exact character offsets in complex/non-Latin scripts (Devanagari
   conjuncts/matras and similar), independent of whether the quoted text
   itself was genuine. Fixed by never trusting model-supplied offsets:
   always re-derive the span via exact literal-text search
   (`_literal_positions`), requiring the quote occur exactly once,
   unambiguously, in the target segment. This keeps the real
   anti-hallucination guarantee (the quoted text must genuinely be present)
   while removing a source of false-positive rejections that had nothing to
   do with hallucination.

### Also found: test-suite-wide isolation gap

`default_semantic_source_db_path()`'s dev-mode fallback resolves relative to
the checked-out source tree (`Path(__file__).resolve().parent.parent /
'resources' / ...`), so *any* test running `prepare_verse_review` from
source — not just Stage 3's own tests — silently picked up the real,
installed production DB and exercised genuine Stage 3 review policy. This
broke 5 pre-existing `test_ai_explain.py` tests that predate Stage 3 and
assume plain review behavior. Fixed at the root: `engine/conftest.py`'s
autouse `isolate_bridge_app_data` fixture now also sets
`BRIDGE_SEMANTIC_SOURCE_DB` to a path that can't exist, so Stage 3 defaults
to `state: "unavailable"` for the whole suite. `test_semantic_mapping_stage3.py`
constructs its DB path explicitly and is unaffected.

### Known gap, not yet fixed

`openSemanticSpan` in `TranslationHelpsReview.svelte` (click a mapped target
span to jump to it) only navigates — it sets `currentChapter`/`selectedVerse`
but does not highlight the `start:end` span. There's no existing mechanism in
this app to highlight an arbitrary span from outside a verse's own
finding-based highlighting (`utils/highlight.ts` `buildSegments`); that needs
new plumbing through `ReviewPanel.svelte`/the verse editor, deliberately
deferred as a follow-up.

### The production DB is not committed

`engine/resources/semantic_mapping/*.sqlite` (~120MB) is gitignored — it's
over GitHub's 100MB single-file push limit and this repo doesn't use Git
LFS. See `docs/DEVELOPER_SETUP.md`'s "Stage 3 semantic mapping DB" section
for how a teammate installs it locally via
`scripts/install_stage3_files.py` from the builder-handoff package.

### Verified

- `pytest engine/tests -q` — 269 passed, against the real full production DB
  installed locally (not just the regression-scope one).
- `npm run check` — 0 errors, 0 warnings. `npm run build` — succeeds.
  `npm run test:ui-state` — 4/4 pass.
- Frozen sidecar smoke test (`scripts/smoke_sidecars.py`) passes after
  rebuilding with `build-sidecars.ps1`.
- Live desktop app (`npm run tauri dev`), real Hindi IRV Philippians
  project, PHP 1:3 — this is what surfaced both bugs above; not caught by
  the test suite alone.

### Still open

- The navigation-only `openSemanticSpan` gap above.
- `prepare_verse_review` now computes the semantic-mapping pack
  unconditionally on every verse review (not only when alignment is
  incomplete) — one extra AI request per verse review, cached per
  passage-fingerprint so re-opening an unchanged passage is a cache hit.
  Worth watching real-world cost/latency impact.

## Brokered Paratext/Logos verse navigation (2026-09-03)

Bridge now has opt-in two-way verse navigation for Paratext and Logos. The existing connector
clients and `NavigationBroker`/`NavigationOwnership` are wired through
`navigation.status/poll/bridgeChanged/resolve`; Svelte polls cached state and explicitly accepts
or rejects each external candidate after verifying the destination exists in the open collection.
Bridge-originated changes go to every enabled connector, while a Paratext- or Logos-originated
change is forwarded only to the other connector after Bridge loads it.

Connector calls run in one bounded daemon probe rather than the synchronous stdio dispatcher.
Unavailable applications therefore cannot freeze verse review, and the latest outbound Bridge
reference remains queued for reconnect. Echoes, stale settling observations, duplicate polls, and
same-context rejected jumps are suppressed. A per-Windows-user mutex prevents two Bridge windows
from driving the desktop applications simultaneously. Incoming navigation is rejected while a
verse edit is active, and invalid cross-book destinations restore the prior Bridge location.

The new Settings → Connections pane controls Paratext and Logos independently and reports live
connection/reference/error state; the top bar exposes the same state compactly. Automated gates
cover non-blocking behavior, both navigation directions, rejection retry semantics, ownership,
and reconnect catch-up.

Live Paratext acceptance read IRVTam at PHP 1:3 in sync group B and a same-reference outbound
request returned `reference_set_by_bridge` with the expected origin ID. Logos was installed but
closed. That check found and fixed two defects in the older unverified helper: its ProgID is the
documented and locally registered `LogosBibleSoftware.Launcher` (not
`Logos4Lib.LogosLauncher`), and active state uses the documented `GetActivePanel()` plus
`GetCurrentReferencesAndHeadwords()` calls. The real helper now returns clean disconnected state
while Logos is closed.

On 2026-09-04, live Logos 53.1 acceptance exposed a second interop layer issue:
PowerShell's .NET COM wrapper could create the correct launcher but rejected typed return
objects with HRESULT `0x80131165`, even with the Logos type library registered. A bundled
native-`IDispatch` VBScript shim now performs panel/reference traversal and `ExecuteUri`
navigation while the persistent PowerShell helper retains the JSON-lines transport. Live state
read the ESV panel at PHP 1:5, and Bridge-to-Logos navigation to PHP 1:5 round-tripped with API
version 3. The Connections-pane flicker was also fixed by retaining the last connected/error
detail while routine background probes run; failed Bridge-originated publish RPCs now retry.


## Stage 9A.4 follow-up (1 of 3) — a running analysis job disappeared on navigation (2026-09-04)

Picks up the "Stage 9A.4 bug fixes" pass (commit `bcb9a7e`), which was
committed unfinished. That pass made a job's identity content-addressed:
`AnalysisJobManager._analysis_identity()` now hashes project, scope kind,
canonical start/end, per-reference target hashes, target revision, source
resource id/version/hash, provider capability, and a `policyVersions` map
collected from every Stage 5-8 engine/calibration/confidence policy. That
digest is the `analysisFingerprint`; `analysisJob.start` requires the caller
to pass back the fingerprint it resolved and refuses to start when it no
longer matches. The UI (`AnalysisControls.svelte`) was made generation-guarded
to match: out-of-order scope lookups are discarded, and `Run analysis` stays
disabled until the displayed status matches the current selection.

That UI change also added a reactive block calling `changeScope()` whenever
`chapter`/`verse` changes. `changeScope()` unconditionally set `job = null`
and cleared the poll timer. But navigation is exactly what a reviewer does
*while* analysis runs - the QA queue is the work surface, and a
`CURRENT_BOOK` run is long. Clicking any finding therefore killed the poll
and dropped the job from the UI: no stage progress, no **Cancel**, and **Run
analysis** re-enabled - where a second click hit the engine's `Analysis job
<id> is already running` conflict as a raw error string.

Fixed by separating "the job being tracked" from "the latest job for the
displayed scope": `isActive()` gates the three places that could replace it
(`changeScope`, `refreshScopeStatus`, `poll`), so only a terminal job is
replaced by whatever the newly selected scope reports. `poll()` now also
works from a captured snapshot, because `refreshScopeStatus()` could
reassign `job` across its `await` and make the `completed` event fire with
the wrong (or a null) job.

Regression test: `AnalysisControls.test.ts` › "keeps a running book job
visible when current navigation changes" - confirmed to fail on `bcb9a7e` at
the post-navigation assertion with the label and Cancel button gone, and to
pass with the fix.

While there: the range inputs had moved from `on:change` to `on:input`, so
every keystroke fired a scope-status RPC, and clearing a field to retype it
sent an incomplete range that the engine rejects - surfacing "Selected range
requires start and end references" as a red error mid-typing. `isResolvable()`
now withholds the request until all four fields are present, and lookups are
debounced 150ms.

Verified: `npm run check` (0 errors/warnings), `npm run test` (110 passed,
was 109), `npm run build` (succeeds).

## Stage 9A.4 follow-up (2 of 3) — the Logos VBScript shim went silent on any COM hiccup (2026-09-04)

**VBScript scopes `On Error Resume Next` per procedure.** `logos_com.vbs`
(added in `bcb9a7e` to work around PowerShell's .NET COM wrapper rejecting
Logos's typed return values with HRESULT `0x80131165`) set it once at file
scope, so it did *not* cover `Sub EmitState` - every `If Err.Number = 0`
guard inside that Sub was dead code. The first COM error there (a non-Bible
panel active, a panel Logos will not hand over, a build without
`LogosPanel.Kind`) aborted the whole Sub, and execution resumed in the
caller at `WScript.Quit 0`: **exit code 0, nothing printed at all.**
`logos_bridge.ps1` then reported `Native Logos COM shim returned no
response`, so Bridge showed a hard Logos error while Logos was running and
connected. The same path follows a *successful* `ExecuteUri`, so an outbound
navigation that actually worked could still be reported as a failure.

The live 53.1 acceptance in `bcb9a7e` did not catch this because it ran with
an ESV Bible panel active - the one path where nothing throws.

Confirmed by running the real `EmitState` against a `FakeApp` whose
`GetActivePanel()` raises: before, zero output; after, `ok=1 connected=1
api_version=3` with empty book/chapter/verse. `EmitState` now opens with its
own `On Error Resume Next` and clears `Err` before emitting, so a panel with
no Bible reference reports *connected without a reference* rather than
failing.

Regression test: `test_logos_connector.py` ›
`test_state_is_still_reported_when_the_active_panel_raises` (skipped where
`cscript` is unavailable). It lifts the real `Sub EmitState` out of the
shipped `.vbs` rather than copying it, so it tracks the file it guards.
Confirmed to fail against `bcb9a7e` ("EmitState went silent") and pass with
the fix.

Still open:
- Not re-verified against a live Logos session or a frozen sidecar build:
  the shim fix is proven against a fault-injected `EmitState`, but
  `build-sidecars.ps1` + `scripts/smoke_sidecars.py` and a real Logos 53.1
  panel-switch acceptance still need a run on a machine with Logos installed.
- `bridge_to_logos_uri()` upper-cases the whole reference, so a lettered
  verse segment becomes `logosref:Bible.Php1.3A` rather than the
  conventional lowercase `...3a`. Whether Logos accepts the upper-case form
  is unverified - left alone deliberately rather than guessed at.

Verified: `pytest tests/ greek_room_engine/tests/ -q` (589 passed, was 588).

## Stage 9A.4 follow-up (3 of 3) — bounded the Bridge navigation publish retry (2026-09-04)

`App.svelte`'s navigation-publish retry (added in `bcb9a7e` alongside the
fingerprinting work) cleared `lastNavigationReference` on failure to re-enter
the reactive publish block, with no attempt counter - a persistently failing
`navigation.bridgeChanged` call would have spun one RPC every 800ms for the
rest of the session. Capped at 3 attempts per reference, reset on success or
when the reference changes.

Verified: `npm run check`, `npm run test`, `npm run build` all still pass.

## AI review never auto-selected tN/tW words — two Stage 3 defects (2026-09-04)

Reported as "running the AI check still isn't auto-selecting the words, it's
still showing Pending". Diagnosed against the reporter's own saved reviews
under `<project>/.apps/translationCoreAI/aiReview/<book>/<ch>/<vs>.json`,
which persist `selection_state`, `semantic_mapping` and the Stage 3 pack —
so the failure is reconstructable offline, with no API key and no rerun.

Aggregate over the 53 saved reviews on that machine: 70 checks ended
`mapping_error` against 9 `found_this_verse`, and 9 of the 12 most recent
Stage 3 packs had `mappings: []`. **Two independent bugs, either one alone
enough to leave every check Pending.**

### 1. One bad model row discarded the whole batch

`SemanticMappingEngine._validate_result` raised on the first offending
mapping row, so a single unusable row threw away every *other* unit's
perfectly good mapping in the same call.
`prepare_semantic_mappings_for_review` then caught that and — correctly, for
the transport/schema failure its comment describes — marked *every* unit
`mapping_error`, which `apply_semantic_review_policy` treats as `_UNRESOLVED`
and clears the proposal for. One hallucinated target quote therefore took out
an entire verse.

PHP 1:6 is the clean example: all 10 checkStates carry the identical detail
`Target quote for translationNotes:qhmh ... was not found as an unambiguous
exact match`, i.e. nine checks were failed by a tenth check's row. The
observed triggers were all single-row: a hallucinated/ambiguous quote (×3),
`Model changed canonical source token IDs` (×3), `Model returned unknown
source unit` (×1).

Row validation moved into `_validate_mapping_row`; the caller catches
`SemanticMappingValidationError` and quarantines that unit as unresolved, so
the adaptive search retries it on the next layer while every accepted mapping
survives. `_MappingRowRejected` carries a per-row `reason` (`AMBIGUOUS` for
the quote case). Unattributable rows — unknown or duplicated `source_unit_id`,
either list — are dropped rather than fatal; the `missing` backstop still
catches any unit that goes unmentioned. A unit the model both maps and
unresolves now fails closed: the mapping is withdrawn and the unit stays
pending. Only genuine top-level schema breaks still raise.

Quarantined units land as `needs_extended_passage_review`, which is still
`_UNRESOLVED` — so that one check stays Pending, as it should, and the rest
of the verse proceeds.

### 2. The auto-apply gate compared clause spans to word tokens

Independent of #1, and the reason even a *clean* Stage 3 run selected
nothing. `semantic_review_policy.native_tc_apply_allowed` required the
proposed translationCore selections to equal the verified Stage 3 target
spans (`selection_text == span_quotes`, or a single span joined from every
selection). Those are different granularities and essentially never equal: a
Stage 3 span is the clause the meaning is realized in, a tC selection is the
word tokens inside it. So `_safe_ai_selection_reason` returned "Stage 3
mapping is not safe for a verse-local automatic selection" for every mapped
check.

PHP 1:19 is the proof — Stage 3 `ready`, 8 checks `found_this_verse` /
`PRESERVED` / confidence 1.0, and zero selections on disk. E.g. proposed
`["यीशु", "मसीह"]` against span `"यीशु मसीह की आत्माके दान के द्वारा,"`.

Replaced with containment: each proposed token must fall inside a verified
span for this verse. Substring containment is deliberate — it also admits the
compounded/suffixed target forms the review prompt explicitly asks the model
to select (`आत्मा` within `आत्माके`). It does not weaken the anti-hallucination
guard: the token comes from a supplied bottomWord ID (already checked against
`known_ids`), `validate_check_selection` re-verifies its occurrence against
the verse text, and `save_check_selection` still refuses to overwrite
imported/human choices.

Re-running the real gate over the untouched PHP 1:19 record: 8 of 9 checks
now APPLY, the 9th correctly skipped as `target_not_located` + verdict
`review`. Before: 0 of 9.

### Note for anyone reproducing this

`start_ai_review_job` skips verses whose cached review is `current`, so
chapter/book scope will *not* revisit a verse already reviewed under the
broken behaviour — it reports them as skipped-because-current. Rerun at
**verse** scope (which never skips) to see the fix on an
already-reviewed verse. Verses hit by bug #1 need a fresh model call either
way; their stored `mapping_error` states are what they are.

`skippedSelections` still carries a per-check `reason` all the way to the
frontend (`AIReviewResult` in `types/finding.ts`) and nothing renders it —
which is why this presented as a silent "nothing happened". Surfacing it is
not done.

Regression tests (`tests/test_semantic_mapping_stage3.py`):
`test_one_rejected_row_does_not_discard_the_rest_of_the_batch`,
`test_word_selections_inside_a_clause_span_are_applicable`, and
`test_hallucinated_target_quote_is_rejected` rewritten — it asserted the
old whole-batch abort, and now asserts the stronger invariant it was
protecting: the hallucinated quote never becomes a mapping and the unit ends
unresolved, never an omission.

Verified: `pytest tests/ greek_room_engine/tests/ -q` (597 passed).
Not verified in the running desktop app — that needs a real API key and a
live rerun.

## Surfaced the automatic-selection outcome in the UI (2026-09-04)

Follow-up to the two Stage 3 defects above. The engine had always decided, per
check, whether it could select the target words automatically and — when it
could not — why; `_safe_ai_selection_reason` returns real sentences ("AI
confidence is below the 82% automatic-selection threshold", "Contradictory QA
evidence requires human review"). Nothing rendered them, so a check the AI
deliberately declined was visually identical to one no AI had ever seen: the
same bare "Pending" pill. That is the direct reason the two bugs above read as
"the AI check does nothing" rather than as a specific, diagnosable refusal.

`appliedSelections` / `skippedSelections` were also the wrong carrier for this:
they ride along with one verse's job result, and `latestResult` holds only the
most recent verse — so on a chapter run the reasons for every earlier verse
were already gone, and navigating away lost them entirely.

**Persisted instead.** `TranslationCoreProject.record_ai_selection_outcomes`
merges an `automaticSelection` map (`"<tool>:<checkId>" -> {outcome, reason}`)
into the saved AI review record, written at the end of
`_apply_safe_ai_selections` — after `rebase_ai_review_fingerprint`, since both
rewrite that file. `list_checks_for_verse` reads it back onto each check row, so
the question survives navigation and app restart.

`_check_review_from_entry` declares `automaticSelection: None` as its default.
Without it a row returned by `save_check_selection` would be missing the field
the UI reads — and that default is also correct on its own terms: a human who
has just saved over a selection is no longer described by the AI's outcome.

UI, all in the two places a reviewer is already looking:
- `TranslationHelpsReview` — per check, "✓ Selected automatically by the AI
  review" (guarded on `provenance === "bridge_ai"`, so a human takeover drops
  the claim) or "Left for you — <engine's own reason>" on a still-pending
  check. Reasons render verbatim; re-mapping them in TypeScript would be a
  second copy of the policy, free to drift from the engine's.
- A verse summary bar replacing the old unconditional notice: "N of M checks
  complete · K selected by AI review" / "J pending". Green once nothing is
  pending.
- `ReviewPanel`'s job status gains a run-wide roll-up from the counts already
  in the snapshot (`appliedCount`/`skippedCount` per verse) — the "how much did
  it actually do" answer for a chapter or book pass, where no single verse is
  on screen.

Tests: `test_ai_explain.py` ›
`test_automatic_selection_outcome_survives_the_job_result` reads the verse back
through `check.listForVerse` with no job snapshot in hand and asserts every
applied/skipped row's reason round-trips. New
`__tests__/TranslationHelpsReview.test.ts` (4 tests) covers the declined-reason
line, the applied marker plus tally, the human-takeover case, and the unchanged
"run AI review" prompt when no automatic pass has run.

Verified: `pytest tests/ greek_room_engine/tests/ -q` (598 passed),
`npm run check` (0/0), `npm run test` (127 passed), `npm run build`.
Not verified in the running desktop app.
